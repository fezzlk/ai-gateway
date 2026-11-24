"""scripts/start.sh joins the tailnet with either kind of Tailscale credential.

The script is sourced with START_SH_FUNCTIONS_ONLY so that only `tailscale_up`
is defined, and `tailscale` is replaced by a stub that records its arguments.
No real Tailscale binary or network is involved.
"""
import os
import subprocess
from pathlib import Path

START_SH = Path(__file__).resolve().parent.parent / "scripts" / "start.sh"

STUB = """#!/bin/sh
for arg in "$@"; do
  printf '%s\\n' "$arg"
done
"""


def run_tailscale_up(tmp_path, authkey, **extra_env):
    stub = tmp_path / "tailscale-stub"
    stub.write_text(STUB)
    stub.chmod(0o755)
    env = {
        "PATH": os.environ["PATH"],
        "START_SH_FUNCTIONS_ONLY": "1",
        "TAILSCALE_BIN": str(stub),
        "TAILSCALE_AUTHKEY": authkey,
    }
    env.update(extra_env)
    result = subprocess.run(
        ["sh", "-c", f". {START_SH} && tailscale_up"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def test_script_is_valid_sh():
    subprocess.run(["sh", "-n", str(START_SH)], check=True)


def test_regular_auth_key_is_passed_unchanged(tmp_path):
    args = run_tailscale_up(tmp_path, "tskey-auth-abc123-secret")

    assert args == [
        "up",
        "--auth-key=tskey-auth-abc123-secret",
        "--hostname=ai-gateway-cloudrun",
        "--ssh=false",
    ]


def test_oauth_client_secret_gets_tags_and_registration_options(tmp_path):
    args = run_tailscale_up(tmp_path, "tskey-client-abc123-secret")

    assert args == [
        "up",
        "--auth-key=tskey-client-abc123-secret?ephemeral=true&preauthorized=true",
        "--advertise-tags=tag:ai-gateway",
        "--hostname=ai-gateway-cloudrun",
        "--ssh=false",
    ]


def test_oauth_client_secret_honours_tag_and_hostname_overrides(tmp_path):
    args = run_tailscale_up(
        tmp_path,
        "tskey-client-abc123-secret",
        TAILSCALE_TAGS="tag:example,tag:other",
        TAILSCALE_HOSTNAME="custom-host",
    )

    assert "--advertise-tags=tag:example,tag:other" in args
    assert "--hostname=custom-host" in args


def test_regular_auth_key_ignores_tags(tmp_path):
    args = run_tailscale_up(tmp_path, "tskey-auth-abc123-secret", TAILSCALE_TAGS="tag:x")

    assert not any(arg.startswith("--advertise-tags") for arg in args)
