"""Deep-copy JSON document trees without aliasing caller containers.

The clone rejects cyclic graphs and non-JSON host types so downstream
preflight logic can mutate an isolated draft safely.
"""

from __future__ import annotations

from typing import Any, cast


class JsonCloneError(ValueError):
    """Reject a document tree that cannot be cloned as plain JSON."""


def snapshot_json_document(document: object) -> dict[str, Any]:
    """Return a new JSON tree that does not alias the caller's containers."""

    if type(document) is not dict:
        raise JsonCloneError("event draft must be a JSON object")
    cloned = _snapshot_json_value(document)
    if type(cloned) is not dict:
        raise JsonCloneError("event draft must be a JSON object")
    return cloned


def _is_json_atom(value: object) -> bool:
    return (
        value is None
        or type(value) is bool
        or type(value) is int
        or type(value) is float
        or type(value) is str
    )


def _snapshot_json_value(root: object) -> object:
    if _is_json_atom(root):
        return root
    if type(root) is not dict and type(root) is not list:
        raise JsonCloneError("event draft must contain only JSON values")

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
            raise JsonCloneError("event draft must contain only JSON values")
        child_id = id(child)
        if child_id in ancestors:
            raise JsonCloneError("event draft must not contain cyclic JSON structures")
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
                raise JsonCloneError("event draft keys must be JSON strings")
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
