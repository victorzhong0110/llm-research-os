"""Detached Ed25519 attestations of existing facts, never launch credentials."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import Field, StringConstraints, model_validator

from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.events.models import EventIdentifier, ResearchEvent, Rfc3339Timestamp
from llm_research_os.execution.authorization_events import (
    PlanAuthorizationEventBinding,
    PlanAuthorizationEventDocumentModel,
    validate_plan_authorization_evaluated_event,
)
from llm_research_os.storage import EventStore

SCHEMA_ID = "https://researchos.dev/schemas/authorization-attestation/v0alpha1.schema.json"
DOMAIN = b"researchos.authorization-attestation.v0alpha1\x00"
MAX_LIFETIME = timedelta(hours=24)
HexSignature = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{128}$", min_length=128, max_length=128)
]
FactDigest = Annotated[
    str, StringConstraints(pattern=r"^jcs-sha256:[0-9a-f]{64}$", min_length=75, max_length=75)
]


class AuthorizationSignatureError(ValueError):
    """Sanitized verification failure, safe to display without input values."""


class AttestationClaims(PlanAuthorizationEventDocumentModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["AuthorizationAttestation"]
    algorithm: Literal["Ed25519"]
    receipt_id: EventIdentifier = Field(alias="receiptId")
    key_id: EventIdentifier = Field(alias="keyId")
    audience: EventIdentifier
    project_id: EventIdentifier = Field(alias="projectId")
    event_id: str = Field(alias="eventId", min_length=1, max_length=1024)
    event_digest: FactDigest = Field(alias="eventDigest")
    binding: PlanAuthorizationEventBinding
    issued_at: Rfc3339Timestamp = Field(alias="issuedAt")
    expires_at: Rfc3339Timestamp = Field(alias="expiresAt")
    authority: Literal["audit-attestation-only"]

    @model_validator(mode="after")
    def bounded_lifetime(self) -> Self:
        lifetime = _instant(self.expires_at) - _instant(self.issued_at)
        if lifetime <= timedelta(0) or lifetime > MAX_LIFETIME:
            raise ValueError("attestation lifetime must be positive and at most 24 hours")
        return self


class AuthorizationAttestation(PlanAuthorizationEventDocumentModel):
    claims: AttestationClaims
    signature: HexSignature


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _clock(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise AuthorizationSignatureError("verification clock must be timezone-aware")
    return now.astimezone(UTC)


def _message(claims: AttestationClaims) -> bytes:
    return DOMAIN + canonical_json(claims.model_dump(mode="json", by_alias=True)).encode("utf-8")


def _fact(store: EventStore, event_id: str) -> ResearchEvent:
    # The store's legacy corruption digest is not the new JCS attestation digest.
    # Always re-read the full verified fact; never accept a caller's StoredEvent.
    store.verify_integrity()
    stored = store.get_event(event_id)
    if stored is None:
        raise AuthorizationSignatureError("authorization fact is missing")
    event = stored.event
    payload = validate_plan_authorization_evaluated_event(event)
    if not payload.authorized:
        raise AuthorizationSignatureError("authorization fact is not authorized")
    return event


def _fact_digest(event: ResearchEvent) -> str:
    # Includes source, sequence, actor, project and every envelope/payload field.
    return content_digest(event.model_dump(mode="json", by_alias=True))


def attest_authorization(
    store: EventStore,
    event_id: str,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    receipt_id: str,
    audience: str,
    expires_at: str,
    now: datetime,
) -> AuthorizationAttestation:
    """Attest an already-authorized fact without modifying it or issuing a grant."""
    instant = _clock(now)
    event = _fact(store, event_id)
    if _instant(event.time) > instant:
        raise AuthorizationSignatureError("authorization fact is in the future")
    payload = validate_plan_authorization_evaluated_event(event)
    claims = AttestationClaims.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "AuthorizationAttestation",
            "algorithm": "Ed25519",
            "receiptId": receipt_id,
            "keyId": key_id,
            "audience": audience,
            "projectId": event.data.project_id,
            "eventId": event.id,
            "eventDigest": _fact_digest(event),
            "binding": payload.binding.model_dump(mode="json", by_alias=True),
            "issuedAt": instant.isoformat().replace("+00:00", "Z"),
            "expiresAt": expires_at,
            "authority": "audit-attestation-only",
        }
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise AuthorizationSignatureError("an Ed25519 private key is required")
    return AuthorizationAttestation(
        claims=claims, signature=private_key.sign(_message(claims)).hex()
    )


def verify_authorization_attestation(
    store: EventStore,
    document: object,
    *,
    public_key: Ed25519PublicKey,
    key_id: str,
    audience: str,
    project_id: str,
    revoked_key_ids: frozenset[str],
    revoked_receipt_ids: frozenset[str],
    now: datetime,
) -> AttestationClaims:
    """Verify against caller-pinned trust and a trusted revocation snapshot.

    No key supplied inside a receipt is trusted. This verifies an audit fact;
    runtimes must still enforce their own grants and current authorization.
    """
    instant = _clock(now)
    if isinstance(document, AuthorizationAttestation):
        document = document.model_dump(mode="json", by_alias=True)
    try:
        receipt = AuthorizationAttestation.model_validate(document)
    except ValueError:
        raise AuthorizationSignatureError("invalid authorization attestation") from None
    claims = receipt.claims
    if not isinstance(public_key, Ed25519PublicKey):
        raise AuthorizationSignatureError("an Ed25519 public key is required")
    if type(revoked_key_ids) is not frozenset or type(revoked_receipt_ids) is not frozenset:
        raise AuthorizationSignatureError("explicit revocation snapshots are required")
    if (claims.key_id, claims.audience, claims.project_id) != (key_id, audience, project_id):
        raise AuthorizationSignatureError("attestation trust scope mismatch")
    if key_id in revoked_key_ids or claims.receipt_id in revoked_receipt_ids:
        raise AuthorizationSignatureError("attestation is revoked")
    if not (_instant(claims.issued_at) <= instant < _instant(claims.expires_at)):
        raise AuthorizationSignatureError("attestation is not currently valid")
    try:
        public_key.verify(bytes.fromhex(receipt.signature), _message(claims))
    except InvalidSignature:
        raise AuthorizationSignatureError("attestation signature is invalid") from None
    event = _fact(store, claims.event_id)
    payload = validate_plan_authorization_evaluated_event(event)
    if (
        _fact_digest(event) != claims.event_digest
        or event.data.project_id != claims.project_id
        or payload.binding != claims.binding
        or _instant(event.time) > _instant(claims.issued_at)
    ):
        raise AuthorizationSignatureError("attestation does not bind the stored fact")
    return claims
