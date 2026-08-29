"""Generic in-memory projection fold over already-validated ResearchEvents."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from llm_research_os.events.models import ResearchEvent


class Projection[StateT](Protocol):
    """A pure fold from ordered events into an in-memory state value."""

    def initial_state(self) -> StateT:
        """Return the empty projection state."""

    def apply(self, state: StateT, event: ResearchEvent) -> StateT:
        """Return the next state after applying one verified event."""


def fold_events[StateT](
    events: Iterable[ResearchEvent],
    projection: Projection[StateT],
    *,
    resume: StateT | None = None,
) -> StateT:
    """Fold verified events into projection state without performing I/O.

    ``resume`` continues from a previously folded state. When omitted, the
    projection starts from ``initial_state()``.
    """

    state = projection.initial_state() if resume is None else resume
    for event in events:
        state = projection.apply(state, event)
    return state
