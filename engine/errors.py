class EngineUnavailableError(RuntimeError):
    """Raised when an engine cannot be activated."""


class UnsupportedOperationError(RuntimeError):
    """Raised when an engine cannot perform an operation."""
