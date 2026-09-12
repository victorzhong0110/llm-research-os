# AuthorizationAttestation v0alpha1

An independently verifiable signature over an existing authorization audit fact.
This document is public evidence, **not an execution credential**.

Schema: [v0alpha1.schema.json](../../schemas/authorization-attestation/v0alpha1.schema.json).
Decision: [ADR-0061](../adr/0061-detached-authorization-attestations.md).

## Wire contract

The closed top-level object contains `claims` and `signature`. Signature encoding
is exactly 128 lowercase hexadecimal characters (64 raw bytes). The claims are:

| Field | Meaning |
| --- | --- |
| apiVersion / kind | researchos.dev/v0alpha1 / AuthorizationAttestation |
| algorithm | Ed25519; other algorithms are rejected |
| receiptId / keyId | Caller-owned receipt identity and externally trusted key identity |
| audience / projectId | Exact expected receiver scope and project |
| eventId / eventDigest | Stored fact identity and JCS digest of its full serialized envelope |
| binding | specDigest, registryDigest, planDigest and decisionDigest |
| issuedAt / expiresAt | Aware RFC3339 timestamps; 0 < lifetime <= 24 hours |
| authority | audit-attestation-only |

The signed message is the ASCII prefix `researchos.authorization-attestation.v0alpha1`,
one NUL byte, then UTF-8 RFC 8785 canonical JSON of `claims`. Verification includes
the prefix. Reordering JSON properties does not invalidate a receipt; changing a
claim does. Public keys, private keys and algorithm-selected key URLs are not
allowed inside the receipt.
Duplicate JSON object keys are rejected before verification.

## Explicit CLI use

Run within a private directory whose parents exist. Commands do not create or
approve a research plan. Replace the event id, project id and expiry with values
from your existing store and a time within the next 24 hours.

```bash
researchos authorizations keygen signing.key signing.pub
researchos authorizations sign EVENT_ID research.db \
  --private-key signing.key --key-id signing.1 --receipt-id attestation.1 \
  --audience research.audit --expires-at RFC3339_EXPIRY --output attestation.json
researchos authorizations verify-signature attestation.json research.db \
  --public-key signing.pub --key-id signing.1 --audience research.audit \
  --project PROJECT_ID
```

`signing.key` must be owner-only and owned by the calling user; keygen creates
both raw key files with mode 0600. It prints no key bytes. Distribute only the
public key through an independently trusted channel; a key delivered with an
untrusted receipt must not automatically become trusted. Never reuse an SSH,
TLS or Worker HMAC private key for this protocol.

Pass `--revoked-key-id ID` or `--revoked-receipt-id ID` repeatedly to apply the
operator's current revocation snapshot. Omitting them means an empty snapshot;
there is no implicit network revocation lookup. A success report explicitly has
`launchAllowed: false`. Exit 2 rejects malformed, expired, revoked, mismatched or
unverifiable input, without printing private key material.

The EventStore must already contain the fact and pass integrity verification.
Signing/verification does not append events or edit their audit-only flags. A
receipt can also be stored as ordinary CAS evidence through existing artifact
commands; storing it does not activate it as a Worker grant.

## Native execution boundary

NativeProcessPreflight remains non-launching. Native execution still needs
reviewed identity binding, environment/working-directory limits, supervision,
cancel/unknown semantics and explicit authority; this attestation does not
substitute for those gates. Issue #53 remains open for that remaining path.
