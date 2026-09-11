"""HMAC-bound authorization grants. Tokens are never EventStore facts (TM-007, TM-009)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from llm_research_os.workers.errors import WorkerGrantError

_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

GRANT_TOKEN_VERSION = "rg1"  # noqa: S105
WORKER_SESSION_VERSION = "ws1"
HMAC_KEY_BYTES = 32
_KEY_ID = "local.hmac.1"


def require_hmac_key(key: bytes) -> bytes:
    if type(key) is not bytes or len(key) != HMAC_KEY_BYTES:
        raise WorkerGrantError("HMAC key must be 32 bytes", code="hmac-key-invalid")
    return key


def parse_rfc3339(value: str) -> datetime:
    if type(value) is not str:
        raise WorkerGrantError("timestamp must be an RFC3339 string", code="grant-exp-invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise WorkerGrantError("timestamp is not RFC3339", code="grant-exp-invalid") from None
    if parsed.tzinfo is None:
        raise WorkerGrantError("timestamp must be timezone-aware", code="grant-exp-invalid")
    return parsed.astimezone(UTC)


def format_rfc3339(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue_grant_token(
    key: bytes,
    *,
    grant_id: str,
    grant_event_id: str,
    worker_id: str,
    task_id: str,
    attempt_id: str,
    run_id: str,
    nonce: str,
    expires_at: str,
    project_id: str,
    image_digest: str,
    config_digest: str,
) -> str:
    """Bind grant identity to a worker, attempt, and execution object. Not a JWT."""

    require_hmac_key(key)
    claims = {
        "v": GRANT_TOKEN_VERSION,
        "keyId": _KEY_ID,
        "grantId": grant_id,
        "grantEventId": grant_event_id,
        "workerId": worker_id,
        "taskId": task_id,
        "attemptId": attempt_id,
        "runId": run_id,
        "nonce": nonce,
        "exp": expires_at,
        "projectId": project_id,
        "imageDigest": image_digest,
        "configDigest": config_digest,
    }
    return _sign(key, GRANT_TOKEN_VERSION, claims)


def peek_grant_token_image_digest(token: object) -> str:
    """Read imageDigest from a grant token without HMAC verification.

    Isolated GPU Workers use this only to run a pre-claim output probe
    against the digest the grant already names. Poll still authenticates
    the token on the control plane.
    """

    document = _decode_grant_payload(token)
    image_digest = document.get("imageDigest")
    if type(image_digest) is not str or _IMAGE_DIGEST.fullmatch(image_digest) is None:
        raise WorkerGrantError(
            "grant token is missing a required claim",
            code="grant-token-invalid",
        )
    return image_digest


def verify_grant_token(
    key: bytes, token: object, *, now: datetime, require_live: bool = True
) -> dict[str, str]:
    require_hmac_key(key)
    claims = _verify(key, GRANT_TOKEN_VERSION, token)
    expires_at = claims.get("exp")
    if type(expires_at) is not str:
        raise WorkerGrantError("grant token is missing exp", code="grant-token-invalid")
    if require_live and parse_rfc3339(expires_at) <= now.astimezone(UTC):
        raise WorkerGrantError("grant token has expired", code="grant-expired")
    required = (
        "grantId",
        "grantEventId",
        "workerId",
        "taskId",
        "attemptId",
        "runId",
        "nonce",
        "keyId",
        "projectId",
        "imageDigest",
        "configDigest",
    )
    for field in required:
        value = claims.get(field)
        if type(value) is not str or value == "":
            raise WorkerGrantError(
                "grant token is missing a required claim",
                code="grant-token-invalid",
            )
    if claims["keyId"] != _KEY_ID:
        raise WorkerGrantError("grant token keyId is unknown", code="grant-key-unknown")
    return {field: claims[field] for field in (*required, "exp")}


def issue_worker_session(key: bytes, *, worker_id: str) -> str:
    require_hmac_key(key)
    return _sign(key, WORKER_SESSION_VERSION, {"v": WORKER_SESSION_VERSION, "workerId": worker_id})


def verify_worker_session(key: bytes, token: object) -> str:
    require_hmac_key(key)
    claims = _verify(key, WORKER_SESSION_VERSION, token)
    worker_id = claims.get("workerId")
    if type(worker_id) is not str or worker_id == "":
        raise WorkerGrantError("worker session is invalid", code="worker-session-invalid")
    return worker_id


def _sign(key: bytes, version: str, claims: Mapping[str, str]) -> str:
    payload = _encode_payload(claims)
    mac = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{version}.{payload}.{mac}"


def _decode_grant_payload(token: object) -> dict[str, Any]:
    if type(token) is not str or token.count(".") != 2:
        raise WorkerGrantError("token encoding is invalid", code="grant-token-invalid")
    prefix, payload, _mac = token.split(".")
    if prefix != GRANT_TOKEN_VERSION:
        raise WorkerGrantError("token version is not supported", code="grant-token-invalid")
    try:
        document = json.loads(_decode_payload(payload))
    except (ValueError, json.JSONDecodeError):
        raise WorkerGrantError("token payload is not JSON", code="grant-token-invalid") from None
    if type(document) is not dict:
        raise WorkerGrantError("token payload must be an object", code="grant-token-invalid")
    return document


def _verify(key: bytes, version: str, token: object) -> dict[str, Any]:
    if type(token) is not str or token.count(".") != 2:
        raise WorkerGrantError("token encoding is invalid", code="grant-token-invalid")
    prefix, payload, mac = token.split(".")
    if prefix != version:
        raise WorkerGrantError("token version is not supported", code="grant-token-invalid")
    expected = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        raise WorkerGrantError("token HMAC does not match", code="grant-hmac-mismatch")
    try:
        document = json.loads(_decode_payload(payload))
    except (ValueError, json.JSONDecodeError):
        raise WorkerGrantError("token payload is not JSON", code="grant-token-invalid") from None
    if type(document) is not dict:
        raise WorkerGrantError("token payload must be an object", code="grant-token-invalid")
    return document


def _encode_payload(claims: Mapping[str, str]) -> str:
    body = json.dumps(dict(claims), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(body.encode("utf-8")).rstrip(b"=").decode("ascii")


def _decode_payload(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    try:
        return base64.urlsafe_b64decode(payload + padding)
    except ValueError:
        raise WorkerGrantError("token payload is not base64", code="grant-token-invalid") from None
