---
name: BMT CI migration to core-main
overview: Stabilize bmt-gate-sandbox first (hard blocking gate), then sync bmt-gcloud/VM state and migrate .github changes into core-main using a clean, reviewable PR path. Do not proceed to core-main migration while sandbox reliability is unstable.
todos: []
isProject: false
---

# BMT CI migration: bmt-gcloud → sandbox → core-main (PR 232)

> **For Claude:** When implementing this plan, use the executing-plans skill task-by-task.

**Goal:** Make sandbox CI/BMT reliable first, then sync bmt-gcloud as source of truth to sandbox/VM and migrate `.github` CI into core-main through a clean production PR.

**Architecture:** bmt-gcloud is authored first and mirrored to sandbox. Sandbox must pass a reliability gate before any core-main migration. After sandbox and VM are stable, core-main receives only drift-list files from bmt-gcloud and is merged via a clean, minimal PR path to `dev`. No direct production merge before sandbox reliability is proven.

**Tech stack:** Git, GitHub Actions, Just, gcloud CLI, uv; repos: bmt-gcloud, klugman-yanai/bmt-gate-sandbox, Kardome-org/core-main.

---

## Current state (verified 2026-03-10)

**Note:** Branch positions and commit SHAs below are a snapshot; re-verify with `git status` and `git log` in each repo before starting.

- **bmt-gcloud** (`/home/yanai/sandbox/bmt-gcloud`): On `ci/check-bmt-gate` at `4228fb5ee` (pushed), but working tree is **not clean** (`deploy/` has many untracked files).
- **core-main** (`/home/yanai/kardome/core-main`): Currently on `ci/bmt-gate-final` at `b7d56e80b` (not on `test/check-bmt-gate-workflow-optimizations`).
- **PR 232** (`ci/bmt-gate-final` → `dev`): Open and blocked. Branch has large divergence from `dev` (`origin/dev...origin/ci/bmt-gate-final` = `35` left, `105` right), so the previous "two commits total" assumption is invalid.
- **Sandbox reliability** (`klugman-yanai/bmt-gate-sandbox`): Mixed success/failure on 2026-03-10. Repeated failures include workflow-file invalid runs, VM pool contention/stale-trigger blocking, and handshake timeouts (`vm_status=TERMINATED/STOPPING`).
- **Drift check**: `CORE_MAIN=/home/yanai/kardome/core-main just diff-core-main` currently fails (extra files only in core-main under `.github/bmt`, including `scripts/` and `README.md`).

**Source of truth**: [maintaining-sandbox-and-production.md](../maintaining-sandbox-and-production.md) — bmt-gcloud is the author repo; sandbox and core-main consume from it. [drift-core-main-vs-bmt-gcloud.md](../drift-core-main-vs-bmt-gcloud.md) lists the exact files that must stay in sync.

---

## Before starting: commit and push your local changes

Commit and push any local changes in **bmt-gcloud** and/or **core-main** before executing the plan. That way Phase 1 (reconciling with origin) and later steps work with your intended state and you don't lose or overwrite uncommitted work.

---

## Phase 0: sandbox reliability gate (mandatory, blocking)

**Goal:** `bmt-gate-sandbox` must be reliably green before any core-main migration work.

1. **Fix known failure modes in sandbox first**

- Address workflow-definition breakages that produce runs with no jobs ("This run likely failed because of a workflow file issue").
- Address release/build infra breakages (for example, setup/download regressions such as 404s).
- Address runtime handoff instability:
  - no VM available (single-VM pool saturation),
  - stale trigger/race conditions (existing trigger file blocks new run),
  - handshake timeout where VM stays `TERMINATED`/`STOPPING`,
  - handshake acknowledged but zero runtime-supported legs.

1. **Instrument and verify root cause closure**

- For each fix, capture one failing run and one succeeding rerun proving the specific failure mode is gone.
- Keep a short table of run IDs + failure reason + commit that fixed it.

1. **Reliability exit criteria (all required)**

- At least **5 consecutive successful CI runs** on `ci/check-bmt-gate` (mix of `push` and `pull_request` events).
- No workflow-file invalid runs in that window.
- No `bmt-handoff` failure due VM unavailable/stale trigger/handshake timeout in that window.
- At least one successful end-to-end BMT handoff where runtime legs are accepted and gate passes.

> **Do not proceed to Phase 1+ until all Phase 0 exit criteria are met.**

---

## Phase 1: bmt-gcloud stable and up to date

**Goal:** One clear, committed state in bmt-gcloud that reflects all tested workflow/action/deploy changes.

1. **Reconcile local vs origin**

