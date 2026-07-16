class EngineUnavailableError(RuntimeError):
    """Raised when an engine cannot be activated."""


class UnsupportedOperationError(RuntimeError):
    """Raised when an engine cannot perform an operation."""


class EngineValidationError(ValueError):
    """Raised when an engine rejects a request before execution."""

    def __init__(self, message: str, loc: tuple[str, ...]) -> None:
        super().__init__(message)
        self.loc = loc
        self.message = message

    def details(self) -> list[dict[str, object]]:
        return [{"loc": list(self.loc), "msg": self.message}]
