# Infrastructure

**Purpose:** **Reference + how-to** for Pulumi, GCP resources, GitHub repo variables, secrets, and related apply order. **Configuration** cross-cutting env names: [configuration.md](configuration.md).

## What Pulumi provisions

Direct **Google Workflows** → **Cloud Run** pipeline:

- **`bmt-control`** — plan + coordinator
- **`bmt-task-standard`** / **`bmt-task-heavy`** — task legs
- One workflow: **`plan` → task group(s) → `coordinator`**
- Artifact Registry, service accounts, IAM

**Source:** `infra/pulumi/` (e.g. `workflow.yaml` rendered from `__main__.py`).

---

## Apply order

1. Ensure **`infra/pulumi/bmt.config.json`** exists (infra owners / automation).
2. Build and push the Cloud Run image when the runtime changes (see [infra/packer/README.md](../infra/packer/README.md)).
3. Run **`just workspace pulumi`** — Pulumi applies and syncs **GitHub repo variables** from outputs (no separate export step).
4. Run **`just tools set-lifecycle`** — GCS lifecycle (orphaned `imports/`, stale `triggers/`); safe to re-run.

Pulumi apply and variable sync are **not** run from GitHub Actions in this repo (local or approved runner). CI caveats: [.github/README.md](../.github/README.md).

---

## Repo variables (synced by `just workspace pulumi`)

Set via Pulumi / `bmt.config.json` — not manually in the GitHub UI for normal use:

- `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `CLOUD_RUN_REGION`
- `BMT_CONTROL_JOB`, `BMT_TASK_STANDARD_JOB`, `BMT_TASK_HEAVY_JOB`
- `GCP_SA_EMAIL`, `GCP_WIF_PROVIDER` (set `gcp_wif_provider` in `bmt.config.json`)

Optional override: `BMT_STATUS_CONTEXT` (default **`BMT Gate`** in workflow if unset).

---

## Secrets

**GitHub repo secrets**

- `BMT_GITHUB_APP_ID`, `BMT_GITHUB_APP_INSTALLATION_ID`, `BMT_GITHUB_APP_PRIVATE_KEY`
- `BMT_GITHUB_APP_DEV_ID`, `BMT_GITHUB_APP_DEV_INSTALLATION_ID`, `BMT_GITHUB_APP_DEV_PRIVATE_KEY`

**GCP Secret Manager** (Cloud Run)

- `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`
- `GITHUB_APP_DEV_ID`, `GITHUB_APP_DEV_INSTALLATION_ID`, `GITHUB_APP_DEV_PRIVATE_KEY`

**Credential selection:** `Kardome-org/*` → `GITHUB_APP_*`; other repos → `GITHUB_APP_DEV_*`. Keep both profiles in Secret Manager while both families are active.

Use **global** Secret Manager secrets for Cloud Run injection (not regional-only).

---

## Bootstrap (after Pulumi)

1. Apply Pulumi: **`just workspace pulumi`** (repeat when outputs change).
2. Set the secrets above (GitHub UI, script, or env file — see [infra/bootstrap/README.md](../infra/bootstrap/README.md) for the helper flow).
3. GitHub Actions reads **`BMT_GITHUB_APP_*`**; Cloud Run reads **`GITHUB_APP_*`** from Secret Manager.

Local bootstrap env: **`infra/bootstrap/.env`** from `.env.example` (gitignored).

---

## Notes

- Eventarc / VM watcher are **not** on the active execution path.
- Workflow ingress: GitHub → Workflows API (WIF).
- Coordinator SA retains storage write + GitHub App secret access for final reporting.

**Packer / image:** [infra/packer/README.md](../infra/packer/README.md).
