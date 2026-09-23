# Native reviewed preparation v0alpha1

> Status: R04 candidate. Preparation and diagnosis only; user code is not started
>
> Constraint record: [ADR-0065](../adr/0065-reviewed-native-execution-authority.md)
>
> Request contract: [Native reviewed execution v0alpha1](native-reviewed-execution-v0alpha1.md)

This document specifies how a reviewed `native-reviewed-python/v0alpha1`
request is materialized into a private workspace. It does not change the R03
request/report contract, consume a Worker grant, append a Run or Attempt
fact, or start an entrypoint. `launchAllowed` stays false. Real entrypoint
execution remains R05.

## Authority

`prepare` and `doctor` rebuild three facts before any workspace decision:

1. The cited `plan.authorization.evaluated` event on the existing EventStore,
   including a human actor, `authorized=true`, capability `execute.native`,
   and the request's digest binding. `revisionId` is the decimal string of
   that event's `experimentRevision`.
2. The existing `rg1` HMAC grant (`verify_grant_token`) and the WorkerControl
   fold of `authorization.grant.recorded`, `revoked`, and `consumed`.
3. The CAS bytes named by the request: bundle, code, inputs, interpreter
   identity, dependency lock, inventory, and the canonical review document.

Caller-supplied prefix citations, prepared citations, and grant booleans from
the R03 validator are contract fixtures. They are not inputs to this package.
An R03 validation report, an application receipt, and an audit signature are
not launch credentials. A successful preparation receipt is not one either.

The grant `imageDigest` binds the reviewed bundle (`sha256:`), media type
`researchos.native-reviewed-python-bundle/v0alpha1`. A
`researchos.python-brick/v0alpha1` object cannot satisfy that binding.
`configDigest` is the JCS digest of the execution object (profile, platform,
code, inputs, environment, limits, restrictions). It is not a separate CAS
object.

## Material documents

Each document is a closed `researchos.dev/v0alpha1` object. Generated schemas
are registered with `researchos schema`. Do not edit the schema files by hand.

| Kind | Role |
| --- | --- |
| `NativeReviewedPythonBundle` | Digest index of bundle-relative `.py` files. The entrypoint `package.module:function` maps to `package/module.py` by string only. No import. |
| `NativeReviewedCodeReview` | Review citation stored as canonical JSON. CAS lookup is `sha256:` of the `jcs-sha256:` hex. |
| `NativeReviewedInterpreterIdentity` | CPython version, ABI (`cp312`, `cp313`, or `cp314`), and platform. A filesystem path is rejected. |
| `NativeReviewedDependencyLock` / `NativeReviewedDependencyInventory` | Closed pin lists (`name`, `version`, `digest`), unique and sorted. The two lists must match. Pins are not installed or imported. |
| `NativeReviewedPreparationReceipt` | Binding of those digests to the grant id. `interpreterIdentity` is the constant `byte-digest`. |
| `NativeReviewedPreparationDiagnosis` | Doctor outcome. `ready` still has `launchAllowed=false`. |

The host `platform.system()`, `platform.machine()`, `python_version()`, and
`python_implementation()` must match the interpreter document. A mismatch
refuses with `environment-identity-mismatch`. `sys.executable` is never an
identity and is not recorded.

Receipt side effects are literal zeros: `entrypointsImported`,
`processesSpawned`, `lifecycleFactsAppended`, `grantsConsumed`, and
`packagesInstalled`. The receipt cites digests and the grant id. It does not
carry an HMAC, a secret, or an absolute path.

## Workspace

A fresh workspace is absent or empty. Preparation creates private directories
(`0700`) and regular files (`0600`) with `O_NOFOLLOW`, refuses symbolic links,
writes `receipt.json` last, and fsyncs. Layout:

```text
receipt.json
material/bundle
material/code/<relative.py>
material/inputs/<name>
material/config.json
material/environment/interpreter
material/environment/dependency-lock
material/environment/inventory
material/environment/review
```

Repeated preparation of a workspace whose receipt and bytes still match is a
no-op success. An occupied workspace that is incomplete, damaged, or bound to
different bytes is refused. It is not overwritten, repaired, or silently
reused. Artifact objects above the existing 1 MiB CAS cap are refused.
The EventStore is opened read-only (`create=False`).

## Substitution before user code

`check_before_user_code` re-reads the EventStore, grant, CAS, and workspace
and returns a diagnosis. It does not import an entrypoint or spawn a process.
Replacing code, configuration, an input, the interpreter identity, the lock,
the inventory, or the review citation yields an invalidated diagnosis
(`code-substituted`, `config-substituted`, `input-substituted`,
`environment-substituted`, `review-substituted`, or `binding-invalidated`)
and the old receipt is not treated as current.

Doctor outcomes are `ready` (`preparation-ready`), `incomplete`, `damaged`,
`mismatched` (`environment-mismatch`), `invalidated`, and `refused`. The CLI
exits 0 only for a prepared receipt or a ready diagnosis. Every other
outcome exits 1 with the diagnosis or a ProblemReport.

## Commands

```text
researchos native prepare REQUEST DATABASE ARTIFACTS WORKSPACE \
  --grant-token-file TOKEN --hmac-key-file KEY
researchos native doctor REQUEST DATABASE ARTIFACTS WORKSPACE \
  --grant-token-file TOKEN --hmac-key-file KEY
```

`researchos native run` remains the `restricted-v0alpha1` noop. Neither
`prepare` nor `doctor` starts user code.

## Out of scope

Implicit system installs, arbitrary dependency execution in the control
plane, cloud provisioning, a training-framework requirement, and the R05
entrypoint process are outside this contract.
