# BMT config (production)

Used by the BMT CI pipeline in this repo. **Local bootstrap and repo setup live in the bmt-gcloud repo.**

## What CI uses

- **`load-env`** — Run in CI by `bmt-job-setup`: loads BMT config (env from workflow `env:` / vars first, then built-in defaults in code) and appends to `GITHUB_ENV` so downstream steps don’t need per-step `env:` blocks. No config file is required; optional override via `BMT_CONFIG_PATH` if you need a JSON file.
- **`secrets/`** — Place `*.pem` (e.g. GitHub App private keys) here when testing locally; directory is gitignored for `*.pem`. CI uses GitHub repo secrets, not files from this tree.

CI does **not** read any `.env` file. Variables are supplied by the workflow’s `env:` block from GitHub repo variables/secrets. Defaults for optional vars (e.g. `BMT_HANDSHAKE_TIMEOUT_SEC`) live in the CLI `shared/config.py` code.

## Bootstrapping repo variables (local dev / one-time setup)

To set or refresh GitHub repo variables and secrets for the repo that runs the workflow (e.g. this repo), use the **bmt-gcloud** repo:

- See **bmt-gcloud** devtools/docs for the list of required variables and how to set them (`gh variable set` / `gh secret set`), or use the bootstrap helper and `.env.example` there.

Required variables include: `GCS_BUCKET`, `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`. Optional and secrets are documented in bmt-gcloud.

To set or refresh GitHub repo variables and secrets for the repo that runs the workflow (e.g. this repo), use the **bmt-gcloud** repo:

- See **bmt-gcloud** devtools/docs for the list of required variables and how to set them (`gh variable set` / `gh secret set`), or use the bootstrap helper and `.env.example` there.

Required variables include: `GCS_BUCKET`, `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`. Optional and secrets are documented in bmt-gcloud.
