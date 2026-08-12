#!/usr/bin/env bash
# Deletes an ephemeral fallback VM created by spin-up-fallback-vm.sh.
# The boot disk is auto-delete, so this removes all standing cost for
# that instance — run it as soon as the task is done.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID to your GCP project}"
REGION="${REGION:-asia-northeast1}"
ZONE="${ZONE:-${REGION}-a}"
INSTANCE_NAME="${INSTANCE_NAME:?set INSTANCE_NAME to the instance to delete}"

gcloud compute instances delete "$INSTANCE_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --quiet

echo "Deleted $INSTANCE_NAME. Verify nothing is left running with:"
echo "  gcloud compute instances list --project=$PROJECT_ID"
