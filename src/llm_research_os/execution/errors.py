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


class PlanAuthorizationLineageError(ValueError):
    """Reject an invalid authorization-lineage reconstruction.

    Messages MUST NOT include caller-supplied digests, identifiers, prompts,
    configuration, or other potentially sensitive values.
    """


class NativeProcessPreflightError(ValueError):
    """Reject an unsafe or inconsistent native-process launch review.

    Messages MUST NOT include entrypoints, task configuration, rejected policy
    values, environment names, or other potentially sensitive caller data.
    """


class NativeProcessRuntimeError(ValueError):
    """Refuse an unsafe native-process launch or report an uncertified outcome.

    Messages MUST NOT include entrypoints, task configuration, host paths,
    interpreter paths, SSH host keys, or other potentially sensitive caller
    data. ``code`` is a stable diagnostic token for the rejecting branch.
    """

    def __init__(self, message: str, *, code: str = "native-runtime") -> None:
        super().__init__(message)
        self.code = code


class NativeSshError(ValueError):
    """Reject an unsafe or incomplete SSH onboarding target or pack.

    Messages MUST NOT include host keys, key paths, usernames combined with
    hosts, or other potentially sensitive caller data. ``code`` is a stable
    diagnostic token for the rejecting branch.
    """

    def __init__(self, message: str, *, code: str = "native-ssh") -> None:
        super().__init__(message)
        self.code = code


class NativeReviewedExecutionError(ValueError):
    """Reject an invalid reviewed-native request before any user code exists.

    Messages MUST NOT include entrypoints, host paths, interpreter contents,
    grant tokens, or other caller-supplied secrets. ``code`` is a stable
    diagnostic token. A refusal is not a Worker grant and cannot launch.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class NativeReviewedPreparationError(ValueError):
    """Refuse reviewed-native preparation before any user code starts.

    Messages MUST NOT include entrypoints, host paths, interpreter contents,
    grant tokens, or other caller-supplied secrets. ``code`` is a stable
    diagnostic token. A receipt is not a launch credential.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class SimulationError(ValueError):
    """Fail-closed error from the deterministic simulated vertical slice.

    Messages MUST NOT include task config, payload bodies, unknown field names,
    secrets, control characters, or other potentially sensitive document text.
    ``code`` is a stable diagnostic token for the rejecting branch; it is not
    caller-supplied document text.
    """

    def __init__(self, message: str, *, code: str = "SimulationError") -> None:
        super().__init__(message)
        self.code = code
