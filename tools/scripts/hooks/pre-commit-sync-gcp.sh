#!/usr/bin/env bash
# Pre-commit hook: if benchmarks/ changed, require that the runtime seed is in sync with GCS.
# Block commit until sync is done or SKIP_SYNC_VERIFY=1.
# Note: backend/ is baked into the Cloud Run image and is NOT synced to GCS.
set -euo pipefail
if [[ -n "${SKIP_SYNC_VERIFY:-}" ]]; then
  exit 0
fi
if [[ -z "${GCS_BUCKET:-}" ]]; then
  echo "benchmarks/ changed but GCS_BUCKET is not set; sync cannot be verified."
  echo "Set GCS_BUCKET and run: just sync-to-bucket  # same as just workspace deploy"
  echo "Or set SKIP_SYNC_VERIFY=1 to skip this check (e.g. in CI or when not using this bucket)."
  exit 1
fi
cd "$(git rev-parse --show-toplevel)"
if ! uv run python -m tools.remote.bucket_verify_runtime_seed_sync; then
  echo "benchmarks/ is out of sync with bucket; BMT workflow may fail."
  echo "Run: just sync-to-bucket  # same as just workspace deploy"
  echo "Or set SKIP_SYNC_VERIFY=1 to skip this check."
  exit 1
fi
exit 0
