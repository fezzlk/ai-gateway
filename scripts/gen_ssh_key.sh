#!/usr/bin/env bash
# One-time helper: generates the dedicated ed25519 keypair ai-gateway uses
# to SSH into your Mac. Never reuse your personal SSH key for this — a
# dedicated key can be revoked (removed from authorized_keys) without
# affecting anything else.
set -euo pipefail

OUT_DIR="${1:-./.dev-keys}"
mkdir -p "$OUT_DIR"

ssh-keygen -t ed25519 -N "" -C "ai-gateway" -f "$OUT_DIR/mac_ssh_key"

echo
echo "Public key (add this to ~/.ssh/authorized_keys on your Mac):"
cat "$OUT_DIR/mac_ssh_key.pub"
echo
echo "Private key path (upload as the MAC_SSH_PRIVATE_KEY secret in Secret Manager,"
echo "never commit it): $OUT_DIR/mac_ssh_key"