- Local `ci/check-bmt-gate` is behind 4. Decide:
  - **Option A:** Discard local changes and align to origin: `git checkout -- . && git clean -fd .github deploy && git pull origin ci/check-bmt-gate` (only if local M/D are not needed).
  - **Expected (Option A):** `git status` shows clean working tree; branch matches `origin/ci/check-bmt-gate`.
  - **Option B:** Keep local changes: create a backup branch, pull (or merge) `origin/ci/check-bmt-gate`, then re-apply or merge local changes, resolve conflicts, and produce a single consolidated commit (or small set) that includes VM reuse, merged BMT job, and any deploy/ or action fixes you care to keep.
  - **Expected (Option B):** No uncommitted workflow/deploy changes you care about; branch is ahead of or equal to what you want in sandbox and core-main.
- After this, `ci/check-bmt-gate` in bmt-gcloud should be **ahead of or equal to** what you want in sandbox and core-main, with no uncommitted workflow/deploy changes you care about.

1. **Optional: single clean commit on bmt-gcloud**

- If history is messy, rebase `ci/check-bmt-gate` onto a suitable base (e.g. `main` or `origin/ci/check-bmt-gate`) and squash to one commit like "ci: BMT workflow and deploy sync — VM reuse, merged gate job, actions, deploy updates". Then force-push (only to your branch).
- **Expected:** Rebase completes without conflict (or resolve conflicts keeping intended content); push succeeds.

---

## Phase 2: bmt-gate-sandbox fully up to date with bmt-gcloud

**Goal:** Sandbox repo runs the same triggers, concurrency, and BMT handoff as the state you will propose for production.

1. **Copy from bmt-gcloud to sandbox**

- In bmt-gcloud (after Phase 1), copy the **exact** `.github` surface that must match production:
  - [drift doc](../drift-core-main-vs-bmt-gcloud.md): `workflows/bmt.yml`, `actions/bmt-prepare`, `bmt-classify-handoff`, `bmt-handoff-run`, `bmt-write-summary`, `bmt-failure-fallback`, `setup-gcp-uv`, and `.github/bmt/` (excluding secrets, `__pycache__`, `.ruff_cache`, `.gitignore`).
  - Main CI: bmt-gcloud uses `.github/workflows/build-and-test.yml` (dummy build). Per [sandbox-mirror-production.md](../sandbox-mirror-production.md), sandbox should use the **same filename** `build-and-test.yml` and same triggers/concurrency/bmt-handoff condition.
