import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml


REPORTER = Path(__file__).resolve().parents[1] / "examples" / "scripts" / "generate_report.py"


def test_smoke_generate_report_outputs_docx(tmp_path):
    java_file = tmp_path / "GeneratedModel.java"
    java_file.write_text(
        "\n".join(
            [
                "import com.comsol.model.*;",
                "public class GeneratedModel {",
                "  public static Model run() {",
                "    Model model = ModelUtil.create(\"Model\");",
                "    model.component().create(\"comp1\", false);",
                "    model.component(\"comp1\").geom().create(\"geom1\", 1);",
                "    model.param().set(\"V_min\", \"2.5[V]\", \"min voltage\");",
                "    model.component(\"comp1\").physics().create(\"liion\", \"LithiumIonBattery\", \"geom1\");",
                "    return model;",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    metrics = pd.DataFrame([{"capacity_Ah": 280.0, "min_voltage": 2.8, "max_temperature": 35.0}])
    metrics_path = tmp_path / "metrics.csv"
    metrics.to_csv(metrics_path, index=False)

    criteria = {
        "meta": {"task": "smoke report"},
        "physical_sanity": {"enabled": False, "rules": []},
        "numeric_criteria": [],
        "experimental_reference": {"enabled": False, "references": []},
    }
    criteria_path = tmp_path / "acceptance.yaml"
    criteria_path.write_text(yaml.safe_dump(criteria, allow_unicode=True), encoding="utf-8")

    history = [
        {
            "iteration": 1,
            "acceptance": {
                "all_passed": True,
                "items_passed": [{"id": "capacity", "actual": 280, "bound": ">=270"}],
                "items_failed": [],
                "warnings": [],
            },
        }
    ]
    history_path = tmp_path / "debug_history.json"
    history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")

    out_path = tmp_path / "simulation_report.docx"
    cmd = [
        sys.executable,
        str(REPORTER),
        "--java",
        str(java_file),
        "--metrics",
        str(metrics_path),
        "--criteria",
        str(criteria_path),
        "--debug-log",
        str(history_path),
        "--workdir",
        str(tmp_path),
        "--out",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr
    assert out_path.exists()
    assert out_path.stat().st_size > 0
