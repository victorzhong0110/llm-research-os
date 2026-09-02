import json
from pathlib import Path

import yaml

from llm_research_os.cli import main

EXAMPLES = Path(__file__).parents[1] / "examples"
SCHEMA = Path(__file__).parents[1] / "schemas" / "research-spec" / "v0alpha1.schema.json"
EVENT_SCHEMA = Path(__file__).parents[1] / "schemas" / "research-event" / "v0alpha1.schema.json"
BLOCK_SCHEMA = Path(__file__).parents[1] / "schemas" / "block-manifest" / "v0alpha1.schema.json"
BLOCK_REPORT_SCHEMA = (
    Path(__file__).parents[1] / "schemas" / "block-command-report" / "v0alpha1.schema.json"
)
DRY_RUN_SCHEMA = Path(__file__).parents[1] / "schemas" / "dry-run-report" / "v0alpha1.schema.json"
PROBLEM_SCHEMA = Path(__file__).parents[1] / "schemas" / "problem-report" / "v0alpha1.schema.json"
PLAN_AUTHORIZATION_REQUEST_SCHEMA = (
    Path(__file__).parents[1] / "schemas" / "plan-authorization-request" / "v0alpha1.schema.json"
)
PLAN_AUTHORIZATION_REPORT_SCHEMA = (
    Path(__file__).parents[1] / "schemas" / "plan-authorization-report" / "v0alpha1.schema.json"
)
PLAN_AUTHORIZATION_EVENT_REQUEST_SCHEMA = (
    Path(__file__).parents[1]
    / "schemas"
    / "plan-authorization-event-request"
    / "v0alpha1.schema.json"
)
NATIVE_PROCESS_PREFLIGHT_REQUEST_SCHEMA = (
    Path(__file__).parents[1]
    / "schemas"
    / "native-process-preflight-request"
    / "v0alpha1.schema.json"
)
NATIVE_PROCESS_PREFLIGHT_REPORT_SCHEMA = (
    Path(__file__).parents[1]
    / "schemas"
    / "native-process-preflight-report"
    / "v0alpha1.schema.json"
)
RUN_STATE_SCHEMA = Path(__file__).parents[1] / "schemas" / "run-state" / "v0alpha1.schema.json"
SIMULATION_REQUEST_SCHEMA = (
    Path(__file__).parents[1] / "schemas" / "simulation-request" / "v0alpha1.schema.json"
)
RUN_CANCELLATION_REQUEST_SCHEMA = (
    Path(__file__).parents[1] / "schemas" / "run-cancellation-request" / "v0alpha1.schema.json"
)
ARTIFACT_OBJECT_REPORT_SCHEMA = (
    Path(__file__).parents[1] / "schemas" / "artifact-object-report" / "v0alpha1.schema.json"
)


def test_validate_command(capsys: object) -> None:
    result = main(["validate", str(EXAMPLES / "valid" / "minimal.yaml")])
    assert result == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert '"valid": true' in output.out


def test_invalid_command(capsys: object) -> None:
    result = main(["validate", str(EXAMPLES / "invalid" / "implicit-cycle.yaml")])
    assert result == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert '"valid": false' in output.err


def test_schema_check_command() -> None:
    assert main(["schema", "--check", str(SCHEMA)]) == 0


