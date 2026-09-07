# ADR-0054: Process observation is running, exited, or unknown

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0050 or ADR-0051. It does not spend GPU
or claim M2 acceptance.

## Context

`process_still_running` was a boolean. After `os.kill(pid, 0)` succeeded,
a missing `/proc` fell through to `ps`. A `ps` failure, nonempty
unparseable output, or nonzero exit was treated as "not running". That
inferred **exited** without exit evidence: `Popen.poll()` could still be
`None` while the helper returned False.

Stop confirmation also waited only for the group leader. A leader that
had already exited left children running, and `cancel-observed` could
still be recorded.

A recorded Linux starttime that could not be re-read still allowed
signaling. That cannot exclude PID reuse.

## Decision

1. **Tri-state observation.** `observe_process` returns `running`,
   `exited`, or `unknown`. `cancel-observed` / `observed-stop` require
   `exited`. Unknown MUST NOT be reported as cancelled.
2. **Failed probes are unknown.** `/proc` missing, `ps`/`pgrep` missing,
   timeout, nonzero status, or unparseable state MUST NOT become
   `exited` while `kill(pid, 0)` still succeeds. Re-check kill after a
   failed probe; `ProcessLookupError` is then `exited`.
3. **Process group, not only the leader.** Stop waits until every
   listed group member is `exited`. If members cannot be listed, a
   non-running leader is `unknown`, not `exited`.
4. **Unverified start token does not kill.** A live pid with a recorded
   start token must re-read a matching token. Unreadable or mismatched
   tokens return `execution-unobserved` without signaling.

## Consequences

- Darwin without `/proc` still uses `ps`/`pgrep`. When those fail, the
  outcome is `unknown`.
- `process_still_running` is `observe_process == running`. Unknown is
  not running and not exited.

## Validation

1. Live pid + `kill(0)` success + failed `ps` is `unknown`, not `exited`.
2. Recorded start token that cannot be re-read does not kill the pid.
3. Leader exit with a live child keeps the group `running` until the
   child is reaped.

## References

- [ADR-0050](0050-observed-execution-identity.md)
- [ADR-0051](0051-live-cpu-fault-acceptance.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
