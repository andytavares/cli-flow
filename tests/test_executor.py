"""Tests for executor.py — step execution loop."""

from pathlib import Path
from unittest.mock import patch, MagicMock, call
import subprocess

import pytest

from cli_flow.executor import run_flow
from cli_flow.loader import Flow, Workflow, Step, load_flow

FIXTURES = Path(__file__).parent / "fixtures"


def _make_result(returncode: int) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    return result


def _load_and_context(fixture: str, extra_argv: list[str] | None = None) -> tuple:
    from cli_flow.arguments import resolve_arguments
    flow = load_flow(str(FIXTURES / fixture))
    # Provide the minimum required arguments for valid_full.yaml
    argv = ["--repo", "acme/app", "--target", "/tmp/dev"]
    if extra_argv:
        argv += extra_argv
    context = resolve_arguments(flow, argv)
    return flow, context


class TestStepSuccess:
    def test_successful_step_returns_zero(self):
        flow, context = _load_and_context("valid_full.yaml")
        with patch("subprocess.run", return_value=_make_result(0)):
            code = run_flow(flow, context, dry_run=False, single_step=None)
        assert code == 0

    def test_all_steps_run_in_order(self):
        flow, context = _load_and_context("valid_full.yaml")
        ran = []

        def fake_run(cmd, **kwargs):
            ran.append(cmd)
            return _make_result(0)

        with patch("subprocess.run", side_effect=fake_run):
            run_flow(flow, context, dry_run=False, single_step=None)

        assert len(ran) > 0
        # pullRepo uses git clone
        assert "git clone" in ran[0]


class TestSoftFail:
    def test_soft_fail_step_continues(self):
        flow, context = _load_and_context("valid_full.yaml")
        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            # showStatus (3rd step) is soft-fail; make it fail
            if "docker compose ps" in cmd:
                return _make_result(1)
            return _make_result(0)

        with patch("subprocess.run", side_effect=fake_run):
            code = run_flow(flow, context, dry_run=False, single_step=None)

        # soft-fail should not bubble up as a non-zero exit
        assert code == 0
        # All steps ran despite the soft-fail
        assert call_count[0] == 3


class TestHardFail:
    def test_hard_fail_halts_execution(self):
        flow, context = _load_and_context("valid_full.yaml")
        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            return _make_result(1)  # every step fails

        with patch("subprocess.run", side_effect=fake_run):
            code = run_flow(flow, context, dry_run=False, single_step=None)

        assert code != 0
        # Only the first step should have run (pullRepo is hard-fail)
        assert call_count[0] == 1


class TestConditionSkip:
    def test_condition_false_skips_step(self, capsys):
        flow, context = _load_and_context("valid_full.yaml")
        # showStatus has condition: env == 'local'; default env is 'local' so it runs.
        # Override to 'staging' to trigger skip.
        context["env"] = "staging"
        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            return _make_result(0)

        with patch("subprocess.run", side_effect=fake_run):
            code = run_flow(flow, context, dry_run=False, single_step=None)

        assert code == 0
        # Only 2 steps ran (showStatus was skipped)
        assert call_count[0] == 2


class TestDryRun:
    def test_dry_run_does_not_call_subprocess(self):
        flow, context = _load_and_context("valid_full.yaml")
        with patch("subprocess.run") as mock_run:
            run_flow(flow, context, dry_run=True, single_step=None)
        mock_run.assert_not_called()

    def test_dry_run_prints_commands(self, capsys):
        flow, context = _load_and_context("valid_full.yaml")
        with patch("subprocess.run"):
            run_flow(flow, context, dry_run=True, single_step=None)
        captured = capsys.readouterr()
        assert "git clone" in captured.out


class TestSingleStep:
    def test_single_step_runs_only_that_step(self):
        flow, context = _load_and_context("valid_full.yaml")
        ran_cmds = []

        def fake_run(cmd, **kwargs):
            ran_cmds.append(cmd)
            return _make_result(0)

        with patch("subprocess.run", side_effect=fake_run):
            code = run_flow(flow, context, dry_run=False, single_step="startServices")

        assert code == 0
        assert len(ran_cmds) == 1
        assert "docker compose up" in ran_cmds[0]

    def test_invalid_step_name_returns_one(self, capsys):
        flow, context = _load_and_context("valid_full.yaml")
        with patch("subprocess.run"):
            code = run_flow(flow, context, dry_run=False, single_step="nonexistent")
        assert code == 1
        captured = capsys.readouterr()
        assert "nonexistent" in captured.out
        # Valid step names should be listed
        assert "pullRepo" in captured.out

    def test_single_step_shows_original_position(self, capsys):
        flow, context = _load_and_context("valid_full.yaml")
        with patch("subprocess.run", return_value=_make_result(0)):
            run_flow(flow, context, dry_run=False, single_step="startServices")
        captured = capsys.readouterr()
        # startServices is step 2 of 3
        assert "[2/3]" in captured.out


