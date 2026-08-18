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


@pytest.fixture
def dashboard():
    return {
        "generated_at": "2026-08-18T05:00:00Z",
        "decisions": [
            {
                "filename": "20260818T050000Z_ab12cd.yaml",
                "direction": "agent-to-user",
                "from": "kobito",
                "type": "decision_request",
                "title": "Deploy?",
                "body": "Please review the evidence.",
                "created_at": "2026-08-18T05:00:00Z",
                "related_links": [
                    "https://linear.app/example/issue/FEZ-112/example",
                    "https://github.com/example/repo/commit/abc123",
                ],
            }
        ],
        "notifications": [],
        "user_requests": [],
        "status_current": [
            {
                "work_id": "FEZ-112",
                "state": "implementing",
                "title": "Dashboard",
                "summary": "Building the LINE dashboard",
                "next_action": "Run tests",
                "updated_at": "2026-08-18T05:00:00Z",
                "related_links": [
                    "https://linear.app/example/issue/FEZ-112/example"
                ],
            }
        ],
        "status_history": [],
    }


def test_handle_text_replies_with_board_flex(monkeypatch, dashboard):
    replies = []
    monkeypatch.setattr(line_webhook, "_get_dashboard", lambda: dashboard)
    monkeypatch.setattr(
        line_webhook,
        "_reply_messages",
        lambda reply_token, messages: replies.append((reply_token, messages)),
    )

    line_webhook._handle_text(
        {"replyToken": "reply-token", "message": {"type": "text", "text": " board "}}
    )

    assert replies[0][0] == "reply-token"
    message = replies[0][1][0]
    assert message["type"] == "flex"
    assert message["altText"] == "Board: 判断待ち・依頼・kobito状況"
    assert "判断待ち  1件" in str(message)
    assert "FEZ-112" in str(message)


def test_handle_text_replies_with_kobito_section(monkeypatch, dashboard):
    replies = []
    monkeypatch.setattr(line_webhook, "_get_dashboard", lambda: dashboard)
    monkeypatch.setattr(
        line_webhook,
        "_reply_messages",
        lambda reply_token, messages: replies.append((reply_token, messages)),
    )

    line_webhook._handle_text(
        {
            "replyToken": "reply-token",
            "message": {"type": "text", "text": "kobito状況"},
        }
    )

    message = replies[0][1][0]
    assert message["type"] == "flex"
    assert message["altText"] == "kobito状況"
    assert "Building the LINE dashboard" in str(message)


def test_handle_text_ignores_unknown_command(monkeypatch):
    monkeypatch.setattr(
        line_webhook,
        "_get_dashboard",
        lambda: pytest.fail("dashboard must not be fetched"),
    )
    monkeypatch.setattr(
        line_webhook,
        "_reply_messages",
        lambda *args, **kwargs: pytest.fail("reply must not be sent"),
    )

    line_webhook._handle_text(
        {"replyToken": "reply-token", "message": {"type": "text", "text": "hello"}}
    )


def test_handle_text_reports_dashboard_failure(monkeypatch):
    replies = []
    monkeypatch.setattr(
        line_webhook, "_get_dashboard", lambda: (_ for _ in ()).throw(RuntimeError("ssh failed"))
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
        ("reply-token", "エラー: Boardを取得できませんでした (ssh failed)")
    ]


def test_board_approve_responds_and_refreshes(monkeypatch, dashboard):
    commands = []
    replies = []
    monkeypatch.setattr(
        line_webhook,
        "_run_board_command",
        lambda arguments, timeout=60: (commands.append(arguments) or (0, "response.yaml")),
    )
    monkeypatch.setattr(line_webhook, "_get_dashboard", lambda: dashboard)
    monkeypatch.setattr(
        line_webhook,
        "_reply_messages",
        lambda reply_token, messages: replies.append((reply_token, messages)),
    )

    line_webhook._handle_postback(
        {
            "replyToken": "reply-token",
            "postback": {"data": "board|approve|20260818T050000Z_ab12cd.yaml"},
        }
    )

    assert commands == [
        "respond 20260818T050000Z_ab12cd.yaml --decision approval"
    ]
    assert replies[0][1][0] == {"type": "text", "text": "承認にしました。"}
    assert replies[0][1][1]["type"] == "flex"


def test_board_complete_marks_item_complete(monkeypatch, dashboard):
    commands = []
    monkeypatch.setattr(
        line_webhook,
        "_run_board_command",
        lambda arguments, timeout=60: (commands.append(arguments) or (0, "done")),
    )
    monkeypatch.setattr(line_webhook, "_get_dashboard", lambda: dashboard)
    monkeypatch.setattr(line_webhook, "_reply_messages", lambda *args: None)

    line_webhook._handle_postback(
        {
            "replyToken": "reply-token",
            "postback": {"data": "board|complete|20260818T050000Z_ab12cd.yaml"},
        }
    )

    assert commands == ["complete 20260818T050000Z_ab12cd.yaml"]


def test_board_postback_rejects_unsafe_filename(monkeypatch):
    monkeypatch.setattr(
        line_webhook,
        "_run_board_command",
        lambda *args, **kwargs: pytest.fail("unsafe filename must not run"),
    )

    line_webhook._handle_postback(
        {
            "replyToken": "reply-token",
            "postback": {"data": "board|complete|../secret.yaml"},
        }
    )


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
                    "message": {"type": "text", "text": "board"},
                }
            ]
        },
        headers={"X-Line-Signature": "valid"},
    )

    assert response.status_code == 200
