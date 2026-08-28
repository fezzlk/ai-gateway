import json
import sys
from pathlib import Path

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
from routes import run_task  # noqa: E402


def _app():
    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    return app


def _refuse(*_args, **_kwargs):
    raise AssertionError("this executor must not run")


def test_agent_omitted_defaults_to_claude_and_still_works(monkeypatch):
    """Backward compat: callers that predate the `agent` field (FEZ-143)
    keep getting Claude without any change on their end."""
    monkeypatch.setattr(config, "CLAUDE_ENABLED", True)
    calls = []
    monkeypatch.setattr(
        run_task, "run_remote_claude",
        lambda *args, **kwargs: calls.append(("claude", args)) or iter(
            [json.dumps({"type": "result", "result": "ok"})]
        ),
    )
    monkeypatch.setattr(run_task, "run_remote_codex", _refuse)

    response = _app().test_client().post("/api/run", json={"prompt": "hello"})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert calls and calls[0][0] == "claude"
    assert '"result"' in body


def test_agent_codex_dispatches_to_codex_executor(monkeypatch):
    """Explicitly requesting codex (with CODEX_ENABLED on) routes to the
    codex executor, never claude."""
    monkeypatch.setattr(config, "CODEX_ENABLED", True)
    calls = []
    monkeypatch.setattr(run_task, "run_remote_claude", _refuse)
    monkeypatch.setattr(
        run_task, "run_remote_codex",
        lambda *args, **kwargs: calls.append(("codex", args)) or iter(
            [json.dumps({"type": "result", "result": "ok"})]
        ),
    )

    response = _app().test_client().post(
        "/api/run", json={"prompt": "hello", "agent": "codex"}
    )
    response.get_data()

    assert response.status_code == 200
    assert calls and calls[0][0] == "codex"


def test_invalid_agent_returns_400_without_executing(monkeypatch):
    monkeypatch.setattr(run_task, "run_remote_claude", _refuse)
    monkeypatch.setattr(run_task, "run_remote_codex", _refuse)
    monkeypatch.setattr(run_task, "_board_command", _refuse)

    response = _app().test_client().post(
        "/api/run", json={"prompt": "hello", "agent": "gemini"}
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_disabled_agent_returns_400_without_executing(monkeypatch):
    monkeypatch.setattr(config, "CODEX_ENABLED", False)
    monkeypatch.setattr(run_task, "run_remote_claude", _refuse)
    monkeypatch.setattr(run_task, "run_remote_codex", _refuse)
    monkeypatch.setattr(run_task, "_board_command", _refuse)

    response = _app().test_client().post(
        "/api/run", json={"prompt": "hello", "agent": "codex"}
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_executor_failure_does_not_fall_back_to_other_agent(monkeypatch):
    """A gateway_error from the resolved agent's executor must not trigger
    a same-run retry with the other agent -- per the ai-gateway agent
    boundary decision record, a failed run is reported and re-run later
    with an agent explicitly chosen again, never silently switched
    mid-run."""
    monkeypatch.setattr(config, "CLAUDE_ENABLED", True)
    codex_calls = []
    monkeypatch.setattr(
        run_task, "run_remote_claude",
        lambda *args, **kwargs: iter(
            [json.dumps({"type": "gateway_error", "message": "boom"})]
        ),
    )
    monkeypatch.setattr(
        run_task, "run_remote_codex",
        lambda *args, **kwargs: codex_calls.append(args) or iter([]),
    )

    response = _app().test_client().post("/api/run", json={"prompt": "hello"})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "gateway_error" in body
    assert codex_calls == []
