# just setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `just onboard` / `bootstrap_dev_env.sh` with a single `just setup` (and `just setup --dev`) that takes a fresh Linux/WSL2 machine from zero to a working contributor environment.

**Architecture:** A single bash script `tools/scripts/setup.sh` handles OS-level installs (sudo, package managers, curl installers) and delegates to existing Python tooling for the bucket probe. Follows the established pattern: bash bootstrap → `uv run python -m tools`. Package manager is detected once at startup in priority order: apt → paru → pacman.

**Tech Stack:** bash (set -euo pipefail), uv, gcloud CLI, prek, shellcheck (validation), ANSI escape codes (output styling).

---

## File Map

| File | Action |
|---|---|
| `tools/scripts/setup.sh` | **Create** — full bootstrap script |
| `tools/scripts/bootstrap_dev_env.sh` | **Delete** |
| `Justfile` | **Modify** — replace `onboard` recipe with `setup`; update help text |
| `CONTRIBUTING.md` | **Modify** — replace three-step onboard section with `just setup` |

---

### Task 1: Create setup.sh skeleton (args, PKG detection, output helpers)

**Files:**
- Create: `tools/scripts/setup.sh`

- [ ] **Step 1: Create the file with shebang, arg parsing, and color helpers**

```bash
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
```

- [ ] **Step 2: Validate skeleton with shellcheck**

```bash
shellcheck --severity=warning tools/scripts/setup.sh
```

Expected: no warnings or errors.

- [ ] **Step 3: Commit**

```bash
git add tools/scripts/setup.sh
git commit -m "feat: add setup.sh skeleton (args, PKG detection, color helpers)"
```

---

### Task 2: Implement base steps 1–4 (repo root, uv, gcloud, ADC)

**Files:**
- Modify: `tools/scripts/setup.sh`

- [ ] **Step 1: Add ensure_repo_root, ensure_uv, ensure_gcloud, ensure_adc**

Append after the `pkg_install` function:

```bash
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
    *)      fail "Cannot install gcloud: no supported package manager."; FAILED_STEPS+=("gcloud"); return 1 ;;
  esac
  if [[ -d "/opt/google-cloud-cli/bin" ]]; then
    export PATH="/opt/google-cloud-cli/bin:${PATH}"
  fi
  # Persist to shell rc files
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
```

- [ ] **Step 2: Validate with shellcheck**

```bash
shellcheck --severity=warning tools/scripts/setup.sh
```

Expected: no warnings or errors.

- [ ] **Step 3: Smoke test dry-run (steps 1–4 only — main not wired yet)**

Manually invoke each function in a subshell to confirm syntax:

```bash
bash -n tools/scripts/setup.sh
```

Expected: no syntax errors printed.

- [ ] **Step 4: Commit**

```bash
git add tools/scripts/setup.sh
git commit -m "feat: setup.sh base steps 1-4 (repo root, uv, gcloud, ADC)"
```

---

### Task 3: Implement base steps 5–8 (GCS bucket, uv sync, prek hooks, bucket probe)

**Files:**
- Modify: `tools/scripts/setup.sh`

- [ ] **Step 1: Add ensure_gcs_bucket, run_uv_sync, ensure_prek_hooks, run_bucket_probe**

Append after `ensure_adc`:

```bash
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
  uv sync
  ok
}

# ── step 7: prek hooks ────────────────────────────────────────────────────────
_prek_hooks_installed() {
  local pc="$REPO_ROOT/.git/hooks/pre-commit"
  local pp="$REPO_ROOT/.git/hooks/pre-push"
  [[ -f "$pc" ]] && [[ -f "$pp" ]] && grep -qi prek "$pc" "$pp" 2>/dev/null
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
```

- [ ] **Step 2: Validate with shellcheck**

```bash
shellcheck --severity=warning tools/scripts/setup.sh
```

Expected: no warnings or errors.

- [ ] **Step 3: Commit**

```bash
git add tools/scripts/setup.sh
git commit -m "feat: setup.sh base steps 5-8 (GCS bucket, uv sync, prek, bucket probe)"
```

---

### Task 4: Implement dev steps 9–11 and wire main()

**Files:**
- Modify: `tools/scripts/setup.sh`

- [ ] **Step 1: Add dev steps (ensure_shellcheck, ensure_actionlint, ensure_pulumi) and main**

Append after `run_bucket_probe`:

```bash
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
        fail "Could not determine actionlint download URL."; FAILED_STEPS+=("actionlint"); return 1
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
  printf "${GREEN}${BOLD}Setup complete.${RESET}\n"
else
  printf "${RED}${BOLD}Setup finished with issues:${RESET}\n"
  for s in "${FAILED_STEPS[@]}"; do
    printf "  - %s\n" "$s"
  done
  exit 1
fi
```

- [ ] **Step 2: Validate with shellcheck**

```bash
shellcheck --severity=warning tools/scripts/setup.sh
```

Expected: no warnings or errors.

- [ ] **Step 3: Smoke test dry-run (full script)**

```bash
bash tools/scripts/setup.sh --dry-run
```

Expected: each `==> Step name` header printed, each step shows `[would install]` or `ok`, final line is `Setup complete.`

```bash
bash tools/scripts/setup.sh --dev --dry-run
```

Expected: same as above plus shellcheck / actionlint / Pulumi steps appear.

- [ ] **Step 4: Commit**

```bash
git add tools/scripts/setup.sh
git commit -m "feat: setup.sh dev steps 9-11 and main() — complete script"
```

---

### Task 5: Update Justfile (replace onboard with setup, update help)

