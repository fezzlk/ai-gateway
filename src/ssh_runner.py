import re
import shlex
import subprocess
from typing import Optional

import config

# Deliberately excludes "/" so a repo name can never resolve to more than
# one path segment below MAC_REPOS_ROOT -- there is no "../" to construct
# without a slash in the input.
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def is_valid_repo_name(repo: str) -> bool:
    return bool(_REPO_NAME_RE.match(repo))


def build_claude_cmdline(prompt: str, resume_session_id: Optional[str]) -> str:
    parts = [
        config.CLAUDE_BIN,
        "-p",
        shlex.quote(prompt),
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]

    if config.CLAUDE_ALLOWED_TOOLS:
        parts += ["--allowedTools", shlex.quote(config.CLAUDE_ALLOWED_TOOLS)]

    if config.CLAUDE_PERMISSION_MODE:
        parts += ["--permission-mode", shlex.quote(config.CLAUDE_PERMISSION_MODE)]

    if resume_session_id:
        parts += ["--resume", shlex.quote(resume_session_id)]

    return " ".join(parts)


def run_remote_claude(
    prompt: str,
    resume_session_id: Optional[str] = None,
    repo: Optional[str] = None,
):
    """Runs `claude -p ...` on the Mac over an IAP-free Tailscale SSH hop,
    yielding stdout lines as they arrive.

    `tailscale nc` (not a SOCKS/HTTP proxy) is used as the SSH ProxyCommand:
    it tunnels the single TCP connection through the container's userspace
    tailscaled with no extra client-side proxy plumbing needed.
    """
    remote_cmd = build_claude_cmdline(prompt, resume_session_id)
    if config.CLAUDE_CODE_OAUTH_TOKEN:
        # SSH does not forward local env vars to the remote command by
        # default, so the token is injected as a leading env-var assignment
        # on the remote command line instead of via `ssh -o SendEnv=`.
        remote_cmd = f"CLAUDE_CODE_OAUTH_TOKEN={shlex.quote(config.CLAUDE_CODE_OAUTH_TOKEN)} {remote_cmd}"

    if config.GITHUB_PERSONAL_ACCESS_TOKEN:
        # Same rationale as CLAUDE_CODE_OAUTH_TOKEN above: the GitHub MCP
        # server's `gh auth token` can't reach the macOS keychain over
        # non-interactive SSH, so start_github_mcp.sh picks up this
        # pre-set env var instead.
        remote_cmd = f"GITHUB_PERSONAL_ACCESS_TOKEN={shlex.quote(config.GITHUB_PERSONAL_ACCESS_TOKEN)} {remote_cmd}"

    if repo:
        # Not shlex.quote()'d: MAC_REPOS_ROOT defaults to "~/repos", and
        # quoting would stop the shell from tilde-expanding it. This is
        # still safe because `repo` is only reached here after
        # is_valid_repo_name() has restricted it to a charset with no shell
        # metacharacters (see _REPO_NAME_RE), and MAC_REPOS_ROOT is
        # operator-set config rather than request input.
        remote_cmd = f"cd {config.MAC_REPOS_ROOT}/{repo} && {remote_cmd}"

    ssh_cmd = [
        "ssh",
        "-o", "ProxyCommand=tailscale nc %h %p",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={config.SSH_CONNECT_TIMEOUT_SECONDS}",
        "-i", config.MAC_SSH_KEY_PATH,
        f"{config.MAC_SSH_USER}@{config.MAC_SSH_HOST}",
        remote_cmd,
    ]

    process = subprocess.Popen(
        ssh_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        yield line.rstrip("\n")

    process.wait()
    if process.returncode != 0:
        yield f'{{"type":"gateway_error","message":"ssh exited with code {process.returncode}"}}'
