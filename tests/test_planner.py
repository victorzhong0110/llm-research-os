from __future__ import annotations

import builtins
import importlib
import json
import os
import socket
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import NoReturn

import pytest
from pydantic import ValidationError

from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.canonical import content_digest
from llm_research_os.execution import PlannerLimits, PlanningInputError, TrustedKernel
from llm_research_os.execution.models import DryRunReport, DryRunStatus, PlannedLoop
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import ResearchSpec

EXAMPLES = Path(__file__).parents[1] / "examples"


def _report(document: dict[str, object], registry: BlockRegistry | None = None):  # type: ignore[no-untyped-def]
    spec = ResearchSpec.model_validate(document)
    return TrustedKernel(registry or build_registry()).dry_run(spec)


def _manifest(
    block_id: str,
    *,
    runtime: str = "simulated",
    entrypoint: str | None = None,
    inputs: list[dict[str, object]] | None = None,
    outputs: list[dict[str, object]] | None = None,
) -> BlockManifest:
    runtime_payload: dict[str, object] = {"type": runtime}
    if entrypoint is not None:
        runtime_payload["entrypoint"] = entrypoint
    return BlockManifest.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "Block",
            "metadata": {"id": block_id, "version": "0.1.0"},
            "runtime": runtime_payload,
            "inputs": inputs or [],
            "outputs": outputs or [],
            "configSchema": {"type": "object", "additionalProperties": False},
        }
    )


def _registry(*manifests: BlockManifest) -> BlockRegistry:
    registry = BlockRegistry()
    for manifest in manifests:
        registry.register(manifest)
    registry.seal()
    return registry


def test_minimal_dry_run_is_ready_and_side_effect_free() -> None:
    report = TrustedKernel(build_registry()).dry_run(load_spec(EXAMPLES / "valid/minimal.yaml"))
    assert report.status is DryRunStatus.READY
    assert report.plan is not None
    assert report.summary.task_count == 1
    assert report.side_effects.blocks_executed == 0
    assert report.side_effects.network_requests == 0
    assert report.side_effects.persistent_writes == 0
    assert report.side_effects.paid_actions == 0
    task = report.plan.graph.stages[0].nodes[0]
    assert task.kind == "task"
    assert task.execution == "not-executed"
    assert task.authorization == "not-evaluated"


def test_same_input_produces_byte_identical_report() -> None:
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    kernel = TrustedKernel(build_registry())
    first = kernel.dry_run(spec).model_dump(mode="json", by_alias=True, exclude_none=True)
    second = kernel.dry_run(spec).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_node_reordering_does_not_change_plan_digest() -> None:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]  # type: ignore[index]
    graph["nodes"] = [  # type: ignore[index]
        {
            "kind": "task",
            "id": node_id,
            "blockType": "simulated.experiment",
            "blockVersion": "0.1.0",
        }
        for node_id in ("z-last", "a-first")
    ]
    first = _report(document)
    reordered = deepcopy(document)
    reordered["workflows"][0]["graph"]["nodes"].reverse()  # type: ignore[index,union-attr]
    second = _report(reordered)
    assert first.digests.spec != second.digests.spec
    assert first.digests.plan == second.digests.plan
    assert first.plan is not None
    assert [node.node_path[-1] for node in first.plan.graph.stages[0].nodes] == [
        "a-first",
        "z-last",
    ]


def test_unknown_exact_version_blocks_whole_plan() -> None:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    task = document["workflows"][0]["graph"]["nodes"][0]  # type: ignore[index]
    task["blockVersion"] = "9.9.9"  # type: ignore[index]
    report = _report(document)
    assert report.status is DryRunStatus.BLOCKED
    assert report.plan is None
    assert report.diagnostics[0].code == "unknown-block"
    assert report.workflow_id == "workflow.simulation"
    assert report.summary.basis == "source"
    assert report.summary.task_count == 1


