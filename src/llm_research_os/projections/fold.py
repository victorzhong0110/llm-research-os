"""Generic in-memory projection fold over already-validated ResearchEvents."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, cast

from llm_research_os.events.models import ResearchEvent

_RESUME_UNSET = object()


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
    resume: StateT | object = _RESUME_UNSET,
) -> StateT:
    """Fold verified events into projection state without performing I/O.

    Omit ``resume`` to start from ``initial_state()``. Pass ``resume=None`` when
    ``None`` is a legitimate checkpoint for ``StateT``.
    """

    state = projection.initial_state() if resume is _RESUME_UNSET else cast(StateT, resume)
    for event in events:
        state = projection.apply(state, event)
    return state
