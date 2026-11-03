"""Direct Slack DM for alerts that must arrive even when the Mac is down."""

import json
import logging
import urllib.request

import config

logger = logging.getLogger(__name__)

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bot token to a redirect target.
        return None


def send_dm(text: str) -> bool:
    """Best-effort DM to SLACK_ALERT_USER_ID. Never raises; logs only the error type."""
    if not config.SLACK_BOT_TOKEN or not config.SLACK_ALERT_USER_ID:
        return False
    body = json.dumps({
        "channel": config.SLACK_ALERT_USER_ID, "text": text,
        "parse": "none", "link_names": False, "unfurl_links": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        SLACK_POST_URL, data=body,
        headers={
            "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=10) as response:
            result = json.loads(response.read())
    except Exception as error:  # noqa: BLE001 - alerting must not break the health check
        logger.warning("Slack alert failed: %s", type(error).__name__)
        return False
    if not result.get("ok"):
        logger.warning("Slack alert rejected: %s", str(result.get("error", "unknown"))[:64])
        return False
    return True
