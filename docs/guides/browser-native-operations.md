# Execute and recover reviewed work from the browser

Prepare a reviewed native request using the existing [native reviewed guide](m3-native-reviewed-execution.md).
Record the exact authorization and Worker grant, prepare material, and place the
request, spec, block manifests, token and key under the controller workspace.
Keep secrets out of CAS, evidence documents and source control. Copy the example
[profile](../../examples/browser-operations/valid/native-profile.json), adjust its
paths and install it as `native-profiles/cpu.json`. Prepared/state paths are
relative to the workspace's Worker root. This configuration is an explicit
operator decision to expose this reviewed task to the signed-in local browser.

1. Open Operations and enter `cpu` as the installed profile ID.
2. Inspect installed work. Review exact plan identity, target Worker/platform,
   declared permissions, limits, resources and policy. The inspection is read-only.
3. Check the expected revision and refresh the event head if another operator
   has changed the project. Start reviewed work uses only existing authorization.
4. After a disconnect, retry the same command while its body is retained. After
   reload, enter the existing Run ID to reconnect, or select the installed
   profile and observe existing work. Unknown requires reconciliation.
5. For checkpoint recovery, install a separate target profile with both a source
   request and a restore claim. Its new Run, Attempt, execution object, compatible
   state, preparation and grant must pass the normal restore gates. Inspect it,
   then choose Restore checkpoint.

For workspace backup recovery, stage a verified image under `backups/image1`,
enter `image1`, and choose Verify backup. Enter a new workspace ID such as
`copy1` and restore it. The resulting root is `restored/copy1`; inspect its report
and start a separate local API for it when needed. Recovery never launches work.

The existing same-user native trust assumptions, resource guarantees and
limitations apply. This slice does not provision hosts, issue credentials,
collect a selected-host/GPU acceptance run, or perform a human trial. Automated
CPU/browser fixtures are explicitly synthetic test inputs with real execution;
they are not scientific or participant evidence.
