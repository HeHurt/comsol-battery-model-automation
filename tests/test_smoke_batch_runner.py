import json
import subprocess
import sys
from pathlib import Path

import yaml


RUNNER = Path(__file__).resolve().parents[1] / "examples" / "scripts" / "comsol_batch_runner.py"


def test_smoke_batch_runner_generates_cycle_result_json(tmp_path):
    java_file = tmp_path / "GeneratedModel.java"
    java_file.write_text("public class GeneratedModel {}", encoding="utf-8")

    criteria = {
        "meta": {"task": "smoke", "max_iterations": 1},
        "physical_sanity": {"enabled": False, "rules": []},
        "numeric_criteria": [],
        "experimental_reference": {"enabled": False, "references": []},
    }
    criteria_path = tmp_path / "acceptance.yaml"
    criteria_path.write_text(yaml.safe_dump(criteria, allow_unicode=True), encoding="utf-8")

    paths = {
        # Intentionally invalid to force compile_failed quickly in smoke test.
        "comsolcompile": str(tmp_path / "not_exists_compile.exe"),
        "comsolbatch": str(tmp_path / "not_exists_batch.exe"),
    }
    paths_path = tmp_path / "paths.json"
    paths_path.write_text(json.dumps(paths, ensure_ascii=False), encoding="utf-8")

    output_name = "cycle_result.json"
    cmd = [
        sys.executable,
        str(RUNNER),
        "--java",
        str(java_file),
        "--criteria",
        str(criteria_path),
        "--paths",
        str(paths_path),
        "--workdir",
        str(tmp_path),
        "--output",
        output_name,
        "--iteration",
        "1",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Smoke test: output file must be generated even on failed cycle.
    result_path = tmp_path / output_name
    assert result_path.exists(), proc.stderr

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload.get("success") is False
    assert payload.get("reason") == "compile_failed"
    assert proc.returncode != 0
