# NativeProcessRuntime v0alpha1

> Status: M3 slice 1 local restricted execution + SSH-shaped refusal
>
> Constraint record:
> [ADR-0063](../adr/0063-m3-native-process-runtime-slice-1.md)

This protocol binds one sealed `NativeProcessPreflight` result and one local
authorization citation to a bounded host process. It is the first executable
step toward `NativeProcessRuntime` ([ADR-0008](../adr/0008-native-process-and-oci-runtimes.md))
and the Issue #53 consume path. It is not OCI, MPS, GPU, paid cloud, or a
public service.

## Preconditions

The reference executor fails closed unless all of these hold:

1. `preflight_native_process` recomputes successfully on the supplied ready
   report, sealed registry, authorization policy, and preflight policy.
2. `authorize_plan` on the same inputs is `authorized`.
3. `consume_local_authorization` accepts the cited `{eventId, sequence}` on
   *this* EventStore: the fact exists, the sequence matches, the actor kind
   is human, `authorized=true`, and the four-digest binding plus project,
   revision, and workflow match the in-process gate.
4. `transport` is `local` and `profile` is `restricted-v0alpha1`.
   `transport=ssh` passes checks 1–3 and is then refused with
   `ssh-transport-not-implemented` without opening a socket. Any other
   transport or profile is `native-transport-invalid` /
   `native-profile-invalid`.

Unknown, stale, broadened, or coerced input is an error. The executor never
silently narrows a caller request and never spawns before checks 1–3 pass.

## Fixed local profile

| Surface | v0alpha1 value | Meaning |
|---|---|---|
| transport | `local` | Host `sys.executable` only; `ssh` is validated but refused |
| profile | `restricted-v0alpha1` | The only executable profile |
| argv | fixed helper | `[python, -B, -I, -c, <fixed noop>]`; no shell, no manifest argv |
| entrypoint | not executed | Manifest `module:callable` is never imported |
| shell | `false` | Shell interpretation is outside the profile |
| network | requested `denied`, enforced `not-enforced` | No firewall or namespace is claimed |
| workspace | isolated temporary cwd | `mkdtemp` dir as cwd, `HOME`/`TMPDIR` pointed there, removed after |
| environment | empty allowlist | Only `PATH`/`SYSTEMROOT`/`WINDIR` passthrough plus fixed `PYTHON*` |
| stdin | JSON object | `{"preflightDigest": "<digest>"}` only; no config or entrypoint text |
| stdout/stderr | bounded capture | Preflight byte caps applied while pipes are read |
| termination | `terminate-then-kill` via group reap | Process-group SIGKILL with caller-group guard |
| interpreter | host recorded, not pinned | `pythonVersion` is recorded; no digest pin or venv proof |
| isolation | `process-group` | No namespace, cgroup, seccomp, or mount jail |
| persistence | none | No lifecycle fact, grant, artifact collect, or projection write |

Limits are the sealed preflight ceilings (`wallTimeSeconds` 1–3,600,
`stdoutBytes`/`stderrBytes` 0–16,777,216, `terminationGraceSeconds` 0–60).

## Outcomes

| Helper observation | Disposition | Reason code |
|---|---|---|
| valid `NativeProcessReport` with matching `preflightDigest` | `succeeded` | `native.process.ok` |
| non-zero exit | `failed` | `native.brick.failed` |
| stdout over cap while reading | `failed` | `native.brick.output-too-large` |
| unparseable or mismatched report | `failed` | `native.brick.invalid-report` |
| cancel requested and group reaped | `failed` | `cancel-observed` |
| wall timeout | `unknown` | `native.process.timeout` |
| signal death, lost process, stdin failure | `unknown` | `native.process.lost` |
| cancel requested but group not confirmed gone | `unknown` | `execution-unobserved` |

Observation after reap is `exited` for `succeeded`/`failed` and `unknown`
for `unknown`, following ADR-0054. A failed `ps`/`/proc` probe is never
reported as exited.

The CLI receipt is digest-only:

```json
{
  "preflightDigest": "jcs-sha256:<64 hex>",
  "disposition": "succeeded",
  "reasonCode": "native.process.ok",
  "resultDigest": "jcs-sha256:<64 hex>",
  "transport": "local",
  "profile": "restricted-v0alpha1",
  "entrypointExecuted": false,
  "isolation": "process-group",
  "networkEnforcement": "not-enforced",
  "observation": "exited",
  "pythonVersion": "3.12.3",
  "stdoutBytes": 141
}
```

It never contains the entrypoint string, task configuration, host paths, or
interpreter paths. `resultDigest` is the content digest of the helper report.

## SSH onboarding shape

`researchos native ssh-onboard` validates a restricted target and writes a
`pending-live` pack. It never dials SSH:

- host: IP or hostname; `0.0.0.0`/`::`/`*` refused; loopback labeled
  `loopback-not-cross-machine`.
- port: integer 1–65,535.
- user: `^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$`; `root` refused.
- workdir: absolute POSIX path under `/`, not `/`, no `.`/`..`/empty
  segments, no whitespace or `~`.
- host key: `ssh-ed25519:` / `ecdsa-sha2-nistp256:` / `ecdsa-sha2-nistp384:` /
  `ssh-rsa:` plus base64 body; private-key material refused; pin required.
- profile: `restricted-v0alpha1` only.

The pack contains `STATUS.json` (`crossMachine: pending-live`,
`transport: ssh-pending`), `ONBOARDING.md`, `ACCEPTANCE.md`,
`ENVIRONMENT.json`, an `ssh_config.fragment` (no passwords, no agent
forwarding, batch mode, strict host-key checking), and an
`authorized_keys.fragment` with a restricted `command=` prefix and a public-key
placeholder. No private key is written.

## CLI behavior

```bash
researchos native run \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  examples/native-process-preflight/preflight-request.json \
  research.db \
  --registry examples/native-process-preflight/manifest.yaml \
  --authorization-event-id evt.auth.native.1 \
  --authorization-sequence 1 \
  --transport local \
  --profile restricted-v0alpha1 \
  --format json
```

The database must already exist and already hold the cited authorization fact
(record it first with `authorizations record`). Exit `0` is a `succeeded`
helper run; exit `1` is a `failed`/`unknown` helper outcome; exit `2` is a
parsing, validation, planning, registry, authorization, binding, transport, or
store error. Stdout on exit `2` is empty; the ProblemReport on stderr carries
the stable `code` (for example `ssh-transport-not-implemented`).

```bash
researchos native ssh-onboard /tmp/native-ssh-pack \
  --host 192.0.2.10 --user researcher --port 22 \
  --workdir /home/researcher/native \
  --host-key ssh-ed25519:BASE64 \
  --project example-native \
  --source https://researchos.dev/projects/example-native \
  --format json
```

Exit `0` writes the pack; exit `2` is a validation or filesystem error. No
socket is opened in either exit path.

## Explicit non-goals

This contract does not import or execute the manifest entrypoint, enforce
network denial, pin the interpreter, provide OCI/MPS/GPU isolation, append
Run/Attempt or grant facts, collect artifacts, open SSH, spend paid cloud,
serve Web UX, isolate plugins, or reach a scientific conclusion. A `succeeded`
receipt means the fixed helper echoed the sealed preflight digest under
bounds, not that research succeeded.
