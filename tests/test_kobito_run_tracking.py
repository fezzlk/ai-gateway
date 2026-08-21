import json
import sys
from pathlib import Path

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from routes import run_task  # noqa: E402


def test_kobito_request_records_start_and_finish(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    calls = []

    def fake_board(*parts):
        calls.append(parts)
        if "start" in parts:
            return 0, json.dumps({"run_id": "run-1"})
        return 0, "{}"

    monkeypatch.setattr(run_task, "_board_command", fake_board)
    monkeypatch.setattr(
        run_task, "run_remote_claude",
        lambda *args, **kwargs: iter([json.dumps({"type": "result", "result": "done"})]),
    )

    response = app.test_client().post(
        "/api/run",
        json={"source": "kobito", "prompt": "execute one pass"},
    )
    response.get_data()

    assert any("start" in call for call in calls)
    assert any("finish" in call and "completed" in call for call in calls)


def test_kobito_gateway_error_records_failed(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    calls = []

    def fake_board(*parts):
        calls.append(parts)
        if "start" in parts:
            return 0, json.dumps({"run_id": "run-2"})
        return 0, "{}"

    monkeypatch.setattr(run_task, "_board_command", fake_board)
    monkeypatch.setattr(
        run_task, "run_remote_claude",
        lambda *args, **kwargs: iter([json.dumps({"type": "gateway_error", "message": "ssh failed"})]),
    )

    response = app.test_client().post(
        "/api/run",
        json={"prompt": "Read ~/repos/kobito/OPERATING.md and execute"},
    )
    response.get_data()

    assert any("finish" in call and "failed" in call for call in calls)
    assert any("finish" in call and "ssh failed" in call for call in calls)
    assert any("add" in call and "kobito-health" in call for call in calls)


def test_kobito_health_opens_deduplicated_action_request(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    calls = []

    def fake_board(*parts):
        calls.append(parts)
        if "list" in parts:
            return 0, json.dumps({
                "health": "degraded", "last_seen_at": "2026-08-21T00:00:00Z",
                "consecutive_failures": 4,
            })
        return 0, "{}"

    monkeypatch.setattr(run_task, "_board_command", fake_board)
    response = app.test_client().post("/api/kobito-health")

    assert response.status_code == 200
    assert response.get_json()["health"] == "degraded"
    assert any("add" in call and "kobito-health" in call for call in calls)
