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
if [ -t 1 ]; then
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  RED='\033[0;31m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  GREEN=''
  YELLOW=''
  RED=''
  BOLD=''
  RESET=''
fi

step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RESET"; }
ok()   { printf '%sok%s\n' "$GREEN" "$RESET"; }
info() { printf '%s%s%s\n' "$YELLOW" "$1" "$RESET"; }
warn() { printf '%s[warn] %s%s\n' "$YELLOW" "$1" "$RESET" >&2; }
fail() { printf '%s[error] %s%s\n' "$RED" "$1" "$RESET" >&2; }

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

# ── step 1: repo root ──────────────────────────────────────────────────────────
REPO_ROOT=""
ensure_repo_root() {
  step "Locate repo root"
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local dir="$here"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/pyproject.toml" ]] && grep -q 'name = "bmt-gcloud"' "$dir/pyproject.toml" 2>/dev/null; then
      REPO_ROOT="$dir"
      ok; return 0
    fi
    dir="$(dirname "$dir")"
  done
  fail "Could not find bmt-gcloud repo root (no pyproject.toml with name = \"bmt-gcloud\")."
  exit 1
}

# ── step 2: uv ────────────────────────────────────────────────────────────────
ensure_uv() {
  step "uv"
  export PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"
  if command -v uv >/dev/null 2>&1; then
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would install] uv via astral.sh installer"; return 0
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"
  ok
}

# ── step 3: gcloud ────────────────────────────────────────────────────────────
ensure_gcloud() {
  step "gcloud CLI"
  if command -v gcloud >/dev/null 2>&1; then
    ok; return 0
  fi
  if [[ -x "/opt/google-cloud-cli/bin/gcloud" ]]; then
    export PATH="/opt/google-cloud-cli/bin:${PATH}"
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would install] google-cloud-cli via ${PKG}"; return 0
  fi
  case "$PKG" in
    apt)
      if [[ ! -f /etc/apt/sources.list.d/google-cloud-sdk.list ]]; then
        sudo apt-get install -y apt-transport-https ca-certificates gnupg curl
        curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
          sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
        echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | \
          sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
        sudo apt-get update
      fi
      sudo apt-get install -y google-cloud-cli
      ;;
    paru)   paru -S --noconfirm google-cloud-cli-lite ;;
    pacman) sudo pacman -S --noconfirm google-cloud-cli-lite ;;
    *)
      fail "Cannot install gcloud: no supported package manager."
      FAILED_STEPS+=("gcloud"); return 1
      ;;
  esac
  if [[ -d "/opt/google-cloud-cli/bin" ]]; then
    export PATH="/opt/google-cloud-cli/bin:${PATH}"
  fi
  # Persist gcloud bin to shell rc files for future sessions
  local line='export PATH="/opt/google-cloud-cli/bin:${PATH}"'
  for rc in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.zshenv"; do
    if [[ -f "$rc" ]] && ! grep -q 'google-cloud-cli/bin' "$rc" 2>/dev/null; then
      echo "$line" >> "$rc"
    fi
  done
  ok
}

# ── step 4: ADC ───────────────────────────────────────────────────────────────
ensure_adc() {
  step "Application Default Credentials"
  if gcloud auth application-default print-access-token >/dev/null 2>&1; then
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would run] gcloud auth application-default login"; return 0
  fi
  gcloud auth application-default login
  ok
}
