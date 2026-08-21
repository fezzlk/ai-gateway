from flask import Blueprint, current_app, jsonify, request

from conversation_store import FirestoreConversationStore

conversations_blueprint = Blueprint(
    "conversations_blueprint", __name__, url_prefix="/api/conversations"
)


def _store():
    factory = current_app.config.get("CONVERSATION_STORE_FACTORY", FirestoreConversationStore)
    return factory()


def _clean_text(value, max_length):
    return str(value or "").strip()[:max_length]


@conversations_blueprint.get("")
def list_conversations():
    return jsonify(conversations=_store().list_conversations())


@conversations_blueprint.post("")
def create_conversation():
    body = request.get_json(silent=True) or {}
    title = _clean_text(body.get("title"), 120) or "New conversation"
    repo = _clean_text(body.get("repo"), 120) or None
    return jsonify(_store().create_conversation(title, repo)), 201


@conversations_blueprint.get("/<conversation_id>")
def get_conversation(conversation_id):
    conversation = _store().get_conversation(conversation_id)
    if not conversation:
        return jsonify(error="conversation not found"), 404
    return jsonify(conversation)


@conversations_blueprint.patch("/<conversation_id>")
def update_conversation(conversation_id):
    body = request.get_json(silent=True) or {}
    changes = {}
    if "title" in body:
        changes["title"] = _clean_text(body["title"], 120) or "New conversation"
    if "repo" in body:
        changes["repo"] = _clean_text(body["repo"], 120) or None
    if "session_id" in body:
        changes["session_id"] = _clean_text(body["session_id"], 200) or None
    if not changes:
        return jsonify(error="no supported fields"), 400
    conversation = _store().update_conversation(conversation_id, changes)
    if not conversation:
        return jsonify(error="conversation not found"), 404
    return jsonify(conversation)


@conversations_blueprint.delete("/<conversation_id>")
def delete_conversation(conversation_id):
    if not _store().delete_conversation(conversation_id):
        return jsonify(error="conversation not found"), 404
    return "", 204


@conversations_blueprint.post("/<conversation_id>/messages")
def add_message(conversation_id):
    body = request.get_json(silent=True) or {}
    role = body.get("role")
    content = str(body.get("content") or "").strip()
    kind = body.get("kind", "message")
    if role not in {"user", "assistant", "system"}:
        return jsonify(error="invalid role"), 400
    if kind not in {"message", "error", "log"}:
        return jsonify(error="invalid kind"), 400
    if not content:
        return jsonify(error="content is required"), 400
    if len(content.encode("utf-8")) > 900_000:
        return jsonify(error="content is too long"), 413
    message = _store().add_message(conversation_id, role, content, kind)
    if not message:
        return jsonify(error="conversation not found"), 404
    return jsonify(message), 201
