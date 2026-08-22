# ADR-0004: Modular Monolith First

- Status: Accepted
- Date: 2026-08-21

## Context

The first implementation is developed on one Apple Silicon laptop by one primary maintainer. Premature services would add deployment, networking and compatibility costs before protocol boundaries have evidence.

## Decision

Start as one installable Python distribution with explicit internal modules and protocol boundaries. Remote Workers are external participants, not a reason to split the control plane into services during M0.

## Consequences

- Local simulation and testing remain inexpensive.
- Module APIs must not be confused with stable external protocols.
- A later service split requires evidence and an ADR, but not a rewrite of ResearchSpec.

## Validation

The complete M0 validation toolchain runs locally without a database, container or network service.

