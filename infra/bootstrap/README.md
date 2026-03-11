# Bootstrap (Terraform-first)

Bootstrap GitHub repo variables and secrets after Terraform apply. **Terraform is the source of truth** for all non-secret configuration.

## Flow

1. **Apply Terraform** (see [../README.md](../README.md)):
   ```bash
   cd infra/terraform && terraform init && terraform apply
   ```
2. **Export Terraform outputs to GitHub variables:**
   ```bash
   just terraform-export-vars
   # or: uv run python tools/terraform_repo_vars.py --apply
   ```
3. **Set secrets manually** (not in Terraform): `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY`. Use this bootstrap script with an env file that contains them, or set via GitHub UI.

## Files

- **`.env.example`** — Template for repo variables/secrets. Copy to `.env` and fill in **secrets only** (Terraform exports the rest).
- **`.env.dev`** / **`.env.prod`** — Pre-filled env files for dev/prod; use with `--env-file`.
- **`bootstrap_gh_vars.sh`** — Applies GitHub repo variables and secrets from an env file. Run after Terraform export to set secrets, or to apply all vars from a single env file.

Run from repo root:

```bash
# Apply Terraform-sourced vars first, then set secrets from env file
just terraform-export-vars
bash infra/bootstrap/bootstrap_gh_vars.sh --env-file infra/bootstrap/.env.dev

# Or apply everything from one env file (overrides Terraform for vars present in file)
bash infra/bootstrap/bootstrap_gh_vars.sh --env-file infra/bootstrap/.env
```

Secrets: place `*.pem` (e.g. GitHub App private keys) in `infra/bootstrap/secrets/` (gitignored) or reference them from your env file.
