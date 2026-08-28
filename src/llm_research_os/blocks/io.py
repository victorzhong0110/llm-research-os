"""Safe loading and canonical serialization for BlockManifest documents."""

from __future__ import annotations

import json
from pathlib import Path

from llm_research_os.blocks.models import BlockManifest
from llm_research_os.spec.io import SpecLoadError, load_document

MAX_MANIFEST_BYTES = 1_048_576


class ManifestLoadError(SpecLoadError):
    """Raised when a manifest path violates the inert M0 loading boundary."""


def load_manifest(path: str | Path) -> BlockManifest:
    source = Path(path)
    if source.is_symlink():
        raise ManifestLoadError(f"manifest path must not be a symbolic link: {source}")
    try:
        document = load_document(
            source,
            max_bytes=MAX_MANIFEST_BYTES,
            reject_symlinks=True,
        )
    except SpecLoadError as exc:
        raise ManifestLoadError(str(exc)) from exc
    return BlockManifest.model_validate(document)


def canonical_manifest(manifest: BlockManifest) -> str:
    return (
        json.dumps(
            manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
