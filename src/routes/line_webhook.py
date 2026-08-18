import hashlib
import hmac
import json
import logging
import re
import shlex
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode

from flask import Blueprint, request

import config
from ssh_runner import run_remote_command

logger = logging.getLogger(__name__)

line_webhook_blueprint = Blueprint("line_webhook_blueprint", __name__)

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

_TYPE_BY_ACTION = {"approve": "approval", "reject": "rejection"}
_LABEL_BY_ACTION = {"approve": "承認", "reject": "却下"}
_DASHBOARD_COMMANDS = {"board", "ボード"}
_DECISION_COMMANDS = {"判断待ち", "decisions"}
_REQUEST_COMMANDS = {"依頼", "requests"}
_STATUS_COMMANDS = {"kobito状況", "kobito 状況", "kobito status"}
_USAGE_COMMANDS = {"利用量", "usage", "残量"}
_BOARD_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.yaml$")


def _verify_signature(body: bytes, signature: str) -> bool:
    if not config.LINE_CHANNEL_SECRET or not signature:
        return False
    digest = hmac.new(
        config.LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected = b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _reply_messages(reply_token: str, messages: list) -> None:
    if not config.LINE_CHANNEL_ACCESS_TOKEN:
        return
    payload = json.dumps(
        {"replyToken": reply_token, "messages": messages}
    ).encode("utf-8")
    req = urllib.request.Request(
        LINE_REPLY_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")
        logger.warning("failed to send LINE reply: HTTP %s: %s", e.code, details[:2000])
    except (urllib.error.URLError, OSError) as e:
        logger.warning("failed to send LINE reply: %s", e)


def _reply(reply_token: str, text: str) -> None:
    _reply_messages(reply_token, [{"type": "text", "text": text}])


def _run_board_command(arguments: str, timeout: int = 60):
    return run_remote_command(
        f"python3 ~/repos/human-agent-board/board.py {arguments}",
        timeout=timeout,
    )


def _get_dashboard():
    returncode, output = _run_board_command("dashboard --json --recent 5")
    if returncode != 0:
        raise RuntimeError(output.strip() or "board dashboard failed")
    return json.loads(output)


def _get_usage_dashboard(hours=168):
    returncode, output = _run_board_command(f"usage dashboard --hours {int(hours)}")
    if returncode != 0:
        raise RuntimeError(output.strip() or "usage dashboard failed")
    return json.loads(output)


def _postback_button(label, data, style="secondary"):
    return {
        "type": "button",
        "style": style,
        "height": "sm",
        "action": {"type": "postback", "label": label, "data": data, "displayText": label},
    }


def _uri_button(label, uri):
    parsed = urllib.parse.urlsplit(uri)
    uri = urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc.encode("idna").decode("ascii"),
        urllib.parse.quote(parsed.path, safe="/%:@-._~!$&'()*+,;="),
        urllib.parse.quote(parsed.query, safe="=&;%:@/?-._~+"),
        urllib.parse.quote(parsed.fragment, safe="-._~!$&'()*+,;=:@/?"),
    ))
    return {
        "type": "button",
        "style": "link",
        "height": "sm",
        "action": {"type": "uri", "label": label, "uri": uri},
    }


def _text(text, size="sm", weight=None, color=None, wrap=True):
    item = {"type": "text", "text": str(text), "size": size, "wrap": wrap}
    if weight:
        item["weight"] = weight
    if color:
        item["color"] = color
    return item


def _flex_message(alt_text, contents):
    return {"type": "flex", "altText": alt_text, "contents": contents}


def _truncate(value, limit):
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _dashboard_flex(data):
    current = data.get("status_current", [])
    status_preview = "\n".join(
        f"• {item.get('work_id', '?')} [{item.get('state', '?')}] {item.get('title', '')}"
        for item in current[:3]
    ) or "進行中の作業なし"
    body = {
        "type": "box",
        "layout": "vertical",
        "spacing": "md",
        "contents": [
            _text("Human Agent Board", size="xl", weight="bold"),
            _text(f"判断待ち  {len(data.get('decisions', []))}件", weight="bold", color="#D97706"),
            _text(f"通知  {len(data.get('notifications', []))}件"),
            _text(f"ユーザー依頼  {len(data.get('user_requests', []))}件"),
            _text(f"kobito進行中  {len(current)}件", weight="bold", color="#2563EB"),
            {"type": "separator"},
            _text(status_preview, size="xs", color="#4B5563"),
            _text(f"更新: {data.get('generated_at', 'unknown')}", size="xxs", color="#9CA3AF"),
        ],
    }
    footer = {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "contents": [
            _postback_button("判断待ち", "board|decisions", "primary"),
            _postback_button("依頼・通知", "board|requests"),
            _postback_button("kobito状況", "board|kobito"),
            _postback_button("AI利用量", "board|usage"),
            _postback_button("更新", "board|home"),
        ],
    }
    return _flex_message(
        "Board: 判断待ち・依頼・kobito状況",
        {"type": "bubble", "body": body, "footer": footer},
    )


