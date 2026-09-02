"""Stable fail-closed errors for trusted execution boundaries."""


class PlanAuthorizationError(ValueError):
    """Reject an invalid or internally inconsistent authorization evaluation.

    Messages MUST NOT include caller-supplied capability, permission, requirement,
    configuration, prompt, or other potentially sensitive values.
    """


class PlanAuthorizationRecordError(ValueError):
    """Reject an invalid authorization-evaluation fact before persistence.

    Messages MUST NOT include caller-supplied grants, requirements, prompts,
    configuration, evidence identifiers, or other potentially sensitive values.
    """


class NativeProcessPreflightError(ValueError):
    """Reject an unsafe or inconsistent native-process launch review.

    Messages MUST NOT include entrypoints, task configuration, rejected policy
    values, environment names, or other potentially sensitive caller data.
    """


class SimulationError(ValueError):
    """Fail-closed error from the deterministic simulated vertical slice.

    Messages MUST NOT include task config, payload bodies, unknown field names,
    secrets, control characters, or other potentially sensitive document text.
    """
