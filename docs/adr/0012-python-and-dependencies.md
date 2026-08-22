# ADR-0012: Python and Dependency Boundaries

- Status: Accepted
- Date: 2026-08-21

## Context

The control plane must run on the maintainer's Apple Silicon Mac and ordinary Linux systems without inheriting CUDA or training-framework dependency conflicts.

## Decision

Use Python 3.12+, `pyproject.toml`, uv and a committed `uv.lock`. Test Python 3.12 and 3.13. Core dependencies must not include NeMo, ms-swift, CUDA or a cloud SDK merely to validate a ResearchSpec.

Training backends use their own Worker or container environments and communicate through versioned protocols.

## Consequences

- Core installation remains small and reproducible.
- Backend adapters may use different Python versions without changing the control-plane contract.
- Lockfile changes are reviewed as supply-chain changes.

## Validation

CI installs with `uv sync --locked --all-groups`; M0 tests run without accelerator packages.

## References

- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [Python version status](https://devguide.python.org/versions/)
