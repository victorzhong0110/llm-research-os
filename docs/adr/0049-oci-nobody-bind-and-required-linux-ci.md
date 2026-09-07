# ADR-0049: Non-root OCI `/in` bind and designated Linux CI

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0008 or ADR-0045. It does not claim GPU
execution or M2 acceptance.

## Context

Ubuntu CI ran `test_live_oci_python_brick_loop` against a live docker
engine and observed `worker.brick.failed`, not a skip. The container runs
as UID/GID 65534. The host brick workspace comes from `tempfile.mkdtemp`
(mode 0700). Bind-mounting that directory at `/in` made the file
unreadable to nobody. Using `--user 0` or mode 0777 would paper over the
failure and weaken the launch shape.

Ordinary developer hosts (including this Darwin machine without a docker
daemon) must still skip live OCI. A skip on the designated Linux job
must not count as acceptance.

## Decision

1. **Keep the container as nobody.** `--user 65534:65534`,
   `no-new-privileges`, read-only root, network `none`. Do not run as
   root to fix permissions.
2. **OCI bind root is 0755 / 0444.** After materializing the brick, chmod
   the workspace to 0755 and `task.py` to 0444. Host-python sandboxes stay
   0700. The bind root MUST NOT be world-writable.
3. **Ordinary pytest may skip.** `discover_oci_backend() is None` or a
   failed local image build skips `oci_live` unless
   `RESEARCHOS_OCI_REQUIRED=1`.
4. **Designated Linux OCI CI fails closed.** Job `Linux OCI integration`
   on `ubuntu-latest` requires `docker info`, sets
   `RESEARCHOS_OCI_REQUIRED=1`, and runs `-m oci_live`. Missing engine,
   failed build, or skip is a job failure. Reports MUST distinguish this
   job from a developer skip.

## Consequences

- Linux docker with a built python image is the live OCI proof.
- Darwin docker Desktop, if present, is still a Linux VM and not a
  Darwin kernel-namespace proof.
- Loopback tests remain not cross-machine.

## Validation

1. Mode test: mkdtemp is 0700; after `prepare_oci_input_root` the directory
   is 0755, the brick is 0444, and neither is world-writable.
2. argv still uses `65534:65534` and never `0:0`.
3. Designated CI: `RESEARCHOS_OCI_REQUIRED=1` converts skip paths to
   `pytest.fail`.
4. Live brick prints `oci-loop` on Linux docker after the mode fix.
5. Ordinary hosts without an engine skip `oci_live` and still report that
   skip distinctly from the Linux job.

## References

- [ADR-0045](0045-cpu-oci-container-runtime.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- Ubuntu CI 2026-09-07 `test_live_oci_python_brick_loop`:
  `worker.brick.failed` with `/in` 0700 vs UID 65534
