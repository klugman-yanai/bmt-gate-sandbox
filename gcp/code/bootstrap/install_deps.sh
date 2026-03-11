#!/usr/bin/env bash
# Install VM dependencies for vm_watcher into REPO_ROOT/.venv.
# Uses pip for portability (no external tool dependencies).
# Usage: install_deps.sh REPO_ROOT

set -euo pipefail

REPO_ROOT="${1:-}"
if [[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT" ]]; then
  echo "Usage: $0 REPO_ROOT" >&2
  exit 1
fi

PYPROJECT="${REPO_ROOT}/pyproject.toml"
if [[ ! -f "$PYPROJECT" ]]; then
  echo "::error::Missing pyproject.toml at $PYPROJECT; cannot install dependencies." >&2
  exit 1
fi
VENV="${REPO_ROOT}/.venv"
DEP_STAMP="${VENV}/.bmt_dep_fingerprint"

_compute_dep_fingerprint() {
  local repo_root="$1"
  if [[ -f "${repo_root}/pyproject.toml" ]]; then
    sha256sum "${repo_root}/pyproject.toml" | awk '{print $1}'
    return 0
  fi
  return 1
}

# Prefer python3.12 explicitly; fall back to python3.
python3_bin="$(command -v python3.12 || command -v python3 || true)"
if [[ -z "${python3_bin}" || ! -x "${python3_bin}" ]]; then
  echo "::error::python3.12 (or python3) not found; cannot install dependencies." >&2
  exit 1
fi
echo "Using Python: ${python3_bin} ($("${python3_bin}" --version 2>&1 || true))"

# Create venv if missing.
if [[ ! -d "${VENV}" ]]; then
  echo "Creating venv at ${VENV}"
  "${python3_bin}" -m venv "${VENV}"
fi

# Install packages from pyproject.toml (base deps + vm extras).
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet \
  "httpx>=0.27" \
  "google-cloud-storage>=2.16" \
  "google-cloud-pubsub>=2.21" \
  "PyJWT>=2.0" \
  "cryptography>=41.0"
echo "pip install complete."

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
