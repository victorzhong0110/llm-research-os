"""BlockManifest protocol and inert M0 registry."""

from llm_research_os.blocks.io import load_manifest
from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.blocks.reports import (
    BlockManifestValidationReport,
    BlockRegistryReport,
)

__all__ = [
    "BlockManifest",
    "BlockManifestValidationReport",
    "BlockRegistry",
    "BlockRegistryReport",
    "build_registry",
    "load_manifest",
]
