#!/usr/bin/env python3
"""Create or reuse the human-agent-board LINE rich menu and make it default."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.line.me/v2/bot"
DATA_API_BASE = "https://api-data.line.me/v2/bot"
MENU_NAME = "human-agent-board"


def request(token, method, url, data=None, content_type="application/json"):
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LINE API {error.code}: {details}") from error
    return json.loads(body) if body else {}


def menu_definition():
    return {
        "size": {"width": 2500, "height": 843},
        "selected": True,
        "name": MENU_NAME,
        "chatBarText": "Board",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "board"},
            },
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {"type": "message", "text": "判断待ち"},
            },
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "kobito状況"},
            },
        ],
    }


def find_or_create_menu(token):
    existing = request(token, "GET", f"{API_BASE}/richmenu/list").get("richmenus", [])
    match = next((menu for menu in existing if menu.get("name") == MENU_NAME), None)
    if match:
        return match["richMenuId"], False
    payload = json.dumps(menu_definition()).encode("utf-8")
    result = request(token, "POST", f"{API_BASE}/richmenu", payload)
    return result["richMenuId"], True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="2500x843 PNG rich-menu image")
    args = parser.parse_args()

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        parser.error("LINE_CHANNEL_ACCESS_TOKEN is required")
    if not args.image.is_file():
        parser.error(f"image not found: {args.image}")

    menu_id, created = find_or_create_menu(token)
    request(
        token,
        "POST",
        f"{DATA_API_BASE}/richmenu/{menu_id}/content",
        args.image.read_bytes(),
        "image/png",
    )
    request(token, "POST", f"{API_BASE}/user/all/richmenu/{menu_id}")
    print(json.dumps({"richMenuId": menu_id, "created": created, "default": True}))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
