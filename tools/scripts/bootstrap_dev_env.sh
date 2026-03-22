#!/usr/bin/env bash
# After uv is installed: sync .venv, install prek hooks, print Rich summary via tools onboard.
# Requires: uv on PATH (install first — see CONTRIBUTING.md).
# Does not run ty, pytest, or prek run.
#
# Usage:
#   bash tools/scripts/bootstrap_dev_env.sh
#   bash tools/scripts/bootstrap_dev_env.sh --dry-run
#   BOOTSTRAP_DRY_RUN=1 bash tools/scripts/bootstrap_dev_env.sh
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --) ;;
  esac
done
if [[ -n "${BOOTSTRAP_DRY_RUN:-}" ]]; then
  DRY_RUN=1
fi

ensure_repo_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local dir="$here"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/pyproject.toml" ]] && grep -q 'name = "bmt-gcloud"' "$dir/pyproject.toml" 2>/dev/null; then
      REPO_ROOT="$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo "bootstrap_dev_env.sh: could not find bmt-gcloud repo root." >&2
  exit 1
}

ensure_uv() {
  export PATH="${HOME}/.local/bin:${PATH}"
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  echo "error: uv is not on PATH. Install uv first, then re-run." >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "See CONTRIBUTING.md (One-time setup)." >&2
  exit 1
}

ensure_python_312() {
  if command -v python3.12 >/dev/null 2>&1; then
    return 0
  fi
  if uv python find 3.12 >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  echo "Installing Python 3.12 via uv..." >&2
  uv python install 3.12
}

# True when prek shims for commit + push are already in .git/hooks/ (typical after a prior onboard).
prek_hooks_already_installed() {
  local pc="$REPO_ROOT/.git/hooks/pre-commit"
  local pp="$REPO_ROOT/.git/hooks/pre-push"
  [[ -f "$pc" ]] && [[ -f "$pp" ]] || return 1
  grep -qi prek "$pc" "$pp" 2>/dev/null
}

# Echo one of: hooks-path | already-installed | would-install | no-git (for tools onboard --prek-state).
compute_dry_run_prek_state() {
  if [[ ! -d "$REPO_ROOT/.git" ]]; then
    echo "no-git"
    return
  fi
  if git -C "$REPO_ROOT" config --get core.hooksPath >/dev/null 2>&1; then
    echo "hooks-path"
    return
  fi
  if prek_hooks_already_installed; then
    echo "already-installed"
    return
  fi
  echo "would-install"
}

invoke_onboard_rich() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    ps="$(compute_dry_run_prek_state)"
    uv run python -m tools onboard --dry-run --prek-state "$ps"
  else
    uv run python -m tools onboard
  fi
}

ensure_repo_root
cd "$REPO_ROOT"

ensure_uv
ensure_python_312

if [[ "$DRY_RUN" -eq 1 ]]; then
  :
else
  echo "Running uv sync..." >&2
  uv sync
fi

if [[ -d "$REPO_ROOT/.git" ]]; then
  SKIP_PREK=0
  if git -C "$REPO_ROOT" config --get core.hooksPath >/dev/null 2>&1; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      SKIP_PREK=1
    else
      echo "error: git core.hooksPath is set; prek cannot install hooks until it is unset." >&2
      echo "  git -C \"${REPO_ROOT}\" config --unset-all core.hooksPath" >&2
      exit 1
    fi
  fi
  if [[ "$SKIP_PREK" -eq 0 ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      :
    else
      echo "Installing prek hooks (pre-commit + pre-push)..." >&2
      uv run prek install -t pre-commit -f
      uv run prek install -t pre-push -f
    fi
  fi
else
  if [[ "$DRY_RUN" -eq 0 ]]; then
    echo "Not a git checkout; skipping prek install." >&2
  fi
fi

invoke_onboard_rich
