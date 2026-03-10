# Getting ci/check-bmt-gate fully up to date

## Current state

- **origin/ci/check-bmt-gate** has PR #233 merged (permissions fix at e0bacbb54). It does **not** have the later workflow/action improvements (they were never committed).
- **Local branch** `test/check-bmt-gate-workflow-optimizations` has **uncommitted** changes that implement:
  - checkout-and-restore composite used in all BMT jobs
  - Removal of handoff-skip (classify fails when no legs)
  - write-summary as success path, failure-fallback only on failure
  - workflow_call.outputs + bmt-outcome job
  - bmt-gate-summary job in build-and-test
  - Job names = job id only
  - Comment/description tidy, Cloud Run env commented out
  - New action: `.github/actions/checkout-and-restore/` (untracked)
  - Action updates: bmt-classify-handoff (fail on no legs), bmt-failure-fallback (drop handoff_skip_result), restore-snapshot (comment)

- **Stash (stash@{0})** contains a **different** change set: migration from bash scripts to Python/uv (`bmt_workflow.sh`, `ci_workflow.sh` removed; actions call `uv run --project .github/bmt bmt ...`). That refactor depends on the Python CLI (e.g. `.github/bmt/cli/`, `bootstrap_gh_vars.py`, etc.) and would conflict with the current workflow file changes. Treat it as a **separate PR** after this one.

## Steps to make ci/check-bmt-gate up to date (workflow improvements only)

1. **Commit workflow improvements** on `test/check-bmt-gate-workflow-optimizations`:
   - Add `.github/actions/checkout-and-restore/`
   - Commit changes to:
     - `.github/workflows/bmt.yml`
     - `.github/workflows/build-and-test.yml`
     - `.github/actions/bmt-classify-handoff/action.yml`
     - `.github/actions/bmt-failure-fallback/action.yml`
     - `.github/actions/restore-snapshot/action.yml`
   - Do **not** commit untracked CLI/config (e.g. `.github/bmt/cli/`, `uv.lock`) unless you are ready for the bash→Python migration.

2. **Push** the branch and **open a PR** into `ci/check-bmt-gate`. Merge after CI passes.

3. **Stash:** Leave as-is for a follow-up “BMT bash→Python” PR, or apply on a new branch and resolve conflicts with the workflow files (then PR into ci/check-bmt-gate).

## What is *not* in the stash (already in your working tree)

The stash does **not** add the following; they exist only in your local workflow/action edits:

- checkout-and-restore usage in bmt.yml
- Removal of handoff-skip job and “no legs” path
- write-summary / failure-fallback structure and bmt-outcome
- workflow_call.outputs and bmt-gate-summary
- Job id–only names and comment/description improvements

So **nothing from the stash is required** to get ci/check-bmt-gate up to date with the workflow improvements. The stash is an additional, optional refactor (bash→Python).
