"""SQLite append-only ResearchEvent fact storage."""

from llm_research_os.storage.errors import (
    DuplicateEventError,
    EventAppendError,
    EventIntegrityError,
    EventSequenceConflictError,
    EventStoreError,
    EventStoreSchemaError,
)
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore

__all__ = [
    "DuplicateEventError",
    "EventAppendError",
    "EventIntegrityError",
    "EventSequenceConflictError",
    "EventStore",
    "EventStoreError",
    "EventStoreSchemaError",
    "StoredEvent",
]
