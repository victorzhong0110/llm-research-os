"""Installation, startup, backup, and recovery entry points for R15."""

from llm_research_os.recovery.backup import (
    create_backup,
    load_manifest,
    restore_backup,
    verify_backup,
)
from llm_research_os.recovery.doctor import diagnose, plan_migration, preflight_port
from llm_research_os.recovery.errors import BackupIntegrityError, RecoveryError
from llm_research_os.recovery.models import (
    BackupManifest,
    BackupReport,
    DiagnosticReport,
    ReconciledRun,
    RestoreReport,
)

__all__ = [
    "BackupIntegrityError",
    "BackupManifest",
    "BackupReport",
    "DiagnosticReport",
    "ReconciledRun",
    "RecoveryError",
    "RestoreReport",
    "create_backup",
    "diagnose",
    "load_manifest",
    "plan_migration",
    "preflight_port",
    "restore_backup",
    "verify_backup",
]
