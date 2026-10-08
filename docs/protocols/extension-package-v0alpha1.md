# Explicit extension packages v0alpha1

A package wraps the unchanged extension/v0alpha1 declaration with exact host
compatibility, up to three unique interfaces (brick, evaluator, provider), and
up to sixteen unique exact id/version dependencies. It grants no handles and
never installs dependencies automatically. Declared read permissions remain
requests. A role matches its Input/Output message kind and version. Envelopes
have exactly kind, version and a JSON object payload; existing finite JSON and
64 KiB input / 256 KiB stdout / 64 KiB stderr / ten-second limits apply.

The package/input/output union has a registered generated JSON Schema:
`researchos schema --contract extension-package`. Original v1 manifest and
registry schemas remain unchanged. Loading bytes is inert and refuses symlinks,
nonregular/oversize files, duplicate JSON keys, incompatible interfaces/hosts,
extra fields, self-dependencies and unsupported permissions. No Python import
from an operator declaration occurs on installation.

Persistent state lives in a private workspace-local extensions.sqlite with a
known complete schema. It retains immutable package bytes and digest, explicit
inert/reviewed-same-user trust and enabled state. The registry admits at most 32
entries. Transactions serialize install and lifecycle changes; dispatch reads
one snapshot and rechecks trust, enabled state and every dependency. Disable
prevents subsequent dispatch; it does not terminate an already dispatched
process. Uninstall removes only registry data, preserving operator source files.
Unknown/untrusted code is refused: these subprocess limits are not isolation.
Reviewed code has the operator's ambient filesystem/network authority. No
control-store connection, Worker grant, credential or model key is supplied.

The existing pinned Iris CPU training function demonstrates an evaluator
interface without importing training extras or fetching new data. Its source
is snapshotted into the inline reviewed declaration at explicit installation;
execution fits and returns the same 20 public development predictions as R13.
It does not dispatch a Run, append EventStore facts, write CAS, record a human
conclusion or establish independent scientific confirmation. Callers obtain a
bounded response and its package digest. Responses violating the declared kind,
version, closed envelope or finite JSON fail with a closed error.

Workspace backup intentionally excludes operator executable declarations and
trust selections, just as it excludes launch profiles and keys. Restoring never
reenables an executable extension automatically: explicitly reinstall/review it.
The original process-local Python API remains available and independently inert.
No marketplace, automatic updates, sandbox claims or paid provider work is added.
