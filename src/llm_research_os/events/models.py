"""Pydantic authoring models for ResearchEvent v0alpha1.

The generated JSON Schema is the external, language-neutral contract. The envelope
follows CloudEvents 1.0 structured JSON mapping; versioned domain fields live in
``data``. Callers must supply identity, time and sequence explicitly; this validator
does not mint them.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from llm_research_os.spec.models import StrictModel

RESEARCH_EVENT_SCHEMA_ID = "https://researchos.dev/schemas/research-event/v0alpha1.schema.json"
CLOUD_EVENTS_INTEGER_MAX = 2_147_483_647
INLINE_BODY_KEYS = frozenset(
    {
        "body",
        "bytes",
        "content",
        "fileBytes",
        "inlineContent",
        "rawBody",
    }
)
RFC3339_AWARE_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
SEQUENCE_INTEGER_PATTERN = (
    r"^(?:[1-9][0-9]{0,8}|1[0-9]{9}|20[0-9]{8}|21[0-3][0-9]{7}|"
    r"214[0-6][0-9]{6}|2147[0-3][0-9]{5}|21474[0-7][0-9]{4}|"
    r"214748[0-2][0-9]{3}|2147483[0-5][0-9]{2}|21474836[0-3][0-9]|"
    r"214748364[0-7])$"
)
URI_REFERENCE_PATTERN = r"^(?:[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=]|%[0-9A-Fa-f]{2})+$"
_RFC3339_AWARE = re.compile(RFC3339_AWARE_PATTERN)
_JSON_ATOMS = (str, int, float, bool, type(None))
_URI_UNRESERVED_AND_RESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/?#[]@!$&'()*+,;="
)


def _is_cloudevents_forbidden_code_point(code: int) -> bool:
    return (
        code <= 0x1F
        or 0x7F <= code <= 0x9F
        or 0xD800 <= code <= 0xDFFF
        or 0xFDD0 <= code <= 0xFDEF
        or (code & 0xFFFE) == 0xFFFE
    )


def _require_cloudevents_string(value: str) -> str:
    if any(_is_cloudevents_forbidden_code_point(ord(char)) for char in value):
        raise ValueError(
            "CloudEvents strings must not contain control, noncharacter or surrogate code points"
        )
    return value


def _require_rfc3986_uri_reference(value: str) -> str:
    _require_cloudevents_string(value)
    index = 0
    length = len(value)
    while index < length:
        char = value[index]
        if char == "%":
            hex_digits = value[index + 1 : index + 3]
            if len(hex_digits) != 2 or any(
                digit not in "0123456789abcdefABCDEF" for digit in hex_digits
            ):
                raise ValueError("source is not an RFC 3986 URI-reference")
            index += 3
            continue
        if char not in _URI_UNRESERVED_AND_RESERVED:
            raise ValueError("source is not an RFC 3986 URI-reference")
        index += 1
    return value


def _require_rfc3339_timestamp(value: str) -> str:
    if not _RFC3339_AWARE.fullmatch(value):
        raise ValueError("time must be an RFC3339 timestamp string with a timezone")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("time must be a valid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("time must include a timezone")
    return value


def _require_event_payload(value: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("payload must be a JSON object")
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if type(current) is dict:
            blocked = sorted(key for key in current if key in INLINE_BODY_KEYS)
            if blocked:
                raise ValueError(
                    "payload must not embed file bytes or document bodies; "
                    f"forbidden keys: {blocked}"
                )
            for key, item in current.items():
                if type(key) is not str:
                    raise ValueError("payload keys must be JSON strings")
                stack.append(item)
        elif type(current) is list:
            stack.extend(current)
        elif isinstance(current, _JSON_ATOMS):
            continue
        else:
            raise ValueError(
                "payload must contain only JSON object, array, string, number, boolean or null"
            )
    try:
        json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ValueError(
            "value must contain only finite JSON-compatible Unicode scalar data"
        ) from exc
    return value


CloudEventsString = Annotated[
    str,
    StringConstraints(
        min_length=1,
        strip_whitespace=False,
        pattern=r"^[^\x00-\x1F\x7F-\x9F]+$",
    ),
    AfterValidator(_require_cloudevents_string),
]
CloudEventsUriReference = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=2048,
        strip_whitespace=False,
        pattern=URI_REFERENCE_PATTERN,
    ),
    AfterValidator(_require_rfc3986_uri_reference),
]
Rfc3339Timestamp = Annotated[
    str,
    StringConstraints(strip_whitespace=False, pattern=RFC3339_AWARE_PATTERN),
    AfterValidator(_require_rfc3339_timestamp),
    Field(json_schema_extra={"format": "date-time"}),
]
SequenceIntegerString = Annotated[
    str,
    StringConstraints(min_length=1, strip_whitespace=False, pattern=SEQUENCE_INTEGER_PATTERN),
]
EventIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        strip_whitespace=False,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
    AfterValidator(_require_cloudevents_string),
]
EventPayload = Annotated[dict[str, Any], AfterValidator(_require_event_payload)]
StreamVersion = Annotated[int, Field(ge=0, le=CLOUD_EVENTS_INTEGER_MAX)]
ExperimentRevision = Annotated[int, Field(ge=1, le=CLOUD_EVENTS_INTEGER_MAX)]


class EventDocumentModel(StrictModel):
    """External event documents accept schema aliases only and do not coerce or trim."""

    model_config = ConfigDict(
        populate_by_name=False,
        validate_by_name=False,
        validate_by_alias=True,
        str_strip_whitespace=False,
        strict=True,
    )


class EventActor(EventDocumentModel):
    """Closed actor identity. Additional actor facets are not part of v0alpha1."""

    id: EventIdentifier


class ResearchEventData(EventDocumentModel):
    """Versioned ResearchEvent domain payload carried in CloudEvents ``data``."""

    schema_version: Literal["v0alpha1"] = Field(alias="schemaVersion")
    actor: EventActor
    project_id: EventIdentifier = Field(alias="projectId")
    experiment_revision: ExperimentRevision = Field(alias="experimentRevision")
    run_id: EventIdentifier | None = Field(default=None, alias="runId")
    attempt_id: EventIdentifier | None = Field(default=None, alias="attemptId")
    block_id: EventIdentifier | None = Field(default=None, alias="blockId")
    payload: EventPayload
    evidence_refs: list[EventIdentifier] = Field(alias="evidenceRefs")

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidenceRefs entries must be unique")
        return self


class ResearchEvent(EventDocumentModel):
    """CloudEvents 1.0 compatible structured JSON envelope for ResearchEvent."""

    specversion: Literal["1.0"]
    id: CloudEventsString
    source: CloudEventsUriReference
    type: EventIdentifier
    time: Rfc3339Timestamp
    subject: CloudEventsString
    dataschema: Literal["https://researchos.dev/schemas/research-event/v0alpha1.schema.json"]
    datacontenttype: Literal["application/json"]
    data: ResearchEventData
    sequence: SequenceIntegerString
    sequencetype: Literal["Integer"]
    streamid: EventIdentifier
    streamversion: StreamVersion
    correlationid: CloudEventsString | None = None
    causationid: CloudEventsString | None = None


def validate_event_document(document: dict[str, Any]) -> ResearchEvent:
    """Validate an external ResearchEvent JSON document."""

    return ResearchEvent.model_validate(document)
