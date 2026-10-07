# Evidence-linked research workflow v0alpha1

Status: R12 engineering continuation from verified main `5a99c71` (#141), preserving the partial ledger integration in #134. Candidate validation is separate from full R12/Checkpoint C acceptance. Requirements remain the [M3 plan](../plans/m3-development-plan.md#r12-ai-proposals-citations-and-researcher-decisions); local transport follows the [local API](local-api-v0alpha1.md).

This application surface composes the existing M1 research, evidence, provider and budget controls. It does not issue Worker grants, queue Runs, execute evidence, or derive human decisions. Published contracts are the generated application command/receipt and research-model-profile schemas.

## Commands and material identity

| Operation | Input | Result/effect |
| --- | --- | --- |
| `model.inspect` | installed profile ID, expected head | frozen material digest, model/call identity, declared spend/capabilities, current budget; no request |
| `model.generate` | same ID, inspected digest, expected head/revision | one durably reserved call through Mock or configured compatible provider; output becomes a validated draft only after all checks |
| `model.observe` | installed profile ID, expected head | existing call facts and output; never dispatches |
| `research.draft` | typed proposal, base/candidate CAS IDs, expected head/revision | recomputed diff and resolved sources, validated draft CAS artifact; no fact |
| `research.submit` | same typed material | one proposal fact; no Run or grant |
| `research.record` | typed decision, dissent, supplied model/system question or human answer | existing ResearchControl CAS fact; no Run or grant |
| `evidence.import` | typed metadata, simple inbox filename, expected head/revision | frozen bytes and extracted text in CAS, one evidence fact |
| `research.budget` | expected head | consumed/outstanding/approved/remaining project budget and open reservations; provider invoice cost remains unknown |

Legacy application `proposal.validate`/`proposal.submit` also require `baseArtifact` and `candidateArtifact` and enforce the same recomputation. Historical M1 CLI objects and accepted event contracts remain unchanged; an application caller must supply the additional material bindings.

A `ResearchModelProfile` is operator-installed at `<workspace>/model-profiles/<simple-ID>.json`. Its `request` and `fixture` reference bounded, regular, symlink-free workspace files; they contain existing typed generate and fixture documents. Base/candidate objects are bounded CAS ResearchSpecs. Browser input cannot select arbitrary endpoints, secret references, profile JSON, process commands or host paths. Existing compatible-provider endpoint, DNS pinning, permission and budget gates remain in force. Secrets resolve from the installed request's env reference at dispatch and are never returned in the inspection or receipt. Changing profile material invalidates the inspected digest.

The base must match the expected revision and the latest recorded project specification when one exists. A project with no recorded specification can only draft from revision 1. The candidate must be a later revision of the same project. Raw CAS identity and semantic specification identity remain distinct.

The server computes changes using `semantic_diff(base, candidate)` and derives:

```text
content_digest({
  baseSpecDigest: spec_identity(base),
  candidateSpecDigest: spec_identity(candidate),
  changes: [change.as_dict() for change in semantic_diff(base, candidate)]
})
```

Here `spec_identity` hashes the spec's JSON model dump with aliases and `exclude_none=True`; `content_digest` is RFC 8785 JCS. The proposal's candidate and diff digests must match. Rationale, predictions, falsification conditions, risks and evidence refs use the existing strict proposal contract. Resource needs come from the actual candidate specification, not an AI claim about authority.

## Drafts, rights and decisions

Mock output is a typed fixture output. Compatible output is the strict JSON document in the existing adapter's `text` output artifact. Malformed output, extra executable fields, actor mismatch, stale base, forged diff and unresolved citations produce no validated draft. Completed invalid output remains auditable as a model fact/CAS output; it is not submitted automatically.

Each citation resolves to this project's imported evidence ID and returns its source/version fact, snapshot/text identities, license, rights and allowed uses. Reading is separate from training. Unknown rights cannot authorize training or redistribution. Imported text is inert evidence, including hostile instructions.

The dedicated `<workspace>/evidence-inbox/` accepts only simple Markdown/PDF filenames. Freezing takes bytes and the exact derived fact before the command's identity is computed. A later file change cannot alter the import; a changed snapshot conflicts with an already committed receipt. Native tokens, keys and other files outside the inbox cannot be selected for import. Frozen imports retain the caller's CAS head at the append boundary. Existing extraction limits and isolated PDF extraction remain unchanged.

Human amendment in the browser creates a human-authored proposal event identity and revalidates the edited text; the original generated draft stays in CAS. Accept/reject/modify, supplied questions, human answers and dissent use the existing ledger reducer. Overriding dissent requires explicit IDs; disagreement remains visible. Acceptance itself launches nothing. Closed proposals cannot be re-decided; the existing reducer refuses a second acceptance/rejection with `proposal-not-open`. Reading the bounded ledger appends nothing and retains per-kind withheld counts.

## Dispatch, retry and observation

A durable per-project/call reservation precedes model effects and is never released by this application layer. The compatible provider's first budget reservation preserves the caller's expected EventStore head; the Mock's first fact does likewise. A CAS conflict is refused before HTTP transport. Known pre-dispatch and uncertain post-dispatch failures retain the existing provider budget semantics; uncertain outbound calls do not release a reservation or automatically retry.

An exact committed command replays its durable receipt. Changed content under the same identity conflicts. A new command cannot dispatch the same reserved call again. If the process loses the receipt after model facts commit, `model.observe` verifies stored project, call, actor, time and prompt identity, verifies the CAS output digest, and reconstructs a draft without making a request. Missing/incomplete facts remain unknown. A stale completed output can be observed but cannot be promoted to a current validated draft.

Proposal, decision and evidence facts committed just before receipt loss recover only when their complete frozen fact is identical. No conflicting event ID can recover another fact. A refusal does not promise rollback of a previously dispatched effect.

## Limits and non-goals

This is a same-user operator workbench, not adversarial host isolation. Direct same-user database/filesystem mutation remains outside the boundary. Profiles do not provide general autonomous agents, tools, literature crawling, automatic acceptance, unlimited retries or invoice reconciliation. Local compatible-server and Mock tests are synthetic contract evidence; they do not establish paid-provider availability, research improvement, selected GPU/two-host evidence, human trials or Checkpoint C acceptance.
