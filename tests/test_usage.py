import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
from auth import api_auth  # noqa: E402
from routes import usage  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "SHARED_TOKEN", "secret")
    flask_app = Flask(__name__)
    flask_app.register_blueprint(api_auth)
    flask_app.register_blueprint(usage.usage_blueprint)
    return flask_app


def test_usage_returns_remote_dashboard(app, monkeypatch):
    commands = []
    monkeypatch.setattr(
        usage,
        "run_remote_command",
        lambda command, timeout=60: (commands.append(command) or (0, '{"latest":{},"snapshots":[]}')),
    )
    response = app.test_client().get(
        "/api/usage?hours=168", headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 200
    assert commands == [
        "python3 ~/repos/human-agent-board/board.py usage dashboard --hours 168"
    ]


def test_usage_requires_auth(app):
    assert app.test_client().get("/api/usage").status_code == 401


def test_usage_rejects_invalid_hours(app):
    response = app.test_client().get(
        "/api/usage?hours=nope", headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 400
