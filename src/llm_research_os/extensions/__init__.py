"""Minimal extension mechanism and permission boundary (R14).

A versioned manifest contract with a closed permission set, a compatibility
check, a bounded subprocess host for one reviewed adapter, and explicit
enable/disable/uninstall. Loading a manifest is inert: nothing is imported,
evaluated or fetched, and a declared permission is a request rather than a
grant.
"""

from llm_research_os.extensions.manifest import (
    KNOWN_PERMISSIONS,
    NEVER_GRANTED,
    AdapterResult,
    ExtensionError,
    ExtensionManifest,
    load_manifest,
    parse_manifest,
    run_adapter,
)
from llm_research_os.extensions.registry import (
    ExtensionRegistry,
    InstalledExtension,
    RegistryError,
)

__all__ = [
    "KNOWN_PERMISSIONS",
    "NEVER_GRANTED",
    "AdapterResult",
    "ExtensionError",
    "ExtensionManifest",
    "ExtensionRegistry",
    "InstalledExtension",
    "RegistryError",
    "load_manifest",
    "parse_manifest",
    "run_adapter",
]
