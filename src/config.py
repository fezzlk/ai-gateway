import os

SHARED_TOKEN = os.environ.get("AI_GATEWAY_SHARED_TOKEN", "")

# Web authentication. `shared_token` preserves the original single-user
# bearer-token flow. `oauth` enables whichever providers have complete
# credentials and stores the authenticated identity in a signed cookie.
AUTH_MODE = os.environ.get("AUTH_MODE", "shared_token").strip().lower()
ACCESS_MODE = os.environ.get("ACCESS_MODE", "private").strip().lower()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
LINE_LOGIN_CHANNEL_ID = os.environ.get("LINE_LOGIN_CHANNEL_ID", "")
LINE_LOGIN_CHANNEL_SECRET = os.environ.get("LINE_LOGIN_CHANNEL_SECRET", "")
LIFF_ID = os.environ.get("LIFF_ID", "")
AUTHORIZED_GOOGLE_EMAILS = {
    value.strip().lower()
    for value in os.environ.get("AUTHORIZED_GOOGLE_EMAILS", "").split(",")
    if value.strip()
}
AUTHORIZED_LINE_USER_IDS = {
    value.strip()
    for value in os.environ.get("AUTHORIZED_LINE_USER_IDS", "").split(",")
    if value.strip()
}


def _env_bool(name, default=True):
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


EXECUTION_ENABLED = _env_bool("EXECUTION_ENABLED", True)
CLAUDE_ENABLED = _env_bool("CLAUDE_ENABLED", True)
CODEX_ENABLED = _env_bool("CODEX_ENABLED", False)
GCP_VM_ENABLED = _env_bool("GCP_VM_ENABLED", False)
USAGE_PRIVATE_ONLY = _env_bool("USAGE_PRIVATE_ONLY", True)

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
HUMAN_AGENT_BOARD_CLI = os.environ.get(
    "HUMAN_AGENT_BOARD_CLI", "~/repos/human-agent-board/board.py"
)
KOBITO_HEARTBEAT_SECONDS = int(os.environ.get("KOBITO_HEARTBEAT_SECONDS", "60"))

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

# Personal Linear API key, used directly by this process (not just injected
# into SSH sessions) to call Linear's GraphQL API for the setpriority
# postback -- see line_webhook.py's _set_linear_priority().
LINEAR_API_KEY = os.environ.get("LINEAR_API_KEY", "")
# Explicit opt-in gate: the setpriority postback refuses to write to Linear
# unless this is set, even if LINEAR_API_KEY is present.
LINEAR_WRITE_ALLOWED = os.environ.get("LINEAR_WRITE_ALLOWED", "")
