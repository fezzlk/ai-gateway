#!/usr/bin/env bash
# Deletes an ephemeral fallback VM created by spin-up-fallback-vm.sh.
# The boot disk is auto-delete, so this removes all standing cost for
# that instance — run it as soon as the task is done.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID to your GCP project}"
REGION="${REGION:-asia-northeast1}"
ZONE="${ZONE:-${REGION}-a}"
INSTANCE_NAME="${INSTANCE_NAME:?set INSTANCE_NAME to the instance to delete}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOARD_CLI="${BOARD_CLI:-$SCRIPT_DIR/../../human-agent-board/board.py}"

record_result() {
  local exit_code=$?
  local result="success"
  if (( exit_code != 0 )); then
    result="failed"
  fi
  if [[ -f "$BOARD_CLI" ]]; then
    python3 "$BOARD_CLI" vm record \
      --action delete --result "$result" --instance "$INSTANCE_NAME" \
      --project "$PROJECT_ID" --zone "$ZONE" >/dev/null || \
      echo "Warning: failed to record VM delete event in human-agent-board." >&2
  else
    echo "Warning: human-agent-board CLI not found at $BOARD_CLI; VM event was not recorded." >&2
  fi
  return "$exit_code"
}
trap record_result EXIT

gcloud compute instances delete "$INSTANCE_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --quiet

echo "Deleted $INSTANCE_NAME. Verify nothing is left running with:"
echo "  gcloud compute instances list --project=$PROJECT_ID"
