"""Stable fail-closed errors for trusted execution boundaries."""


class PlanAuthorizationError(ValueError):
    """Reject an invalid or internally inconsistent authorization evaluation.

    Messages MUST NOT include caller-supplied capability, permission, requirement,
    configuration, prompt, or other potentially sensitive values.
    """


class SimulationError(ValueError):
    """Fail-closed error from the deterministic simulated vertical slice.

    Messages MUST NOT include task config, payload bodies, unknown field names,
    secrets, control characters, or other potentially sensitive document text.
    """
