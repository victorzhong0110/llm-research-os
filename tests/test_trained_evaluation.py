"""Real native CPU training, forged provenance refusals and human reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_application_native import native_command, setup_native
from test_web_commands import _command
from web_helpers import ORIGIN, Client

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import ApplicationCommand
from llm_research_os.application.native import freeze_native
from llm_research_os.application.service import ApplicationService
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.evaluation import iris
from llm_research_os.evaluation.evaluator import parse_detail
from llm_research_os.evaluation.trained import load_detail
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.sessions import SessionStore


def command(
    service: ApplicationService, operation: dict, identity: str, revision: int = 1
) -> ApplicationCommand:
    with EventStore(service.workspace.control_db) as store:
        head = store.last_sequence()
    return ApplicationCommand.model_validate(
        _command(
            command_id=identity, operation=operation, expected_head=head, expected_revision=revision
        )
    )


def setup_trained(tmp_path: Path):  # type: ignore[no-untyped-def]
    workspace, world, _ = setup_native(
        tmp_path, task_source=Path(iris.__file__).read_bytes(), stdout_bytes=65536
    )
    service = ApplicationService(workspace)
    launch = service.execute(
        native_command("native.start", digest=freeze_native(workspace, "cpu").digest)
    )
    output = launch["result"]["artifactDigest"]
    receipt = service.execute(
        command(
            service,
            {"kind": "evaluation.collect", "profileId": "cpu", "outputArtifact": output},
            "collect",
        )
    )
    return service, world, receipt


def test_real_training_recompute_failures_report_and_exact_replay(tmp_path: Path) -> None:
    service, world, receipt = setup_trained(tmp_path)
    result = receipt["result"]
    assert result["baselineMetrics"] == {
        "accuracy": "0.500000",
        "macro_f1": "0.333333",
        "mean_absolute_error": "0.500000",
    }
    assert result["candidateMetrics"]["accuracy"] == "0.950000"
    assert len(result["failureExampleIds"]) == 1
    assert result["provenance"]["runId"] == world.request.run_id
    assert result["systemDerivedConclusion"] is False
    detail = load_detail(service.workspace, result["candidateArtifact"], service._read_artifact)
    assert len(parse_detail(detail["detail"]).details) == 20
    assert len(iris.main()["training"]) == 80
    train_ids = {r["id"] for r in iris.main()["training"]}
    assert train_ids.isdisjoint({r["id"] for r in iris.main()["heldout"]})
    pair = {"baseline": result["baselineArtifact"], "candidate": result["candidateArtifact"]}
    preview = service.execute(command(service, {"kind": "evaluation.report", **pair}, "preview"))[
        "result"
    ]
    assert preview["verdict"] is None and preview["humanDecisionRequired"] is True
    assert preview["comparison"]["comparison"]["outcome"] == "improved"
    intent = command(
        service,
        {
            "kind": "conclusion.publish",
            **pair,
            "comparisonDigest": preview["comparisonDigest"],
            "reportId": "report.human",
            "narrative": "Edited narrative; this public split is not an independent finding.",
            "verdict": "insufficient-evidence",
            "rationale": "Needs independent data and repeats.",
        },
        "publish",
    )
    published = service.execute(intent)
    assert published["result"]["report"]["systemDerived"] is False
    assert published["result"]["report"]["actorId"] == intent.actor_id
    assert "Edited narrative" in published["result"]["report"]["narrative"]
    assert service.execute(intent)["disposition"] == "replayed"
    with LocalArtifactStore(service.workspace.cas_root).open(
        published["result"]["reportArtifact"]
    ) as stream:
        assert json.load(stream) == published["result"]["report"]
    with EventStore(service.workspace.control_db) as store:
        head = store.last_sequence()
    reopened = ApplicationService.open(service.workspace.root)
    assert reopened.execute(intent)["disposition"] == "replayed"
    listing = reopened.execute(command(reopened, {"kind": "conclusion.list"}, "list"))["result"]
    assert listing["reports"][0]["reportArtifact"] == published["result"]["reportArtifact"]
    inspected = reopened.execute(
        command(
            reopened,
            {"kind": "conclusion.inspect", "reportArtifact": published["result"]["reportArtifact"]},
            "inspect",
        )
    )["result"]
    assert inspected["report"] == published["result"]["report"]
    with EventStore(service.workspace.control_db) as store:
        assert store.last_sequence() == head


@pytest.mark.parametrize("field", ["metrics", "config", "source", "failures", "run"])
def test_forged_trained_detail_is_refused(tmp_path: Path, field: str) -> None:
    service, _world, receipt = setup_trained(tmp_path)
    result = receipt["result"]
    doc = json.loads(service._read_artifact(Path(result["candidateArtifact"])))
    if field == "metrics":
        doc["detail"]["metrics"].pop("macro_f1")
    elif field == "config":
        doc["provenance"]["configDigest"] = "jcs-sha256:" + "0" * 64
    elif field == "source":
        doc["provenance"]["sourceDigest"] = "sha256:" + "0" * 64
    elif field == "failures":
        doc["failureExampleIds"] = []
    else:
        doc["provenance"]["runId"] = "run.forged"
    forged = LocalArtifactStore(service.workspace.cas_root).put_bytes(canonical_json(doc).encode())
    with pytest.raises(ApplicationError, match=r"validation or replay|differs"):
        service.execute(
            command(
                service,
                {
                    "kind": "evaluation.report",
                    "baseline": result["baselineArtifact"],
                    "candidate": forged.digest,
                },
                "forged",
            )
        )


def test_unrecorded_output_is_not_real_training(tmp_path: Path) -> None:
    workspace, world, _ = setup_native(tmp_path, task_source=Path(iris.__file__).read_bytes())
    from llm_research_os.execution.native_reviewed import request_digest

    envelope = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "NativeReviewedTaskOutput",
        "requestDigest": request_digest(world.request),
        "taskId": world.request.task_id,
        "runId": world.request.run_id,
        "attemptId": world.request.attempt_id,
        "output": iris.main(),
    }
    cas = LocalArtifactStore(workspace.cas_root)
    forged = cas.put_bytes(canonical_json(envelope).encode())
    service = ApplicationService(workspace)
    with pytest.raises(ApplicationError, match="Worker completion"):
        service.execute(
            command(
                service,
                {"kind": "evaluation.collect", "profileId": "cpu", "outputArtifact": forged.digest},
                "unrecorded",
            )
        )


@pytest.mark.parametrize("alteration", ["output", "actor", "comparison", "roles", "evidence"])
def test_report_refuses_substitution_and_missing_inputs(tmp_path: Path, alteration: str) -> None:
    service, _world, receipt = setup_trained(tmp_path)
    result = receipt["result"]
    pair = {"baseline": result["baselineArtifact"], "candidate": result["candidateArtifact"]}
    preview = service.execute(command(service, {"kind": "evaluation.report", **pair}, "preview"))[
        "result"
    ]
    operation = {
        "kind": "conclusion.publish",
        **pair,
        "comparisonDigest": preview["comparisonDigest"],
        "reportId": "report.negative",
        "narrative": "A human-edited negative finding.",
        "verdict": "unsupported",
        "rationale": "The evidence does not test the stated claim.",
    }
    if alteration == "output":
        output = json.loads(service._read_artifact(Path(result["provenance"]["outputArtifact"])))
        output["output"]["models"]["candidate"]["centroids"][0][0] = "999"
        digest = (
            LocalArtifactStore(service.workspace.cas_root)
            .put_bytes(canonical_json(output).encode())
            .digest
        )
        operation = {"kind": "evaluation.collect", "profileId": "cpu", "outputArtifact": digest}
    elif alteration == "comparison":
        operation["comparisonDigest"] = "jcs-sha256:" + "0" * 64
    elif alteration == "roles":
        operation["baseline"], operation["candidate"] = (
            operation["candidate"],
            operation["baseline"],
        )
    elif alteration == "evidence":
        operation["evidenceRefs"] = ["evidence.nonexistent"]
    else:
        operation["rationale"] = "   "
    with pytest.raises(ApplicationError):
        service.execute(command(service, operation, "invalid"))


def test_trained_workflow_through_actual_local_api(tmp_path: Path) -> None:
    service, _world, receipt = setup_trained(tmp_path)
    api = LocalApi(
        service.workspace,
        sessions=SessionStore(bootstrap_token="training-test"),
        allowed_hosts=frozenset({"127.0.0.1:8787"}),
        allowed_origin=ORIGIN,
    )
    client = Client(api)
    client.bootstrap("training-test")
    pair = {
        "baseline": receipt["result"]["baselineArtifact"],
        "candidate": receipt["result"]["candidateArtifact"],
    }
    intent = command(service, {"kind": "evaluation.report", **pair}, "http.report")
    status, _, doc = client.request(
        "POST",
        "/api/v0alpha1/commands",
        body=intent.model_dump_json(by_alias=True).encode(),
        content_type="application/json",
        origin=ORIGIN,
    )
    assert status == 200, doc
    assert doc["result"]["verdict"] is None
    assert doc["result"]["comparisonDigest"] == content_digest(doc["result"]["comparison"])


def test_checkpoint_c_proposal_decision_matches_actual_run_spec(tmp_path: Path) -> None:
    from trained_demo import stage_trained_demo

    from llm_research_os.application.research import freeze_model

    workspace, fixture = stage_trained_demo(tmp_path / "demo")
    service = ApplicationService(workspace)
    generated = service.execute(
        command(
            service,
            {
                "kind": "model.generate",
                "profileId": "mock",
                "materialDigest": freeze_model(workspace, "mock").digest,
            },
            "model",
        )
    )["result"]
    service.execute(
        command(
            service,
            {
                "kind": "research.submit",
                "proposal": generated["draft"],
                "baseArtifact": fixture["baseArtifact"],
                "candidateArtifact": fixture["candidateArtifact"],
            },
            "proposal",
        )
    )
    decision = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "DecisionRecordRequest",
        "projectId": workspace.project_id,
        "experimentRevision": 1,
        "source": "researchos://demo/synthetic",
        "subject": "proposal.cpu",
        "streamid": "stream.research",
        "actor": {"id": "browser-operator", "kind": "human"},
        "event": {"id": "evt.decision.cpu", "time": "2026-10-08T00:01:00Z"},
        "decisionId": "decision.cpu",
        "targetKind": "proposal",
        "targetId": "proposal.cpu",
        "outcome": "accept",
        "rationale": "Synthetic engineering decision only; no phase acceptance.",
        "overriddenDissentIds": [],
        "evidenceRefs": [],
    }
    service.execute(command(service, {"kind": "research.record", "document": decision}, "decision"))
    # An accepted proposal cannot substitute for an actual completed output.
    fake_output = LocalArtifactStore(workspace.cas_root).put_bytes(b"{}").digest
    with pytest.raises(ApplicationError, match="validation or replay"):
        service.execute(
            command(
                service,
                {
                    "kind": "evaluation.collect",
                    "profileId": "cpu",
                    "outputArtifact": fake_output,
                    "decisionId": "decision.cpu",
                },
                "before-run",
                2,
            )
        )
    launched = service.execute(
        command(
            service,
            {
                "kind": "native.start",
                "profileId": "cpu",
                "materialDigest": freeze_native(workspace, "cpu").digest,
            },
            "start",
            2,
        )
    )["result"]
    collect = service.execute(
        command(
            service,
            {
                "kind": "evaluation.collect",
                "profileId": "cpu",
                "outputArtifact": launched["artifactDigest"],
                "decisionId": "decision.cpu",
            },
            "collect",
            2,
        )
    )["result"]
    assert collect["provenance"]["proposalId"] == "proposal.cpu"
    assert collect["provenance"]["decisionId"] == "decision.cpu"
    pair = {"baseline": collect["baselineArtifact"], "candidate": collect["candidateArtifact"]}
    preview = service.execute(
        command(service, {"kind": "evaluation.report", **pair}, "preview", 2)
    )["result"]
    assert preview["comparison"]["candidate"]["experimentRevision"] == 2
    for index, verdict in enumerate(("supported", "unsupported", "insufficient-evidence")):
        result = service.execute(
            command(
                service,
                {
                    "kind": "conclusion.publish",
                    **pair,
                    "comparisonDigest": preview["comparisonDigest"],
                    "reportId": f"report.demo{index}",
                    "narrative": "Synthetic edited report; no human or scientific acceptance.",
                    "verdict": verdict,
                    "rationale": "Explicit test choice over a public development benchmark.",
                },
                f"report.{index}",
                2,
            )
        )["result"]
        assert result["report"]["verdict"] == verdict and result["systemDerived"] is False
    with pytest.raises(ApplicationError, match="accepted proposal"):
        service.execute(
            command(
                service,
                {
                    "kind": "evaluation.collect",
                    "profileId": "cpu",
                    "outputArtifact": launched["artifactDigest"],
                    "decisionId": "missing.decision",
                },
                "bad.decision",
                2,
            )
        )


def test_published_contract_examples_and_version_separation() -> None:
    from jsonschema import Draft202012Validator
    from pydantic import TypeAdapter, ValidationError

    from llm_research_os.evaluation.trained_contracts import (
        ResearchReport,
        TrainedComparison,
        TrainedEvaluationDetail,
    )
    from llm_research_os.evaluation.trained_schema import build_schema

    validator = Draft202012Validator(build_schema())
    adapter = TypeAdapter(TrainedEvaluationDetail | TrainedComparison | ResearchReport)
    root = Path(__file__).parents[1] / "examples/trained-evaluation"
    for path in root.glob("*.valid.json"):
        document = json.loads(path.read_bytes())
        validator.validate(document)
        adapter.validate_python(document)
    for path in root.glob("*.invalid-*.json"):
        document = json.loads(path.read_bytes())
        assert list(validator.iter_errors(document)), path
        with pytest.raises(ValidationError):
            adapter.validate_python(document)
    from llm_research_os.evaluation.evaluator import evaluate

    old = evaluate(threshold=0.5, mode="majority").detail_document()
    with pytest.raises(ValidationError):
        adapter.validate_python(old)


def test_incompatible_training_setup_reports_no_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from copy import deepcopy

    import llm_research_os.evaluation.trained as module

    service, _world, receipt = setup_trained(tmp_path)
    result = receipt["result"]
    left = load_detail(service.workspace, result["baselineArtifact"], service._read_artifact)
    right = load_detail(service.workspace, result["candidateArtifact"], service._read_artifact)
    # Domain comparison policy alone; production loading separately refuses
    # forged details and checks the actual completed Run before reaching it.
    for field in ("experimentRevision", "configDigest", "trainingDatasetDigest"):
        modified = deepcopy(right)
        modified["provenance"][field] = (
            2 if field == "experimentRevision" else "jcs-sha256:" + "0" * 64
        )
        monkeypatch.setattr(
            module,
            "load_detail",
            lambda _w, digest, _read, saved=modified: left if digest == "left" else saved,
        )
        comparison = module.comparison_document(
            service.workspace, "left", "right", service._read_artifact
        )
        assert comparison["comparison"]["outcome"] == "incomparable"
        assert comparison["comparison"]["deltas"] == []
        assert comparison["comparison"]["supportsAConclusion"] is False


def test_report_discovery_is_bounded_and_unrecorded_actor_is_refused(tmp_path: Path) -> None:
    from copy import deepcopy

    service, _world, receipt = setup_trained(tmp_path)
    result = receipt["result"]
    pair = {"baseline": result["baselineArtifact"], "candidate": result["candidateArtifact"]}
    preview = service.execute(command(service, {"kind": "evaluation.report", **pair}, "preview"))[
        "result"
    ]
    for index in range(11):
        published = service.execute(
            command(
                service,
                {
                    "kind": "conclusion.publish",
                    **pair,
                    "comparisonDigest": preview["comparisonDigest"],
                    "reportId": f"report.{index}",
                    "narrative": "Synthetic negative report preserves the immutable comparison.",
                    "verdict": "unsupported",
                    "rationale": "The benchmark does not test the broad claim.",
                },
                f"publish.{index}",
            )
        )["result"]
    listed = service.execute(command(service, {"kind": "conclusion.list"}, "list"))["result"]
    assert len(listed["reports"]) == 10 and listed["withheld"] == 1
    forged = deepcopy(published["report"])
    forged["actorId"] = "invented.person"
    artifact = (
        LocalArtifactStore(service.workspace.cas_root)
        .put_bytes(canonical_json(forged).encode())
        .digest
    )
    with pytest.raises(ApplicationError, match="no recorded report"):
        service.execute(
            command(
                service,
                {"kind": "conclusion.inspect", "reportArtifact": artifact},
                "inspect.forged",
            )
        )
