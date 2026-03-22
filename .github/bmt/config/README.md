# BMT config (production)

Used by the BMT CI pipeline in this repo. **Local bootstrap and repo setup live in the bmt-gcloud repo.**

## What CI uses

- **`load-env`** — Available for workflow or local bootstrap when a step needs BMT config materialized into `GITHUB_ENV`. Current handoff workflows do not use the removed `bmt-runner-env` wrapper action; they pass required env explicitly and rely on `setup-gcp-uv` plus direct `uv run bmt ...` steps.
- **`secrets/`** — Place `*.pem` (e.g. GitHub App private keys) here when testing locally; directory is gitignored for `*.pem`. CI uses GitHub repo secrets, not files from this tree.

CI does **not** read any `.env` file. Variables are supplied by the workflow’s `env:` block from GitHub repo variables/secrets. Required vars such as `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC` are set from Terraform via `just terraform-export-vars-apply` in bmt-gcloud; the CLI `shared/config.py` still provides fallback defaults when env is missing (e.g. local runs).

## Bootstrapping repo variables (local dev / one-time setup)

To set or refresh GitHub repo variables and secrets for the repo that runs the workflow (e.g. this repo), use the **bmt-gcloud** repo:

- See **bmt-gcloud** devtools/docs for the list of required variables and how to set them (`gh variable set` / `gh secret set`), or use the bootstrap helper and `.env.example` there.

Required variables set by Terraform export: `GCS_BUCKET`, `GCP_PROJECT`, `GCP_SA_EMAIL`. Set manually: `GCP_WIF_PROVIDER`. Zone, subscription, topic, status context, and timeout settings are fixed or derived in code (not overridable via env). Optional and secrets are documented in bmt-gcloud.
