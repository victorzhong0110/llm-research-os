from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.canonical import canonical_json
from llm_research_os.cli import main
from llm_research_os.cli.signature_commands import _read, _write_new
from llm_research_os.execution.authorization_signature_schema import build_schema, schema_matches
from llm_research_os.execution.authorization_signatures import (
    DOMAIN,
    AttestationClaims,
    AuthorizationAttestation,
    AuthorizationSignatureError,
    attest_authorization,
    verify_authorization_attestation,
)
from llm_research_os.m1.prove import prove_checkpoint
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


@pytest.fixture
def case(tmp_path: Path) -> tuple[Path, str, Ed25519PrivateKey, AuthorizationAttestation]:
    db = tmp_path / "facts.db"
    prove_checkpoint(ROOT / "examples/m1-checkpoint", db, decision="accept")
    key = Ed25519PrivateKey.generate()
    with EventStore(db, create=False) as store:
        event = next(
            x.event
            for x in store.read_events(limit=40)
            if x.event.type == "plan.authorization.evaluated"
        )
        receipt = attest_authorization(
            store,
            event.id,
            private_key=key,
            key_id="signer.1",
            receipt_id="receipt.1",
            audience="research.audit",
            expires_at="2026-09-12T13:00:00Z",
            now=NOW,
        )
    return db, event.id, key, receipt


def verify(
    case: tuple[Path, str, Ed25519PrivateKey, AuthorizationAttestation],
    document: object | None = None,
    **changes: Any,
) -> AttestationClaims:
    db, _, key, receipt = case
    kwargs: dict[str, Any] = dict(
        public_key=key.public_key(),
        key_id="signer.1",
        audience="research.audit",
        project_id=receipt.claims.project_id,
        revoked_key_ids=frozenset(),
        revoked_receipt_ids=frozenset(),
        now=NOW,
    )
    kwargs.update(changes)
    with EventStore(db, create=False) as store:
        return verify_authorization_attestation(
            store, receipt if document is None else document, **kwargs
        )


def test_roundtrip_is_publicly_verifiable_and_does_not_mutate_facts(case: Any) -> None:
    db, event_id, key, receipt = case
    with EventStore(db, create=False) as store:
        before = store.last_sequence(), store.get_event(event_id)
    assert verify(case) == receipt.claims
    message = canonical_json(receipt.claims.model_dump(mode="json", by_alias=True)).encode()
    key.public_key().verify(bytes.fromhex(receipt.signature), DOMAIN + message)
    with pytest.raises(InvalidSignature):
        key.public_key().verify(bytes.fromhex(receipt.signature), message)
    with EventStore(db, create=False) as store:
        assert (store.last_sequence(), store.get_event(event_id)) == before
    assert receipt.claims.authority == "audit-attestation-only"
    assert "private" not in receipt.model_dump_json().lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("receiptId", "receipt.other"),
        ("keyId", "signer.other"),
        ("audience", "other.audit"),
        ("projectId", "project.other"),
        ("eventId", "event.other"),
        ("eventDigest", "jcs-sha256:" + "1" * 64),
        ("issuedAt", "2026-09-12T11:59:00Z"),
        ("expiresAt", "2026-09-12T14:00:00Z"),
        ("algorithm", "none"),
        ("authority", "launch"),
        ("kind", "Grant"),
    ],
)
def test_each_claim_is_authenticated(case: Any, field: str, value: str) -> None:
    document = case[3].model_dump(mode="json", by_alias=True)
    document["claims"][field] = value
    with pytest.raises(AuthorizationSignatureError):
        verify(case, document)


@pytest.mark.parametrize("field", ["specDigest", "registryDigest", "planDigest", "decisionDigest"])
def test_every_plan_digest_is_authenticated(case: Any, field: str) -> None:
    document = case[3].model_dump(mode="json", by_alias=True)
    document["claims"]["binding"][field] = "jcs-sha256:" + "2" * 64
    with pytest.raises(AuthorizationSignatureError, match="signature"):
        verify(case, document)


@pytest.mark.parametrize(
    "changes",
    [
        {"key_id": "other"},
        {"audience": "other"},
        {"project_id": "other"},
        {"revoked_key_ids": frozenset({"signer.1"})},
        {"revoked_receipt_ids": frozenset({"receipt.1"})},
        {"revoked_receipt_ids": None},
        {"revoked_key_ids": []},
        {"now": NOW - timedelta(microseconds=1)},
        {"now": NOW + timedelta(hours=1)},
        {"now": NOW.replace(tzinfo=None)},
        {"public_key": b"untrusted"},
    ],
)
def test_trust_time_and_revocation_are_enforced(case: Any, changes: dict[str, Any]) -> None:
    with pytest.raises(AuthorizationSignatureError):
        verify(case, **changes)


def test_other_valid_key_cannot_verify(case: Any) -> None:
    with pytest.raises(AuthorizationSignatureError, match="signature"):
        verify(case, public_key=Ed25519PrivateKey.generate().public_key())


def test_resigned_wrong_fact_is_rejected(case: Any) -> None:
    document = case[3].model_dump(mode="json", by_alias=True)
    document["claims"]["eventDigest"] = "jcs-sha256:" + "3" * 64
    message = canonical_json(document["claims"]).encode()
    document["signature"] = case[2].sign(DOMAIN + message).hex()
    with pytest.raises(AuthorizationSignatureError, match="stored fact"):
        verify(case, document)


