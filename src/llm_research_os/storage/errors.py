"""Stable error types for the local SQLite fact store."""


class EventStoreError(RuntimeError):
    """Base class for event-store failures."""


class EventStoreSchemaError(EventStoreError):
    """Raised when a database does not match the supported schema."""


class EventAppendError(EventStoreError):
    """Raised when an event draft cannot be appended."""


class DuplicateEventError(EventAppendError):
    """Raised when an event ID has already been persisted."""


class EventIntegrityError(EventStoreError):
    """Raised when persisted facts fail an integrity check."""