def test_blocked_spec_digest_uses_the_normalized_snapshot() -> None:
    spec = load_spec(EXAMPLES / "valid/bounded-loop.yaml")
    loop = spec.workflows[0].graph.nodes[0]
    assert loop.kind == "loop"
    task = loop.body.nodes[0]
    assert task.kind == "task"
    task.resource_refs[0] = " remote-gpu "
    report = TrustedKernel(build_registry()).dry_run(spec)
    normalized = ResearchSpec.model_validate(
        spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    expected = normalized.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert report.status is DryRunStatus.BLOCKED
    assert report.digests.spec == content_digest(expected)


def test_invalid_config_blocks_without_echoing_secret() -> None:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    task = document["workflows"][0]["graph"]["nodes"][0]  # type: ignore[index]
    secret = "TOP-SECRET-SENTINEL"
    task["config"] = {"outcome": secret}  # type: ignore[index]
    report = _report(document)
    rendered = report.model_dump_json(by_alias=True)
    assert report.status is DryRunStatus.BLOCKED
    assert report.diagnostics[0].code == "invalid-block-config"
    assert secret not in rendered


def test_bounded_loop_is_symbolic_and_until_is_never_exposed_or_evaluated() -> None:
    document = load_document(EXAMPLES / "valid/bounded-loop.yaml")
    loop = document["workflows"][0]["graph"]["nodes"][0]  # type: ignore[index]
    loop["maxIterations"] = 10**100  # type: ignore[index]
    expression = "__import__('os').system('TOP-SECRET-SENTINEL')"
    loop["until"]["expression"] = expression  # type: ignore[index]
    registry = build_registry([EXAMPLES / "manifests/example-train.yaml"])
    report = _report(document, registry)
    assert report.status is DryRunStatus.READY
    assert report.summary.loop_count == 1
    assert report.summary.task_count == 1
    assert report.plan is not None
    planned_loop = report.plan.graph.stages[0].nodes[0]
    assert isinstance(planned_loop, PlannedLoop)
    assert planned_loop.max_iterations == 10**100
    assert planned_loop.until is not None
    assert planned_loop.until.evaluated is False
    assert expression not in report.model_dump_json(by_alias=True)
    assert len(planned_loop.body.stages) == 1
    assert planned_loop.max_cost == 5
    assert report.plan.resources[0].id == "remote-gpu"
    assert report.plan.resources[0].max_wall_time_seconds == 3600
    assert {requirement.kind for requirement in report.plan.policy_requirements} == {
        "paid-loop-approval",
        "paid-resource-approval",
    }
    assert report.side_effects.paid_actions == 0


def test_multiple_workflows_require_exact_selection() -> None:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    second = deepcopy(document["workflows"][0])  # type: ignore[index]
    second["id"] = "workflow.second"
    document["workflows"].append(second)  # type: ignore[union-attr]
    spec = ResearchSpec.model_validate(document)
    kernel = TrustedKernel(build_registry())
    with pytest.raises(PlanningInputError, match="select one workflow explicitly"):
        kernel.dry_run(spec)
    report = kernel.dry_run(spec, workflow_id="workflow.second")
    assert report.status is DryRunStatus.READY
    assert report.workflow_id == "workflow.second"


def test_approval_is_reported_as_pending_without_echoing_prompt() -> None:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]  # type: ignore[index]
    secret_prompt = "Approve TOP-SECRET-SENTINEL"
    graph["nodes"] = [  # type: ignore[index]
        {
            "kind": "approval",
            "id": "researcher-review",
            "prompt": secret_prompt,
            "requiredRole": "researcher",
        }
    ]
    report = _report(document)
    assert report.status is DryRunStatus.READY
    assert report.plan is not None
    approval = report.plan.graph.stages[0].nodes[0]
    assert approval.kind == "approval"
    assert approval.disposition == "would-pause"
    assert report.plan.policy_requirements[0].kind == "human-approval"
    assert secret_prompt not in report.model_dump_json(by_alias=True)


def test_unknown_port_and_missing_required_input_fail_closed() -> None:
    source = _manifest(
        "example.source",
        outputs=[{"id": "data", "valueType": "researchos.dataset/v0alpha1"}],
    )
    target = _manifest(
        "example.target",
        inputs=[
            {
                "id": "data",
                "valueType": "researchos.dataset/v0alpha1",
                "required": True,
            }
        ],
    )
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]  # type: ignore[index]
    graph["nodes"] = [  # type: ignore[index]
        {
            "kind": "task",
            "id": "source",
            "blockType": "example.source",
            "blockVersion": "0.1.0",
        },
        {
            "kind": "task",
            "id": "target",
            "blockType": "example.target",
            "blockVersion": "0.1.0",
        },
    ]
    graph["edges"] = []  # type: ignore[index]
    missing = _report(document, _registry(source, target))
    assert missing.diagnostics[0].code == "missing-required-input"
    graph["edges"] = [  # type: ignore[index]
        {
            "source": "source",
            "target": "target",
            "sourcePort": "missing",
            "targetPort": "data",
        }
    ]
    unknown = _report(document, _registry(source, target))
    assert unknown.diagnostics[0].code == "unknown-source-port"


