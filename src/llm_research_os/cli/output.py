"""Shared CLI rendering for JSON, ProblemReport, and ResearchEvent documents."""

from __future__ import annotations

import json
import sys

from pydantic import ValidationError

from llm_research_os.events.models import ResearchEvent
from llm_research_os.execution.errors import SimulationError
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.problem import ProblemDetail, ProblemReport
from llm_research_os.providers.errors import ModelProviderError, ModelRequestError
from llm_research_os.research.errors import ResearchDecisionError, ResearchRequestError
from llm_research_os.runs import RunCancellationRequestError


def dumps_json(payload: object, *, indent: int | None = 2) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
    )


def safe_text(value: object) -> str:
    rendered = json.dumps(str(value), ensure_ascii=True)
    return rendered[1:-1]


def print_error(exc: Exception, output_format: str) -> None:
    print_problem(problem_report(exc), output_format)


def print_problem(report: ProblemReport, output_format: str) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        print(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return
    for error in report.errors:
        display_path = error.path or "<root>"
        print(
            f"error: {safe_text(error.type)} at {safe_text(display_path)}: "
            f"{safe_text(error.message)}",
            file=sys.stderr,
        )


def problem_report(exc: Exception) -> ProblemReport:
    if isinstance(exc, (ModelRequestError, ResearchRequestError, RunCancellationRequestError)):
        errors = _pydantic_problem_details(exc.error, hide_extra_field_names=True)
    elif isinstance(exc, ValidationError):
        errors = _pydantic_problem_details(exc, hide_extra_field_names=False)
    elif isinstance(exc, PlanningInputError):
        errors = [ProblemDetail(path=exc.path, message=str(exc), type=exc.code)]
    elif isinstance(exc, (SimulationError, ResearchDecisionError, ModelProviderError)):
        errors = [ProblemDetail(message=str(exc), type=exc.code)]
    else:
        errors = [ProblemDetail(message=str(exc), type=type(exc).__name__)]
    return ProblemReport(
        apiVersion="researchos.dev/v0alpha1",
        kind="ProblemReport",
        valid=False,
        errors=tuple(errors),
    )


def _pydantic_problem_details(
    exc: ValidationError,
    *,
    hide_extra_field_names: bool,
) -> list[ProblemDetail]:
    errors: list[ProblemDetail] = []
    for error in exc.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = error["loc"]
        message = error["msg"]
        if hide_extra_field_names and error["type"] == "extra_forbidden" and location:
            location = location[:-1]
        if hide_extra_field_names and error["type"] == "union_tag_invalid":
            message = "Input should select a supported cancellation target"
        errors.append(
            ProblemDetail(
                path=_json_pointer(_source_location(location)),
                message=message,
                type=error["type"],
            )
        )
    return errors


def event_document(event: ResearchEvent) -> dict[str, object]:
    return event.model_dump(mode="json", by_alias=True)


def print_event(event: ResearchEvent, output_format: str) -> None:
    payload = event_document(event)
    if output_format == "json":
        print(dumps_json(payload))
        return
    print(f"id: {safe_text(event.id)}")
    print(f"type: {safe_text(event.type)}")
    print(f"sequence: {safe_text(event.sequence)}")
    print(f"streamid: {safe_text(event.streamid)}")
    print(f"streamversion: {safe_text(event.streamversion)}")
    print(f"time: {safe_text(event.time)}")
    print(f"subject: {safe_text(event.subject)}")
    print(dumps_json(payload))


def _source_location(parts: tuple[str | int, ...]) -> tuple[str, ...]:
    """Remove Pydantic discriminated-union labels absent from source documents."""

    workflow_node_tags = {"task", "approval", "loop"}
    cancellation_target_tags = {"run", "attempt"}
    cleaned: list[str | int] = []
    for index, part in enumerate(parts):
        is_workflow_branch_label = (
            isinstance(part, str)
            and part in workflow_node_tags
            and index >= 2
            and parts[index - 2] == "nodes"
            and isinstance(parts[index - 1], int)
        )
        is_cancellation_target_label = (
            isinstance(part, str)
            and part in cancellation_target_tags
            and index >= 1
            and parts[index - 1] == "target"
        )
        if not is_workflow_branch_label and not is_cancellation_target_label:
            cleaned.append(part)
    return tuple(str(part) for part in cleaned)


def _json_pointer(parts: tuple[str, ...]) -> str:
    if not parts:
        return ""
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)
