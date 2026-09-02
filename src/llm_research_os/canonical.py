"""Canonical JSON and content digests used by immutable M0 records."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Any

from pydantic import StringConstraints

JCS_SHA256_PREFIX = "jcs-sha256:"
LEGACY_SHA256_PREFIX = "sha256:"
SEMANTIC_DIGEST_PATTERN = r"^(?:jcs-sha256|sha256):[0-9a-f]{64}$"

# IEEE 754 binary64 exact-integer range from RFC 7493 / RFC 8785 Appendix B note 1.
_IJSON_SAFE_INTEGER = (1 << 53) - 1

_STRING_ESCAPES = {
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
    '"': '\\"',
    "\\": "\\\\",
}

ContentDigest = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=SEMANTIC_DIGEST_PATTERN,
    ),
]


def canonical_json(value: Any) -> str:
    """Serialize an I-JSON value using RFC 8785 JSON Canonicalization Scheme."""

    return _serialize_jcs(value, set())


def content_digest(value: Any) -> str:
    """Return an explicitly tagged JCS SHA-256 digest for a semantic JSON value."""

    encoded = canonical_json(value).encode("utf-8")
    return f"{JCS_SHA256_PREFIX}{hashlib.sha256(encoded).hexdigest()}"


def legacy_canonical_json(value: Any) -> str:
    """Return the Python-specific canonical form used by SQLite schema v1 records."""

    rendered = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        rendered.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("canonical JSON requires valid Unicode scalar values") from exc
    return rendered


def legacy_content_digest(value: Any) -> str:
    """Return the legacy Python-canonicalized digest used by SQLite schema v1."""

    encoded = legacy_canonical_json(value).encode("utf-8")
    return f"{LEGACY_SHA256_PREFIX}{hashlib.sha256(encoded).hexdigest()}"


def _serialize_jcs(value: Any, active_containers: set[int]) -> str:
    value_type = type(value)
    if value is None:
        return "null"
    if value_type is bool:
        return "true" if value else "false"
    if value_type is str:
        return _quote_string(value)
    if value_type is int:
        if not -_IJSON_SAFE_INTEGER <= value <= _IJSON_SAFE_INTEGER:
            raise ValueError("JCS integers must be exactly representable as IEEE 754 binary64")
        return str(value)
    if value_type is float:
        return _serialize_binary64(value)
    if value_type is list:
        return _serialize_array(value, active_containers)
    if value_type is dict:
        return _serialize_object(value, active_containers)
    raise TypeError(f"JCS value has unsupported type: {value_type.__name__}")


def _serialize_array(value: list[Any], active_containers: set[int]) -> str:
    marker = id(value)
    if marker in active_containers:
        raise ValueError("JCS value contains a circular reference")
    active_containers.add(marker)
    try:
        return "[" + ",".join(_serialize_jcs(item, active_containers) for item in value) + "]"
    finally:
        active_containers.remove(marker)


def _serialize_object(value: dict[Any, Any], active_containers: set[int]) -> str:
    marker = id(value)
    if marker in active_containers:
        raise ValueError("JCS value contains a circular reference")
    active_containers.add(marker)
    try:
        for key in value:
            if type(key) is not str:
                raise TypeError("JCS object keys must be strings")
            _validate_unicode(key)
        items = sorted(value.items(), key=lambda item: item[0].encode("utf-16-be"))
        members = (
            f"{_quote_string(key)}:{_serialize_jcs(item, active_containers)}" for key, item in items
        )
        return "{" + ",".join(members) + "}"
    finally:
        active_containers.remove(marker)


def _quote_string(value: str) -> str:
    """Quote a string per RFC 8785 §3.2.2.2 / ECMA-262 JSON String serialization."""

    _validate_unicode(value)
    parts = ['"']
    for char in value:
        escape = _STRING_ESCAPES.get(char)
        if escape is not None:
            parts.append(escape)
            continue
        code_point = ord(char)
        if code_point < 0x20:
            parts.append(f"\\u{code_point:04x}")
        else:
            parts.append(char)
    parts.append('"')
    return "".join(parts)


def _validate_unicode(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("JCS requires valid Unicode scalar values") from exc


def _serialize_binary64(value: float) -> str:
    """Render a finite binary64 using ECMAScript's shortest number syntax.

    The textual exponent normalization follows the Apache-2.0 WebPKI JCS
    reference implementation's ``NumberToJson.py`` algorithm:
    https://github.com/cyberphone/json-canonicalization
    """

    if not math.isfinite(value):
        raise ValueError("JCS numbers must be finite")
    if value == 0:
        return "0"

    rendered = str(value)
    if "n" in rendered:
        raise ValueError("JCS numbers must be finite")

    sign = ""
    if rendered[0] == "-":
        sign = "-"
        rendered = rendered[1:]

    exponent_text = ""
    exponent = 0
    exponent_at = rendered.find("e")
    if exponent_at > 0:
        exponent_text = rendered[exponent_at:]
        if len(exponent_text) > 2 and exponent_text[2] == "0":
            exponent_text = exponent_text[:2] + exponent_text[3:]
        rendered = rendered[:exponent_at]
        exponent = int(exponent_text[1:])

    first = rendered
    separator = ""
    last = ""
    dot_at = rendered.find(".")
    if dot_at > 0:
        separator = "."
        first = rendered[:dot_at]
        last = rendered[dot_at + 1 :]

    if last == "0":
        separator = ""
        last = ""

    if 0 < exponent < 21:
        first += last
        last = ""
        separator = ""
        exponent_text = ""
        pad = exponent - len(first)
        while pad >= 0:
            pad -= 1
            first += "0"
    elif -7 < exponent < 0:
        last = first + last
        first = "0"
        separator = "."
        exponent_text = ""
        pad = exponent
        while pad < -1:
            pad += 1
            last = "0" + last

    return sign + first + separator + last + exponent_text
