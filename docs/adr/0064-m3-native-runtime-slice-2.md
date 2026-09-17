# ADR-0064: M3 slice 2 — pinned identity, second profile, local Web onboarding

- Status: Proposed in this slice (M3 work, Issue #53)
- Date: 2026-09-17

This record does not close Issue #53, does not claim paid cloud, public MVP,
live SSH execution, or entrypoint execution. It scopes the second reviewable
M3 increment on top of [ADR-0063](0063-m3-native-process-runtime-slice-1.md).

## Context

Slice 1 runs a fixed noop helper under `restricted-v0alpha1` with the host
interpreter recorded by version only, and writes a pending-live SSH pack with
Markdown checklist files. Three gaps remain for M3 onboarding:

1. The interpreter binary and the exact spawn environment have no
   content-bound identity: a swapped binary or a mutated environment between
   review and spawn is undetectable at launch.
2. There is exactly one executable profile, so stricter local runs cannot be
   selected without changing the only profile's meaning.
3. Onboarding is Markdown-only; there is no operator-facing page foundation.

## Decision

Slice 2 delivers three small, CI-executable pieces with no paid cloud:

1. **Pinned interpreter and environment identity**
   (`execution/native_identity.py`): `resolve_interpreter_identity` digests
   the resolved interpreter binary (domain-separated SHA-256 over real path,
   version, and file bytes) and `environment_identity` digests the exact
   spawn environment mapping. Failures are `native-interpreter-unpinned` /
   `native-environment-unpinned` and carry no paths. A new profile,
   `restricted-v0alpha2`, re-resolves the interpreter immediately before
   `Popen` and refuses with `native-interpreter-changed` on any drift.
   Receipts carry `interpreterDigest`, `environmentDigest`, and
   `interpreterPinned` (`false` for v0alpha1, which keeps slice-1
   recorded-not-pinned semantics).
2. **Second restricted profile** (`restricted-v0alpha2`): identical argv,
   helper, cwd, env allowlist, caps, and supervision as v0alpha1, plus the
   pinning above. The profile registry (`NATIVE_RUNTIME_PROFILES`) is the
   single allowlist for `native run` and onboarding packs.
   `transport=ssh` stays validated-then-refused for every profile.
3. **Local Web onboarding foundation** (`execution/native_web.py`,
   `ssh-onboard --web`): an optional static `ONBOARDING.html` inside the
   pending-live pack. Pure file writer: no server, no JavaScript, no
   external resources, no network calls; all operator text is HTML-escaped
   and only the host-key *type* (never the body) is rendered. It is a
   `file://` checklist foundation, not a public service.

Entrypoint execution stays a documented non-goal for every local profile
(see the v0alpha2 protocol): it needs a module-digest allowlist bound at
preflight plus a mount jail, neither of which this slice builds.

## Consequences

- A swapped interpreter binary fails closed on v0alpha2 before any spawn;
  v0alpha1 behavior and receipt semantics are unchanged apart from additive
  digest fields.
- Profile selection is explicit and enumerable; unknown profiles still fail
  with `native-profile-invalid` / `ssh-profile-invalid`.
- Operators get a single-file page they can open locally; the page cannot
  exfiltrate anything because it has no script or network surface and never
  embeds key bodies.
- Threat model gains TM-066 (interpreter/swap) and TM-067 (web pack) in the
  same pull request. No new EventStore type, schema contract, or capability
  string is introduced.

## Validation

1. `tests/test_native_identity.py`: determinism, missing/empty binary
   refusal, drift refusal, path-free errors, env digest behavior, registry.
2. `tests/test_native_process_runtime_slice2.py`: v0alpha2 pinned success,
   v0alpha1 recorded semantics, pre-spawn drift refusal with a `Popen`
   tripwire, unknown-profile refusal, CLI `--profile` path.
3. `tests/test_native_web_onboard.py`: page shape, no-script/no-network
   assertions, escaping, key-body absence, module hygiene tripwire,
   pack/CLI `--web` on/off paths, socket/`Popen` tripwires.
4. `researchos schema --check-all` unchanged (no new contract), ruff
   (including `S` on `src/`), ruff format, mypy strict, pytest with the
   integer-count 85% floor, digest conformance, and `uv build`.
5. Live two-host, paid cloud, public MVP, entrypoint execution, network
   enforcement, and plugin isolation remain out of scope and must not be
   inferred from this slice.

## References

- [ADR-0008](0008-native-process-and-oci-runtimes.md)
- [ADR-0062](0062-m1-m2-acceptance-and-m3-boundary.md)
- [ADR-0063](0063-m3-native-process-runtime-slice-1.md)
- [NativeProcessRuntime v0alpha2](../protocols/native-process-runtime-v0alpha2.md)
- [Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53)
