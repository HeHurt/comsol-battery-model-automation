import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "examples" / "scripts" / "comsol_batch_runner.py"
spec = importlib.util.spec_from_file_location("comsol_batch_runner", MODULE_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(runner)


def _write_two_col_csv(path, xs, ys):
    pd.DataFrame({"time": xs, "value": ys}).to_csv(path, index=False)


def test_physical_sanity_voltage_window_fails_when_outside(tmp_path):
    metrics = {
        "E_cell": 4.0,
        "V_min": 2.5,
        "V_max": 3.65,
        "min_voltage": 2.4,
        "max_voltage": 3.6,
    }
    criteria = {
        "physical_sanity": {
            "enabled": True,
            "rules": [{"id": "voltage_in_window", "expr": "E_cell >= V_min and E_cell <= V_max"}],
        }
    }

    result = runner.check_acceptance(metrics, criteria, str(tmp_path))
    assert result["all_passed"] is False
    assert any(item["id"] == "voltage_in_window" for item in result["items_failed"])


def test_r2_metric_uses_greater_equal_threshold(tmp_path):
    sim_csv = tmp_path / "sim.csv"
    exp_csv = tmp_path / "exp.csv"

    xs = [0, 1, 2, 3]
    ys = [3.3, 3.2, 3.1, 3.0]
    _write_two_col_csv(sim_csv, xs, ys)
    _write_two_col_csv(exp_csv, xs, ys)

    criteria = {
        "experimental_reference": {
            "enabled": True,
            "references": [
                {
                    "id": "r2_ref",
                    "file": str(exp_csv),
                    "sim_export": sim_csv.name,
                    "metric": "R2",
                    "threshold": 0.95,
                    "align_method": "interp",
                    "severity": "hard",
                }
            ],
        }
    }

    result = runner.check_acceptance({}, criteria, str(tmp_path))
    assert result["all_passed"] is True
    assert any(item["id"] == "r2_ref" and item["passed"] for item in result["items_passed"])


def test_weighted_score_can_fail_overall_threshold(tmp_path):
    sim_a = tmp_path / "sim_a.csv"
    exp_a = tmp_path / "exp_a.csv"
    sim_b = tmp_path / "sim_b.csv"
    exp_b = tmp_path / "exp_b.csv"

    _write_two_col_csv(sim_a, [0, 1], [1.0, 1.0])
    _write_two_col_csv(exp_a, [0, 1], [1.0, 1.0])  # RMSE = 0

    _write_two_col_csv(sim_b, [0, 1], [2.0, 2.0])
    _write_two_col_csv(exp_b, [0, 1], [1.0, 1.0])  # RMSE = 1

    criteria = {
        "experimental_reference": {
            "enabled": True,
            "references": [
                {
                    "id": "case_a",
                    "file": str(exp_a),
                    "sim_export": sim_a.name,
                    "metric": "RMSE",
                    "threshold": 2.0,
                    "align_method": "interp",
                    "severity": "hard",
                },
                {
                    "id": "case_b",
                    "file": str(exp_b),
                    "sim_export": sim_b.name,
                    "metric": "RMSE",
                    "threshold": 2.0,
                    "align_method": "interp",
                    "severity": "hard",
                },
            ],
            "weighted_score": {
                "enabled": True,
                "weights": {
                    "case_a": 0.5,
                    "case_b": 0.5,
                },
                "overall_threshold": 0.4,
            },
        }
    }

    result = runner.check_acceptance({}, criteria, str(tmp_path))
    assert result["all_passed"] is False
    assert any(item["id"] == "weighted_score" for item in result["items_failed"])
