# Run a reviewed CPU project task through optional Ray

Use an authorized single compute host with private Worker credentials and the
[native Worker controller](native-worker-cli.md) already provisioned. Install the
core wheel and `extras/ray-jobs/requirements.txt` into the separate compute
environment, not the controller. Start an explicitly owned single-node Ray 2.59.0
cluster with token authentication and dashboard bound to `127.0.0.1`; the owned
cluster/resource example is `examples/r08-ray-jobs/probe.py`. Do not reuse a
notebook cluster or expose an unauthenticated dashboard.

Keep the original bounded reviewed request and credential/CA on the compute
host. Credential files are 0600, regular single-link files under a 0700 parent.
Create separate 0700 CAS, workspace, staging, native state and Ray state roots;
none may contain another. No controller EventStore, HMAC key or TLS private key
is a Worker input. A private Ray token is supplied in memory, never CLI argv or
submitted `runtime_env`. Ray
cluster processes use their own token authentication configuration; set it before
importing Ray, as in the owned-cluster probe example.

```python
from pathlib import Path
from llm_research_os.execution.native_reviewed import parse_native_reviewed_request
from llm_research_os.execution.native_reviewed_documents import MAX_REVIEWED_REQUEST_BYTES
from llm_research_os.execution.native_reviewed_preparation import load_bounded_file
from llm_research_os.workers.ray_probe import RayJobsProbe
from llm_research_os.workers.ray_native_job import RayNativeJob

root = Path("/private/compute-worker")
request = parse_native_reviewed_request(
    load_bounded_file(root / "original-request.json", limit=MAX_REVIEWED_REQUEST_BYTES)
)
# endpoint and ray_token come from the explicitly owned authenticated local cluster.
job = RayNativeJob(
    RayJobsProbe(endpoint, ray_token),
    request,
    root / "credential.json",
    root / "cas",
    root / "workspace",
    root / "staging",
    root / "native-state",
    root / "ray-state",
)
backend_observation = job.submit_once()
# Later, recreate the same object with the same original request and paths.
backend_observation = job.observe()
# Once the driver releases native state, obtain the independently verified outcome.
project_result = job.reconcile()
receipt = project_result.receipt
```

Keep backend and project results separate. Backend SUCCEEDED does not establish
an output digest or Run completion; the native service verifies the output and
returns the existing non-launch receipt. Missing/unknown intent or unavailable
process identity is not permission to rerun. Do not delete journals to clear an
unknown submission. Observation may continue without vendor history; controller
connectivity and process identity are still independently required.

Request cancellation through existing controller Run controls. A Ray stop call
can kill a driver while a task survives or exits without an outcome; continue
native observation on the compute host outside Ray. Only actual saved-group
observation and controller intent can establish cancellation. Never declare stop
from Ray STOPPED alone. `native-state-busy` means the original driver still holds
the journal; retry observation later without fresh submission.

Designated Linux `ray-native` CI requires actual Ray scheduling, reviewed task
execution over TLS into independent Worker CAS, verified output and Run facts,
real lost-submit-response replay and vendor stop followed by controller-intent/
actual process observation. It fails on missing Ray/OS identity or deadline;
protocol fixtures and ordinary skips are not live evidence. This is single-host
integration; selected two-host, GPU/Kaggle and Checkpoint B acceptance remain open.
The 2026-10-04 direction authorizes sequential work through R16, with each
predecessor merged and accepted before the next starts. R09 still awaits B;
see the [live acceptance runbook](r08-live-acceptance.md). No paid host
provisioning is included.
