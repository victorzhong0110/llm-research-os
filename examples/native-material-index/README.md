# Native material index fixtures

`valid/linux-index.json` is closed review metadata based on the existing Linux
request fixture. Its placeholder object digests/sizes are schema examples,
not downloadable artifacts, executable authorization or host evidence. Runtime
preparation additionally verifies actual bytes, exact bundle membership and the
Worker environment. No fixture is a launch credential.

Invalid examples:

- `launch-allowed.json`: preparation must keep `launchAllowed` false.
- `unknown-field.json`: the index is closed and may not embed a controller key.
- `oversize.json`: one object exceeds the existing 1 MiB preparation bound.

Both published JSON Schema and Pydantic reject these structural examples;
cross-document semantic binding checks are exercised by the runtime tests.
