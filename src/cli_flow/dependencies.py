"""Dependency pre-flight checks.

Verifies that every entry in a flow's `dependsOn` list is available on PATH
before any step runs. All failures are collected and reported together.

Multi-word entries like "docker compose" are checked by running the binary
with the subcommand as an argument: `docker compose --version`.
Single-word entries are checked as: `git --version`.
"""

from __future__ import annotations

import subprocess

from cli_flow.errors import PreflightError


def check_dependencies(depends_on: list[str]) -> list[str]:
    """Check each dependency and return a list of missing entries.

    Does not raise — collects all failures so they can be reported together.
    """
    missing = []
    for entry in depends_on:
        if not _is_available(entry):
            missing.append(entry)
    return missing


def assert_dependencies(depends_on: list[str]) -> None:
    """Check all dependencies and raise PreflightError if any are missing."""
    missing = check_dependencies(depends_on)
    if missing:
        formatted = "\n  ".join(missing)
        raise PreflightError(
            f"The following dependencies were not found:\n  {formatted}"
        )


def _is_available(entry: str) -> bool:
    """Return True if the dependency is available, False otherwise.

    Splits on the first space so "docker compose" runs as:
      subprocess.run(["docker", "compose", "--version"], ...)
    Single words run as:
      subprocess.run(["git", "--version"], ...)
    """
    parts = entry.split(" ", maxsplit=1)
    binary = parts[0]
    subcommand = parts[1].split() if len(parts) > 1 else []
    cmd = [binary] + subcommand + ["--version"]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
