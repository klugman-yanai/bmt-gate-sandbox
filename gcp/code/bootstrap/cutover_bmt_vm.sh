#!/usr/bin/env bash
# Cut over a GitHub repo to a new BMT VM by updating repository variable BMT_VM_NAME.
#
# Required env vars:
#   TARGET_REPO   (e.g. klugman-yanai/bmt-gate-sandbox)
#   BMT_VM_NAME   (current/blue VM name; used only for display if variable missing)
#   BMT_GREEN_VM_NAME (target VM name; default: ${BMT_VM_NAME}-v2)
#
# Example:
#   export TARGET_REPO=klugman-yanai/bmt-gate-sandbox
#   export BMT_VM_NAME=bmt-performance-gate
#   export BMT_GREEN_VM_NAME=bmt-performance-gate-v2
#   ./remote/code/bootstrap/cutover_bmt_vm.sh

set -euo pipefail

TARGET_REPO="${TARGET_REPO:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"
BMT_GREEN_VM_NAME="${BMT_GREEN_VM_NAME:-${BMT_VM_NAME}-v2}"

if [[ -z "$TARGET_REPO" || -z "$BMT_GREEN_VM_NAME" ]]; then
  echo "Set TARGET_REPO and BMT_GREEN_VM_NAME (or BMT_VM_NAME)." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required." >&2
  exit 1
fi

current_vm="$(gh variable get BMT_VM_NAME -R "$TARGET_REPO" --json value -q .value 2>/dev/null || true)"
if [[ -z "$current_vm" ]]; then
  current_vm="$BMT_VM_NAME"
fi

echo "Cutover target repo: ${TARGET_REPO}"
echo "Current BMT_VM_NAME: ${current_vm:-<unset>}"
echo "New BMT_VM_NAME:     ${BMT_GREEN_VM_NAME}"

gh variable set BMT_VM_NAME \
  --repo "$TARGET_REPO" \
  --body "$BMT_GREEN_VM_NAME"

updated_vm="$(gh variable get BMT_VM_NAME -R "$TARGET_REPO" --json value -q .value)"
echo "Updated BMT_VM_NAME: ${updated_vm}"