def _link_buttons(item, limit=2):
    buttons = []
    for index, uri in enumerate((item.get("related_links") or [])[:limit], start=1):
        host = urllib.parse.urlparse(uri).hostname or ""
        if "github.com" in host:
            label = "GitHub"
        elif "linear.app" in host:
            label = "Linear"
        else:
            label = f"資料 {index}"
        buttons.append(_uri_button(label, uri))
    return buttons


def _item_bubble(item, decision=False):
    body = {
        "type": "box",
        "layout": "vertical",
        "spacing": "md",
        "contents": [
            _text(item.get("title") or "(no title)", size="lg", weight="bold"),
            _text(_truncate(item.get("body") or "(no details)", 1200), size="sm", color="#4B5563"),
            _text(
                f"{item.get('from', '?')} · {item.get('type', '?')} · {item.get('created_at', '?')}",
                size="xxs",
                color="#9CA3AF",
            ),
        ],
    }
    footer_contents = _link_buttons(item)
    filename = item.get("filename", "")
    if decision:
        footer_contents.extend([
            _postback_button("承認", f"board|approve|{filename}", "primary"),
            _postback_button("却下", f"board|reject|{filename}"),
        ])
    else:
        footer_contents.append(_postback_button("処理済みにする", f"board|complete|{filename}"))
    return {
        "type": "bubble",
        "body": body,
        "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": footer_contents},
    }


def _status_bubble(item):
    contents = [
        _text(f"{item.get('work_id', '?')} [{item.get('state', '?')}]", size="lg", weight="bold"),
        _text(item.get("title") or "(no title)", weight="bold"),
        _text(item.get("summary") or "(no summary)", color="#4B5563"),
    ]
    if item.get("next_action"):
        contents.append(_text(f"次: {item['next_action']}", color="#2563EB"))
    contents.append(_text(f"更新: {item.get('updated_at', '?')}", size="xxs", color="#9CA3AF"))
    return {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": contents},
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": _link_buttons(item) or [_postback_button("Boardへ戻る", "board|home")],
        },
    }


def _carousel_or_empty(title, items, bubble_builder):
    if not items:
        return _flex_message(
            title,
            {
                "type": "bubble",
                "body": {"type": "box", "layout": "vertical", "contents": [_text(f"{title}はありません。", weight="bold")]},
                "footer": {"type": "box", "layout": "vertical", "contents": [_postback_button("Boardへ戻る", "board|home")]},
            },
        )
    return _flex_message(
        title,
        {"type": "carousel", "contents": [bubble_builder(item) for item in items[:10]]},
    )


def _dashboard_section_message(section, data):
    if section == "decisions":
        return _carousel_or_empty("判断待ち", data.get("decisions", []), lambda item: _item_bubble(item, True))
    if section == "requests":
        items = data.get("notifications", []) + data.get("user_requests", [])
        return _carousel_or_empty("依頼・通知", items, _item_bubble)
    if section == "kobito":
        items = data.get("status_current", []) + data.get("status_history", [])
        return _carousel_or_empty("kobito状況", items, _status_bubble)
    return _dashboard_flex(data)


def _usage_flex(data, web_url):
    contents = [_text("AI利用量", size="xl", weight="bold")]
    for provider in ("claude", "codex"):
        item = data.get("latest", {}).get(provider)
        if not item:
            contents.append(_text(f"{provider.title()}: 取得待ち", color="#9CA3AF"))
            continue
        primary = max(0, 100 - float(item.get("primary_used", 0)))
        secondary = item.get("secondary_used")
        label = f"{provider.title()}: 5h {primary:.0f}%残"
        if secondary is not None:
            label += f" / 7d {max(0, 100 - float(secondary)):.0f}%残"
        contents.append(_text(label, weight="bold"))
        contents.append(_text(f"取得: {item.get('recorded_at', '?')}", size="xxs", color="#9CA3AF"))
    contents.extend([
        {"type": "separator"},
        _text(data.get("savings", {}).get("message", "効果測定データを蓄積中です。"), size="xs", color="#4B5563"),
    ])
    return _flex_message(
        "Claude・Codex利用量",
        {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": contents},
            "footer": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [_uri_button("詳細グラフ", web_url), _postback_button("更新", "board|usage")],
            },
        },
    )


def _handle_postback(event: dict) -> None:
    reply_token = event.get("replyToken", "")
    data = event.get("postback", {}).get("data", "")
    if data.startswith("board|"):
        _handle_board_postback(event, data)
        return

    action, _, related_link = data.partition("|")

    item_type = _TYPE_BY_ACTION.get(action)
    if not item_type or not related_link:
        logger.warning("ignoring malformed postback data: %r", data)
        return

    remote_cmd = (
        "python3 ~/repos/human-agent-board/board.py add "
        "--direction user-to-agent --from user --type "
        f"{shlex.quote(item_type)} "
        f"--title {shlex.quote(f'{_LABEL_BY_ACTION[action]} (LINE経由)')} "
        f"--body {shlex.quote(f'LINE Botから{_LABEL_BY_ACTION[action]}されました。')} "
        f"--related-link {shlex.quote(related_link)}"
    )

    try:
        returncode, output = run_remote_command(remote_cmd, timeout=60)
    except Exception as e:  # noqa: BLE001 -- must not raise inside webhook handler
        logger.exception("run_remote_command failed")
        _reply(reply_token, f"エラー: Macへの接続に失敗しました ({e})")
        return

    if returncode != 0:
        logger.warning("board.py add failed (rc=%s): %s", returncode, output)
        _reply(reply_token, f"エラー: 記録に失敗しました\n{output}".strip()[:2000])
        return

    _reply(reply_token, f"{_LABEL_BY_ACTION[action]}を記録しました。")


