# BMT config

YAML and Python config consumed by **`uv run kardome-bmt`** (see [.github/README.md](../../../.github/README.md)).

- **Infra and repo variables:** Pulumi and **`just pulumi`** — [infra/README.md](../../../infra/README.md), [docs/configuration.md](../../../docs/configuration.md).
- **`secrets/`:** optional local `*.pem` for GitHub App testing (gitignored). **CI** should use a **GitHub Actions secret** (multiline PEM) and, if code requires a path, write to **`RUNNER_TEMP`** at runtime — do **not** commit keys to the repo.
- **core-main / production:** Prefer **no** tracked `*.pem` under `.github/`. Use GitHub Secrets for the GitHub App private key; CI should obtain **`bmt.pex`** from releases on **klugman-yanai/bmt-gcloud** (see `.github/actions/setup-bmt-pex`).
- **`meta load-env`:** `uv run kardome-bmt meta load-env` materializes config into `GITHUB_ENV` when bootstrapping; most handoff flows pass vars via `setup-gcp-uv` and nested commands such as `uv run kardome-bmt handoff write-context`.
