# Remote native start-record examples

These are schema/parser fixtures, not actual execution or host evidence.
The valid request binds a preparation receipt, consumed lease and Worker-local
identity digest. The valid receipt records one controller `attempt.started`
fact with `launchAllowed: false`. It cannot authorize another process.

`request.invalid-pid.json` is invalid because remote PIDs are not request fields
and cannot become controller-local process identities. `receipt.invalid-launch.json`
is invalid because a start-record receipt is not a portable launch credential.
See [the guide](../../docs/guides/m3-native-start-record.md).
