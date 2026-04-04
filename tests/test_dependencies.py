"""Tests for dependencies.py — dependency pre-flight checks."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from cli_flow.dependencies import check_dependencies, assert_dependencies
from cli_flow.errors import PreflightError


def _make_result(returncode: int) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    return result


class TestCheckDependencies:
    def test_available_single_binary(self):
        with patch("subprocess.run", return_value=_make_result(0)):
            missing = check_dependencies(["git"])
        assert missing == []

    def test_missing_single_binary(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            missing = check_dependencies(["notabinary"])
        assert missing == ["notabinary"]

    def test_non_zero_exit_counts_as_missing(self):
        with patch("subprocess.run", return_value=_make_result(1)):
            missing = check_dependencies(["badtool"])
        assert missing == ["badtool"]

    def test_multi_word_entry(self):
        """'docker compose' should be checked as ['docker', 'compose', '--version']."""
        with patch("subprocess.run", return_value=_make_result(0)) as mock_run:
            check_dependencies(["docker compose"])
        mock_run.assert_called_once_with(
            ["docker", "compose", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )

    def test_single_word_entry(self):
        """'git' should be checked as ['git', '--version']."""
        with patch("subprocess.run", return_value=_make_result(0)) as mock_run:
            check_dependencies(["git"])
        mock_run.assert_called_once_with(
            ["git", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )

    def test_collects_all_missing(self):
        """All missing deps are returned, not just the first one."""
        def side_effect(cmd, **kwargs):
            if "git" in cmd:
                return _make_result(0)
            raise FileNotFoundError

        with patch("subprocess.run", side_effect=side_effect):
            missing = check_dependencies(["git", "notreal", "alsonot"])
        assert "notreal" in missing
        assert "alsonot" in missing
        assert "git" not in missing

    def test_timeout_counts_as_missing(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)):
            missing = check_dependencies(["slowtool"])
        assert missing == ["slowtool"]

    def test_empty_list_returns_empty(self):
        missing = check_dependencies([])
        assert missing == []


class TestAssertDependencies:
    def test_no_missing_does_not_raise(self):
        with patch("subprocess.run", return_value=_make_result(0)):
            assert_dependencies(["git"])  # should not raise

    def test_missing_dep_raises_preflight_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(PreflightError, match="notabinary"):
                assert_dependencies(["notabinary"])

    def test_all_missing_listed_in_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(PreflightError) as exc_info:
                assert_dependencies(["tool1", "tool2"])
        error_msg = str(exc_info.value)
        assert "tool1" in error_msg
        assert "tool2" in error_msg
