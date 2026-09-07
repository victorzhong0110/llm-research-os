"""RunControl adapter that leaves Attempt running for a Worker, then records the outcome."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from llm_research_os.events.models import RESEARCH_EVENT_SCHEMA_ID, validate_event_document
from llm_research_os.execution.authorization import PlanAuthorizationResult
from llm_research_os.execution.consume import consume_local_authorization
from llm_research_os.execution.errors import SimulationError
from llm_research_os.execution.models import DryRunReport
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.runs import RunControl, RunControlResult, RunSnapshot
from llm_research_os.runs.models import (
    TYPE_ATTEMPT_LOST,
    TYPE_ATTEMPT_QUEUED,
    TYPE_ATTEMPT_STARTED,
    TYPE_ATTEMPT_SUCCEEDED,
    TYPE_ATTEMPT_UNKNOWN,
    TYPE_RUN_COMPLETED,
    TYPE_RUN_QUEUED,
    TYPE_RUN_STARTED,
)
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore

START_PATH = (
    TYPE_RUN_QUEUED,
    TYPE_RUN_STARTED,
    TYPE_ATTEMPT_QUEUED,
    TYPE_ATTEMPT_STARTED,
)
SUCCESS_TAIL = (TYPE_ATTEMPT_SUCCEEDED, TYPE_RUN_COMPLETED)
UNKNOWN_TAIL = (TYPE_ATTEMPT_UNKNOWN,)
LOST_TAIL = (TYPE_ATTEMPT_LOST,)
_ATTEMPT_TYPES = frozenset(
    {
        TYPE_ATTEMPT_QUEUED,
        TYPE_ATTEMPT_STARTED,
        TYPE_ATTEMPT_SUCCEEDED,
        TYPE_ATTEMPT_UNKNOWN,
        TYPE_ATTEMPT_LOST,
    }
)


class WorkerRuntime:
    """Queue a Run, then record Worker success, unknown, or lost. Does not spawn itself."""

    def __init__(
        self,
        store: EventStore,
        *,
        project_id: str,
        run_id: str,
        attempt_id: str,
        source: str,
        subject: str,
        stream_id: str,
        actor_id: str,
        events: dict[str, tuple[str, str]],
    ) -> None:
        self._store = store
        self._project_id = project_id
        self._run_id = run_id
        self._attempt_id = attempt_id
        self._source = source
        self._subject = subject
        self._stream_id = stream_id
        self._actor_id = actor_id
        self._events = events
        self._control = RunControl(store, project_id=project_id, run_id=run_id)

    def start(
        self,
        *,
        report: DryRunReport,
        authorization: PlanAuthorizationResult,
        citation: dict[str, str],
        revision: int,
    ) -> RunSnapshot:
        consumed = consume_local_authorization(
            self._store,
            event_id=citation["eventId"],
            sequence=citation["sequence"],
            report=report,
            authorization=authorization,
            project_id=self._project_id,
        )
        snapshot: RunSnapshot | None = None
        for event_type in START_PATH:
            snapshot = self._append(
                event_type,
                report=report,
                authorization=authorization,
                consumed=consumed,
                revision=revision,
            ).snapshot
        if snapshot is None:
            raise SimulationError("worker runtime produced no snapshot")
        return snapshot

    def succeed(self, *, report: DryRunReport, revision: int) -> RunSnapshot:
        snapshot: RunSnapshot | None = None
        for event_type in SUCCESS_TAIL:
            snapshot = self._append(
                event_type,
                report=report,
                authorization=None,
                consumed=None,
                revision=revision,
            ).snapshot
        if snapshot is None:
            raise SimulationError("worker runtime produced no snapshot")
        return snapshot

    def unknown(self, *, reason_code: str, revision: int) -> RunSnapshot:
        return self._append(
            TYPE_ATTEMPT_UNKNOWN,
            report=None,
            authorization=None,
            consumed=None,
            revision=revision,
            reason_code=reason_code,
        ).snapshot

    def lost(self, *, reason_code: str, revision: int) -> RunSnapshot:
        return self._append(
            TYPE_ATTEMPT_LOST,
            report=None,
            authorization=None,
            consumed=None,
            revision=revision,
            reason_code=reason_code,
        ).snapshot

    def _append(
        self,
        event_type: str,
        *,
        report: DryRunReport | None,
        authorization: PlanAuthorizationResult | None,
        consumed: StoredEvent | None,
        revision: int,
        reason_code: str | None = None,
    ) -> RunControlResult:
        identity = self._events.get(event_type)
        if identity is None:
            raise SimulationError("worker runtime event identities are incomplete")
        event_id, event_time = identity
        payload: dict[str, Any] = {}
        if event_type == TYPE_RUN_QUEUED:
            if report is None or authorization is None or consumed is None:
                raise SimulationError("run.queued requires a consumed authorization")
            payload = {
                "workflowId": report.workflow_id,
                "specDigest": report.digests.spec,
                "registryDigest": report.digests.registry,
                "planDigest": report.digests.plan,
                "decisionDigest": authorization.decision_digest,
                "authorizationEventId": consumed.event.id,
                "authorizationSequence": consumed.event.sequence,
                "maxAttempts": 1,
            }
        elif event_type == TYPE_ATTEMPT_QUEUED:
            payload = {"ordinal": 1, "retryOf": None, "retryDecisionId": None}
        elif event_type in {TYPE_ATTEMPT_UNKNOWN, TYPE_ATTEMPT_LOST}:
            if reason_code is None:
                raise SimulationError("unknown/lost attempts require a reasonCode")
            payload = {"reasonCode": reason_code}
        data: dict[str, Any] = {
            "schemaVersion": "v0alpha1",
            "actor": {"id": self._actor_id},
            "projectId": self._project_id,
            "experimentRevision": revision,
            "payload": payload,
            "evidenceRefs": [],
            "runId": self._run_id,
        }
        if event_type in _ATTEMPT_TYPES:
            data["attemptId"] = self._attempt_id
        draft = {
            "specversion": "1.0",
            "id": event_id,
            "source": self._source,
            "type": event_type,
            "time": event_time,
            "subject": self._subject,
            "dataschema": RESEARCH_EVENT_SCHEMA_ID,
            "datacontenttype": "application/json",
            "streamid": self._stream_id,
            "data": data,
        }
        try:
            snapshot_json_document(draft)
            probe: dict[str, Any] = dict(draft)
            probe.update({"sequence": "1", "sequencetype": "Integer", "streamversion": 0})
            validate_event_document(probe)
        except ValidationError:
            raise SimulationError("event draft failed ResearchEvent validation") from None
        return self._control.append(draft)
