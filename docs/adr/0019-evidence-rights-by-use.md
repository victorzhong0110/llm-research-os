# ADR-0019: Evidence Rights Are Tracked by Use

- Status: Accepted
- Date: 2026-08-21

## Context

Reading a paper, retrieving a note, training on copied content and redistributing a dataset are legally and operationally different actions. A single “open” flag cannot represent those distinctions.

## Decision

Evidence and dataset sources record provenance, rights status, license when known, digest or snapshot when available, and allowed uses. Unknown rights default to research reading only and cannot authorize training or redistribution.

This protocol check is a conservative operational gate, not a legal conclusion. Human review may create a new, documented rights decision when evidence supports it.

## Consequences

- Research assistance remains possible without silently converting all sources into training data.
- Data-building workflows must propagate provenance and use restrictions.
- Published datasets and models require a separate rights and provenance review.

## Validation

The v0alpha1 validator rejects a source with `rights: unknown` when `allowedUses` contains `training` or `redistribution`.

