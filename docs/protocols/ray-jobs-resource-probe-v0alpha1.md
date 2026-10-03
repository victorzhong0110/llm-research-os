# Ray Jobs resource-probe adapter (R08 candidate)

On 2026-10-03 the maintainer authorized using an available open-source backend
instead of rebuilding its execution services. This finite adapter evaluates
Ray Jobs 2.59.0 as a compute backend, separately from GPU availability and the
existing native remote-chain acceptance. It is not a new project-task profile.

## Existing vendor API, limited adapter

`RayJobsProbe` uses Ray's existing Jobs REST API version 4. There is no new
ResearchOS JSON request/receipt contract, CLI task profile or authority ledger.
The Python-only observation record preserves vendor status, bounded diagnostic
output and literal zero project-task starts/lifecycle facts. The private intent
format and fixed result marker are internal adapter state, not portable launch
credentials. Fixtures under `examples/r08-ray-jobs` are diagnostic logs.

The default control-plane environment does not import/install Ray. Ray lives in
an optional compute-host extra (`extras/ray-jobs`); the bridge uses bounded
standard-library HTTP on a literal `127.0.0.1` endpoint. A caller-owned 256-bit
Ray token is required. URLs with public hosts, credentials, suffixes or ambiguous
ports refuse. The Ray token is separate from the controller HMAC, is omitted
from representations and is never saved to intent/log/result state. The
control-plane SSH/pinned TLS transport is unchanged. A future Worker invokes
this bridge locally; exposing Ray Jobs publicly is not supported.

The only submitted commands are repository-fixed CPU arithmetic and CUDA matrix
multiplication probes. Caller code, shell commands, model/data paths, dependency
installation, environment overrides and general jobs are not accepted. CPU
reserves one Ray CPU; CUDA reserves one GPU and verifies an actual CUDA tensor
operation plus device/framework identity. Scheduling hints are not isolation.
The API and Ray versions are checked before a fresh submission. The compute
host supplies its already-installed PyTorch for CUDA; no runtime pip installation
is requested. `runtime_env` is empty.

## Durable submission and observation

A held no-follow private directory descriptor anchors every intent/lock access.
Owner-only regular single-link files, bounded exact intent bytes and a
nonblocking per-probe lock prevent substituted state and concurrent submissions.
The intent binds endpoint, token fingerprint, probe identity, source, command,
device and Ray version. It is exclusive-created and file/directory-synchronized
**before** the single submission POST. The Ray submission ID is stable.

If the intent already exists, reconnect only queries that ID. A missing job,
cluster history loss or an ambiguous/refused submission never leads to another
POST. An explicitly new probe identity is needed for a new diagnostic. Changed
scope, unsafe or corrupt state refuse without repair. Existing vendor jobs
cannot be adopted without the adapter's own durable intent.

Observation verifies submission ID, fixed entrypoint, metadata and environment
before accepting a vendor status. Response bounds are 16 KiB, or 64 KiB for
logs, with a 10-second socket ceiling and one wire attempt. A successful vendor
status also needs exactly one correctly bound compute-result marker. An exit
code alone does not establish GPU usability. Unknown remains unknown.

Stopping calls the vendor's asynchronous stop request. A true acknowledgement
is not a host process-group observation, completed cancellation or a ResearchOS
Run transition. No remote PID is installed as a controller-local identity.

## Evidence and next integration boundary

The ordinary adapter tests use explicit vendor API fixtures for refusals,
corruption, bounds, lost responses and history loss. They are not real Ray/GPU
evidence. The separate `Linux Ray Jobs resource integration` CI job must start a
real token-authenticated local cluster, execute the CPU probe and replay its
durable observation; it must fail rather than skip if Ray is unusable.

The example bootstrap starts only an explicitly owned local cluster and shuts
it down through its own `ray.shutdown()`. A parent process deadline bounds
native startup calls as well as the probe. It does not issue global `ray stop`.
This workspace's real startup attempt is currently unavailable because its PID
namespace hides process identities from Ray/psutil; this is recorded, not patched
away. CUDA and Kaggle compatibility remain pending real execution.

Before this backend can execute a ResearchOS task, it still needs the existing
material/environment checks, grant consumption, durable pre-import identity
barrier, Run/Attempt lifecycle, verified output transfer and conservative remote
recovery. No Docker GPU isolation requirement or accepted hardware identity is
silently translated into a Ray scheduling hint. This candidate cannot close R08
or Checkpoint B; it starts no R09 or new development phase.
