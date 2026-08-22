import hmac
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, g, jsonify, redirect, request, session, url_for

import config

api_auth = Blueprint("api_auth", __name__)


def _oauth_providers():
    return {
        "google": bool(
            config.SESSION_SECRET
            and config.GOOGLE_OAUTH_CLIENT_ID
            and config.GOOGLE_OAUTH_CLIENT_SECRET
        ),
        "line": bool(
            config.SESSION_SECRET
            and config.LINE_LOGIN_CHANNEL_ID
            and config.LINE_LOGIN_CHANNEL_SECRET
        ),
    }


def _public_user(user):
    if not user:
        return None
    return {key: user.get(key) for key in ("provider", "name", "email", "picture")}


def _is_allowed(user):
    if config.ACCESS_MODE == "authenticated":
        return True
    if user["provider"] == "google":
        return bool(user.get("email")) and user["email"].lower() in config.AUTHORIZED_GOOGLE_EMAILS
    allowed_line_ids = config.AUTHORIZED_LINE_USER_IDS or {config.LINE_AUTHORIZED_USER_ID}
    return user["subject"] in allowed_line_ids


def is_private_user(user):
    """Whether an OAuth identity is explicitly trusted for owner-only data."""
    if not user:
        return False
    if user["provider"] == "google":
        return bool(user.get("email")) and user["email"].lower() in config.AUTHORIZED_GOOGLE_EMAILS
    allowed_line_ids = config.AUTHORIZED_LINE_USER_IDS or {config.LINE_AUTHORIZED_USER_ID}
    return user["subject"] in allowed_line_ids


def _line_user(profile):
    return {
        "provider": "line",
        "subject": profile["sub"],
        "user_id": f"line:{profile['sub']}",
        "name": profile.get("name") or "LINE user",
        "email": profile.get("email"),
        "picture": profile.get("picture"),
    }


def _establish_session(user):
    if not _is_allowed(user):
        return jsonify(error="this account is not allowed"), 403
    session.clear()
    session["user"] = user
    session.permanent = True
    return None


def _post_form(url, values):
    body = urllib.parse.urlencode(values).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(f"identity provider rejected the request ({error.code})") from error


def _get_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(f"identity provider rejected the request ({error.code})") from error


def _start_login(provider, authorization_url, client_id, scope):
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    session["oauth_pending"] = {"provider": provider, "state": state, "nonce": nonce}
    params = {
        "client_id": client_id,
        "redirect_uri": url_for("api_auth.oauth_callback", provider=provider, _external=True),
        "response_type": "code",
        "scope": scope,
        "state": state,
        "nonce": nonce,
    }
    return redirect(f"{authorization_url}?{urllib.parse.urlencode(params)}")


@api_auth.get("/auth/session")
def auth_session():
    providers = _oauth_providers()
    return jsonify(
        mode=config.AUTH_MODE,
        access_mode=config.ACCESS_MODE,
        authenticated=bool(session.get("user")) if config.AUTH_MODE == "oauth" else False,
        user=_public_user(session.get("user")),
        providers=providers,
        liff_id=config.LIFF_ID if providers["line"] else None,
        execution={
            "enabled": config.EXECUTION_ENABLED,
            "claude": config.CLAUDE_ENABLED,
            "codex": config.CODEX_ENABLED,
            "gcp_vm": config.GCP_VM_ENABLED,
        },
    )


@api_auth.get("/auth/login/<provider>")
def oauth_login(provider):
    if config.AUTH_MODE != "oauth" or not _oauth_providers().get(provider):
        return jsonify(error="login provider is not enabled"), 404
    if provider == "google":
        return _start_login(
            provider,
            "https://accounts.google.com/o/oauth2/v2/auth",
            config.GOOGLE_OAUTH_CLIENT_ID,
            "openid email profile",
        )
    return _start_login(
        provider,
        "https://access.line.me/oauth2/v2.1/authorize",
        config.LINE_LOGIN_CHANNEL_ID,
        "openid profile",
    )


@api_auth.get("/auth/callback/<provider>")
def oauth_callback(provider):
    pending = session.pop("oauth_pending", None)
    if (
        not pending
        or pending.get("provider") != provider
        or not request.args.get("state")
        or not hmac.compare_digest(request.args["state"], pending.get("state", ""))
    ):
        return jsonify(error="invalid OAuth state"), 400
    code = request.args.get("code")
    if not code:
        return jsonify(error=request.args.get("error", "authorization was cancelled")), 400
    redirect_uri = url_for("api_auth.oauth_callback", provider=provider, _external=True)
    try:
        if provider == "google":
            tokens = _post_form(
                "https://oauth2.googleapis.com/token",
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": config.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": config.GOOGLE_OAUTH_CLIENT_SECRET,
                },
            )
            profile = _get_json(
                "https://openidconnect.googleapis.com/v1/userinfo", tokens["access_token"]
            )
            if not profile.get("email_verified"):
                raise ValueError("Google email is not verified")
            user = {
                "provider": "google",
                "subject": profile["sub"],
                "user_id": f"google:{profile['sub']}",
                "name": profile.get("name") or profile.get("email"),
                "email": profile.get("email"),
                "picture": profile.get("picture"),
            }
        elif provider == "line":
            tokens = _post_form(
                "https://api.line.me/oauth2/v2.1/token",
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": config.LINE_LOGIN_CHANNEL_ID,
                    "client_secret": config.LINE_LOGIN_CHANNEL_SECRET,
                },
            )
            profile = _post_form(
                "https://api.line.me/oauth2/v2.1/verify",
                {
                    "id_token": tokens["id_token"],
                    "client_id": config.LINE_LOGIN_CHANNEL_ID,
                    "nonce": pending["nonce"],
                },
            )
            user = _line_user(profile)
        else:
            return jsonify(error="unknown provider"), 404
    except (KeyError, ValueError) as error:
        return jsonify(error=str(error)), 400
    denied = _establish_session(user)
    if denied:
        return denied
    return redirect("/")


@api_auth.post("/auth/liff")
def liff_login():
    if (
        config.AUTH_MODE != "oauth"
        or not _oauth_providers()["line"]
        or not config.LIFF_ID
    ):
        return jsonify(error="LIFF login is not enabled"), 404
    body = request.get_json(silent=True) or {}
    id_token = str(body.get("id_token") or "")
    if not id_token:
        return jsonify(error="id_token is required"), 400
    try:
        profile = _post_form(
            "https://api.line.me/oauth2/v2.1/verify",
            {"id_token": id_token, "client_id": config.LINE_LOGIN_CHANNEL_ID},
        )
        user = _line_user(profile)
    except (KeyError, ValueError) as error:
        return jsonify(error=str(error)), 400
    denied = _establish_session(user)
    if denied:
        return denied
    return jsonify(user=_public_user(user))


@api_auth.post("/auth/logout")
def logout():
    session.clear()
    return "", 204


@api_auth.before_app_request
def require_api_authentication():
    if not request.path.startswith("/api/"):
        return None
    if config.AUTH_MODE == "oauth":
        user = session.get("user")
        if not user:
            return jsonify(error="authentication required"), 401
        g.user_id = user["user_id"]
        g.user = user
        return None
    if config.AUTH_MODE != "shared_token":
        return jsonify(error="server authentication mode is invalid"), 500
    if not config.SHARED_TOKEN:
        return jsonify(error="server not configured"), 500
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    token = header[len(prefix):] if header.startswith(prefix) else ""
    if not hmac.compare_digest(token, config.SHARED_TOKEN):
        return jsonify(error="unauthorized"), 401
    g.user_id = "shared"
    g.user = None
    return None
