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
        curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
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
  if ! command -v gcloud >/dev/null 2>&1; then
    warn "gcloud not found; skipping ADC setup."
    FAILED_STEPS+=("adc"); return 1
  fi
  if gcloud auth application-default print-access-token >/dev/null 2>&1; then
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would run] gcloud auth application-default login"; return 0
  fi
  gcloud auth application-default login
  ok
}

# ── step 5: GCS bucket ────────────────────────────────────────────────────────
ensure_gcs_bucket() {
  step "GCS_BUCKET"
  if [[ -n "${GCS_BUCKET:-}" ]]; then
    info "GCS_BUCKET=${GCS_BUCKET}"; ok; return 0
  fi
  local resolved=""
  if command -v gh >/dev/null 2>&1; then
    resolved="$(gh variable get GCS_BUCKET 2>/dev/null || true)"
  fi
  if [[ -n "$resolved" ]]; then
    export GCS_BUCKET="$resolved"
    info "GCS_BUCKET=${GCS_BUCKET} (from gh variable)"; ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would resolve] GCS_BUCKET — not set and gh unavailable or unset"; return 0
  fi
  fail "GCS_BUCKET is not set and could not be resolved."
  printf '  Fix:\n' >&2
  printf '    export GCS_BUCKET=<bucket-name>\n' >&2
  printf '    gh variable set GCS_BUCKET --body <bucket-name>\n' >&2
  FAILED_STEPS+=("GCS_BUCKET")
  return 1
}

# ── step 6: uv sync ───────────────────────────────────────────────────────────
run_uv_sync() {
  step "uv sync"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would run] uv sync"; return 0
  fi
  if ! uv sync; then
    fail "uv sync failed."
    FAILED_STEPS+=("uv sync")
    return 1
  fi
  ok
}

# ── step 7: prek hooks ────────────────────────────────────────────────────────
_prek_hooks_installed() {
  local pc="$REPO_ROOT/.git/hooks/pre-commit"
  local pp="$REPO_ROOT/.git/hooks/pre-push"
  [[ -f "$pc" ]] && [[ -f "$pp" ]] && grep -qi prek "$pc" 2>/dev/null && grep -qi prek "$pp" 2>/dev/null
}

ensure_prek_hooks() {
  step "prek hooks"
  if [[ ! -d "$REPO_ROOT/.git" ]]; then
    info "Not a git checkout; skipping prek install."; return 0
  fi
  if git -C "$REPO_ROOT" config --get core.hooksPath >/dev/null 2>&1; then
    info "core.hooksPath is set; skipping (hooks managed externally)."; return 0
  fi
  if _prek_hooks_installed; then
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would install] prek pre-commit + pre-push hooks"; return 0
  fi
  uv run prek install -t pre-commit -f
  uv run prek install -t pre-push -f
  ok
}

# ── step 8: bucket probe ──────────────────────────────────────────────────────
run_bucket_probe() {
  step "Bucket preflight"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[skipped in dry-run]"; return 0
  fi
  if ! uv run python -m tools bucket preflight; then
    warn "Bucket preflight returned non-zero."
    warn "The bucket may not be seeded yet. Run 'just deploy' once GCS_BUCKET is set."
  else
    ok
  fi
}

# ── dev step 9: shellcheck ────────────────────────────────────────────────────
ensure_shellcheck() {
  step "shellcheck"
  if command -v shellcheck >/dev/null 2>&1; then
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would install] shellcheck via ${PKG}"; return 0
  fi
  pkg_install shellcheck
  ok
}

# ── dev step 10: actionlint ───────────────────────────────────────────────────
ensure_actionlint() {
  step "actionlint"
  if command -v actionlint >/dev/null 2>&1; then
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would install] actionlint via ${PKG} (or GitHub release for apt)"; return 0
  fi
  case "$PKG" in
    paru)   paru -S --noconfirm actionlint ;;
    pacman) sudo pacman -S --noconfirm actionlint ;;
    apt|*)
      local tmpdir url
      tmpdir="$(mktemp -d)"
      url="$(curl -fsSL https://api.github.com/repos/rhysd/actionlint/releases/latest \
        | grep -o '"browser_download_url": "[^"]*linux_amd64[^"]*\.tar\.gz"' \
        | head -1 \
        | grep -o 'https://[^"]*')"
      if [[ -z "$url" ]]; then
        fail "Could not determine actionlint download URL."
        FAILED_STEPS+=("actionlint"); return 1
      fi
      curl -fsSL "$url" -o "$tmpdir/actionlint.tar.gz"
      tar -xzf "$tmpdir/actionlint.tar.gz" -C "$tmpdir"
      mkdir -p "${HOME}/.local/bin"
      mv "$tmpdir/actionlint" "${HOME}/.local/bin/actionlint"
      chmod +x "${HOME}/.local/bin/actionlint"
      rm -rf "$tmpdir"
      ;;
  esac
  ok
}

# ── dev step 11: pulumi ───────────────────────────────────────────────────────
ensure_pulumi() {
  step "Pulumi"
  if command -v pulumi >/dev/null 2>&1; then
    ok; return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[would install] Pulumi via get.pulumi.com installer"; return 0
  fi
  curl -fsSL https://get.pulumi.com | sh
  export PATH="${HOME}/.pulumi/bin:${PATH}"
  ok
}

# ── main ──────────────────────────────────────────────────────────────────────
ensure_repo_root
cd "$REPO_ROOT"

ensure_uv
ensure_gcloud
ensure_adc
ensure_gcs_bucket || true   # non-fatal; FAILED_STEPS captures failure
run_uv_sync
ensure_prek_hooks
run_bucket_probe

if [[ "$DEV" -eq 1 ]]; then
  ensure_shellcheck
  ensure_actionlint
  ensure_pulumi
fi

printf '\n'
if [[ ${#FAILED_STEPS[@]} -eq 0 ]]; then
  printf '%sSetup complete.%s\n' "$GREEN$BOLD" "$RESET"
else
  printf '%sSetup finished with issues:%s\n' "$RED$BOLD" "$RESET"
  for s in "${FAILED_STEPS[@]}"; do
    printf '  - %s\n' "$s"
  done
  exit 1
fi