@pytest.mark.parametrize("expiry", ["2026-09-12T12:00:00Z", "2026-09-14T13:00:00Z", "invalid"])
def test_invalid_or_excessive_lifetime_cannot_be_signed(case: Any, expiry: str) -> None:
    with EventStore(case[0], create=False) as store, pytest.raises(ValidationError):
        attest_authorization(
            store,
            case[1],
            private_key=case[2],
            key_id="signer.1",
            receipt_id="receipt.2",
            audience="audit",
            expires_at=expiry,
            now=NOW,
        )


def test_missing_fact_cannot_be_attested(case: Any) -> None:
    with (
        EventStore(case[0], create=False) as store,
        pytest.raises(AuthorizationSignatureError, match="missing"),
    ):
        attest_authorization(
            store,
            "missing",
            private_key=case[2],
            key_id="signer.1",
            receipt_id="receipt.2",
            audience="audit",
            expires_at="2026-09-12T13:00:00Z",
            now=NOW,
        )


def test_schema_is_closed_and_current(case: Any) -> None:
    schema = build_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(case[3].model_dump(mode="json", by_alias=True))
    assert schema["additionalProperties"] is False
    assert schema_matches(ROOT / "schemas/authorization-attestation/v0alpha1.schema.json")


def test_cli_keygen_sign_verify_and_revocation(case: Any, tmp_path: Path, capsys: Any) -> None:
    private, public, output = [tmp_path / x for x in ("private.key", "public.key", "receipt.json")]
    assert main(["authorizations", "keygen", str(private), str(public)]) == 0
    assert private.stat().st_mode & 0o777 == 0o600
    original = private.read_bytes()
    assert main(["authorizations", "keygen", str(private), str(public)]) == 2
    assert private.read_bytes() == original
    capsys.readouterr()
    expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert (
        main(
            [
                "authorizations",
                "sign",
                case[1],
                str(case[0]),
                "--private-key",
                str(private),
                "--key-id",
                "signer.1",
                "--receipt-id",
                "receipt.cli",
                "--audience",
                "audit",
                "--expires-at",
                expiry,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    argv = [
        "authorizations",
        "verify-signature",
        str(output),
        str(case[0]),
        "--public-key",
        str(public),
        "--key-id",
        "signer.1",
        "--audience",
        "audit",
        "--project",
        case[3].claims.project_id,
    ]
    capsys.readouterr()
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["launchAllowed"] is False
    assert main([*argv, "--revoked-receipt-id", "receipt.cli"]) == 2
    assert original.hex() not in capsys.readouterr().err


def test_key_and_receipt_file_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "key"
    _write_new(path, b"x" * 32)
    assert _read(path, private=True) == b"x" * 32
    path.chmod(0o644)
    with pytest.raises(AuthorizationSignatureError, match="owner-only"):
        _read(path, private=True)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError, match=r"loop|links|symbolic"):
        _read(link)
    with pytest.raises(FileExistsError):
        _write_new(link, b"do not overwrite")
    hard = tmp_path / "hard"
    os.link(path, hard)
    with pytest.raises(AuthorizationSignatureError, match="regular file"):
        _read(hard)
    assert path.read_bytes() == b"x" * 32
    big = tmp_path / "large"
    big.write_bytes(b"x" * 16385)
    with pytest.raises(AuthorizationSignatureError, match="size limit"):
        _read(big)


def test_future_fact_and_invalid_signer_are_rejected(case: Any) -> None:
    kwargs = dict(
        key_id="signer.1",
        receipt_id="receipt.2",
        audience="audit",
        expires_at="2026-09-12T13:00:00Z",
    )
    with EventStore(case[0], create=False) as store:
        with pytest.raises(AuthorizationSignatureError, match="future"):
            attest_authorization(
                store, case[1], private_key=case[2], now=NOW - timedelta(days=365), **kwargs
            )
        with pytest.raises(AuthorizationSignatureError, match="private key"):
            attest_authorization(store, case[1], private_key=b"bad", now=NOW, **kwargs)


def test_constructed_receipt_does_not_bypass_validation(case: Any) -> None:
    forged = case[3].model_copy(update={"signature": "not-hex-private-value"})
    with pytest.raises(AuthorizationSignatureError) as error:
        verify(case, forged)
    assert "private-value" not in str(error.value)


def test_non_authorization_fact_is_not_signable(case: Any) -> None:
    with EventStore(case[0], create=False) as store:
        event = store.read_events(limit=1)[0]
        with pytest.raises(ValueError, match="type"):
            attest_authorization(
                store,
                event.event.id,
                private_key=case[2],
                key_id="signer.1",
                receipt_id="receipt.2",
                audience="audit",
                expires_at="2026-09-12T13:00:00Z",
                now=NOW,
            )


def test_intermediate_symlink_and_parent_traversal_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError, match=r"directory|loop|links"):
        _write_new(link / "key", b"secret")
    assert not (outside / "key").exists()
    with pytest.raises(AuthorizationSignatureError, match="path"):
        _write_new(outside / ".." / "key", b"secret")


def test_cli_rejects_private_file_with_group_access(case: Any, tmp_path: Path, capsys: Any) -> None:
    private = tmp_path / "private.key"
    private.write_bytes(case[2].private_bytes_raw())
    private.chmod(0o640)
    output = tmp_path / "output.json"
    assert (
        main(
            [
                "authorizations",
                "sign",
                case[1],
                str(case[0]),
                "--private-key",
                str(private),
                "--key-id",
                "signer.1",
                "--receipt-id",
                "receipt.1",
                "--audience",
                "audit",
                "--expires-at",
                "2026-09-12T13:00:00Z",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
    assert case[2].private_bytes_raw().hex() not in capsys.readouterr().err
