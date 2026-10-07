# Browser native operations v0alpha1

The shared ApplicationCommand union now exposes `native.inspect`, `native.start`,
`native.restore`, `native.observe`, `run.show`, `backup.verify` and `backup.restore`.
The existing ApplicationReceipt remains the result contract. These commands are
also available through `researchos app execute`; CLI, browser and event replay
use the same services. No authorization event or Worker credential is created by
these commands.

## Installed profiles

The operator stages a schema-validated NativeLaunchProfile as
`<workspace>/native-profiles/<profileId>.json`. Profile IDs are bounded simple
names, not paths. Browser requests cannot provide a profile document, secret,
executable, controller endpoint or arbitrary filesystem path. Request, spec,
registry and credential files stay under the controller workspace; prepared and
launch-state roots stay under the configured Worker root. Every path ancestor is
checked for symbolic links. The native runtime continues to check reviewed bytes,
exact plan/authorization identity, platform, preparation, grant validity, lease
consumption and cancellation before starting code.

`native.inspect` returns a material digest, Run/Attempt/Worker identities, exact
plan, declared limits/resources and policy. It authorizes nothing. Start/restore
require that material digest plus expected revision and event head. Changed
profiles, specs, requests, manifests or checkpoint claims require another
inspection. Limits retain the existing native-reviewed same-user guarantees;
this does not create isolation for malicious code.

Start and restore reserve the project/Run identity durably before invoking the
existing executor. The reservation is never released after an exception, timeout,
process loss or receipt-write failure. Another command/window targeting the same
Run receives an unknown observation rather than dispatching again; altered
material cannot rebind the reservation. A confirmed receipt replays unchanged.
Observe reconciles only the existing execution identity and may record an
observed outcome or apply already authorized cancellation; it never launches.
`run.show` reads event-derived state without contacting a Worker.

Checkpoint restore additionally requires both sourceRequest and restoreClaim in
the installed profile. The source must have a completed result artifact. Existing
full-state/adapter-only compatibility, CAS, lineage and independent target
execution/grant checks apply. A restore command cannot reopen the source Run.

## Backup recovery

Images are operator-staged as `<workspace>/backups/<imageId>`. Destination IDs
select only `<workspace>/restored/<destinationId>`. Verification checks the
existing manifest, SQLite prefix, ledger and referenced CAS objects. Restore
pins the verified manifest digest and refuses a different manifest at the actual
materialization boundary. A destination reservation precedes copying; an
uncertain operation requires inspection, never an automatic second copy.

Restore creates a new workspace, appends zero events, creates no authority and
starts no tasks. Historical active Runs remain unknown for manual reconciliation.
The running API stays bound to its original workspace. The operator may start a
separate server for the verified new root.

## Response uncertainty

A completed native receipt is backed by the executor's observed result and Run
facts. A request or a dispatch reservation alone is not completion. The browser
retains the exact command body while mounted for retry and can reconnect to its
Run after reload. If the HTTP socket closes while execution continues, use the
same identity for receipt recovery, or observe the existing Run. The bounded
server may time out a long request; it does not kill or redispatch the task.
