"""``ResearchEvent v0alpha1`` — a CloudEvents 1.0 compatible envelope forming the
append-only fact stream shared by the runtime, AI, and humans.

The charter (decision ``4-EC``) fixes a CloudEvents-compatible shell that is not
yet bound to any transport. Standard CloudEvents context attributes
(``specversion``, ``id``, ``source``, ``type``, ``time``, ``subject``,
``datacontenttype``) live alongside research-specific correlation fields; the
research payload rides in ``data``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_os import SCHEMA_VERSION

CLOUDEVENTS_SPECVERSION = "1.0"

# Event type prefix, reverse-DNS per CloudEvents guidance.
EVENT_TYPE_PREFIX = "dev.researchos"


def _now_rfc3339() -> str:
    return datetime.now(tz=UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class ResearchEvent(BaseModel):
    """A single immutable fact about a research project or run."""

    model_config = ConfigDict(extra="forbid")

    specversion: str = Field(default=CLOUDEVENTS_SPECVERSION)
    schemaVersion: str = Field(default=SCHEMA_VERSION)
    id: str = Field(default_factory=_new_id)
    source: str = Field(description="Logical producer, e.g. 'runtime/simulated'.")
    type: str = Field(description="Reverse-DNS event type, e.g. 'dev.researchos.run.started'.")
    time: str = Field(default_factory=_now_rfc3339)
    datacontenttype: str = Field(default="application/json")

    projectId: str
    experimentRevision: int | None = None
    runId: str | None = None
    blockId: str | None = None
    correlationId: str | None = None
    causationId: str | None = None

    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def subject(self) -> str:
        """CloudEvents ``subject``: project scoped to run when present."""
        return f"{self.projectId}/{self.runId}" if self.runId else self.projectId

    def to_cloudevent(self) -> dict[str, Any]:
        """Render as a CloudEvents 1.0 structured-mode JSON object."""
        event: dict[str, Any] = {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time,
            "subject": self.subject,
            "datacontenttype": self.datacontenttype,
            # Research-specific extension attributes.
            "schemaversion": self.schemaVersion,
            "projectid": self.projectId,
            "data": self.data,
        }
        for key, value in (
            ("experimentrevision", self.experimentRevision),
            ("runid", self.runId),
            ("blockid", self.blockId),
            ("correlationid", self.correlationId),
            ("causationid", self.causationId),
        ):
            if value is not None:
                event[key] = value
        return event
