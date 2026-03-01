#!/usr/bin/env bash
# Pre-commit assist hook (advisory only): if remote/ changed and GCS_BUCKET is set,
# verify remote/code and remote/runtime manifests against bucket. This hook never blocks commits.
set -euo pipefail
if [[ -z "${GCS_BUCKET:-}" ]]; then
  echo "[advisory] remote/ changed but GCS_BUCKET is not set; cannot verify bucket sync."
  echo "[advisory] run manually: just sync-remote && just verify-sync"
  exit 0
fi
cd "$(git rev-parse --show-toplevel)"
code_ok=0
runtime_ok=0
if uv run python devtools/bucket_verify_remote_sync.py; then
  code_ok=1
fi
if uv run python devtools/bucket_verify_runtime_seed_sync.py; then
  runtime_ok=1
fi

if [[ "$code_ok" -ne 1 || "$runtime_ok" -ne 1 ]]; then
  echo "[advisory] remote/ is out of sync with bucket manifests; commit is not blocked."
  echo "[advisory] run manually: just sync-remote && just verify-sync"
fi
exit 0
