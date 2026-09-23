# Native reviewed execution v0alpha1 contract

> Status: R03 normative design; validation-only until R05 real execution
>
> Constraint record: [ADR-0065](../adr/0065-reviewed-native-execution-authority.md)

This is the proposed external request/report shape for one reviewed Python
task. R03 implements strict models, generated JSON Schemas, examples, and a
non-launching validator. It does not turn `researchos native run`'s existing
`restricted-v0alpha1` noop into real execution. Only an independently
accepted R05 Worker path may start an entrypoint.

## Request identity

The document uses `apiVersion: researchos.dev/v0alpha1` and
`kind: NativeReviewedExecutionRequest` (or
`NativeReviewedExecutionReport` for the report). The profile is
`native-reviewed-python/v0alpha1`. All digest fields use the
repository's existing explicit `sha256:` byte digest or `jcs-sha256:`
semantic digest type. IDs, times and digest references are supplied by the
caller and validated, never silently minted or replaced. The request is a
closed object. Nested objects also reject unknown fields.

| Field | Required binding |
| --- | --- |
| `apiVersion`, `kind`, `profile`, `platform` | Exact discriminators and `linux` or `darwin`; unsupported OS/architecture/interpreter ABI fails closed |
| `projectId`, `revisionId`, `workflowId`, `taskId` | One project, immutable spec revision, workflow and planned graph node |
| `runId`, `attemptId`, `workerId` | One existing Run, Attempt and registered Worker; no duplicate new Attempt on retry |
| `authorizationEventId`, `authorizationSequence` | This EventStore's human `plan.authorization.evaluated` fact with `authorized=true` and `execute.native` |
| `specDigest`, `registryDigest`, `planDigest`, `decisionDigest` | The same exact cited authorization binding; `decisionDigest` is the authorization decision, not an AI proposal or an R02 receipt |
| `code` | Byte digest and media type of a reviewed immutable bundle; entrypoint in that bundle; review citation bound to that digest |
| `inputs` | Closed list of named CAS object byte digests with purpose/size; no arbitrary paths or URLs |
| `configDigest` | JCS digest of the complete planned execution object including profile, code, input references, environment and limits |
| `environment` | Executable byte digest plus version/ABI, dependency lock and resolved inventory digests, supported platform identity; no mutable path-only identity |
| `limits` | Bounded wall time, stdout/stderr and artifact bytes; optional process and memory ceilings carry explicit required/enforcement status |
| `restrictions` | Network, filesystem and memory requests with `required` flag; rejection if a required restriction cannot be enforced |

The implementer defines exact JSON keys and canonicalization of the nested
`code`, `inputs`, `environment`, `limits`, and `restrictions` objects in the
R03 generated schemas and valid examples. They must retain every binding in
this table, reject unknown nested keys, and specify byte/count maxima.
`code` includes bundle digest, media type, entrypoint within the bundle and a
review citation tied to that digest; `environment` includes interpreter byte
digest, Python version/ABI, dependency lock and resolved inventory digests;
`limits` includes enforced wall/output bounds. Optional process/memory
ceilings cannot be claimed enforced without platform proof. The
authorization/grant `imageDigest` binds the reviewed code
bundle; `configDigest` binds the *whole* execution object, including its
image digest. A hash of only runtime options, or agreement among mutually
forged request/grant/queue objects, cannot replace reconstruction of the
cited plan. Existing Worker schema changes must be versioned and keep old
bricks compatible. A different media type or runtime cannot reuse an old
grant. The R04 preparation receipt may cite this identity; it cannot grant
launch authority.

Do not put an HMAC token, private key, secret value, absolute host path,
source body, or interpreter contents in the durable request/report. The
existing Worker session carries the grant credential separately.

## Validation and launch sequence

1. Parse a bounded request; reject unknown fields, ambiguous paths, duplicate
   input names, noncanonical digests and unsupported versions/platforms.
2. Verify project/workspace binding and the cited immutable spec, registry,
   plan, decision and planned task against the verified EventStore prefix.
   An R02 `ApplicationReceipt` may point to facts, but is not an authority.
3. Verify the reviewed code and prepared environment identities and every
   input/config digest, including the final point-of-use check required in
   R04. A changed byte or dependency inventory invalidates the binding.
4. Evaluate restriction requirements against **actual**, platform-specific
   enforcement. Reject required network, filesystem or memory isolation
   when unenforced; report advisory requests as `not-enforced` instead of
   falsely claiming isolation.
5. R03 stops here and returns a validation report with `launchAllowed=false`.
   R05 will additionally validate the exact Worker HMAC grant, expiry,
   revocation and lease, atomically claim/consume once, then spawn. A revoke
   committed before that gate denies; a later revoke requests cancellation
   and real observation. Crashes in the consume/spawn/identity interval
   remain unknown and cannot auto-rerun.

No validation, dry run, preflight, signed attestation, or application receipt
authorizes step 5 on its own.

## Validation report

The strict report is versioned and binds the request's semantic digest,
project/Run/Attempt/task IDs, authorization citation and exact profile. It
records `acceptedForPreparation`, `launchAllowed=false`, a stable outcome
and reason code, and per-restriction `requested`, `enforced`, `unsupported`
values for network, filesystem and memory. Missing evidence is reported as
missing, never inferred from a declaration. The report cites verified
code/input/environment digests without copying private bytes or paths.
Refusal reports do not append Run lifecycle facts or imply a started task.

R05 adds a separate execution result and Worker/Run/Attempt fact references;
the R03 validation report is never retrospectively rewritten as a successful
execution. A real result needs `work.completed` and verified artifact
digests; process exit alone is insufficient. `attempt.unknown`, cancellation
requested, and observed stop remain separate.

## R03 example and test matrix

Ship a valid Linux reviewed-code request and a valid macOS request only
where the report correctly identifies the unsupported network/filesystem/
memory restrictions. Include invalid examples for each of:

- foreign project or Run/Attempt/task, stale revision, mismatched cited event
  sequence or actor, swapped spec/registry/plan/decision digest;
- changed code, entrypoint, input bytes, configuration, interpreter or
  dependency inventory after authorization or preparation;
- an old `execute.local` or `process.native` authorization presented as
  `execute.native`, forged HMAC, expired/revoked grant, nonce replay and
  resumed claim that would otherwise spawn twice;
- unknown profile/platform, path-only executable, required network denial,
  required filesystem confinement or required memory bound without proven
  enforcement, and missing resource ceilings.

The R03 validator can use a test adapter for grant-state cases; it must
identify those as contract checks, not real R05 launches. Each negative
case asserts no entrypoint import, subprocess or new lifecycle fact. The
implementer publishes the generated schemas through `researchos schema`
and registers them with the existing CLI contract registry. Do not edit
generated schema files by hand. Record implementation SHA, commands and
test platform in the M3 acceptance matrix; leave real execution and live
fault cases for R05/R06.
