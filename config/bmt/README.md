# BMT config

- **`.env.example`** — Template for repo variables. Copy to `.env` and fill in values.
- **`.env.dev`** / **`.env.prod`** — Pre-filled env files for dev and prod; use with `--env-file`.
- **`bootstrap_gh_vars.sh`** — Sets GitHub repository variables from an env file (`gh variable set`).
- **`secrets/`** — Place `*.pem` (e.g. GitHub App private keys) here; directory is gitignored for `*.pem`.

Run from repo root:

```bash
# Default: reads config/.env
bash config/bmt/bootstrap_gh_vars.sh

# Or use a specific env file
bash config/bmt/bootstrap_gh_vars.sh --env-file config/bmt/.env.dev
```
