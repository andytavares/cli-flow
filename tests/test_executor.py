"""Tests for executor.py — step execution loop."""

from pathlib import Path
from unittest.mock import patch, MagicMock, call
import subprocess

import pytest

from cli_flow.executor import run_flow
from cli_flow.loader import load_flow

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
