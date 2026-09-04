"""Typed SecretRef handles and redaction helpers (TM-007, TM-022)."""

from llm_research_os.secrets.models import (
    SECRET_REF_API_VERSION,
    SECRET_REF_SCHEMA_ID,
    SecretBackend,
    SecretRef,
)
from llm_research_os.secrets.redaction import REDACTED, message_without_secrets, redact_object
from llm_research_os.secrets.resolve import SecretResolutionError, resolve_secret
from llm_research_os.secrets.schema import build_schema

__all__ = [
    "REDACTED",
    "SECRET_REF_API_VERSION",
    "SECRET_REF_SCHEMA_ID",
    "SecretBackend",
    "SecretRef",
    "SecretResolutionError",
    "build_schema",
    "message_without_secrets",
    "redact_object",
    "resolve_secret",
]
