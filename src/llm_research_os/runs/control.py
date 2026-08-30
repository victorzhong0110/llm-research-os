"""Atomic RunControl boundary over EventStore and RunStateProjection.

EventStore remains the only fact source. RunSnapshot is a rebuildable in-memory
projection. This module does not generate caller-owned event fields, retry CAS
conflicts, persist snapshots, or execute blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from pydantic import ValidationError

from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    ResearchEvent,
    validate_event_document,
)
from llm_research_os.projections import replay_events
from llm_research_os.runs.errors import RunControlError
from llm_research_os.runs.models import LIFECYCLE_TYPES, RunSnapshot
from llm_research_os.runs.reducer import RunStateProjection
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import MAX_READ_PAGE_SIZE, EventStore

_STORE_ASSIGNED_FIELDS = frozenset({"sequence", "sequencetype", "streamversion"})


@dataclass(frozen=True, slots=True)
class RunControlHead:
    """Frozen global event head plus the rebuilt snapshot for one Run."""

    last_sequence: int
    snapshot: RunSnapshot | None


@dataclass(frozen=True, slots=True)
class RunControlResult:
    """One CAS-committed event and the snapshot produced from that fact."""

    stored: StoredEvent
    snapshot: RunSnapshot


class RunControl:
    """Validate a lifecycle draft against a frozen replay, then CAS-append it.

    ``last_sequence`` is the global EventStore head used as the CAS token. It is
    not a per-Run event count and is not ``streamversion``. Conflicts are not
    retried; the caller must invoke ``append`` again so replay and preflight run
    against the new head.
    """

    def __init__(
        self,
        store: EventStore,
        *,
        project_id: str,
        run_id: str,
        page_size: int = 100,
    ) -> None:
        self._store = store
        self._page_size = _require_page_size(page_size)
        self._projection = RunStateProjection(project_id=project_id, run_id=run_id)
        self._project_id = self._projection.project_id
        self._run_id = self._projection.run_id

    def rebuild(self) -> RunControlHead:
        """Replay the frozen global log and fold only this Run's events."""

        snapshot: RunSnapshot | None = None
        last_sequence = 0
        for stored in replay_events(
            self._store,
            freeze_high_water=True,
            page_size=self._page_size,
        ):
            last_sequence = stored.sequence
            snapshot = self._projection.apply(snapshot, stored.event)
        return RunControlHead(last_sequence=last_sequence, snapshot=snapshot)

    def append(self, document: dict[str, Any]) -> RunControlResult:
        """Preflight one lifecycle draft, then append it at the frozen head."""

        head = self.rebuild()
        frozen_head = head.last_sequence
        snapshot = head.snapshot
        draft = _snapshot_json_document(document)
        supplied = sorted(_STORE_ASSIGNED_FIELDS.intersection(draft))
        if supplied:
            raise RunControlError(
                f"RunControl does not accept store-assigned fields; caller supplied: {supplied}"
            )
        if frozen_head >= CLOUD_EVENTS_INTEGER_MAX:
            raise RunControlError("global event sequence is exhausted")
        preflight_document = dict(draft)
        preflight_document.update(
            {
                "sequence": str(frozen_head + 1),
                "sequencetype": "Integer",
                "streamversion": 0,
            }
        )
        preflight_event = _validate_preflight_event(preflight_document)
        _require_matching_aggregate(preflight_event, self._project_id, self._run_id)
        if preflight_event.type not in LIFECYCLE_TYPES:
            raise RunControlError("event type is not a Run/Attempt lifecycle type")
        preflight_snapshot = self._projection.apply(snapshot, preflight_event)
        if preflight_snapshot is None:
            raise RunControlError("lifecycle preflight produced no snapshot")
        stored = self._store.append(draft, expected_last_sequence=frozen_head)
        committed_snapshot = self._projection.apply(snapshot, stored.event)
        if committed_snapshot is None:
            raise RunControlError("committed lifecycle event produced no snapshot")
        return RunControlResult(stored=stored, snapshot=committed_snapshot)


