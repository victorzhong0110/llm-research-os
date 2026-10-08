"""Actual reviewed evaluator, persistent CLI and refusal boundaries."""

import json
from pathlib import Path

import pytest

from llm_research_os.application.workspace import init_workspace
from llm_research_os.cli import main
from llm_research_os.evaluation.iris import main as iris_main
from llm_research_os.extensions.manifest import ExtensionError
from llm_research_os.extensions.package import existing_cpu_evaluator, parse_package
from llm_research_os.extensions.persistent import PersistentExtensions


@pytest.fixture
def root(tmp_path: Path) -> Path:
    init_workspace(
        tmp_path,
        project_id="project.extensions",
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )
    return tmp_path


def test_existing_evaluator_runs_exact_cpu_output_and_disable_survives_restart(root: Path) -> None:
    registry = PersistentExtensions(root)
    package = parse_package(existing_cpu_evaluator())
    registry.install_package(package, trust="reviewed-same-user")
    result = PersistentExtensions(root).run(
        "researchos.pinned-iris", "1.0.0", "evaluator", {"task": "pinned-iris"}
    )
    assert result["response"]["payload"] == iris_main()
    assert len(result["response"]["payload"]["predictions"]) == 20
    assert not (root / "control/events.sqlite").exists()
    assert list((root / "cas").iterdir()) == []
    registry.change("researchos.pinned-iris", "1.0.0", "disable")
    with pytest.raises(ExtensionError, match="disabled"):
        PersistentExtensions(root).run("researchos.pinned-iris", "1.0.0", "evaluator", {})
    registry.change("researchos.pinned-iris", "1.0.0", "uninstall")
    assert PersistentExtensions(root).inspect()["installed"] == []


def test_inert_install_and_unknown_trust_never_dispatch(root: Path) -> None:
    document = existing_cpu_evaluator()
    document["manifest"]["entryModule"] = "raise AssertionError('must not execute')"
    registry = PersistentExtensions(root)
    with pytest.raises(ExtensionError, match="verified isolation"):
        registry.install_package(parse_package(document), trust="untrusted")
    registry.install_package(parse_package(document))
    with pytest.raises(ExtensionError, match="inert"):
        registry.run("researchos.pinned-iris", "1.0.0", "evaluator", {})


@pytest.mark.parametrize("change", ["interface", "host", "permission", "dependency"])
def test_incompatible_declarations_leave_registry_empty(root: Path, change: str) -> None:
    document = existing_cpu_evaluator()
    if change == "interface":
        document["interfaces"][0]["version"] = "v999"
    elif change == "host":
        document["hostContracts"] = ["v999"]
    elif change == "permission":
        document["manifest"]["permissions"] = ["workers.launch"]
    else:
        document["dependencies"] = [{"id": "missing", "version": "1"}]
    registry = PersistentExtensions(root)
    with pytest.raises(ExtensionError):
        registry.install_package(parse_package(document), trust="reviewed-same-user")
    assert registry.inspect()["installed"] == []


def test_disabling_dependency_blocks_future_dispatch(root: Path) -> None:
    registry = PersistentExtensions(root)
    base = existing_cpu_evaluator()
    registry.install_package(parse_package(base))
    dependent = existing_cpu_evaluator()
    dependent["manifest"]["id"] = "dependent"
    dependent["dependencies"] = [{"id": "researchos.pinned-iris", "version": "1.0.0"}]
    registry.install_package(parse_package(dependent), trust="reviewed-same-user")
    registry.change("researchos.pinned-iris", "1.0.0", "disable")
    assert PersistentExtensions(root).inspect()["missingDependencies"]
    with pytest.raises(ExtensionError, match="dependency"):
        registry.run("dependent", "1.0.0", "evaluator", {})


@pytest.mark.parametrize(
    "entry",
    ["print('not-json')", 'print(\'{"kind":"ProviderOutput","version":"v0alpha1","payload":{}}\')'],
)
def test_wrong_response_is_closed(root: Path, entry: str) -> None:
    document = existing_cpu_evaluator()
    document["manifest"]["entryModule"] = entry
    registry = PersistentExtensions(root)
    registry.install_package(parse_package(document), trust="reviewed-same-user")
    with pytest.raises(ExtensionError, match="response"):
        registry.run("researchos.pinned-iris", "1.0.0", "evaluator", {})
    assert not (root / "control/events.sqlite").exists()


def test_cli_persists_install_inspect_disable_uninstall(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prefix = ["extensions"]
    assert main([*prefix, "install-cpu-example", "--root", str(root)]) == 0
    assert main([*prefix, "inspect", "--root", str(root)]) == 0
    capsys.readouterr()
    for action in ["disable", "enable", "uninstall"]:
        assert (
            main(
                [
                    *prefix,
                    action,
                    "--root",
                    str(root),
                    "--id",
                    "researchos.pinned-iris",
                    "--version",
                    "1.0.0",
                ]
            )
            == 0
        )
        output = json.loads(capsys.readouterr().out)
        if action == "uninstall":
            assert output["installed"] == []


def test_unknown_registry_schema_is_refused_without_writes(root: Path) -> None:
    import sqlite3

    PersistentExtensions(root)
    path = root / "extensions.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER changed AFTER INSERT ON extensions BEGIN SELECT 1; END")
    before = path.read_bytes()
    with pytest.raises(ExtensionError, match="structure"):
        PersistentExtensions(root)
    assert path.read_bytes() == before


def test_loading_duplicate_or_symlink_package_is_inert(root: Path) -> None:
    from llm_research_os.extensions.package import load_package

    path = root / "package.json"
    path.write_text('{"kind":"ExtensionPackage","kind":"ExtensionPackage"}')
    with pytest.raises(ExtensionError):
        load_package(path)
    link = root / "link.json"
    link.symlink_to(path)
    with pytest.raises(ExtensionError):
        load_package(link)
