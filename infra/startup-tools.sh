#!/usr/bin/env bash
# Runs once per ephemeral VM boot (via instance startup-script metadata).
# Installs the tools needed for a headless Claude Code / Codex CLI session.
#
# Does NOT clone any repos, even agent-kit: repos on this GitHub account are
# private, and cloning them needs `gh auth login` first. Intentionally
# contains NO credentials or secrets either — instance metadata (including
# startup-script content) is readable in plaintext by anyone with describe
# access to the instance — so both auth and repo cloning happen
# interactively after SSH, never here. (An earlier version tried to
# git-clone agent-kit unauthenticated here; it failed outright with "could
# not read Username for 'https://github.com'" since the repo is private.)
set -euo pipefail

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

mkdir -p /opt/work

echo "startup-tools.sh: done. SSH in, run 'gh auth login', then clone whatever repos you need into /opt/work before starting Claude/Codex."
