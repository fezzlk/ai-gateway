import hmac

from flask import Blueprint, request, jsonify

import config

api_auth = Blueprint("api_auth", __name__)


@api_auth.before_app_request
def require_bearer_token():
    if not request.path.startswith("/api/"):
        return None

    if not config.SHARED_TOKEN:
        return jsonify(error="server not configured"), 500

    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    token = header[len(prefix):] if header.startswith(prefix) else ""

    if not hmac.compare_digest(token, config.SHARED_TOKEN):
        return jsonify(error="unauthorized"), 401

    return None
