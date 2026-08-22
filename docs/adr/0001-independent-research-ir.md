# ADR-0001: Independent Research IR

- Status: Accepted
- Date: 2026-08-21

## Context

Existing training, workflow and agent frameworks expose useful execution capabilities, but each centers its own domain model. Making one of them the project's source of truth would prevent experiments that replace the training or agent framework itself.

## Decision

The project owns a versioned Research IR headed by `ResearchSpec`. NeMo, ms-swift, generic Python, containers, agent harnesses and cloud systems are replaceable adapters. None may add hidden state that changes the meaning of a ResearchSpec revision.

## Consequences

- The core can express research that does not fit an existing framework.
- Adapters must translate explicitly and report unsupported semantics.
- We must maintain protocol compatibility tests instead of inheriting another project's compatibility guarantees.

## Validation

M0 validates and compares a ResearchSpec without installing any training backend.

