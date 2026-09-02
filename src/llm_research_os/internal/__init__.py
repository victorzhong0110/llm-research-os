"""Internal shared primitives that are not external protocol contracts."""

from llm_research_os.internal.jsonclone import JsonCloneError, snapshot_json_document

__all__ = ["JsonCloneError", "snapshot_json_document"]
