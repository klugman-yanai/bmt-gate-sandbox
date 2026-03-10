# Trim-the-fat: bmt-gcloud repo clutter and root layout

## Summary

- **Remove:** Windows Zone.Identifier artifact; root-level reference workflow copy (move to archive).
- **Fix:** Stale paths in `config/bmt/`; allow `packages` in layout policy.
- **Optional later:** Consolidate `.github/bmt` vs `packages/bmt-cli` to one CLI location; trim `docs/plans` to active-only.

---

## 1. Removed / moved (done)

| Item | Action | Reason |
|------|--------|--------|
| `docs/plans/PLAN.md:Zone.Identifier` | Deleted | Windows NTFS zone identifier; not useful in repo. |
| `original_build-and-test.yml` (root) | Moved to `docs/archive/original_build-and-test.yml` | Reference copy only; keeps root clean. Policy updated to drop it from allowed root. |

**Still to do (manual):** *(none — canary removed from tracking, cursor plan moved to `docs/plans/archive/cursor/`.)*

---

## 2. Root folders: what belongs at top level

| Root entry | Verdict | Notes |
|------------|---------|--------|
| **`.github/`** | Keep | Workflows and actions; standard. |
| **`config/`** | Keep | Repo-level env contract, repo vars, BMT bootstrap env files. |
| **`deploy/`** | Keep | Canonical mirror for bucket `code/` and `runtime/`; required. |
| **`docs/`** | Keep | Architecture, configuration, plans. |
| **`packages/`** | Keep | Contains `bmt-cli`; used by workflows. Policy updated to allow. |
| **`scripts/`** | Keep | Only `scripts/hooks/pre-commit-sync-remote.sh`; required by policy. Could move to `.github/scripts/hooks` later. |
| **`tools/`** | Keep | Bucket sync, BMT run, gh_* helpers; core devtools. |
| **`tests/`** | Keep | Pytest suite. |
| **`original_build-and-test.yml`** | Moved | Was reference copy; now under `docs/archive/`. |

**Optional future:** Move `scripts/hooks/` into `.github/` (e.g. `.github/scripts/hooks/`) and point pre-commit there so the only root dir for “scripts” is not a single hook.

---

## 3. Bloat and redundancy

### 3.1 Dual CLI locations (`.github/bmt` and `packages/bmt-cli`)

Workflows reference **both** with fallbacks (e.g. `uv run --project .github/bmt bmt ...` then `uv run --project packages/bmt-cli bmt ...`). That duplicates surface and can cause drift.

- **Recommendation:** Pick one source of truth (e.g. `packages/bmt-cli` only), update all actions to use it, and remove or archive the other. Defer to a dedicated refactor.

### 3.2 `config/bmt/` vs `tools/gh_repo_vars.py`

- **`config/bmt/`** — Shell bootstrap: `bootstrap_gh_vars.sh`, `.env.example`, `.env.dev`, `.env.prod`. Used for `gh variable set` / `gh secret set` from env files.
- **`tools/gh_repo_vars.py`** — Python tool; Justfile uses it for `show-vars` / `apply-vars`.

Both are valid: shell for one-off bootstrap from env files, Python for programmatic apply. Comments in `config/bmt/*` referenced the old path `.github/bmt/config/`; updated to `config/bmt/`.

### 3.3 Plans and docs

- **`docs/plans/`** — Several plans (PLAN.md, bmt-support-plan, migration-to-production, future-architecture, high-level-design-improvements). Keep as-is; optionally add `docs/plans/archive/` for completed or superseded plans and move them there.
- **`docs/communication-flow.md`**, **`docs/implementation.md`** — Referenced from README and CLAUDE; keep.

### 3.4 Forbidden / ignored

- **`.cursor/plans/`** — In `.gitignore` and policy; must not be tracked. Policy already requires moving plan artifacts to `docs/plans/archive/cursor/` if present.
- **`debug/`**, **`resources/`** — Forbidden by policy; no change.

---

## 4. Layout policy updates (done)

- **`ALLOWED_TRACKED_TOP_LEVEL`:** Removed `original_build-and-test.yml`; added `packages`.
- **`REQUIRED_PATHS`:** Unchanged (workflows, deploy/code, deploy/runtime, scripts/hooks).

---

## 5. Not committed (unchanged)

Per CLAUDE.md / .gitignore: `data/`, `sk_runtime/`, `local_batch/`, `gcp-key.json`, `.local/diagnostics/`, `secrets/`, `.cursor/plans/`. No change.

---

## 6. Merge conflict leftovers

After merging `redesign/modern-convention` into `dev`, some files still have conflict markers (e.g. CLAUDE.md, Justfile). Those should be resolved in a separate pass (keep dev layout: `deploy/`, `tools/`, and either `.github/bmt` or `packages/bmt-cli` consistently).
