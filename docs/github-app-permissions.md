# GitHub App permissions

This doc explains how to **check** the current GitHub App permissions and **why each permission** is required for BMT (trigger, status, Check Runs).

**Current implementation:** The VM posts commit status and Check Run only. PR comments are **not** implemented; the Issues/Pull requests permission is listed for when that feature is added.

## How to check current permissions

Use the devtools script with your App credentials:

```bash
# Option 1: env vars + private key path
export GITHUB_APP_TEST_ID="123456"   # or GITHUB_APP_PROD_ID for production
uv run python devtools/gh_app_perms.py --private-key /path/to/your-app.private-key.pem

# Option 2: explicit app-id and key
uv run python devtools/gh_app_perms.py --app-id 123456 --private-key /path/to/app.private-key.pem

# Only print the permissions object
uv run python devtools/gh_app_perms.py --app-id 123456 --private-key /path/to/key.pem --jq .permissions
```

The script calls `GET https://api.github.com/app` with JWT auth and prints the app metadata (including `permissions` and `events`). Repository/installation-level overrides can be seen in GitHub: **Settings → GitHub Apps → Your App → Permissions and events**.

---

## Required permissions and why

The BMT flow uses the GitHub App in **two places**:

1. **CI workflow (Actions)** — to trigger the BMT workflow and post status on failure.
2. **BMT VM (watcher)** — to post commit status and create/update Check Runs.

The App must have at least the permissions below. If you use a single App for both CI and VM, grant all of them at the App level (or per repository).

| Permission | Level | Why it's needed |
|------------|--------|------------------|
| **Actions: Read and write** | Repository | **CI (dummy-build-and-test.yml)** uses an installation token from `create-github-app-token` with `permission-actions: write` to call **workflow_dispatch** on `bmt.yml`. Without this, the "Trigger BMT" step cannot start the BMT workflow and returns 403. |
| **Commit statuses: Read and write** | Repository | **Commit status** is how the PR is gated (e.g. "BMT Gate"). Used by: (1) **bmt.yml** — posts pending/failure status from jobs 06 and 07; (2) **dummy-build-and-test.yml** — posts failure status when "Trigger BMT" fails; (3) **VM (vm_watcher.py)** — posts pending then success/failure via `POST /repos/{owner}/{repo}/statuses/{sha}`. Branch protection typically requires this status to pass. |
| **Checks: Read and write** | Repository | **Check Runs** are created and updated by the **VM (remote/code/lib/github_checks.py)** to show live BMT progress in the PR (create_check_run, update_check_run). Optional for gating (the gate is commit status) but needed for the progress table and final results in the check UI. |
| **Issues: Read and write** (or **Pull requests: Read and write**) | Repository | **Planned:** PR comments would be posted by the VM after each run when associated with a PR. Not yet implemented. The workflow can post "Did not run" from failure-path jobs (bmt.yml 07/08, dummy-build-and-test.yml trigger-bmt) using `GITHUB_TOKEN` with `issues: write`. |

### Workflows permission — not required for BMT

**Workflows** is a separate repository permission from **Actions**:

- **Actions** — Run and manage workflow *runs*: trigger workflows (`workflow_dispatch`), list runs, artifacts, logs, etc. The API used by CI to trigger BMT is `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches`, which requires **Actions: write**, not Workflows.
- **Workflows** — Create, update, or delete *workflow files* in `.github/workflows` (via Contents API for those paths). Needed only if the App will create or edit YAML in `.github/workflows`.

BMT does not create or edit workflow files; it only **triggers** an existing workflow. So you do **not** need to grant the **Workflows** permission for BMT. Grant **Actions: Read and write** for triggering; leave **Workflows** unset unless the App has another use case that edits workflow files.

### Optional / workflow default

- **Contents: Read** — Used by **bmt.yml** for `checkout` and reading repo content; usually granted via workflow `permissions: contents: read` (default for many events). The App does not need Contents for the VM; the VM only uses statuses and checks.
- **Metadata: Read** — Default; needed for repository identification.

### Summary

| Permission        | Where used                    | Purpose |
|-------------------|-------------------------------|---------|
| **Actions (R/W)** | CI workflow (trigger step)    | Dispatch `bmt.yml` via workflow_dispatch. |
| **Statuses (R/W)**| CI, BMT workflow, VM         | Gate PR with "BMT Gate" status; post pending/failure from workflow and VM. |
| **Checks (R/W)**  | VM only                       | Create/update Check Run for live progress and final summary. |
| **Issues (R/W)** or **Pull requests (R/W)** | VM (and workflow failure steps use `GITHUB_TOKEN`) | Planned: one PR comment per run. Currently unused (PR comments not implemented). Workflow can post failure "Did not run" comments. |

If the App is used only on the **VM**, the VM still needs **Statuses** and **Checks** at minimum. If the App is also used in **CI** to trigger BMT, it must have **Actions: Read and write**.

---

## Who needs what: runners vs VM

### GitHub Actions runners (GITHUB_TOKEN)

What the workflow jobs actually use:

| Workflow | Job(s) | Truly needed | Notes |
|----------|--------|--------------|-------|
| **dummy-build-and-test.yml** | extract-presets, build | **contents: read** | Checkout only. Default token is enough. |
| **dummy-build-and-test.yml** | trigger-bmt | **statuses: write**, **issues: write** | Post status on failure; post PR comment when trigger fails and event is pull_request. |
| **bmt.yml** | all jobs | **contents: read**, **id-token: write**, **statuses: write**, **actions: read**, **issues: write** | Checkout; GCP WIF; post status; download-artifact; post PR comment on failure (jobs 07, 08). |
| **bmt.yml** | — | ~~checks: write~~ | **Not used by any step.** Only the VM creates/updates Check Runs. You can remove `checks: write` from bmt.yml to minimize runner permissions. |

So for **minimum** runner permissions:

- **dummy-build-and-test.yml**: For **trigger-bmt** only: `permissions: statuses: write, issues: write` (for failure status and PR comment).
- **bmt.yml**: `contents: read`, `id-token: write`, `statuses: write`, `actions: read`, `issues: write` (for failure-path PR comments).

### VM / GCS machine (GitHub App installation token)

The VM does **not** use `GITHUB_TOKEN`. It resolves a **GitHub App installation token** per repository (`github_auth.resolve_auth_for_repository`).

| Capability | Permission needed | Where it’s used |
|------------|-------------------|------------------|
| Post commit status (pending → success/failure) | **Commit statuses: Read and write** | `vm_watcher.py` → `POST /repos/{owner}/{repo}/statuses/{sha}` |
| Create/update Check Run (progress + result) | **Checks: Read and write** | `remote/code/lib/github_checks.py` → create_check_run, update_check_run |
| Post PR comment (Success / Failed / Did not run) — *not yet implemented* | **Issues: Read and write** (or **Pull requests: Read and write**) | Would use `POST /repos/{owner}/{repo}/issues/{pr_number}/comments` |

The VM does **not** trigger workflows or read repo contents from GitHub; it talks to GCS and to the GitHub API for statuses and Check Runs. PR comments are not implemented. In practice the VM token needs **Statuses** and **Checks**; **Issues** (or **Pull requests**) is for when PR comments are added.

### GCS (not GitHub permissions)

The VM and the BMT workflow jobs use **GCP** (bucket, compute) via Workload Identity Federation and a service account. That is separate from GitHub permissions. The repo vars (`GCS_BUCKET`, `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, etc.) and the SA’s IAM roles (e.g. Storage Object Admin, Compute Instance Admin for start/stop) define what the runners and VM can do in GCS/GCP.
