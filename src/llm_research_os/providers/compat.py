"""OpenAI-compatible HTTP ModelProvider and recording. Local loopback is the default."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from email.message import Message
from typing import IO, Any
from urllib.parse import urlparse

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.budget.control import BudgetControl
from llm_research_os.budget.errors import BudgetExceededError
from llm_research_os.budget.models import (
    TYPE_BUDGET_CONSUMED,
    TYPE_BUDGET_EXCEEDED,
    TYPE_BUDGET_RELEASED,
    TYPE_BUDGET_RESERVED,
)
from llm_research_os.budget.money import CURRENCY_CNY, parse_money
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.providers.capabilities import CapabilityReport, ModelCapability
from llm_research_os.providers.compat_requests import (
    COMPAT_PROVIDER_ID,
    OpenAICompatGenerateRequestDocument,
    endpoint_is_loopback,
)
from llm_research_os.providers.errors import (
    ModelCallError,
    ModelCapabilityError,
    ModelFixtureError,
    ModelTransportError,
)
from llm_research_os.providers.models import ModelFixtureDocument
from llm_research_os.providers.provider import (
    GenerateRequest,
    GenerateResult,
    ModelIdentity,
    ModelProvider,
)
from llm_research_os.secrets.redaction import message_without_secrets
from llm_research_os.storage.errors import EventStoreError
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore

_COMPAT_CAPABILITIES = frozenset({ModelCapability.GENERATE})
_COMPAT_REPORT = CapabilityReport(
    declared=_COMPAT_CAPABILITIES,
    measured=_COMPAT_CAPABILITIES,
    allowed=_COMPAT_CAPABILITIES,
)
MAX_RESPONSE_BYTES = 1_048_576
TIMEOUT_SECONDS = 10.0
Transport = Callable[[str, bytes, Mapping[str, str]], dict[str, Any]]


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise ModelTransportError("HTTP redirects are not allowed", code="redirect-forbidden")


def _urllib_transport(url: str, payload: bytes, headers: Mapping[str, str]) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ModelTransportError("endpoint scheme must be http or https", code="endpoint-scheme")
    request = urllib.request.Request(url, data=payload, method="POST")  # noqa: S310
    for name, value in headers.items():
        request.add_header(name, value)
    opener = urllib.request.build_opener(
        _RejectRedirects,
        urllib.request.ProxyHandler({}),
    )
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except ModelTransportError:
        raise
    except urllib.error.URLError:
        raise ModelTransportError("model endpoint could not be reached", code="transport") from None
    except TimeoutError:
        raise ModelTransportError("model endpoint timed out", code="transport-timeout") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ModelTransportError("model response exceeds size limit", code="response-too-large")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelTransportError("model response is not JSON", code="invalid-response") from None
    if type(parsed) is not dict:
        raise ModelTransportError("model response is not a JSON object", code="invalid-response")
    return parsed


class CompatHttpProvider(ModelProvider):
    """POST /chat/completions on an OpenAI-compatible endpoint. No vendor SDK types leak."""

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        secret: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._model_id = model_id
        self._secret = secret
        self._transport = transport or _urllib_transport
        self._local = endpoint_is_loopback(endpoint)
        if self._local:
            if secret is not None:
                raise ModelTransportError(
                    "loopback endpoints must not use a secret",
                    code="local-secret-forbidden",
                )
        elif secret is None:
            raise ModelTransportError(
                "remote endpoints require a resolved secret",
                code="remote-secret-required",
            )

    def __repr__(self) -> str:
        return f"CompatHttpProvider(endpoint={self._endpoint!r}, model_id={self._model_id!r})"

    def identity(self) -> ModelIdentity:
        return ModelIdentity(
            provider_id=COMPAT_PROVIDER_ID,
            model_id=self._model_id,
            local=self._local,
            cost_known=self._local,
            data_leaves_machine=not self._local,
            context_tokens=8192,
            max_output_tokens=1024,
            endpoint=self._endpoint,
        )

    def capabilities(self) -> CapabilityReport:
        return _COMPAT_REPORT

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if not request.requested <= _COMPAT_REPORT.allowed:
            raise ModelCapabilityError(
                "requested capability is not allowed",
                code="capability-not-allowed",
            )
        if not request.requested:
            raise ModelCapabilityError(
                "requested capability set is empty",
                code="capability-empty",
            )
        raise ModelFixtureError(
            "HTTP adapter generate requires the fixture document",
            code="fixture-required",
        )

    def generate_fixture(self, fixture: ModelFixtureDocument) -> GenerateResult:
        prompt_digest = content_digest(fixture.prompt)
        url = _chat_completions_url(self._endpoint)
        body = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": canonical_json(fixture.prompt)}],
            "max_tokens": 1024,
        }
        payload = canonical_json(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._secret is not None:
            headers = {**headers, "Authorization": f"Bearer {self._secret}"}
        try:
            parsed = self._transport(url, payload, headers)
            text = _completion_text(parsed)
        except ModelTransportError as exc:
            raise ModelTransportError(
                message_without_secrets(str(exc), self._secret or ""),
                code=exc.code,
            ) from None
        output_payload: dict[str, object] = {"text": text}
        return GenerateResult(
            prompt_digest=prompt_digest,
            output_digest=content_digest(output_payload),
            capabilities=_COMPAT_REPORT,
            output_payload=output_payload,
        )


def record_compat_generate(
    *,
    store: EventStore,
    project_id: str,
    append_call: Callable[[dict[str, Any]], StoredEvent],
    request: object,
    fixture: ModelFixtureDocument,
    provider: CompatHttpProvider,
    artifacts: LocalArtifactStore | None,
) -> tuple[StoredEvent, StoredEvent, StoredEvent, StoredEvent | None]:
    if not isinstance(request, OpenAICompatGenerateRequestDocument):
        raise ModelCallError("request is not an HTTP generate document", code="invalid-request")
    if request.project_id != project_id:
        raise ModelCallError(
            "request projectId does not match this ModelCallControl",
            code="project-mismatch",
        )
    if request.provider_id != COMPAT_PROVIDER_ID:
        raise ModelCallError("provider is not the HTTP adapter", code="provider-not-compat")
    if fixture.id != request.fixture_id:
        raise ModelCallError("fixture id does not match the request", code="fixture-id-mismatch")
    identity = provider.identity()
    if request.actor.model_id != identity.model_id:
        raise ModelCallError("actor modelId does not match the provider", code="model-id-mismatch")
    if identity.provider_id != COMPAT_PROVIDER_ID:
        raise ModelCallError(
            "provider identity is not the HTTP adapter",
            code="provider-not-compat",
        )
    if request.endpoint != identity.endpoint:
        raise ModelCallError(
            "request endpoint does not match the provider",
            code="endpoint-mismatch",
        )
    generate_request = request.generate_request()
    if not generate_request.requested <= provider.capabilities().allowed:
        raise ModelCapabilityError(
            "requested capability is not allowed",
            code="capability-not-allowed",
        )
    if not generate_request.requested:
        raise ModelCapabilityError(
            "requested capability set is empty",
            code="capability-empty",
        )
    budget = BudgetControl(store, project_id=project_id)
    head = budget.rebuild()
    cap = parse_money(request.budget_cap)
    reserve = parse_money(request.reserve_amount)
    if head.fold.consumed + head.fold.outstanding + reserve > cap:
        budget.append(
            request.budget_draft(
                TYPE_BUDGET_EXCEEDED,
                {
                    "budgetId": request.budget_id,
                    "callId": request.call_id,
                    "currency": CURRENCY_CNY,
                    "attempted": request.reserve_amount,
                    "cap": request.budget_cap,
                },
            )
        )
        raise BudgetExceededError()
    reserved = budget.append(
        request.budget_draft(
            TYPE_BUDGET_RESERVED,
            {
                "budgetId": request.budget_id,
                "callId": request.call_id,
                "currency": CURRENCY_CNY,
                "amount": request.reserve_amount,
                "cap": request.budget_cap,
            },
        )
    )
    report = provider.capabilities().document()
    declared = tuple(report["declaredCapabilities"])
    measured = tuple(report["measuredCapabilities"])
    allowed = tuple(report["allowedCapabilities"])
    try:
        started = append_call(
            request.started_draft(
                identity=identity,
                prompt_digest=content_digest(fixture.prompt),
                declared=declared,
                measured=measured,
                allowed=allowed,
            )
        )
    except (EventStoreError, ModelCallError):
        budget.append(_release_draft(request, reason_code="call-start-failed"))
        raise
    try:
        result = provider.generate_fixture(fixture)
    except ModelTransportError as exc:
        budget.append(_release_draft(request, reason_code=exc.code))
        append_call(request.failed_draft(reason_code=exc.code))
        raise
    if result.prompt_digest != content_digest(fixture.prompt):
        raise ModelCallError(
            "provider prompt digest does not match fixture",
            code="digest-mismatch",
        )
    if result.output_payload is None:
        raise ModelCallError("HTTP adapter returned no output payload", code="missing-output")
    if result.output_digest != content_digest(result.output_payload):
        raise ModelCallError(
            "provider output digest does not match payload",
            code="digest-mismatch",
        )
    prompt_artifact, output_artifact = _compat_artifacts(artifacts, fixture, result.output_payload)
    consumed: StoredEvent | None = None
    if identity.cost_known:
        consumed = budget.append(
            request.budget_draft(
                TYPE_BUDGET_CONSUMED,
                {
                    "budgetId": request.budget_id,
                    "callId": request.call_id,
                    "currency": CURRENCY_CNY,
                    "amount": request.consume_amount,
                    "cap": request.budget_cap,
                },
            )
        )
    completed = append_call(
        request.completed_draft(
            output_digest=result.output_digest,
            declared=declared,
            measured=measured,
            allowed=allowed,
            prompt_artifact=prompt_artifact,
            output_artifact=output_artifact,
        )
    )
    return started, completed, reserved, consumed


def _release_draft(
    request: OpenAICompatGenerateRequestDocument, *, reason_code: str
) -> dict[str, Any]:
    return request.budget_draft(
        TYPE_BUDGET_RELEASED,
        {
            "budgetId": request.budget_id,
            "callId": request.call_id,
            "currency": CURRENCY_CNY,
            "amount": request.reserve_amount,
            "cap": request.budget_cap,
            "reasonCode": reason_code,
        },
    )


def _chat_completions_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.username is not None or parsed.password is not None:
        raise ModelTransportError("endpoint must not contain userinfo", code="endpoint-userinfo")
    return endpoint.rstrip("/") + "/chat/completions"


def _completion_text(document: dict[str, Any]) -> str:
    choices = document.get("choices")
    if type(choices) is not list or not choices:
        raise ModelTransportError("model response has no choices", code="invalid-response")
    first = choices[0]
    if type(first) is not dict:
        raise ModelTransportError("model response has no choices", code="invalid-response")
    message = first.get("message")
    if type(message) is not dict:
        raise ModelTransportError("model response has no message", code="invalid-response")
    content = message.get("content")
    if type(content) is not str or content == "":
        raise ModelTransportError("model response has no text", code="invalid-response")
    return content


def _compat_artifacts(
    store: LocalArtifactStore | None,
    fixture: ModelFixtureDocument,
    output_payload: dict[str, object],
) -> tuple[str | None, str | None]:
    if store is None:
        return None, None
    prompt = store.put_bytes(canonical_json(fixture.prompt).encode("utf-8"))
    output = store.put_bytes(canonical_json(output_payload).encode("utf-8"))
    return prompt.digest, output.digest
