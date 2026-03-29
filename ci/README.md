# kardome-bmt-gate (`ci/`)

YAML and Python config consumed by **`uv run bmt`**. Workflow wiring: [.github/README.md](../.github/README.md).

- **Infra, repo variables, secrets:** [docs/infrastructure.md](../docs/infrastructure.md) · env map: [docs/configuration.md](../docs/configuration.md)
- **`secrets/`:** optional local `*.pem` for GitHub App testing (gitignored). **CI** uses **GitHub Actions secrets** (multiline PEM); do **not** commit keys.
- **`meta load-env`:** `uv run bmt meta load-env` materializes config into `GITHUB_ENV` when bootstrapping; handoff flows usually pass vars via `setup/gcp-uv` and nested `uv run bmt …` commands.
