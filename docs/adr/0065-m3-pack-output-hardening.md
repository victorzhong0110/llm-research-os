# ADR-0065: M3 slice 3 — onboarding pack output hardening

- Status: Proposed in this slice (M3 work, Issue #53)
- Date: 2026-09-18

This record does not close Issue #53, does not claim paid cloud, public MVP,
live SSH execution, or entrypoint execution. It scopes the third reviewable
M3 increment on top of [ADR-0064](0064-m3-native-runtime-slice-2.md).

## Context

Slices 1–2 write the pending-live SSH pack (plus the optional static page)
into an operator-chosen directory. Two output-handling gaps remain, both
exploitable without any live host:

1. A symlinked `output` path is followed silently: existence/emptiness
   checks and all pack writes land wherever the link points.
2. Only `ssh_config.fragment` is mode-restricted; `STATUS.json` embeds the
   full pinned `hostKey` body but is written with the default umask.
3. The executable profile allowlist exists in two places — the
   `NATIVE_RUNTIME_PROFILES` registry and the CLI `--profile` choices —
   with no test pinning them together.

## Decision

Slice 3 delivers small, CI-executable hardening with no paid cloud:

1. **Symlink-safe pack output** (`execution/native_ssh.py`,
   `execution/native_web.py`): reject symlinked (or non-directory) output
   paths fail-closed with `pack-output-invalid` before any write. No
   writes occur on the refusal path.
2. **Restricted pack file modes**: `STATUS.json` (embeds the pinned host-key
   body) is written `0600` like `ssh_config.fragment`. Other pack files
   stay default-readable; the page embeds no key body by construction.
3. **Single-source profile registry tests**: CLI `--profile` choices and
   defaults are asserted equal to `NATIVE_RUNTIME_PROFILES` and its first
   entry, so a future profile cannot be added in one place only.

`transport=ssh` stays validated-then-refused for every profile. No new
EventStore type, schema contract, or capability string is introduced.

## Consequences

- An operator pointing `--output` at a symlink gets a clean refusal
  instead of writes outside the intended directory.
- Key-body-bearing pack files are owner-only on POSIX; behavior on
  non-POSIX stays best-effort and is documented, not claimed.
- Threat model gains TM-068 (pack output handling) in the same change.

## Validation

1. `tests/test_native_pack_hardening.py`: symlink output refusal (pack + page, no writes performed),
   `0600` modes on `STATUS.json`/`ssh_config.fragment` (POSIX-only
   assertion, skipped otherwise), registry/CLI parity test.
2. Existing `test_native_ssh_onboard.py` / `test_native_web_onboard.py`
   unchanged in meaning; `researchos schema --check-all` unchanged,
   ruff (including `S` on `src/`), ruff format, mypy strict, pytest with
   the integer-count 85% floor, digest conformance, and `uv build`.
3. Live two-host, paid cloud, public MVP, entrypoint execution, network
   enforcement, and plugin isolation remain out of scope.

## References

- [ADR-0008](0008-native-process-and-oci-runtimes.md)
- [ADR-0062](0062-m1-m2-acceptance-and-m3-boundary.md)
- [ADR-0063](0063-m3-native-process-runtime-slice-1.md)
- [ADR-0064](0064-m3-native-runtime-slice-2.md)
- [NativeProcessRuntime v0alpha2](../protocols/native-process-runtime-v0alpha2.md)
- [Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53)
