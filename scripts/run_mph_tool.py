"""Single-command launcher for ``mph_tool.py``.

The launcher owns sim-cli session discovery, health checking, temporary config
injection, and cleanup of sessions it creates. It never stops or disconnects a
session that existed before the command started.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, NamedTuple

MPH_TOOL_PATH = Path(__file__).resolve().with_name("mph_tool.py")
MPH_TOOL_SPEC = importlib.util.spec_from_file_location("mph_tool", MPH_TOOL_PATH)
if MPH_TOOL_SPEC is None or MPH_TOOL_SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MPH_TOOL_PATH}")
mph_tool = importlib.util.module_from_spec(MPH_TOOL_SPEC)
MPH_TOOL_SPEC.loader.exec_module(mph_tool)


SIM_PREFIX = [
    "uvx",
    "--from",
    "sim-cli-core==0.3.7",
    "--with",
    "sim-plugin-comsol==0.1.14",
    "sim",
]
if os.environ.get("COMSOL_SIM_COMMAND"):
    SIM_PREFIX = json.loads(os.environ["COMSOL_SIM_COMMAND"])
    if not isinstance(SIM_PREFIX, list) or not all(isinstance(item, str) for item in SIM_PREFIX):
        raise RuntimeError("COMSOL_SIM_COMMAND must be a JSON array of command tokens")
MODEL_ACTIONS = {"audit", "patch", "verify", "smoke"}


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise RuntimeError(f"sim-cli did not return JSON: {text[-500:]}")
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("sim-cli JSON response must be an object")
    return value


class SessionLease(NamedTuple):
    session_id: str
    created: bool


class SimClient:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run):
        self._runner = runner

    def _call(self, *args: str, session: str | None = None, timeout: float | None = None) -> dict[str, Any]:
        command = [*SIM_PREFIX, "--json"]
        if session:
            command.extend(["--session", session])
        command.extend(["--no-interactive", *args])
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"sim-cli command timed out after {timeout}s: {' '.join(command)}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"sim-cli command failed ({' '.join(command)}): {detail}")
        return _parse_json(completed.stdout)

    def list_sessions(self) -> dict[str, Any]:
        return self._call("ps", timeout=20)

    def is_healthy(self, session_id: str) -> bool:
        try:
            self._call("exec", "print('MPH_SESSION_HEALTHY')", session=session_id, timeout=30)
            return True
        except RuntimeError:
            return False

    def connect(self) -> str:
        result = self._call("connect", "--solver", "comsol", "--ui-mode", "no_gui", timeout=180)
        session_id = result.get("session_id")
        if not session_id and isinstance(result.get("session"), dict):
            session_id = result["session"].get("session_id")
        if not session_id:
            sessions = self.list_sessions().get("sessions", [])
            session_id = next(
                (item.get("session_id") for item in sessions if item.get("solver") == "comsol"),
                None,
            )
        if not session_id:
            raise RuntimeError("COMSOL connected but sim-cli returned no session id")
        return str(session_id)

    def ensure_session(self) -> SessionLease:
        errors: list[str] = []
        snapshot: dict[str, Any] = {}
        try:
            snapshot = self.list_sessions()
            sessions = snapshot.get("sessions", [])
        except RuntimeError as exc:
            sessions = []
            errors.append(str(exc))
        default_session = snapshot.get("default_session")
        sessions = sorted(sessions, key=lambda item: item.get("session_id") != default_session)
        for item in sessions:
            session_id = item.get("session_id")
            if item.get("solver") == "comsol" and session_id and self.is_healthy(str(session_id)):
                return SessionLease(str(session_id), created=False)
        try:
            return SessionLease(self.connect(), created=True)
        except RuntimeError as exc:
            errors.append(str(exc))
            detail = "\n".join(errors)
            raise RuntimeError(
                "Unable to obtain a healthy COMSOL session. The launcher will not kill an "
                "unknown server or process automatically. Inspect `uv run sim --json ps` and "
                f"the process owner before cleanup.\n{detail}"
            ) from exc

    def exec_file(self, session_id: str, script: Path) -> dict[str, Any]:
        return self._call("exec", "--file", str(script), session=session_id)

    def disconnect(self, session_id: str) -> None:
        self._call("disconnect", session=session_id)


def _bootstrap_text(config_path: Path, tool_path: Path) -> str:
    config_literal = json.dumps(str(config_path), ensure_ascii=False)
    tool_literal = json.dumps(str(tool_path), ensure_ascii=False)
    return (
        f"MPH_TOOL_CONFIG = {config_literal}\n"
        f"_mph_tool_path = {tool_literal}\n"
        "with open(_mph_tool_path, encoding='utf-8') as _handle:\n"
        "    exec(compile(_handle.read(), _mph_tool_path, 'exec'), globals())\n"
    )


def execute(config_path: Path, client: SimClient, keep_created_session: bool = False) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mph_tool.validate_config(config)
    if config["action"] == "diff":
        return mph_tool.run(config)
    if config["action"] not in MODEL_ACTIONS:
        raise ValueError(f"Unsupported model action: {config['action']}")

    lease = client.ensure_session()
    tool_path = Path(__file__).with_name("mph_tool.py").resolve()
    bootstrap = config_path.parent / f".{config_path.stem}.mph_exec.py"
    manifest = config_path.parent / f"{config_path.stem}.session.json"
    bootstrap.write_text(_bootstrap_text(config_path, tool_path), encoding="utf-8")
    manifest_payload: dict[str, Any] = {
        "session_id": lease.session_id,
        "created_by_launcher": lease.created,
        "action": config["action"],
        "config": str(config_path),
        "status": "running",
    }
    manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    operation_error: Exception | None = None
    try:
        result = client.exec_file(lease.session_id, bootstrap)
        manifest_payload["status"] = "completed"
        return result
    except Exception as exc:
        operation_error = exc
        manifest_payload["status"] = "failed"
        manifest_payload["error"] = str(exc)
        raise
    finally:
        bootstrap.unlink(missing_ok=True)
        if lease.created and not keep_created_session:
            try:
                client.disconnect(lease.session_id)
                manifest_payload["created_session_disconnected"] = True
            except RuntimeError as exc:
                manifest_payload["cleanup_error"] = str(exc)
                if operation_error is None:
                    raise
        manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="UTF-8 mph_tool JSON config")
    parser.add_argument("--keep-created-session", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate config without contacting sim-cli")
    args = parser.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    mph_tool.validate_config(config)
    if args.dry_run:
        print(json.dumps({"ok": True, "action": config["action"], "dry_run": True}, ensure_ascii=False))
        return 0
    execute(args.config, SimClient(), args.keep_created_session)
    print(json.dumps({"ok": True, "action": config["action"], "output": config.get("output")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
