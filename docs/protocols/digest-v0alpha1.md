# Reference Content Digests v0alpha1

> Status: Python reference-implementation convention, not yet a cross-language contract

M0 uses tagged SHA-256 values such as `sha256:...` to make accidental substitution and
non-determinism visible. These digests are stable inside the Python 3.12+ reference
implementation, but v0alpha1 deliberately does **not** claim that an independent JavaScript,
Rust or Go implementation can reproduce them yet.

## Reference encoding

The reference implementation first converts protocol models with Pydantic JSON-mode,
external aliases and omitted `None` fields. It then calls Python `json.dumps` with:

- `allow_nan=False`;
- `ensure_ascii=False`;
- `separators=(",", ":")`;
- `sort_keys=True`.

The resulting Unicode string is UTF-8 encoded and hashed with SHA-256. The lowercase
hexadecimal result is prefixed with `sha256:`. This rule inherits Python's number rendering;
for example it emits `1e-07` and `-0.0`. That differs from ECMAScript JSON serialization.
Lone Unicode surrogates are invalid protocol text and are rejected before encoding.

Golden vectors are committed in `tests/test_canonical.py`, including primitive JSON plus
the built-in manifest, registry, minimal ResearchSpec and its compiled plan.

## Digest preimages

| Digest | Reference preimage |
|---|---|
| Manifest | Complete normalized BlockManifest object |
| Registry | ID-sorted list of `{id, version, manifestDigest}` entries |
| Spec | Complete normalized ResearchSpec object |
| Plan | Complete normalized ExecutionPlan after removing its `specDigest` field |
| Config/prompt/expression | The normalized JSON value or string itself |

`planDigest` identifies the planner's semantic projection, not the whole experiment. Its
deliberate exclusion of `specDigest` lets irrelevant source-list ordering produce the same
plan. A cache, approval or future Run identity MUST therefore bind the complete tuple
`(specDigest, registryDigest, planDigest)` rather than `planDigest` alone.

Before a stable multi-language protocol release, this convention must be replaced or
superseded by a normative cross-language canonicalization decision, with RFC 8785/JCS as the
leading candidate. Until then, non-Python consumers should treat these values as opaque
reference-generated identifiers.
