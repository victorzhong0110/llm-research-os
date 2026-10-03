# Ray reviewed native CPU jobs v0alpha1

Status: optional R08 implementation candidate. No new grant, Run contract,
sandbox, GPU profile or two-host acceptance. Core dependencies do not include Ray.

`workers.ray_native_job.RayNativeJob` submits one fixed installed driver through
Ray 2.59.0 Jobs API 4 on a token-authenticated literal loopback endpoint. The
caller supplies the original closed [NativeReviewedExecutionRequest](native-reviewed-execution-v0alpha1.md)
and private compute-host paths. Driver argv contains only its installed Python,
`-I -m llm_research_os.workers.ray_native_job`, private intent path and binding
digest. There is no arbitrary command, working directory upload, dynamic package
installation or environment map. Runtime environment is empty; entrypoint CPU=1,
GPU=0 are scheduling hints, not OS resource enforcement.

Before the sole POST the adapter checks the pinned server version and absent
submission identity, then exclusively writes/fsyncs a bounded 0600, no-follow,
regular single-link intent under a locked owner-only directory. Identity is
stable for project/Run/Attempt. Binding includes original request, private paths,
Worker/origin/TLS pin/grant fingerprint, installed driver digest, interpreter,
host/UID and Ray endpoint/token fingerprint/version. No credential or session
bytes are written. The journal is internal implementation state, not a new
public JSON contract. The driver verifies the exact digest and local context;
existing native runtime additionally compares the live material-index request
with the original request before preparation, poll or child creation.

On any existing intent, ambiguous/refused POST or backend history loss, no second
POST is permitted. `submit_once()` re-entry and `observe()` query only the same
vendor identity. Returned `RayNativeObservation` has only submission identity and
vendor status. Observations verify exact entrypoint/metadata/runtime environment. Fixed CPU/GPU
hints are bound in private intent and metadata digest and sent in the sole POST.
Ray 2.59.0 [public JobDetails](https://github.com/ray-project/ray/blob/ray-2.59.0/python/ray/dashboard/modules/job/pydantic_models.py)
omits resource fields; if present in a response they must agree. Reservation is
not independently certified by GET. No logs are interpreted as project results; Ray SUCCEEDED,
FAILED and STOPPED never append project lifecycle facts.

`reconcile()` runs on the same compute host **outside the Ray driver**. It checks
the original intent and calls only the existing native observation/transfer/
receipt service. No Ray submission, Worker poll, preparation or new task process.
The native private PID/PGID/start token remain Worker-local. Controller cancellation
intent and actual group-exit observation are required for cancellation; a Ray stop
acknowledgement cannot substitute. Concurrent live driver recovery may refuse
`native-state-busy`; wait and observe the same intent, never resubmit.

Use existing [valid](../../examples/native-reviewed-execution/valid/linux-request.json) and
[invalid](../../examples/native-reviewed-execution/invalid/schema/unknown-field.json) request examples
and [NativeOutcomeReceipt](../../examples/native-remote-outcome/receipt.valid.json)
with its [invalid launch flag](../../examples/native-remote-outcome/receipt.invalid-launch.json). Public request/outcome shapes
and authority meanings are unchanged. Driver refusal/interruption prints one
sanitized message; vendor exit code is not an outcome receipt.

Supported deployment is an owned, single-node, same-UID Ray compute environment
with core wheel and approved interpreter already installed. Multi-node filesystem
routing, credentials via runtime_env, GPU allocation/device inheritance, dynamic
training installs and controller DB/key copying are unsupported. Host labels and
Ray authentication are trusted operator controls, not hardware attestation.
