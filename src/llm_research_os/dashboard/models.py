"""Closed contracts for semantic maps and cooperative Agent composition."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")]


class Model(BaseModel):
    model_config = ConfigDict(
        frozen=True, populate_by_name=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class Position(Model):
    x: float = Field(ge=0, le=100000)
    y: float = Field(ge=0, le=100000)
    width: float = Field(default=280, ge=180, le=20000)
    height: float = Field(default=190, ge=120, le=20000)


class Binding(Model):
    source: Literal["workspace", "runs", "research", "events", "telemetry"]
    entity_id: Identifier | None = Field(default=None, alias="entityId")
    source_id: Identifier | None = Field(default=None, alias="sourceId")


class Component(Model):
    id: Identifier
    type: Literal[
        "group",
        "project",
        "run",
        "agent",
        "research",
        "evaluation",
        "resource",
        "provider",
        "dataset",
        "model",
        "service",
        "pool",
        "availability",
        "cost",
        "access",
        "recovery",
        "note",
        "custom",
    ]
    title: str = Field(min_length=1, max_length=160)
    parent_id: Identifier | None = Field(default=None, alias="parentId")
    position: Position
    pinned: bool = False
    collapsed: bool = False
    binding: Binding | None = None
    body: str = Field(default="", max_length=4000)
    renderer: Literal["summary", "metric", "table", "chart", "timeline"] = "summary"


class Relation(Model):
    id: Identifier
    source: Identifier
    target: Identifier
    type: Literal["dependency", "evidence", "shared", "peer", "association"]
    label: str = Field(min_length=1, max_length=100)
    scope: Literal["view"] = "view"


class Appearance(Model):
    skin: Literal["graphite", "paper", "custom"] = "graphite"
    background: str = Field(default="#f5f5f4", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#262626", pattern=r"^#[0-9a-fA-F]{6}$")
    density: Literal["comfortable", "compact"] = "comfortable"
    text_scale: float = Field(default=1, alias="textScale", ge=0.9, le=1.4)


class Viewport(Model):
    x: float = Field(default=0, ge=-200000, le=200000)
    y: float = Field(default=0, ge=-200000, le=200000)
    zoom: float = Field(default=0.75, ge=0.1, le=2)


class MapState(Model):
    components: tuple[Component, ...] = Field(default=(), max_length=2000)
    relations: tuple[Relation, ...] = Field(default=(), max_length=6000)
    appearance: Appearance = Field(default_factory=Appearance)
    viewport: Viewport = Field(default_factory=Viewport)

    @model_validator(mode="after")
    def coherent_map(self) -> Self:
        nodes = {node.id: node for node in self.components}
        if len(nodes) != len(self.components):
            raise ValueError("duplicate component identity")
        for node in self.components:
            if node.parent_id is not None:
                parent = nodes.get(node.parent_id)
                if parent is None or parent.type != "group":
                    raise ValueError("parent must be an existing group")
                p, c = parent.position, node.position
                if c.y < 48 or c.x + c.width > p.width or c.y + c.height > p.height:
                    raise ValueError("child must fit inside its group")
            visited = {node.id}
            parent_id = node.parent_id
            while parent_id is not None:
                if parent_id in visited or len(visited) > 8:
                    raise ValueError("cyclic or excessive containment")
                visited.add(parent_id)
                parent = nodes.get(parent_id)
                if parent is None:
                    raise ValueError("missing parent")
                parent_id = parent.parent_id
        if len({edge.id for edge in self.relations}) != len(self.relations):
            raise ValueError("duplicate relation identity")
        for edge in self.relations:
            if edge.source not in nodes or edge.target not in nodes or edge.source == edge.target:
                raise ValueError("invalid relation endpoints")
        return self


class DashboardDocument(Model):
    api_version: Literal["researchos.dev/dashboard/v0alpha1"] = Field(
        default="researchos.dev/dashboard/v0alpha1", alias="apiVersion"
    )
    kind: Literal["DashboardDocument"] = "DashboardDocument"
    project_id: Identifier = Field(alias="projectId")
    revision: int = Field(default=0, ge=0)
    state: MapState = Field(default_factory=MapState)
    author: str = Field(default="system", min_length=1, max_length=120)
    author_kind: Literal["human", "agent", "system"] = Field(default="system", alias="authorKind")
    updated_at: str | None = Field(default=None, alias="updatedAt")


class DashboardWrite(Model):
    api_version: Literal["researchos.dev/dashboard/v0alpha1"] = Field(
        default="researchos.dev/dashboard/v0alpha1", alias="apiVersion"
    )
    kind: Literal["DashboardWrite"] = "DashboardWrite"
    project_id: Identifier = Field(alias="projectId")
    request_id: Identifier = Field(alias="requestId")
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    author: str = Field(min_length=1, max_length=120)
    author_kind: Literal["human", "agent"] = Field(alias="authorKind")
    state: MapState


def check_agent_edit(before: MapState, after: MapState) -> None:
    """TM-100: protect human pins, including movement through an ancestor."""
    previous = {node.id: node for node in before.components}
    proposed = {node.id: node for node in after.components}
    for node in before.components:
        if not node.pinned:
            continue
        replacement = proposed.get(node.id)
        if replacement is None or (
            replacement.position,
            replacement.parent_id,
            replacement.pinned,
            replacement.type,
            replacement.binding,
        ) != (node.position, node.parent_id, node.pinned, node.type, node.binding):
            raise ValueError("Agent edit conflicts with a human pin")
        parent_id = node.parent_id
        while parent_id is not None:
            old = previous[parent_id]
            new = proposed.get(parent_id)
            if new is None or (new.position.x, new.position.y, new.parent_id) != (
                old.position.x,
                old.position.y,
                old.parent_id,
            ):
                raise ValueError("Agent edit moves a pinned descendant")
            parent_id = old.parent_id
