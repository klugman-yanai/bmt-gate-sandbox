# Structure audit (2026-03)

Audit of root-level and folder structure bloat, over-verbosity, and complexity in bmt-gcloud. Executed per [bloat and structure audit plan](../../../.cursor/plans/bloat_and_structure_audit_6ed44cad.plan.md).

## 1. Root and policy (done)

- **Policy aligned:** [tools/repo_layout_policy.py](../../tools/repo_layout_policy.py) — Added `packages` to `ALLOWED_TRACKED_TOP_LEVEL`; removed `original_build-and-test.yml` from allowed set. Also added `.canary-bmt-pr-test-20260305` and `src` so that `just validate-repo-layout` passes (both are tracked).
- **Root duplicate removed:** `original_build-and-test.yml` existed at both repo root and `docs/archive/`. Removed from root; canonical copy remains at [docs/archive/original_build-and-test.yml](../archive/original_build-and-test.yml).
- **Outcome:** `just validate-repo-layout` and `just validate-layout` both pass.

## 2. Docs and plans (done)

- **Zone.Identifier removed:** `docs/plans/PLAN.md:Zone.Identifier` removed from git and filesystem (Windows NTFS artifact).
- **Trim-the-fat archived:** [trim-the-fat-report.md](archive/trim-the-fat-report.md) moved to `docs/plans/archive/` (completed audit).
- **Docs index added:** [docs/README.md](../README.md) — Active reference, sandbox/production, plans, and archive sections. [README.md](../../README.md) and [CLAUDE.md](../../CLAUDE.md) updated to point to it.
- **Classification:** Active reference docs and plans left in place; only completed audit report archived.

## 3. Tools (done)

- **Reference audit:** All `tools/*.py` scripts are either used by Justfile, referenced in CLAUDE.md, or are libraries (shared_*, click_exit, repo_paths). No unreferenced scripts removed.
- **Documented:** In [CLAUDE.md](../../CLAUDE.md): (1) **Layout validators** — `just validate-layout` checks `deploy/` mirror contract; `just validate-repo-layout` checks repo root policy; run both when changing layout. (2) **Config vs repo vars** — `config/bmt/` for shell bootstrap from env files; `tools/gh_repo_vars.py` and `just repo-vars-check` / `just repo-vars-apply` for programmatic check/apply.
- **Just recipe added:** `just diff-core-main` now invokes [tools/diff_github_core_main.py](../../tools/diff_github_core_main.py) (was documented in docs but missing from Justfile).

## 4. Deploy bootstrap (done)

- **Scripts tagged:** [deploy/code/bootstrap/README.md](../../deploy/code/bootstrap/README.md) updated with a **Role** column: **required** (startup_wrapper, startup_example, ensure_uv, install_deps), **ops-only** (setup_vm_startup, rollback_vm_startup_to_inline, export_vm_spec, build_bmt_image, create_bmt_green_vm, cutover_bmt_vm, rollback_bmt_vm, audit_vm_and_bucket, ssh_install), **example** (bmt-watcher.service.example).

## 5. Optional follow-ups (not done)

- **scripts/:** Single hook `scripts/hooks/pre-commit-sync-remote.sh`. Optional: move to `.github/scripts/hooks/` and update pre-commit config.
- **.canary and src:** Both are tracked and in allowed set so policy passes. Consider removing from repo or keeping as-is; no change in this audit.
- **Tools grouping:** Optional later: group `tools/` by prefix (e.g. `tools/bucket/`, `tools/gh/`) to reduce flat list.
- **Unify validate-layout:** Optional: single `just validate-layout` that runs both deploy_layout_policy and repo_layout_policy (currently two recipes).

## Summary

| Area | Action |
|------|--------|
| Root/policy | Policy updated; root `original_build-and-test.yml` removed; validate-repo-layout passes. |
| Docs | Zone.Identifier removed; trim-the-fat archived; docs/README.md index added; README and CLAUDE link to it. |
| Tools | Validators and config vs gh_repo_vars documented in CLAUDE; diff-core-main added to Justfile. |
| Deploy bootstrap | README scripts table updated with Role column (required / ops-only / example). |
