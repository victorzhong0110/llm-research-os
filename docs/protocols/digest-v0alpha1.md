# Semantic Content Digests v0alpha1

> Status: Normative cross-language protocol
>
> Algorithm: RFC 8785 JSON Canonicalization Scheme (JCS) over UTF-8, then SHA-256
>
> Tagged form: `jcs-sha256:<64 lowercase hex>`

Semantic JSON digests identify immutable protocol values: manifests, registries,
ResearchSpec snapshots, execution plans, authorization decisions, native
preflight contracts, and other JSON records that must compare equal across
implementations. This document is the language-neutral contract. The Python
package is a reference implementation, not a second encoding.

Raw artifact bytes and SQLite schema v1 event rows are **not** semantic JSON
digests. Their exceptions are listed below and MUST NOT be treated as JCS.

## 1. Algorithm identity

A new semantic digest is exactly:

```text
jcs-sha256: + lowercase hexadecimal SHA-256 of the UTF-8 encoding of RFC 8785 JCS text
```

- Canonicalization: [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) JSON Canonicalization Scheme.
- Preimage: the JCS Unicode text encoded as UTF-8 bytes. Implementations MUST NOT hash a UTF-16, Latin-1, or Python `str` representation that is not that UTF-8 sequence.
- Hash: SHA-256.
- Tag: `jcs-sha256:` is part of the algorithm identity. Comparing only the 64 hex digits, stripping the prefix, or treating `sha256:` and `jcs-sha256:` as aliases is forbidden.
- Length: `jcs-sha256:` plus 64 lowercase hex digits is 75 characters.

`content_digest(value)` in the reference implementation MUST emit only this form.

## 2. Input profile

JCS input MUST be an I-JSON value as profiled by [RFC 7493](https://www.rfc-editor.org/rfc/rfc7493.html):

- objects, arrays, strings, booleans, `null`, and finite IEEE 754 binary64 numbers;
- object keys MUST be strings;
- numbers MUST be finite; `NaN` and `±Infinity` are rejected;
- `-0` and `+0` both canonicalize to `0`;
- integers that are not exactly representable as binary64 (`|n| > 9007199254740991`) MUST NOT appear as JSON numbers;
- high-precision integers, currency amounts, and other values that cannot be expressed safely across languages MUST be JSON strings;
- Unicode is preserved without NFC/NFD/NFKC/NFKD normalization;
- lone UTF-16 surrogates are invalid protocol text and are rejected before encoding;
- circular structures and non-JSON types (bytes, tuples, sets, host objects) are rejected.

ECMAScript `JSON.stringify` number rendering (shortest round-trippable binary64) is the
normative number syntax. Implementations MUST match RFC 8785 Appendix B bit-pattern
vectors, including `9007199254740992` rendered from the float `9007199254740992.0`.

Object members are sorted by UTF-16 code units of the key, as required by RFC 8785
§3.2.3. Astral-plane keys therefore sort by their UTF-16 surrogate pairs, not by
Unicode code-point order.

## 3. Compatibility reads of legacy `sha256:`

Historical semantic identifiers used:

```text
sha256:<64 lowercase hex>
```

That 71-character form MAY be parsed by protocol models as a compatibility input.
It MUST NOT be produced by new code. It MUST NOT be silently interpreted as JCS.

When a stored or supplied `sha256:` binding is compared with a currently
recomputed `jcs-sha256:` digest, the values MUST fail closed. Matching hex
payloads under different tags are still unequal. Implementations MUST NOT ignore
the prefix or compare only hex.

`ContentDigest`, authorization/preflight digest fields, and `RunSnapshot`
digest fields therefore accept:

```text
^(?:jcs-sha256|sha256):[0-9a-f]{64}$
```

Producers still emit only `jcs-sha256:`.

## 4. Permanent exceptions

### SQLite schema v1

The following remain on the historical Python `json.dumps` encoding forever:

- `EventStore.event_json`
- `EventStore.event_digest`
- `SCHEMA_DEFINITION_DIGEST`

They MUST continue to use `legacy_canonical_json()` / `legacy_content_digest()`.
The SQLite `event_digest` CHECK still requires exactly 71 characters with the
`sha256:` prefix. `SCHEMA_DEFINITION_DIGEST` remains:

```text
sha256:dfdfe1bc8233723bfd164f488779428eeae72e4d4b0efa7128abf25e333bd1f1
```

This is an on-disk schema freeze, not an algorithm upgrade path. Legacy event
digests do not become JCS by dropping the prefix.

### Raw artifact bytes

Artifact object identity hashes **raw file bytes**, not canonical JSON. The only
legal artifact digest is:

```text
sha256:<64 lowercase hex>
```

`ArtifactObjectReport`, artifact Schema, path derivation
(`objects/sha256/<ab>/<62 hex>`), and artifact tests MUST keep that grammar.
`content_digest()` MUST NOT be used as an artifact preimage.

## 5. Digest preimages

| Digest | Preimage |
|---|---|
| Manifest | Complete normalized BlockManifest object |
| Registry | ID-sorted list of `{id, version, manifestDigest}` entries |
| Spec | Complete normalized ResearchSpec object |
| Plan | Complete normalized ExecutionPlan after removing its `specDigest` field |
| Authorization decision | Normalized status, digest triple, and sorted dispositions |
| Native preflight | Normalized non-launchable launch-review contract |
| Config/prompt/expression | The normalized JSON value or string itself |

`planDigest` identifies the planner's semantic projection, not the whole
experiment. Its deliberate exclusion of `specDigest` lets irrelevant source-list
ordering produce the same plan. A cache, approval or future Run identity MUST
therefore bind the complete tuple `(specDigest, registryDigest, planDigest)`
rather than `planDigest` alone.

## 6. Conformance

The committed corpus is `conformance/digest/rfc8785-v1.json`. Python tests in
`tests/test_canonical.py` and the standalone Node verifier MUST consume that
same file. Expected digests MUST NOT be generated at test time from only one
language.

```bash
node conformance/digest/verify.mjs
```

The Node verifier uses `JSON.stringify` for numbers and strings, recursively
sorts object keys with `Object.keys().sort()` (UTF-16 code units), and hashes
with `node:crypto`. It MUST NOT call Python and MUST NOT load npm packages.

CI runs this command from the existing workflow.

## 7. Security claims

These digests detect accidental substitution and encoding drift. They are not
signatures, authenticators, keyed MACs, or a defense against a malicious host
that can rewrite files and recompute hashes. Legacy `sha256:` compatibility
reads are not an algorithm-agility upgrade.
