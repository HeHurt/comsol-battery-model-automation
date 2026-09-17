import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "mph_tool.py"
SPEC = importlib.util.spec_from_file_location("mph_tool", SCRIPT)
mph_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mph_tool)


def test_recursive_diff_reports_only_changed_paths():
    left = {"model": {"params": {"L": "1[m]", "C": 1}}, "tool_version": "1"}
    right = {"model": {"params": {"L": "2[m]", "C": 1}}, "tool_version": "2"}
    result = mph_tool.recursive_diff(left, right, {"tool_version"})
    assert result == [{"path": "model.params.L", "left": "1[m]", "right": "2[m]"}]


def test_patch_refuses_source_overwrite(tmp_path):
    source = tmp_path / "source.mph"
    source.touch()
    with pytest.raises(ValueError, match="must differ"):
        mph_tool.ensure_save_as(str(source), str(source))


def test_validate_config_requires_action_keys():
    with pytest.raises(ValueError, match="Missing config keys"):
        mph_tool.validate_config({"action": "audit", "models": []})


def test_diff_action_writes_json(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    output = tmp_path / "diff.json"
    left.write_text('{"x": 1}', encoding="utf-8")
    right.write_text('{"x": 2}', encoding="utf-8")
    result = mph_tool.action_diff({"left": str(left), "right": str(right), "output": str(output)})
    assert result["differences"][0]["path"] == "x"
    assert output.exists()


def test_known_diagnostic_presets_are_available():
    assert set(mph_tool.AUDIT_PRESETS) == {"voltage", "capacity", "heat_balance", "solver", "sweep"}


def test_empty_parameter_patterns_skip_manager_access():
    class ModelThatMustNotBeRead:
        def param(self):
            raise AssertionError("parameter manager should not be opened")

    assert mph_tool._parameters(ModelThatMustNotBeRead(), []) == {}


def test_manager_get_prefers_comsol_64_get_method():
    class Manager:
        def get(self, tag):
            return f"node:{tag}"

        def __call__(self, tag):
            raise AssertionError("COMSOL 6.4 manager should use get(tag)")

    assert mph_tool._manager_get(Manager(), "ocv") == "node:ocv"


def test_smoke_requires_explicit_output_units():
    with pytest.raises(ValueError, match="explicit units"):
        mph_tool.validate_config(
            {
                "action": "smoke",
                "source": "model.mph",
                "output": "smoke.json",
                "metrics": [{"name": "voltage", "expr": "liion.E_cell"}],
            }
        )
