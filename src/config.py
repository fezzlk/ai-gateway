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
LINEAR_API_KEY = os.environ.get("LINEAR_API_KEY", "")
LINEAR_WRITE_ALLOWED = os.environ.get("LINEAR_WRITE_ALLOWED", "")
CLAUDE_ALLOWED_TOOLS = os.environ.get("CLAUDE_ALLOWED_TOOLS", "Bash,Read,Edit")
CLAUDE_PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "")

SSH_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("SSH_CONNECT_TIMEOUT_SECONDS", "15"))

# Root directory on the Mac under which per-repo `cd` targets are resolved
# (see ssh_runner.py). Matches the convention already used by the
# pico-briefing sync-repos.sh skill.
MAC_REPOS_ROOT = os.environ.get("MAC_REPOS_ROOT", "~/repos")
CONNECTIVITY_PREFLIGHT_PATH = os.environ.get(
    "CONNECTIVITY_PREFLIGHT_PATH",
    "~/repos/agent-kit/scripts/connectivity-preflight.py",
)
CONNECTIVITY_PREFLIGHT_TIMEOUT_SECONDS = int(
    os.environ.get("CONNECTIVITY_PREFLIGHT_TIMEOUT_SECONDS", "30")
)

# LINE Messaging API channel used for human-agent-board's /line/webhook route
# (see routes/line_webhook.py). LINE_CHANNEL_ACCESS_TOKEN here is only used
# to send the reply confirmation -- the push notification itself is sent
# directly from board.py on the Mac, not through this service.
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
# Fixed LINE userId allowed to trigger board.py writes via postback. Anything
# from a different userId is silently ignored -- this is the trust boundary
# that makes accepting an external webhook safe (see line_webhook.py).
LINE_AUTHORIZED_USER_ID = os.environ.get("LINE_AUTHORIZED_USER_ID", "")
