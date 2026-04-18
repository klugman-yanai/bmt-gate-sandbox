#!/usr/bin/env bash
# Full live-test pipeline: `just ship` → `git push` → workflow_dispatch on the
# BMT pipeline workflow. Each phase is skippable; the trigger phase prompts for
# confirmation unless --no-confirm is given.
#
# Flags:
#   --skip-ship      Skip `just ship` (test → preflight → deploy → image)
#   --skip-push      Skip `git push --set-upstream origin <branch>`
#   --skip-trigger   Skip `gh workflow run <workflow> --ref <branch>`
#   --no-confirm     Skip the interactive trigger confirmation
#   --dry-run        Print all actions; do not execute push/trigger; pass --dry-run to ship
#   --force-image    Forwarded to `just ship --force-image`
#   --workflow=NAME  Workflow filename to dispatch (default: build-and-test.yml)
#   -h | --help      Print this help and exit
set -euo pipefail

SKIP_SHIP=0
SKIP_PUSH=0
SKIP_TRIGGER=0
NO_CONFIRM=0
DRY_RUN=0
SHIP_ARGS=()
WORKFLOW="${BMT_LIVE_TRIGGER_WORKFLOW:-build-and-test.yml}"

print_help() {
  sed -n '1,/^set -euo pipefail$/p' "$0" | sed 's/^# \{0,1\}//;1d;$d'
}

for arg in "$@"; do
  case "$arg" in
    --skip-ship) SKIP_SHIP=1 ;;
    --skip-push) SKIP_PUSH=1 ;;
    --skip-trigger) SKIP_TRIGGER=1 ;;
    --no-confirm) NO_CONFIRM=1 ;;
    --dry-run) DRY_RUN=1; SHIP_ARGS+=("--dry-run") ;;
    --force-image) SHIP_ARGS+=("--force-image") ;;
    --workflow=*) WORKFLOW="${arg#--workflow=}" ;;
    -h|--help) print_help; exit 0 ;;
    *) printf 'unknown flag: %s (use --help)\n' "$arg" >&2; exit 64 ;;
  esac
done

if ! command -v just >/dev/null 2>&1; then
  echo "error: 'just' not on PATH" >&2; exit 127
fi
if [ "$SKIP_TRIGGER" -eq 0 ] && ! command -v gh >/dev/null 2>&1; then
  echo "error: 'gh' not on PATH (needed for workflow trigger; pass --skip-trigger to bypass)" >&2; exit 127
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
HEAD_SHORT=$(git rev-parse --short HEAD)

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '  \033[2m%s\033[0m\n' "$*"; }

bold "live-test • branch=${BRANCH} • head=${HEAD_SHORT} • workflow=${WORKFLOW}"
phase() { [ "$1" -eq 0 ] && printf 'on' || printf 'skip'; }
note "phases: ship=$(phase $SKIP_SHIP) | push=$(phase $SKIP_PUSH) | trigger=$(phase $SKIP_TRIGGER) | dry_run=$DRY_RUN"

if [ "$SKIP_SHIP" -eq 0 ]; then
  bold "[1/3] just ship ${SHIP_ARGS[*]:-}"
  just ship "${SHIP_ARGS[@]:-}"
else
  bold "[1/3] ship: skipped"
fi

if [ "$SKIP_PUSH" -eq 0 ]; then
  bold "[2/3] git push --set-upstream origin ${BRANCH}"
  if [ "$DRY_RUN" -eq 1 ]; then
    note "dry-run: not executed"
  else
    git push --set-upstream origin "$BRANCH"
  fi
else
  bold "[2/3] push: skipped"
fi

if [ "$SKIP_TRIGGER" -eq 0 ]; then
  bold "[3/3] gh workflow run ${WORKFLOW} --ref ${BRANCH}"
  if [ "$DRY_RUN" -eq 1 ]; then
    note "dry-run: not executed"
  else
    if [ "$NO_CONFIRM" -eq 0 ]; then
      printf '  Confirm trigger of %s on %s? [y/N] ' "$WORKFLOW" "$BRANCH"
      read -r ans
      case "$ans" in
        y|Y|yes|YES) ;;
        *) echo "  trigger declined."; bold "live-test stopped before trigger"; exit 0 ;;
      esac
    fi
    gh workflow run "$WORKFLOW" --ref "$BRANCH"
    sleep 3
    note "Latest runs for ${WORKFLOW} on ${BRANCH}:"
    gh run list --workflow="$WORKFLOW" --branch="$BRANCH" --limit 3 || true
    note "Watch with: gh run watch \$(gh run list --workflow=${WORKFLOW} --branch=${BRANCH} --limit 1 --json databaseId -q '.[0].databaseId')"
  fi
else
  bold "[3/3] trigger: skipped"
fi

bold "live-test complete"
