import json
import shlex
import subprocess

import pytest
from flask import Flask

import config
import ssh_runner
from routes import run_task


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_ENABLED", True)
    monkeypatch.setattr(config, "CLAUDE_ENABLED", True)
    monkeypatch.setattr(config, "CODEX_ENABLED", True)
    monkeypatch.setattr(config, "KOBITO_PROJECT_DISPATCH_ENABLED", False)
    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    return app.test_client()


def record(monkeypatch, lines):
    runs, board = [], []
    def run(*args, **kwargs):
        runs.append((args, kwargs))
        return iter(lines)
    monkeypatch.setattr(run_task, "run_remote_agent", run)
    monkeypatch.setattr(run_task, "_board_command", lambda *parts, **kwargs: (
        board.append(parts) or (0, json.dumps({"run_id": "r1"}) if "start" in parts else "{}")))
    return runs, board


CODEX = {"agent": "codex", "bin": "/usr/local/bin/codex"}


def test_codex_selection_is_passed_to_the_runner_and_recorded(client, monkeypatch):
    monkeypatch.setattr(run_task, "select_kobito_agent", lambda: CODEX)
    runs, board = record(monkeypatch, [json.dumps({"type": "turn.completed"})])
    response = client.post("/api/run", json={"source": "kobito", "prompt": "一巡"})
    body = response.get_data(as_text=True)
    assert '"agent_selected", "agent": "codex"' in body
    assert runs[0][1]["agent"] == CODEX
    start = next(parts for parts in board if "start" in parts)
    assert start[start.index("--trigger") + 1] == "cloud-scheduler/codex"
    assert any("finish" in parts and "completed" in parts for parts in board)


def test_codex_failure_is_recorded_and_never_retried_on_claude(client, monkeypatch):
    monkeypatch.setattr(run_task, "select_kobito_agent", lambda: CODEX)
    runs, board = record(monkeypatch, [json.dumps({"type": "turn.failed", "error": {"message": "usage limit"}})])
    client.post("/api/run", json={"source": "kobito", "prompt": "一巡"}).get_data()
    assert len(runs) == 1
    finish = next(parts for parts in board if "finish" in parts)
    assert "failed" in finish and "usage limit" in finish[finish.index("--summary") + 1]
    alert = next(parts for parts in board if "add" in parts)
    assert "エージェント: codex" in alert[alert.index("--body") + 1]


@pytest.mark.parametrize("failure", [ValueError("bad"), subprocess.TimeoutExpired("ssh", 15)])
def test_unavailable_agent_selection_starts_nothing(client, monkeypatch, failure):
    def select():
        raise failure
    monkeypatch.setattr(run_task, "select_kobito_agent", select)
    monkeypatch.setattr(run_task, "run_remote_agent", lambda *a, **k: pytest.fail("no run"))
    monkeypatch.setattr(run_task, "_board_command", lambda *a, **k: pytest.fail("no board"))
    assert client.post("/api/run", json={"source": "kobito", "prompt": "一巡"}).status_code == 503


def test_codex_is_refused_when_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "CODEX_ENABLED", False)
    monkeypatch.setattr(run_task, "select_kobito_agent", lambda: CODEX)
    monkeypatch.setattr(run_task, "run_remote_agent", lambda *a, **k: pytest.fail("no run"))
    assert client.post("/api/run", json={"source": "kobito", "prompt": "一巡"}).status_code == 503


def test_non_kobito_runs_do_not_ask_for_an_agent(client, monkeypatch):
    monkeypatch.setattr(run_task, "select_kobito_agent", lambda: pytest.fail("not a kobito run"))
    runs, _ = record(monkeypatch, [json.dumps({"type": "result", "result": "ok"})])
    client.post("/api/run", json={"prompt": "hello"}).get_data()
    assert "agent" not in runs[0][1]


def test_codex_command_line_is_explicit_and_quoted():
    command = shlex.split(ssh_runner.build_codex_cmdline("一巡; rm -rf /", "/usr/local/bin/codex"))
    assert command[:3] == ["/usr/local/bin/codex", "exec", "--json"]
    assert command[command.index("-s") + 1] == "danger-full-access"
    assert command[command.index("-c") + 1] == 'approval_policy="never"'
    assert command[-1] == "一巡; rm -rf /"


@pytest.mark.parametrize("output,expected", [
    ('{"agent": "claude"}', {"agent": "claude"}),
    ('{"agent": "codex", "bin": "/usr/local/bin/codex"}', CODEX),
])
def test_agent_selection_reads_the_mac_config(monkeypatch, output, expected):
    monkeypatch.setattr(ssh_runner, "run_remote_command", lambda command, timeout: (0, output))
    assert ssh_runner.select_kobito_agent() == expected


@pytest.mark.parametrize("result", [
    (1, ""), (0, "not json"), (0, '{"agent": "gpt"}'), (0, '{"agent": "codex"}'),
    (0, '{"agent": "codex", "bin": "codex"}'), (0, '{"agent": "codex", "bin": "/x/../codex"}'),
    (0, '{"agent": "codex", "bin": "/bin/codex; rm"}'),
])
def test_malformed_agent_selection_is_rejected(monkeypatch, result):
    monkeypatch.setattr(ssh_runner, "run_remote_command", lambda command, timeout: result)
    with pytest.raises(ValueError):
        ssh_runner.select_kobito_agent()


def test_remote_runner_wraps_codex_in_the_project_exec(monkeypatch):
    commands = []
    monkeypatch.setattr(ssh_runner, "run_remote_preflight", lambda repo: {"overall": "OK"})
    class Process:
        stdout = iter([])
        returncode = 0
        def wait(self):
            return 0
    monkeypatch.setattr(ssh_runner.subprocess, "Popen", lambda cmd, **kwargs: commands.append(cmd) or Process())
    list(ssh_runner.run_remote_agent("一巡", "old-session", "RJH", project_id="p-1",
                                     execution_mode="work", agent=CODEX))
    remote = commands[0][-1]
    assert "exec --project-id p-1 --repo RJH --mode work -- /usr/local/bin/codex exec --json" in remote
    assert "--resume" not in remote
