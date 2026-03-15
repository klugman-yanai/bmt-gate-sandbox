# Sandbox and production

Single reference for keeping sandbox and production in sync, how the sandbox mirrors production, and managing drift between core-main and bmt-gcloud.

---

## Maintaining sandbox and production

You have **full permissions** on **bmt-gate-sandbox** (klugman-yanai) but **not admin** on **core-main** (Kardome-org). That affects how you change workflows and how to keep the two from drifting.

**How to manage drift**

1. **Compare `.github` between core-main and bmt-gcloud** — See [Drift: core-main vs bmt-gcloud](#drift-core-main-vs-bmt-gcloud) for the file map. From bmt-gcloud repo root, diff the paths listed there (e.g. `diff -r "$CORE_MAIN/.github/workflows/bmt-handoff.yml" .github/workflows/bmt-handoff.yml` and the actions/bmt* and `.github/bmt/` trees). Exit code 1 if any differ.

2. **Use the diff to decide direction** — Only in bmt-gcloud → propose adding to core-main via PR or treat as dev-only. Only in core-main → add to bmt-gcloud if you want to mirror, or accept as prod-only. Different content → either open a PR to core-main with bmt-gcloud's version, or update bmt-gcloud from core-main.

3. **Run the diff regularly** — After pulling both repos, diff the relevant paths. Fix drift by updating bmt-gcloud and re-syncing sandbox, or opening a PR to core-main.

**What the permission difference means**

| | bmt-gate-sandbox | core-main (production) |
| --- | --- | --- |
| **You can** | Push directly, change workflows, branch protection, secrets, vars | Open PRs, review, merge if you have merge rights |
| **You cannot** | — | Merge without approval, change protected branches or org secrets, force workflow changes |

**Strategy: single source of truth**

Use **bmt-gcloud as the single source of truth** for BMT workflow logic and structure.

- **bmt-gcloud** — You maintain workflows here. This is where changes are **authored**.
- **bmt-gate-sandbox** — Full control. Update from bmt-gcloud whenever you change workflows (copy/build from bmt-gcloud).
- **core-main** — You **propose** changes via PRs from bmt-gcloud. Admins merge. You cannot force sync.

**Maintenance flow**

1. **Author in bmt-gcloud** — Edit workflows and actions. Test locally (e.g. `just test`, and [development.md](development.md#testing-production-ci-locally) if applicable).
2. **Deploy to sandbox** — Copy updated workflow(s) and actions into klugman-yanai/bmt-gate-sandbox. Commit and push. Use this to validate before proposing to production.
3. **Propose to production** — Open a PR to Kardome-org/core-main with the **same** workflow/action changes. Describe that the PR aligns production with the sandbox/bmt-gcloud source.
4. **Track production** — Periodically pull core-main and diff workflow files against bmt-gcloud. Align bmt-gcloud with production if the production change is desired, or open a PR to production to re-align with bmt-gcloud.

**Summary**

| Repo | Your role | How it stays in sync |
| --- | --- | --- |
| **bmt-gcloud** | Author workflows and BMT logic | Source of truth; you maintain it. |
| **bmt-gate-sandbox** | Full control | Update from bmt-gcloud whenever you change workflows. |
| **core-main** | Contributor (PRs) | Open PRs that mirror bmt-gcloud; drift limited by merging and by periodically diffing. |

---

## Sandbox mirror production

The **bmt-gate-sandbox** repo (klugman-yanai/bmt-gate-sandbox) should mirror **production** (Kardome-org/core-main) as closely as possible so that testing in the sandbox validates the same flow and conditions that run in production.

**What must match**

| Aspect | Production (core-main) | Sandbox (bmt-gate-sandbox) |
| --- | --- | --- |
| **Main CI workflow file** | `.github/workflows/build-and-test.yml` | Same filename: `build-and-test.yml`. |
| **Triggers** | push: `dev` only; pull_request: `dev`, `ci/check-bmt-gate`, `test/check-bmt-gate-*`, etc. | Same triggers. |
| **Concurrency** | `group: ci-${{ github.repository }}-...`, `cancel-in-progress: true` | Same. |
| **BMT handoff condition** | Runs when branch is `dev` or `ci/check-bmt-gate` | Same condition. |
| **bmt-handoff.yml** | Reusable workflow; same inputs | Same; use same `.github/workflows/bmt-handoff.yml` and `.github/actions/*`. |

**Deploying to the sandbox repo**

1. **Workflow filename** — In bmt-gcloud the CI workflow may be `build-and-test.yml` (minimal dummy builds). For the sandbox repo, use the **same filename** `build-and-test.yml` so branch protection and tooling behave the same.
2. **Copy from bmt-gcloud to sandbox** — Copy `.github/workflows/build-and-test.yml`, `.github/workflows/bmt-handoff.yml`, and `.github/actions/*` from bmt-gcloud. Ensure sandbox has the same structure for BMT (`.github/bmt` as used by the workflow).
3. **Repo variables and secrets** — Use **sandbox** GCP/GitHub App configuration. Only **workflow shape and conditions** mirror production; credentials and resources stay sandbox-specific.

**Acceptable differences**

- **Build steps:** Sandbox uses minimal dummy build jobs; production runs full build and BMT staging. The **decision** to run BMT (triggers + bmt job condition) must be the same.
- **resolve-context job:** Sandbox can keep a `resolve-context` job; BMT handoff still uses the same condition.
- **Branch list:** Production may add branches over time; keep sandbox trigger list in sync when you want identical behavior.

**Reference:** Production CI is in **Kardome-org/core-main**: `.github/workflows/build-and-test.yml`, `.github/workflows/bmt-handoff.yml`. When in doubt, compare sandbox `build-and-test.yml` triggers, concurrency, and **bmt** job `if` condition with core-main's.

---

## Drift: core-main vs bmt-gcloud

This section defines **what to compare** between Kardome-org/core-main and bmt-gcloud so you can manage drift concretely. Diff these paths regularly (e.g. with `diff -r` or your preferred compare tool).

**Side-by-side: what exists where**

| Path under `.github/` | core-main | bmt-gcloud | Notes |
| --- | --- | --- | --- |
| **Workflows** | | | |
| `workflows/build-and-test.yml` | ✅ Main CI (real build) | ✅ Sandbox CI (dummy builds) | Same triggers/concurrency/BMT condition; bmt-gcloud uses minimal dummy build steps. |
| `workflows/bmt-handoff.yml` | ✅ | ✅ | **Must stay in sync.** |
| **Actions (BMT)** | | | |
| `actions/bmt-prepare-context/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-filter-handoff-matrix/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-handoff-run/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-write-summary/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-failure-fallback/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| `actions/bmt-runner-env/action.yml` | ✅ | ✅ | **Must stay in sync.** Checkout + restore snapshot + uv + load-env. |
| **Actions (GCP / shared)** | | | |
| `actions/setup-gcp-uv/action.yml` | ✅ | ✅ | **Must stay in sync.** |
| **BMT CLI / config** | | | |
| `bmt/` (Python CLI, config) | ✅ | ✅ | **Must stay in sync** for behavior. |

**Files you must diff**

- `.github/workflows/bmt-handoff.yml`
- `.github/actions/bmt-prepare-context/action.yml`, `bmt-filter-handoff-matrix/action.yml`, `bmt-handoff-run/action.yml`, `bmt-write-summary/action.yml`, `bmt-failure-fallback/action.yml`
- `.github/actions/setup-gcp-uv/action.yml`
- `.github/bmt/` (entire tree; exclude secrets and `__pycache__`)

**Intentional differences**

- Main CI: core-main has real build in `workflows/build-and-test.yml`, bmt-gcloud has dummy. Triggers, concurrency, and **bmt** job `if` should match; job names and build steps differ.

**How to run the diff**

From **bmt-gcloud** repo root, with core-main checked out locally (e.g. `../core-main` or `$CORE_MAIN`), diff the paths listed above:

```bash
CORE_MAIN="${CORE_MAIN:-$(realpath ../core-main 2>/dev/null || realpath ../kardome/core-main 2>/dev/null)}"
diff -r "$CORE_MAIN/.github/workflows/bmt-handoff.yml" .github/workflows/bmt-handoff.yml
diff -r "$CORE_MAIN/.github/actions/bmt-prepare-context" .github/actions/bmt-prepare-context
# ... and the other paths in the table
```

**How to use the diff**

1. Run the diff after pulling both repos.
2. **Only in bmt-gcloud:** Add to core-main via PR or leave as dev-only.
3. **Only in core-main:** Add to bmt-gcloud to mirror, or accept as prod-only.
4. **Different content:** bmt-gcloud is source → open PR to core-main with bmt-gcloud's version; or core-main is source → update bmt-gcloud and re-sync sandbox.

**Intentional differences to keep documented**

- **Main CI file name:** Production = `build-and-test.yml`; bmt-gcloud may use same name for sandbox copy.
- **Build steps:** core-main may have real build steps in the build job; bmt-gcloud uses a dummy build. Both use `bmt-runner-env` in the BMT workflow (checkout + restore snapshot + uv + load-env).
