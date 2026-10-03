# Reviewed native Worker command composition v0alpha1 (R08)

The existing Worker CLI now exposes the reviewed TLS executor and observation
service. It adds no task ledger, grant type or arbitrary process command.
`workers serve` accepts paired `--native-spec` and repeatable `--native-registry`
files. They are explicit controller-owned inputs, never an HTTP caller's spec.
Missing pairs, invalid documents and foreign projects refuse before binding a
listener or creating controller state. Omitting both preserves the existing
non-native server. Actual dispatch/start still recomputes the trusted kernel
binding and live authorization using the existing native endpoints.

`workers run-native CREDENTIAL --artifacts CAS --workspace WORKSPACE --staging
STAGING --state STATE` executes one fresh bound reviewed claim. The credential
file must be owner-only 0600, bounded to 64 KiB, regular, no-follow and single-link,
in an owner-only directory. A held parent descriptor anchors reads; credential
fields and CA fingerprint use the existing WorkerCredential validator. No
credential, HMAC key, controller database or arbitrary argv is accepted as a
request body, printed in reports or persisted in execution state.

`workers reconcile-native CREDENTIAL --artifacts CAS --state STATE --request
REQUEST` parses the original closed reviewed request within its existing 64 KiB
bound. It observes/replays the original private state through the same service;
it never fetches a replacement request, polls, prepares or launches. Foreign
requests, unsafe state and unknown process identity cannot create rerun authority.
The request must be retained independently of active grant validity; its copy
also exists in the immutable Worker-local intent.

Commands print only the existing closed `NativeOutcomeReceipt` to stdout, with
literal `launchAllowed: false`. Valid/invalid examples and schemas remain those
of `native-outcome-receipt`; no contract is added or weakened. Known completed,
cancelled or observed-running receipts return 0; unknown/failed receipts return 1.
A zero return code for observation means the request was handled, not that work
completed or stopped. An unrecorded uncertain prefix emits a ProblemReport and
returns 1; it retains launch intent. Invalid parser input returns 2. Errors use
existing ProblemReport on stderr; parser bodies and credentials are suppressed.

The programmatic binding's optional NativeControllerContext is the same object
constructed by the CLI. Workers receive scoped TLS credentials and private local
roots, never controller spec files, database or HMAC material. Unsupported
checkpoint restore/isolation still refuses in preparation. This CPU command
composition does not submit Ray project jobs, validate GPUs/Kaggle, certify
onboarding on another host or close Checkpoint B.
