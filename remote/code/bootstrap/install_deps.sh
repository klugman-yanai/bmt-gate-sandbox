#!/usr/bin/env bash
# Install VM dependencies for vm_watcher (requests + PyJWT + cryptography).
# Uses uv sync from the VM runtime project in REPO_ROOT (pyproject.toml / uv.lock).
# uv is resolved from:
#   1) UV_BIN / BMT_UV_BIN
#   2) uv on PATH
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

UV_BIN="${UV_BIN:-${BMT_UV_BIN:-}}"
if [[ -z "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv 2>/dev/null || true)"
fi

if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "uv not found. Set UV_BIN/BMT_UV_BIN or install uv on the VM image." >&2
  exit 1
fi

cd "$REPO_ROOT"
if [[ -f "$PYPROJECT" && -f "$UVLOCK" ]]; then
  # Sync from lock file so install is reproducible; --frozen keeps lock unchanged on VM.
  "$UV_BIN" sync --extra vm --frozen
  echo "Synced VM deps (requests + vm extras) from uv.lock into ${REPO_ROOT}/.venv"
elif [[ -f "$PYPROJECT" ]]; then
  # Non-frozen fallback for debug environments where lock file is intentionally omitted.
  "$UV_BIN" sync --extra vm
  echo "Synced VM deps from pyproject.toml (non-frozen; uv.lock missing) into ${REPO_ROOT}/.venv"
else
  echo "::error::Missing VM dependency project file: ${PYPROJECT}" >&2
  exit 1
fi

# Non-fatal check: watcher can still run without jwt if PAT fallback is used.
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  if "${REPO_ROOT}/.venv/bin/python" -c "import jwt; import cryptography; import requests; print('OK')" 2>/dev/null; then
    echo "Verified requests/jwt/cryptography availability in ${REPO_ROOT}/.venv"
  else
    echo "Warning: dependency import check failed; watcher auth/check runs may be degraded." >&2
  fi
fi
