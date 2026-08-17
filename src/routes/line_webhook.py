import hashlib
import hmac
import json
import logging
import shlex
import urllib.error
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


def _verify_signature(body: bytes, signature: str) -> bool:
    if not config.LINE_CHANNEL_SECRET or not signature:
        return False
    digest = hmac.new(
        config.LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected = b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _reply(reply_token: str, text: str) -> None:
    if not config.LINE_CHANNEL_ACCESS_TOKEN:
        return
    payload = json.dumps(
        {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
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
    except (urllib.error.URLError, OSError) as e:
        logger.warning("failed to send LINE reply: %s", e)


def _handle_postback(event: dict) -> None:
    reply_token = event.get("replyToken", "")
    data = event.get("postback", {}).get("data", "")
    action, _, related_link = data.partition("|")

    item_type = _TYPE_BY_ACTION.get(action)
    if not item_type or not related_link:
        logger.warning("ignoring malformed postback data: %r", data)
        return

    remote_cmd = (
        "python ~/repos/human-agent-board/board.py add "
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

        if event.get("type") != "postback":
            continue
        if not config.LINE_AUTHORIZED_USER_ID or source_user_id != config.LINE_AUTHORIZED_USER_ID:
            logger.warning("ignoring postback from unauthorized userId: %s", source_user_id)
            continue
        _handle_postback(event)

    return "", 200
