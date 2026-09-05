# ADR-0011: Apache-2.0 Project License

- Status: Accepted
- Date: 2026-08-21

## Context

The project is intended for broad research and engineering adoption while remaining independent of any company or upstream framework.

## Decision

Project code and original documentation are released under Apache License 2.0 unless a file explicitly states otherwise. Third-party code, data, models and notes retain their own licenses and provenance.

## Consequences

- Commercial and academic reuse is permitted under the license conditions.
- Patent and notice obligations must be preserved.
- The project license does not grant rights to imported datasets, papers, model weights or third-party notes.
- CLA, DCO and other contribution mechanics are not silently assumed; they require a follow-up decision before being imposed.

## Validation

The repository contains the unmodified Apache-2.0 license text, including the
appendix placeholders. [NOTICE](../../NOTICE) names the copyright owner
`victorzhong0110`. `pyproject.toml` declares SPDX `Apache-2.0`.

