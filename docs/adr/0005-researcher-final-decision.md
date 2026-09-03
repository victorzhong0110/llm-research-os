# ADR-0005: Researcher Final Decision and Preserved AI Dissent

- Status: Accepted
- Date: 2026-08-21

## Context

An AI research control plane can silently treat model output as a scientific
conclusion, overwrite a researcher's choice, or drop the record of an AI
objection once a human decides otherwise. Charter principles P1 and P2 forbid
that: the researcher holds default final scientific judgment, AI must be able
to object, and any change that affects data, code, training, budget or
conclusions must be an explicit proposal, approval or policy grant.

M0 does not yet run a live assistant. The constraint still has to be written
before Proposal, Dissent and Decision objects appear in M1, or those objects
will be invented as convenience types instead of as an audit trail.

## Decision

The researcher has default final scientific decision rights. An AI may object
and must be able to persist that objection. A researcher override does not
delete, rewrite or hide the dissent. Covering a recommendation is itself an
auditable act.

AI-initiated changes that affect experiment definition, data, code, training,
budget or conclusions MUST correspond to a traceable proposal, approval or
policy authorization. There is no hidden in-place mutation of a running
revision.

This slice records the constitutional rule. It does not freeze Proposal,
Dissent or Decision schemas. Those remain M1 deliverables and MUST preserve
this rule.

## Consequences

- Simulated completion, dry-run `ready`, and `authorized` are not scientific
  conclusions.
- Later assistant adapters cannot treat a model vote as execution authority.
- Override and dissent are separate facts; UI aggregation must not collapse
  them into a single winner.

## Validation

M0 tests already keep simulated `completed` distinct from a supported
hypothesis, and keep authorization reports explicitly non-credential. M1
Proposal/Dissent/Decision schemas MUST add corpus tests that a stored dissent
survives a later human decision.

## References

- [Project charter v0.1 §5 P1–P2](../charter-v0.1.md)
- [Chapter 18 decision 15-AUC](../chapter-18-decision-guide-v0.1.md)
- [ADR-0030 Deterministic Plan Authorization Gate](0030-deterministic-plan-authorization-gate.md)
