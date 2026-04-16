#!/usr/bin/env bash
# Invoke the kardome-bmt CLI: use release PEX when BMT_PEX_PATH is set, else uv run bmt.
set -euo pipefail
if [[ -n "${BMT_PEX_PATH:-}" ]]; then
  exec "${BMT_PEX_PATH}" "$@"
fi
exec uv run bmt "$@"
