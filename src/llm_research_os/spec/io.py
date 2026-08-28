"""Safe loading and canonical serialization for ResearchSpec documents."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import yaml
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode

from llm_research_os.spec.models import ResearchSpec

MAX_DOCUMENT_BYTES = 8_388_608
MAX_DECODED_DEPTH = 128
MAX_DECODED_NODES = 100_000


class SpecLoadError(ValueError):
    """Raised when a document cannot be decoded into a mapping."""


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects aliases before they can amplify data."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise ComposerError(
                "while composing a document",
                None,
                "YAML aliases are not supported in M0",
                None,
            )
        return super().compose_node(parent, index)


def _construct_unique_mapping(
    loader: _StrictSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate mapping key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("found a duplicate JSON object key")
        value[key] = item
    return value


def _load_yaml(text: str) -> Any:
    loader = _StrictSafeLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def _validate_decoded_limits(value: object) -> None:
    seen = 0
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        seen += 1
        if seen > MAX_DECODED_NODES:
            raise SpecLoadError(f"decoded document exceeds the {MAX_DECODED_NODES}-node M0 limit")
        if depth > MAX_DECODED_DEPTH:
            raise SpecLoadError(f"decoded document exceeds the {MAX_DECODED_DEPTH}-level M0 limit")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _read_regular_text(
    source: Path,
    *,
    max_bytes: int,
    reject_symlinks: bool,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if reject_symlinks and no_follow:
        flags |= no_follow
    elif reject_symlinks and source.is_symlink():
        raise SpecLoadError(f"document path must not be a symbolic link: {source}")

    descriptor = os.open(source, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SpecLoadError(f"document path is not a regular file: {source}")
        if metadata.st_size > max_bytes:
            raise SpecLoadError(f"document exceeds the {max_bytes}-byte M0 limit: {source}")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise SpecLoadError(f"document exceeds the {max_bytes}-byte M0 limit: {source}")
        return b"".join(chunks).decode("utf-8")
    finally:
        os.close(descriptor)


def load_document(
    path: str | Path,
    *,
    max_bytes: int = MAX_DOCUMENT_BYTES,
    reject_symlinks: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    try:
        text = _read_regular_text(
            source,
            max_bytes=max_bytes,
            reject_symlinks=reject_symlinks,
        )
        data = (
            json.loads(text, object_pairs_hook=_unique_json_object)
            if source.suffix.lower() == ".json"
            else _load_yaml(text)
        )
        _validate_decoded_limits(data)
    except SpecLoadError:
        raise
    except (
        OSError,
        RecursionError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        raise SpecLoadError(f"could not load {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecLoadError(f"{source} must contain one object at the document root")
    return data


def load_spec(path: str | Path) -> ResearchSpec:
    return ResearchSpec.model_validate(load_document(path))


def canonical_document(spec: ResearchSpec) -> str:
    return (
        json.dumps(
            spec.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
