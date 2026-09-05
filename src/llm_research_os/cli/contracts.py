"""Registered JSON Schema contracts for ``researchos schema``.

Adding a contract means appending one ``SchemaContract`` here. Parser choices,
dispatch, and ``schema --check-all`` all read this table.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from llm_research_os.artifacts.schema import (
    canonical_schema as canonical_artifact_object_report_schema,
)
from llm_research_os.artifacts.schema import (
    schema_matches as artifact_object_report_schema_matches,
)
from llm_research_os.artifacts.schema import (
    write_schema as write_artifact_object_report_schema,
)
from llm_research_os.blocks.report_schema import canonical_schema as canonical_block_report_schema
from llm_research_os.blocks.report_schema import schema_matches as block_report_schema_matches
from llm_research_os.blocks.report_schema import write_schema as write_block_report_schema
from llm_research_os.blocks.schema import canonical_schema as canonical_block_schema
from llm_research_os.blocks.schema import schema_matches as block_schema_matches
from llm_research_os.blocks.schema import write_schema as write_block_schema
from llm_research_os.events.schema import canonical_schema as canonical_event_schema
from llm_research_os.events.schema import schema_matches as event_schema_matches
from llm_research_os.events.schema import write_schema as write_event_schema
from llm_research_os.evidence.schema import (
    canonical_evidence_citation_schema,
    canonical_evidence_import_request_schema,
    evidence_citation_schema_matches,
    evidence_import_request_schema_matches,
    write_evidence_citation_schema,
    write_evidence_import_request_schema,
)
from llm_research_os.execution.authorization_event_request_schema import (
    canonical_schema as canonical_plan_authorization_event_request_schema,
)
from llm_research_os.execution.authorization_event_request_schema import (
    schema_matches as plan_authorization_event_request_schema_matches,
)
from llm_research_os.execution.authorization_event_request_schema import (
    write_schema as write_plan_authorization_event_request_schema,
)
from llm_research_os.execution.authorization_lineage_query_schema import (
    canonical_schema as canonical_plan_authorization_lineage_query_schema,
)
from llm_research_os.execution.authorization_lineage_query_schema import (
    schema_matches as plan_authorization_lineage_query_schema_matches,
)
from llm_research_os.execution.authorization_lineage_query_schema import (
    write_schema as write_plan_authorization_lineage_query_schema,
)
from llm_research_os.execution.authorization_lineage_report_schema import (
    canonical_schema as canonical_plan_authorization_lineage_report_schema,
)
from llm_research_os.execution.authorization_lineage_report_schema import (
    schema_matches as plan_authorization_lineage_report_schema_matches,
)
from llm_research_os.execution.authorization_lineage_report_schema import (
    write_schema as write_plan_authorization_lineage_report_schema,
)
from llm_research_os.execution.authorization_report_schema import (
    canonical_schema as canonical_plan_authorization_report_schema,
)
from llm_research_os.execution.authorization_report_schema import (
    schema_matches as plan_authorization_report_schema_matches,
)
from llm_research_os.execution.authorization_report_schema import (
    write_schema as write_plan_authorization_report_schema,
)
from llm_research_os.execution.authorization_request_schema import (
    canonical_schema as canonical_plan_authorization_request_schema,
)
from llm_research_os.execution.authorization_request_schema import (
    schema_matches as plan_authorization_request_schema_matches,
)
from llm_research_os.execution.authorization_request_schema import (
    write_schema as write_plan_authorization_request_schema,
)
from llm_research_os.execution.native_preflight_report_schema import (
    canonical_schema as canonical_native_process_preflight_report_schema,
)
from llm_research_os.execution.native_preflight_report_schema import (
    schema_matches as native_process_preflight_report_schema_matches,
)
from llm_research_os.execution.native_preflight_report_schema import (
    write_schema as write_native_process_preflight_report_schema,
)
from llm_research_os.execution.native_preflight_request_schema import (
    canonical_schema as canonical_native_process_preflight_request_schema,
)
from llm_research_os.execution.native_preflight_request_schema import (
    schema_matches as native_process_preflight_request_schema_matches,
)
from llm_research_os.execution.native_preflight_request_schema import (
    write_schema as write_native_process_preflight_request_schema,
)
from llm_research_os.execution.request_schema import (
    canonical_schema as canonical_simulation_request_schema,
)
from llm_research_os.execution.request_schema import (
    schema_matches as simulation_request_schema_matches,
)
from llm_research_os.execution.request_schema import (
    write_schema as write_simulation_request_schema,
)
from llm_research_os.execution.schema import canonical_schema as canonical_dry_run_schema
from llm_research_os.execution.schema import schema_matches as dry_run_schema_matches
from llm_research_os.execution.schema import write_schema as write_dry_run_schema
from llm_research_os.problem_schema import canonical_schema as canonical_problem_schema
from llm_research_os.problem_schema import schema_matches as problem_schema_matches
from llm_research_os.problem_schema import write_schema as write_problem_schema
from llm_research_os.providers.schema import (
    canonical_model_fixture_schema,
    canonical_model_generate_request_schema,
    canonical_openai_compat_generate_request_schema,
    model_fixture_schema_matches,
    model_generate_request_schema_matches,
    openai_compat_generate_request_schema_matches,
    write_model_fixture_schema,
    write_model_generate_request_schema,
    write_openai_compat_generate_request_schema,
)
from llm_research_os.research.schema import (
    canonical_decision_record_request_schema,
    canonical_dissent_record_request_schema,
    canonical_proposal_submit_request_schema,
    canonical_question_answer_request_schema,
    canonical_question_ask_request_schema,
    decision_record_request_schema_matches,
    dissent_record_request_schema_matches,
    proposal_submit_request_schema_matches,
    question_answer_request_schema_matches,
    question_ask_request_schema_matches,
    write_decision_record_request_schema,
    write_dissent_record_request_schema,
    write_proposal_submit_request_schema,
    write_question_answer_request_schema,
    write_question_ask_request_schema,
)
from llm_research_os.research.schema import (
    canonical_schema as canonical_research_ledger_schema,
)
from llm_research_os.research.schema import (
    schema_matches as research_ledger_schema_matches,
)
from llm_research_os.research.schema import write_schema as write_research_ledger_schema
from llm_research_os.runs.cancellation_schema import (
    canonical_schema as canonical_run_cancellation_request_schema,
)
from llm_research_os.runs.cancellation_schema import (
    schema_matches as run_cancellation_request_schema_matches,
)
from llm_research_os.runs.cancellation_schema import (
    write_schema as write_run_cancellation_request_schema,
)
from llm_research_os.runs.schema import canonical_schema as canonical_run_state_schema
from llm_research_os.runs.schema import schema_matches as run_state_schema_matches
from llm_research_os.runs.schema import write_schema as write_run_state_schema
from llm_research_os.secrets.schema import canonical_schema as canonical_secret_ref_schema
from llm_research_os.secrets.schema import schema_matches as secret_ref_schema_matches
from llm_research_os.secrets.schema import write_schema as write_secret_ref_schema
from llm_research_os.spec.schema import canonical_schema as canonical_research_schema
from llm_research_os.spec.schema import schema_matches as research_schema_matches
from llm_research_os.spec.schema import write_schema as write_research_schema

DEFAULT_SCHEMA_CONTRACT = "research-spec"


@dataclass(frozen=True, slots=True)
class SchemaContract:
    """Handlers and committed path for one generated JSON Schema contract."""

    canonical: Callable[[], str]
    matches: Callable[[str | Path], bool]
    write: Callable[[str | Path], None]
    committed_path: Path


def _contract(
    canonical: Callable[[], str],
    matches: Callable[[str | Path], bool],
    write: Callable[[str | Path], None],
    committed_path: str,
) -> SchemaContract:
    return SchemaContract(
        canonical=canonical,
        matches=matches,
        write=write,
        committed_path=Path(committed_path),
    )


SCHEMA_CONTRACTS: dict[str, SchemaContract] = {
    "research-spec": _contract(
        canonical_research_schema,
        research_schema_matches,
        write_research_schema,
        "schemas/research-spec/v0alpha1.schema.json",
    ),
    "research-event": _contract(
        canonical_event_schema,
        event_schema_matches,
        write_event_schema,
        "schemas/research-event/v0alpha1.schema.json",
    ),
    "block-manifest": _contract(
        canonical_block_schema,
        block_schema_matches,
        write_block_schema,
        "schemas/block-manifest/v0alpha1.schema.json",
    ),
    "block-command-report": _contract(
        canonical_block_report_schema,
        block_report_schema_matches,
        write_block_report_schema,
        "schemas/block-command-report/v0alpha1.schema.json",
    ),
    "dry-run-report": _contract(
        canonical_dry_run_schema,
        dry_run_schema_matches,
        write_dry_run_schema,
        "schemas/dry-run-report/v0alpha1.schema.json",
    ),
    "problem-report": _contract(
        canonical_problem_schema,
        problem_schema_matches,
        write_problem_schema,
        "schemas/problem-report/v0alpha1.schema.json",
    ),
    "plan-authorization-request": _contract(
        canonical_plan_authorization_request_schema,
        plan_authorization_request_schema_matches,
        write_plan_authorization_request_schema,
        "schemas/plan-authorization-request/v0alpha1.schema.json",
    ),
    "plan-authorization-report": _contract(
        canonical_plan_authorization_report_schema,
        plan_authorization_report_schema_matches,
        write_plan_authorization_report_schema,
        "schemas/plan-authorization-report/v0alpha1.schema.json",
    ),
    "plan-authorization-event-request": _contract(
        canonical_plan_authorization_event_request_schema,
        plan_authorization_event_request_schema_matches,
        write_plan_authorization_event_request_schema,
        "schemas/plan-authorization-event-request/v0alpha1.schema.json",
    ),
    "plan-authorization-lineage-query": _contract(
        canonical_plan_authorization_lineage_query_schema,
        plan_authorization_lineage_query_schema_matches,
        write_plan_authorization_lineage_query_schema,
        "schemas/plan-authorization-lineage-query/v0alpha1.schema.json",
    ),
    "plan-authorization-lineage-report": _contract(
        canonical_plan_authorization_lineage_report_schema,
        plan_authorization_lineage_report_schema_matches,
        write_plan_authorization_lineage_report_schema,
        "schemas/plan-authorization-lineage-report/v0alpha1.schema.json",
    ),
    "native-process-preflight-request": _contract(
        canonical_native_process_preflight_request_schema,
        native_process_preflight_request_schema_matches,
        write_native_process_preflight_request_schema,
        "schemas/native-process-preflight-request/v0alpha1.schema.json",
    ),
    "native-process-preflight-report": _contract(
        canonical_native_process_preflight_report_schema,
        native_process_preflight_report_schema_matches,
        write_native_process_preflight_report_schema,
        "schemas/native-process-preflight-report/v0alpha1.schema.json",
    ),
    "run-state": _contract(
        canonical_run_state_schema,
        run_state_schema_matches,
        write_run_state_schema,
        "schemas/run-state/v0alpha1.schema.json",
    ),
    "simulation-request": _contract(
        canonical_simulation_request_schema,
        simulation_request_schema_matches,
        write_simulation_request_schema,
        "schemas/simulation-request/v0alpha1.schema.json",
    ),
    "run-cancellation-request": _contract(
        canonical_run_cancellation_request_schema,
        run_cancellation_request_schema_matches,
        write_run_cancellation_request_schema,
        "schemas/run-cancellation-request/v0alpha1.schema.json",
    ),
    "artifact-object-report": _contract(
        canonical_artifact_object_report_schema,
        artifact_object_report_schema_matches,
        write_artifact_object_report_schema,
        "schemas/artifact-object-report/v0alpha1.schema.json",
    ),
    "secret-ref": _contract(
        canonical_secret_ref_schema,
        secret_ref_schema_matches,
        write_secret_ref_schema,
        "schemas/secret-ref/v0alpha1.schema.json",
    ),
    "research-ledger": _contract(
        canonical_research_ledger_schema,
        research_ledger_schema_matches,
        write_research_ledger_schema,
        "schemas/research-ledger/v0alpha1.schema.json",
    ),
    "proposal-submit-request": _contract(
        canonical_proposal_submit_request_schema,
        proposal_submit_request_schema_matches,
        write_proposal_submit_request_schema,
        "schemas/proposal-submit-request/v0alpha1.schema.json",
    ),
    "dissent-record-request": _contract(
        canonical_dissent_record_request_schema,
        dissent_record_request_schema_matches,
        write_dissent_record_request_schema,
        "schemas/dissent-record-request/v0alpha1.schema.json",
    ),
    "decision-record-request": _contract(
        canonical_decision_record_request_schema,
        decision_record_request_schema_matches,
        write_decision_record_request_schema,
        "schemas/decision-record-request/v0alpha1.schema.json",
    ),
    "question-ask-request": _contract(
        canonical_question_ask_request_schema,
        question_ask_request_schema_matches,
        write_question_ask_request_schema,
        "schemas/question-ask-request/v0alpha1.schema.json",
    ),
    "question-answer-request": _contract(
        canonical_question_answer_request_schema,
        question_answer_request_schema_matches,
        write_question_answer_request_schema,
        "schemas/question-answer-request/v0alpha1.schema.json",
    ),
    "model-generate-request": _contract(
        canonical_model_generate_request_schema,
        model_generate_request_schema_matches,
        write_model_generate_request_schema,
        "schemas/model-generate-request/v0alpha1.schema.json",
    ),
    "model-fixture": _contract(
        canonical_model_fixture_schema,
        model_fixture_schema_matches,
        write_model_fixture_schema,
        "schemas/model-fixture/v0alpha1.schema.json",
    ),
    "openai-compat-generate-request": _contract(
        canonical_openai_compat_generate_request_schema,
        openai_compat_generate_request_schema_matches,
        write_openai_compat_generate_request_schema,
        "schemas/openai-compat-generate-request/v0alpha1.schema.json",
    ),
    "evidence-import-request": _contract(
        canonical_evidence_import_request_schema,
        evidence_import_request_schema_matches,
        write_evidence_import_request_schema,
        "schemas/evidence-import-request/v0alpha1.schema.json",
    ),
    "evidence-citation": _contract(
        canonical_evidence_citation_schema,
        evidence_citation_schema_matches,
        write_evidence_citation_schema,
        "schemas/evidence-citation/v0alpha1.schema.json",
    ),
}


def schema_command(
    *,
    output: Path | None,
    check: Path | None,
    check_all: bool,
    contract: str,
) -> int:
    """Print, write, or check one registered contract, or every committed schema."""

    if check_all:
        return _check_all_schemas()
    handlers = SCHEMA_CONTRACTS[contract]
    if check is not None:
        if handlers.matches(check):
            print(f"schema is current: {check}")
            return 0
        print(f"schema differs from generated contract: {check}", file=sys.stderr)
        return 1
    if output is not None:
        handlers.write(output)
        print(f"wrote schema: {output}")
        return 0
    print(handlers.canonical(), end="")
    return 0


def _check_all_schemas() -> int:
    failed = False
    for handlers in SCHEMA_CONTRACTS.values():
        path = handlers.committed_path
        if handlers.matches(path):
            print(f"schema is current: {path}")
            continue
        print(f"schema differs from generated contract: {path}", file=sys.stderr)
        failed = True
    return 1 if failed else 0
