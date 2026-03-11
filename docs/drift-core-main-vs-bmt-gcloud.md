# Managing drift: core-main vs bmt-gcloud `.github`

This doc defines **what to compare** between Kardome-org/core-main and bmt-gcloud so you can manage drift concretely. Use the [diff script](#how-to-run-the-diff) below regularly.

## Side-by-side: what exists where

| Path under `.github/` | core-main | bmt-gcloud | Notes |
|-----------------------|-----------|------------|--------|
| **Workflows** | | | |
| `workflows/build-and-test.yml` | ✅ Main CI (real build) | ✅ Sandbox CI (dummy builds) | Same triggers/concurrency/BMT condition; bmt-gcloud uses minimal dummy build steps. |
| `workflows/bmt.yml` | ✅ | ✅ | **Must stay in sync.** Reusable BMT handoff. Diff these. |
| **Actions (BMT)** | | | |
| `actions/bmt-prepare/action.yml` | ✅ | ✅ | **Must stay in sync.** Use same project path `.github/bmt`. |
| `actions/bmt-classify-handoff/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-handoff-run/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-write-summary/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-failure-fallback/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-job-setup/action.yml` | ✅ | ❌ | Prod only (build-job setup). No equivalent in bmt-gcloud. |
| **Actions (build / checkout)** | | | |
| `actions/setup-gcp-uv/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/checkout-and-restore/action.yml` | ✅ | ❌ | Prod only (build job restores snapshot). |
| `actions/restore-snapshot/action.yml` | ✅ | ❌ | Prod only. |
| `actions/setup-build-env/action.yml` | ✅ | ❌ | Prod only (CMake/configure). |
| `actions/checkout-robust/action.yml` | ❌ | ✅ | bmt-gcloud only (e.g. handoff checkout fallback). |
| **BMT CLI / config** | | | |
| `bmt/` (Python CLI, config) | ✅ | ✅ | **Must stay in sync** for behavior. Both use `.github/bmt` only. |
| **Other** | | | |
| `actionlint.yaml` | ❌ | ✅ | bmt-gcloud only. |
| `README.md` | ❌ | ✅ | bmt-gcloud only. |
| `CODEOWNERS`, `PULL_REQUEST_TEMPLATE.md` | ✅ | ❌ | Prod repo policy; not BMT drift. |

## Files you must diff to manage drift

**Same path in both (content should align or be intentionally documented):**

- `.github/workflows/bmt.yml`
- `.github/actions/bmt-prepare/action.yml`
- `.github/actions/bmt-classify-handoff/action.yml`
- `.github/actions/bmt-handoff-run/action.yml`
- `.github/actions/bmt-write-summary/action.yml`
- `.github/actions/bmt-failure-fallback/action.yml`
- `.github/actions/setup-gcp-uv/action.yml`
- `.github/bmt/` (entire tree: `cli/`, `config/`, `pyproject.toml`, `uv.lock`, `resources/` — exclude secrets and `__pycache__`)

**Intentional differences (still compare when changing behavior):**

- Main CI: core-main has `workflows/build-and-test.yml` (real build), bmt-gcloud has `workflows/build-and-test.yml` (dummy). Triggers, concurrency, and **bmt** job `if` should match; job names and build steps differ.

## How to run the diff

From **bmt-gcloud** repo root, with core-main checked out locally (e.g. `../core-main` or `$CORE_MAIN`):

```bash
# Set path to core-main (default: ../core-main if present, else ../kardome/core-main)
CORE_MAIN="${CORE_MAIN:-$(realpath ../core-main 2>/dev/null || realpath ../kardome/core-main 2>/dev/null)}"

# 1) Diff workflows and BMT actions (files that exist in both)
for f in workflows/bmt.yml \
         actions/bmt-prepare/action.yml \
         actions/bmt-classify-handoff/action.yml \
         actions/bmt-handoff-run/action.yml \
         actions/bmt-write-summary/action.yml \
         actions/bmt-failure-fallback/action.yml \
         actions/setup-gcp-uv/action.yml; do
  if [[ -f "$CORE_MAIN/.github/$f" && -f ".github/$f" ]]; then
    echo "=== .github/$f ==="
    diff -u "$CORE_MAIN/.github/$f" ".github/$f" || true
  fi
done

# 2) Diff .github/bmt (exclude secrets and cache)
diff -rq "$CORE_MAIN/.github/bmt" .github/bmt \
  --exclude='*.pem' --exclude='__pycache__' --exclude='.ruff_cache' --exclude='*.egg-info' \
  --exclude='.gitignore' 2>/dev/null || true
diff -r "$CORE_MAIN/.github/bmt" .github/bmt \
  --exclude='*.pem' --exclude='__pycache__' --exclude='.ruff_cache' --exclude='*.egg-info' \
  --exclude='.gitignore' 2>/dev/null || true
```

Or use the Just recipe (see below).

## How to use the diff

1. **Run the diff** after pulling both repos (e.g. `git -C core-main pull`, `git pull` in bmt-gcloud).
2. **Interpret:**
   - **Only in bmt-gcloud:** Either add to core-main via PR (if it should exist in prod) or leave as dev-only.
   - **Only in core-main:** Either add to bmt-gcloud (if you want to mirror it) or accept as prod-only (e.g. checkout-and-restore, setup-build-env).
   - **Different content:** Decide direction:
     - **bmt-gcloud is source** → Open a PR to core-main with bmt-gcloud’s version (and note “aligns with bmt-gcloud”).
     - **core-main is source** → Update bmt-gcloud to match, then re-sync sandbox.
3. **Resolve merge conflicts** in bmt-gcloud (e.g. `.github/actions/bmt-prepare/action.yml`). Use `uv run --project .github/bmt` consistently in both repos.

## Intentional differences to keep documented

- **Main CI file name:** Production = `build-and-test.yml`; bmt-gcloud = `dummy-build-and-test.yml`. Sandbox gets a copy as `build-and-test.yml`.
- **Project path in actions:** Both use `uv run --project .github/bmt`; keep aligned.
- **Build-job actions:** core-main has checkout-and-restore, restore-snapshot, setup-build-env, bmt-job-setup for the real build pipeline. bmt-gcloud does not need these for the dummy workflow; no need to copy them unless you add a “real build” path to bmt-gcloud.
