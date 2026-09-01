"""Trusted planning, authorization, and deterministic SimulatedRuntime."""

from llm_research_os.execution.authorization import (
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    PlanAuthorizationStatus,
    RequirementDecision,
    RequirementDecisionValue,
    authorize_plan,
)
from llm_research_os.execution.authorization_documents import (
    PLAN_AUTHORIZATION_API_VERSION,
    PLAN_AUTHORIZATION_REPORT_SCHEMA_ID,
    PLAN_AUTHORIZATION_REQUEST_SCHEMA_ID,
    PlanAuthorizationBinding,
    PlanAuthorizationReport,
    PlanAuthorizationRequestDocument,
    PlanAuthorizationSideEffects,
    RequirementDecisionDocument,
    load_plan_authorization_request,
    validate_plan_authorization_request_document,
)
from llm_research_os.execution.errors import PlanAuthorizationError, SimulationError
from llm_research_os.execution.kernel import TrustedKernel
from llm_research_os.execution.models import DryRunReport
from llm_research_os.execution.planner import PlannerLimits, PlanningInputError
from llm_research_os.execution.request import (
    SimulationEventIdentityDocument,
    SimulationRequestDocument,
    load_simulation_request,
    validate_simulation_request_document,
)
from llm_research_os.execution.simulated import (
    SimulatedRuntime,
    SimulationDisposition,
    SimulationEventIdentity,
    SimulationRequest,
    SimulationResult,
)

__all__ = [
    "PLAN_AUTHORIZATION_API_VERSION",
    "PLAN_AUTHORIZATION_REPORT_SCHEMA_ID",
    "PLAN_AUTHORIZATION_REQUEST_SCHEMA_ID",
    "DryRunReport",
    "PlanAuthorizationBinding",
    "PlanAuthorizationError",
    "PlanAuthorizationPolicy",
    "PlanAuthorizationReport",
    "PlanAuthorizationRequestDocument",
    "PlanAuthorizationResult",
    "PlanAuthorizationSideEffects",
    "PlanAuthorizationStatus",
    "PlannerLimits",
    "PlanningInputError",
    "RequirementDecision",
    "RequirementDecisionDocument",
    "RequirementDecisionValue",
    "SimulatedRuntime",
    "SimulationDisposition",
    "SimulationError",
    "SimulationEventIdentity",
    "SimulationEventIdentityDocument",
    "SimulationRequest",
    "SimulationRequestDocument",
    "SimulationResult",
    "TrustedKernel",
    "authorize_plan",
    "load_plan_authorization_request",
    "load_simulation_request",
    "validate_plan_authorization_request_document",
    "validate_simulation_request_document",
]
