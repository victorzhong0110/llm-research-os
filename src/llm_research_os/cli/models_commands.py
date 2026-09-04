"""Model generate commands for the deterministic mock and the HTTP adapter."""

from __future__ import annotations

import argparse

from pydantic import ValidationError

from llm_research_os.artifacts import ArtifactStoreError, LocalArtifactStore
from llm_research_os.budget.errors import BudgetError, BudgetRequestError
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.providers.compat import CompatHttpProvider
from llm_research_os.providers.compat_requests import validate_compat_generate_request
from llm_research_os.providers.control import ModelCallControl, ModelCallResult
from llm_research_os.providers.errors import (
    ModelProviderError,
    ModelRequestError,
    ModelTransportError,
)
from llm_research_os.providers.mock import DeterministicMockProvider
from llm_research_os.providers.models import ModelFixtureDocument
from llm_research_os.providers.requests import load_model_fixture, validate_model_generate_request
from llm_research_os.secrets.resolve import SecretResolutionError, resolve_secret
from llm_research_os.spec.io import SpecLoadError, load_document
from llm_research_os.storage import EventStore, EventStoreError

_INPUT_ERRORS = (
    ArtifactStoreError,
    BudgetRequestError,
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
        document = load_document(args.request, reject_symlinks=True)
        fixture = load_model_fixture(args.fixture)
        artifacts = LocalArtifactStore(args.artifacts) if args.artifacts is not None else None
        if type(document) is not dict:
            raise ValueError("request must be a JSON object")
        kind = document.get("kind")
        with EventStore(args.database, require_existing=True) as store:
            if kind == "OpenAICompatGenerateRequest":
                result = _record_http(store, document, fixture, artifacts)
            elif kind == "ModelGenerateRequest":
                request = validate_model_generate_request(document)
                provider = DeterministicMockProvider({fixture.id: fixture})
                result = ModelCallControl(store, project_id=request.project_id).record_generate(
                    request,
                    fixture,
                    provider,
                    artifacts=artifacts,
                )
            else:
                raise ValueError("request kind is not a model generate document")
    except (BudgetError, ModelProviderError) as exc:
        print_error(exc, args.format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, args.format)
        return 2
    _print_receipt(result, args.format)
    return 0


def _record_http(
    store: EventStore,
    document: object,
    fixture: ModelFixtureDocument,
    artifacts: LocalArtifactStore | None,
) -> ModelCallResult:
    request = validate_compat_generate_request(document)
    try:
        secret = resolve_secret(request.secret_ref) if request.secret_ref is not None else None
    except SecretResolutionError:
        raise ModelTransportError("secret is not available", code="secret-unavailable") from None
    provider = CompatHttpProvider(
        endpoint=request.endpoint,
        model_id=request.actor.model_id,
        secret=secret,
    )
    return ModelCallControl(store, project_id=request.project_id).record_http_generate(
        request,
        fixture,
        provider,
        artifacts=artifacts,
    )


def _print_receipt(result: ModelCallResult, output_format: str) -> None:
    event = result.completed.event
    started = result.started.event
    call_id = event.data.payload.get("callId")
    prompt_digest = started.data.payload.get("promptDigest")
    output_digest = event.data.payload.get("outputDigest")
    if type(call_id) is not str or type(prompt_digest) is not str or type(output_digest) is not str:
        raise ModelProviderError(
            "committed payload is missing call digests",
            code="missing-call-id",
        )
    payload: dict[str, object] = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "ModelCallReceipt",
        "callId": call_id,
        "startedEventId": started.id,
        "completedEventId": event.id,
        "sequence": event.sequence,
        "projectId": event.data.project_id,
        "promptDigest": prompt_digest,
        "outputDigest": output_digest,
    }
    if result.reserved is not None:
        payload["reservedEventId"] = result.reserved.event.id
    if result.consumed is not None:
        payload["consumedEventId"] = result.consumed.event.id
    if output_format == "json":
        print(dumps_json(payload))
        return
    print("model call: recorded")
    print(f"call: {safe_text(call_id)}")
    print(f"started: {safe_text(started.id)}")
    print(f"completed: {safe_text(event.id)}")
    print(f"project: {safe_text(event.data.project_id)}")
    print(f"sequence: {safe_text(event.sequence)}")
