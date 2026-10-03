# Run the reviewed native Worker from the command line

Prepare the actual reviewed spec/registry and grant using the existing native
review and Worker authorization procedures. On the controller, pass that actual
context to the existing HTTPS server:

```bash
researchos workers serve controller/research.sqlite \
  --artifacts controller/cas --state controller/state \
  --project PROJECT --source URI \
  --native-spec reviewed-spec.yaml \
  --native-registry reviewed-native-block.json
```

Repeat `--native-registry` for each manifest in the reviewed registry. Both
context options are required together; wrong project or invalid context refuses
before listener/state creation. The emitted URL/fingerprint is connectivity
information, not launch permission. For a different host, use the approved SSH
onboarding/tunnel flow and verified TLS pin. Copy only the public Worker CA and
scoped WorkerCredential, never control SQLite/CAS, HMAC key or TLS private key.
The native run still needs the exact queued task/Run/Attempt and live grant.

On the Worker, keep the credential file at 0600 under an owner-only directory;
CAS, workspace, staging and execution state must be disjoint as required by
material preparation. Provision empty owner-only CAS/state and their parent;
workspace/staging publication is handled by verified preparation:

```bash
mkdir -m 700 worker worker/cas worker/state
# Provision worker/credential.json and its verified public CA through the existing
# credential/bootstrap flow; do not place token bytes in shell arguments or logs.
researchos workers run-native worker/credential.json \
  --artifacts worker/cas --workspace worker/workspace \
  --staging worker/staging --state worker/state
```

This command uses the fixed reviewed runner and pre-import barrier. Unsupported
required isolation/checkpoint restoration refuses. It prints the controller's
existing closed outcome receipt, not arbitrary task stdout, a launch credential
or a scientific conclusion. Verified output is in the existing Worker/controller
CAS and Work facts. Connection availability and usable GPU/backend resources
remain separately verified records.

After a lost response, upload interruption or Worker restart, use the original
reviewed request, not a newly issued request. Keep private state and CAS; never
remove uncertain intent to force another launch:

```bash
researchos workers reconcile-native worker/credential.json \
  --artifacts worker/cas --state worker/state --request original-request.json
```

Recovery only observes the original local process identity or replays saved
results. Completed receipts can replay after consumed-grant expiry/revocation;
pending results cannot bypass cancellation. A known revoked consumed grant
records cancellation intent separately from actual stop. Running/unknown
observations cannot become a fresh task or invent terminal stop. A handled
running receipt returns 0 but does not mean completion; unknown/failed returns 1,
invalid parser input 2. An uncertain prefix with no controller receipt returns 1
and remains retained for inspection/observation.

Real Linux CI runs both in-process CLI routing and a separate isolated CLI
Worker process producing CPU output, then starts another CLI process that
replays the identical receipt without new facts. Unsafe credential/context and
parser-secret tests are ordinary control-boundary fixtures, not two-host/GPU
acceptance. The designated native gate fails rather than skips if real OS
identity is absent. Ray project-job hosting, actual selected hosts, CUDA/Kaggle
and Checkpoint B remain open; freeze follows B acceptance, no R09.
