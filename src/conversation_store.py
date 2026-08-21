from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from google.cloud import firestore


def _now():
    return datetime.now(timezone.utc)


def _json_value(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _serialize(snapshot):
    data = snapshot.to_dict() or {}
    return {"id": snapshot.id, **{key: _json_value(value) for key, value in data.items()}}


class FirestoreConversationStore:
    def __init__(self, owner_id="shared", client=None):
        self.client = client or firestore.Client()
        if owner_id == "shared":
            # Preserve conversations created by the original single-user app.
            self.collection = self.client.collection("ai_gateway_conversations")
        else:
            owner_key = sha256(owner_id.encode()).hexdigest()
            self.collection = (
                self.client.collection("ai_gateway_users")
                .document(owner_key)
                .collection("conversations")
            )

    def list_conversations(self, limit=50):
        query = self.collection.order_by(
            "updated_at", direction=firestore.Query.DESCENDING
        ).limit(limit)
        return [_serialize(item) for item in query.stream()]

    def create_conversation(self, title, repo=None):
        now = _now()
        ref = self.collection.document(uuid4().hex)
        ref.set(
            {
                "title": title,
                "repo": repo,
                "session_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return _serialize(ref.get())

    def get_conversation(self, conversation_id):
        snapshot = self.collection.document(conversation_id).get()
        if not snapshot.exists:
            return None
        result = _serialize(snapshot)
        messages = snapshot.reference.collection("messages").order_by("created_at").stream()
        result["messages"] = [_serialize(message) for message in messages]
        return result

    def update_conversation(self, conversation_id, changes):
        ref = self.collection.document(conversation_id)
        if not ref.get().exists:
            return None
        ref.update({**changes, "updated_at": _now()})
        return _serialize(ref.get())

    def delete_conversation(self, conversation_id):
        ref = self.collection.document(conversation_id)
        if not ref.get().exists:
            return False
        for message in ref.collection("messages").stream():
            message.reference.delete()
        ref.delete()
        return True

    def add_message(self, conversation_id, role, content, kind="message"):
        ref = self.collection.document(conversation_id)
        if not ref.get().exists:
            return None
        now = _now()
        message_ref = ref.collection("messages").document(uuid4().hex)
        message_ref.set(
            {"role": role, "content": content, "kind": kind, "created_at": now}
        )
        ref.update({"updated_at": now})
        return _serialize(message_ref.get())
