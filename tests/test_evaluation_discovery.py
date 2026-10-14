"""Discover replayable evaluation pairs without redispatch or trusting receipt scores."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_application_native import setup_native
from test_trained_evaluation import command, setup_trained

from llm_research_os.application import ApplicationService
from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import ApplicationCommand
from llm_research_os.application.receipts import ReceiptLog
from llm_research_os.canonical import content_digest
from llm_research_os.evaluation.trained import load_detail
from llm_research_os.storage import EventStore


def test_empty_discovery_is_not_an_evaluation_or_run(tmp_path: Path) -> None:
    workspace, _world, _ = setup_native(tmp_path)
    service = ApplicationService(workspace)
    intent = command(service, {"kind": "evaluation.list"}, "empty").model_copy(
        update={"expected_revision": None, "expected_head": None}
    )
    with EventStore(workspace.control_db) as store:
        head = store.last_sequence()
    assert service.execute(intent)["result"] == {"evaluations": [], "withheld": 0}
    with EventStore(workspace.control_db) as store:
        assert store.last_sequence() == head


def test_discovery_and_preview_survive_restart_with_verified_examples(tmp_path: Path) -> None:
    service, _world, collected = setup_trained(tmp_path)
    with EventStore(service.workspace.control_db) as store:
        head = store.last_sequence()
    reopened = ApplicationService.open(service.workspace.root)
    listing = reopened.execute(command(reopened, {"kind": "evaluation.list"}, "discover"))["result"]
    assert listing["withheld"] == 0
    summary = listing["evaluations"][0]
    assert summary["commandId"] == "collect"
    assert summary["exampleCount"] == 20
    assert summary["provenance"] == collected["result"]["provenance"]
    pair = {"baseline": summary["baselineArtifact"], "candidate": summary["candidateArtifact"]}
    preview = reopened.execute(command(reopened, {"kind": "evaluation.report", **pair}, "preview"))[
        "result"
    ]
    for role in ("baseline", "candidate"):
        assert preview[f"{role}Detail"] == load_detail(
            reopened.workspace, pair[role], reopened._read_artifact
        )
    assert len(preview["baselineDetail"]["failureExampleIds"]) == 10
    assert len(preview["candidateDetail"]["failureExampleIds"]) == 1
    assert preview["verdict"] is None
    assert preview["comparisonDigest"] == content_digest(preview["comparison"])
    with EventStore(service.workspace.control_db) as store:
        assert store.last_sequence() == head


def test_discovery_bound_newest_first_and_exact_replay(tmp_path: Path) -> None:
    service, _world, collected = setup_trained(tmp_path)
    for index in range(11):
        service.execute(
            command(
                service,
                {
                    "kind": "evaluation.collect",
                    "profileId": "cpu",
                    "outputArtifact": collected["result"]["provenance"]["outputArtifact"],
                },
                f"collect.{index}",
            )
        )
    intent = command(service, {"kind": "evaluation.list"}, "bounded")
    receipt = service.execute(intent)
    listing = receipt["result"]
    assert listing["withheld"] == 2
    assert [item["commandId"] for item in listing["evaluations"]] == [
        f"collect.{index}" for index in range(10, 0, -1)
    ]
    assert service.execute(intent)["result"] == listing
    assert service.execute(intent)["disposition"] == "replayed"


@pytest.mark.parametrize("alteration", ["digest", "metrics", "provenance", "missing-object"])
def test_discovery_refuses_corrupt_or_rehashed_collection(tmp_path: Path, alteration: str) -> None:
    service, _world, collected = setup_trained(tmp_path)
    forged = copy.deepcopy(collected)
    forged["commandId"] = "corrupt.collect"
    if alteration == "digest":
        forged["resultDigest"] = "jcs-sha256:" + "0" * 64
    elif alteration == "metrics":
        forged["result"]["candidateMetrics"]["accuracy"] = "1.000000"
    elif alteration == "provenance":
        forged["result"]["provenance"]["projectId"] = "foreign-project"
    else:
        forged["result"]["candidateArtifact"] = "sha256:" + "0" * 64
    if alteration != "digest":
        forged["resultDigest"] = content_digest(forged["result"])
    ReceiptLog(service.workspace.receipt_db).append(
        forged["commandId"], forged["requestDigest"], forged
    )
    with pytest.raises(
        ApplicationError, match=r"receipt differs|collected evidence differs|unreadable"
    ):
        service.execute(command(service, {"kind": "evaluation.list"}, "refused"))


def test_discovery_request_refuses_paths_or_extra_authority(tmp_path: Path) -> None:
    workspace, _world, _ = setup_native(tmp_path)
    service = ApplicationService(workspace)
    valid = command(service, {"kind": "evaluation.list"}, "example").model_dump(
        mode="json", by_alias=True
    )
    valid["operation"]["path"] = "/other-project"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ApplicationCommand.model_validate(valid)


def test_discovery_command_examples_match_the_closed_contract() -> None:
    root = Path(__file__).parents[1] / "examples/trained-evaluation/commands"
    valid = ApplicationCommand.model_validate(json.loads((root / "list.valid.json").read_bytes()))
    assert valid.operation.kind == "evaluation.list" and valid.expected_revision is None
    with pytest.raises(ValidationError, match="Extra inputs"):
        ApplicationCommand.model_validate(
            json.loads((root / "list.invalid-extra-path.json").read_bytes())
        )
