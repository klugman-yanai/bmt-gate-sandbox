# BMT config

YAML and Python config consumed by **`uv run bmt`** (see [.github/README.md](../../README.md)).

- **Infra and repo variables:** Pulumi and **`just pulumi`** — [infra/README.md](../../../infra/README.md), [docs/configuration.md](../../../docs/configuration.md).
- **`secrets/`:** optional local `*.pem` for GitHub App testing (gitignored); CI uses GitHub **Secrets**, not files here.
- **`meta load-env`:** `uv run bmt meta load-env` materializes config into `GITHUB_ENV` when bootstrapping; most handoff flows pass vars via `setup-gcp-uv` and nested commands such as `uv run bmt handoff write-context`.