def test_valid_data_edge_preserves_dependency_and_rejects_type_mismatch() -> None:
    source = _manifest(
        "example.source",
        outputs=[{"id": "data", "valueType": "researchos.dataset/v0alpha1"}],
    )
    target = _manifest(
        "example.target",
        inputs=[
            {
                "id": "data",
                "valueType": "researchos.dataset/v0alpha1",
                "required": True,
            }
        ],
    )
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]  # type: ignore[index]
    graph["nodes"] = [  # type: ignore[index]
        {
            "kind": "task",
            "id": "source",
            "blockType": "example.source",
            "blockVersion": "0.1.0",
        },
        {
            "kind": "task",
            "id": "target",
            "blockType": "example.target",
            "blockVersion": "0.1.0",
        },
    ]
    graph["edges"] = [  # type: ignore[index]
        {
            "source": "source",
            "target": "target",
            "sourcePort": "data",
            "targetPort": "data",
        }
    ]
    ready = _report(document, _registry(source, target))
    assert ready.status is DryRunStatus.READY
    assert ready.plan is not None
    target_step = ready.plan.graph.stages[1].nodes[0]
    assert target_step.depends_on == ("/workflow/workflow.simulation/source",)
    assert len(ready.plan.graph.edges) == 1
    assert ready.plan.graph.edges[0].source_port == "data"
    assert ready.plan.graph.edges[0].target_port == "data"

    incompatible = _manifest(
        "example.incompatible",
        inputs=[
            {
                "id": "data",
                "valueType": "researchos.metrics/v0alpha1",
                "required": True,
            }
        ],
    )
    graph["nodes"][1]["blockType"] = "example.incompatible"  # type: ignore[index]
    blocked = _report(document, _registry(source, incompatible))
    assert blocked.diagnostics[0].code == "incompatible-port-types"


def test_data_bindings_are_part_of_the_semantic_plan_digest() -> None:
    source = _manifest(
        "example.source",
        outputs=[
            {"id": "a", "valueType": "researchos.dataset/v0alpha1"},
            {"id": "b", "valueType": "researchos.dataset/v0alpha1"},
        ],
    )
    target = _manifest(
        "example.target",
        inputs=[
            {"id": "x", "valueType": "researchos.dataset/v0alpha1", "required": True},
            {"id": "y", "valueType": "researchos.dataset/v0alpha1", "required": True},
        ],
    )
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]  # type: ignore[index]
    graph["nodes"] = [  # type: ignore[index]
        {
            "kind": "task",
            "id": "source",
            "blockType": "example.source",
            "blockVersion": "0.1.0",
        },
        {
            "kind": "task",
            "id": "target",
            "blockType": "example.target",
            "blockVersion": "0.1.0",
        },
    ]
    graph["edges"] = [  # type: ignore[index]
        {"source": "source", "target": "target", "sourcePort": "a", "targetPort": "x"},
        {"source": "source", "target": "target", "sourcePort": "b", "targetPort": "y"},
    ]
    registry = _registry(source, target)
    first = _report(document, registry)
    swapped = deepcopy(document)
    swapped_edges = swapped["workflows"][0]["graph"]["edges"]  # type: ignore[index]
    swapped_edges[0]["targetPort"] = "y"  # type: ignore[index]
    swapped_edges[1]["targetPort"] = "x"  # type: ignore[index]
    second = _report(swapped, registry)
    assert first.status is DryRunStatus.READY
    assert second.status is DryRunStatus.READY
    assert first.digests.plan != second.digests.plan
    assert first.plan is not None
    assert [(edge.source_port, edge.target_port) for edge in first.plan.graph.edges] == [
        ("a", "x"),
        ("b", "y"),
    ]


def test_resource_provider_and_model_are_part_of_the_semantic_plan_digest() -> None:
    document = load_document(EXAMPLES / "valid/bounded-loop.yaml")
    registry = build_registry([EXAMPLES / "manifests/example-train.yaml"])
    first = _report(document, registry)
    changed = deepcopy(document)
    changed["resources"][0]["provider"] = "another-cloud"  # type: ignore[index]
    changed["resources"][0]["model"] = "A100"  # type: ignore[index]
    second = _report(changed, registry)
    assert first.digests.plan != second.digests.plan
    assert second.plan is not None
    assert second.plan.resources[0].provider == "another-cloud"
    assert second.plan.resources[0].model == "A100"


