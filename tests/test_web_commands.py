"""R11: browser-driven commands through the shared idempotent services.

The acceptance bar is that a duplicate click, a retransmission, a second window
or an uncertain HTTP response cannot append a second fact, and that an accepted
request is never presented as an observed process outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from web_helpers import ORIGIN, Client

from llm_research_os.application.workspace import init_workspace, load_workspace
from llm_research_os.runs.cancellation import load_run_cancellation_request
from llm_research_os.web.app import LocalApi
from llm_research_os.web.sessions import SessionStore

PREFIX = "/api/v0alpha1"
BOOTSTRAP = "r11-bootstrap"
PROJECT = "example-minimal"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ops"
    init_workspace(
        root,
        project_id=PROJECT,
        control_db=root / "control.db",
        cas_root=root / "cas",
        worker_root=tmp_path / "ops-worker",
    )
    _seed(root / "control.db")
    return root


@pytest.fixture
def client(workspace: Path) -> Client:
    api = LocalApi(
        load_workspace(workspace),
        sessions=SessionStore(bootstrap_token=BOOTSTRAP),
        allowed_hosts=frozenset({"127.0.0.1:8787"}),
        allowed_origin=ORIGIN,
        stream_idle_seconds=0.1,
        stream_poll_seconds=0.01,
    )
    instance = Client(api)
    instance.bootstrap(BOOTSTRAP)
    return instance


def _seed(database: Path) -> None:
    """Seed a genuinely running Run using the repository's own fixture.

    Reusing the existing cancellation fixture keeps the lifecycle legal: a
    terminal Run cannot be reopened, so a completed Run would only ever prove
    that cancellation is refused, not that a request is recorded honestly.
    """

    from test_run_cancel_cli import _seed_running

    _seed_running(database)


def _command(
    *,
    command_id: str,
    operation: dict[str, Any],
    actor: str = "operator",
    submitted_at: str = "2026-10-04T10:00:00+08:00",
    expected_head: int | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": command_id,
        "actorId": actor,
        "submittedAt": submitted_at,
        "operation": operation,
    }
    if expected_head is not None:
        document["expectedHead"] = expected_head
    if expected_revision is not None:
        document["expectedRevision"] = expected_revision
    return document


def _head(client: Client) -> int:
    """The project's current high-water mark, as the UI would read it."""

    status, _headers, payload = client.request("GET", f"{PREFIX}/workspace")
    assert status == 200
    return int(payload["highWaterMark"])


def _submit(client: Client, document: dict[str, Any]) -> tuple[int, Any]:
    status, _headers, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=json.dumps(document).encode("utf-8"),
        content_type="application/json",
        origin=ORIGIN,
    )
    return status, payload


# --- Idempotency --------------------------------------------------------------


def test_repeated_command_replays_the_same_receipt(client: Client, tmp_path: Path) -> None:
    """A double-click must not append a second fact."""

    request = _write_cancel_request(tmp_path)
    document = _command(
        command_id="cmd.cancel.1",
        operation={"kind": "run.cancel", "request": str(request)},
        expected_head=_head(client),
    )
    first_status, first = _submit(client, document)
    second_status, second = _submit(client, document)
    assert first_status == 200
    assert second_status == 200
    assert first["commandId"] == second["commandId"]
    assert first["disposition"] == "committed"
    assert second["disposition"] == "replayed"
    assert first["resultDigest"] == second["resultDigest"]


def test_same_identity_with_different_content_is_refused(client: Client, tmp_path: Path) -> None:
    """A reused commandId with new content is a conflict, not a silent replay."""

    first_request = _write_cancel_request(tmp_path)
    second_request = _write_cancel_request(tmp_path, suffix="2", event_id="evt.cancel.2")
    _submit(
        client,
        _command(
            command_id="cmd.conflict",
            operation={"kind": "run.cancel", "request": str(first_request)},
            expected_head=_head(client),
        ),
    )
    status, payload = _submit(
        client,
        _command(
            command_id="cmd.conflict",
            operation={"kind": "run.cancel", "request": str(second_request)},
            expected_head=_head(client) + 1,
        ),
    )
    assert status == 409
    assert payload["code"] == "command-refused"


def test_two_windows_do_not_duplicate_a_fact(client: Client, tmp_path: Path) -> None:
    """A second window sending the same command must replay, not append."""

    request = _write_cancel_request(tmp_path)
    document = _command(
        command_id="cmd.windows",
        operation={"kind": "run.cancel", "request": str(request)},
        expected_head=_head(client),
    )
    _submit(client, document)
    status, payload = _submit(client.fork(), document)
    assert status == 200
    assert payload["disposition"] == "replayed"


# --- Honesty ------------------------------------------------------------------


def test_cancel_receipt_is_a_request_not_an_observed_stop(client: Client, tmp_path: Path) -> None:
    """Accepting a cancellation must not be reported as process completion."""

    request = _write_cancel_request(tmp_path)
    status, payload = _submit(
        client,
        _command(
            command_id="cmd.cancel.honest",
            operation={"kind": "run.cancel", "request": str(request)},
            expected_head=_head(client),
        ),
    )
    assert status == 200
    result = payload["result"]
    assert result["disposition"] == "cancel-requested"
    assert result["observedStop"] is False
    assert "no process outcome is claimed" in result["note"].lower()


