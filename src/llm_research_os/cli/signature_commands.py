"""Explicit local key files and detached authorization attestations."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from llm_research_os.cli.output import dumps_json, print_error
from llm_research_os.execution.authorization_signatures import (
    AuthorizationSignatureError,
    attest_authorization,
    verify_authorization_attestation,
)
from llm_research_os.storage import EventStore, EventStoreError

MAX_DOCUMENT_BYTES = 16384


@contextmanager
def _parent(path: Path) -> Iterator[tuple[int, str]]:
    absolute = path.absolute()
    parts = absolute.parts[1:]
    if not parts or ".." in parts:
        raise AuthorizationSignatureError("invalid signature file path")
    fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


def _read(path: Path, *, private: bool = False) -> bytes:
    with _parent(path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise AuthorizationSignatureError(
                    "signature input must be a single-link regular file"
                )
            if private and (info.st_mode & 0o077 or info.st_uid != os.geteuid()):
                raise AuthorizationSignatureError("private key requires owner-only access")
            limit = 32 if private else MAX_DOCUMENT_BYTES
            value = stream.read(limit + 1)
            if len(value) > limit:
                raise AuthorizationSignatureError("signature input exceeds its size limit")
            return value


def _write_new(path: Path, value: bytes) -> None:
    with _parent(path) as (parent, name):
        fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())


def run_signature(args: argparse.Namespace) -> int:
    try:
        if args.authorizations_command == "keygen":
            key = Ed25519PrivateKey.generate()
            _write_new(args.private_key, key.private_bytes_raw())
            _write_new(args.public_key, key.public_key().public_bytes_raw())
            print(dumps_json({"kind": "AuthorizationKeyCreated", "algorithm": "Ed25519"}))
            return 0
        with EventStore(args.database, create=False) as store:
            if args.authorizations_command == "sign":
                private_key = Ed25519PrivateKey.from_private_bytes(
                    _read(args.private_key, private=True)
                )
                receipt = attest_authorization(
                    store,
                    args.event_id,
                    private_key=private_key,
                    key_id=args.key_id,
                    receipt_id=args.receipt_id,
                    audience=args.audience,
                    expires_at=args.expires_at,
                    now=datetime.now(UTC),
                )
                _write_new(
                    args.output,
                    (dumps_json(receipt.model_dump(mode="json", by_alias=True)) + "\n").encode(
                        "utf-8"
                    ),
                )
                print(
                    dumps_json(
                        {"kind": "AuthorizationAttestationWritten", "receiptId": args.receipt_id}
                    )
                )
            else:
                public_key = Ed25519PublicKey.from_public_bytes(_read(args.public_key))
                claims = verify_authorization_attestation(
                    store,
                    json.loads(_read(args.receipt)),
                    public_key=public_key,
                    key_id=args.key_id,
                    audience=args.audience,
                    project_id=args.project,
                    revoked_key_ids=frozenset(args.revoked_key_id),
                    revoked_receipt_ids=frozenset(args.revoked_receipt_id),
                    now=datetime.now(UTC),
                )
                print(
                    dumps_json(
                        {
                            "kind": "AuthorizationAttestationVerified",
                            "receiptId": claims.receipt_id,
                            "authority": claims.authority,
                            "launchAllowed": False,
                        }
                    )
                )
        return 0
    except (OSError, ValueError, EventStoreError):
        # Neither key material nor attacker-controlled document/path values enter errors.
        print_error(AuthorizationSignatureError("authorization signature operation failed"), "json")
        return 2


def add_signature_parsers(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    keygen = commands.add_parser("keygen", help="create owner-only Ed25519 raw key files")
    keygen.add_argument("private_key", type=Path)
    keygen.add_argument("public_key", type=Path)
    sign = commands.add_parser("sign", help="attest an existing authorization fact; not a grant")
    sign.add_argument("event_id")
    sign.add_argument("database", type=Path)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--receipt-id", required=True)
    sign.add_argument("--audience", required=True)
    sign.add_argument("--expires-at", required=True)
    sign.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser(
        "verify-signature", help="verify a fact with pinned public-key trust"
    )
    verify.add_argument("receipt", type=Path)
    verify.add_argument("database", type=Path)
    verify.add_argument("--public-key", type=Path, required=True)
    verify.add_argument("--key-id", required=True)
    verify.add_argument("--audience", required=True)
    verify.add_argument("--project", required=True)
    verify.add_argument("--revoked-key-id", action="append", default=[])
    verify.add_argument("--revoked-receipt-id", action="append", default=[])
