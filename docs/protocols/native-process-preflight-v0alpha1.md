# NativeProcessPreflight v0alpha1

> Status: M0 reference contract
>
> Schema authority:
> `schemas/native-process-preflight-request/v0alpha1.schema.json` and
> `schemas/native-process-preflight-report/v0alpha1.schema.json`

## Purpose

`NativeProcessPreflightRequest` freezes the review parameters for one exact, already authorized
native Python task. `NativeProcessPreflightReport` records the normalized launch shape while
unambiguously refusing launch. This protocol lets reviewers inspect and hash the boundary before a
real `NativeProcessRuntime` exists.

It is not a process API, an authenticated approval, a durable receipt or evidence that the listed
isolation and limits were enforced.

## Preconditions

The reference evaluator fails closed unless all of these conditions hold:

1. A defensively revalidated `DryRunReport` is `ready` and contains exactly one task, no graph edge
   and no project resource.
2. A sealed registry exactly matches the report's registry digest and resolves the planned
   manifest digest.
3. The supplied `PlanAuthorizationRequest` recomputes to `authorized` for the exact
   `(specDigest, registryDigest, planDigest)` tuple.
4. The preflight request repeats that tuple and the recomputed `authorizationDecisionDigest`.
5. The selected task path is exact and has no dependency or resource reference.
6. The manifest and planned task both declare only `process.native`, no permission, no port and no
   host resource.
7. Runtime type is `python`, the entrypoint matches `module.path:callable.path`, and runtime config
   is exactly `{"protocol":"researchos.python-json-stdio/v0alpha1"}`.
8. Every fixed constraint and numeric ceiling has the exact type and permitted value.

Unknown, stale, broadened, duplicated, coerced or unsupported input is an error. The evaluator does
not silently discard a field or narrow a caller's request.

## Request document

The request is closed to unknown properties. All four digests use lowercase
`sha256:<64 lowercase hex>` syntax. `taskPath` must be a JSON array with 1–128 identifiers.
`environmentAllowlist` is an explicit empty JSON array in this profile.

Normative example:

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "NativeProcessPreflightRequest",
  "specDigest": "sha256:6246fb9842ed8f808e6d556e6a500596d5bcc5b41f11f3676e428afe0b68ffa5",
  "registryDigest": "sha256:05cd693d9f1a195ae4408968b8da927d1eb0a1e877ebc3853dacedeb08117d3e",
  "planDigest": "sha256:310d4aadd18c6cbd8c258853b056af3704f0e6db0eb25ecf18121e6e642a7ac7",
  "authorizationDecisionDigest": "sha256:3ae63e85738fde08cb3705b1797ef98f3836c0dd7ae279934f70cdf2945a82b8",
  "taskPath": [
    "workflow",
    "workflow.native",
    "invoke"
  ],
  "runner": "researchos.python-worker/v0alpha1",
  "shell": false,
  "network": "denied",
  "workspace": "isolated-temporary",
  "environmentAllowlist": [],
  "limits": {
    "wallTimeSeconds": 30,
    "stdoutBytes": 1048576,
    "stderrBytes": 1048576,
    "terminationGraceSeconds": 5
  }
}
```

The separately validated authorization input used by the example is:

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "PlanAuthorizationRequest",
  "specDigest": "sha256:6246fb9842ed8f808e6d556e6a500596d5bcc5b41f11f3676e428afe0b68ffa5",
  "registryDigest": "sha256:05cd693d9f1a195ae4408968b8da927d1eb0a1e877ebc3853dacedeb08117d3e",
  "planDigest": "sha256:310d4aadd18c6cbd8c258853b056af3704f0e6db0eb25ecf18121e6e642a7ac7",
  "grantedCapabilities": [
    "process.native"
  ],
  "grantedPermissions": [],
  "requirementDecisions": []
}
```

## Fixed launch review profile

