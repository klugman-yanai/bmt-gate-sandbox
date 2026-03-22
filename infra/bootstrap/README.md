# Bootstrap

Bootstrap GitHub repo variables and secrets after Pulumi apply. **Pulumi is the source of truth** for all non-secret configuration.

## Flow

1. **Apply Pulumi** (see [../README.md](../README.md)):

   ```bash
   just pulumi
   ```

2. **Pulumi exports repo variables** as part of `just pulumi`. Re-run it whenever outputs change:

   ```bash
   just pulumi
   ```

3. **Set secrets manually** (repo variables, including `GCP_WIF_PROVIDER`, are synced by `just pulumi` from `bmt.tfvars.json`):
   - repo secrets: `BMT_GITHUB_APP_ID`, `BMT_GITHUB_APP_INSTALLATION_ID`, `BMT_GITHUB_APP_PRIVATE_KEY`
   - repo secrets: `BMT_GITHUB_APP_DEV_ID`, `BMT_GITHUB_APP_DEV_INSTALLATION_ID`, `BMT_GITHUB_APP_DEV_PRIVATE_KEY`
   - GCP Secret Manager secrets: `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`
   - GCP Secret Manager secrets: `GITHUB_APP_DEV_ID`, `GITHUB_APP_DEV_INSTALLATION_ID`, `GITHUB_APP_DEV_PRIVATE_KEY`

Use this bootstrap script with an env file that contains them, or set them via the GitHub UI.

GitHub reporting selects the credential profile from the repository slug:
- `Kardome-org/*` uses `GITHUB_APP_*`
- non-org repos use `GITHUB_APP_DEV_*`

## Files

- **`.env.example`** — Template for repo variables/secrets. Copy to `.env` and fill in the missing values.
- **`bootstrap_gh_vars.sh`** — Applies GitHub repo variables and secrets from an env file. Run after `just pulumi` to set secrets, or to apply all vars from a single env file.

Run from repo root:

```bash
# Apply Pulumi-sourced vars first, then set secrets from env file
just pulumi
bash infra/bootstrap/bootstrap_gh_vars.sh --env-file infra/bootstrap/.env

# Or apply everything from one env file (overrides repo vars present in file)
bash infra/bootstrap/bootstrap_gh_vars.sh --env-file infra/bootstrap/.env
```

Secrets: place `*.pem` (e.g. GitHub App private keys) in `infra/bootstrap/secrets/` (gitignored) or reference them from your env file.
