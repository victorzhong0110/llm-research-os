"""Semantic, ID-aware differences between immutable ResearchSpec revisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from llm_research_os.spec.models import ResearchSpec


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class ChangeImpact(StrEnum):
    METADATA = "metadata"
    RESEARCH = "research"
    EXECUTION = "execution"
    GOVERNANCE = "governance"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class SemanticChange:
    path: str
    kind: ChangeKind
    impact: ChangeImpact
    before: Any = None
    after: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind.value,
            "impact": self.impact.value,
            "before": self.before,
            "after": self.after,
        }


def semantic_diff(old: ResearchSpec, new: ResearchSpec) -> list[SemanticChange]:
    if old.metadata.id != new.metadata.id:
        raise ValueError("cannot diff specs with different project ids")
    if new.metadata.revision <= old.metadata.revision:
        raise ValueError("new revision must be greater than old revision")

    before = old.model_dump(mode="json", by_alias=True, exclude_none=False)
    after = new.model_dump(mode="json", by_alias=True, exclude_none=False)
    changes: list[SemanticChange] = []
    _diff_values(before, after, "", changes)
    return changes


def _diff_values(old: Any, new: Any, path: str, changes: list[SemanticChange]) -> None:
    if type(old) is not type(new):
        changes.append(_change(path, ChangeKind.CHANGED, old, new))
        return

    if isinstance(old, dict):
        for key in sorted(set(old).union(new)):
            child_path = f"{path}/{_escape(str(key))}"
            if key not in old:
                changes.append(_change(child_path, ChangeKind.ADDED, None, new[key]))
            elif key not in new:
                changes.append(_change(child_path, ChangeKind.REMOVED, old[key], None))
            else:
                _diff_values(old[key], new[key], child_path, changes)
        return

    if isinstance(old, list):
        if _is_id_list(old) and _is_id_list(new):
            old_by_id = {item["id"]: item for item in old}
            new_by_id = {item["id"]: item for item in new}
            for item_id in sorted(set(old_by_id).union(new_by_id)):
                item_path = f"{path}[id={_escape(str(item_id))}]"
                if item_id not in old_by_id:
                    changes.append(_change(item_path, ChangeKind.ADDED, None, new_by_id[item_id]))
                elif item_id not in new_by_id:
                    changes.append(_change(item_path, ChangeKind.REMOVED, old_by_id[item_id], None))
                else:
                    _diff_values(old_by_id[item_id], new_by_id[item_id], item_path, changes)
        elif old != new:
            changes.append(_change(path, ChangeKind.CHANGED, old, new))
        return

    if old != new:
        changes.append(_change(path, ChangeKind.CHANGED, old, new))


def _is_id_list(value: list[Any]) -> bool:
    ids: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return False
        ids.append(item["id"])
    return len(ids) == len(set(ids))


def _change(path: str, kind: ChangeKind, before: Any, after: Any) -> SemanticChange:
    return SemanticChange(
        path=path or "/",
        kind=kind,
        impact=_impact_for(path),
        before=before,
        after=after,
    )


def _impact_for(path: str) -> ChangeImpact:
    root = path.lstrip("/").split("/", maxsplit=1)[0].split("[", maxsplit=1)[0]
    if root == "metadata":
        return ChangeImpact.METADATA
    if root in {"questions", "hypotheses", "evidence"}:
        return ChangeImpact.RESEARCH
    if root in {"datasets", "models", "workflows", "evaluations", "resources"}:
        return ChangeImpact.EXECUTION
    if root == "policies":
        return ChangeImpact.GOVERNANCE
    return ChangeImpact.EXTENSION


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
