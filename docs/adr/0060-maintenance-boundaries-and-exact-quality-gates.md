# ADR-0060: Maintenance boundaries and exact quality gates

Status: Proposed for review with the M1/M2 maintenance change.

## Problem

The integrated tree has stale pre-live status prose. Its coverage tool can round
84.77% to the 85% floor when deciding the exit code, while printing a failure.
GPU output preparation can invoke sudo/chown/setfacl implicitly and follow host
paths during privileged mutation. Independent capability strings and unpublished
domain payload schemas also make compatibility changes difficult to review.

## Decision

- Require at least 85% statement-plus-branch coverage using integer counts.
  Retain branch coverage, source scope and existing exclusions. Set report
  precision to three and independently validate coverage JSON totals in CI.
- Output preparation never obtains additional privilege. Existing root authority
  can use descriptor-based fchown; non-root operators must provision ownership
  before launch. Walk directories with O_NOFOLLOW and reject special files,
  symlink paths and multiply-linked regular files before mutation. Keep the
  existing non-root container user and claim-before-execution authorization.
- Known plan capabilities are centrally registered, including the historical
  process.native preflight and inert train.simulated capabilities. Registration
  does not make a runtime executable. Unknown capability plans cannot authorize;
  known plans keep their existing strings and digests. Kernel and execution
  namespaces retain their distinct meaning.
- Export a core domain payload catalog from the existing Pydantic models.
  Keep the v0alpha1 extensible event envelope and consumer-specific actor,
  reference and transition checks. Do not add required payload fields or rewrite
  historical events. New contracts need explicit version/migration review.
- Check installed-wheel execution outside the source checkout with no torch or
  ms-swift. An offline accept/reject research loop must work independently of
  training extras. This is a packaging gate, not SSH onboarding or GPU proof.
- Generate both README status tables from one reviewed evidence index. Historical
  experiment receipts remain immutable; update interpretation documents only.

## Consequences and limits

Non-root installations that relied on implicit sudo/ACL elevation now fail
closed with gpu-output-unwritable until an operator provisions directories.
This does not isolate a malicious host administrator or a hostile same-UID
process. Docker access itself remains privileged host authority.

Money parsing rejects exponent notation, nonfinite values, negative values and
out-of-contract precision before arithmetic. This does not convert USD to CNY;
the budget protocol remains CNY and ResearchSpec resource currency is descriptive.

No new CUDA grant, cloud payment, public release, asymmetric signing system or
NativeProcessRuntime is introduced. The accepted cuda.11 evidence applies to its
recorded runtime SHA. Maintenance boundary tests do not relabel it as a new live run.
