#!/usr/bin/env bash
# Roll back a GitHub repo to the previous/blue BMT VM by setting BMT_VM_NAME.
#
# Required env vars:
#   TARGET_REPO
#   BMT_ROLLBACK_VM_NAME (or BMT_VM_NAME as fallback)
#
# Example:
#   export TARGET_REPO=Kardome-org/core-main
#   export BMT_ROLLBACK_VM_NAME=bmt-performance-gate
#   ./remote/code/bootstrap/rollback_bmt_vm.sh

set -euo pipefail

TARGET_REPO="${TARGET_REPO:-}"
BMT_ROLLBACK_VM_NAME="${BMT_ROLLBACK_VM_NAME:-${BMT_VM_NAME:-}}"

if [[ -z "$TARGET_REPO" || -z "$BMT_ROLLBACK_VM_NAME" ]]; then
  echo "Set TARGET_REPO and BMT_ROLLBACK_VM_NAME (or BMT_VM_NAME)." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required." >&2
  exit 1
fi

current_vm="$(gh variable get BMT_VM_NAME -R "$TARGET_REPO" --json value -q .value 2>/dev/null || true)"
echo "Rollback target repo: ${TARGET_REPO}"
echo "Current BMT_VM_NAME:  ${current_vm:-<unset>}"
echo "Rollback BMT_VM_NAME: ${BMT_ROLLBACK_VM_NAME}"

gh variable set BMT_VM_NAME \
  --repo "$TARGET_REPO" \
  --body "$BMT_ROLLBACK_VM_NAME"

updated_vm="$(gh variable get BMT_VM_NAME -R "$TARGET_REPO" --json value -q .value)"
echo "Updated BMT_VM_NAME: ${updated_vm}"
