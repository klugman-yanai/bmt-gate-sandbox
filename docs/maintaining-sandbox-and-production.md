# Maintaining sandbox and production without drift

You have **full permissions** on **bmt-gate-sandbox** (klugman-yanai) but **not admin** on **core-main** (Kardome-org). That affects how you change workflows and how to keep the two from drifting.

## How to manage drift (concrete)

**1. Compare `.github` between core-main and bmt-gcloud**

- **Map of what exists where:** [docs/drift-core-main-vs-bmt-gcloud.md](drift-core-main-vs-bmt-gcloud.md) lists every relevant file under `.github/` in both repos and which must stay in sync.
- **Run the diff** from bmt-gcloud repo root:
  ```bash
  export CORE_MAIN=/path/to/kardome/core-main   # or clone next to bmt-gcloud as ../core-main
  just diff-core-main
  ```
  This diffs `workflows/bmt.yml`, all `actions/bmt-*/action.yml`, `setup-gcp-uv`, and `.github/bmt/` (excluding secrets and cache). Exit code 1 if any differ.

**2. Use the diff to decide direction**

- **Only in bmt-gcloud** → Propose adding to core-main via PR, or treat as dev-only.
- **Only in core-main** → Add to bmt-gcloud if you want to mirror, or accept as prod-only (e.g. `checkout-and-restore`, `setup-build-env`).
- **Different content** → Either open a PR to core-main with bmt-gcloud’s version (bmt-gcloud is source), or update bmt-gcloud from core-main (core-main is source for that file).

**3. Run the diff regularly**

After pulling both repos, run `just diff-core-main`. Fix drift by either updating bmt-gcloud and re-syncing sandbox, or opening a PR to core-main. See [drift-core-main-vs-bmt-gcloud.md](drift-core-main-vs-bmt-gcloud.md) for intentional differences (e.g. `build-and-test.yml` vs `dummy-build-and-test.yml`).

---

## What the permission difference means

| | bmt-gate-sandbox | core-main (production) |
|---|------------------|-------------------------|
| **You can** | Push directly, change workflows, branch protection, secrets, vars | Open PRs, review, merge if you have merge rights |
| **You cannot** | — | Merge without approval, change protected branches or org secrets, force workflow changes |
| **Risk** | You can keep it in sync with your source of truth easily | Production may be updated by others or your PRs may sit unmerged → drift |

So: **sandbox** is under your control; **production** is not. Any workflow change in production depends on someone with access merging your PR (or making equivalent changes).

## Strategy: single source of truth

**Use bmt-gcloud as the single source of truth** for BMT workflow logic and structure.

- **bmt-gcloud** — You maintain workflows here (e.g. `dummy-build-and-test.yml`, `bmt.yml`, actions). This is where changes are **authored**.
- **bmt-gate-sandbox** — You have full control. Update it **from bmt-gcloud** whenever you change workflows (copy/build from bmt-gcloud). No need to wait on anyone.
- **core-main** — You **propose** changes via PRs from bmt-gcloud (or a branch that matches it). Admins/maintainers merge. You cannot force sync.

That way you never maintain two different “truths” by hand: you only maintain bmt-gcloud, then propagate to sandbox (direct) and to production (via PR).

## Maintenance flow

1. **Author in bmt-gcloud**  
   Edit `.github/workflows/dummy-build-and-test.yml`, `bmt.yml`, `.github/actions/*`, etc. Test locally (e.g. `just lint`, tests, and [testing production CI locally](testing-production-ci-locally.md) if applicable).

2. **Deploy to sandbox**  
   Copy the updated workflow(s) and actions into klugman-yanai/bmt-gate-sandbox (e.g. `dummy-build-and-test.yml` → sandbox `build-and-test.yml`). Commit and push. You have full permissions, so no approval step. Use this to validate behavior before proposing to production.

3. **Propose to production**  
   Open a PR to Kardome-org/core-main that brings in the **same** workflow/action changes (same triggers, concurrency, bmt-handoff condition, job structure). Describe that the PR aligns production with the sandbox/bmt-gcloud source so both stay in sync. If you keep a branch in core-main that tracks bmt-gcloud (e.g. by re-applying patches or copying files), the PR is “sync from bmt-gcloud” rather than ad-hoc edits.

4. **Track production**  
   Periodically pull core-main and diff workflow files against bmt-gcloud. If production has diverged (e.g. someone else changed `build-and-test.yml` or `bmt.yml`), you can either:
   - Align bmt-gcloud with production (if the production change is the desired behavior), then re-sync sandbox and optionally open a follow-up PR, or
   - Open a PR to production to revert or re-align with bmt-gcloud, with a short note that bmt-gcloud is the source of truth for BMT workflow shape.

## Reducing drift in practice

- **One place to edit**  
  Always change workflow logic and structure in bmt-gcloud first. Sandbox and production are consumers, not sources of truth.

- **Same checklist for both**  
  When you change triggers, concurrency, or bmt-handoff condition, use the same list for both repos:  
  “Update sandbox: copy X → build-and-test.yml, push. Update production: open PR with same X.”

- **Document the sync**  
  In PRs to core-main, mention that the change matches bmt-gcloud (and sandbox) so reviewers know it’s intentional alignment, not a one-off edit.

- **Optional: sync script or Just recipe**  
  A small script or `just` recipe can: (1) Copy `dummy-build-and-test.yml` → a file or directory used for sandbox/production, or (2) Generate a patch of bmt-gcloud vs core-main for workflow files. That makes “sync from bmt-gcloud” repeatable and reduces copy-paste mistakes.

- **Accept that production can lag**  
  Production will only stay in sync when your PRs are merged. Until then, sandbox can be ahead. That’s acceptable as long as you know: “sandbox = current source of truth; production = proposed via PR.”

## Summary

| Repo | Your role | How it stays in sync |
|------|-----------|----------------------|
| **bmt-gcloud** | Author workflows and BMT logic | You maintain it; it is the source of truth. |
| **bmt-gate-sandbox** | Full control | You update from bmt-gcloud whenever you change workflows (copy/build and push). |
| **core-main** | Contributor (PRs) | You open PRs that mirror bmt-gcloud; drift is limited by merging those PRs and by periodically diffing production vs bmt-gcloud. |

You maintain **one** workflow story in bmt-gcloud, push it to the sandbox directly, and propose the same story to production via PRs; that keeps drift manageable despite not having admin on core-main.