def _handle_board_postback(event: dict, data: str) -> None:
    reply_token = event.get("replyToken", "")
    parts = data.split("|", 2)
    action = parts[1] if len(parts) > 1 else ""

    try:
        if action == "usage":
            usage = _get_usage_dashboard()
            web_url = request.host_url.rstrip("/") + "/usage.html"
            _reply_messages(reply_token, [_usage_flex(usage, web_url)])
            return
        if action in {"home", "decisions", "requests", "kobito"}:
            dashboard = _get_dashboard()
            _reply_messages(reply_token, [_dashboard_section_message(action, dashboard)])
            return

        if action not in {"approve", "reject", "complete"} or len(parts) != 3:
            logger.warning("ignoring malformed board postback: %r", data)
            return
        filename = parts[2]
        if not _BOARD_FILENAME_RE.fullmatch(filename):
            logger.warning("ignoring invalid board filename: %r", filename)
            return

        quoted_filename = shlex.quote(filename)
        if action in {"approve", "reject"}:
            decision = "approval" if action == "approve" else "rejection"
            returncode, output = _run_board_command(
                f"respond {quoted_filename} --decision {decision}"
            )
            label = "承認" if action == "approve" else "却下"
        else:
            returncode, output = _run_board_command(f"complete {quoted_filename}")
            label = "処理済み"

        if returncode != 0:
            raise RuntimeError(output.strip() or "board action failed")
        dashboard = _get_dashboard()
        _reply_messages(
            reply_token,
            [
                {"type": "text", "text": f"{label}にしました。"},
                _dashboard_flex(dashboard),
            ],
        )
    except Exception as e:  # noqa: BLE001 -- must not raise inside webhook handler
        logger.exception("board postback failed")
        _reply(reply_token, f"エラー: Board操作に失敗しました ({e})"[:2000])


def _handle_text(event: dict) -> None:
    reply_token = event.get("replyToken", "")
    text = event.get("message", {}).get("text", "").strip()
    normalized = text.lower()
    if normalized not in (
        _DASHBOARD_COMMANDS | _DECISION_COMMANDS | _REQUEST_COMMANDS | _STATUS_COMMANDS | _USAGE_COMMANDS
    ):
        return

    try:
        if normalized in _USAGE_COMMANDS:
            usage = _get_usage_dashboard()
            web_url = request.host_url.rstrip("/") + "/usage.html"
            _reply_messages(reply_token, [_usage_flex(usage, web_url)])
            return
        dashboard = _get_dashboard()
    except Exception as e:  # noqa: BLE001 -- must not raise inside webhook handler
        logger.exception("board dashboard failed")
        _reply(reply_token, f"エラー: Boardを取得できませんでした ({e})")
        return

    if normalized in _DECISION_COMMANDS:
        section = "decisions"
    elif normalized in _REQUEST_COMMANDS:
        section = "requests"
    elif normalized in _STATUS_COMMANDS:
        section = "kobito"
    else:
        section = "home"
    _reply_messages(reply_token, [_dashboard_section_message(section, dashboard)])


@line_webhook_blueprint.route("/line/webhook", methods=["POST"])
def line_webhook():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")

    if not _verify_signature(body, signature):
        # Always 200 for anything that isn't a verified LINE request, so LINE
        # doesn't retry and no information about why is leaked to the caller.
        return "", 200

    payload = json.loads(body or b"{}")
    for event in payload.get("events", []):
        source_user_id = event.get("source", {}).get("userId")
        # Logged for every verified event (not just postback) so the
        # channel owner can find their own userId in Cloud Run logs during
        # setup -- see human-agent-board's LINE_NOTIFY_USER_ID /
        # LINE_AUTHORIZED_USER_ID setup steps.
        logger.info("verified LINE event type=%s userId=%s", event.get("type"), source_user_id)

        event_type = event.get("type")
        is_supported_text = (
            event_type == "message" and event.get("message", {}).get("type") == "text"
        )
        if event_type != "postback" and not is_supported_text:
            continue
        if not config.LINE_AUTHORIZED_USER_ID or source_user_id != config.LINE_AUTHORIZED_USER_ID:
            logger.warning("ignoring %s from unauthorized userId: %s", event_type, source_user_id)
            continue
        if event_type == "postback":
            _handle_postback(event)
        else:
            _handle_text(event)

    return "", 200
