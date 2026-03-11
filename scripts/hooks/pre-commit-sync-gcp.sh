#!/usr/bin/env bash
# Pre-commit hook: if gcp/ changed, require that gcp/ is in sync with GCS
# (code + runtime manifests). Block commit until sync is done or SKIP_SYNC_VERIFY=1.
set -euo pipefail
if [[ -n "${SKIP_SYNC_VERIFY:-}" ]]; then
  exit 0
fi
if [[ -z "${GCS_BUCKET:-}" ]]; then
  echo "gcp/ changed but GCS_BUCKET is not set; sync cannot be verified."
  echo "Set GCS_BUCKET and run: just sync-gcp && just verify-sync"
  echo "Or set SKIP_SYNC_VERIFY=1 to skip this check (e.g. in CI or when not using this bucket)."
  exit 1
fi
cd "$(git rev-parse --show-toplevel)"
code_ok=0
runtime_ok=0
if uv run python -m tools.remote.bucket_verify_gcp_sync; then
  code_ok=1
fi
if uv run python -m tools.remote.bucket_verify_runtime_seed_sync; then
  runtime_ok=1
fi

if [[ "$code_ok" -ne 1 || "$runtime_ok" -ne 1 ]]; then
  echo "gcp/ is out of sync with bucket; BMT workflow may fail (VM will accept zero legs)."
  echo "Run: just sync-gcp && just verify-sync"
  echo "Or set SKIP_SYNC_VERIFY=1 to skip this check."
  exit 1
fi
exit 0
