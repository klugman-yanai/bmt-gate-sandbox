#!/usr/bin/env bash
# Pre-flight: run gcloud storage commands to check current bucket contents.
# Saves output to .local/preflight-bucket-YYYYMMDD-HHMMSS.txt for diff/review.
# Usage: GCS_BUCKET=<bucket> tools/scripts/preflight_bucket_vs_remote.sh
#   Or: GCS_BUCKET="${GCS_BUCKET:-$(gh variable get GCS_BUCKET)}" tools/scripts/...
# Requires: gcloud, GCS_BUCKET set (or use just preflight-bucket to get it from gh).
set -euo pipefail

BUCKET="${GCS_BUCKET:?Set GCS_BUCKET (e.g. export GCS_BUCKET=\$(gh variable get GCS_BUCKET))}"
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
cd "$REPO_ROOT"
mkdir -p .local
STAMP=$(date +%Y%m%d-%H%M%S)
OUT=".local/preflight-bucket-${STAMP}.txt"

{
  echo "Pre-flight bucket check: gs://${BUCKET}/"
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "---"
  echo ""
  echo "=== 1) Top-level prefixes ==="
  gcloud storage ls "gs://${BUCKET}/" 2>&1 || true
  echo ""
  echo "=== 2) All objects under code/ ==="
  gcloud storage ls -r "gs://${BUCKET}/code/" 2>&1 || true
  echo ""
  echo "=== 3) All objects under runtime/ ==="
  gcloud storage ls -r "gs://${BUCKET}/runtime/" 2>&1 || true
  echo ""
  echo "=== 4) Size/count code/ ==="
  gcloud storage du -s "gs://${BUCKET}/code/" 2>&1 || true
  echo ""
  echo "=== 5) Size/count runtime/ ==="
  gcloud storage du -s "gs://${BUCKET}/runtime/" 2>&1 || true
} > "$OUT" 2>&1

echo "Output saved to ${OUT}"
cat "$OUT"