def _require_page_size(page_size: int) -> int:
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_READ_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be an integer in 1..{MAX_READ_PAGE_SIZE}")
    return page_size


def _is_json_atom(value: object) -> bool:
    return (
        value is None
        or type(value) is bool
        or type(value) is int
        or type(value) is float
        or type(value) is str
    )


def _snapshot_json_document(document: object) -> dict[str, Any]:
    """Return a new JSON tree that does not alias the caller's containers."""

    if type(document) is not dict:
        raise RunControlError("event draft must be a JSON object")
    cloned = _snapshot_json_value(document)
    if type(cloned) is not dict:
        raise RunControlError("event draft must be a JSON object")
    return cloned


def _snapshot_json_value(root: object) -> object:
    if _is_json_atom(root):
        return root
    if type(root) is not dict and type(root) is not list:
        raise RunControlError("event draft must contain only JSON values")

    clones: dict[int, dict[str, Any] | list[Any]] = {}
    ancestors: set[int] = set()
    container = cast(dict[str, Any] | list[Any], root)
    root_clone = _new_json_clone(container, clones)
    stack: list[tuple[object, dict[str, Any] | list[Any], list[tuple[str | int, object]], int]] = [
        (container, root_clone, _json_children(container), 0)
    ]
    ancestors.add(id(root))
    while stack:
        node, clone, children, index = stack[-1]
        if index >= len(children):
            ancestors.discard(id(node))
            stack.pop()
            continue
        key, child = children[index]
        stack[-1] = (node, clone, children, index + 1)
        if _is_json_atom(child):
            _assign_json_clone(clone, key, child)
            continue
        if type(child) is not dict and type(child) is not list:
            raise RunControlError("event draft must contain only JSON values")
        child_id = id(child)
        if child_id in ancestors:
            raise RunControlError("event draft must not contain cyclic JSON structures")
        existing = clones.get(child_id)
        if existing is not None:
            _assign_json_clone(clone, key, existing)
            continue
        child_container = cast(dict[str, Any] | list[Any], child)
        child_clone = _new_json_clone(child_container, clones)
        _assign_json_clone(clone, key, child_clone)
        ancestors.add(child_id)
        stack.append((child_container, child_clone, _json_children(child_container), 0))
    return root_clone


def _new_json_clone(
    node: dict[str, Any] | list[Any],
    clones: dict[int, dict[str, Any] | list[Any]],
) -> dict[str, Any] | list[Any]:
    clone: dict[str, Any] | list[Any] = {} if type(node) is dict else [None] * len(node)
    clones[id(node)] = clone
    return clone


def _json_children(node: dict[str, Any] | list[Any]) -> list[tuple[str | int, object]]:
    children: list[tuple[str | int, object]] = []
    if type(node) is dict:
        for key, child in node.items():
            if type(key) is not str:
                raise RunControlError("event draft keys must be JSON strings")
            children.append((key, child))
        return children
    items = cast(list[Any], node)
    for index in range(len(items)):
        children.append((index, items[index]))
    return children


def _assign_json_clone(
    clone: dict[str, Any] | list[Any],
    key: str | int,
    value: object,
) -> None:
    if type(clone) is dict:
        clone[cast(str, key)] = value
        return
    cast(list[Any], clone)[cast(int, key)] = value


def _require_matching_aggregate(event: ResearchEvent, project_id: str, run_id: str) -> None:
    if event.data.project_id != project_id or event.data.run_id != run_id:
        raise RunControlError("event projectId/runId does not match this RunControl")


def _validate_preflight_event(document: dict[str, Any]) -> ResearchEvent:
    try:
        validated = validate_event_document(document)
    except ValidationError:
        payload_error = RunControlError("event draft failed ResearchEvent validation")
    else:
        return validated
    raise payload_error
