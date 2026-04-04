"""Jinja2 template rendering for commands and conditions.

All templates are rendered with StrictUndefined so unresolved variables raise
immediately rather than silently rendering as empty strings.

The YAML authoring syntax supports a JS-style ternary shorthand (A ? B : C)
which is rewritten to Jinja2's native (B if A else C) before rendering.
The || operator is NOT rewritten — authors must use Jinja2-native `or`.
"""

from __future__ import annotations

import re

import jinja2

from cli_flow.errors import PreflightError

# Matches {{ A ? B : C }} — the JS-style ternary inside a Jinja2 block.
# Capture groups: (condition, true_value, false_value)
#
# Both ? and : require at least one space on each side. This distinguishes
# the ternary : from colons inside values (e.g. 'https://' or 'git@host:').
# Authors must write:  {{ useHttps ? 'https://' : 'git@' }}
# Not:                 {{ useHttps?'https://':'git@' }}
_TERNARY_RE = re.compile(
    r"\{\{\s*(.+?)\s+\?\s+(.+?)\s+:\s+(.+?)\s*\}\}"
)

# Shared Jinja2 environment — StrictUndefined ensures any missing variable
# raises immediately rather than rendering as an empty string.
_ENV = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    autoescape=False,
)


def preprocess(template: str) -> str:
    """Rewrite JS-style ternary (A ? B : C) to Jinja2 (B if A else C).

    Only rewrites expressions inside {{ }} delimiters.
    The || operator is not handled here — use Jinja2's `or` instead.
    """
    return _TERNARY_RE.sub(
        lambda m: "{{ " + f"{m.group(2)} if {m.group(1)} else {m.group(3)}" + " }}",
        template,
    )


def render_command(command: str, context: dict) -> str:
    """Render a command string with the resolved argument context."""
    try:
        return _ENV.from_string(preprocess(command)).render(context)
    except jinja2.UndefinedError as exc:
        raise PreflightError(f"unresolved variable in command: {exc}") from exc
    except jinja2.TemplateSyntaxError as exc:
        raise PreflightError(f"template syntax error in command: {exc}") from exc


def evaluate_condition(condition: str, context: dict) -> bool:
    """Render a condition expression and coerce the result to bool.

    Returns False for: empty string, "false" (case-insensitive), "0".
    Returns True for everything else.
    """
    try:
        rendered = _ENV.from_string(preprocess(condition)).render(context).strip()
    except jinja2.UndefinedError as exc:
        raise PreflightError(f"unresolved variable in condition: {exc}") from exc
    except jinja2.TemplateSyntaxError as exc:
        raise PreflightError(f"template syntax error in condition: {exc}") from exc

    return rendered.lower() not in ("", "false", "0")


def extract_variable_names(template: str) -> set[str]:
    """Return all variable names referenced in a template string.

    Uses the Jinja2 AST parser so it handles all expression forms correctly,
    including nested expressions and quoted strings (unlike regex).
    """
    try:
        ast = _ENV.parse(preprocess(template))
    except jinja2.TemplateSyntaxError:
        # Syntax errors are surfaced at render time with better context
        return set()

    return {node.name for node in ast.find_all(jinja2.nodes.Name)}
