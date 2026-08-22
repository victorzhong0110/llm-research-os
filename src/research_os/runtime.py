"""``SimulatedRuntime`` — runs a full vertical loop with no GPU (milestone M0).

The runtime consumes an approved ``ResearchSpec`` and emits a deterministic
sequence of CloudEvents-compatible ``ResearchEvent`` facts into an
:class:`~research_os.store.EventStore`, exercising the happy path plus the
failure and cancellation paths the charter requires (section 14.2).
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from research_os.models.research_event import EVENT_TYPE_PREFIX, ResearchEvent
from research_os.models.research_spec import ResearchSpec
from research_os.store import EventStore

SOURCE = "runtime/simulated"


class Outcome(StrEnum):
    """How a simulated run should terminate."""

    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"


def _event(spec: ResearchSpec, run_id: str, suffix: str, **data: object) -> ResearchEvent:
    return ResearchEvent(
        source=SOURCE,
        type=f"{EVENT_TYPE_PREFIX}.{suffix}",
        projectId=spec.metadata.id,
        experimentRevision=spec.metadata.revision,
        runId=run_id,
        data=dict(data),
    )


class SimulatedRuntime:
    """Executes a research spec as a deterministic, GPU-free simulation."""

    def __init__(self, store: EventStore) -> None:
        self._store = store

    def run(
        self,
        spec: ResearchSpec,
        *,
        run_id: str | None = None,
        steps: int = 3,
        outcome: Outcome = Outcome.COMPLETE,
    ) -> str:
        """Run ``spec`` in simulation, appending events, and return the run id."""
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"

        self._store.append(_event(spec, run_id, "run.queued", steps=steps))
        self._store.append(_event(spec, run_id, "run.leased", worker="simulated-local"))
        self._store.append(_event(spec, run_id, "run.started"))

        for step in range(1, steps + 1):
            # Deterministic, monotonically decreasing pseudo-loss for demo signal.
            loss = round(1.0 / (step + 1), 6)
            self._store.append(_event(spec, run_id, "train.step", step=step, loss=loss))
            if outcome is Outcome.FAIL and step == steps:
                self._store.append(_event(spec, run_id, "run.failed", reason="simulated failure"))
                return run_id
            if outcome is Outcome.CANCEL and step == steps:
                self._store.append(
                    _event(spec, run_id, "run.cancelled", reason="operator cancelled")
                )
                return run_id

        self._store.append(
            _event(spec, run_id, "run.completed", final_loss=round(1.0 / (steps + 1), 6))
        )
        return run_id
