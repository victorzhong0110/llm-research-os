# ADR-0050: Observed execution identity and cancel supervision

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0046. It does not stop cloud instances,
spend GPU, or claim M2 acceptance.

## Context

ADR-0046 forbade treating a cancel request as observed stop, but the
Worker client still called `fail(..., "cancel-observed")` on a resumed
lease whenever `cancelRequested` was true, without a process or
container. That reports a stop that was never observed.

A recovered Worker also had no durable identity: POSIX PID reuse could
signal the wrong process, and `docker run --rm` deleted the container
before inspect could confirm exit. Container stop is not cloud-instance
stop; the latter is a billing action for a future GPU slice.

## Decision

1. **Resume plus cancel is not observed stop.** A resumed claim MUST NOT
   spawn. `cancel-observed` is recorded only after `observe_and_stop`
   confirms the recorded executor exited. Missing identity, PID-reuse
   (Linux starttime mismatch), or failed inspect stays
   `execution-unobserved`. That MUST NOT be reported as cancelled and
   MUST NOT auto-rerun.
2. **Durable execution identity.** After spawn, the Worker writes a 0600
   identity file under a 0700 directory: lease id, kind (`posix-pg` or
   `oci-container`), pid/pgid, Linux start token, and for OCI a
   container id plus docker executable. Isolated Workers keep this next
   to the credential.
3. **Supervise during execute.** The parent polls `/v0alpha1/work/heartbeat`
   while the brick runs. Heartbeats still MUST NOT append facts. A true
   `cancelRequested` stops the recorded executor and waits for exit.
4. **Host process.** Stop the process group, wait until the pid is gone
   or zombie, then SIGKILL if needed. Linux starttime rejects PID reuse.
5. **OCI container.** Launch with `--cidfile` and without `--rm`. Stop
   is `docker stop` then `kill`, then `inspect` `State.Running=false`,
   then `rm`. This is container stop, not cloud VM stop/destroy.
6. **Cloud instance stop is forbidden here.** `refuse_cloud_instance_stop`
   fails closed. GPU billing stop remains a later, separately approved
   action.

## Consequences

- `test_resumed_cancel_fails_lease_without_spawn` now expects
  `execution-unobserved` and no `work.failed` when no identity exists.
- Live fault cases (checkpoint C) must assert real process/container
  state; they must not call `plane.fail("cancel-observed")` as the only
  proof of stop.
- Darwin has no `/proc` starttime; PID-only stop is weaker and documented.

## Validation

1. Resumed `cancelRequested` without identity does not spawn and does
   not write `cancel-observed`.
2. A long-running host brick is reaped on cancel; `work.failed` reason
   is `cancel-observed` only after the pid is gone.
3. A forged start token on a live pid returns `execution-unobserved`
   without killing that pid (Linux `/proc`).
4. Docker argv includes `--cidfile` and MUST NOT include `--rm`.
5. Cloud instance stop raises `cloud-instance-stop-forbidden`.

## References

- [ADR-0046](0046-worker-stop-fault-recovery.md)
- [ADR-0045](0045-cpu-oci-container-runtime.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
