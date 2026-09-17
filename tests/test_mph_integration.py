"""Optional live COMSOL integration test.

Set COMSOL_MPH_TEST_MODEL to a small, safe .mph file to enable it. The test is
skipped in ordinary unit-test runs because it consumes a COMSOL license.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


MODEL = os.environ.get("COMSOL_MPH_TEST_MODEL")
pytestmark = pytest.mark.skipif(not MODEL, reason="COMSOL_MPH_TEST_MODEL is not configured")
RUNNER = Path(__file__).parents[1] / "scripts" / "run_mph_tool.py"


def test_live_summary_audit_loads_and_unloads_model(tmp_path):
    model_path = Path(MODEL).resolve()
    output = tmp_path / "audit.json"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "action": "audit",
                "options": {"scope": "summary", "preset": "voltage"},
                "models": [{"path": str(model_path), "tag": "integration_audit"}],
                "output": str(output),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--config", str(config)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["action"] == "audit"
    assert payload["models"][0]["scope"] == "summary"
    assert payload["models"][0]["preset"] == "voltage"
