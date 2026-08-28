"""LLM Research OS reference implementation."""

from llm_research_os.blocks.models import BlockManifest
from llm_research_os.events.models import ResearchEvent, validate_event_document
from llm_research_os.execution.kernel import TrustedKernel
from llm_research_os.problem import ProblemReport
from llm_research_os.spec.models import ResearchSpec

__all__ = [
    "BlockManifest",
    "ProblemReport",
    "ResearchEvent",
    "ResearchSpec",
    "TrustedKernel",
    "validate_event_document",
]
__version__ = "0.0.0"
