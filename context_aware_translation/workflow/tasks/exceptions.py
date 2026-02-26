"""Task workflow exceptions."""


class CancelDispatchRaceError(Exception):
    """Raised when cancel dispatch encounters a known benign race condition."""

    pass


class RunValidationError(RuntimeError):
    """Raised when validate_run rejects a task before the worker is started."""

    pass