def test_preflight_never_reports_launch_allowed(client: Client) -> None:
    """A preflight is not a launch credential."""

    spec = Path(__file__).parents[1] / "examples" / "m1-checkpoint" / "spec.yaml"
    status, payload = _submit(
        client,
        _command(
            command_id="cmd.preflight.1",
            operation={"kind": "plan.preflight", "document": str(spec)},
            expected_revision=1,
        ),
    )
    assert status == 200
    result = payload["result"]
    assert result["launchAllowed"] is False
    assert result["planIdentity"]["projectId"] == PROJECT
    assert result["enforcedLimits"]["decodedNodes"] > 0
    assert "not enforced by a preflight" in result["resourceRequirements"]
    assert "no reservation is made" in result["budgetRequirement"]


def test_stale_plan_is_refused(client: Client) -> None:
    """A stale expected revision must fail visibly rather than re-validate."""

    spec = Path(__file__).parents[1] / "examples" / "m1-checkpoint" / "spec.yaml"
    status, payload = _submit(
        client,
        _command(
            command_id="cmd.preflight.stale",
            operation={"kind": "plan.preflight", "document": str(spec)},
            expected_revision=99,
        ),
    )
    assert status == 409
    assert payload["code"] == "command-refused"


def test_revoke_reports_revoked_without_launching(client: Client) -> None:
    status, payload = _submit(
        client,
        _command(
            command_id="cmd.revoke.unknown",
            operation={
                "kind": "authorization.revoke",
                "grantId": "grant.does-not-exist",
                "eventId": "evt.revoke.1",
            },
            expected_head=_head(client),
        ),
    )
    assert status == 409
    assert payload["code"] == "command-refused"


# --- Browser authority boundary -----------------------------------------------


def test_commands_require_a_session(client: Client) -> None:
    stranger = client.fork(session=False)
    status, _headers, payload = stranger.request(
        "POST",
        f"{PREFIX}/commands",
        body=b"{}",
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 401
    assert isinstance(payload, dict)
    assert payload["code"] == "session-required"


def test_commands_require_csrf_and_same_origin(client: Client, tmp_path: Path) -> None:
    request = _write_cancel_request(tmp_path / "requests")
    document = _command(
        command_id="cmd.csrf",
        operation={"kind": "run.cancel", "request": str(request)},
        expected_head=_head(client),
    )
    body = json.dumps(document).encode("utf-8")
    client.csrf = None
    status, _, payload = client.request(
        "POST", f"{PREFIX}/commands", body=body, content_type="application/json", origin=ORIGIN
    )
    assert status == 403
    assert payload["code"] == "csrf-invalid"

    client.csrf = "wrong"
    status, _, payload = client.request(
        "POST", f"{PREFIX}/commands", body=body, content_type="application/json", origin=ORIGIN
    )
    assert status == 403
    assert payload["code"] == "csrf-invalid"

    client.csrf = _valid_csrf(client)
    status, _, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=body,
        content_type="application/json",
        origin="http://evil.example",
    )
    assert status == 403
    assert payload["code"] == "origin-forbidden"


def test_invalid_command_document_is_refused(client: Client) -> None:
    status, payload = _submit(client, {"kind": "not-a-command"})
    assert status == 400
    assert payload["code"] == "document-invalid"


def test_oversized_command_body_is_refused(client: Client) -> None:
    document = _command(
        command_id="cmd.big",
        operation={"kind": "plan.preflight", "document": "x" * 2_000_000},
    )
    status, payload = _submit(client, document)
    assert status == 400
    assert payload["code"] in {"body-too-large", "document-invalid"}


def test_get_on_commands_is_not_allowed(client: Client) -> None:
    status, _, payload = client.request("GET", f"{PREFIX}/commands")
    assert status == 405
    assert payload["code"] == "method-not-allowed"


def _valid_csrf(client: Client) -> str:
    status, _headers, payload = client.request("GET", f"{PREFIX}/session")
    assert status == 200
    return str(payload["csrfToken"])


def _write_cancel_request(
    tmp_path: Path, *, suffix: str = "1", event_id: str = "evt.cancel.1"
) -> Path:
    """Write a real cancellation request document the service will accept.

    The shape mirrors the repository's own ``examples/run-cancellation-requests``
    fixtures so the frozen document passes the production validator.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    request = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "RunCancellationRequest",
        "projectId": PROJECT,
        "experimentRevision": 1,
        "runId": "run.simulated",
        "target": {"kind": "run"},
        "reasonCode": "human.request",
        "source": "//researchos.dev/projects/local",
        "subject": f"runs/run.simulated/{suffix}",
        "streamid": "project.example-minimal",
        "actor": {"id": "operator"},
        "event": {"id": event_id, "time": "2026-10-04T10:00:00+08:00"},
        "evidenceRefs": [],
    }
    path = tmp_path / f"cancel-{suffix}.json"
    path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    # Fail early with the real validator rather than inside the request.
    load_run_cancellation_request(path)
    return path
