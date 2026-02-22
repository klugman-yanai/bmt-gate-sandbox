#!/usr/bin/env bash
# Audit VM filesystem and GCS bucket layout; report bloat. All config from env (GitHub vars or gcloud).
# Requires: GCP_ZONE, VM_NAME (or BMT_VM_NAME), GCS_BUCKET; and GCP_PROJECT or GCP_SA_EMAIL.
# Optional: BMT_BUCKET_PREFIX, BMT_REPO_ROOT (default /opt/bmt).
#
# Usage: set vars then run ./remote/bootstrap/audit_vm_and_bucket.sh
#   export GCP_ZONE=europe-west4-a VM_NAME=... GCS_BUCKET=... GCP_SA_EMAIL=...
#   ./remote/bootstrap/audit_vm_and_bucket.sh

set -euo pipefail

VM_NAME="${VM_NAME:-${BMT_VM_NAME:-}}"
GCP_ZONE="${GCP_ZONE:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
BMT_BUCKET_PREFIX="${BMT_BUCKET_PREFIX:-}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"

# Derive GCP_PROJECT from GCP_SA_EMAIL (e.g. x@PROJECT.iam.gserviceaccount.com) when unset
if [[ -z "${GCP_PROJECT:-}" && -n "${GCP_SA_EMAIL:-}" ]]; then
  if [[ "${GCP_SA_EMAIL}" =~ @(.+)\.iam\.gserviceaccount\.com ]]; then
    GCP_PROJECT="${BASH_REMATCH[1]}"
  fi
fi
GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$VM_NAME" || -z "$GCS_BUCKET" ]]; then
  echo "Set GCP_ZONE, VM_NAME (or BMT_VM_NAME), GCS_BUCKET, and GCP_PROJECT or GCP_SA_EMAIL." >&2
  echo "These should come from GitHub vars or your environment." >&2
  exit 1
fi

BUCKET_ROOT="gs://${GCS_BUCKET}"
if [[ -n "${BMT_BUCKET_PREFIX}" ]]; then
  BUCKET_ROOT="${BUCKET_ROOT}/${BMT_BUCKET_PREFIX}"
fi

echo "=== VM filesystem audit (gcloud compute ssh) ==="
gcloud compute ssh "$VM_NAME" \
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
