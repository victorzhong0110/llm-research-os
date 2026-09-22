# Shared application services

R02 exposes workspace, revision, validate, diff, dry-run, ledger, decision,
and Run query operations through one Python service and the `researchos app`
commands. Both callers execute `ApplicationCommand` documents and print
`ApplicationReceipt` documents. The contract is
[ApplicationCommand v0alpha1](../protocols/application-command-v0alpha1.md).

```bash
uv run researchos app init \
  --root ./workspace \
  --project example-minimal \
  --control-db control/events.sqlite \
  --cas-root cas \
  --worker-root worker
uv run researchos app execute --root ./workspace command.json
```

Python:

```python
from pathlib import Path

from llm_research_os.application import ApplicationService, load_application_command

service = ApplicationService.open(Path("workspace"))
receipt = service.execute(load_application_command(Path("command.json")))
```

The service reuses `ResearchControl`, `RunControl`, `TrustedKernel`, and
`SimulatedRuntime`. It does not import task entrypoints and it does not grant
Worker launch authority. Core import of `llm_research_os.application` does not
load training extras.

Bind a workspace before the first command. Overlapping control and Worker
roots are refused. A document whose project id differs from the workspace is
refused. Pass the head and revision you reviewed; a mismatch fails closed and
leaves the EventStore unchanged. Decision append uses that head as its CAS
token. Spec, decision, simulation-request, and registry bytes are snapshotted
once for the receipt digest and the execution.

Receipts survive a new process. Replaying the same command id and content
returns the prior result. EventStore schema v2 is unchanged: no migration is
required, and existing event digests stay in place.
