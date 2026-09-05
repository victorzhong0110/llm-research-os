"""Project-scoped CAS append for ``ai.call.*`` facts.

EventStore remains the only fact source. The call index is a rebuildable fold
and is discarded when the caller rebuilds from the verified prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document
from llm_research_os.projections.replay import replay_events
from llm_research_os.providers.errors import ModelCallError, ModelPayloadError
from llm_research_os.providers.mock import DeterministicMockProvider
from llm_research_os.providers.models import (
    TYPE_AI_CALL_COMPLETED,
    TYPE_AI_CALL_FAILED,
    TYPE_AI_CALL_STARTED,
    AiCallCompletedPayload,
    AiCallFailedPayload,
    AiCallStartedPayload,
    ModelFixtureDocument,
    parse_ai_call_payload,
    require_ai_actor,
)
from llm_research_os.providers.provider import MOCK_PROVIDER_ID, GenerateResult, ModelProvider
from llm_research_os.providers.requests import ModelGenerateRequestDocument
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore

_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})


@dataclass(frozen=True, slots=True)
class CallFold:
    open_calls: frozenset[str]
    closed_calls: frozenset[str]


@dataclass(frozen=True, slots=True)
class ModelCallHead:
    last_sequence: int
    fold: CallFold


@dataclass(frozen=True, slots=True)
class ModelCallResult:
    started: StoredEvent
    completed: StoredEvent


class ModelCallControl:
    """Validate two ``ai.call`` drafts against a frozen index, then CAS-append them.

    ``last_sequence`` is the global EventStore head used as the CAS token.
    Conflicts are not retried. The call index is not persisted.
    """

    def __init__(self, store: EventStore, *, project_id: str, page_size: int = 100) -> None:
        self._store = store
        self._page_size = _require_page_size(page_size)
        self._project_id = project_id

    def rebuild(self) -> ModelCallHead:
        high_water = self._store.freeze_high_water()
        fold = CallFold(open_calls=frozenset(), closed_calls=frozenset())
        for stored in replay_events(
            self._store,
            page_size=self._page_size,
            freeze_high_water=False,
            until_sequence=high_water,
        ):
            fold = apply_call_fold(fold, stored.event, project_id=self._project_id)
        return ModelCallHead(last_sequence=high_water, fold=fold)

    def record_generate(
        self,
        request: ModelGenerateRequestDocument,
        fixture: ModelFixtureDocument,
        provider: ModelProvider,
        *,
        artifacts: LocalArtifactStore | None = None,
    ) -> ModelCallResult:
        if request.project_id != self._project_id:
            raise ModelCallError(
                "request projectId does not match this ModelCallControl",
                code="project-mismatch",
            )
        if request.provider_id != MOCK_PROVIDER_ID:
            raise ModelCallError("provider is not the deterministic mock", code="provider-not-mock")
        if not isinstance(provider, DeterministicMockProvider):
            raise ModelCallError(
                "M1-2 records only DeterministicMockProvider",
                code="provider-not-mock",
            )
        if fixture.id != request.fixture_id:
            raise ModelCallError(
                "fixture id does not match the request",
                code="fixture-id-mismatch",
            )
        identity = provider.identity()
        if request.actor.model_id != identity.model_id:
            raise ModelCallError(
                "actor modelId does not match the provider",
                code="model-id-mismatch",
            )
        if request.provider_id != identity.provider_id:
            raise ModelCallError(
                "request providerId does not match the provider",
                code="provider-id-mismatch",
            )
        result = provider.generate(request.generate_request())
        _require_matching_digests(fixture, result)
        prompt_artifact, output_artifact = _optional_artifacts(artifacts, fixture)
        report = result.capabilities.document()
        declared = tuple(report["declaredCapabilities"])
        measured = tuple(report["measuredCapabilities"])
        allowed = tuple(report["allowedCapabilities"])
        started_draft = request.started_draft(
            identity=identity,
            prompt_digest=result.prompt_digest,
            declared=declared,
            measured=measured,
            allowed=allowed,
        )
        completed_draft = request.completed_draft(
            output_digest=result.output_digest,
            declared=declared,
            measured=measured,
            allowed=allowed,
            prompt_artifact=prompt_artifact,
            output_artifact=output_artifact,
        )
        started = self._append_one(started_draft)
        completed = self._append_one(completed_draft)
        return ModelCallResult(started=started, completed=completed)

    def _append_one(self, document: dict[str, Any]) -> StoredEvent:
        head = self.rebuild()
        frozen_head = head.last_sequence
        try:
            draft = snapshot_json_document(document)
        except JsonCloneError as exc:
            raise ModelCallError(str(exc), code="invalid-draft") from None
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(draft))
        if supplied:
            raise ModelCallError(
                "ModelCallControl does not accept store-assigned fields; "
                f"caller supplied: {supplied}",
                code="store-assigned-fields",
            )
        if frozen_head >= CLOUD_EVENTS_INTEGER_MAX:
            raise ModelCallError("global event sequence is exhausted", code="sequence-exhausted")
        preflight_document = dict(draft)
        preflight_document.update(
            {
                "sequence": str(frozen_head + 1),
                "sequencetype": "Integer",
                "streamversion": 0,
            }
        )
        preflight_event = _validate_preflight_event(preflight_document)
        if preflight_event.data.project_id != self._project_id:
            raise ModelCallError(
                "event projectId does not match this ModelCallControl",
                code="project-mismatch",
            )
        apply_call_fold(head.fold, preflight_event, project_id=self._project_id)
        return self._store.append(draft, expected_last_sequence=frozen_head)


def apply_call_fold(fold: CallFold, event: ResearchEvent, *, project_id: str) -> CallFold:
    if event.data.project_id != project_id:
        return fold
    if event.type not in {TYPE_AI_CALL_STARTED, TYPE_AI_CALL_COMPLETED, TYPE_AI_CALL_FAILED}:
        return fold
    require_ai_actor(event)
    payload = parse_ai_call_payload(event)
    if isinstance(payload, AiCallStartedPayload):
        return _apply_started(fold, payload.call_id)
    if isinstance(payload, (AiCallCompletedPayload, AiCallFailedPayload)):
        return _apply_terminal(fold, payload.call_id)
    raise ModelCallError("ai.call payload type is not foldable", code="unknown-ai-call-type")


def _apply_started(fold: CallFold, call_id: str) -> CallFold:
    if call_id in fold.open_calls or call_id in fold.closed_calls:
        raise ModelCallError("callId is already recorded", code="duplicate-call-id")
    return CallFold(open_calls=fold.open_calls | {call_id}, closed_calls=fold.closed_calls)


def _apply_terminal(fold: CallFold, call_id: str) -> CallFold:
    if call_id in fold.closed_calls:
        raise ModelCallError("callId is already complete", code="duplicate-call-id")
    if call_id not in fold.open_calls:
        raise ModelCallError("ai.call completion has no matching start", code="orphan-call-id")
    return CallFold(
        open_calls=fold.open_calls - {call_id},
        closed_calls=fold.closed_calls | {call_id},
    )


def _require_matching_digests(fixture: ModelFixtureDocument, result: GenerateResult) -> None:
    if result.prompt_digest != content_digest(fixture.prompt):
        raise ModelCallError(
            "provider prompt digest does not match fixture",
            code="digest-mismatch",
        )
    if result.output_digest != content_digest(fixture.output):
        raise ModelCallError(
            "provider output digest does not match fixture",
            code="digest-mismatch",
        )


def _optional_artifacts(
    store: LocalArtifactStore | None,
    fixture: ModelFixtureDocument,
) -> tuple[str | None, str | None]:
    if store is None:
        return None, None
    prompt = store.put_bytes(canonical_json(fixture.prompt).encode("utf-8"))
    output = store.put_bytes(canonical_json(fixture.output).encode("utf-8"))
    return prompt.digest, output.digest


def _require_page_size(page_size: int) -> int:
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_READ_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be an integer in 1..{MAX_READ_PAGE_SIZE}")
    return page_size


def _validate_preflight_event(document: dict[str, Any]) -> ResearchEvent:
    try:
        validated = validate_event_document(document)
    except ValidationError:
        payload_error = ModelPayloadError(
            "event draft failed ResearchEvent validation",
            code="invalid-event",
        )
    else:
        return validated
    raise payload_error
