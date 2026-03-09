#!/usr/bin/env bash
# Export current VM configuration to a timestamped JSON snapshot for rollback/auditing.
# Required env vars: GCP_PROJECT, GCP_ZONE, BMT_VM_NAME
# Optional:
#   BMT_EXPORT_DIR (default: ./remote/code/bootstrap/out)
#
# Example:
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-performance-gate
#   ./remote/code/bootstrap/export_vm_spec.sh

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-}"
GCP_ZONE="${GCP_ZONE:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"
BMT_EXPORT_DIR="${BMT_EXPORT_DIR:-./remote/code/bootstrap/out}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" ]]; then
  echo "Set GCP_PROJECT, GCP_ZONE, and BMT_VM_NAME." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for export_vm_spec.sh." >&2
  exit 1
fi

mkdir -p "$BMT_EXPORT_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
json_path="${BMT_EXPORT_DIR}/${BMT_VM_NAME}-spec-${timestamp}.json"
summary_path="${BMT_EXPORT_DIR}/${BMT_VM_NAME}-spec-${timestamp}.summary.txt"

echo "Exporting VM spec for ${BMT_VM_NAME} (${GCP_PROJECT}/${GCP_ZONE})..."
gcloud compute instances describe "$BMT_VM_NAME" \
  --project="$GCP_PROJECT" \
  --zone="$GCP_ZONE" \
  --format=json >"$json_path"

jq -r '
  [
    "name=\(.name)",
    "machineType=\(.machineType | split("/") | last)",
    "status=\(.status)",
    "serviceAccount=\(.serviceAccounts[0].email // "")",
    "network=\(.networkInterfaces[0].network // "" | split("/") | last)",
    "subnetwork=\(.networkInterfaces[0].subnetwork // "" | split("/") | last)",
    "tags=\((.tags.items // []) | join(","))",
    "gcs_bucket=\((.metadata.items // [] | map(select(.key=="GCS_BUCKET")) | .[0].value) // "")",
    "bmt_repo_root=\((.metadata.items // [] | map(select(.key=="BMT_REPO_ROOT")) | .[0].value) // "")",
    "startup_script_url_set=\((.metadata.items // [] | map(select(.key=="startup-script-url")) | .[0].value // "") != "")"
  ] | .[]
' "$json_path" >"$summary_path"

echo "Wrote VM spec JSON: ${json_path}"
echo "Wrote VM summary : ${summary_path}"
