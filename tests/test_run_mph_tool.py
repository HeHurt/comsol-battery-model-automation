import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_mph_tool.py"
SPEC = importlib.util.spec_from_file_location("run_mph_tool", SCRIPT)
run_mph_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_mph_tool)


class FakeClient:
    def __init__(self, lease):
        self.lease = lease
        self.executed = []
        self.disconnected = []

    def ensure_session(self):
        return self.lease

    def exec_file(self, session_id, script):
        assert script.exists()
        self.executed.append((session_id, script.read_text(encoding="utf-8")))
        return {"executed": True}

    def disconnect(self, session_id):
        self.disconnected.append(session_id)


def test_parse_json_accepts_prefixed_output():
    assert run_mph_tool._parse_json('notice\n{"sessions": []}\n') == {"sessions": []}


def test_default_sim_command_is_portable_and_pinned():
    assert run_mph_tool.SIM_PREFIX == [
        "uvx",
        "--from",
        "sim-cli-core==0.3.7",
        "--with",
        "sim-plugin-comsol==0.1.14",
        "sim",
    ]


def test_sim_client_turns_timeout_into_actionable_error():
    def timeout_runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    client = run_mph_tool.SimClient(timeout_runner)
    with pytest.raises(RuntimeError, match="timed out after 20s"):
        client.list_sessions()


def test_execute_cleans_only_created_session(tmp_path):
    config_path = tmp_path / "verify.json"
    config_path.write_text(
        json.dumps({"action": "verify", "source": "model.mph", "assertions": []}),
        encoding="utf-8",
    )
    client = FakeClient(run_mph_tool.SessionLease("new-session", created=True))
    result = run_mph_tool.execute(config_path, client)
    assert result == {"executed": True}
    assert client.disconnected == ["new-session"]
    assert not (tmp_path / ".verify.mph_exec.py").exists()
    assert (tmp_path / "verify.session.json").exists()
    manifest = json.loads((tmp_path / "verify.session.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["created_session_disconnected"] is True


def test_execute_preserves_reused_session(tmp_path):
    config_path = tmp_path / "verify.json"
    config_path.write_text(
        json.dumps({"action": "verify", "source": "model.mph", "assertions": []}),
        encoding="utf-8",
    )
    client = FakeClient(run_mph_tool.SessionLease("existing-session", created=False))
    run_mph_tool.execute(config_path, client)
    assert client.disconnected == []


def test_diff_runs_without_sim_session(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    output = tmp_path / "diff.json"
    config_path = tmp_path / "config.json"
    left.write_text('{"x": 1}', encoding="utf-8")
    right.write_text('{"x": 2}', encoding="utf-8")
    config_path.write_text(
        json.dumps({"action": "diff", "left": str(left), "right": str(right), "output": str(output)}),
        encoding="utf-8",
    )
    result = run_mph_tool.execute(config_path, FakeClient(None))
    assert result["differences"] == [{"path": "x", "left": 1, "right": 2}]
