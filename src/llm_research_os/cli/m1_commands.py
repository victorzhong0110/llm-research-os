"""M1 checkpoint command. This path does not close Issue #38."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.execution.errors import (
    PlanAuthorizationError,
    PlanAuthorizationRecordError,
    SimulationError,
)
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.m1.errors import M1CheckpointError
from llm_research_os.m1.prove import CheckpointDecision, M1CheckpointResult, prove_checkpoint
from llm_research_os.providers.errors import ModelProviderError, ModelRequestError
from llm_research_os.report.errors import ReportError
from llm_research_os.research.errors import ResearchDecisionError, ResearchRequestError
from llm_research_os.runs.errors import RunStateError
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.storage import EventStoreError

_INPUT_ERRORS = (
    EventStoreError,
    ManifestLoadError,
    ModelRequestError,
    OSError,
    PlanningInputError,
    RegistryError,
    ResearchRequestError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_m1(args: argparse.Namespace) -> int:
    if args.m1_command == "prove":
        decision = args.decision
        if decision != "accept" and decision != "reject":
            raise AssertionError(f"unhandled m1 decision: {decision}")
        return _prove(
            args.corpus,
            args.database,
            decision,
            args.registry,
            args.format,
        )
    raise AssertionError(f"unhandled m1 command: {args.m1_command}")


def _prove(
    corpus: Path,
    database: Path,
    decision: CheckpointDecision,
    registry_paths: list[Path],
    output_format: str,
) -> int:
    try:
        result = prove_checkpoint(
            corpus,
            database,
            decision=decision,
            registry_paths=registry_paths,
        )
    except M1CheckpointError as exc:
        print_error(exc, output_format)
        return 2
    except (
        ModelProviderError,
        PlanAuthorizationError,
        PlanAuthorizationRecordError,
        ReportError,
        ResearchDecisionError,
        RunStateError,
        SimulationError,
    ) as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(result, output_format)
    return 0


def _print_receipt(result: M1CheckpointResult, output_format: str) -> None:
    if output_format == "json":
        print(
            dumps_json(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "M1CheckpointReceipt",
                    "decision": result.decision,
                    "projectId": result.project_id,
                    "runId": result.run_id,
                    "queued": result.queued,
                    "specDigest": result.spec_digest,
                    "proposedSpecDigest": result.proposed_spec_digest,
                    "specDiffDigest": result.spec_diff_digest,
                    "outputDigest": result.output_digest,
                    "eventTypes": list(result.event_types),
                    "eventIds": list(result.event_ids),
                    "decisionCount": result.decision_count,
                    "answeredQuestionCount": result.answered_question_count,
                    "rationaleCharacters": result.rationale_characters,
                    "overriddenDissentCount": result.overridden_dissent_count,
                }
            )
        )
        return
    print("m1 checkpoint: recorded")
    print(f"decision: {safe_text(result.decision)}")
    print(f"project: {safe_text(result.project_id)}")
    print(f"queued: {safe_text(str(result.queued).lower())}")
    print(f"events: {safe_text(len(result.event_types))}")
    print(f"decisions: {safe_text(result.decision_count)}")
    print(f"answered questions: {safe_text(result.answered_question_count)}")
    print(f"rationale characters: {safe_text(result.rationale_characters)}")
    if result.report_markdown is not None:
        print()
        print(result.report_markdown, end="")
