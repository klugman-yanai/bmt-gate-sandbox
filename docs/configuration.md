# Configuration

This repo now has one supported execution model: direct GitHub Actions handoff to Google Workflows, then Cloud Run Jobs.

## Centralized config and repo variables

**Single config file:** `infra/pulumi/bmt.tfvars.json` is the source of truth for all non-secret infra and repo variables. You do not set `GCP_*` or `GCS_BUCKET` (or `GCP_WIF_PROVIDER`) in the GitHub UI for normal use.

**Apply infra and push repo vars:**

```bash
just pulumi
```

That command runs Pulumi and then syncs its outputs to GitHub repo variables. So:

- **User sets:** `bmt.tfvars.json` (copy from `bmt.tfvars.example.json`, set `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`, and `gcp_wif_provider`).
- **Pulumi sets for you:** `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `CLOUD_RUN_REGION`, `BMT_CONTROL_JOB`, `BMT_TASK_STANDARD_JOB`, `BMT_TASK_HEAVY_JOB`, `GCP_SA_EMAIL`, `GCP_WIF_PROVIDER` — all synced from config when you run `just pulumi`.

Defaults in the config file (e.g. `cloud_run_region`, job names) are used by Pulumi; you only override what you need.

## Required Manual GitHub Configuration (secrets and optional overrides)

- GitHub repo secret: `BMT_GITHUB_APP_ID`
- GitHub repo secret: `BMT_GITHUB_APP_INSTALLATION_ID`
- GitHub repo secret: `BMT_GITHUB_APP_PRIVATE_KEY`
- GitHub repo secret: `BMT_GITHUB_APP_DEV_ID`
- GitHub repo secret: `BMT_GITHUB_APP_DEV_INSTALLATION_ID`
- GitHub repo secret: `BMT_GITHUB_APP_DEV_PRIVATE_KEY`
- GCP Secret Manager secret: `GITHUB_APP_ID`
- GCP Secret Manager secret: `GITHUB_APP_INSTALLATION_ID`
- GCP Secret Manager secret: `GITHUB_APP_PRIVATE_KEY`
- GCP Secret Manager secret: `GITHUB_APP_DEV_ID`
- GCP Secret Manager secret: `GITHUB_APP_DEV_INSTALLATION_ID`
- GCP Secret Manager secret: `GITHUB_APP_DEV_PRIVATE_KEY`

`BMT_STATUS_CONTEXT` is optional. If unset, the default is `BMT Gate`.

GitHub reporting chooses the credential profile from the repository slug:

- `Kardome-org/*` uses `GITHUB_APP_*`
- all other repositories use `GITHUB_APP_DEV_*`

GitHub Actions reads the `BMT_GITHUB_APP_*` secrets from the repository. Cloud Run reads the `GITHUB_APP_*` names from GCP Secret Manager. While both the personal dev repo and the org repo are active, keep both profiles populated in Secret Manager so runtime reporting can finalize against either repository without any manual GCP secret swaps.

Use standard global Secret Manager secrets for the Cloud Run path. Regional secrets are not supported for Cloud Run secret injection.

## Local Tooling Environment

Typical local commands use:

- `GCS_BUCKET`
- `GCP_PROJECT`
- `CLOUD_RUN_REGION`

Optional local inspection helpers also use:

- `GCP_ZONE` for image-build and compute-image tooling

Print the current expected environment with:

```bash
just show-env
```

## Pulumi Config

`infra/pulumi/bmt.tfvars.json` must define:

- `gcp_project`
- `gcp_zone`
- `gcs_bucket`
- `service_account`
- `gcp_wif_provider` — Workload Identity Federation provider (GitHub Actions OIDC). Synced to `GCP_WIF_PROVIDER` by `just pulumi` like the other GCP_* vars.

Common optional fields:

- `cloud_run_region`
- `cloud_run_job_sa_name`
- `cloud_run_workflow_sa_name`
- `artifact_registry_repo`
- `github_repo_owner`
- `github_repo_name`

There is no VM name or startup-script setting in the active system.

## Config layers and consistency

Three places touch the same logical settings; they stay consistent as follows:

| Layer | Role | Source of values |
|-------|------|-------------------|
| **`infra/pulumi/config.py`** | Pulumi only. Loads `bmt.tfvars.json`, defines `InfraConfig` (gcp_project, gcs_bucket, service_account, cloud_run_region, gcp_wif_provider, etc.). | `infra/pulumi/bmt.tfvars.json` |
| **`.github/bmt/ci/config.py`** | CI only. Builds `BmtConfig` from **env** (no file). Used when workflows run. | GitHub repo variables (and workflow env); values ultimately from Pulumi sync or manual. |
| **`gcp/image/config/constants.py`** | Code constants only (no loading). Defaults that must match across Pulumi and CI. | Hardcoded (e.g. `DEFAULT_CLOUD_RUN_REGION = "europe-west4"`). |

**Overlap:** The same settings (bucket, project, SA, WIF, region, job names) appear in Pulumi config (file) and CI config (env). The flow is: **bmt.tfvars.json → Pulumi → `just pulumi` syncs to GitHub vars → workflow env → CI config.** So the single source of truth for infra values is `bmt.tfvars.json`; CI reads what was synced.

**Pulumi consistency:** `infra/pulumi/config.py` uses defaults that match `gcp/image/config/constants.py` (e.g. `cloud_run_region = "europe-west4"` with a comment to keep it in sync). Required keys are enforced in Pulumi config; the repo-vars contract lists which vars the workflow requires (including `GCP_WIF_PROVIDER`).

**`GCP_WIF_PROVIDER`:** Required in `bmt.tfvars.json` as `gcp_wif_provider` and synced by Pulumi like the other GCP_* vars. The handoff workflow needs it for OIDC auth.

## Runtime Storage Contract

The active runtime writes:

- `triggers/plans/<workflow_run_id>.json`
- `triggers/summaries/<workflow_run_id>/<project>-<bmt_slug>.json`
- `projects/<project>/results/<bmt_slug>/snapshots/<run_id>/latest.json`
- `projects/<project>/results/<bmt_slug>/snapshots/<run_id>/ci_verdict.json`
- `projects/<project>/results/<bmt_slug>/current.json`

Published staged control-plane content lives under:

- `projects/<project>/project.json`
- `projects/<project>/bmts/<bmt_slug>/bmt.json`
- `projects/<project>/plugins/<plugin>/sha256-<digest>/...`
- `projects/<project>/inputs/<dataset>/...`

## Packages

The repo is a uv workspace with two active packages:

- `bmt` under [`.github/bmt`](/home/yanai/sandbox/bmt-gcloud/.github/bmt)
- `bmt-runtime` under [`gcp/image`](/home/yanai/sandbox/bmt-gcloud/gcp/image)

Run a specific member with:

```bash
uv run --package bmt …
uv run --package bmt-runtime …
```
