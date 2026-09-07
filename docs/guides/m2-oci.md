# M2 CPU OCI runtime

Digest-pinned `OCIContainerRuntime` for a free CPU python brick.
Constraint record: [ADR-0045](../adr/0045-cpu-oci-container-runtime.md).
Protocol: [Worker v0alpha1](../protocols/worker-v0alpha1.md).

Host Python (`researchos m2 prove`) remains the trusted helper. It is not
this runtime and is not a kernel sandbox.

## Fail closed

`researchos m2 oci` requires a live docker engine that already has the
planned `imageDigest`. A docker CLI without a daemon is
`oci-runtime-missing`. A missing digest is `oci-image-missing`. Tests do
not mock a successful container. Docker Desktop on macOS is a Linux VM,
not a Darwin kernel-namespace proof, and not a cross-machine Worker.

Ubuntu CI 2026-09-07 recorded `worker.brick.failed` for the live brick:
the host workspace from `tempfile.mkdtemp` was mode 0700, bind-mounted at
`/in`, while the container ran as UID 65534. Redacted shape: `host_dir_mode=0o700
container_user=65534:65534` and a non-zero python exit (`Permission denied`
on `/in/task.py`). The fix keeps nobody and chmod 0755/0444 (ADR-0049).
Do not run the container as root.

Ordinary pytest may skip `oci_live` when no engine is present. The
designated GitHub job `Linux OCI integration` sets
`RESEARCHOS_OCI_REQUIRED=1` and MUST fail if docker, the image build, or
the live brick is missing.

```bash
uv run researchos m2 oci \
  examples/m2-oci-checkpoint \
  research-oci.db \
  --format json
```

The example corpus pins a placeholder image digest. Replace it with a
local `sha256:` image id before a live run. Do not use a floating tag.
The CAS brick is `inputs.brickDigest`.

Build a CPU interpreter image from the corpus Dockerfile only when a live
engine is present, then copy the image id into the spec and grant.

Launch records a container id (`--cidfile`, no `--rm`) so cancel can
`docker stop` / `kill` and `inspect` before `rm`. That is container
stop, not cloud-instance stop (ADR-0050).

## What this is not

- NativeProcessRuntime (preflight still forbids launch)
- Paid GPU / CUDA / training-framework adapter
- Cross-machine Worker (ADR-0021)
- A claim that M2 is accepted without GPU evidence
