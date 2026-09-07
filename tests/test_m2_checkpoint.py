from __future__ import annotations

import json
from pathlib import Path

from llm_research_os.cli import main
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples" / "m2-checkpoint"


def test_m2_prove_cli_records_worker_artifact_and_report(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    assert (
        main(
            [
                "m2",
                "prove",
                str(CORPUS),
                str(database),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["kind"] == "M2CheckpointReceipt"
    assert payload["runId"] == "run.worker.cpu"
    assert payload["workerId"] == "worker.loopback.1"
    assert payload["imageDigest"].startswith("sha256:")
    assert payload["artifactDigest"].startswith("sha256:")
    assert "worker.registered" in payload["eventTypes"]
    assert "authorization.grant.recorded" in payload["eventTypes"]
    assert "authorization.grant.consumed" in payload["eventTypes"]
    assert "work.completed" in payload["eventTypes"]
    assert "attempt.succeeded" in payload["eventTypes"]
    assert "run.completed" in payload["eventTypes"]
    with EventStore(database, require_existing=True) as store:
        types = [item.event.type for item in store.read_events(limit=40)]
        assert types == payload["eventTypes"]
    assert (
        main(
            [
                "report",
                payload["runId"],
                "--database",
                str(database),
                "--format",
                "markdown",
            ]
        )
        == 0
    )
    report = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Spec digest" in report
    assert "Registry digest" in report
    assert "Plan digest" in report
    assert "Worker runtime" in report
    assert "Image digest" in report
    assert "Config digest" in report
    assert "Output artifact" in report
    assert payload["imageDigest"] in report
    assert payload["artifactDigest"] in report
    text_db = tmp_path / "text.db"
    text_artifacts = tmp_path / "text-artifacts"
    assert (
        main(
            [
                "m2",
                "prove",
                str(CORPUS),
                str(text_db),
                "--artifacts",
                str(text_artifacts),
            ]
        )
        == 0
    )
    text = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "m2 checkpoint: recorded" in text
    assert "work.completed" in text
    assert payload["runId"] in text


def test_m2_prove_refuses_a_nonempty_store(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    artifacts = tmp_path / "artifacts"
    assert (
        main(
            [
                "m2",
                "prove",
                str(CORPUS),
                str(database),
                "--artifacts",
                str(artifacts),
            ]
        )
        == 0
    )
    capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        main(
            [
                "m2",
                "prove",
                str(CORPUS),
                str(database),
                "--artifacts",
                str(artifacts),
            ]
        )
        == 2
    )
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "store-not-empty" in err


def test_workers_register_and_grants_record_omit_tokens(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert (
        main(
            [
                "workers",
                "register",
                str(CORPUS / "worker.json"),
                str(database),
                "--format",
                "json",
            ]
        )
        == 0
    )
    registered = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert registered["type"] == "worker.registered"
    assert "rg1." not in json.dumps(registered)
    assert (
        main(
            [
                "grants",
                "record",
                str(CORPUS / "spec.yaml"),
                str(CORPUS / "grant.json"),
                str(database),
                "--registry",
                str(CORPUS / "block.json"),
                "--format",
                "json",
            ]
        )
        == 1
    )
    recorded = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "authorization-event-not-found" in recorded
    assert "rg1." not in recorded


def test_workers_register_missing_database_exits_two(tmp_path: Path, capsys: object) -> None:
    assert (
        main(
            [
                "workers",
                "register",
                str(CORPUS / "worker.json"),
                str(tmp_path / "missing.db"),
            ]
        )
        == 2
    )
    capsys.readouterr()  # type: ignore[attr-defined]


def test_workers_register_text_and_invalid_grant_request(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert main(["workers", "register", str(CORPUS / "worker.json"), str(database)]) == 0
    text = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "worker.registered" in text
    bad = tmp_path / "bad-grant.json"
    bad.write_text("{}", encoding="utf-8")
    assert main(["grants", "record", str(CORPUS / "spec.yaml"), str(bad), str(database)]) == 2
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "error:" in err


def test_m2_prove_missing_corpus_exits_two(tmp_path: Path, capsys: object) -> None:
    corpus = tmp_path / "empty-corpus"
    corpus.mkdir()
    assert main(["m2", "prove", str(corpus), str(tmp_path / "research.db")]) == 2
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "missing-corpus-file" in err


def test_grants_record_missing_database_exits_two(tmp_path: Path, capsys: object) -> None:
    assert (
        main(
            [
                "grants",
                "record",
                str(CORPUS / "spec.yaml"),
                str(CORPUS / "grant.json"),
                str(tmp_path / "missing.db"),
                "--registry",
                str(CORPUS / "block.json"),
            ]
        )
        == 2
    )
    capsys.readouterr()  # type: ignore[attr-defined]


def test_grants_record_cli_binds_the_rebuilt_plan(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert (
        main(
            [
                "authorizations",
                "record",
                str(CORPUS / "spec.yaml"),
                str(CORPUS / "authorization-request.json"),
                str(CORPUS / "authorization-event.json"),
                str(database),
                "--registry",
                str(CORPUS / "block.json"),
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        main(
            [
                "workers",
                "register",
                str(CORPUS / "worker.json"),
                str(database),
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        main(
            [
                "grants",
                "record",
                str(CORPUS / "spec.yaml"),
                str(CORPUS / "grant.json"),
                str(database),
                "--registry",
                str(CORPUS / "block.json"),
                "--workflow",
                "workflow.cpu",
                "--format",
                "json",
            ]
        )
        == 0
    )
    recorded = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert recorded["type"] == "authorization.grant.recorded"
    assert "rg1." not in json.dumps(recorded)
    swapped = json.loads((CORPUS / "grant.json").read_text(encoding="utf-8"))
    swapped["grantId"] = "grant.cpu.swapped"
    swapped["nonce"] = "nonce.cpu.swapped"
    swapped["event"] = {"id": "evt.grant.recorded.swapped", "time": "2026-09-07T12:00:00Z"}
    swapped["imageDigest"] = "sha256:" + ("b" * 64)
    swapped_path = tmp_path / "grant-swapped.json"
    swapped_path.write_text(json.dumps(swapped), encoding="utf-8")
    assert (
        main(
            [
                "grants",
                "record",
                str(CORPUS / "spec.yaml"),
                str(swapped_path),
                str(database),
                "--registry",
                str(CORPUS / "block.json"),
                "--format",
                "json",
            ]
        )
        == 1
    )
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "execution-binding-mismatch" in err
