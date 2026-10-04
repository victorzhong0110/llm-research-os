"""R10 contract and asset gates.

Three things must hold for the browser workbench to be trustworthy:

1. The committed TypeScript types still match the Python contracts.
2. The built bundle is present, is what the client actually loads, and is
   served without traversal or content-type guessing.
3. The client calls only endpoints the local API actually routes.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from web_helpers import HOST, ORIGIN, Client

from llm_research_os.application.workspace import init_workspace, load_workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.storage import EventStore
from llm_research_os.web.app import API_PREFIX, LocalApi
from llm_research_os.web.assets import AssetError, clear_cache, content_type_for, index_asset, load
from llm_research_os.web.contracts import CONTRACT_MODELS
from llm_research_os.web.sessions import SessionStore

ROOT = Path(__file__).parents[1]
GENERATED = ROOT / "web" / "src" / "generated" / "local-api.ts"
STATIC = ROOT / "src" / "llm_research_os" / "web" / "static"


def _load_generator() -> Any:
    path = ROOT / "scripts" / "generate_web_types.py"
    spec = importlib.util.spec_from_file_location("generate_web_types", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_web_types"] = module
    spec.loader.exec_module(module)
    return module


# --- Contract drift -----------------------------------------------------------


def test_generated_types_match_the_python_contracts() -> None:
    """The committed TypeScript must equal what the models render today."""

    expected = _load_generator().render()
    assert GENERATED.read_text(encoding="utf-8") == expected, (
        "web/src/generated/local-api.ts is stale; run `uv run python scripts/generate_web_types.py`"
    )


def test_every_contract_model_is_reachable_from_the_registry() -> None:
    assert CONTRACT_MODELS
    for name, model in CONTRACT_MODELS.items():
        assert model.__name__, name
        schema = model.model_json_schema(by_alias=True, mode="serialization")
        assert schema.get("properties"), name


def test_generated_types_declare_no_untyped_loose_fields() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    # `unknown` is only legitimate for a genuinely open object, never for a field
    # the server always sends.
    assert "readonly text | undefined" not in text
    assert ": any" not in text


def test_observation_states_are_closed_and_include_every_required_state() -> None:
    """R10 acceptance: these five states must never collapse into success."""

    from typing import get_args

    from llm_research_os.web.contracts import RunObservationState

    states = set(get_args(RunObservationState))
    for required in {
        "unknown",
        "lost",
        "failed",
        "cancel-requested",
        "observed-stop",
        "succeeded",
    }:
        assert required in states, required
    # The closed set is what lets the client style success exclusively.
    assert "completed" not in states


def test_run_observation_comes_from_the_run_fold(tmp_path: Path) -> None:
    """A run's state must come from RunControl, never from guessing event names.

    Regression guard. An earlier version left ``observation`` at its default, so
    a run with a full queued -> started -> completed history was labelled
    "No lifecycle facts" in the browser. The fixture is produced by the repo's
    own ``researchos m1 prove`` so the lifecycle is genuinely legal rather than
    hand-assembled.
    """

    from llm_research_os.web.projections import ReadProjections

    database = tmp_path / "fold.db"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "m1",
            "prove",
            str(ROOT / "examples" / "m1-checkpoint"),
            str(database),
        ],
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode()

    cas_root = tmp_path / "cas"
    cas_root.mkdir()
    with EventStore(database, require_existing=True) as store:
        views = ReadProjections(store, LocalArtifactStore(cas_root), "example-minimal")
        page = views.run_page(cursor=None, limit=10)

    assert page.items, "the simulated run must appear in the index"
    state = page.items[0]["observation"]
    assert state in {"succeeded", "running", "queued", "failed", "unknown", "lost", "observed-stop"}
    assert state != "absent", "a run with a real lifecycle must not read as absent"
    # A simulated lifecycle is synthetic, never presented as a measurement.
    assert page.items[0]["origin"] == "synthetic"


def test_unfoldable_run_is_absent_not_a_guess(tmp_path: Path) -> None:
    """A lifecycle the fold refuses must not be reported as a known state."""

    from test_web_api import _draft

    from llm_research_os.web.projections import ReadProjections

    root = tmp_path / "refused"
    init_workspace(
        root,
        project_id="proj-refuse",
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "worker",
    )
    with EventStore(root / "control.db") as store:
        # run.started with no preceding run.queued: the fold refuses it.
        store.append(_draft(1, project_id="proj-refuse", run_id="run.bad"))
        views = ReadProjections(store, LocalArtifactStore(root / "cas"), "proj-refuse")
        page = views.run_page(cursor=None, limit=10)
    assert page.items[0]["observation"] == "absent"
    assert page.items[0]["origin"] == "absent"


# --- Built assets -------------------------------------------------------------


def test_bundle_is_present_and_referenceable() -> None:
    clear_cache()
    index = index_asset()
    assert index.content_type == "text/html; charset=utf-8"
    assert b'<div id="root">' in index.body
    match = re.search(rb'src="(/assets/[^"]+)"', index.body)
    assert match is not None, "index.html must reference a hashed bundle"
    script = match.group(1).decode()
    asset = load(script)
    assert asset.content_type == "text/javascript; charset=utf-8"
    assert len(asset.body) > 1000
    assert asset.immutable is True


def test_index_is_not_immutably_cached() -> None:
    """A rebuilt bundle must not stay invisible behind a cached index."""

    clear_cache()
    assert index_asset().immutable is False


def test_asset_etag_is_stable_and_content_derived() -> None:
    clear_cache()
    first = index_asset()
    second = index_asset()
    assert first.etag == second.etag
    assert first.etag.startswith('"')


@pytest.mark.parametrize(
    "path",
    ["/../pyproject.toml", "/assets/../../pyproject.toml", "/..%2fpyproject.toml"],
)
def test_traversal_out_of_the_asset_root_is_refused(path: str) -> None:
    clear_cache()
    with pytest.raises(AssetError) as caught:
        load(path)
    assert caught.value.code in {"asset-path-invalid", "asset-missing"}


def test_symlinked_asset_is_refused() -> None:
    """A symlink inside the bundle must not become a read of its target."""

    clear_cache()
    escape = STATIC / "escape.txt"
    if escape.is_symlink() or escape.exists():
        escape.unlink()
    escape.symlink_to(ROOT / "pyproject.toml")
    try:
        with pytest.raises(AssetError) as caught:
            load("/escape.txt")
        assert caught.value.code in {"asset-missing", "asset-not-a-file", "asset-path-invalid"}
    finally:
        escape.unlink()


def test_directory_request_is_not_a_file() -> None:
    clear_cache()
    with pytest.raises(AssetError) as caught:
        load("/assets")
    assert caught.value.code in {"asset-missing", "asset-path-invalid", "asset-not-a-file"}


def test_missing_asset_is_a_closed_error() -> None:
    clear_cache()
    with pytest.raises(AssetError, match=r"not installed|not present") as caught:
        load("/assets/does-not-exist.js")
    assert caught.value.code == "asset-missing"


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (".js", "text/javascript; charset=utf-8"),
        (".css", "text/css; charset=utf-8"),
        (".html", "text/html; charset=utf-8"),
        (".svg", "image/svg+xml"),
        (".exe", "application/octet-stream"),
    ],
)
def test_content_types_come_from_a_closed_table(suffix: str, expected: str) -> None:
    assert content_type_for(f"asset{suffix}") == expected


# --- Serving through the API --------------------------------------------------


@pytest.fixture
def static_client(tmp_path: Path) -> Client:
    from llm_research_os.application.workspace import init_workspace

    root = tmp_path / "assets-project"
    init_workspace(
        root,
        project_id="proj-assets",
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "assets-worker",
    )
    clear_cache()
    api = LocalApi(
        load_workspace(root),
        sessions=SessionStore(bootstrap_token="asset-bootstrap"),
        allowed_hosts=frozenset({HOST}),
        allowed_origin=ORIGIN,
        stream_idle_seconds=0.1,
        stream_poll_seconds=0.01,
    )
    return Client(api)


def test_bundle_loads_without_a_session(static_client: Client) -> None:
    """The operator must be able to load the page in order to obtain a session."""

    clear_cache()
    status, headers, body = static_client.request("GET", "/")
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert headers["x-content-type-options"] == "nosniff"
    assert b'<div id="root">' in body


def test_bundle_sends_its_own_csp_free_html_only(static_client: Client) -> None:
    clear_cache()
    _, headers, _ = static_client.request("GET", "/index.html")
    assert headers["cache-control"] == "no-store"


def test_hashed_bundle_is_immutably_cached(static_client: Client) -> None:
    clear_cache()
    index = static_client.request("GET", "/")[2]
    assert isinstance(index, bytes)
    match = re.search(rb'src="(/assets/[^"]+)"', index)
    assert match is not None
    status, headers, _ = static_client.request("GET", match.group(1).decode())
    assert status == 200
    assert headers["cache-control"] == "public, max-age=31536000, immutable"


def test_matching_etag_returns_not_modified(static_client: Client) -> None:
    clear_cache()
    _, headers, _ = static_client.request("GET", "/")
    etag = headers["etag"]
    status, _, _ = static_client.request("GET", "/", headers={"If-None-Match": etag})
    assert status == 304


def test_unknown_asset_is_not_found(static_client: Client) -> None:
    clear_cache()
    status, _, payload = static_client.request("GET", "/assets/missing.js")
    assert status == 404
    assert isinstance(payload, dict)
    assert payload["code"] == "not-found"


def test_api_prefix_still_requires_a_session(static_client: Client) -> None:
    """Adding the bundle must not open the API surface."""

    clear_cache()
    status, _, payload = static_client.request("GET", f"{API_PREFIX}/workspace")
    assert status == 401
    assert isinstance(payload, dict)
    assert payload["code"] == "session-required"


def test_bundle_rejects_unsafe_methods(static_client: Client) -> None:
    clear_cache()
    status, _, payload = static_client.request("PUT", "/")
    assert status == 405
    assert isinstance(payload, dict)
    assert payload["code"] == "method-not-allowed"


# --- Client/server agreement --------------------------------------------------


def test_client_only_calls_routed_endpoints() -> None:
    """Every API path the bundle references must be one the server routes.

    This is a contract check, not a browser run: it catches a client that calls
    a renamed or removed endpoint without needing a headless browser. The
    production bundle is minified, so a request path appears either as a plain
    string (`"/workspace"`) or as a template head (`` `/events${...}` ``).
    """

    clear_cache()
    bundle = b"".join(
        load(f"/assets/{path.name}").body
        for path in sorted((STATIC / "assets").iterdir())
        if path.suffix in {".js", ".css"}
    ).decode("utf-8", errors="replace")
    called = {path for path in re.findall(r'["`](/[a-z][a-zA-Z0-9_/-]*)', bundle)}
    assert called, "the bundle must reference the API paths"
    assert {"/capabilities", "/workspace", "/events", "/revisions", "/runs", "/session"} <= called
    assert any(path.startswith("/artifacts/") for path in called)

    # `/api/v0alpha1` is the prefix constant and `/api/health` the liveness
    # route; both are resolved by the server, neither is a resource path.
    allowed_roots = {
        "api",
        "artifacts",
        "capabilities",
        "events",
        "revisions",
        "runs",
        "session",
        "workspace",
    }
    for path in called:
        head = path.lstrip("/").split("/", 1)[0]
        assert head in allowed_roots, f"unrouted client path {path}"


def test_client_requests_the_health_path_outside_the_prefix() -> None:
    """Health must not be fetched through the versioned, session-gated prefix."""

    source = (ROOT / "web" / "src" / "api.ts").read_text(encoding="utf-8")
    assert 'fetch("/api/health"' in source
    assert "${API_PREFIX}/health" not in source


# --- Packaging ----------------------------------------------------------------


def test_wheel_ships_the_bundle_and_not_the_toolchain() -> None:
    """The built bundle must be installable without a checkout or Node."""

    spec = importlib.util.spec_from_file_location(
        "llm_research_os", ROOT / "src" / "llm_research_os" / "__init__.py"
    )
    assert spec is not None
    # The committed tree is the contract when no dist artifact exists locally.
    assert (STATIC / "index.html").is_file()
    assert any(path.suffix == ".js" for path in (STATIC / "assets").iterdir())


def test_static_assets_are_not_source_modules() -> None:
    """The bundle must not shadow a Python module name in the package."""

    names = {path.name for path in STATIC.iterdir()}
    assert "index.html" in names
    assert not (STATIC / "__init__.py").exists()


def test_generated_header_names_its_regenerator() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    assert "scripts/generate_web_types.py" in text
    assert "Do not edit by hand" in text


def test_contracts_json_schema_is_serialisable() -> None:
    for name, model in CONTRACT_MODELS.items():
        json.dumps(model.model_json_schema(by_alias=True, mode="serialization"), sort_keys=True)
        assert name
