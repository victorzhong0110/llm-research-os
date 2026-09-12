# ADR-0055: Live OCI fault acceptance

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0045, ADR-0049, ADR-0050, or ADR-0051.
It does not stop cloud instances, spend GPU, or claim M2 acceptance.

## Context

Designated Linux OCI CI only ran one successful brick
(`test_live_oci_python_brick_loop`). CPU live faults (ADR-0051) already
assert process state. OCI stop/inspect was unit-tested with stubs, not
with a live container remaining after cancel, timeout, Worker kill,
control-plane restart, external `docker stop`, inspect failure, or a
second client while the original container still runs.

A skip of `oci_live` on the designated job is still not a pass
(ADR-0049). `plane.fail("cancel-observed")` is still not observed stop.

## Decision

1. **Designated CI runs every `oci_live` test.** The GitHub job sets
   `RESEARCHOS_OCI_REQUIRED=1` and invokes `pytest -m oci_live`. Missing
   engine, image build failure, or a skip MUST fail the job. Ordinary
   pytest MAY skip when no engine is present.
2. **Live proof is container state.** Cancelled outcomes require
   `inspect` (or equivalent) showing the recorded container is not
   running, then `work.failed` / `attempt.cancelled` / `run.cancelled`.
   Timeout reaps/removes the container, writes no `work.failed`, stays
   unknown, and resume MUST NOT spawn.
3. **Worker kill leaves the container.** SIGKILL of the Worker parent
   MUST NOT be treated as observed stop. Recovery MUST NOT spawn. Stop
   is confirmed only after a cancel request plus inspect.
4. **Inspect failure is unknown.** If `docker inspect` does not return a
   boolean Running state, the outcome is `execution-unobserved`, not
   `cancel-observed`. An externally stopped container with
   `Running=false` MAY be observed stop.
5. **OCI wall is a closed bound, not the host-python 5s cap.** Default
   wall remains 5 seconds. The launch maximum is 30 seconds so live
   cancel/restart/orphan tests can observe the container. Memory, PIDs,
   CPU millis, network-denied, non-root, and forbidden host mappings
   stay the CPU OCI shape.
6. **Container stop is not cloud instance stop.**

## Consequences

- Live OCI faults live in `tests/test_worker_oci_live_faults.py`.
- This is not cross-machine (ADR-0021) and not a paid GPU run.

## Validation

1. In-flight cancel stops a live sleep container; Run/Attempt become
   cancelled only after inspect is not running.
2. Wall-clock timeout removes the container, writes no `work.failed`,
   stays unknown, and resume does not spawn.
3. SIGKILL of the Worker leaves the container running; recovery does
   not spawn; cancel then observes stop.
4. Control-plane HTTP restart on the same port; container still
   running; cancel observes stop.
5. External `docker stop` with inspect `Running=false` is observed
   stop. `docker rm` so inspect fails is `execution-unobserved`.
6. A second client while the original container is alive does not
   spawn.

## References

- [ADR-0045](0045-cpu-oci-container-runtime.md)
- [ADR-0049](0049-oci-nobody-bind-and-required-linux-ci.md)
- [ADR-0050](0050-observed-execution-identity.md)
- [ADR-0051](0051-live-cpu-fault-acceptance.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
