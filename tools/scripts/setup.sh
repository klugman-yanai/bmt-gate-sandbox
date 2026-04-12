#!/usr/bin/env bash
# Bootstrap a fresh Linux/WSL2 machine for bmt-gcloud contribution.
#
# Usage:
#   bash tools/scripts/setup.sh           # base: plugin contributor
#   bash tools/scripts/setup.sh --dev     # full: developer
#   bash tools/scripts/setup.sh --dry-run # report only, no installs
set -euo pipefail

# ── args ──────────────────────────────────────────────────────────────────────
DEV=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dev)     DEV=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --) ;;
    *) printf 'Unknown argument: %s\n' "$arg" >&2; exit 1 ;;
  esac
done

# ── color helpers ──────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

step() { printf "\n${BOLD}==> %s${RESET}\n" "$1"; }
ok()   { printf "${GREEN}ok${RESET}\n"; }
info() { printf "${YELLOW}%s${RESET}\n" "$1"; }
warn() { printf "${YELLOW}[warn] %s${RESET}\n" "$1" >&2; }
fail() { printf "${RED}[error] %s${RESET}\n" "$1" >&2; }

FAILED_STEPS=()

# ── package manager detection ──────────────────────────────────────────────────
PKG="unknown"
if command -v apt-get >/dev/null 2>&1; then
  PKG="apt"
elif command -v paru >/dev/null 2>&1; then
  PKG="paru"
elif command -v pacman >/dev/null 2>&1; then
  PKG="pacman"
fi

pkg_install() {
  local pkg="$1"
  case "$PKG" in
    apt)    sudo apt-get install -y "$pkg" ;;
    paru)   paru -S --noconfirm "$pkg" ;;
    pacman) sudo pacman -S --noconfirm "$pkg" ;;
    *)      fail "No supported package manager (apt/paru/pacman)"; return 1 ;;
  esac
}
