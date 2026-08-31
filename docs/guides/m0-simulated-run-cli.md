# M0 Simulated Run CLI

## What this command does

`researchos runs simulate` exposes the already-tested deterministic
SimulatedRuntime as a local CLI. It loads one ResearchSpec and one explicit
`SimulationRequest`, creates or resumes a local SQLite EventStore, then returns
the rebuilt `RunSnapshot`.

It does not execute Python, shell commands, containers, plugins, model APIs, or
GPU workloads. It does not generate IDs or timestamps. The caller supplies all
event identity in the request file.

## Run the committed example

```bash
uv run researchos runs simulate \
  examples/valid/minimal.yaml \
  examples/simulation-requests/valid/success.json \
  research.db --format json
```

The first invocation appends the six success-path lifecycle facts. Running the
same command again rebuilds the terminal Run, appends zero facts, and returns
the same completed snapshot.

Inspect the facts independently:

```bash
uv run researchos events verify research.db --format json
uv run researchos events replay research.db --page-size 100
```

The request is validated against
`schemas/simulation-request/v0alpha1.schema.json`. Its complete field rules and
normative example are in [SimulationRequest v0alpha1](../protocols/simulation-request-v0alpha1.md).

## Output and exit codes

With `--format json`, stdout is exactly a versioned `RunSnapshot`, already
covered by `schemas/run-state/v0alpha1.schema.json`. With `--format text`, the
command prints disposition, project, Run, workflow, status, append count, and
last global sequence; terminal-control characters are escaped.

- `0`: controlled simulation completed;
- `1`: simulation produced or retained failed, unknown, or unresolved state;
- `2`: the command could not safely execute, including input, registry,
  integrity, transition, duplicate, or CAS errors.

Errors go to stderr as `ProblemReport` JSON in JSON mode. A CAS conflict is not
retried or translated to success.

## Creation, recovery, and failure

Spec, request, and registry validation happen before the database is opened, so
their structural errors do not create a database. Starting a semantically
unsupported simulation can initialize an empty EventStore, but it appends no
lifecycle fact. Invoking a run command is therefore authorization to create the
named local database if it is absent.

Each lifecycle event remains its own RunControl CAS append, not one multi-event
transaction. An interruption can leave a legal prefix. Reusing the same spec,
request identities, and database resumes that prefix. A conflicting writer,
corrupt database, mismatched Run binding, missing identity, unknown/lost/cancel
state, or illegal transition fails closed under the existing runtime rules.

`completed` describes only the simulated lifecycle. Review, evidence, metrics,
and scientific conclusions remain separate work.
