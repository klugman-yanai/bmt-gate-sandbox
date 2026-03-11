#!/usr/bin/env bash
# Install VM dependencies for vm_watcher into REPO_ROOT/.venv.
# Uses pip for portability (no external tool dependencies).
# Usage: install_deps.sh REPO_ROOT

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/shared.sh"
_bmt_log_tag="install_deps"

REPO_ROOT="${1:-}"
if [[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT" ]]; then
  _log_err "Usage: $0 REPO_ROOT"
  exit 1
fi

_log "REPO_ROOT=${REPO_ROOT}"

PYPROJECT="${REPO_ROOT}/pyproject.toml"
if [[ ! -f "$PYPROJECT" ]]; then
  _log_err "::error::Missing pyproject.toml at $PYPROJECT; cannot install dependencies."
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

python3_bin="$(command -v python3 || true)"
if [[ -z "${python3_bin}" || ! -x "${python3_bin}" ]]; then
  _log_err "::error::python3 not found; cannot install dependencies."
  exit 1
fi

# Create venv if missing.
if [[ ! -d "${VENV}" ]]; then
  _log "Creating venv at ${VENV}"
  "${python3_bin}" -m venv "${VENV}"
fi

# Install the code-root package (lib) and VM runtime deps in editable mode. No PYTHONPATH.
_log "Installing package (editable) with [vm] extra from ${REPO_ROOT}..."
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet -e "${REPO_ROOT}[vm]"
_log "pip install complete."

# Write fingerprint stamp.
if dep_fingerprint="$(_compute_dep_fingerprint "$REPO_ROOT")"; then
  mkdir -p "$(dirname "$DEP_STAMP")"
  printf '%s\n' "$dep_fingerprint" >"$DEP_STAMP"
  _log "Dependency fingerprint: ${dep_fingerprint}"
fi

# Verify import (fail fast so image build and maintenance do not produce a broken venv).
if [[ -x "${VENV}/bin/python" ]]; then
  if ! "${VENV}/bin/python" -c "import lib.bmt_config; import jwt; import cryptography; import httpx; import google.cloud.storage; print('OK')" 2>/dev/null; then
    _log_err "::error::Dependency import check failed; watcher would be broken. Fix pyproject or environment."
    exit 1
  fi
  _log "Import check passed."
fi
