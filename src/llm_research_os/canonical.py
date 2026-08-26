"""Canonical JSON and content digests used by immutable M0 records."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

from pydantic import StringConstraints

ContentDigest = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^sha256:[0-9a-f]{64}$",
    ),
]


def canonical_json(value: Any) -> str:
    """Return compact, deterministic JSON without accepting non-finite numbers."""

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


def content_digest(value: Any) -> str:
    """Return a tagged SHA-256 digest for a JSON-compatible value."""

    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
