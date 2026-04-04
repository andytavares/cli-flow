"""Tests for template.py — Jinja2 rendering and preprocessing."""

import pytest
import jinja2

from cli_flow.template import preprocess, render_command, evaluate_condition, extract_variable_names
from cli_flow.errors import PreflightError


class TestPreprocess:
    def test_rewrites_ternary(self):
        result = preprocess("{{ useHttps ? 'https://' : 'git@' }}")
        assert result == "{{ 'https://' if useHttps else 'git@' }}"

    def test_leaves_normal_expressions_untouched(self):
        result = preprocess("{{ repo }}")
        assert result == "{{ repo }}"

    def test_leaves_or_untouched(self):
        # || is not rewritten — authors must use Jinja2's `or`
        result = preprocess("{{ x or '.' }}")
        assert result == "{{ x or '.' }}"


class TestRenderCommand:
    def test_variable_reference(self):
        assert render_command("git clone {{ repo }}", {"repo": "acme/app"}) == "git clone acme/app"

    def test_ternary(self):
        result = render_command(
            "{{ useHttps ? 'https://github.com/' : 'git@github.com:' }}{{ repo }}",
            {"useHttps": True, "repo": "acme/app"},
        )
        assert result == "https://github.com/acme/app"

    def test_ternary_false_branch(self):
        result = render_command(
            "{{ useHttps ? 'https://' : 'git@' }}{{ repo }}",
            {"useHttps": False, "repo": "acme/app"},
        )
        assert result == "git@acme/app"

    def test_fallback_with_or(self):
        assert render_command("{{ target or '.' }}", {"target": ""}) == "."
        assert render_command("{{ target or '.' }}", {"target": "/home/dev"}) == "/home/dev"

    def test_string_concat(self):
        result = render_command("{{ 'https://github.com/' + repo }}", {"repo": "acme/app"})
        assert result == "https://github.com/acme/app"

    def test_comparison(self):
        result = render_command("{{ env == 'production' }}", {"env": "production"})
        assert result == "True"

    def test_undefined_variable_raises_preflight_error(self):
        with pytest.raises(PreflightError, match="unresolved variable"):
            render_command("{{ unknown }}", {})

    def test_pipe_pipe_raises_syntax_error(self):
        # || is not supported — Jinja2 will raise a syntax error
        with pytest.raises(PreflightError, match="syntax error"):
            render_command("{{ x || '.' }}", {"x": ""})


class TestEvaluateCondition:
    def test_true_condition(self):
        assert evaluate_condition("{{ env == 'production' }}", {"env": "production"}) is True

    def test_false_condition(self):
        assert evaluate_condition("{{ env == 'production' }}", {"env": "staging"}) is False

    def test_empty_string_is_false(self):
        assert evaluate_condition("{{ '' }}", {}) is False

    def test_string_false_is_false(self):
        assert evaluate_condition("{{ 'false' }}", {}) is False

    def test_string_false_case_insensitive(self):
        assert evaluate_condition("{{ 'False' }}", {}) is False

    def test_string_zero_is_false(self):
        assert evaluate_condition("{{ '0' }}", {}) is False

    def test_truthy_value(self):
        assert evaluate_condition("{{ 'yes' }}", {}) is True

    def test_undefined_raises_preflight_error(self):
        with pytest.raises(PreflightError):
            evaluate_condition("{{ unknown }}", {})


class TestExtractVariableNames:
    def test_simple_reference(self):
        assert "repo" in extract_variable_names("{{ repo }}")

    def test_multiple_references(self):
        names = extract_variable_names("{{ 'https://' + host }}/{{ path }}")
        assert "host" in names
        assert "path" in names

    def test_ternary_extracts_condition_variable(self):
        names = extract_variable_names("{{ useHttps ? 'https://' : 'git@' }}")
        assert "useHttps" in names

    def test_quoted_string_not_extracted(self):
        names = extract_variable_names("{{ 'literal' }}")
        # 'literal' is a string constant, not a variable name
        assert "literal" not in names