- Clone or open the sandbox repo (e.g. `git clone https://github.com/klugman-yanai/bmt-gate-sandbox.git` or use core-main's `sandbox` remote). Overwrite the listed paths with bmt-gcloud's versions. Example (from bmt-gcloud repo root, with `SANDBOX_REPO` set to sandbox repo path): `rsync -av --exclude='*.pem' --exclude='__pycache__' --exclude='.ruff_cache' --exclude='.gitignore' .github/ "$SANDBOX_REPO/.github/"`. Then commit and push to the branch you use for testing (e.g. `ci/check-bmt-gate` or `dev`). No PR needed; you have full permissions.
- **Expected:** Sandbox `.github` matches bmt-gcloud for the drift-list paths; push succeeds.

1. **Smoke-check**

- Trigger a run on sandbox (e.g. push to `ci/check-bmt-gate` or open a PR). **Use a PR** to properly monitor expected behavior: open a PR targeting `ci/check-bmt-gate` (or `dev`), then watch the PR Checks tab for workflow jobs and BMT gate outcome. Confirm: triggers, concurrency, BMT handoff condition, and job topology match what you expect for production.
- **Expected:** Workflow runs; BMT handoff runs when branch is dev or ci/check-bmt-gate; job names and order match production intent.
- **Gate:** This phase is complete only when Phase 0 reliability exit criteria are satisfied.

---

## Phase 3: VM fully updated, synced, and stable

**Goal:** VM and GCS reflect the same deploy/code and config as in bmt-gcloud.


1. **Sync deploy/ to GCS**

- From bmt-gcloud: `GCS_BUCKET=<bucket> just sync-remote` then `just verify-sync`. Fix any layout or contract issues so the bucket matches [deploy layout](../../CLAUDE.md).
- **Expected:** `sync-remote` and `verify-sync` exit 0; no layout errors.

1. **VM metadata and startup**

- If the workflow or scripts push VM metadata (bucket, repo root, etc.): run the sync step used by CI. From bmt-gcloud: `uv run --project packages/bmt-cli bmt sync-vm-metadata` (or the equivalent from your workflow; set `GCS_BUCKET`, `GCP_PROJECT`, etc. as required). Ensure VM startup (e.g. `deploy/code/bootstrap/startup_wrapper.sh`) pulls `code/` from the bucket and that the image/script set is up to date.
- **Expected:** VM metadata updated (or skip if not used); VM startup script and bucket are in sync.

1. **Stability**

- Optionally run a full E2E (trigger from sandbox → VM picks up → gate pass/fail). Document any flakiness or config fixes and apply them in bmt-gcloud, then re-sync (Phase 1/2/3) as needed.

---

## Phase 4: core-main — migrate .github from bmt-gcloud and align branches

**Goal:** Add bmt-gcloud's `.github` changes to the **current** `test/check-bmt-gate-workflow-optimizations` branch. Rebase that branch (e.g. onto `ci/check-bmt-gate`), then merge it into `ci/check-bmt-gate`. Finally, update `ci/bmt-gate-final` with a **second commit** so PR 232 shows two commits total.

**Do not stage or commit in core-main:** Exclude `bmt.code-workspace` from any `git add` or commits in core-main during this migration (local workspace file; should not be part of the PR).

### Drift-list paths (copy these)

Copy **only** these paths from bmt-gcloud into core-main (same paths under `.github/`):

- `.github/workflows/bmt.yml`
- `.github/actions/bmt-prepare/action.yml`
- `.github/actions/bmt-classify-handoff/action.yml`
- `.github/actions/bmt-handoff-run/action.yml`
- `.github/actions/bmt-write-summary/action.yml`
- `.github/actions/bmt-failure-fallback/action.yml`
- `.github/actions/setup-gcp-uv/action.yml`
- `.github/bmt/` — whole tree. **Exclude:** `*.pem`, `__pycache__`, `.ruff_cache`, `.gitignore`

For `build-and-test.yml`: core-main keeps **real** build steps; update only triggers, concurrency, bmt-handoff condition, and job topology to align with bmt-gcloud (do not replace with the dummy file).

1. **Check current core-main vs bmt-gcloud**

- **Step A:** From bmt-gcloud: `CORE_MAIN=/home/yanai/kardome/core-main just diff-core-main`. Resolve any drift by treating **bmt-gcloud as source**: you will overwrite core-main's listed files with bmt-gcloud's versions in the next step.
- **Expected:** Exit 0 with no diff, or a documented list of differences you will fix by copying from bmt-gcloud.

1. **Verify unstaged / branch state on core-main**

- **Step B:** In core-main: `git status` and confirm branch is `test/check-bmt-gate-workflow-optimizations` and there are no unintended staged files (e.g. `bmt.code-workspace` must not be staged).
- **Expected:** Branch correct; no `bmt.code-workspace` in staged files.

1. **Add bmt-gcloud changes to `test/check-bmt-gate-workflow-optimizations`, then rebase**

- **Step C:** Copy from bmt-gcloud into core-main **only** the [Drift-list paths](#drift-list-paths-copy-these) above. For `build-and-test.yml`: update only triggers, concurrency, bmt-handoff condition, job topology (do not replace with dummy file).
- **Step D:** Stage only the drift-list paths so `bmt.code-workspace` is never included. Example (run from core-main repo root):

  ```bash
  git add .github/workflows/bmt.yml \
    .github/actions/bmt-prepare/action.yml \
    .github/actions/bmt-classify-handoff/action.yml \
    .github/actions/bmt-handoff-run/action.yml \
    .github/actions/bmt-write-summary/action.yml \
    .github/actions/bmt-failure-fallback/action.yml \
    .github/actions/setup-gcp-uv/action.yml \
    .github/bmt/
  ```

  Do **not** run `git add .` or `git add bmt.code-workspace`.
- **Step E:** Commit: `git commit -m "ci(bmt): sync with bmt-gcloud — VM reuse, merged gate job, actions, triggers"`. Then from bmt-gcloud run `just diff-core-main` again.
- **Expected (Step E):** Commit succeeds; diff-core-main exits 0 with no BMT surface diff (or only intentional differences).
- **Step F:** Rebase: `git checkout test/check-bmt-gate-workflow-optimizations && git fetch origin ci/check-bmt-gate && git rebase origin/ci/check-bmt-gate` (or `git rebase ci/check-bmt-gate` if you have it updated). Resolve any conflicts; keep the migrated .github content.
- **Expected (Step F):** Rebase completes (clean or after resolving conflicts); no .github content reverted.

1. **Merge into `ci/check-bmt-gate`**

- After the rebase, merge `test/check-bmt-gate-workflow-optimizations` into `ci/check-bmt-gate`: `git checkout ci/check-bmt-gate && git pull origin ci/check-bmt-gate`, then `git merge test/check-bmt-gate-workflow-optimizations` (or merge via a PR). Resolve conflicts if any; keep the migrated .github content. Push `ci/check-bmt-gate`.
- **Expected:** Merge succeeds (or conflicts resolved); `git push origin ci/check-bmt-gate` succeeds.

1. **Update `ci/bmt-gate-final` with a second commit (no squash or rebase)**

- **Goal:** PR 232 (ci/bmt-gate-final → dev) should show **two commits**: (1) the existing "BMT gate final" commit, (2) the new bmt-gcloud sync. Do **not** squash or rebase; add the new work as a second commit.
- **Recommended: merge:**
  - `git checkout ci/bmt-gate-final && git pull origin ci/bmt-gate-final`.
  - `git merge ci/check-bmt-gate` (after ci/check-bmt-gate has the workflow-optimizations merge). Resolve conflicts; keep the migrated .github content.
  - Push `ci/bmt-gate-final`. The PR will show: commit 1 (existing), commit 2 (merge commit or the single "sync with bmt-gcloud" commit from ci/check-bmt-gate).
- **Expected:** PR 232 shows exactly two commits; `just diff-core-main` from bmt-gcloud shows no BMT surface diff.
- **Alternative: direct second commit:** Checkout `ci/bmt-gate-final`, copy the drift-list files from bmt-gcloud into core-main's `.github/` (same as in step 4b), then `git add .github/` (or add only the changed files under `.github/`) and `git commit -m "ci(bmt): sync with bmt-gcloud — VM reuse, merged gate job, actions"`. **Do not stage** `bmt.code-workspace`. Push. PR 232 then shows exactly two commits.
- Ensure `ci/bmt-gate-final`'s `.github` matches bmt-gcloud (and sandbox) and passes `just diff-core-main`.

1. **PR 232 — stop here; merge is manual**

- Refresh the PR (base `dev`, head `ci/bmt-gate-final`). The PR will show two commits. Re-request review if needed.
- **Expected:** PR 232 displays two commits; review requested; CI runs (if configured).
- **Do not merge in this plan.** The actual merge of PR 232 into `dev` is done **manually** by a code owner after approval.

---

## Phase 5: dev fully up to date with tested behavior (after manual merge)

**Goal:** After a code owner merges PR 232 into `dev`, `dev` will have the same BMT CI behavior you validated in sandbox and on `ci/check-bmt-gate`. This plan does not perform the merge. After the merge, optionally trigger a run on `dev` and confirm gate and VM behavior.

---

## Branch name note

- Workflow triggers in core-main's `build-and-test.yml` mention both `test/check-bmt-gate-*` and `test/workflow-optimizations`. The branch you use is `test/check-bmt-gate-workflow-optimizations`. The plan treats this as the branch to add changes to, rebase, and merge; if you also use a separate `test/workflow-optimizations` branch, apply the same migration there or point triggers to the single rebased branch.

---

## Checklist summary

| Step | Where                   | Action                                                                                                                                   |
| ---- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | bmt-gcloud / core-main  | ✅ **Commit and push** any local changes before starting                                                                                    |
| 1    | bmt-gcloud              | ✅ Reconcile local vs origin; single clean state on `ci/check-bmt-gate`                                                                     |
| 2    | bmt-gate-sandbox        | ✅ Copy .github (and main workflow) from bmt-gcloud; push; smoke-check                                                                      |
| 3    | bmt-gcloud / GCS / VM   | ✅ `just sync-remote`, `just verify-sync`; sync VM metadata; confirm startup                                                                |
| 4a   | core-main               | Run `just diff-core-main`; treat bmt-gcloud as source                                                                                    |
| 4b   | core-main               | Add bmt-gcloud .github; commit; **rebase** (e.g. onto ci/check-bmt-gate). Do not merge yet.                                              |
| 4c   | core-main               | Merge `test/check-bmt-gate-workflow-optimizations` into `ci/check-bmt-gate`; push `ci/check-bmt-gate`.                                   |
| 4d   | core-main               | Add **second** commit to `ci/bmt-gate-final` (merge ci/check-bmt-gate or copy); push - no squash or rebase                               |
| 4e   | core-main               | PR 232: refresh, re-request review; **stop here** - merge into `dev` done manually by code owner after approval                          |
| 5    | core-main               | After code owner merges PR 232, optionally confirm `dev` runs BMT as in sandbox                                                          |

---

## Execution

To run this plan task-by-task, use the **executing-plans** skill in a session (or worktree).

- **Option A (this session):** Step through each phase with verification; mark checklist items as you go.
- **Option B (dedicated session):** Open a new session in the same worktree, use executing-plans, and run by checklist with checkpoints after each phase.

---

## Risks and mitigations

- **bmt-gcloud "behind 4" and local M/D:** Resolving by discarding local changes (Option A) can lose deploy/ or action tweaks. Prefer Option B and explicitly decide which local changes to keep before pulling/merging.
- **Production build-and-test.yml:** Only sync structure, triggers, concurrency, and BMT job shape from bmt-gcloud; do not overwrite real build steps with dummy steps.
- **Force-push:** Use only on your own branches (`ci/check-bmt-gate`, `ci/bmt-gate-final`, `test/check-bmt-gate-workflow-optimizations`); avoid force-pushing shared branches without agreement.
