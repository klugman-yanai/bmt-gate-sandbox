#!/usr/bin/env bash
# Full local verify: sync, pytest, ruff, ty, actionlint, shellcheck (hooks), layout policy.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
cd "$repo_root"

uv sync
uv run python -m pytest tests/ -v
ruff check .
ruff format --check .
uv run ty check

if ! command -v actionlint >/dev/null 2>&1; then
    echo "Install actionlint (https://github.com/rhysd/actionlint)" >&2
    exit 1
fi
actionlint -config-file .github/actionlint.yaml

if ! command -v shellcheck >/dev/null 2>&1; then
    echo "Install shellcheck (e.g. apt install shellcheck)" >&2
    exit 1
fi
shellcheck --severity=warning tools/scripts/hooks/*.sh

uv run python -m tools repo validate-layout