def test_all_contract_schema_check_commands() -> None:
    assert (
        main(
            [
                "schema",
                "--contract",
                "research-event",
                "--check",
                str(EVENT_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "artifact-object-report",
                "--check",
                str(ARTIFACT_OBJECT_REPORT_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "simulation-request",
                "--check",
                str(SIMULATION_REQUEST_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "run-cancellation-request",
                "--check",
                str(RUN_CANCELLATION_REQUEST_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "block-manifest",
                "--check",
                str(BLOCK_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "plan-authorization-request",
                "--check",
                str(PLAN_AUTHORIZATION_REQUEST_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "plan-authorization-report",
                "--check",
                str(PLAN_AUTHORIZATION_REPORT_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "plan-authorization-event-request",
                "--check",
                str(PLAN_AUTHORIZATION_EVENT_REQUEST_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "native-process-preflight-request",
                "--check",
                str(NATIVE_PROCESS_PREFLIGHT_REQUEST_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "native-process-preflight-report",
                "--check",
                str(NATIVE_PROCESS_PREFLIGHT_REPORT_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "problem-report",
                "--check",
                str(PROBLEM_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "block-command-report",
                "--check",
                str(BLOCK_REPORT_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "dry-run-report",
                "--check",
                str(DRY_RUN_SCHEMA),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "schema",
                "--contract",
                "run-state",
                "--check",
                str(RUN_STATE_SCHEMA),
            ]
        )
        == 0
    )


def test_dry_run_json_command_is_ready(capsys: object) -> None:
    result = main(["dry-run", str(EXAMPLES / "valid/minimal.yaml"), "--format", "json"])
    assert result == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(output.out)
    assert payload["status"] == "ready"
    assert payload["sideEffects"] == {
        "blocksExecuted": 0,
        "networkRequests": 0,
        "paidActions": 0,
        "persistentWrites": 0,
    }


def test_dry_run_unknown_block_returns_blocked_report(capsys: object) -> None:
    result = main(["dry-run", str(EXAMPLES / "valid/bounded-loop.yaml"), "--format", "json"])
    assert result == 1
    output = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(output.out)
    assert payload["status"] == "blocked"
    assert "plan" not in payload
    assert payload["diagnostics"][0]["code"] == "unknown-block"
    assert payload["workflowId"] == "workflow.iteration"
    assert payload["summary"]["basis"] == "source"


def test_text_dry_run_is_readable_and_inspectable(capsys: object) -> None:
    blocked_result = main(["dry-run", str(EXAMPLES / "valid/bounded-loop.yaml")])
    assert blocked_result == 1
    blocked = capsys.readouterr()  # type: ignore[attr-defined]
    assert "source nodes:" in blocked.out
    assert "unknown block manifest: example.train@0.1.0" in blocked.out

    ready_result = main(
        [
            "dry-run",
            str(EXAMPLES / "valid/bounded-loop.yaml"),
            "--registry",
            str(EXAMPLES / "manifests/example-train.yaml"),
        ]
    )
    assert ready_result == 0
    ready = capsys.readouterr()  # type: ignore[attr-defined]
    assert "loop /workflow/workflow.iteration/research-loop: maxIterations=3" in ready.out
    assert (
        "task /workflow/workflow.iteration/research-loop/body/train: example.train@0.1.0"
        in ready.out
    )
    assert "remote-gpu: gpu x1" in ready.out
    assert "paid-resource-approval" in ready.out


def test_text_input_errors_are_plain_and_exit_two(tmp_path: Path, capsys: object) -> None:
    invalid = tmp_path / "oversized-number.yaml"
    invalid.write_text("revision: " + "9" * 5000, encoding="utf-8")
    assert main(["dry-run", str(invalid)]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert output.err.startswith("error:")
    assert '"valid"' not in output.err

    assert main(["dry-run", str(invalid), "--format", "json"]) == 2
    json_output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(json_output.err)
    assert problem["apiVersion"] == "researchos.dev/v0alpha1"
    assert problem["kind"] == "ProblemReport"
    assert problem["valid"] is False
    assert problem["errors"][0]["path"] == ""
    assert "location" not in problem["errors"][0]


def test_text_output_escapes_terminal_control_characters(tmp_path: Path, capsys: object) -> None:
    document = yaml.safe_load((EXAMPLES / "valid/minimal.yaml").read_text(encoding="utf-8"))
    dangerous = "researcher\x1b]52;c;payload\x07\nINJECTED"
    document["workflows"][0]["graph"]["nodes"] = [
        {
            "kind": "approval",
            "id": "review",
            "prompt": "Review",
            "requiredRole": dangerous,
        }
    ]
    path = tmp_path / "control.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert main(["dry-run", str(path)]) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert "\\u001b]52;c;payload\\u0007\\nINJECTED" in output.out
    assert "\x1b" not in output.out
    assert "\nINJECTED" not in output.out


def test_invalid_unicode_is_a_structured_input_error(tmp_path: Path, capsys: object) -> None:
    document = yaml.safe_load((EXAMPLES / "valid/minimal.yaml").read_text(encoding="utf-8"))
    document["workflows"][0]["graph"]["nodes"][0]["config"] = {"value": "\ud800"}
    path = tmp_path / "surrogate.json"
    path.write_text(json.dumps(document, ensure_ascii=True), encoding="utf-8")
    assert main(["dry-run", str(path), "--format", "json"]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert problem["kind"] == "ProblemReport"
    assert "Unicode scalar" in problem["errors"][0]["message"]


def test_problem_paths_use_rfc_6901_escaping(tmp_path: Path, capsys: object) -> None:
    document = yaml.safe_load((EXAMPLES / "valid/minimal.yaml").read_text(encoding="utf-8"))
    document["a/b~c"] = True
    document["trailing "] = True
    path = tmp_path / "pointer.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert main(["dry-run", str(path), "--format", "json"]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    paths = {error["path"] for error in problem["errors"]}
    assert paths == {"/a~1b~0c", "/trailing "}


def test_problem_paths_exclude_discriminated_union_branch_labels(
    tmp_path: Path, capsys: object
) -> None:
    base = yaml.safe_load((EXAMPLES / "valid/minimal.yaml").read_text(encoding="utf-8"))
    cases = (
        (
            {
                "kind": "task",
                "id": "task",
                "blockType": "simulated.experiment",
            },
            "/workflows/0/graph/nodes/0/blockVersion",
        ),
        (
            {"kind": "approval", "id": "approval"},
            "/workflows/0/graph/nodes/0/prompt",
        ),
        (
            {
                "kind": "loop",
                "id": "loop",
                "body": {
                    "nodes": [{"kind": "approval", "id": "nested-approval", "prompt": "Review"}],
                    "edges": [],
                },
            },
            "/workflows/0/graph/nodes/0/maxIterations",
        ),
    )

    for index, (node, expected_path) in enumerate(cases):
        document = dict(base)
        document["workflows"] = [
            {
                "id": "workflow.invalid",
                "graph": {"nodes": [node], "edges": []},
            }
        ]
        path = tmp_path / f"union-path-{index}.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        assert main(["validate", str(path)]) == 2
        output = capsys.readouterr()  # type: ignore[attr-defined]
        problem = json.loads(output.err)
        assert [error["path"] for error in problem["errors"]] == [expected_path]


def test_problem_paths_preserve_real_fields_named_like_union_branches(
    tmp_path: Path, capsys: object
) -> None:
    base = yaml.safe_load((EXAMPLES / "valid/minimal.yaml").read_text(encoding="utf-8"))
    for branch_name in ("task", "approval", "loop"):
        document = yaml.safe_load(yaml.safe_dump(base))
        document["workflows"][0]["graph"]["nodes"][0][branch_name] = True
        path = tmp_path / f"real-{branch_name}-field.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        assert main(["validate", str(path)]) == 2
        output = capsys.readouterr()  # type: ignore[attr-defined]
        problem = json.loads(output.err)
        assert [error["path"] for error in problem["errors"]] == [
            f"/workflows/0/graph/nodes/0/{branch_name}"
        ]


def test_long_problem_pointer_does_not_break_structured_errors(
    tmp_path: Path, capsys: object
) -> None:
    document = yaml.safe_load((EXAMPLES / "valid/minimal.yaml").read_text(encoding="utf-8"))
    long_key = "x" * 5000
    document[long_key] = True
    path = tmp_path / "long-pointer.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["dry-run", str(path), "--format", "json"]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    problem = json.loads(output.err)
    assert problem["errors"][0]["path"] == f"/{long_key}"


def test_blocks_list_show_and_validate_commands(capsys: object) -> None:
    assert main(["blocks", "list", "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert listed["blocks"][0]["id"] == "simulated.experiment"
    assert (
        main(
            [
                "blocks",
                "show",
                "simulated.experiment",
                "--version",
                "0.1.0",
                "--format",
                "json",
            ]
        )
        == 0
    )
    shown = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert shown["blocks"][0]["version"] == "0.1.0"
    assert shown["blocks"][0]["manifest"]["configSchema"]["type"] == "object"
    assert shown["blocks"][0]["manifest"]["telemetry"] == ["metric", "log"]
    assert (
        main(
            [
                "blocks",
                "validate",
                str(EXAMPLES / "manifests/example-train.yaml"),
                "--format",
                "json",
            ]
        )
        == 0
    )
    validated = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert validated["valid"] is True
    assert validated["kind"] == "BlockManifestValidationReport"


def test_blocks_text_show_and_errors_are_readable(capsys: object) -> None:
    assert (
        main(
            [
                "blocks",
                "show",
                "simulated.experiment",
                "--version",
                "0.1.0",
            ]
        )
        == 0
    )
    shown = capsys.readouterr()  # type: ignore[attr-defined]
    assert "manifest:" in shown.out
    assert '"configSchema"' in shown.out
    assert '"reproducibility"' in shown.out

    assert main(["blocks", "show", "missing.block", "--version", "0.1.0"]) == 1
    missing = capsys.readouterr()  # type: ignore[attr-defined]
    assert missing.err.startswith("error:")
    assert "unknown block manifest: missing.block@0.1.0" in missing.err
