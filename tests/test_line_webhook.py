import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from routes import line_webhook  # noqa: E402


@pytest.fixture
def app():
    flask_app = Flask(__name__)
    flask_app.register_blueprint(line_webhook.line_webhook_blueprint)
    return flask_app


def test_handle_text_replies_with_kobito_status(monkeypatch):
    commands = []
    replies = []

    def fake_run(command, timeout=None):
        commands.append((command, timeout))
        return 0, "進行中\n[implementing] FEZ-111: status feature\n"

    monkeypatch.setattr(line_webhook, "run_remote_command", fake_run)
    monkeypatch.setattr(
        line_webhook, "_reply", lambda reply_token, text: replies.append((reply_token, text))
    )

    line_webhook._handle_text(
        {
            "replyToken": "reply-token",
            "message": {"type": "text", "text": " kobito状況 "},
        }
    )

    assert commands == [
        (
            "python3 ~/repos/human-agent-board/board.py "
            "status list --source kobito --recent 5",
            60,
        )
    ]
    assert replies == [
        ("reply-token", "進行中\n[implementing] FEZ-111: status feature")
    ]


def test_handle_text_ignores_unknown_command(monkeypatch):
    monkeypatch.setattr(
        line_webhook,
        "run_remote_command",
        lambda *args, **kwargs: pytest.fail("remote command must not run"),
    )
    monkeypatch.setattr(
        line_webhook,
        "_reply",
        lambda *args, **kwargs: pytest.fail("reply must not be sent"),
    )

    line_webhook._handle_text(
        {"replyToken": "reply-token", "message": {"type": "text", "text": "hello"}}
    )


def test_handle_text_reports_remote_failure(monkeypatch):
    replies = []
    monkeypatch.setattr(
        line_webhook, "run_remote_command", lambda *args, **kwargs: (1, "ssh failed")
    )
    monkeypatch.setattr(
        line_webhook, "_reply", lambda reply_token, text: replies.append((reply_token, text))
    )

    line_webhook._handle_text(
        {
            "replyToken": "reply-token",
            "message": {"type": "text", "text": "kobito status"},
        }
    )

    assert replies == [
        ("reply-token", "エラー: 状況を取得できませんでした\nssh failed")
    ]


def test_webhook_ignores_status_command_from_unauthorized_user(app, monkeypatch):
    monkeypatch.setattr(line_webhook, "_verify_signature", lambda body, signature: True)
    monkeypatch.setattr(line_webhook.config, "LINE_AUTHORIZED_USER_ID", "U-owner")
    monkeypatch.setattr(
        line_webhook,
        "_handle_text",
        lambda event: pytest.fail("unauthorized text must not be handled"),
    )

    response = app.test_client().post(
        "/line/webhook",
        json={
            "events": [
                {
                    "type": "message",
                    "replyToken": "reply-token",
                    "source": {"userId": "U-other"},
                    "message": {"type": "text", "text": "kobito状況"},
                }
            ]
        },
        headers={"X-Line-Signature": "valid"},
    )

    assert response.status_code == 200
