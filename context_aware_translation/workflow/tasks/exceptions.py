"""Task workflow exceptions."""


class CancelDispatchRaceError(Exception):
    """Raised when cancel dispatch encounters a known benign race condition."""
    pass
