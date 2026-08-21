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
        "kobito_run": {
            "health": "degraded",
            "last_seen_at": "2026-08-18T05:00:00Z",
            "consecutive_failures": 3,
            "latest": {"summary": "GitHub push authentication failed"},
        },
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
    assert "障害継続中" in str(message)
    assert "連続失敗: 3回" in str(message)


def test_handle_text_replies_with_usage_flex(app, monkeypatch):
    replies = []
    usage = {
        "latest": {"codex": {"primary_used": 23, "recorded_at": "2026-08-18T12:00:00Z"}},
        "snapshots": [], "tasks": [],
        "savings": {"message": "データを蓄積中です。"},
    }
    monkeypatch.setattr(line_webhook, "_get_usage_dashboard", lambda: usage)
    monkeypatch.setattr(
        line_webhook, "_reply_messages",
        lambda reply_token, messages: replies.append((reply_token, messages)),
    )

    with app.test_request_context("/line/webhook", base_url="https://gateway.example"):
        line_webhook._handle_text(
            {"replyToken": "reply-token", "message": {"type": "text", "text": "利用量"}}
        )

    message = replies[0][1][0]
    assert message["type"] == "flex"
    assert "Codex: 5h 77%残" in str(message)
    assert "usage.html" in str(message)


def test_handle_text_replies_with_vm_history(monkeypatch):
    replies = []
    history = [{
        "action": "create",
        "result": "success",
        "instance": "ai-gateway-fallback-20260818-120000",
        "project": "sample-project",
        "zone": "asia-northeast1-a",
        "recorded_at": "2026-08-18T03:00:00Z",
    }]
    monkeypatch.setattr(line_webhook, "_get_vm_history", lambda: history)
    monkeypatch.setattr(
        line_webhook, "_reply_messages",
        lambda reply_token, messages: replies.append((reply_token, messages)),
    )

    line_webhook._handle_text(
        {"replyToken": "reply-token", "message": {"type": "text", "text": "VM履歴"}}
    )

    message = replies[0][1][0]
    assert message["type"] == "flex"
    assert message["altText"] == "GCP VM起動・停止履歴"
    assert "起動（作成） · 成功" in str(message)
    assert "ai-gateway-fallback-20260818-120000" in str(message)


def test_board_vm_postback_replies_with_history(monkeypatch):
    replies = []
    monkeypatch.setattr(line_webhook, "_get_vm_history", lambda: [])
    monkeypatch.setattr(
        line_webhook, "_reply_messages",
        lambda reply_token, messages: replies.append((reply_token, messages)),
    )

    line_webhook._handle_postback(
        {"replyToken": "reply-token", "postback": {"data": "board|vm"}}
    )

    assert "記録された操作はありません。" in str(replies[0][1][0])


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


def test_item_bubble_encodes_unicode_links_and_truncates_body():
    bubble = line_webhook._item_bubble(
        {
            "filename": "item.yaml",
            "title": "title",
            "body": "長" * 2500,
            "related_links": ["https://linear.app/team/issue/FEZ-1/日本語 slug"],
        },
        decision=True,
    )

    body_text = bubble["body"]["contents"][1]["text"]
    link = bubble["footer"]["contents"][0]["action"]["uri"]
    assert len(body_text) == 1200
    assert body_text.endswith("…")
    assert "日本語" not in link
    assert "%E6%97%A5" in link
    assert "%20" in link

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
