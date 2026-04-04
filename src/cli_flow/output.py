"""Colored terminal output helpers.

COLOR_ENABLED is set once at startup by cli.main() based on --no-color.
Tests that need color-free output use monkeypatch.setattr(output, "COLOR_ENABLED", False).
"""

COLOR_ENABLED: bool = True

# ANSI color codes
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_GREY = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _color(text: str, code: str) -> str:
    if COLOR_ENABLED:
        return f"{code}{text}{_RESET}"
    return text


def print_step_header(index: int, total: int, name: str, description: str | None) -> None:
    suffix = f" — {description}" if description else ""
    print(f"[{index}/{total}] {_color(name, _BOLD)}{suffix}")


def print_step_success(name: str) -> None:
    print(_color(f"  ✓ {name}", _GREEN))


def print_step_failure(name: str, exit_code: int) -> None:
    # stdout/stderr are already on screen (streamed in real time); print exit code only
    print(_color(f"  ✗ {name} failed (exit {exit_code})", _RED))


def print_soft_fail(name: str, exit_code: int) -> None:
    print(_color(f"  ⚠ {name} exited {exit_code} (soft-fail, continuing)", _YELLOW))


def print_step_skipped(name: str) -> None:
    print(_color(f"  – {name} skipped", _GREY))


def print_preflight_error(message: str) -> None:
    print(_color(f"Error: {message}", _RED))


def print_summary(passed: int, soft_failed: int, skipped: int, failed: list[str]) -> None:
    parts = []
    if passed:
        parts.append(_color(f"{passed} passed", _GREEN))
    if soft_failed:
        parts.append(_color(f"{soft_failed} soft-failed", _YELLOW))
    if skipped:
        parts.append(_color(f"{skipped} skipped", _GREY))
    if failed:
        names = ", ".join(failed)
        parts.append(_color(f"{len(failed)} failed ({names})", _RED))
    print("\n" + ", ".join(parts))
