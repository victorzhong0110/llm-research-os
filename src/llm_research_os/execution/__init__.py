"""Trusted planning, authorization, and deterministic SimulatedRuntime."""

from llm_research_os.execution.authorization import (
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    PlanAuthorizationStatus,
    RequirementDecision,
    RequirementDecisionValue,
    authorize_plan,
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
    "DryRunReport",
    "PlanAuthorizationError",
    "PlanAuthorizationPolicy",
    "PlanAuthorizationResult",
    "PlanAuthorizationStatus",
    "PlannerLimits",
    "PlanningInputError",
    "RequirementDecision",
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
    "load_simulation_request",
    "validate_simulation_request_document",
]
