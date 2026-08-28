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
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)
SEQUENCE_INTEGER_PATTERN = (
    r"^(?:[1-9][0-9]{0,8}|1[0-9]{9}|20[0-9]{8}|21[0-3][0-9]{7}|"
    r"214[0-6][0-9]{6}|2147[0-3][0-9]{5}|21474[0-7][0-9]{4}|"
    r"214748[0-2][0-9]{3}|2147483[0-5][0-9]{2}|21474836[0-3][0-9]|"
    r"214748364[0-7])$"
)
_JSON_ATOMS = (str, int, float, bool, type(None))


def _rfc3986_uri_reference_pattern() -> str:
    """Return an RFC 3986 URI-reference pattern for Python and JSON Schema."""

    unreserved = r"[A-Za-z0-9._~-]"
    pct_encoded = r"%[0-9A-Fa-f]{2}"
    sub_delims = r"[!$&'()*+,;=]"
    pchar = rf"(?:{unreserved}|{pct_encoded}|{sub_delims}|[:@])"
    query_or_fragment = rf"(?:{pchar}|[/?])*"
    segment = rf"{pchar}*"
    segment_nz = rf"{pchar}+"
    segment_nz_nc = rf"(?:{unreserved}|{pct_encoded}|{sub_delims}|@)+"
    path_abempty = rf"(?:/{segment})*"
    path_absolute = rf"/(?:{segment_nz}(?:/{segment})*)?"
    path_noscheme = rf"{segment_nz_nc}(?:/{segment})*"
    path_rootless = rf"{segment_nz}(?:/{segment})*"
    dec_octet = r"(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])"
    ipv4 = rf"(?:{dec_octet}\.){{3}}{dec_octet}"
    h16 = r"[0-9A-Fa-f]{1,4}"
    ls32 = rf"(?:{h16}:{h16}|{ipv4})"
    ipv6 = (
        rf"(?:(?:{h16}:){{6}}{ls32}|"
        rf"::(?:{h16}:){{5}}{ls32}|"
        rf"(?:{h16})?::(?:{h16}:){{4}}{ls32}|"
        rf"(?:{h16}(?::{h16}){{0,1}})?::(?:{h16}:){{3}}{ls32}|"
        rf"(?:{h16}(?::{h16}){{0,2}})?::(?:{h16}:){{2}}{ls32}|"
        rf"(?:{h16}(?::{h16}){{0,3}})?::{h16}:{ls32}|"
        rf"(?:{h16}(?::{h16}){{0,4}})?::{ls32}|"
        rf"(?:{h16}(?::{h16}){{0,5}})?::{h16}|"
        rf"(?:{h16}(?::{h16}){{0,6}})?::)"
    )
    ipv_future = rf"v[0-9A-Fa-f]+\.(?:{unreserved}|{sub_delims}|:)+"
    ip_literal = rf"\[(?:{ipv6}|{ipv_future})\]"
    reg_name = rf"(?:{unreserved}|{pct_encoded}|{sub_delims})*"
    host = rf"(?:{ip_literal}|{ipv4}|{reg_name})"
    userinfo = rf"(?:{unreserved}|{pct_encoded}|{sub_delims}|:)*"
    authority = rf"(?:{userinfo}@)?{host}(?::[0-9]*)?"
    hier_part = rf"(?://{authority}{path_abempty}|{path_absolute}|{path_rootless}|)"
    relative_part = rf"(?://{authority}{path_abempty}|{path_absolute}|{path_noscheme}|)"
    scheme = r"[A-Za-z][A-Za-z0-9+.-]*"
    query = rf"(?:\?{query_or_fragment})?"
    fragment = rf"(?:#{query_or_fragment})?"
    uri = rf"{scheme}:{hier_part}{query}{fragment}"
    relative_ref = rf"{relative_part}{query}{fragment}"
    return rf"^(?:{uri}|{relative_ref})$"


URI_REFERENCE_PATTERN = _rfc3986_uri_reference_pattern()
_RFC3339_AWARE = re.compile(RFC3339_AWARE_PATTERN)
_URI_REFERENCE = re.compile(URI_REFERENCE_PATTERN)


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
    if _URI_REFERENCE.fullmatch(value) is None:
        raise ValueError("source is not an RFC 3986 URI-reference")
    return value


def _require_rfc3339_timestamp(value: str) -> str:
    if _RFC3339_AWARE.fullmatch(value) is None:
        raise ValueError("time must be an RFC3339 timestamp string with a timezone")
    if value.endswith("Z"):
        stamp = value[:-1]
    else:
        offset_hour = int(value[-5:-3])
        offset_minute = int(value[-2:])
        if offset_hour > 23 or offset_minute > 59:
            raise ValueError("time offset hours must be 00-23 and minutes 00-59")
        stamp = value[:-6]
    date_text, time_text = stamp.split("T")
    year, month, day = (int(part) for part in date_text.split("-"))
    clock = time_text.split(".", 1)[0]
    hour, minute, second = (int(part) for part in clock.split(":"))
    if hour > 23 or minute > 59 or second > 60:
        raise ValueError("time must use RFC3339 hour, minute and second ranges")
    try:
        datetime(year, month, day, hour, minute, min(second, 59))
    except ValueError as exc:
        raise ValueError("time must be a valid RFC3339 timestamp") from exc
    return value


def _require_event_payload(value: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("payload must be a JSON object")
    stack: list[tuple[object, Literal["enter", "leave"]]] = [(value, "enter")]
    path: set[int] = set()
    while stack:
        current, action = stack.pop()
        if type(current) is dict or type(current) is list:
            identity = id(current)
            if action == "leave":
                path.discard(identity)
                continue
            if identity in path:
                raise ValueError("payload must not contain cyclic JSON structures")
            path.add(identity)
            stack.append((current, "leave"))
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
                    stack.append((item, "enter"))
            else:
                for item in current:
                    stack.append((item, "enter"))
            continue
        if action == "leave":
            continue
        if isinstance(current, _JSON_ATOMS):
            continue
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
