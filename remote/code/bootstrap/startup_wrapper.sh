#!/usr/bin/env bash
# Startup wrapper loaded from VM metadata startup-script.
# It materializes BMT_REPO_ROOT from GCS code namespace, then executes startup_example.sh.
set -euo pipefail

_read_meta() {
  local key="$1"
  curl -sSf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/${key}" 2>/dev/null || true
}

_object_exists() {
  local uri="$1"
  gcloud storage ls "$uri" >/dev/null 2>&1
}

_rsync_with_retry() {
  local src="$1"
  local dest="$2"
  local attempts=5
  local delay=2
  local attempt
  for attempt in $(seq 1 "$attempts"); do
    if gcloud storage rsync --recursive "${src}/" "${dest}" --quiet; then
      return 0
    fi
    if [[ "$attempt" -lt "$attempts" ]]; then
      echo "::warning::Code sync attempt ${attempt}/${attempts} failed; retrying in ${delay}s." >&2
      sleep "$delay"
      delay=$((delay * 2))
    fi
  done
  return 1
}

export GCS_BUCKET="${GCS_BUCKET:-$(_read_meta "GCS_BUCKET")}"
export BMT_REPO_ROOT="${BMT_REPO_ROOT:-$(_read_meta "BMT_REPO_ROOT")}"

GCS_BUCKET="${GCS_BUCKET:?Set metadata GCS_BUCKET}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
CODE_ROOT="gs://${GCS_BUCKET}/code"
BOOTSTRAP_REL="bootstrap/startup_example.sh"

export GCS_BUCKET BMT_REPO_ROOT

if ! command -v gcloud >/dev/null 2>&1; then
  echo "::error::gcloud CLI not found on VM; bootstrap cannot sync code." >&2
  exit 1
fi

if ! _object_exists "${CODE_ROOT}/${BOOTSTRAP_REL}"; then
  echo "::error::Missing bootstrap at ${CODE_ROOT}/${BOOTSTRAP_REL}" >&2
  echo "::error::Sync code mirror first (just sync-remote && just verify-sync)." >&2
  exit 1
fi

mkdir -p "${BMT_REPO_ROOT}"
echo "Syncing code namespace ${CODE_ROOT}/ -> ${BMT_REPO_ROOT}/"
if ! _rsync_with_retry "${CODE_ROOT}" "${BMT_REPO_ROOT}"; then
  echo "::error::Failed to sync ${CODE_ROOT}/ to ${BMT_REPO_ROOT} after retries." >&2
  exit 1
fi

# GCS sync may lose executable bits; normalize bootstrap scripts defensively.
if [[ -d "${BMT_REPO_ROOT}/bootstrap" ]]; then
  chmod +x "${BMT_REPO_ROOT}/bootstrap/"*.sh 2>/dev/null || true
fi

# Remove Python/uv bloat that may have been synced or left from a previous run.
_clean_bloat() {
  local root="${1:?}"
  find "$root" -type d \( -name '__pycache__' -o -name '.venv' -o -name 'venv' -o -name '.uv' \
    -o -name '.mypy_cache' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '.tox' -o -name '.eggs' \) \
    -exec rm -rf {} + 2>/dev/null || true
  find "$root" -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
  find "$root" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.egg' \) -delete 2>/dev/null || true
}
_clean_bloat "${BMT_REPO_ROOT}"

if [[ -f "${BMT_REPO_ROOT}/bootstrap/startup_example.sh" ]]; then
  exec bash "${BMT_REPO_ROOT}/bootstrap/startup_example.sh"
fi

echo "::error::Missing startup entrypoint under ${BMT_REPO_ROOT}" >&2
exit 1