**Files:**
- Modify: `Justfile`

- [ ] **Step 1: Replace the onboard recipe**

In `Justfile`, find:

```justfile
# One-time local setup: uv, Python 3.12, uv sync, prek hooks (no ty/pytest in the script)
[group('dev')]
onboard *args:
    bash tools/scripts/bootstrap_dev_env.sh {{ args }}
```

Replace with:

```justfile
# One-time setup for a fresh machine: installs uv, gcloud, ADC, syncs deps, installs prek hooks.
# Pass --dev for a full developer environment (shellcheck, actionlint, pulumi).
# Pass --dry-run to preview what would be installed without making changes.
[group('setup')]
setup *args:
    bash tools/scripts/setup.sh {{ args }}
```

- [ ] **Step 2: Update the help text at the top of the Justfile**

Find the line:

```
'  just onboard           Bootstrap: uv, Python 3.12, hooks (use: just onboard --dry-run)' \
```

Replace with:

```
'  just setup             Bootstrap: uv, gcloud, ADC, deps, hooks (just setup --dev for full)' \
```

- [ ] **Step 3: Verify just lists setup correctly**

```bash
just help
```

Expected: `just setup` appears in the Daily section. `just onboard` no longer appears.

```bash
just --list
```

Expected: `setup` recipe listed under `setup` group.

- [ ] **Step 4: Commit**

```bash
git add Justfile
git commit -m "feat: replace just onboard with just setup in Justfile"
```

---

### Task 6: Update CONTRIBUTING.md

**Files:**
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Replace the three-step onboard section with just setup**

Find and replace the entire "One-time setup" section (lines starting from `## One-time setup` through the end of the "Manual equivalent" block at approximately L70). Replace with:

```markdown
## One-time setup

Install **`just`** (optional but recommended), then run **`just setup`** from the repo root.

### 1. Install just (optional)

**[just](https://github.com/casey/just)** runs named recipes from the `Justfile`.

**Ubuntu:**

```bash
sudo apt update && sudo apt install -y just
```

### 2. Run setup

From the **repository root**:

```bash
just setup
```

`just setup` runs [`tools/scripts/setup.sh`](tools/scripts/setup.sh): installs **uv** (if missing), installs **gcloud CLI** (if missing), authenticates Application Default Credentials, syncs the Python workspace (**`uv sync`**), and installs **prek** shims for **pre-commit** and **pre-push**.

For a full developer environment (adds **shellcheck**, **actionlint**, **Pulumi**):

```bash
just setup --dev
```

**Dry run** (no installs or `uv sync`; reports what would happen):

```bash
just setup --dry-run
```

**Manual equivalent** (without `just`):

```bash
bash tools/scripts/setup.sh
```

Re-running `just setup` on an already-configured machine is safe and fast — each step is idempotent.
```

- [ ] **Step 2: Update all remaining references to `just onboard` and `bootstrap_dev_env.sh`**

Search for stale references:

```bash
grep -n 'onboard\|bootstrap_dev_env' CONTRIBUTING.md
```

Expected: zero matches (or only in historical context). Fix any remaining references by replacing with `just setup` / `setup.sh`.

- [ ] **Step 3: Verify the file renders correctly**

```bash
head -80 CONTRIBUTING.md
```

Confirm the setup section reads cleanly.

- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: update CONTRIBUTING.md for just setup (replaces just onboard)"
```

---

### Task 7: Delete bootstrap_dev_env.sh and audit remaining references

**Files:**
- Delete: `tools/scripts/bootstrap_dev_env.sh`

- [ ] **Step 1: Check for references to bootstrap_dev_env.sh across the repo**

```bash
grep -rn 'bootstrap_dev_env' . --include='*.md' --include='*.sh' --include='*.yml' --include='*.yaml' --include='*.toml' --include='Justfile'
```

Expected: only references in git history. Fix any live references before deleting.

- [ ] **Step 2: Delete the file**

```bash
git rm tools/scripts/bootstrap_dev_env.sh
```

- [ ] **Step 3: Audit for onboard references across all docs**

```bash
grep -rn 'just onboard\|onboard' . --include='*.md' --include='Justfile' --include='*.sh'
```

Fix any remaining references (replace with `just setup`).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: delete bootstrap_dev_env.sh (superseded by setup.sh)"
```

---

### Task 8: Full validation

- [ ] **Step 1: shellcheck the final setup.sh**

```bash
shellcheck --severity=warning tools/scripts/setup.sh
```

Expected: no warnings or errors.

- [ ] **Step 2: shellcheck hooks (regression check)**

```bash
shellcheck --severity=warning tools/scripts/hooks/*.sh
```

Expected: no new errors introduced.

- [ ] **Step 3: Dry-run smoke test (base)**

```bash
bash tools/scripts/setup.sh --dry-run
```

Verify every step prints a header and `[would install]` or `ok`. Final line: `Setup complete.`

- [ ] **Step 4: Dry-run smoke test (dev)**

```bash
bash tools/scripts/setup.sh --dev --dry-run
```

Verify shellcheck, actionlint, Pulumi steps appear.

- [ ] **Step 5: Run the full test suite (layout + lint regression)**

```bash
just test
```

Expected: all checks pass. The `shellcheck` step covers `tools/scripts/hooks/*.sh` — confirm `setup.sh` is not accidentally picked up by the glob (it's not in `hooks/`).

- [ ] **Step 6: Commit if any fixes needed**

```bash
git add -p
git commit -m "fix: address shellcheck findings in setup.sh"
```
