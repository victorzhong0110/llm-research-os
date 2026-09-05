"""Research decision objects: proposal, dissent, decision, and the ledger fold."""

from llm_research_os.research.control import (
    ResearchControl,
    ResearchControlHead,
    ResearchControlResult,
)
from llm_research_os.research.errors import (
    ResearchControlError,
    ResearchDecisionError,
    ResearchLedgerError,
    ResearchPayloadError,
    ResearchRequestError,
)
from llm_research_os.research.ledger import ResearchLedgerProjection, build_research_ledger
from llm_research_os.research.models import (
    DecisionOutcome,
    ResearchLedger,
    empty_research_ledger,
    parse_decision_payload,
    research_ledger_document,
)
from llm_research_os.research.requests import (
    DecisionRecordRequestDocument,
    DissentRecordRequestDocument,
    ProposalSubmitRequestDocument,
    load_decision_record_request,
    load_dissent_record_request,
    load_proposal_submit_request,
)

__all__ = [
    "DecisionOutcome",
    "DecisionRecordRequestDocument",
    "DissentRecordRequestDocument",
    "ProposalSubmitRequestDocument",
    "ResearchControl",
    "ResearchControlError",
    "ResearchControlHead",
    "ResearchControlResult",
    "ResearchDecisionError",
    "ResearchLedger",
    "ResearchLedgerError",
    "ResearchLedgerProjection",
    "ResearchPayloadError",
    "ResearchRequestError",
    "build_research_ledger",
    "empty_research_ledger",
    "load_decision_record_request",
    "load_dissent_record_request",
    "load_proposal_submit_request",
    "parse_decision_payload",
    "research_ledger_document",
]
