#!/usr/bin/env bash
# Audit VM filesystem and GCS bucket layout; report bloat. Config from canonical env vars.
# Requires: GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, GCS_BUCKET.
# Optional: BMT_BUCKET_PREFIX, BMT_REPO_ROOT (default /opt/bmt).
#
# Usage: set vars then run ./remote/bootstrap/audit_vm_and_bucket.sh
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=... GCS_BUCKET=...
#   ./remote/bootstrap/audit_vm_and_bucket.sh

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"
GCP_ZONE="${GCP_ZONE:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
BMT_BUCKET_PREFIX="${BMT_BUCKET_PREFIX:-}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
  echo "Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET." >&2
  exit 1
fi

BUCKET_ROOT="gs://${GCS_BUCKET}"
if [[ -n "${BMT_BUCKET_PREFIX}" ]]; then
  BUCKET_ROOT="${BUCKET_ROOT}/${BMT_BUCKET_PREFIX}"
fi

echo "=== VM filesystem audit (gcloud compute ssh) ==="
gcloud compute ssh "$BMT_VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  -- \
  "set -e; echo '--- Disk usage ---'; df -h / /opt 2>/dev/null || df -h; echo '--- Repo root ${BMT_REPO_ROOT} ---'; if [ -d '${BMT_REPO_ROOT}' ]; then ls -la '${BMT_REPO_ROOT}'; du -sh '${BMT_REPO_ROOT}'/.venv '${BMT_REPO_ROOT}'/remote 2>/dev/null || true; else echo 'Missing'; fi; echo '--- Workspace (sk_runtime) ---'; du -sh \$HOME/sk_runtime 2>/dev/null || echo 'N/A'; echo '--- Temp / large ---'; du -sh /tmp 2>/dev/null || true; echo '--- Bloat check: old trigger/cache under repo ---'; find '${BMT_REPO_ROOT}' -maxdepth 4 -type f -name '*.json' -mtime +7 2>/dev/null | head -20 || true"

echo ""
echo "=== Bucket layout (expected: triggers/runs/, sk/results/..., ci_verdicts) ==="
gcloud storage ls "$BUCKET_ROOT/" 2>/dev/null || true
echo "--- triggers/runs (run trigger JSONs; old ones are bloat) ---"
gcloud storage ls "${BUCKET_ROOT}/triggers/runs/" 2>/dev/null || echo "None or missing"
echo "--- sk/results (if present) ---"
gcloud storage ls "${BUCKET_ROOT}/sk/results/" 2>/dev/null || echo "N/A"

echo ""
echo "=== Bloat: consider removing old run triggers (keeps bucket small) ==="
echo "Example: gcloud storage rm ${BUCKET_ROOT}/triggers/runs/*.json  # or delete by age in a script"
