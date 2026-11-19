"""Domain errors.

Each error carries a stable `code` (SPEC §7) so the API can render
`{"error": code, "message": message}` without knowing every error class.
"""


class CoveredError(Exception):
    """Base class for every expected, user-facing error."""

    code: str = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidInputError(CoveredError):
    """Input that is well-formed but not acceptable (bad amount, currency, ...)."""

    code = "validation_error"


class InvalidAmountError(InvalidInputError):
    """An amount could not be parsed into positive minor units."""


class UnsupportedCurrencyError(InvalidInputError):
    """The MVP supports only the company currency."""


class NotFoundError(CoveredError):
    code = "not_found"


class NoActivePolicyError(CoveredError):
    """The employee's policy has no active version: never evaluate, never approve."""

    code = "no_active_policy"


class VersionImmutableError(CoveredError):
    code = "version_immutable"


class CompileInProgressError(CoveredError):
    code = "compile_in_progress"


class ActivationBlockedError(CoveredError):
    code = "activation_blocked"


class IdempotencyKeyReusedError(CoveredError):
    code = "idempotency_key_reused"


class InvalidTransitionError(CoveredError):
    code = "invalid_transition"