| Surface | v0alpha1 value | Meaning |
|---|---|---|
| runner | `researchos.python-worker/v0alpha1` | Future trusted runner identity; no binary is resolved now |
| protocol | `researchos.python-json-stdio/v0alpha1` | One future JSON object on stdin; bounded capture on stdout/stderr |
| argv | `trusted-runner-fixed` | No shell or manifest-controlled argument vector |
| shell | `false` | Shell interpretation is outside the profile |
| network | `denied` | Requested future policy; not enforced by preflight |
| workspace | `isolated-temporary` | Requested future policy; no directory is created by preflight |
| environment | empty allowlist | No inherited or injected name is approved |
| termination | `terminate-then-kill` | Requested bounded future sequence; no signal is sent now |
| interpreter identity | `not-bound` | A future executor must bind an exact interpreter/environment |

Limits are caller-selected hard ceilings within these inclusive ranges:

| Field | Minimum | Maximum |
|---|---:|---:|
| `wallTimeSeconds` | 1 | 3,600 |
| `stdoutBytes` | 0 | 16,777,216 |
| `stderrBytes` | 0 | 16,777,216 |
| `terminationGraceSeconds` | 0 | 60 |

## Report and digest

The report contains the exact four-digest binding, task and manifest identity, config and
entrypoint digests, fixed constraints and limits. It never contains the entrypoint string or task
configuration. An entrypoint digest reduces accidental disclosure in output; it is not encryption
and does not conceal a guessable value from an offline dictionary attack.

`preflightDigest` is the reference `content_digest` of this logical payload:

```json
{
  "binding": {
    "specDigest": "<digest>",
    "registryDigest": "<digest>",
    "planDigest": "<digest>",
    "authorizationDecisionDigest": "<digest>"
  },
  "task": {
    "taskPath": ["<segment>"],
    "blockId": "<id>",
    "blockVersion": "<version>",
    "manifestDigest": "<digest>",
    "configDigest": "<digest>",
    "entrypointDigest": "<digest>",
    "runtimeType": "python",
    "runner": "researchos.python-worker/v0alpha1",
    "protocol": "researchos.python-json-stdio/v0alpha1"
  },
  "constraints": {
    "shell": false,
    "network": "denied",
    "workspace": "isolated-temporary",
    "environmentAllowlist": [],
    "argvMode": "trusted-runner-fixed",
    "stdin": "json-object",
    "stdout": "bounded-capture",
    "stderr": "bounded-capture",
    "termination": "terminate-then-kill",
    "interpreterIdentity": "not-bound"
  },
  "limits": {
    "wallTimeSeconds": 30,
    "stdoutBytes": 1048576,
    "stderrBytes": 1048576,
    "terminationGraceSeconds": 5
  },
  "authority": {
    "authentication": "not-authenticated",
    "persistence": "not-persisted",
    "isolation": "not-enforced",
    "launchAllowed": false
  }
}
```

The report model recomputes this digest. Its other literal claims require `status=reviewable`,
`launchAllowed=false`, `authorizationAuthentication=not-authenticated`,
`authorizationPersistence=not-persisted`, `isolation=not-enforced`,
`execution=not-executed`, and zero blocks, entrypoint imports, processes, signals, network requests,
persistent writes and paid actions.

As with the other v0alpha1 reference digests, cross-language producers must not claim byte-for-byte
compatibility until the project adopts a normative canonical encoding.

## CLI behavior

```bash
researchos native preflight \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  examples/native-process-preflight/preflight-request.json \
  --registry examples/native-process-preflight/manifest.yaml \
  --format json
```

- Exit `0`: one structurally valid, self-verifying, non-launchable report was produced.
- Exit `2`: parsing, validation, planning, registry, authorization or binding failed.

There is no exit code meaning “process launch is allowed.” Successful evaluation performs local
reads only and does not import or execute the manifest entrypoint.

## Explicit non-goals

This contract does not authenticate an approver, persist or revoke authorization, resolve a Python
interpreter, inject a secret, materialize an artifact, create an isolated workspace, enforce a
network rule, spawn or supervise a child, stream output, send a signal, append a lifecycle event,
run OCI, contact a Worker or reach a scientific conclusion.
