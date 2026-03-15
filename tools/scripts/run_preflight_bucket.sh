#!/usr/bin/env bash
# Wrapper: set GCS_BUCKET from env or gh variable, run preflight shell script then Python diff.
# Usage: tools/scripts/run_preflight_bucket.sh   (or: just preflight-bucket)
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
cd "$REPO_ROOT"

if [[ -z "${GCS_BUCKET:-}" ]]; then
  GCS_BUCKET="$(gh variable get GCS_BUCKET 2>/dev/null)" || true
fi
export GCS_BUCKET

tools/scripts/preflight_bucket_vs_remote.sh

REPORT="$(ls -t .local/preflight-bucket-*.txt 2>/dev/null | head -1)"
if [[ -n "$REPORT" ]]; then
  uv run python tools/scripts/preflight_bucket_vs_remote.py --report "$REPORT"
else
  echo "No preflight report found; run the shell script first or check .local/" >&2
  exit 1
fi
