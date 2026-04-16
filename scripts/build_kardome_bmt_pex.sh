#!/usr/bin/env bash
# Build a self-contained PEX for the kardome-bmt CLI (console script: bmt).
# Requires: uv, network for PyPI transitive deps. Target interpreter: CPython 3.12.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

uv sync
VER="$(uv version --package kardome-bmt | awk '{print $2}')"
WHEEL_DIR="${WHEEL_DIR:-dist/pexb}"
OUT="${OUT:-dist/bmt.pex}"
mkdir -p "$(dirname "$OUT")" "$WHEEL_DIR"

uv build --package bmt-sdk --wheel -o "$WHEEL_DIR"
uv build --package bmt-runtime --wheel -o "$WHEEL_DIR"
uv build --package kardome-bmt --wheel -o "$WHEEL_DIR"
uv build --package bmt-gcloud --wheel -o "$WHEEL_DIR"

PY="$(uv python find 3.12)"
uv tool run --from pex pex \
  --python "$PY" \
  --python-shebang '/usr/bin/env python3' \
  "kardome-bmt==${VER}" \
  --find-links "$WHEEL_DIR" \
  -o "$OUT" \
  --console-script bmt

echo "Wrote ${OUT} (kardome-bmt==${VER})"
