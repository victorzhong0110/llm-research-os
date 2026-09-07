# ADR-0045: CPU OCIContainerRuntime with digest-pinned images

- Status: Accepted
- Date: 2026-09-07

This record does not reopen ADR-0008, ADR-0009, ADR-0043, or ADR-0044. It
adds the first `OCIContainerRuntime` adapter for a free CPU loop. It is not
NativeProcessRuntime, not a cross-machine Worker, and not paid GPU.

## Context

ADR-0008 keeps two runtime families: a local supervised process and a
portable OCI container path selected by immutable digest. M2-0 landed a
host-python helper that is explicitly not that container path (ADR-0043,
TM-043). Isolated processes (ADR-0044) still execute that helper.

A CPU OCI loop is required before a training-framework adapter or GPU
slice. Treating host Python as kernel isolation, or selecting an image by
tag, would hide the binding the grant already records.

## Decision

1. **Two execution paths.** `python-sandbox` / `researchos.python-brick/v0alpha1`
   remains the trusted host-python helper. `oci-container` /
   `researchos.oci-image/v0alpha1` is `OCIContainerRuntime`. A Worker
   advertises exactly one runtime. A python-sandbox Worker MUST NOT lease
   OCI work (`runtime-mismatch`).
2. **Digest identity.** `imageDigest` is `sha256:` plus 64 hex. Tags,
   `:latest`, and pull-by-name are forbidden. The first adapter is
   **docker** with `--pull=never`. A docker CLI without a running engine is
   not a runtime (`oci-runtime-missing`). Tests MUST NOT mock a successful
   container. Missing runtime is listed as an external verification item.
3. **Binding.** Grants for OCI work require `execute.oci` on the rebuilt
   plan. The execution object covers the OCI digest, media type, runtime,
   nested config, and `inputs.brickDigest` (the CAS python brick). Changing
   image, brick, config, runtime, task, or revision fails closed. Host
   `execute.local` MUST NOT issue an executable OCI grant.
4. **Launch shape.** Network is `denied`. Allowed mounts are `/in`
   (read-only bind of the materialized brick), plus `/tmp` and `/out`
   tmpfs. Privileged mode, extra binds, devices, ports, and GPU flags are
   forbidden. Resource ceilings are closed integers. Secrets enter only as
   `SecretRef` env slots resolved at spawn; values MUST NOT appear in
   events or error text (TM-007).
5. **Python brick.** The generic JSON-stdio brick still does
   input → execute → CAS artifact → `work.completed` → replayable report.
   Host Python is unchanged and MUST keep being described as a trusted
   helper, not a kernel sandbox.

## Consequences

- `researchos m2 oci` records the OCI CPU loop when a live engine can
  inspect the planned digest. Otherwise it fails closed and MUST NOT print
  a success receipt.
- Docker Desktop on macOS is a Linux VM. It is not a Darwin
  kernel-namespace proof and not a cross-machine Worker.
- runc/crun without an unpacked bundle are not this adapter. Paid GPU and
  training-framework adapters remain later slices.

## Validation

1. Tag, extra mount, non-denied network, over-limit resources, and mixed
   runtime/media fail closed.
2. `execute.local` cannot grant an OCI plan. A python-sandbox Worker cannot
   lease OCI work. CAS GET for OCI work is the brick digest, not the OCI
   digest.
3. Host-python helper still completes the ADR-0043 brick.
4. `researchos m2 oci` without a live image is `oci-runtime-missing` or
   `oci-image-missing`.
5. Live `docker` execution is skip-if-missing on ordinary hosts and is
   never replaced by a mock success. Designated Linux OCI CI MUST fail
   closed (ADR-0049).

## References

- [ADR-0008](0008-native-process-and-oci-runtimes.md)
- [ADR-0043](0043-m2-loopback-worker-and-hmac-grants.md)
- [ADR-0044](0044-isolated-control-plane-and-loopback-https.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
