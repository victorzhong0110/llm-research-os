"""Deterministic mock model-generate commands."""

from __future__ import annotations

import argparse

from pydantic import ValidationError

from llm_research_os.artifacts import ArtifactStoreError, LocalArtifactStore
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.providers.control import ModelCallControl, ModelCallResult
from llm_research_os.providers.errors import ModelProviderError, ModelRequestError
from llm_research_os.providers.mock import DeterministicMockProvider
from llm_research_os.providers.requests import load_model_fixture, load_model_generate_request
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.storage import EventStore, EventStoreError

_INPUT_ERRORS = (
    ArtifactStoreError,
    EventStoreError,
    ModelRequestError,
    OSError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_models(args: argparse.Namespace) -> int:
    if args.models_command == "generate":
        return _generate(args)
    raise AssertionError(f"unhandled models command: {args.models_command}")


def _generate(args: argparse.Namespace) -> int:
    try:
        request = load_model_generate_request(args.request)
        fixture = load_model_fixture(args.fixture)
        artifacts = LocalArtifactStore(args.artifacts) if args.artifacts is not None else None
        provider = DeterministicMockProvider({fixture.id: fixture})
        with EventStore(args.database, require_existing=True) as store:
            result = ModelCallControl(store, project_id=request.project_id).record_generate(
                request,
                fixture,
                provider,
                artifacts=artifacts,
            )
    except ModelProviderError as exc:
        print_error(exc, args.format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, args.format)
        return 2
    _print_receipt(result, args.format)
    return 0


def _print_receipt(result: ModelCallResult, output_format: str) -> None:
    started = result.started.event
    completed = result.completed.event
    call_id = completed.data.payload.get("callId")
    prompt_digest = started.data.payload.get("promptDigest")
    output_digest = completed.data.payload.get("outputDigest")
    if type(call_id) is not str or type(prompt_digest) is not str or type(output_digest) is not str:
        raise ModelProviderError(
            "committed payload is missing call digests",
            code="missing-call-id",
        )
    if output_format == "json":
        print(
            dumps_json(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "ModelCallReceipt",
                    "callId": call_id,
                    "startedEventId": started.id,
                    "completedEventId": completed.id,
                    "sequence": completed.sequence,
                    "projectId": completed.data.project_id,
                    "promptDigest": prompt_digest,
                    "outputDigest": output_digest,
                }
            )
        )
        return
    print("model call: recorded")
    print(f"call: {safe_text(call_id)}")
    print(f"started: {safe_text(started.id)}")
    print(f"completed: {safe_text(completed.id)}")
    print(f"project: {safe_text(completed.data.project_id)}")
    print(f"sequence: {safe_text(completed.sequence)}")
