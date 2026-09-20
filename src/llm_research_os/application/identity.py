"""Operation identity helpers for R02 idempotency.

An operation identity lets a CLI or Python caller replay a command under the
same identifier and observe the prior result. The identity is opaque to the
kernel: operations are still validated and CAS-checked against the current
EventStore head. Identities are recorded in the receipt log so that
re-submitting the same content returns the existing receipt, while
re-submitting a new identity (or stale expected head) fails visibly.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from llm_research_os.application.errors import (
    InvalidCommandIdError,
)

_COMMAND_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


__all__ = ["InvalidCommandIdError"]


def normalize_command_id(value: str | None) -> str:
    """Return a canonical command identifier.

    ``None`` or empty input yields a UUID4-derived identifier. Provided
    identifiers are validated against the documented pattern and rejected
    if they would collide with reserved prefixes used by atomic receipt
    replay.
    """

    if value is None or value.strip() == "":
        return f"cmd-{uuid.uuid4().hex}"
    candidate = value.strip()
    if not _COMMAND_ID_PATTERN.fullmatch(candidate):
        raise InvalidCommandIdError(
            f"command_id must match [A-Za-z0-9][A-Za-z0-9._:-]{{0,127}}; got {value!r}"
        )
    if candidate.startswith("__") or candidate.startswith("replay-"):
        raise InvalidCommandIdError(f"command_id prefix reserved for internal use: {candidate!r}")
    return candidate


@dataclass(frozen=True, slots=True)
class OperationIdentity:
    """Identity binding a single command submission.

    ``command_id`` is the caller-visible identifier; ``submission_id`` is the
    internal monotonic counter paired with ``command_id`` so accidental
    re-submission by the same caller under a different revision is still
    detected by the receipt log replay guard.
    """

    command_id: str
    submission_id: int = 1

    def next_submission(self) -> OperationIdentity:
        return OperationIdentity(self.command_id, self.submission_id + 1)


def bind_operation_identity(command_id: str | None, *, submission_id: int = 1) -> OperationIdentity:
    """Build an :class:`OperationIdentity` from a caller-supplied id.

    ``command_id`` may be ``None`` or an empty string, in which case a fresh
    UUID-based id is generated. ``submission_id`` is preserved across
    replays so an algorithm may distinguish an idempotent re-submission
    (same ``command_id`` and ``submission_id``) from an accidental retry
    that should be rejected.
    """

    if submission_id < 1:
        raise InvalidCommandIdError("submission_id must be >= 1")
    return OperationIdentity(normalize_command_id(command_id), submission_id)


__all__ = [
    "InvalidCommandIdError",
    "OperationIdentity",
    "bind_operation_identity",
    "normalize_command_id",
]
