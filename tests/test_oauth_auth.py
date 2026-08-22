import sys
from pathlib import Path

import pytest
from flask import Flask, g, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import auth  # noqa: E402
import config  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "oauth")
    monkeypatch.setattr(config, "ACCESS_MODE", "authenticated")
    monkeypatch.setattr(config, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", "google-id")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr(config, "LINE_LOGIN_CHANNEL_ID", "line-id")
    monkeypatch.setattr(config, "LINE_LOGIN_CHANNEL_SECRET", "line-secret")
    monkeypatch.setattr(config, "LIFF_ID", "123-liff-id")
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.config.update(SESSION_COOKIE_SECURE=False, TESTING=True)
    flask_app.register_blueprint(auth.api_auth)

    @flask_app.get("/api/whoami")
    def whoami():
        return jsonify(user_id=g.user_id)

    return flask_app


def test_oauth_api_requires_session(app):
    assert app.test_client().get("/api/whoami").status_code == 401


def test_auth_session_lists_configured_providers(app):
    payload = app.test_client().get("/auth/session").get_json()
    assert payload["providers"] == {"google": True, "line": True}
    assert payload["liff_id"] == "123-liff-id"
    assert payload["authenticated"] is False


def test_authenticated_session_sets_scoped_user(app):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user"] = {
            "provider": "google",
            "subject": "123",
            "user_id": "google:123",
            "name": "Test User",
            "email": "test@example.com",
        }
    assert client.get("/api/whoami").get_json()["user_id"] == "google:123"
    session_payload = client.get("/auth/session").get_json()
    assert session_payload["user"]["email"] == "test@example.com"


def test_google_callback_verifies_state_and_creates_session(app, monkeypatch):
    monkeypatch.setattr(
        auth,
        "_post_form",
        lambda url, values: {"access_token": "access-token"},
    )
    monkeypatch.setattr(
        auth,
        "_get_json",
        lambda url, token: {
            "sub": "google-user",
            "email": "user@example.com",
            "email_verified": True,
            "name": "User",
        },
    )
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["oauth_pending"] = {
            "provider": "google",
            "state": "expected-state",
            "nonce": "expected-nonce",
        }
    response = client.get(
        "/auth/callback/google?state=expected-state&code=authorization-code"
    )
    assert response.status_code == 302
    assert client.get("/api/whoami").get_json()["user_id"] == "google:google-user"


def test_private_mode_rejects_unlisted_google_account(app, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_MODE", "private")
    monkeypatch.setattr(config, "AUTHORIZED_GOOGLE_EMAILS", {"owner@example.com"})
    monkeypatch.setattr(auth, "_post_form", lambda url, values: {"access_token": "token"})
    monkeypatch.setattr(
        auth,
        "_get_json",
        lambda url, token: {
            "sub": "stranger",
            "email": "stranger@example.com",
            "email_verified": True,
        },
    )
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["oauth_pending"] = {
            "provider": "google",
            "state": "state",
            "nonce": "nonce",
        }
    assert client.get("/auth/callback/google?state=state&code=code").status_code == 403


def test_liff_id_token_creates_same_line_session(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        auth,
        "_post_form",
        lambda url, values: (
            calls.append((url, values))
            or {"sub": "line-user", "name": "LINE User", "picture": "https://example.com/p.png"}
        ),
    )
    client = app.test_client()
    response = client.post("/auth/liff", json={"id_token": "signed-id-token"})
    assert response.status_code == 200
    assert calls == [
        (
            "https://api.line.me/oauth2/v2.1/verify",
            {"id_token": "signed-id-token", "client_id": "line-id"},
        )
    ]
    assert client.get("/api/whoami").get_json()["user_id"] == "line:line-user"


def test_liff_login_rejects_missing_token(app):
    assert app.test_client().post("/auth/liff", json={}).status_code == 400
