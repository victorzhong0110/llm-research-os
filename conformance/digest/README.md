# RFC 8785 digest conformance corpus

This directory freezes the M0 semantic JSON digest algorithm as:

- canonicalization: [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) JSON Canonicalization Scheme (JCS)
- digest: UTF-8 SHA-256 of that canonical text
- tagged form: `jcs-sha256:` followed by 64 lowercase hex digits

`rfc8785-v1.json` is the committed golden corpus. Python tests in
`tests/test_canonical.py` and the Node verifier in `verify.mjs` must consume
this same file. Do not generate expected digests at test time from only one
language.

## Node verifier

```bash
node conformance/digest/verify.mjs
```

The verifier is a standalone ECMAScript module. It uses `JSON.stringify` for
numbers and strings, recursively sorts object keys with `Object.keys().sort()`
(UTF-16 code units), and hashes with `node:crypto`. It must not call Python
and must not load npm packages.

CI runs this command from the existing workflow; it does not add a new GitHub
Action.

## Corpus fields

Each vector records:

| Field | Meaning |
|---|---|
| `algorithm` / `prefix` | Fixed as `jcs-sha256` / `jcs-sha256:` |
| `id` | Stable vector name |
| `input` | JSON value after ordinary `JSON.parse` / `json.loads` |
| `canonicalUtf8` | Exact RFC 8785 Unicode text (later UTF-8 encoded) |
| `digest` | `jcs-sha256:` + SHA-256 of that UTF-8 encoding |

The corpus covers RFC primitive examples, Appendix B numeric values, UTF-16
key ordering, Unicode preservation (NFC vs NFD), nested objects, and string
escapes.

JSON numbers that would overflow IEEE 754 exact integers are written with a
decimal (for example `9007199254740992.0`) so both `JSON.parse` and Python
`json.loads` yield an I-JSON number rather than a language-specific bigint.
`-0` is written as `-0.0` for the same reason.

## Out of scope

- SQLite schema v1 `event_json` / `event_digest` / `SCHEMA_DEFINITION_DIGEST`
  still use `legacy_canonical_json()` / `legacy_content_digest()` (`sha256:`).
- Artifact raw-byte digests remain `sha256:` and are not JCS.
- `sha256:<hex>` is accepted by `ContentDigest` only as a compatibility read
  of those legacy semantic identifiers. `content_digest()` never emits it.
