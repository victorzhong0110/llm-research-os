# ADR-0039: The OS Serves the Period in Which Human Help Remains Necessary

- Status: Accepted
- Date: 2026-09-03

This record states the purpose that charter v0.1 §2 left implicit, and derives
from it the constraints M1 must satisfy when it models the researcher. It amends
ADR-0038 E4 (M1-1 object set, M1-5 report, checkpoint sentence) and extends
ADR-0005. It does not reopen ADR-0037 and does not change the M1 slice order.

## Context

Charter §2.1 describes the vision as an auditable, extensible, reproducible way
of doing LLM research with AI participation. That sentence is true in any decade
and does not say why this system is needed now. Without a stated purpose, priority
drifts toward generic infrastructure.

The researcher's thesis, recorded on 2026-09-03: the OS targets the period before
human intelligence becomes irrelevant to AI. During that period AI cannot fully
understand humans by observation alone, whether the limit is technical or a matter
of scarce resources, and still needs active human help. The OS exists to make that
help cheap, high in information, persistent and auditable.

M0 built control: identity, events, authorization, state machines, a threat model.
Control is one half of the problem; AI acting on human help must be bounded, or the
help channel becomes an attack surface. The other half, the channel through which
a human supplies what observation cannot, has no object yet. `run.reviewed`
carries only a `decisionId`; no rationale is recorded anywhere; overriding a
dissent leaves no reason; no object lets an AI component ask the researcher a
question. The event log records what the AI did and whether the human approved,
not what the human taught.

What observation cannot supply is concrete: which question is worth asking, what
counts as success, which risk is acceptable, why a given dissent fails, which
anomalies matter, and whose authority governs data, budget and publication.
ResearchSpec already carries the first two (`Hypothesis`, `Prediction`,
`EvaluationSpec`, `PolicySpec`). The rest must be supplied during the loop.

## Decision

### D1 — Purpose

The OS is the instrument that makes human help to AI cheap, high in information,
persistent and auditable for as long as that help is necessary.

Human input is of two kinds:

- **Information** the AI cannot infer from available observation: what matters,
  what counts as success, acceptable risk, why a dissent fails, which anomalies
  matter.
- **Authority** the AI must not infer: whose research this is, whose budget is
  spent, whose consent governs what data may be read, retrieved, trained on or
  redistributed.

The information kind may shrink as capability grows. The authority kind does not.
The validity of this OS therefore does not depend on whether, or when, human
intelligence becomes irrelevant. Charter §2 is amended by errata E12.

### D2 — The researcher is modeled as a teacher, not only an approver

Every human decision that resolves or overrides AI output MUST carry a rationale.
A decision that overrides a dissent MUST reference the dissents it overrides;
those dissents are never deleted or rewritten. This extends ADR-0005: dissent
survival is not only an audit property but a data property (see D5).

### D3 — One sanctioned channel for AI to ask the researcher

`question.asked` and `question.answered` are ResearchEvent facts. They are the
only path by which an AI component may request information from the researcher.

- A question MUST state the uncertainty it resolves and why available evidence
  could not settle it. A question that observation could have answered is a
  defect, not a neutral cost.
- An answer is a fact with rights (chapter 18 decision `14-RB`, ADR-0019). Its
  default allowed use is research reading; unknown rights cannot authorize
  training or redistribution.
- Answers and rationales are data for other components, never instructions
  (charter §10.4). They pass the same redaction and secret gates as any other
  payload (TM-007, TM-022).
- Only actors of kind `human` or `policy` may record decisions or answers; only
  actors of kind `ai` or `system` may ask questions. Actor kind is the M1-0
  extension of the ResearchEvent actor.

### D4 — North-star metric: human attention per unit of improvement

The OS reports how much human attention was spent per unit of pre-registered
outcome change: number of decisions, number of answered questions and rationale
length, against the change in pre-registered prediction accuracy or another
pre-registered outcome. The metric is part of the cost view (charter §12.1,
errata E14) and of the M1-5 report. Reducing human attention while holding
information content is a design goal; reducing information content to save
attention is not.

### D5 — Persistence into parameters is gated, not default

Decisions with rationale and answered questions are the candidate training facts
for governed parameter evolution (Issue #26). Preserved dissent is the negative
signal. A fact becomes training-eligible only when its rights allow `training`
and a human decision explicitly approves that use. Nothing enters weights by
default. Per-user adapters and content-addressed checkpoints are the rollback
path. This ADR does not schedule any parameter-update slice.

### D6 — Amendments to ADR-0038 E4

| Item | ADR-0038 E4 | Amended by this record |
|---|---|---|
| M1-1 deliverable | `proposal.submitted`, `dissent.recorded`, `decision.recorded`; CLI | Adds required `rationale` and `overriddenDissentIds` on decisions; adds `question.asked` / `question.answered`; adds a read-only research ledger projection. Field-level draft: [Research decision objects v0alpha1 (draft)](../protocols/research-decision-objects-v0alpha1.md). Tracked by Issues #41 and #42. |
| M1-5 deliverable | Static report with research, training, cost, lineage | Cost view includes the D4 metric |
| Checkpoint sentence | 研究者决定（异议保留） | 研究者决定（异议保留，**理由记录**） |
| Slice order | M1-0 → M1-6 | Unchanged |

## Consequences

- Charter §2, §9.2, §12.1 and §14.3 receive one-line pointers; §23 gains rows
  E12–E15. Original text is unchanged.
- The living threat model registers the question channel and rationale data as
  planned surfaces (TM-037 to TM-039) before any code exists for them.
- M1-1 cannot close with a `decision.recorded` payload that lacks a rationale, or
  with any AI-to-human information request outside `question.asked`.
- The first demonstrable M1 command chain must show a human answering a question
  and recording a reasoned decision, not only approving.
- A later parameter-update slice must consume only facts that pass D5. It needs
  its own ADR and threat-model review.

## Validation

1. Charter §23 contains E12–E15 and the pointers listed above.
2. Threat model contains TM-037, TM-038 and TM-039 marked as planned.
3. The M1-1 draft protocol document exists and Issues #38, #41 and #42 reference
   this record.
4. When M1-1 lands: corpus tests reject a decision without rationale, reject an
   answer without a prior question in the same project, reject a question from a
   `human` actor and a decision from an `ai` actor, and show a stored dissent
   surviving a later overriding decision.
5. When M1-5 lands: the report shows decisions, answered questions and rationale
   length next to the pre-registered outcome change.

## References

- [Project charter v0.1 §2, §9, §10.4, §12.1](../charter-v0.1.md)
- [Chapter 18 decisions 14-RB and 15-AUC](../chapter-18-decision-guide-v0.1.md)
- [ADR-0005 Researcher Final Decision](0005-researcher-final-decision.md)
- [ADR-0019 Evidence Rights by Use](0019-evidence-rights-by-use.md)
- [ADR-0038 Charter Errata After M0](0038-charter-errata-after-m0.md)
- [Research decision objects v0alpha1 (draft)](../protocols/research-decision-objects-v0alpha1.md)
- [Issue #26 Governed parameter evolution](https://github.com/victorzhong0110/llm-research-os/issues/26)
- [Issue #38 M1 tracking](https://github.com/victorzhong0110/llm-research-os/issues/38)
- [Living threat model](../security/threat-model.md)
