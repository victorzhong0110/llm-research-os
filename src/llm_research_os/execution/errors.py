"""Stable fail-closed errors for SimulatedRuntime."""


class SimulationError(ValueError):
    """Fail-closed error from the deterministic simulated vertical slice.

    Messages MUST NOT include task config, payload bodies, unknown field names,
    secrets, control characters, or other potentially sensitive document text.
    """
