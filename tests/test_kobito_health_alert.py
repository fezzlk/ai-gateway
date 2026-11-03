import io
import json
import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
import slack_alert  # noqa: E402
from routes import run_task  # noqa: E402


@pytest.fixture
def health(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    board, dms = [], []

    def call(result):
        monkeypatch.setattr(run_task, "_board_command", lambda *parts, **kwargs: (
            board.append((parts, kwargs)) or (result if parts[0] == "run" else (0, ""))))
        monkeypatch.setattr(run_task, "send_dm", lambda text: dms.append(text))
        return app.test_client().post("/api/kobito-health")

    return call, board, dms


def test_unreachable_mac_is_reported_by_direct_dm(health):
    call, board, dms = health
    response = call((255, ""))
    assert response.status_code == 503
    assert len(dms) == 1 and "Macに接続できません" in dms[0]


def test_invalid_board_response_is_reported_by_dm(health):
    call, _, dms = health
    assert call((0, "not json")).status_code == 503
    assert len(dms) == 1


def test_stale_run_records_silently_on_board_and_sends_dm(health):
    call, board, dms = health
    call((0, json.dumps({"health": "stale", "last_seen_at": "2026-11-03T00:00:00Z"})))
    add = [entry for entry in board if entry[0][0] == "add"]
    assert len(add) == 1 and add[0][1] == {"notify": False}
    assert len(dms) == 1 and "stale" in dms[0]


def test_healthy_resolves_without_dm(health):
    call, board, dms = health
    call((0, json.dumps({"health": "healthy"})))
    assert any(entry[0][0] == "resolve" for entry in board)
    assert dms == []


def test_silent_board_command_disables_board_notification(monkeypatch):
    commands = []
    monkeypatch.setattr(run_task, "run_remote_command", lambda command, timeout: commands.append(command))
    run_task._board_command("add", "--title", "x", notify=False)
    run_task._board_command("resolve")
    assert commands[0].startswith("HUMAN_AGENT_NOTIFICATION_BACKEND=none python3 ")
    assert commands[1].startswith("python3 ")


def test_send_dm_is_noop_without_configuration(monkeypatch):
    monkeypatch.setattr(config, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(config, "SLACK_ALERT_USER_ID", "U1")
    monkeypatch.setattr(slack_alert.urllib.request, "build_opener", lambda *a: pytest.fail("no request"))
    assert slack_alert.send_dm("x") is False


def configure(monkeypatch, opener):
    monkeypatch.setattr(config, "SLACK_BOT_TOKEN", "xoxb-test-secret")
    monkeypatch.setattr(config, "SLACK_ALERT_USER_ID", "U123")
    def build_opener(handler):
        assert handler.redirect_request(None, None, 302, "", {}, "https://other.example") is None
        return opener
    monkeypatch.setattr(slack_alert.urllib.request, "build_opener", build_opener)


def test_send_dm_posts_to_the_alert_user(monkeypatch):
    sent = []
    class Opener:
        def open(self, request, timeout):
            sent.append(request)
            return io.BytesIO(b'{"ok": true}')
    configure(monkeypatch, Opener())
    assert slack_alert.send_dm("停止") is True
    assert sent[0].full_url == "https://slack.com/api/chat.postMessage"
    assert json.loads(sent[0].data)["channel"] == "U123"


@pytest.mark.parametrize("behaviour", ["raise", "not_ok"])
def test_send_dm_failure_never_raises_or_logs_the_token(monkeypatch, caplog, behaviour):
    class Opener:
        def open(self, request, timeout):
            if behaviour == "raise":
                raise OSError("boom xoxb-test-secret")
            return io.BytesIO(b'{"ok": false, "error": "channel_not_found"}')
    configure(monkeypatch, Opener())
    assert slack_alert.send_dm("停止") is False
    assert "xoxb-test-secret" not in caplog.text
