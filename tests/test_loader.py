"""Tests for loader.py — YAML loading and schema validation."""

import pytest
from pathlib import Path

from cli_flow.loader import load_flow, MISSING
from cli_flow.errors import SchemaError

FIXTURES = Path(__file__).parent / "fixtures"


class TestValidFlow:
    def test_returns_flow_dataclass(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        assert flow.name == "Developer Onboarding"
        assert flow.version == "1.0.0"
        assert flow.description == "Clone a repo and start local services"

    def test_arguments_parsed(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        arg_names = [a.name for a in flow.arguments]
        assert "repo" in arg_names
        assert "useHttps" in arg_names
        assert "target" in arg_names
        assert "port" in arg_names
        assert "env" in arg_names

    def test_required_argument(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        repo = next(a for a in flow.arguments if a.name == "repo")
        assert repo.required is True
        assert repo.default is MISSING

    def test_optional_argument_with_default(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        port = next(a for a in flow.arguments if a.name == "port")
        assert port.required is False
        assert port.default == 8080

    def test_boolean_argument(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        use_https = next(a for a in flow.arguments if a.name == "useHttps")
        assert use_https.type == "boolean"
        assert use_https.default is False

    def test_enum_argument_has_options(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        env = next(a for a in flow.arguments if a.name == "env")
        assert env.type == "enum"
        assert env.options == ["local", "staging", "production"]

    def test_workflow_depends_on(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        assert "docker compose" in flow.workflow.depends_on
        assert "git" in flow.workflow.depends_on

    def test_workflow_env(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        assert flow.workflow.env == {"LOG_LEVEL": "info"}

    def test_steps_are_ordered_list(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        step_names = [s.name for s in flow.workflow.steps]
        assert step_names == ["pullRepo", "startServices", "showStatus"]

    def test_step_fields(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        pull = flow.workflow.steps[0]
        assert pull.name == "pullRepo"
        assert pull.soft_fail is False
        assert pull.condition is None

    def test_step_soft_fail(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        show = flow.workflow.steps[2]
        assert show.soft_fail is True

    def test_step_env(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        start = flow.workflow.steps[1]
        assert start.env == {"COMPOSE_PROJECT_NAME": "myproject"}

    def test_step_condition(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        show = flow.workflow.steps[2]
        assert show.condition is not None

    def test_step_workdir(self):
        flow = load_flow(str(FIXTURES / "valid_full.yaml"))
        start = flow.workflow.steps[1]
        assert start.workdir == "{{ target }}"


class TestInvalidFlows:
    def test_missing_name_raises_schema_error(self):
        with pytest.raises(SchemaError) as exc_info:
            load_flow(str(FIXTURES / "invalid_missing_name.yaml"))
        assert "name" in str(exc_info.value)

    def test_enum_without_options_raises_schema_error(self):
        with pytest.raises(SchemaError) as exc_info:
            load_flow(str(FIXTURES / "invalid_enum_no_options.yaml"))
        assert "options" in str(exc_info.value)

    def test_file_not_found_raises_schema_error(self):
        with pytest.raises(SchemaError) as exc_info:
            load_flow("does_not_exist.yaml")
        assert "not found" in str(exc_info.value)

    def test_invalid_yaml_raises_schema_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: [unclosed")
        with pytest.raises(SchemaError) as exc_info:
            load_flow(str(bad))
        assert "invalid YAML" in str(exc_info.value)

    def test_invalid_argument_type_raises_schema_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: x\nversion: '1'\ndescription: x\n"
            "arguments:\n  foo:\n    type: integer\n    required: true\n"
            "workflow:\n  steps:\n    - name: s\n      command: echo hi\n"
        )
        with pytest.raises(SchemaError) as exc_info:
            load_flow(str(bad))
        assert "type" in str(exc_info.value)

    def test_default_on_required_arg_raises_schema_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: x\nversion: '1'\ndescription: x\n"
            "arguments:\n  foo:\n    type: string\n    required: true\n    default: oops\n"
            "workflow:\n  steps:\n    - name: s\n      command: echo hi\n"
        )
        with pytest.raises(SchemaError) as exc_info:
            load_flow(str(bad))
        assert "default" in str(exc_info.value)

    def test_duplicate_step_names_raises_schema_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: x\nversion: '1'\ndescription: x\n"
            "workflow:\n  steps:\n"
            "    - name: step1\n      command: echo 1\n"
            "    - name: step1\n      command: echo 2\n"
        )
        with pytest.raises(SchemaError) as exc_info:
            load_flow(str(bad))
        assert "duplicate" in str(exc_info.value)
