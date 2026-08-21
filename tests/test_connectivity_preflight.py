import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
import ssh_runner  # noqa: E402


def test_remote_preflight_parses_json(monkeypatch):
    expected = {"schema_version": 1, "overall": "DEGRADED", "checks": {}}
    monkeypatch.setattr(
        ssh_runner, "run_remote_command", lambda command, timeout: (0, json.dumps(expected))
    )
    assert ssh_runner.run_remote_preflight("agent-kit") == expected


def test_remote_preflight_invalid_output_is_blocked(monkeypatch):
    monkeypatch.setattr(
        ssh_runner, "run_remote_command", lambda command, timeout: (1, "ssh failed: secret")
    )
    payload = ssh_runner.run_remote_preflight("agent-kit")
    assert payload["overall"] == "BLOCKED"
    assert "secret" not in json.dumps(payload)


def test_remote_claude_does_not_start_when_blocked(monkeypatch):
    monkeypatch.setattr(
        ssh_runner,
        "run_remote_preflight",
        lambda repo: {"schema_version": 1, "overall": "BLOCKED", "checks": {}},
    )
    monkeypatch.setattr(
        ssh_runner.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    events = list(ssh_runner.run_remote_claude("work", repo="agent-kit"))
    assert json.loads(events[0])["type"] == "connectivity_preflight"
    assert json.loads(events[1])["type"] == "gateway_error"


def test_credentials_are_not_returned(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_PERSONAL_ACCESS_TOKEN", "github_pat_secret")
    monkeypatch.setattr(config, "LINEAR_API_KEY", "lin_api_secret")
    command = ssh_runner._with_agent_credentials("true")
    assert "github_pat_secret" in command
    assert "lin_api_secret" in command
    assert "GIT_CONFIG_KEY_0=credential.helper" in command
    assert "password=$GITHUB_PERSONAL_ACCESS_TOKEN" in command
    # The helper is command construction only; diagnostics never echo this string.
