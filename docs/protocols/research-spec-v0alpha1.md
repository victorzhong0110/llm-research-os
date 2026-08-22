# ResearchSpec v0alpha1

> Status: Experimental external contract  
> API version: `researchos.dev/v0alpha1`  
> JSON Schema: `schemas/research-spec/v0alpha1.schema.json`

ResearchSpec describes why an experiment exists, what it uses, how its workflow is composed, which limits apply and how revisions differ. It is not a training-backend configuration file.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative requirements in this document.

## 1. Authority layers

1. The committed JSON Schema is the language-neutral structural contract.
2. This document defines cross-object semantics that JSON Schema cannot express completely.
3. Positive and negative examples form an initial conformance corpus.
4. The Python package is the first reference implementation, not an additional hidden protocol.

An implementation that only validates JSON Schema is a **structural validator**. A conforming v0alpha1 implementation MUST also enforce the semantic rules below.

## 2. Envelope and revisions

Every document MUST contain:

```yaml
apiVersion: researchos.dev/v0alpha1
kind: ResearchProject
metadata:
  id: project-id
  revision: 1
  title: Project title
```

- `metadata.id` identifies one research project across revisions.
- `metadata.revision` MUST be a positive integer.
- A new revision of the same project MUST have a greater revision number.
- Once a Run refers to a revision, that revision MUST NOT be modified in place.
- Comparing documents with different project IDs is not a revision diff.

The M0 package validates revision ordering when `researchos diff OLD NEW` is used. Run immutability is a kernel requirement for the later Run store.

## 3. Identity and references

Top-level questions, hypotheses, evidence records, datasets, models, workflows, evaluations and resources share one ID namespace and MUST be globally unique inside a document.

Node IDs are scoped to one `WorkflowGraph` and MUST be unique within that graph. A nested loop body creates a nested graph scope.

References MUST resolve:

- every `Hypothesis.questionRefs` entry to a declared question;
- every `EvaluationSpec.datasetRefs` entry to a declared dataset;
- every task `resourceRefs` entry to a declared resource;
- every workflow edge endpoint to a node in the same graph.

IDs are identifiers, not filesystem paths or shell fragments. Implementations MUST NOT interpolate an ID into a path or command without separate encoding and validation.

## 4. Closed structure and extension points

Unknown structural fields MUST fail validation. This catches misspellings and prevents an adapter from inventing hidden protocol behavior.

Open-ended values are allowed only at declared boundaries:

- `ModelSpec.config` for model-specific parameters;
- `TaskBlock.config` for block-specific parameters;
- root `extensions` for namespaced experimental data.

These values MUST contain finite JSON-compatible data. Their presence does not grant execution permission. A consumer MUST validate the relevant block or extension schema before acting on them.

## 5. Workflow semantics

Each `WorkflowGraph` MUST be acyclic. Edges MUST reference existing nodes, self-edges are invalid and duplicate edges are invalid.

Iteration is represented only by a `LoopBlock`:

- `maxIterations` is mandatory and positive;
- `body` is a nested `WorkflowGraph` and therefore acyclic at its own level;
- each runtime iteration will later receive a distinct attempt identity;
- `until` declares the inert expression language `researchos.expr/v0alpha1`;
- M0 stores and validates the expression as text but MUST NOT execute it;
- changing the loop body during a Run requires a new ResearchSpec revision.

Retry is not a research iteration. Retry attempts to repeat the same intended operation; a research iteration may intentionally change data, policy or parameters and must remain auditable.

## 6. Resources, cost and time

A resource with `paid: true` MUST declare `maxCost` and `maxWallTimeSeconds`.

A loop that either:

- declares `mayIncurCost: true`; or
- references a paid, GPU, TPU or Ascend resource anywhere in its nested body

MUST also declare loop-level `maxCost` and `maxWallTimeSeconds`. These are protocol limits. Runtime enforcement is required before real execution and is not implemented in this slice.

## 7. Evidence and dataset rights

Reading, retrieval, training and redistribution are distinct uses.

- Every dataset source declares a rights status and `allowedUses`.
- `rights: unknown` MUST NOT authorize `training` or `redistribution`.
- A human review that establishes adequate rights SHOULD create a new provenance or rights record; it MUST NOT silently reinterpret `unknown`.
- This mechanism is an operational safety gate, not a legal opinion.

## 8. Constitutional policy fields

The following v0alpha1 values are invariants:

- `preserveAiDissent` is always `true`;
- `unknownEvidenceMayTrain` is always `false`.

Paid and destructive approvals remain configurable because a researcher may explicitly delegate authority under a future policy engine. Such a value does not itself grant a model or adapter capability.

## 9. Semantic diff

The reference diff is ID-aware:

- pure reordering of ID-bearing entities is not a semantic change;
- object addition, removal and field changes are reported by stable ID path;
- changes are classified as metadata, research, execution, governance or extension impact;
- a diff requires the same project ID and an increasing revision number.

The current diff does not yet calculate compatibility or scientific-risk severity. Those require additional rules and tests.

## 10. Conformance commands

```bash
uv run researchos validate examples/valid/minimal.yaml
uv run researchos schema --check schemas/research-spec/v0alpha1.schema.json
uv run pytest
```

Valid examples MUST pass both Draft 2020-12 structural validation and reference semantic validation. Invalid examples may target either structural or semantic rules; their expected failure layer will be made machine-readable as the conformance corpus grows.

## 11. Deliberate M0 limitations

v0alpha1 does not yet define:

- BlockManifest port typing and capability negotiation;
- ResearchEvent and Run state-machine schemas;
- expression evaluation;
- Worker transport or authentication;
- plugin discovery or isolation;
- secret-reference objects;
- event, artifact or projection persistence;
- runtime enforcement of budgets and approvals.

These omissions are explicit. Adapters MUST NOT fill them with hidden, incompatible semantics and call the result conforming v0alpha1 behavior.

