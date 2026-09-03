# ADR-0033: Normative JCS Semantic Digests

- Status: Accepted
- Implemented for review: 2026-09-02

## Context

M0 previously hashed semantic JSON with Python `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)` and tagged the SHA-256 as `sha256:<hex>`. That encoding is stable inside CPython 3.12+, but it is not a cross-language contract:

- Python renders `-0.0` and `1e-07`; ECMAScript JSON renders `0` and `1e-7`.
- Python sorts object keys by Unicode code point; RFC 8785 sorts by UTF-16 code units, so astral-plane keys diverge.
- Unlabeled `sha256:` collides in spelling with raw artifact byte digests and with SQLite schema v1 `event_digest`, which MUST remain on the historical encoding.

Issue #20 therefore requires a normative semantic-digest algorithm before independent implementations can recompute plan, registry, authorization and preflight identities.

## Decision

Adopt [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) JSON Canonicalization Scheme as the only producer algorithm for new semantic JSON digests.

- Preimage: RFC 8785 JCS text encoded as UTF-8.
- Hash: SHA-256.
- Tagged form: `jcs-sha256:<64 lowercase hex>`.
- Number syntax: ECMAScript binary64 shortest form, including RFC 8785 Appendix B.
- Object-key order: UTF-16 code units.
- Input profile: [RFC 7493](https://www.rfc-editor.org/rfc/rfc7493.html) I-JSON. `NaN`/`Infinity`, lone surrogates, non-JSON types and circular values fail closed. Integers outside `±9007199254740991` MUST NOT appear as JSON numbers; high-precision integers and amounts MUST be JSON strings.
- The tag is part of the algorithm identity. Implementations MUST NOT compare only hex, ignore prefixes, or treat `sha256:` as JCS.

Protocol models accept both `jcs-sha256:` and historical `sha256:` on input so committed compatibility fixtures can still parse. New producers MUST emit only `jcs-sha256:`. A legacy binding compared with a recomputed JCS digest MUST fail closed.

Permanent exceptions:

- SQLite schema v1 `event_json`, `event_digest` and `SCHEMA_DEFINITION_DIGEST` remain on `legacy_canonical_json()` / `legacy_content_digest()` (`sha256:`). Migrating them would rewrite every stored fact and the 71-character CHECK constraint.
- Raw artifact bytes remain `sha256:` of the file contents. They are not JSON and MUST NOT use `content_digest()`.

Conformance is a committed corpus plus a Python test and a standalone Node verifier (`node conformance/digest/verify.mjs`).

## Compatibility matrix

| Surface | Producer | Parser | Notes |
|---|---|---|---|
| Semantic JSON (spec, registry, plan, decision, preflight, run-state fields, …) | `jcs-sha256:` only | `jcs-sha256:` or legacy `sha256:` | Hex-only or prefix-stripping comparison is forbidden |
| SQLite schema v1 event rows / `SCHEMA_DEFINITION_DIGEST` | `sha256:` via `legacy_content_digest()` | `sha256:` only, 71 characters | Frozen on-disk format |
| Artifact raw bytes | `sha256:` of file bytes | `sha256:` only | Not JCS; path `objects/sha256/<ab>/<62 hex>` |

## Why not keep Python `json.dumps`

Independent JavaScript, Go or Rust implementations cannot reproduce CPython number rendering or code-point key order. Golden values generated from `json.dumps` would lock every consumer to Python. RFC 8785 already specifies the missing rules (UTF-16 key order, ES binary64, `-0` → `0`).

## Why not reuse unlabeled `sha256:`

`sha256:` already names two different preimages: historical Python-canonical JSON and raw artifact bytes. Reusing it for JCS would make a 64-hex collision look like an algorithm upgrade. The new tag makes fail-closed mismatch the default when an old binding is compared with a JCS digest.

## Why SQLite v1 is not migrated

Schema v1 CHECK constraints, stored `event_digest` values and `SCHEMA_DEFINITION_DIGEST` are an append-only freeze. Changing the algorithm would invalidate every existing database and would look like a silent rewrite of history. ADR-0015 remains authoritative for that on-disk encoding.

## Why raw artifacts are not migrated

Artifact identity is the SHA-256 of opaque bytes. JCS does not apply. Path derivation and `ArtifactObjectReport` stay on `sha256:`.

## High-precision numbers

JSON numbers are binary64. Values that need more precision than `±(2^53-1)`, including iteration counts that exceed that range, money, and other cross-language integers, MUST be JSON strings. The JCS encoder rejects oversized bare integers instead of silently rounding them.

## Consequences and version boundary

- Existing live-bound examples, Schema patterns and protocol JSON must be regenerated from the current reference implementation.
- v0alpha1 remains experimental; this is a breaking adjustment inside an unreleased contract, not a signed compatibility promise.
- Digests still are not signatures, authenticators, or a defense against a malicious host.
- Legacy `sha256:` compatibility reads are not algorithm agility.
- Frontend work and Issues #21–#24 (CLI split, JSON snapshot primitives, RunControl cost notes, diagnostic-code/title special cases) are out of scope.

## References

- [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html)
- [RFC 7493 The I-JSON Message Format](https://www.rfc-editor.org/rfc/rfc7493.html)
- [ECMA-262 JSON String / Number serialization](https://tc39.es/ecma262/)
- [Semantic Content Digests v0alpha1](../protocols/digest-v0alpha1.md)
- [Conformance corpus](../../conformance/digest/README.md)
- [Issue #20](https://github.com/victorzhong0110/llm-research-os/issues/20)
