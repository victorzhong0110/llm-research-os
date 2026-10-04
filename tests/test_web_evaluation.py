"""R13 through the shared service: evaluate, compare, and record a conclusion.

This is the Checkpoint C loop the plan names — proposal, decision, evaluation,
comparison, human conclusion — exercised through the same command path the
browser and the CLI use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from web_helpers import BOOTSTRAP, ORIGIN, Client

from llm_research_os.application.workspace import init_workspace, load_workspace
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.sessions import SessionStore

PREFIX = "/api/v0alpha1"
PROJECT = "example-minimal"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "eval"
    root.mkdir(parents=True)
    database = root / "control.db"
    init_workspace(
        root,
        project_id=PROJECT,
        control_db=database,
        cas_root=root / "cas",
        worker_root=tmp_path / "eval-worker",
    )
    with EventStore(database):
        pass
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


def _head(workspace: Path) -> int:
    with EventStore(workspace / "control.db", require_existing=True) as store:
        return store.last_sequence()


def _run(
    client: Client, workspace: Path, command_id: str, operation: dict[str, Any], **extra: Any
) -> Any:
    document: dict[str, Any] = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": command_id,
        "actorId": "researcher.alice",
        "submittedAt": "2026-10-04T12:00:00+08:00",
        "expectedRevision": 1,
        "expectedHead": _head(workspace),
        "operation": operation,
    }
    document.update(extra)
    status, _headers, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=json.dumps(document).encode("utf-8"),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 200, payload
    return payload["result"]


# --- A real evaluation ---------------------------------------------------------


def test_evaluation_is_real_labelled_and_reproducible(client: Client, workspace: Path) -> None:
    result = _run(
        client, workspace, "cmd.eval.candidate", {"kind": "evaluation.run", "mode": "candidate"}
    )
    assert result["label"] == "computed-fixture"
    assert "Synthetic" in result["limitations"][0]
    assert result["reproducible"] is True
    assert set(result["metrics"]) == {"accuracy", "macro_f1", "mean_absolute_error"}
    assert result["provenance"]["split"] == "held-out"
    assert result["provenance"]["evaluatorVersion"] == "v0alpha1"
    assert result["provenance"]["exampleCount"] > 0
    assert result["detailArtifact"].startswith("sha256:")

    # The stored artifact replays to the same metrics: the number is re-derivable.
    from llm_research_os.artifacts.store import LocalArtifactStore
    from llm_research_os.evaluation import recompute
    from llm_research_os.evaluation.evaluator import held_out_dataset

    store = LocalArtifactStore(workspace / "cas")
    with store.open(result["detailArtifact"]) as stream:
        document = json.loads(stream.read().decode("utf-8"))
    assert document["metrics"] == result["metrics"]
    assert len(document["examples"]) == result["provenance"]["exampleCount"]
    assert recompute(_rebuild(document), held_out_dataset()).metrics == result["metrics"]


def _rebuild(document: dict[str, Any]) -> Any:
    from llm_research_os.evaluation.evaluator import (
        Detail,
        EvaluationResult,
        Provenance,
    )

    return EvaluationResult(
        provenance=Provenance(
            dataset_digest=document["datasetDigest"],
            evaluator_name=document["evaluatorName"],
            evaluator_version=document["evaluatorVersion"],
            split=document["split"],
            seed=int(document["seed"]),
            example_count=int(document["exampleCount"]),
        ),
        metrics=document["metrics"],
        details=tuple(
            Detail(
                example_id=item["exampleId"],
                predicted=int(item["predicted"]),
                expected=int(item["expected"]),
                correct=bool(item["correct"]),
                absolute_error=float(item["absoluteError"]),
            )
            for item in document["examples"]
        ),
    )


def test_evaluation_appends_no_event(client: Client, workspace: Path) -> None:
    """Metrics live in CAS chunks. A series must not fill the event log."""

    def head() -> int:
        with EventStore(workspace / "control.db", require_existing=True) as store:
            return store.last_sequence()

    before = head()
    _run(client, workspace, "cmd.eval.nofacts", {"kind": "evaluation.run", "mode": "candidate"})
    assert head() == before
    with EventStore(workspace / "control.db", require_existing=True) as store:
        assert store.verify_integrity() == before


def test_evaluation_requires_a_revision(client: Client, workspace: Path) -> None:
    document = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": "cmd.eval.norev",
        "actorId": "researcher.alice",
        "submittedAt": "2026-10-04T12:00:00+08:00",
        "operation": {"kind": "evaluation.run", "mode": "candidate"},
    }
    status, _headers, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=json.dumps(document).encode("utf-8"),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 400
    assert payload["code"] == "document-invalid"


# --- Comparison ---------------------------------------------------------------


def test_comparison_reports_metrics_and_can_support_a_conclusion(
    client: Client, workspace: Path
) -> None:
    baseline = _run(
        client, workspace, "cmd.eval.base", {"kind": "evaluation.run", "mode": "majority"}
    )
    candidate = _run(
        client, workspace, "cmd.eval.cand", {"kind": "evaluation.run", "mode": "candidate"}
    )
    comparison = _run(
        client,
        workspace,
        "cmd.eval.compare",
        {
            "kind": "evaluation.compare",
            "baseline": baseline["detailArtifact"],
            "candidate": candidate["detailArtifact"],
        },
    )
    assert comparison["outcome"] == "improved"
    assert comparison["supportsAConclusion"] is True
    assert {delta["metric"] for delta in comparison["deltas"]} == {
        "accuracy",
        "macro_f1",
        "mean_absolute_error",
    }
    assert comparison["limitations"], "a comparison must state its limits"


def test_comparison_of_incompatible_setups_is_refused(client: Client, workspace: Path) -> None:
    baseline = _run(
        client, workspace, "cmd.eval.seed0", {"kind": "evaluation.run", "mode": "candidate"}
    )
    other = _run(
        client,
        workspace,
        "cmd.eval.seed9",
        {"kind": "evaluation.run", "mode": "candidate", "seed": 9},
    )
    comparison = _run(
        client,
        workspace,
        "cmd.eval.compare.bad",
        {
            "kind": "evaluation.compare",
            "baseline": baseline["detailArtifact"],
            "candidate": other["detailArtifact"],
        },
    )
    assert comparison["outcome"] == "incomparable"
    assert comparison["refusal"] is not None
    assert comparison["deltas"] == []


def test_comparison_of_a_missing_artifact_is_refused(client: Client, workspace: Path) -> None:
    candidate = _run(
        client, workspace, "cmd.eval.missing.cand", {"kind": "evaluation.run", "mode": "candidate"}
    )
    document = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": "cmd.eval.compare.missing",
        "actorId": "researcher.alice",
        "submittedAt": "2026-10-04T12:00:00+08:00",
        "expectedRevision": 1,
        "operation": {
            "kind": "evaluation.compare",
            "baseline": "sha256:" + "0" * 64,
            "candidate": candidate["detailArtifact"],
        },
    }
    status, _headers, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=json.dumps(document).encode("utf-8"),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 409
    assert payload["code"] == "command-refused"


# --- Conclusions --------------------------------------------------------------


def test_a_human_conclusion_can_be_recorded(client: Client, workspace: Path) -> None:
    baseline = _run(
        client, workspace, "cmd.eval.c.base", {"kind": "evaluation.run", "mode": "majority"}
    )
    candidate = _run(
        client, workspace, "cmd.eval.c.cand", {"kind": "evaluation.run", "mode": "candidate"}
    )
    conclusion = _run(
        client,
        workspace,
        "cmd.conclusion.ok",
        {
            "kind": "conclusion.record",
            "baseline": baseline["detailArtifact"],
            "candidate": candidate["detailArtifact"],
            "verdict": "supported",
            "rationale": "Accuracy and macro F1 both improve on the fixed held-out set.",
            "conclusionId": "conclusion.1",
        },
    )
    assert conclusion["verdict"] == "supported"
    assert conclusion["actorId"] == "researcher.alice"
    assert conclusion["systemDerived"] is False, "the system must not supply the judgement"
    assert conclusion["contractVersion"] == "v0alpha1"


def test_a_negative_conclusion_is_recorded(client: Client, workspace: Path) -> None:
    good = _run(
        client,
        workspace,
        "cmd.eval.n.good",
        {"kind": "evaluation.run", "mode": "candidate", "threshold": 0.45},
    )
    worse = _run(
        client,
        workspace,
        "cmd.eval.n.bad",
        {"kind": "evaluation.run", "mode": "threshold", "threshold": 0.95},
    )
    conclusion = _run(
        client,
        workspace,
        "cmd.conclusion.negative",
        {
            "kind": "conclusion.record",
            "baseline": good["detailArtifact"],
            "candidate": worse["detailArtifact"],
            "verdict": "unsupported",
            "rationale": "The candidate threshold regresses against the baseline.",
            "conclusionId": "conclusion.negative",
        },
    )
    assert conclusion["verdict"] == "unsupported"


def test_a_conclusion_over_incompatible_evidence_is_refused(
    client: Client, workspace: Path
) -> None:
    baseline = _run(
        client, workspace, "cmd.eval.i.base", {"kind": "evaluation.run", "mode": "candidate"}
    )
    other = _run(
        client,
        workspace,
        "cmd.eval.i.other",
        {"kind": "evaluation.run", "mode": "candidate", "seed": 4},
    )
    document = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": "cmd.conclusion.refused",
        "actorId": "researcher.alice",
        "submittedAt": "2026-10-04T12:00:00+08:00",
        "expectedRevision": 1,
        "expectedHead": _head(workspace),
        "operation": {
            "kind": "conclusion.record",
            "baseline": baseline["detailArtifact"],
            "candidate": other["detailArtifact"],
            "verdict": "supported",
            "rationale": "It looked better.",
            "conclusionId": "conclusion.refused",
        },
    }
    status, _headers, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=json.dumps(document).encode("utf-8"),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 409
    assert payload["code"] == "command-refused"


def test_inconclusive_is_recordable_without_a_comparison(client: Client, workspace: Path) -> None:
    baseline = _run(
        client, workspace, "cmd.eval.q.base", {"kind": "evaluation.run", "mode": "candidate"}
    )
    other = _run(
        client,
        workspace,
        "cmd.eval.q.other",
        {"kind": "evaluation.run", "mode": "candidate", "seed": 8},
    )
    conclusion = _run(
        client,
        workspace,
        "cmd.conclusion.inconclusive",
        {
            "kind": "conclusion.record",
            "baseline": baseline["detailArtifact"],
            "candidate": other["detailArtifact"],
            "verdict": "insufficient-evidence",
            "rationale": "Different seeds, so no comparison is possible yet.",
            "conclusionId": "conclusion.inconclusive",
        },
    )
    assert conclusion["verdict"] == "insufficient-evidence"


def test_a_conclusion_needs_a_rationale(client: Client, workspace: Path) -> None:
    baseline = _run(
        client, workspace, "cmd.eval.r.base", {"kind": "evaluation.run", "mode": "majority"}
    )
    candidate = _run(
        client, workspace, "cmd.eval.r.cand", {"kind": "evaluation.run", "mode": "candidate"}
    )
    document = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": "cmd.conclusion.empty",
        "actorId": "researcher.alice",
        "submittedAt": "2026-10-04T12:00:00+08:00",
        "expectedRevision": 1,
        "expectedHead": _head(workspace),
        "operation": {
            "kind": "conclusion.record",
            "baseline": baseline["detailArtifact"],
            "candidate": candidate["detailArtifact"],
            "verdict": "supported",
            "rationale": "",
            "conclusionId": "conclusion.empty",
        },
    }
    status, _headers, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=json.dumps(document).encode("utf-8"),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 409
    assert payload["code"] == "command-refused"


def test_same_command_cannot_replay_different_evaluator_parameters(
    client: Client, workspace: Path
) -> None:
    _run(client, workspace, "cmd.eval.identity", {"kind": "evaluation.run", "mode": "candidate"})
    document = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ApplicationCommand",
        "commandId": "cmd.eval.identity",
        "actorId": "researcher.alice",
        "submittedAt": "2026-10-04T12:00:00+08:00",
        "expectedRevision": 1,
        "expectedHead": _head(workspace),
        "operation": {"kind": "evaluation.run", "mode": "threshold", "threshold": 0.95},
    }
    status, _, payload = client.request(
        "POST",
        f"{PREFIX}/commands",
        body=json.dumps(document).encode(),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 409
    assert payload["code"] == "command-refused"
    from llm_research_os.application.errors import ApplicationError
    from llm_research_os.application.models import ApplicationCommand
    from llm_research_os.application.service import ApplicationService

    with pytest.raises(ApplicationError, match="different content") as fault:
        ApplicationService.open(workspace).execute(ApplicationCommand.model_validate(document))
    assert fault.value.code == "receipt-conflict"


def test_forged_aggregate_is_refused_through_service(client: Client, workspace: Path) -> None:
    from llm_research_os.artifacts.store import LocalArtifactStore
    from llm_research_os.evaluation import evaluate

    cas = LocalArtifactStore(workspace / "cas")
    document = evaluate(threshold=0.45, mode="threshold").detail_document()
    document["metrics"]["accuracy"] = "0.000000"
    forged = cas.put_bytes(json.dumps(document).encode())
    valid = _run(
        client, workspace, "cmd.eval.valid", {"kind": "evaluation.run", "mode": "candidate"}
    )
    from llm_research_os.application.errors import ApplicationError
    from llm_research_os.application.models import ApplicationCommand
    from llm_research_os.application.service import ApplicationService

    command = ApplicationCommand.model_validate(
        {
            "apiVersion": "researchos.dev/application/v0alpha1",
            "kind": "ApplicationCommand",
            "commandId": "cmd.eval.forged",
            "actorId": "researcher.alice",
            "submittedAt": "2026-10-04T12:00:00+08:00",
            "operation": {
                "kind": "evaluation.compare",
                "baseline": forged.digest,
                "candidate": valid["detailArtifact"],
            },
        }
    )
    with pytest.raises(ApplicationError, match="detail artifact is invalid") as fault:
        ApplicationService.open(workspace).execute(command)
    assert fault.value.code == "evaluation-invalid"
