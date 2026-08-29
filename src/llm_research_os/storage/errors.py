"""Stable error types for the local SQLite fact store."""


class EventStoreError(RuntimeError):
    """Base class for event-store failures."""


class EventStoreSchemaError(EventStoreError):
    """Raised when a database does not match the supported schema."""


class EventAppendError(EventStoreError):
    """Raised when an event draft cannot be appended."""


class DuplicateEventError(EventAppendError):
    """Raised when an event ID has already been persisted."""


class EventSequenceConflictError(EventAppendError):
    """Raised when expected_last_sequence does not match the current global head."""

    def __init__(self, expected_last_sequence: int, actual_last_sequence: int) -> None:
        self._expected_last_sequence = expected_last_sequence
        self._actual_last_sequence = actual_last_sequence
        super().__init__(
            "event sequence conflict: "
            f"expected last sequence {expected_last_sequence}, "
            f"actual last sequence {actual_last_sequence}"
        )

    @property
    def expected_last_sequence(self) -> int:
        """Return the global head the caller required."""

        return self._expected_last_sequence

    @property
    def actual_last_sequence(self) -> int:
        """Return the global head observed inside the append transaction."""

        return self._actual_last_sequence


class EventIntegrityError(EventStoreError):
    """Raised when persisted facts fail an integrity check."""
