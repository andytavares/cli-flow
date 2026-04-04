"""Shared exception types for cli-flow."""


class SchemaError(Exception):
    """Raised when a flow YAML file fails structural validation."""

    def __init__(self, message: str, file: str, line: int | None = None) -> None:
        self.file = file
        self.line = line
        location = f"{file}:{line}" if line else file
        super().__init__(f"{location}: {message}")


class PreflightError(Exception):
    """Raised when pre-execution checks fail (missing args, missing deps, unresolvable templates)."""


class StepError(Exception):
    """Raised when a step exits non-zero and soft-fail is False."""

    def __init__(self, step_name: str, exit_code: int) -> None:
        self.step_name = step_name
        self.exit_code = exit_code
        super().__init__(f"Step '{step_name}' failed with exit code {exit_code}")
