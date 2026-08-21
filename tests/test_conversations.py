import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
from auth import api_auth  # noqa: E402
from routes.conversations import conversations_blueprint  # noqa: E402


class MemoryStore:
    conversations = {}
    messages = {}
    next_id = 1

    def list_conversations(self, limit=50):
        return list(self.conversations.values())[:limit]

    def create_conversation(self, title, repo=None):
        conversation_id = str(self.next_id)
        type(self).next_id += 1
        result = {
            "id": conversation_id,
            "title": title,
            "repo": repo,
            "session_id": None,
            "created_at": "2026-08-21T00:00:00+00:00",
            "updated_at": "2026-08-21T00:00:00+00:00",
        }
        self.conversations[conversation_id] = result
        self.messages[conversation_id] = []
        return result

    def get_conversation(self, conversation_id):
        value = self.conversations.get(conversation_id)
        return {**value, "messages": self.messages[conversation_id]} if value else None

    def update_conversation(self, conversation_id, changes):
        if conversation_id not in self.conversations:
            return None
        self.conversations[conversation_id].update(changes)
        return self.conversations[conversation_id]

    def delete_conversation(self, conversation_id):
        if conversation_id not in self.conversations:
            return False
        del self.conversations[conversation_id]
        del self.messages[conversation_id]
        return True

    def add_message(self, conversation_id, role, content, kind="message"):
        if conversation_id not in self.conversations:
            return None
        message = {"id": str(len(self.messages[conversation_id]) + 1), "role": role, "content": content, "kind": kind}
        self.messages[conversation_id].append(message)
        return message


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "SHARED_TOKEN", "secret")
    MemoryStore.conversations = {}
    MemoryStore.messages = {}
    MemoryStore.next_id = 1
    flask_app = Flask(__name__)
    flask_app.config["CONVERSATION_STORE_FACTORY"] = MemoryStore
    flask_app.register_blueprint(api_auth)
    flask_app.register_blueprint(conversations_blueprint)
    return flask_app


@pytest.fixture
def client(app):
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer secret"
    return client


def test_conversation_lifecycle(client):
    created = client.post("/api/conversations", json={"title": "Fix login", "repo": "web"})
    assert created.status_code == 201
    conversation_id = created.get_json()["id"]

    message = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Find the bug"},
    )
    assert message.status_code == 201

    detail = client.get(f"/api/conversations/{conversation_id}").get_json()
    assert detail["messages"][0]["content"] == "Find the bug"

    updated = client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "Login fixed", "session_id": "session-1"},
    )
    assert updated.get_json()["session_id"] == "session-1"
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404


def test_conversation_validation_and_auth(app, client):
    created = client.post("/api/conversations", json={})
    conversation_id = created.get_json()["id"]
    invalid = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "hacker", "content": "bad"},
    )
    assert invalid.status_code == 400
    assert app.test_client().get("/api/conversations").status_code == 401
