import os

SHARED_TOKEN = os.environ.get("AI_GATEWAY_SHARED_TOKEN", "")

MAC_SSH_HOST = os.environ.get("MAC_SSH_HOST", "")
MAC_SSH_USER = os.environ.get("MAC_SSH_USER", "")
MAC_SSH_KNOWN_HOST_LINE = os.environ.get("MAC_SSH_KNOWN_HOST_LINE", "")
MAC_SSH_KEY_PATH = os.environ.get("MAC_SSH_KEY_PATH", "/secrets/mac_ssh_key")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_ALLOWED_TOOLS = os.environ.get("CLAUDE_ALLOWED_TOOLS", "Bash,Read,Edit")
CLAUDE_PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "")

SSH_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("SSH_CONNECT_TIMEOUT_SECONDS", "15"))
