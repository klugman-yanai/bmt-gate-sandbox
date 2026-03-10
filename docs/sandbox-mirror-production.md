# bmt-gate-sandbox: mirror production behavior

The **bmt-gate-sandbox** repo (klugman-yanai/bmt-gate-sandbox) should mirror **production** (Kardome-org/core-main) as closely as possible so that testing in the sandbox validates the same flow and conditions that run in production.

## What must match

| Aspect | Production (core-main) | Sandbox (bmt-gate-sandbox) |
|--------|------------------------|----------------------------|
| **Main CI workflow file** | `.github/workflows/build-and-test.yml` | Use the **same filename**: `build-and-test.yml` (see below). |
| **Triggers** | `push`: `dev` only. `pull_request`: `dev`, `ci/check-bmt-gate`, `test/check-bmt-gate-*`, `test/workflow-optimizations` | Same triggers (no extra branches like `canary/*`). |
| **Concurrency** | `group: ci-${{ github.repository }}-${{ github.event.pull_request.head.ref \|\| github.ref_name }}`, `cancel-in-progress: true` | Same. |
| **BMT handoff condition** | Runs only when branch is `dev` or `ci/check-bmt-gate` (same-repo check applies) | Same condition so BMT runs for the same events as production. |
| **Job topology** | checkout-once → extract-presets → build → bmt-handoff | Sandbox uses dummy build steps but same job names/structure where possible (extract-presets, build, bmt-handoff; optional resolve-context for test/check-bmt-gate-* context). |
| **bmt.yml** | Reusable workflow; same inputs (ci_run_id, head_sha, head_branch, head_event, pr_number) | Same; use the same `.github/workflows/bmt.yml` and `.github/actions/*` as production. |

## Deploying to the sandbox repo

1. **Workflow filename**  
   In bmt-gcloud the CI workflow is maintained as `dummy-build-and-test.yml` (dummy build steps). For the sandbox repo, **commit it as `build-and-test.yml`** so the filename matches production and branch protection / tooling that references “build-and-test” behaves the same.

2. **Copy from bmt-gcloud to sandbox**  
   When updating the sandbox repo from bmt-gcloud:
   - Copy `.github/workflows/dummy-build-and-test.yml` → sandbox `.github/workflows/build-and-test.yml`
   - Copy `.github/workflows/bmt.yml` and `.github/actions/*` from bmt-gcloud (or core-main once aligned)
   - Ensure sandbox has the same structure for BMT (e.g. `.github/bmt` or `packages/bmt-cli` as used by the workflow)

3. **Repo variables and secrets**  
   Use the **sandbox** GCP/GitHub App configuration (WIF, VM name, bucket, BMT dispatch App, etc.) as defined in `config/env_contract.json` and repo settings. Only the **workflow shape and conditions** mirror production; credentials and resources stay sandbox-specific.

## Differences that are acceptable

- **Build steps:** Sandbox uses dummy/no-op build steps and a lightweight runner staging path; production runs real CMake build and BMT staging. The important part is that the **decision** to run BMT (triggers + bmt-handoff condition) is the same.
- **resolve-context job:** Sandbox can keep a `resolve-context` job for mapping `test/check-bmt-gate-*` pushes to a PR; production may derive context directly. BMT handoff still uses the same condition (dev / ci/check-bmt-gate).
- **Branch list:** Production may add branches over time (e.g. `main`); keep the sandbox trigger list in sync with production when you want identical behavior.

## Reference: production workflow location

Production CI is defined in **Kardome-org/core-main** in:

- `.github/workflows/build-and-test.yml` — main CI (build + BMT handoff)
- `.github/workflows/bmt.yml` — reusable BMT handoff workflow

When in doubt, compare sandbox `build-and-test.yml` triggers, concurrency, and `bmt-handoff` `if` condition with core-main’s `build-and-test.yml`.

## Permissions and drift

You have full permissions on the sandbox repo but not on production (core-main). To maintain both without significant drift, use **bmt-gcloud as the single source of truth** and propagate changes to sandbox (direct) and production (via PR). See [maintaining-sandbox-and-production.md](maintaining-sandbox-and-production.md).
