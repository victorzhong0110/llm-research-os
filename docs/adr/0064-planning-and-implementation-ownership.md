# ADR-0064: Separate global planning ownership from implementation

Status: Proposed for repository integration in PR #84; records the maintainer's
explicit instruction assigning global normative guidance to the planning/review
assistant. Merge and milestone acceptance remain with the maintainer.

## Context

R01 drafts changed headings while retaining superseded work-package definitions,
Web-first dependencies, and inconsistent evidence labels. Passing documentation
checks did not establish alignment with the assigned task. Requiring implementers
to reconstruct global instructions mixed planning decisions with implementation.

## Decision

The designated planning/review assistant authors and maintains global plans,
package boundaries, cross-cutting normative guidance, and acceptance criteria.
Assigned implementers execute those packages, make routine technical choices,
maintain package-local documentation, and submit tests and factual evidence.
The maintainer can change assignments and instructions at any time.

Implementers propose material scope, authority, or acceptance changes explicitly;
they do not silently rewrite canonical guidance to fit an implementation. The
planning/review assistant reconciles approved changes. This does not add approval
requirements to routine in-scope work or invalidate existing authorization.

The R01–R16 meanings and A/B/C/D checkpoints in the corrected M3 plan supersede
older proposed mappings. Existing scoped M1/M2 acceptance remains unchanged.
Issue #53 is reviewed on its native-consumption evidence independently of R16.

## Consequences and validation

- `AGENTS.md` links one canonical plan and the governance document.
- The master plan and evidence matrix use the same package identities.
- Candidate evidence, merge status, and acceptance are recorded separately.
- Cross-cutting changes carry a proposed-difference explanation for review.
- No GitHub permissions, protection rules, runtime authority, tags, or publication
  are changed by this ADR. The repository remains pre-release.
- Validate links, translations, exact package/dependency/checkpoint correspondence,
  and historical evidence scope. Runtime tests are not added for this policy.

## References

- [Development governance](../development-governance.md)
- [M3 plan](../plans/m3-development-plan.md)
- [M3 acceptance matrix](../evidence/m3/acceptance-matrix.md)
- [ADR-0062](0062-m1-m2-acceptance-and-m3-boundary.md)
