"""Immutable result objects returned by the event store."""

from __future__ import annotations

from dataclasses import dataclass

from llm_research_os.events.models import ResearchEvent


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """A validated ResearchEvent plus store-owned persistence metadata."""

    event: ResearchEvent
    recorded_at: str
    digest: str

    @property
    def sequence(self) -> int:
        """Return the globally ordered sequence as an integer."""

        return int(self.event.sequence)

    @property
    def stream_version(self) -> int:
        """Return the store-assigned version within the event stream."""

        return self.event.streamversion
