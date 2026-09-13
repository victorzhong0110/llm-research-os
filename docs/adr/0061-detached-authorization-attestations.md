# ADR-0061: Detached authorization fact attestations

Status: Accepted through PR #78. Scope: the signature-on-facts portion of Issue #53.

## Context

M1 authorization events deliberately declare approvalAuthentication=not-authenticated
and authority=audit-only. M2 adds HMAC-authenticated Worker grants and sessions,
expiry and revocation. Neither mechanism gives an independent holder of a public
key a signature over an authorization fact. Rewriting old events would invalidate
history and confuse fact authenticity with execution authority.

## Decision

Use cryptography's Ed25519 implementation for detached, versioned attestations.
Do not implement cryptographic primitives, accept algorithm negotiation, embed a
self-trusted public key, or treat a receipt as a JWT or Worker grant.

The signed bytes are a domain separator followed by RFC 8785 canonical JSON of
the complete claims object. Claims bind the JCS digest of the complete stored
event, its id, project, all plan/decision digests, a caller-owned receipt id,
key id, audience, issuance and expiry. Maximum lifetime is 24 hours. The event
digest includes source, sequence, actor and every payload/envelope field; it is
distinct from the store's legacy corruption-detection digest.

Sign only an already-authorized fact read from a verified existing EventStore.
Do not rewrite the event or mint a fresh plan authorization. Verification reads
the fact again, verifies its semantics, and requires an externally pinned public
key, key id, project, audience, timezone-aware clock and revocation snapshot.
Key and receipt revocation are checked before acceptance. Exact expiry is invalid.

CLI signing keys are 32-byte raw Ed25519 private keys in owner-only files. Public
keys are 32-byte raw keys distributed through an independently trusted channel.
Key/receipt file access rejects symbolic links, special files, multiply-linked
inputs and oversized files. Output creation is exclusive and never overwrites a
key or receipt. No sudo, network request or process launch is involved.

## Consequences

- A new AuthorizationAttestation v0alpha1 document/schema and explicit keygen,
  sign and verify-signature commands are added. Existing events, schemas and
  rg1/ws1 token formats retain their meaning.
- A successful signature authenticates possession of the pinned signing key and
  the signed fact bytes. It does not authenticate the event's asserted human
  actor, prove human authorship, or give the signer unbounded launch authority.
- Verification reports launchAllowed=false. Runtimes still require current plan
  authorization, Worker grant and their own execution policy. No implicit
  NativeProcessRuntime or unreviewed SSH execution is introduced.
- Revocation input is an operator-trusted snapshot, not an online freshness
  protocol. The CLI's omitted revocation flags mean an empty snapshot. Offline
  verification cannot prove that no later revocation exists; it is not a launch
  gate. M2's online grant revocation continues independently.
- Key generation does not activate a trust root. Rotation means distributing a
  newly pinned public key and retiring/revoking the old key in trust policy.
  Keygen writes two files; if the second write fails the first remains protected
  on disk, with no overwrite or automatic cleanup of an operator's key.
- The signing library becomes a locked core dependency. No hand-written crypto,
  external signing service, CA installation, live grant or paid call is added.

## Validation

Tests cover public-key verification, domain separation, each signed claim and
plan digest, changed keys, malformed receipts, validity boundaries, key/receipt
revocation, wrong project/audience, a valid signature over the wrong fact,
unmodified EventStore history, private-key permissions and path escapes.
Required Linux/macOS CI and existing authorization/Worker tests remain required.

Reference: [cryptography Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).
