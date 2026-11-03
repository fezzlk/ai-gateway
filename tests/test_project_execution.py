import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config
import ssh_runner
from routes import run_task


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_ENABLED", True)
    monkeypatch.setattr(config, "CLAUDE_ENABLED", True)
    monkeypatch.setattr(config, "KOBITO_PROJECT_DISPATCH_ENABLED", False)
    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    return app.test_client()


def test_slack_conversations_are_rejected_since_they_run_on_the_mac(client, monkeypatch):
    monkeypatch.setattr(run_task, "run_remote_claude", lambda *args, **kwargs: pytest.fail("no remote run"))
    for values in ({"source": "kobito-slack"},
                   {"source": "kobito-slack", "project_id": "project-a", "repo": "repo",
                    "execution_mode": "conversation"},
                   {"project_id": "project-a", "repo": "repo", "execution_mode": "conversation"}):
        response = client.post("/api/run", json={"prompt": "相談", **values})
        assert response.status_code == 400


def test_remote_runner_refuses_conversation_mode():
    with pytest.raises(ValueError):
        next(ssh_runner.run_remote_claude("x", None, "repo", project_id="p", execution_mode="conversation"))


def test_dispatch_no_enabled_project_does_not_start_an_ai_run(client, monkeypatch):
    monkeypatch.setattr(config, "KOBITO_PROJECT_DISPATCH_ENABLED", True)
    monkeypatch.setattr(run_task, "select_kobito_project", lambda: (0, "null"))
    monkeypatch.setattr(run_task, "run_remote_claude", lambda *args: pytest.fail("no work slot"))
    response = client.post("/api/run", json={"source": "kobito", "prompt": "定期実行"})
    assert response.status_code == 200 and b"No enabled project" in response.data
    response = client.post("/api/run", json={"prompt": "~/repos/kobito/OPERATING.mdを読んで一巡"})
    assert response.status_code == 200 and b"No enabled project" in response.data


def test_dispatch_timeout_stops_without_starting_global_work(client, monkeypatch):
    monkeypatch.setattr(config, "KOBITO_PROJECT_DISPATCH_ENABLED", True)
    def timeout():
        raise subprocess.TimeoutExpired("ssh", 15)
    monkeypatch.setattr(run_task, "select_kobito_project", timeout)
    monkeypatch.setattr(run_task, "run_remote_claude", lambda *args: pytest.fail("must stop"))
    assert client.post("/api/run", json={"source": "kobito", "prompt": "work"}).status_code == 503


@pytest.mark.parametrize("selection", [(1, "private failure"), (0, "invalid"),
                                        (0, '{"id":"p","repo":"../wrong"}')])
def test_invalid_selection_cannot_fall_back_to_global_work(client, monkeypatch, selection):
    monkeypatch.setattr(config, "KOBITO_PROJECT_DISPATCH_ENABLED", True)
    monkeypatch.setattr(run_task, "select_kobito_project", lambda: selection)
    response = client.post("/api/run", json={"source": "kobito", "prompt": "定期実行"})
    assert response.status_code == 503
    assert b"private failure" not in response.data


def test_project_id_cannot_inject_a_remote_shell_command(client):
    response = client.post("/api/run", json={"project_id": "p; echo bad", "repo": "repo", "prompt": "test"})
    assert response.status_code == 400


def test_ssh_work_uses_registered_project_executor_instead_of_arbitrary_cd(monkeypatch):
    commands = []
    class Process:
        stdout = []
        returncode = 0
        def wait(self): pass
    monkeypatch.setattr(ssh_runner, "run_remote_preflight", lambda repo: {"overall": "OK"})
    monkeypatch.setattr(ssh_runner, "_with_agent_credentials", lambda cmd: cmd)
    monkeypatch.setattr(ssh_runner.subprocess, "Popen", lambda cmd, **kwargs: (commands.append(cmd), Process())[1])
    list(ssh_runner.run_remote_claude("hello", repo="repo", project_id="project-a", execution_mode="work"))
    remote = commands[0][-1]
    assert "project_slack.py exec --project-id project-a --repo repo --mode work" in remote
    assert "cd " not in remote
