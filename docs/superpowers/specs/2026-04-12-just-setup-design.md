# Design: `just setup` contributor bootstrap

**Date:** 2026-04-12
**Status:** Approved

## Problem

New contributors need to run two separate commands (`just onboard` for Python env, then manually configure gcloud and GCS_BUCKET) with no single entry point. `just onboard` covered Python/prek but not GCP access, leaving plugin contributors without a clear path to bucket connectivity.

## Goal

One command (`just setup`) that takes a fresh Linux/WSL2 machine from zero to able to add BMT plugins and push to the bucket. `just setup --dev` extends that to a fully functional dev environment.

## Out of scope

- macOS, Windows native
- Personal shell tool preferences (rg, fd, jq, etc.) — contributors manage those themselves
- GitHub App secrets / CI reporting credentials — those are operator-level config

---

## Architecture

Hybrid: thin bash script for OS-level installs (needs sudo, package managers, curl installers), delegates to existing Python tooling for the bucket probe. Follows the established pattern of `bootstrap_dev_env.sh` → `uv run python -m tools`.

---

## Files

| File | Change |
|---|---|
| `tools/scripts/setup.sh` | New — replaces `bootstrap_dev_env.sh` |
| `Justfile` | Replace `onboard` recipe with `setup`; remove `bootstrap_dev_env.sh` reference |
| `CONTRIBUTING.md` | Update one-time setup section |
| `tools/scripts/bootstrap_dev_env.sh` | Deleted |

No new Python module. Bucket probe reuses `uv run python -m tools bucket preflight`.

---

## `tools/scripts/setup.sh`

### Invocation

```bash
bash tools/scripts/setup.sh           # base: plugin contributor
bash tools/scripts/setup.sh --dev     # full: developer
bash tools/scripts/setup.sh --dry-run # report only, no installs
```

### Package manager detection

Detected once at startup, in priority order: `apt` → `paru` → `pacman`. Stored in `PKG` variable. All installs use the detected manager.

### Steps — base (always)

Each step is an idempotent `ensure_<thing>()` function: checks if already satisfied, skips if so.

1. **`ensure_repo_root`** — locate repo root by walking up looking for `pyproject.toml` with `name = "bmt-gcloud"`. `cd` to it.
2. **`ensure_uv`** — `command -v uv`; if missing, run `curl -LsSf https://astral.sh/uv/install.sh | sh` and source the updated PATH.
3. **`ensure_gcloud`** — `command -v gcloud`; if missing, install:
   - apt: `google-cloud-cli` from the Google apt repo (add keyring + source list if needed)
   - paru: `google-cloud-cli-lite`
   - pacman: `google-cloud-cli-lite`
   After install, ensure `/opt/google-cloud-cli/bin` is on PATH for the session and appended to `~/.bashrc` / `~/.zshrc` / `~/.zshenv` as appropriate.
4. **`ensure_adc`** — run `gcloud auth application-default print-access-token` silently. If it fails (exit non-zero), run `gcloud auth application-default login` inline and wait for it to complete.
5. **`ensure_gcs_bucket`** — resolve directly: check `$GCS_BUCKET` env var, then fall back to `gh variable get GCS_BUCKET`. If neither resolves, print a clear message with the fix (`export GCS_BUCKET=<bucket>` or `gh variable set GCS_BUCKET --body <bucket>`) and exit 1.
6. **`uv sync`** — sync the full workspace (dev group included by default).
7. **`ensure_prek_hooks`** — same logic as `bootstrap_dev_env.sh`: skip if `core.hooksPath` is set or hooks already installed; otherwise `uv run prek install -t pre-commit -f && uv run prek install -t pre-push -f`.
8. **Bucket probe** — `uv run python -m tools bucket preflight`. Non-zero exit prints a clear message but does not fail the overall script (bucket may not be seeded yet on a brand-new environment).

### Steps — dev only (`--dev`)

Run after all base steps complete.

9. **`ensure_shellcheck`** — `command -v shellcheck`; if missing, install via `$PKG`.
10. **`ensure_actionlint`** — `command -v actionlint`; if missing: paru/pacman install via `$PKG`; apt falls back to the GitHub release binary (actionlint is not in Ubuntu's standard apt repos) — download the latest `actionlint_*_linux_amd64.tar.gz` from `https://github.com/rhysd/actionlint/releases/latest` and install to `~/.local/bin`.
11. **`ensure_pulumi`** — `command -v pulumi`; if missing, run `curl -fsSL https://get.pulumi.com | sh` and source `~/.pulumi/bin` into PATH.

### Dry-run mode

`--dry-run` skips all installs and `uv sync`/prek but still resolves and reports what would happen. Each `ensure_*` prints `[would install]` or `[ok]`. Bucket probe is skipped in dry-run.

### Output style

Plain `echo` with colour via ANSI codes (no external deps at this point in the script). Each step prints a single `==> Step name` header and either `ok` or the action taken. Final line is either `Setup complete.` or a list of failed steps.

---

## Justfile changes

```justfile
# Replace `onboard` with `setup`:
[group('setup')]
setup *args:
    bash tools/scripts/setup.sh {{ args }}
```

Remove the existing `onboard` recipe. Update the help text at the top of the Justfile.

---

## CONTRIBUTING.md changes

Replace the three-step "Install uv → Install just → just onboard" section with a single step: `just setup` (or `just setup --dev` for contributors who will edit CI/infra). Keep the manual equivalent steps as a fallback block for environments without `just`.

---

## Success criteria

- A fresh Ubuntu 22.04 machine with only `git` and `just` can run `just setup` and end up with a working `just deploy` (assuming `GCS_BUCKET` is resolvable).
- `just setup --dev` produces a machine where `just test` passes.
- Re-running `just setup` on an already-configured machine is fast and produces no errors.
- `--dry-run` produces no side effects.
