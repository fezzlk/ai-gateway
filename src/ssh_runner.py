import json
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


def _build_ssh_cmd(remote_cmd: str) -> list:
    return [
        "ssh",
        "-o", "ProxyCommand=tailscale nc %h %p",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={config.SSH_CONNECT_TIMEOUT_SECONDS}",
        "-i", config.MAC_SSH_KEY_PATH,
        f"{config.MAC_SSH_USER}@{config.MAC_SSH_HOST}",
        remote_cmd,
    ]


def run_remote_command(remote_cmd: str, timeout: Optional[int] = None):
    """Runs an arbitrary command on the Mac over the same Tailscale SSH hop
    as run_remote_claude(), blocking until it finishes. Returns
    (returncode, combined_stdout_stderr) instead of streaming -- callers
    that just need a short command's result (e.g. `board.py add ...`) don't
    need SSE plumbing.
    """
    process = subprocess.run(
        _build_ssh_cmd(remote_cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    return process.returncode, process.stdout


def _with_agent_credentials(remote_cmd: str) -> str:
    """Inject credentials required by non-interactive agent processes.

    Values are shell-quoted and are never included in returned diagnostics.
    """
    assignments = []
    if config.GITHUB_PERSONAL_ACCESS_TOKEN:
        token = shlex.quote(config.GITHUB_PERSONAL_ACCESS_TOKEN)
        # GH_TOKEN is consumed by gh/MCP, while git itself needs a credential
        # helper in a non-interactive SSH session. Configure it per-process so
        # no token is written to disk or to the user's global git config.
        helper = shlex.quote(
            "!f() { echo username=x-access-token; "
            "echo password=$GITHUB_PERSONAL_ACCESS_TOKEN; }; f"
        )
        assignments.extend([
            f"GITHUB_PERSONAL_ACCESS_TOKEN={token}", f"GH_TOKEN={token}",
            "GIT_CONFIG_COUNT=1", "GIT_CONFIG_KEY_0=credential.helper",
            f"GIT_CONFIG_VALUE_0={helper}",
        ])
    if config.LINEAR_API_KEY:
        assignments.append(f"LINEAR_API_KEY={shlex.quote(config.LINEAR_API_KEY)}")
    if config.LINEAR_WRITE_ALLOWED:
        assignments.append(
            f"LINEAR_WRITE_ALLOWED={shlex.quote(config.LINEAR_WRITE_ALLOWED)}"
        )
    if config.CLAUDE_CODE_OAUTH_TOKEN:
        assignments.append(
            f"CLAUDE_CODE_OAUTH_TOKEN={shlex.quote(config.CLAUDE_CODE_OAUTH_TOKEN)}"
        )
    return " ".join(assignments + [remote_cmd])


def run_remote_preflight(repo: Optional[str] = None):
    repo_path = config.MAC_REPOS_ROOT if not repo else f"{config.MAC_REPOS_ROOT}/{repo}"
    command = (
        f"python3 {config.CONNECTIVITY_PREFLIGHT_PATH} --json "
        f"--repo {repo_path} --timeout 10"
    )
    returncode, output = run_remote_command(
        _with_agent_credentials(command),
        timeout=config.CONNECTIVITY_PREFLIGHT_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = {
            "schema_version": 1,
            "overall": "BLOCKED",
            "checks": {
                "preflight": {
                    "status": "BLOCKED",
                    "summary": "remote preflight did not return valid JSON",
                    "recovery": "verify agent-kit installation and remote connectivity",
                }
            },
        }
    if returncode not in (0, 2):
        payload["overall"] = "BLOCKED"
    return payload


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
    preflight = run_remote_preflight(repo)
    yield json.dumps({"type": "connectivity_preflight", **preflight})
    if preflight.get("overall") == "BLOCKED":
        yield json.dumps(
            {
                "type": "gateway_error",
                "message": "task was not started because connectivity preflight is BLOCKED",
            }
        )
        return

    remote_cmd = _with_agent_credentials(build_claude_cmdline(prompt, resume_session_id))

    if repo:
        # Not shlex.quote()'d: MAC_REPOS_ROOT defaults to "~/repos", and
        # quoting would stop the shell from tilde-expanding it. This is
        # still safe because `repo` is only reached here after
        # is_valid_repo_name() has restricted it to a charset with no shell
        # metacharacters (see _REPO_NAME_RE), and MAC_REPOS_ROOT is
        # operator-set config rather than request input.
        remote_cmd = f"cd {config.MAC_REPOS_ROOT}/{repo} && {remote_cmd}"

    process = subprocess.Popen(
        _build_ssh_cmd(remote_cmd),
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
