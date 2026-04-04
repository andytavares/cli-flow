"""Tests for arguments.py — argument parsing, type coercion, and pre-flight validation."""

import pytest
from pathlib import Path

from cli_flow.arguments import resolve_arguments
from cli_flow.loader import load_flow
from cli_flow.errors import PreflightError

FIXTURES = Path(__file__).parent / "fixtures"


class TestTypeCoercion:
    def setup_method(self):
        self.flow = load_flow(str(FIXTURES / "valid_full.yaml"))

    def test_string_argument(self):
        context = resolve_arguments(self.flow, ["--repo", "acme/app", "--target", "/dev"])
        assert context["repo"] == "acme/app"
        assert isinstance(context["repo"], str)

    def test_boolean_flag_present(self):
        context = resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev", "--useHttps"])
        assert context["useHttps"] is True

    def test_boolean_flag_absent(self):
        context = resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev"])
        assert context["useHttps"] is False

    def test_number_integer(self):
        context = resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev", "--port", "8080"])
        assert context["port"] == 8080
        assert isinstance(context["port"], int)

    def test_number_not_float_for_whole_numbers(self):
        context = resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev", "--port", "9000"])
        # Must be int, not 9000.0
        assert context["port"] == 9000
        assert type(context["port"]) is int

    def test_number_float(self):
        # Use a flow with a float-accepting field
        context = resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev", "--port", "3.14"])
        assert context["port"] == pytest.approx(3.14)
        assert isinstance(context["port"], float)

    def test_enum_valid_choice(self):
        context = resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev", "--env", "staging"])
        assert context["env"] == "staging"

    def test_enum_invalid_choice_exits(self):
        with pytest.raises(SystemExit):
            resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev", "--env", "invalid"])

    def test_number_default_applied(self):
        context = resolve_arguments(self.flow, ["--repo", "x", "--target", "/dev"])
        assert context["port"] == 8080


class TestRequiredArguments:
    def setup_method(self):
        self.flow = load_flow(str(FIXTURES / "valid_full.yaml"))

    def test_missing_required_arg_exits(self):
        # --repo is required; omitting it should cause argparse to exit 1
        with pytest.raises(SystemExit) as exc_info:
            resolve_arguments(self.flow, ["--target", "/dev"])
        assert exc_info.value.code != 0

    def test_all_required_args_provided(self):
        context = resolve_arguments(self.flow, ["--repo", "acme/app", "--target", "/dev"])
        assert context["repo"] == "acme/app"
        assert context["target"] == "/dev"


class TestTemplateReferenceCheck:
    def test_optional_no_default_referenced_raises_preflight(self):
        flow = load_flow(str(FIXTURES / "optional_no_default_referenced.yaml"))
        # --target not provided, but it's referenced in the step command
        with pytest.raises(PreflightError, match="target"):
            resolve_arguments(flow, [])

    def test_optional_no_default_provided_by_user_is_ok(self):
        flow = load_flow(str(FIXTURES / "optional_no_default_referenced.yaml"))
        # User provides the value explicitly — no error
        context = resolve_arguments(flow, ["--target", "/tmp/out"])
        assert context["target"] == "/tmp/out"
