# Infrastructure

Pulumi now provisions the direct-Workflow Cloud Run pipeline:

- `bmt-control`
- `bmt-task-standard`
- `bmt-task-heavy`
- one Google Workflow that runs `plan -> task group(s) -> coordinator`
- Artifact Registry and the required service accounts / IAM

## Apply order

1. Set `infra/pulumi/bmt.tfvars.json` (copy from `bmt.tfvars.example.json`).
2. Build and push the Cloud Run image (if needed).
3. Run `just pulumi` — Pulumi applies and syncs repo variables from its outputs (no separate export step).

## Repo variables (synced by `just pulumi`)

All of these come from Pulumi / `bmt.tfvars.json`; you do not set them in the GitHub UI:

- `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `CLOUD_RUN_REGION`
- `BMT_CONTROL_JOB`, `BMT_TASK_STANDARD_JOB`, `BMT_TASK_HEAVY_JOB`
- `GCP_SA_EMAIL`
- `GCP_WIF_PROVIDER` — set `gcp_wif_provider` in `bmt.tfvars.json`; synced by `just pulumi` like the other GCP_* vars.

Optional override (manual or via `github_vars` in config):

- `BMT_STATUS_CONTEXT` — default is `BMT Gate` in the workflow if unset.

Manual GitHub repository secrets:

- GitHub repo secrets: `BMT_GITHUB_APP_ID`, `BMT_GITHUB_APP_INSTALLATION_ID`, `BMT_GITHUB_APP_PRIVATE_KEY`
- GitHub repo secrets: `BMT_GITHUB_APP_DEV_ID`, `BMT_GITHUB_APP_DEV_INSTALLATION_ID`, `BMT_GITHUB_APP_DEV_PRIVATE_KEY`
- GCP Secret Manager secrets: `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`
- GCP Secret Manager secrets: `GITHUB_APP_DEV_ID`, `GITHUB_APP_DEV_INSTALLATION_ID`, `GITHUB_APP_DEV_PRIVATE_KEY`

## Notes

- Eventarc and the VM watcher are no longer part of the active execution path.
- Workflow ingress is direct GitHub -> Workflows API.
- The job runner service account keeps storage write access and GitHub App secret access because the coordinator owns final result publication.
- GitHub reporting selects credentials from the repository slug: `Kardome-org/*` uses `GITHUB_APP_*`, and non-org repos use `GITHUB_APP_DEV_*`.
- Keep both profiles in GCP Secret Manager while both repo families are active.
