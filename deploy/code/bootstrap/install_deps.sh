#!/usr/bin/env bash
# Install VM dependencies for vm_watcher into REPO_ROOT/.venv.
# Prefers uv (if available) for speed; falls back to pip for portability.
# Usage: install_deps.sh REPO_ROOT

set -euo pipefail

REPO_ROOT="${1:-}"
if [[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT" ]]; then
  echo "Usage: $0 REPO_ROOT" >&2
  exit 1
fi

PYPROJECT="${REPO_ROOT}/pyproject.toml"
UVLOCK="${REPO_ROOT}/uv.lock"
VENV="${REPO_ROOT}/.venv"
DEP_STAMP="${VENV}/.bmt_dep_fingerprint"

_compute_dep_fingerprint() {
  local repo_root="$1"
  if [[ -f "${repo_root}/pyproject.toml" && -f "${repo_root}/uv.lock" ]]; then
    sha256sum "${repo_root}/pyproject.toml" "${repo_root}/uv.lock" | sha256sum | awk '{print $1}'
    return 0
  fi
  if [[ -f "${repo_root}/pyproject.toml" ]]; then
    sha256sum "${repo_root}/pyproject.toml" | awk '{print $1}'
    return 0
  fi
  return 1
}

# Attempt uv-based install first (fast, uses lock file).
UV_BIN="${UV_BIN:-${BMT_UV_BIN:-$(command -v uv 2>/dev/null || true)}}"
if [[ -n "${UV_BIN}" && -x "${UV_BIN}" ]]; then
  cd "$REPO_ROOT"
  if [[ -f "$UVLOCK" ]]; then
    echo "Installing deps via uv sync --extra vm --frozen"
    "$UV_BIN" sync --extra vm --frozen
  else
    echo "Installing deps via uv sync --extra vm (no lock file)"
    "$UV_BIN" sync --extra vm
  fi
  echo "uv install complete."
else
  # Fallback: system python3 + pip.
  # Extract package list from pyproject.toml dependencies and vm extras.
  echo "uv not available; falling back to pip install."

  PYTHON3="$(command -v python3 || true)"
  if [[ -z "${PYTHON3}" || ! -x "${PYTHON3}" ]]; then
    echo "::error::Neither uv nor python3 found; cannot install dependencies." >&2
    exit 1
  fi

  # Create venv if missing.
  if [[ ! -d "${VENV}" ]]; then
    echo "Creating venv at ${VENV}"
    "${PYTHON3}" -m venv "${VENV}"
  fi

  # Install packages from pyproject.toml (base deps + vm extras).
  # These are pinned in pyproject.toml; for exact versions use pip with constraints from uv.lock.
  "${VENV}/bin/pip" install --quiet --upgrade pip
  "${VENV}/bin/pip" install --quiet \
    "httpx>=0.27" \
    "google-cloud-storage>=2.16" \
    "google-cloud-pubsub>=2.21" \
    "PyJWT>=2.0" \
    "cryptography>=41.0"
  echo "pip install complete."
fi

# Write fingerprint stamp.
if dep_fingerprint="$(_compute_dep_fingerprint "$REPO_ROOT")"; then
  mkdir -p "$(dirname "$DEP_STAMP")"
  printf '%s\n' "$dep_fingerprint" >"$DEP_STAMP"
  echo "Dependency fingerprint: ${dep_fingerprint}"
fi

# Verify import.
if [[ -x "${VENV}/bin/python" ]]; then
  if "${VENV}/bin/python" -c "import jwt; import cryptography; import httpx; import google.cloud.storage; print('OK')" 2>/dev/null; then
    echo "Import check passed."
  else
    echo "Warning: dependency import check failed; watcher may be degraded." >&2
  fi
fi