def test_data_edge_cannot_target_approval_block() -> None:
    source = _manifest(
        "example.source",
        outputs=[{"id": "data", "valueType": "researchos.dataset/v0alpha1"}],
    )
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]  # type: ignore[index]
    graph["nodes"] = [  # type: ignore[index]
        {
            "kind": "task",
            "id": "source",
            "blockType": "example.source",
            "blockVersion": "0.1.0",
        },
        {"kind": "approval", "id": "review", "prompt": "Review it"},
    ]
    graph["edges"] = [  # type: ignore[index]
        {
            "source": "source",
            "target": "review",
            "sourcePort": "data",
            "targetPort": "input",
        }
    ]
    blocked = _report(document, _registry(source))
    assert blocked.diagnostics[0].code == "data-edge-requires-tasks"


def test_plan_snapshot_is_unchanged_after_source_mutation() -> None:
    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    report = TrustedKernel(build_registry()).dry_run(spec)
    before = report.model_dump_json(by_alias=True)
    task = spec.workflows[0].graph.nodes[0]
    assert task.kind == "task"
    task.config["seed"] = 99
    assert report.model_dump_json(by_alias=True) == before


def test_planner_node_limit_blocks_without_partial_plan() -> None:
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    graph = document["workflows"][0]["graph"]  # type: ignore[index]
    graph["nodes"].append(  # type: ignore[union-attr]
        {
            "kind": "task",
            "id": "second",
            "blockType": "simulated.experiment",
            "blockVersion": "0.1.0",
        }
    )
    spec = ResearchSpec.model_validate(document)
    report = TrustedKernel(build_registry(), limits=PlannerLimits(max_nodes=1)).dry_run(spec)
    assert report.status is DryRunStatus.BLOCKED
    assert report.plan is None
    assert report.diagnostics[0].code == "node-limit"
    assert report.summary.truncated is True
    assert report.summary.task_count == 1


@pytest.mark.parametrize(
    "limits",
    [
        {"max_nodes": float("nan")},
        {"max_nodes": float("inf")},
        {"max_nodes": 1.5},
        {"max_nodes": True},
        {"max_nodes": 10_001},
        {"max_loop_depth": float("nan")},
        {"max_loop_depth": "16"},
        {"max_loop_depth": 17},
    ],
)
def test_planner_limits_cannot_weaken_kernel_hard_caps(limits: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        PlannerLimits(**limits)  # type: ignore[arg-type]


def test_dry_run_report_rejects_tampered_status_identity_digests_and_summary() -> None:
    report = TrustedKernel(build_registry()).dry_run(load_spec(EXAMPLES / "valid/minimal.yaml"))
    payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)

    missing_plan = deepcopy(payload)
    del missing_plan["plan"]
    with pytest.raises(ValidationError, match="ready reports require"):
        DryRunReport.model_validate(missing_plan)

    blocked_with_plan = deepcopy(payload)
    blocked_with_plan["status"] = "blocked"
    blocked_with_plan["summary"]["basis"] = "source"  # type: ignore[index]
    blocked_with_plan["diagnostics"] = [
        {"code": "blocked", "severity": "error", "path": "/", "message": "blocked"}
    ]
    with pytest.raises(ValidationError, match="blocked reports must not contain"):
        DryRunReport.model_validate(blocked_with_plan)

    wrong_identity = deepcopy(payload)
    wrong_identity["project"]["id"] = "another-project"  # type: ignore[index]
    with pytest.raises(ValidationError, match="identity must match"):
        DryRunReport.model_validate(wrong_identity)

    wrong_summary = deepcopy(payload)
    wrong_summary["summary"]["taskCount"] = 999  # type: ignore[index]
    with pytest.raises(ValidationError, match="summary does not match"):
        DryRunReport.model_validate(wrong_summary)

    invalid_digest = deepcopy(payload)
    invalid_digest["digests"]["plan"] = "not-a-digest"  # type: ignore[index]
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        DryRunReport.model_validate(invalid_digest)


def test_dry_run_never_calls_runtime_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest(
        "example.python",
        runtime="python",
        entrypoint="tripwire.module:main",
    )
    document = load_document(EXAMPLES / "valid/minimal.yaml")
    task = document["workflows"][0]["graph"]["nodes"][0]  # type: ignore[index]
    task["blockType"] = "example.python"  # type: ignore[index]
    spec = ResearchSpec.model_validate(document)

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"runtime side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(os, "system", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    monkeypatch.setattr(Path, "write_text", tripwire)

    report = TrustedKernel(_registry(manifest)).dry_run(spec)
    assert report.status is DryRunStatus.READY
    assert report.side_effects == report.side_effects.model_copy()
