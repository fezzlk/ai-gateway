import os

SHARED_TOKEN = os.environ.get("AI_GATEWAY_SHARED_TOKEN", "")

MAC_SSH_HOST = os.environ.get("MAC_SSH_HOST", "")
MAC_SSH_USER = os.environ.get("MAC_SSH_USER", "")
MAC_SSH_KNOWN_HOST_LINE = os.environ.get("MAC_SSH_KNOWN_HOST_LINE", "")
MAC_SSH_KEY_PATH = os.environ.get("MAC_SSH_KEY_PATH", "/secrets/mac_ssh_key")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
# One-year OAuth token from `claude setup-token`, billed against the Claude
# subscription rather than pay-per-token API usage. Must be forwarded
# explicitly into the SSH remote command's environment (SSH does not forward
# local env vars by default) — see ssh_runner.py.
CLAUDE_CODE_OAUTH_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
# Fine-grained GitHub PAT, injected the same way as CLAUDE_CODE_OAUTH_TOKEN:
# `gh auth token` (used by the GitHub MCP server) reads from the macOS
# keychain, which non-interactive SSH sessions can't reach.
GITHUB_PERSONAL_ACCESS_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
CLAUDE_ALLOWED_TOOLS = os.environ.get("CLAUDE_ALLOWED_TOOLS", "Bash,Read,Edit")
CLAUDE_PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "")

SSH_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("SSH_CONNECT_TIMEOUT_SECONDS", "15"))
