# ADR-0063: M3 slice 1 — local restricted NativeProcessRuntime and SSH onboarding scaffold

- Status: Proposed in this slice (M3 work, Issue #53)
- Date: 2026-09-17

This record does not close Issue #53, does not claim paid cloud, public MVP,
or SSH execution. It scopes the first reviewable M3 increment toward the
SSH/non-OCI execution package assigned by
[ADR-0062](0062-m1-m2-acceptance-and-m3-boundary.md).

## Context

M0 froze a non-launching `NativeProcessPreflight` (`launchAllowed=false`,
`isolation=not-enforced`, `interpreterIdentity=not-bound`;
[ADR-0008](0008-native-process-and-oci-runtimes.md)). M1-6 added local
`{eventId, sequence}` authorization consume for SimulatedRuntime only
([ADR-0042](0042-m1-local-authorization-consume-and-closure.md)). M2 delivered
HMAC Worker grants, loopback/OCI/GPU/MPS execution, and a pending-live remote
pack ([ADR-0043](0043-m2-loopback-worker-and-hmac-grants.md),
[ADR-0021](0021-remote-worker-transport.md)). Detached Ed25519 attestations
prove audit bytes and never grant launch ([ADR-0061](0061-detached-authorization-attestations.md)).

Issue #53 retains the unfinished path: plan-bound authorization consumption
before native process launch, with denial, cancellation, and audit behavior
under an explicit process profile. There is no SSH code in the tree, and no
second host may be claimed from loopback or unit tests.

## Decision

Slice 1 delivers two small, CI-executable pieces with no paid cloud:

1. **Local restricted `NativeProcessRuntime`** (`execution/native_runtime.py`):
   sealed preflight is recomputed, the in-process gate must be `authorized`,
   and one local `{eventId, sequence}` fact is consumed on this EventStore
   before any spawn. Only `transport=local` with `profile=restricted-v0alpha1`
   executes, and it runs a fixed noop helper over JSON stdio with bounded
   wall/output capture, an empty environment allowlist, an isolated temporary
   cwd, `shell=false`, fixed argv, and process-group supervision. The manifest
   entrypoint is never imported. `transport=ssh` is validated past
   authorization and then refused (`ssh-transport-not-implemented`) without
   opening a socket. Outcomes map to `succeeded` / `failed` / `unknown` with
   stable reason codes; cancel maps to `cancel-observed` only after the group
   is reaped, else `execution-unobserved` (ADR-0050, ADR-0054).
2. **SSH onboarding scaffold** (`execution/native_ssh.py`, `native ssh-onboard`):
   a pure validator plus pending-live pack writer. It pins a host key, forbids
   root, passwords, agent forwarding, and private-key material, and writes
   `STATUS.json` (`crossMachine: pending-live`), an onboarding checklist, an
   `ssh_config` fragment, and a restricted `authorized_keys` prefix. It never
   dials SSH. The pack is usable as an operator checklist; it is not a live
   two-host proof.

CLI surfaces are `researchos native run` (existing DB, citation flags, exit
0/1/2 mirroring `runs simulate`) and `researchos native ssh-onboard`
(pending-live pack, no network). Receipts are digest-only and never echo
entrypoints, configs, host keys, or paths beyond the safe receipt fields.

## Consequences

- Authorization consumption before spawn is demonstrated for `process.native`,
  including stale, swapped, denied, and sequence-mismatch denials that spawn
  nothing. The runtime appends no lifecycle or grant facts; the receipt is not
  an EventStore fact and confers no further authority.
- Isolation claims stay narrow: process group plus allowlisted env and closed
  cwd only. Network denial is requested, not enforced; the interpreter is the
  host `sys.executable` recorded by version, not pinned. OCI, namespaces,
  cgroup, seccomp, and mount jails are explicitly not claimed.
- SSH onboarding becomes usable without inventing live evidence: operators get
  a checklist, config fragment, and restricted prefix, while `native run
  --transport ssh` fails closed in CI.
- Threat model gains TM-064 (native runtime) and TM-065 (SSH onboarding) in
  the same pull request. No new EventStore type, schema contract, or
  capability string is introduced; `process.native` keeps its existing
  meaning and registration does not make other runtimes executable.

## Validation

1. `tests/test_native_process_runtime.py`: sealed binding, local consume,
   ssh refusal past authorization, transport/profile/citation shape,
   pre-CAS denial, wall/overflow/failure/invalid-report mapping,
   cancel-observed vs execution-unobserved, no-import/no-network tripwires,
   CLI success/refusal/missing-citation paths.
2. `tests/test_native_ssh_onboard.py`: target validation table, pending-live
   pack contents without private keys, non-empty-output refusal,
   no-socket/no-spawn tripwires, CLI JSON/text/refusal paths.
3. `researchos schema --check-all` unchanged (no new contract), ruff
   (including `S` on `src/`), ruff format, mypy strict, pytest with the
   integer-count 85% floor, digest conformance, and `uv build`.
4. Live two-host, paid cloud, public MVP, Web UX, and plugin isolation remain
   out of scope and must not be inferred from this slice.

## References

- [ADR-0008](0008-native-process-and-oci-runtimes.md)
- [ADR-0042](0042-m1-local-authorization-consume-and-closure.md)
- [ADR-0050](0050-observed-execution-identity.md)
- [ADR-0054](0054-process-observation-tristate.md)
- [ADR-0061](0061-detached-authorization-attestations.md)
- [ADR-0062](0062-m1-m2-acceptance-and-m3-boundary.md)
- [NativeProcessRuntime v0alpha1](../protocols/native-process-runtime-v0alpha1.md)
- [Issue #53](https://github.com/victorzhong0110/llm-research-os/issues/53)
