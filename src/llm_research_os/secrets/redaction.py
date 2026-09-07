"""Redact secret-bearing keys and known secret values from diagnostic objects (TM-007, TM-022)."""

from __future__ import annotations

from typing import Any

REDACTED = "[redacted]"
_SECRET_KEYS = frozenset(
    {
        "password",
        "token",
        "secret",
        "apikey",
        "api_key",
        "authorization",
        "accesstoken",
        "access_token",
        "privatekey",
        "private_key",
    }
)


def redact_object(value: object, *, secret_values: tuple[str, ...] = ()) -> object:
    """Return a JSON-safe copy with secret keys and known values replaced."""

    secrets = tuple(item for item in secret_values if type(item) is str and item)
    return _redact(value, secrets, set())


def message_without_secrets(message: str, *secret_values: str) -> str:
    """Replace known secret substrings in an error or log line."""

    redacted = message
    for secret in secret_values:
        if type(secret) is str and secret:
            redacted = redacted.replace(secret, REDACTED)
    return redacted


def _redact(value: object, secrets: tuple[str, ...], seen: set[int]) -> object:
    if type(value) is str:
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, REDACTED)
        return redacted
    if type(value) is dict:
        identity = id(value)
        if identity in seen:
            return REDACTED
        seen.add(identity)
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = key if type(key) is str else str(key)
            if type(key) is str and key.casefold() in _SECRET_KEYS:
                result[key_text] = REDACTED
                continue
            result[key_text] = _redact(item, secrets, seen)
        seen.discard(identity)
        return result
    if type(value) is list:
        identity = id(value)
        if identity in seen:
            return REDACTED
        seen.add(identity)
        result_list = [_redact(item, secrets, seen) for item in value]
        seen.discard(identity)
        return result_list
    return value
