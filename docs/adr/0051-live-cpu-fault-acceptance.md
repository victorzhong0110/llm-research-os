# ADR-0051: Live CPU fault acceptance

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0046 or ADR-0050. It does not stop cloud
instances, spend GPU, or claim M2 acceptance.

## Context

ADR-0046 bound leases to Run/Attempt recovery. Some tests still recorded
`cancel-observed` by calling `plane.fail` without a process. Checkpoint C
requires long-running CPU work with an observable OS identity: cancel,
timeout, Worker kill, control-plane restart, disconnect after upload,
a recovery client while the original executor is alive, plus duplicate
complete, expired lease, and revoke.

Unknown work must not auto-rerun. Container stop is still not cloud
instance stop.

## Decision

1. **Live proof is process state.** A test that only calls
   `plane.fail(..., "cancel-observed")` is not observed stop. Cancelled
   outcomes require `observe_and_stop` confirming the recorded pid or
   container is gone, then `work.failed` / `attempt.cancelled` /
   `run.cancelled`.
2. **Timeout and kill stay unknown.** After the sandbox reaps a timeout
   or signal-lost brick, the Worker drops the execution identity so a
   later cancel request cannot rewrite unknown as cancelled. Resume MUST
   NOT spawn.
3. **Pending complete receipt.** After a successful brick and artifact
   upload, the Worker writes a 0600 pending complete file (result and
   artifact digests). Disconnect before `work.completed` retries that
   complete. Completed work still wins over a retained cancel request.
   Missing receipt stays `work-already-claimed` and MUST NOT re-execute.
4. **Worker process killed.** SIGKILL of the Worker parent may leave an
   orphan executor. Recovery loads the identity, MUST NOT spawn, and
   stops only after a cancel request plus confirmed reap.
5. **Control-plane restart.** Loopback HTTP uses `SO_REUSEADDR`. Restart
   on the same port rebuilds the Worker fold from the EventStore. HMAC
   reuse remains ADR-0044. The original executor may keep running.
6. **Second client.** A recovery `run_once` while the original executor
   is alive MUST raise `work-already-claimed` (or observe-and-stop if
   cancel was requested) and MUST NOT start a second brick.
7. **Expire and revoke.** An expired lease or revoked grant refuses a
   new result. That refusal is not observed stop; the process is still
   running until `observe_and_stop`.

## Consequences

- `tests/test_worker_recovery.py::test_observed_stop_records_cancelled_outcomes`
  remains a reconcile-from-fact unit test. Live observation lives in
  `tests/test_worker_live_faults.py`.
- Darwin still has no `/proc` starttime (ADR-0050).
- This is not cross-machine (ADR-0021) and not a paid GPU run.

## Validation

1. In-flight cancel reaps a live sleep brick; Run/Attempt become
   cancelled only after the pid is gone.
2. Wall-clock timeout reaps the pid, writes no `work.failed`, stays
   unknown, and resume does not spawn.
3. SIGKILL of the Worker leaves the orphan pid running; recovery does
   not spawn; cancel then observes stop.
4. Control-plane HTTP restart on the same port; executor still running;
   cancel observes stop.
5. Disconnect after upload retries complete from the pending receipt
   without a second `Popen`.
6. A second client while the original pid is alive does not spawn.
7. Duplicate matching complete is idempotent. Expire/revoke refuse a
   new result while the pid is still running.

## References

- [ADR-0046](0046-worker-stop-fault-recovery.md)
- [ADR-0050](0050-observed-execution-identity.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
