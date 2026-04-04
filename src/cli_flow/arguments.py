"""Argument parsing, type coercion, and pre-flight validation.

Turns sys.argv flags into a resolved dict[str, Any] based on the flow's
argument definitions. Also checks that every variable referenced in a step
template is resolvable.
"""

from __future__ import annotations

import argparse
from typing import Any

from cli_flow.errors import PreflightError
from cli_flow.loader import MISSING, Argument, Flow
from cli_flow.template import extract_variable_names


def build_arg_parser(flow: Flow) -> argparse.ArgumentParser:
    """Build an ArgumentParser from a flow's argument definitions."""
    parser = argparse.ArgumentParser(
        prog=flow.name,
        description=flow.description,
    )

    for arg in flow.arguments:
        _add_argument(parser, arg)

    return parser


def resolve_arguments(flow: Flow, argv: list[str]) -> dict[str, Any]:
    """Parse argv against the flow's argument definitions.

    Returns a dict keyed by argument name with fully typed values.
    Raises PreflightError if any variable referenced in a step template
    is neither provided nor has a default.
    """
    parser = build_arg_parser(flow)
    namespace = parser.parse_args(argv)
    context = vars(namespace)

    _check_template_references(flow, context)

    return context


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _add_argument(parser: argparse.ArgumentParser, arg: Argument) -> None:
    flag = f"--{arg.name}"
    help_text = _build_help_text(arg)

    if arg.type == "boolean":
        # Boolean is flag-style: presence = True, absence = False.
        # argparse store_true handles this natively; default comes from the spec.
        default = arg.default if arg.default is not MISSING else False
        parser.add_argument(flag, action="store_true", default=default, help=help_text)
        return

    kwargs: dict[str, Any] = {"help": help_text}

    if arg.type == "string":
        kwargs["type"] = str
    elif arg.type == "number":
        kwargs["type"] = _coerce_number
    elif arg.type == "enum":
        kwargs["type"] = str
        kwargs["choices"] = arg.options

    if arg.required:
        kwargs["required"] = True
    else:
        kwargs["required"] = False
        kwargs["default"] = None if arg.default is MISSING else arg.default

    parser.add_argument(flag, **kwargs)


def _coerce_number(value: str) -> int | float:
    """Coerce a CLI number string to int if it's whole, float otherwise.

    --port 8080  ->  8080  (int, not 8080.0)
    --ratio 1.5  ->  1.5   (float)
    """
    f = float(value)
    return int(f) if f.is_integer() else f


def _build_help_text(arg: Argument) -> str:
    parts = [arg.description]
    if arg.format:
        parts.append(f"(example: {arg.format})")
    if arg.required:
        parts.append("[required]")
    elif arg.default is not MISSING and arg.default is not None:
        parts.append(f"(default: {arg.default})")
    return " ".join(parts)


def _check_template_references(flow: Flow, context: dict[str, Any]) -> None:
    """Verify every variable referenced in a step template is resolvable.

    An optional argument with no default (MISSING) that is referenced in a
    command or condition but was not provided by the user is a pre-flight error.
    """
    # Build a set of argument names that are not resolvable:
    # optional, no default, and not provided (value is None after argparse)
    missing_defaults = {
        arg.name
        for arg in flow.arguments
        if arg.default is MISSING and not arg.required and context.get(arg.name) is None
    }

    if not missing_defaults:
        return

    # Scan every step's command and condition for references to those names
    violations: list[str] = []
    for step in flow.workflow.steps:
        templates = [("command", step.command)]
        if step.condition:
            templates.append(("condition", step.condition))

        for field_name, template_str in templates:
            referenced = extract_variable_names(template_str)
            for name in referenced & missing_defaults:
                violations.append(
                    f"step '{step.name}' {field_name} references '{name}' "
                    f"which is optional with no default and was not provided"
                )

    if violations:
        raise PreflightError(
            "Unresolvable template references:\n  " + "\n  ".join(violations)
        )
