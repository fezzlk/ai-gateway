#!/usr/bin/env bash
# Runs once per ephemeral VM boot (via instance startup-script metadata).
# Installs the tools needed for a headless Claude Code / Codex CLI session
# and clones the repos needed for the current task.
#
# Intentionally contains NO credentials or secrets: instance metadata
# (including startup-script content) is readable in plaintext by anyone
# with describe access to the instance, so auth (gh auth login, Claude/Codex
# login) must happen interactively after SSH, never here.
set -euo pipefail

# Custom metadata isn't exported as env vars on boot; fetch it from the
# metadata server instead.
TASK_REPO_URL="$(curl -fsS -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/task-repo-url" \
  2>/dev/null || true)"
WORKDIR="/opt/work"

export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y --no-install-recommends \
  git curl ca-certificates gnupg

# GitHub CLI (official apt repo)
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | dd of=/etc/apt/keyrings/githubcli-archive-keyring.gpg
chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list
apt-get update -y
apt-get install -y --no-install-recommends gh

# Docker Engine (official apt repo)
curl -fsSL https://get.docker.com | sh

# Node.js LTS (NodeSource)
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
apt-get install -y --no-install-recommends nodejs

# CLIs
npm install -g @anthropic-ai/claude-code @openai/codex

# Repos: only agent-kit (shared rules/memory pointers) + the one repo needed
# for this task. Syncing *all* repos is out of scope here (tracked as FEZ-78).
mkdir -p "$WORKDIR"
git clone https://github.com/fezzlk/agent-kit.git "$WORKDIR/agent-kit"

if [ -n "$TASK_REPO_URL" ]; then
  git clone "$TASK_REPO_URL" "$WORKDIR/task-repo"
fi

echo "startup-tools.sh: done. SSH in and run 'gh auth login' + Claude/Codex login before use."
