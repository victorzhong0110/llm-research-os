"""Rebuildable in-memory projections over verified ResearchEvent streams."""

from llm_research_os.projections.fold import Projection, fold_events
from llm_research_os.projections.replay import replay_events

__all__ = ["Projection", "fold_events", "replay_events"]
