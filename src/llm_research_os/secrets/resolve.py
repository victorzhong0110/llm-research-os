"""Resolve a SecretRef without putting the secret value in errors (TM-007)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from llm_research_os.secrets.models import SecretBackend, SecretRef


class SecretResolutionError(RuntimeError):
    """Raised when a SecretRef cannot be resolved. Messages must not contain secret values."""


def resolve_secret(
    ref: SecretRef,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return the secret for an ``env`` backend. Other backends fail closed in M1-0."""

    if ref.backend is not SecretBackend.ENV:
        raise SecretResolutionError("secret backend is not supported")
    source = os.environ if environ is None else environ
    try:
        value = source[ref.name]
    except KeyError:
        raise SecretResolutionError("secret is not available") from None
    if type(value) is not str or value == "":
        raise SecretResolutionError("secret is not available")
    return value
