"""Real CPU training details and human reports survive verified workspace restore."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from test_trained_evaluation import command, setup_trained

from llm_research_os.application import ApplicationService
from llm_research_os.application.receipts import ReceiptLog
from llm_research_os.canonical import content_digest
from llm_research_os.cli.contracts import SCHEMA_CONTRACTS
from llm_research_os.evaluation.trained import load_detail
from llm_research_os.recovery import (
    RecoveryError,
    create_backup,
    load_manifest,
    restore_backup,
    verify_backup,
)
from llm_research_os.recovery.models import BackupManifestV2
from llm_research_os.storage import EventStore

NOW = datetime(2026, 10, 8, 1, 0, tzinfo=UTC)


def published_workspace(tmp_path: Path):
    service, _world, collected = setup_trained(tmp_path)
    result = collected["result"]
    pair = {"baseline": result["baselineArtifact"], "candidate": result["candidateArtifact"]}
    preview = service.execute(command(service, {"kind": "evaluation.report", **pair}, "preview"))[
        "result"
    ]
    intent = command(
        service,
        {
            "kind": "conclusion.publish",
            **pair,
            "comparisonDigest": preview["comparisonDigest"],
            "reportId": "report.restorable",
            "narrative": "Human-edited public benchmark report; independent evidence remains pending.",
            "verdict": "insufficient-evidence",
            "rationale": "This fixed development split cannot establish an independent finding.",
        },
        "publish",
    )
    published = service.execute(intent)["result"]
    log = ReceiptLog(service.workspace.receipt_db)
    assert log.reserve_effect("synthetic-unfinished-dispatch", "jcs-sha256:" + "1" * 64)
    return service, result, intent, published


def test_backup_restore_preserves_real_details_reports_and_unknown_reservations(tmp_path: Path) -> None:
    service, result, intent, published = published_workspace(tmp_path)
    image = tmp_path / "image"
    report = create_backup(service.workspace, image, now=NOW)
    manifest = load_manifest(image)
    assert isinstance(manifest, BackupManifestV2)
    assert manifest.operations_receipt_count >= 4 and manifest.operations_intent_count >= 1
    assert verify_backup(image).object_count == report.object_count
    for name in ("backup-manifest-v2", "operations-backup"):
        contract = SCHEMA_CONTRACTS[name]
        assert contract.matches(Path(__file__).parents[1] / contract.committed_path)
    Draft202012Validator(json.loads(SCHEMA_CONTRACTS["backup-manifest-v2"].canonical())).validate(
        manifest.model_dump(mode="json", by_alias=True)
    )
    with EventStore(service.workspace.control_db) as store:
        head = store.last_sequence()
    restored = restore_backup(image, tmp_path / "restored")
    assert restored.appended_events == 0 and restored.relaunch_policy == "not-relaunched"
    reopened = ApplicationService.open(tmp_path / "restored")
    for role in ("baseline", "candidate"):
        detail = load_detail(reopened.workspace, result[f"{role}Artifact"], reopened._read_artifact)
        assert detail["modelRole"] == role and detail["provenance"] == (
            load_detail(service.workspace, result[f"{role}Artifact"], service._read_artifact)[
                "provenance"
            ]
        )
    listed = reopened.execute(command(reopened, {"kind": "conclusion.list"}, "restored.list"))[
        "result"
    ]
    assert listed["reports"][0]["reportArtifact"] == published["reportArtifact"]
    inspected = reopened.execute(
        command(
            reopened,
            {"kind": "conclusion.inspect", "reportArtifact": published["reportArtifact"]},
            "restored.inspect",
        )
    )["result"]
    assert inspected["report"] == published["report"]
    assert reopened.execute(intent)["disposition"] == "replayed"
    assert not ReceiptLog(reopened.workspace.receipt_db).reserve_effect(
        "synthetic-unfinished-dispatch", "jcs-sha256:" + "1" * 64
    )
    with EventStore(reopened.workspace.control_db) as store:
        assert store.last_sequence() == head
    assert not (reopened.workspace.root / "native-profiles").exists()


def rewrite_operations(image: Path, mutate) -> None:
    path = image / "operations.json"
    state = json.loads(path.read_bytes())
    mutate(state)
    payload = json.dumps(state).encode()
    path.write_bytes(payload)
    manifest_path = image / "backup-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["operationsSnapshotDigest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    manifest["operationsSnapshotBytes"] = len(payload)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    "alteration",
    ["project", "result", "future", "fact", "identity", "intent", "count", "missing", "object"],
)
def test_corrupt_receipt_aware_images_fail_before_restore(tmp_path: Path, alteration: str) -> None:
    service, _result, _intent, published = published_workspace(tmp_path)
    image = tmp_path / "image"
    create_backup(service.workspace, image, now=NOW)

    def mutate(state):
        receipt = state["receipts"][0]
        if alteration == "project":
            state["projectId"] = "project.foreign"
        elif alteration == "result":
            receipt["result"]["forged"] = True
        elif alteration == "future":
            receipt["observedHead"] = 2_000_000_000
        elif alteration == "fact":
            receipt["factEventIds"] = ["evt.nonexistent"]
        elif alteration == "identity":
            state["receipts"].append(receipt)
        elif alteration == "intent":
            state["intents"][0]["contentDigest"] = "not-a-digest"
        elif alteration == "count":
            state["intents"] = []

    rewrite_operations(image, mutate)
    if alteration == "missing":
        (image / "operations.json").unlink()
    elif alteration == "object":
        from llm_research_os.artifacts.store import storage_key_for

        (image / "cas" / storage_key_for(published["reportArtifact"])).unlink()
    with pytest.raises(RecoveryError, match="operation|object"):
        verify_backup(image)
    target = tmp_path / "refused"
    with pytest.raises(RecoveryError, match="operation|object"):
        restore_backup(image, target)
    assert not target.exists()


def test_operation_result_tampering_is_refused_even_with_rehashed_receipt(tmp_path: Path) -> None:
    service, _result, _intent, _published = published_workspace(tmp_path)
    image = tmp_path / "image"
    create_backup(service.workspace, image, now=NOW)

    def mutate(state):
        receipt = next(r for r in state["receipts"] if r["operation"] == "conclusion.publish")
        receipt["result"]["report"]["projectId"] = "project.foreign"
        receipt["resultDigest"] = content_digest(receipt["result"])

    rewrite_operations(image, mutate)
    with pytest.raises(RecoveryError, match="operation"):
        verify_backup(image)


def test_receipt_object_set_is_rederived_and_missing_entry_is_refused(tmp_path: Path) -> None:
    service, result, _intent, _published = published_workspace(tmp_path)
    image = tmp_path / "image"
    create_backup(service.workspace, image, now=NOW)
    path = image / "backup-manifest.json"
    manifest = json.loads(path.read_bytes())
    dropped = next(o for o in manifest["objects"] if o["digest"] == result["candidateArtifact"])
    manifest["objects"].remove(dropped)
    manifest["totalObjectBytes"] -= dropped["sizeBytes"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RecoveryError, match="objects"):
        verify_backup(image)


def test_capture_refuses_corrupt_source_receipt_and_preserves_source(tmp_path: Path) -> None:
    import sqlite3

    service, _result, _intent, _published = published_workspace(tmp_path)
    connection = sqlite3.connect(service.workspace.receipt_db)
    try:
        connection.execute("DROP TRIGGER operation_receipts_reject_update")
        connection.execute(
            "UPDATE operation_receipts SET receipt_json = '{}' WHERE command_id = 'publish'"
        )
        connection.commit()
    finally:
        connection.close()
    target = tmp_path / "refused"
    with pytest.raises(RecoveryError, match="operation"):
        create_backup(service.workspace, target, now=NOW)
    assert not target.exists()
    assert service.workspace.control_db.exists()