def _make_capture_flow(*steps: Step) -> Flow:
    """Build a minimal Flow with the given steps for capture tests."""
    return Flow(
        name="test",
        version="1.0",
        description="test",
        arguments=[],
        workflow=Workflow(depends_on=[], env={}, steps=list(steps)),
    )


def _make_step(name: str, command: str, result: str | None = None, error: str | None = None, soft_fail: bool = False) -> Step:
    return Step(
        name=name,
        command=command,
        description=None,
        soft_fail=soft_fail,
        condition=None,
        workdir=None,
        env={},
        result=result,
        error=error,
    )


class TestCapture:
    def test_result_captured_stdout_available_to_next_step(self):
        step_a = _make_step("getTag", "git describe --tags", result="version")
        step_b = _make_step("build", "docker build -t app:{{ version }} .")
        flow = _make_capture_flow(step_a, step_b)
        context = {}
        built_cmds = []

        def fake_run(cmd, **kwargs):
            built_cmds.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = b"v1.2.3\n"
            result.stderr = None
            return result

        with patch("subprocess.run", side_effect=fake_run):
            code = run_flow(flow, context, dry_run=False, single_step=None)

        assert code == 0
        assert context["version"] == "v1.2.3"
        assert "app:v1.2.3" in built_cmds[1]

    def test_error_captures_stderr(self):
        step = _make_step("check", "some-cmd", error="check_err")
        flow = _make_capture_flow(step)
        context = {}

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = None
            result.stderr = b"warning: deprecated\n"
            return result

        with patch("subprocess.run", side_effect=fake_run):
            run_flow(flow, context, dry_run=False, single_step=None)

        assert context["check_err"] == "warning: deprecated"

    def test_both_result_and_error_captured(self):
        step = _make_step("cmd", "echo hi", result="out", error="err")
        flow = _make_capture_flow(step)
        context = {}

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = b"hello\n"
            result.stderr = b"oops\n"
            return result

        with patch("subprocess.run", side_effect=fake_run):
            run_flow(flow, context, dry_run=False, single_step=None)

        assert context["out"] == "hello"
        assert context["err"] == "oops"

    def test_captured_value_is_stripped(self):
        step = _make_step("cmd", "echo hi", result="val")
        flow = _make_capture_flow(step)
        context = {}

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = b"  trimmed  \n"
            result.stderr = None
            return result

        with patch("subprocess.run", side_effect=fake_run):
            run_flow(flow, context, dry_run=False, single_step=None)

        assert context["val"] == "trimmed"

    def test_dry_run_injects_placeholder_for_result(self, capsys):
        step_a = _make_step("getTag", "git describe", result="version")
        step_b = _make_step("build", "docker build -t app:{{ version }} .")
        flow = _make_capture_flow(step_a, step_b)
        context = {}

        with patch("subprocess.run") as mock_run:
            code = run_flow(flow, context, dry_run=True, single_step=None)

        mock_run.assert_not_called()
        assert code == 0
        out = capsys.readouterr().out
        assert "app:<captured>" in out

    def test_dry_run_injects_placeholder_for_error(self, capsys):
        step_a = _make_step("check", "some-cmd", error="check_err")
        step_b = _make_step("use", "echo {{ check_err }}")
        flow = _make_capture_flow(step_a, step_b)
        context = {}

        with patch("subprocess.run"):
            code = run_flow(flow, context, dry_run=True, single_step=None)

        assert code == 0
        out = capsys.readouterr().out
        assert "<captured>" in out

    def test_failed_hard_step_does_not_update_context(self):
        step = _make_step("fail", "bad-cmd", result="val")
        flow = _make_capture_flow(step)
        context = {}

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = b"some output\n"
            result.stderr = None
            return result

        with patch("subprocess.run", side_effect=fake_run):
            code = run_flow(flow, context, dry_run=False, single_step=None)

        assert code != 0
        assert "val" not in context
