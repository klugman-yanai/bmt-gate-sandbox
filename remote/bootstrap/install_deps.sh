#!/usr/bin/env bash
# Install VM dependencies for vm_watcher (PyJWT + cryptography for GitHub App JWT).
# Uses uv sync for reproducible install from uv.lock. Install uv once on the VM (e.g. via SSH) if not present.
# Run once per VM (or at image build). Venv and packages live under REPO_ROOT (use a persistent path like /opt/bmt so they survive VM stop/start).
# Usage: install_deps.sh REPO_ROOT
# Example: install_deps.sh /opt/bmt

set -euo pipefail

REPO_ROOT="${1:-}"
if [[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT" ]]; then
  echo "Usage: $0 REPO_ROOT" >&2
  echo "Example: $0 /opt/bmt" >&2
  exit 1
fi

PYPROJECT="${REPO_ROOT}/pyproject.toml"
UVLOCK="${REPO_ROOT}/uv.lock"

if [[ ! -f "$PYPROJECT" ]]; then
  echo "pyproject.toml not found at ${PYPROJECT}" >&2
  exit 1
fi

if [[ ! -f "$UVLOCK" ]]; then
  echo "uv.lock not found at ${UVLOCK}. Run 'uv lock' (and optionally 'uv sync --extra vm') in the repo and commit uv.lock." >&2
  exit 1
fi

if ! command -v uv &>/dev/null; then
  echo "uv not found. Install it once on the VM (e.g. curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2
  exit 1
fi

cd "$REPO_ROOT"
# Sync from lock file so install is reproducible; --frozen keeps lock unchanged on VM
uv sync --extra vm --frozen
echo "Synced VM extras (PyJWT, cryptography) from uv.lock into ${REPO_ROOT}/.venv"

# Quick check
"${REPO_ROOT}/.venv/bin/python" -c "import jwt; import cryptography; print('OK')"
