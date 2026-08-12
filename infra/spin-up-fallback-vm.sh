#!/usr/bin/env bash
# Creates a fresh, ephemeral GCP Compute Engine VM to use as a fallback
# execution environment when Claude/Codex can't run locally (e.g. Mac
# unreachable via Tailscale).
#
# Ephemeral by design: this script creates a NEW instance every time it's
# run, with a minimal boot disk that is auto-deleted along with the
# instance. There is no persistent, always-on environment — run
# teardown-fallback-vm.sh when the task is done so nothing keeps billing.
#
# Required one-time setup (see README.md): a GCP project with Compute
# Engine enabled, billing linked, and a firewall rule allowing SSH only
# from the IAP range (35.235.240.0/20).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID to your GCP project}"
REGION="${REGION:-asia-northeast1}"
ZONE="${ZONE:-${REGION}-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
DISK_SIZE_GB="${DISK_SIZE_GB:-10}"
INSTANCE_NAME="${INSTANCE_NAME:-ai-gateway-fallback-$(date +%Y%m%d-%H%M%S)}"
IMAGE_FAMILY="${IMAGE_FAMILY:-ubuntu-2404-lts-amd64}"
IMAGE_PROJECT="${IMAGE_PROJECT:-ubuntu-os-cloud}"
TASK_REPO_URL="${TASK_REPO_URL:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

gcloud compute instances create "$INSTANCE_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --image-family="$IMAGE_FAMILY" \
  --image-project="$IMAGE_PROJECT" \
  --boot-disk-size="${DISK_SIZE_GB}GB" \
  --boot-disk-type=pd-balanced \
  --boot-disk-auto-delete \
  --no-address \
  --metadata-from-file=startup-script="$SCRIPT_DIR/startup-tools.sh" \
  --metadata=task-repo-url="$TASK_REPO_URL"

echo "Created $INSTANCE_NAME in $PROJECT_ID/$ZONE."
echo "Tool install takes a few minutes; then connect with:"
echo "  gcloud compute ssh $INSTANCE_NAME --project=$PROJECT_ID --zone=$ZONE --tunnel-through-iap"
echo "When done, tear it down with:"
echo "  PROJECT_ID=$PROJECT_ID ZONE=$ZONE INSTANCE_NAME=$INSTANCE_NAME ./teardown-fallback-vm.sh"
