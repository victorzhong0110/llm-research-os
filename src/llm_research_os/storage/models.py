"""Immutable result objects returned by the event store."""

from __future__ import annotations

from dataclasses import dataclass

from llm_research_os.events.models import ResearchEvent


@dataclass(frozen=True, slots=True)
class IntegrityCheckpoint:
    """Live or remembered high-water fingerprint. Untrusted until revalidated."""

    high_water: int
    last_event_digest: str | None
    schema_digest: str
    verified_event_count: int


@dataclass(frozen=True, slots=True)
class RunProjectionRecord:
    """Rebuildable Run snapshot cache. Not a second fact source (TM-011)."""

    project_id: str
    run_id: str
    last_sequence: int
    snapshot_json: str | None
    snapshot_digest: str | None


@dataclass(frozen=True, slots=True)
class SpecRevisionRecord:
    """First-seen ResearchSpec digest for one project revision."""

    project_id: str
    revision: int
    spec_digest: str
    first_seen_sequence: int


@dataclass(frozen=True, slots=True)
class ArtifactIndexRecord:
    """Digest observed in a ResearchEvent payload or evidence ref."""

    digest: str
    byte_length: int | None
    first_seen_sequence: int


@dataclass(frozen=True, slots=True)
class ArtifactLinkRecord:
    """One event's use of a content digest, keyed by role."""

    digest: str
    event_sequence: int
    role: str


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
