# Execute and recover a remote reviewed native CPU task

This R08 slice joins the existing scoped HTTPS material preparation, fresh
controller-bound claim and start record with the fixed reviewed Python child.
The controller runs `LoopbackWorkerServer(native_context=NativeControllerContext(
spec, registry), ...)` with its real trusted plan, controller EventStore/CAS and
private signing key. Use a reviewed SSH TLS tunnel for a separate host. The
Worker receives only its session/grant, pinned origin/certificate, authorized
metadata and scoped material, never the controller database or signing key.

The interface is programmatic, not a new CLI/backend selection or arbitrary-job
service:

```python
from pathlib import Path
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.workers.native_executor import (
    execute_remote_native,
    reconcile_remote_native,
)

# Construct the existing WorkerClient using the registered session, scoped grant,
# verified CA and explicit TLS fingerprint. Provision separate owner-only roots.
result = execute_remote_native(
    client,
    artifacts=LocalArtifactStore(Path("worker/cas")),
    workspace=Path("worker/workspace"),
    staging_root=Path("worker/staging"),
    state_root=Path("worker/state"),
)
# After interruption, supply the original bounded reviewed request from your
# saved intent. Reopen the same CAS/state; recovery does not poll or launch.
result = reconcile_remote_native(
    client,
    artifacts=LocalArtifactStore(Path("worker/cas")),
    state_root=Path("worker/state"),
    request=request,
)
```

Root/parents must be private and disjoint as required by material preparation.
The state root must already exist with owner-only permissions. It is bound to
project/Run/Attempt, original request, Worker, grant, origin, pin and token
fingerprint. Token/credential bytes are not written to state. Keep state and CAS
for recovery; do not remove uncertain launch intent to permit a retry.

## Execution and recovery behavior

Preparation verifies actual Worker environment and material. Durable exclusive
intent precedes the single poll. Only an exact fresh claim can create the fixed
child; resumed/uncertain claim refuses. The child waits for bounded stdin before
import. Worker PID/PGID/start token are local only. Durable identity, interpreter
byte verification, immutable start document, bound controller acknowledgement,
material recheck and current cancellation/authority check precede barrier release.
Only that same existing child can cross the barrier.

A nonblocking monitor records transport cancel intent separately from OS stop.
Collection enforces reviewed wall/stream limits even when heartbeat stalls or
pipes close before process exit. Actual process-group observation precedes any
terminal report. A signal acknowledgement, connectivity failure or unavailable
identity stays unknown. Required isolation and unsupported checkpoint restore
are refused; this remains the reviewed trusted-host profile, not a sandbox.

On success, bounded canonical task output is saved in Worker CAS and durable
result/outcome records before upload. Recovery verifies the original request and
local identity, observes existing work and replays saved output/outcome only.
Missing pre-start state remains unknown, never a replacement launch. A known
revoked consumed grant records controller cancellation intent on observation;
subsequent heartbeat/recovery stops the verified group. A bound observed exit
can settle cancellation only when the controller confirms cancel/revoke intent.
Other refusals remain unknown. Running
work is observed passively; a recorded cancel intent can stop only the verified
saved group and report cancellation after actual stop. PID reuse/unknown
observation refuses terminal replay and fresh execution. Unsafe/corrupt state is
not repaired. Lost responses replay the same bound documents; competing terminal
facts cannot replace each other.

## Validation and remaining work

`RESEARCHOS_NATIVE_REMOTE_REQUIRED=1 uv run pytest -m native_remote_live` is the
designated Linux real CPU execution gate. It must fail, not skip, if OS identity
observation is missing. Ordinary outcome tests explicitly supply Worker-report
fixtures and prove controller behavior only. Current scratch-host identity is
unavailable, so those local live skips are not evidence of execution.

This slice does not host project jobs through Ray or validate CUDA/Kaggle. The
finite Ray probe remains a separate resource check. The actual two-host faults,
supported GPU profile and Checkpoint B acceptance remain pending-live. No new
phase begins; freeze follows B acceptance.
