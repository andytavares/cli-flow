"""Integration tests for compiler.py — compile and run zipapp artifacts."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from cli_flow.compiler import compile_flow, default_output_name
from cli_flow.errors import SchemaError

FIXTURES = Path(__file__).parent / "fixtures"


class TestDefaultOutputName:
    def test_spaces_become_hyphens(self):
        assert default_output_name("Developer Onboarding") == "developer-onboarding"

    def test_already_lowercase(self):
        assert default_output_name("my-flow") == "my-flow"

    def test_strips_whitespace(self):
        assert default_output_name("  My Flow  ") == "my-flow"


class TestCompileFlow:
    def test_invalid_flow_raises_schema_error(self, tmp_path):
        with pytest.raises(SchemaError):
            compile_flow(
                str(FIXTURES / "invalid_missing_name.yaml"),
                str(tmp_path / "out"),
                bundle_deps=False,
            )

    def test_produces_output_file(self, tmp_path):
        output_path = str(tmp_path / "onboarding")
        compile_flow(str(FIXTURES / "valid_full.yaml"), output_path, bundle_deps=False)
        assert os.path.exists(output_path)

    def test_output_is_executable(self, tmp_path):
        output_path = str(tmp_path / "onboarding")
        compile_flow(str(FIXTURES / "valid_full.yaml"), output_path, bundle_deps=False)
        file_stat = os.stat(output_path)
        assert file_stat.st_mode & stat.S_IXUSR

    def test_no_build_dir_left_behind(self, tmp_path):
        output_path = str(tmp_path / "onboarding")
        compile_flow(str(FIXTURES / "valid_full.yaml"), output_path, bundle_deps=False)
        # The _build temp dir should be cleaned up; only the output file exists
        entries = list(tmp_path.iterdir())
        assert len(entries) == 1
        assert entries[0].name == "onboarding"

    def test_help_flag_works_on_compiled_artifact(self, tmp_path):
        output_path = str(tmp_path / "onboarding")
        compile_flow(str(FIXTURES / "valid_full.yaml"), output_path, bundle_deps=False)

        result = subprocess.run(
            [sys.executable, output_path, "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--repo" in result.stdout

    def test_compiled_artifact_runs_with_valid_args(self, tmp_path):
        output_path = str(tmp_path / "onboarding")
        compile_flow(str(FIXTURES / "valid_full.yaml"), output_path, bundle_deps=False)

        result = subprocess.run(
            [sys.executable, output_path, "--dry-run", "--repo", "acme/app", "--target", "/tmp/dev"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "git clone" in result.stdout

    def test_original_yaml_not_required_at_runtime(self, tmp_path):
        yaml_copy = tmp_path / "flow.yaml"
        import shutil
        shutil.copy(FIXTURES / "valid_full.yaml", yaml_copy)

        output_path = str(tmp_path / "onboarding")
        compile_flow(str(yaml_copy), output_path, bundle_deps=False)

        # Delete the original YAML — the compiled artifact should still work
        yaml_copy.unlink()
        assert not yaml_copy.exists()

        result = subprocess.run(
            [sys.executable, output_path, "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
