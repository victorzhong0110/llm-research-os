"""Stable error types for the local content-addressed artifact store."""


class ArtifactStoreError(RuntimeError):
    """Base class for artifact-store failures."""


class ArtifactPathError(ArtifactStoreError):
    """Raised when a root, source, or digest cannot be used as a store path."""


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when a digest does not resolve to a stored object."""


class ArtifactIntegrityError(ArtifactStoreError):
    """Raised when a stored object fails an integrity check."""
