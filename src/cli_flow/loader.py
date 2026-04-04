"""YAML loading and schema validation.

Loads a flow YAML file and returns a fully validated Flow dataclass tree.
All YAML parsing uses yaml.safe_load (pure-Python SafeLoader) — never CLoader.
This is required for zipapp compatibility (C extensions cannot load from inside a zip).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

from cli_flow.errors import SchemaError

# Sentinel that distinguishes "no default key in YAML" from "default: null".
# Using a module-level object so it survives import and can be checked with `is`.
MISSING = object()

_VALID_TYPES = ("string", "boolean", "number", "enum")


@dataclass
class Argument:
    name: str
    type: Literal["string", "boolean", "number", "enum"]
    description: str
    required: bool
    default: Any          # MISSING = no default specified; None = explicit null default
    format: str | None    # display-only example, shown in --help
    options: list[str] | None  # required when type == "enum", None otherwise


@dataclass
class Step:
    name: str
    command: str
    description: str | None
    soft_fail: bool
    condition: str | None     # Jinja2 expression; step is skipped when this evaluates falsy
    workdir: str | None
    env: dict[str, str]


@dataclass
class Workflow:
    depends_on: list[str]
    env: dict[str, str]
    steps: list[Step]


@dataclass
class Flow:
    name: str
    version: str
    description: str
    arguments: list[Argument]
    workflow: Workflow


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_flow(path: str) -> Flow:
    """Load and validate a flow YAML file. Raises SchemaError on any problem."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError:
        raise SchemaError("file not found", file=path)
    except yaml.YAMLError as exc:
        line = _yaml_error_line(exc)
        raise SchemaError(f"invalid YAML: {exc}", file=path, line=line)

    return _parse_flow(raw, source=path)


def load_flow_from_string(content: str, source: str = "<string>") -> Flow:
    """Load and validate a flow from a YAML string. Used by compiled artifacts."""
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        line = _yaml_error_line(exc)
        raise SchemaError(f"invalid YAML: {exc}", file=source, line=line)

    return _parse_flow(raw, source=source)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_flow(raw: Any, source: str) -> Flow:
    if not isinstance(raw, dict):
        raise SchemaError("flow must be a YAML mapping", file=source)

    _require_keys(raw, ("name", "version", "description", "workflow"), source)

    arguments = _parse_arguments(raw.get("arguments") or {}, source)
    workflow = _parse_workflow(raw["workflow"], source)

    return Flow(
        name=raw["name"],
        version=str(raw["version"]),
        description=raw["description"],
        arguments=arguments,
        workflow=workflow,
    )


def _parse_arguments(raw: Any, source: str) -> list[Argument]:
    if not isinstance(raw, dict):
        raise SchemaError("'arguments' must be a YAML mapping", file=source)

    arguments = []
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise SchemaError(f"argument '{name}' must be a mapping", file=source)

        arg_type = spec.get("type")
        if arg_type not in _VALID_TYPES:
            raise SchemaError(
                f"argument '{name}': type must be one of {_VALID_TYPES}, got '{arg_type}'",
                file=source,
            )

        required = bool(spec.get("required", False))

        # default is only allowed when required is False
        has_default_key = "default" in spec
        if has_default_key and required:
            raise SchemaError(
                f"argument '{name}': 'default' cannot be set when 'required' is true",
                file=source,
            )
        default = spec["default"] if has_default_key else MISSING

        # enum must have options; other types must not
        options = spec.get("options")
        if arg_type == "enum" and not options:
            raise SchemaError(
                f"argument '{name}': type 'enum' requires an 'options' list",
                file=source,
            )
        if arg_type != "enum" and options is not None:
            raise SchemaError(
                f"argument '{name}': 'options' is only valid for type 'enum'",
                file=source,
            )

        arguments.append(Argument(
            name=name,
            type=arg_type,
            description=spec.get("description", ""),
            required=required,
            default=default,
            format=spec.get("format"),
            options=options,
        ))

    return arguments


def _parse_workflow(raw: Any, source: str) -> Workflow:
    if not isinstance(raw, dict):
        raise SchemaError("'workflow' must be a YAML mapping", file=source)

    steps_raw = raw.get("steps")
    if not steps_raw:
        raise SchemaError("'workflow.steps' must be a non-empty list", file=source)
    if not isinstance(steps_raw, list):
        raise SchemaError("'workflow.steps' must be a YAML list", file=source)

    steps = _parse_steps(steps_raw, source)

    return Workflow(
        depends_on=list(raw.get("dependsOn") or []),
        env=dict(raw.get("env") or {}),
        steps=steps,
    )


def _parse_steps(raw: list[Any], source: str) -> list[Step]:
    seen_names: set[str] = set()
    steps = []

    for i, spec in enumerate(raw):
        position = f"steps[{i}]"
        if not isinstance(spec, dict):
            raise SchemaError(f"{position} must be a mapping", file=source)

        name = spec.get("name")
        if not name:
            raise SchemaError(f"{position}: 'name' is required", file=source)
        if name in seen_names:
            raise SchemaError(f"duplicate step name '{name}'", file=source)
        seen_names.add(name)

        command = spec.get("command")
        if not command:
            raise SchemaError(f"step '{name}': 'command' is required", file=source)

        steps.append(Step(
            name=name,
            command=command,
            description=spec.get("description"),
            soft_fail=bool(spec.get("soft-fail", False)),
            condition=spec.get("condition"),
            workdir=spec.get("workdir"),
            env=dict(spec.get("env") or {}),
        ))

    return steps


def _require_keys(mapping: dict, keys: tuple[str, ...], source: str) -> None:
    missing = [k for k in keys if k not in mapping]
    if missing:
        raise SchemaError(f"missing required keys: {missing}", file=source)


def _yaml_error_line(exc: yaml.YAMLError) -> int | None:
    if hasattr(exc, "problem_mark") and exc.problem_mark:
        return exc.problem_mark.line + 1  # problem_mark is 0-indexed
    return None
