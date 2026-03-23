# BMT config

YAML and Python config consumed by **`uv run bmt`** (see [.github/README.md](../../README.md)).

- **Infra and repo variables:** Pulumi and **`just pulumi`** — [infra/README.md](../../../infra/README.md), [docs/configuration.md](../../../docs/configuration.md).
- **`secrets/`:** optional local `*.pem` for GitHub App testing (gitignored); CI uses GitHub **Secrets**, not files here.
- **`load-env`:** helper for materializing env when bootstrapping; handoff workflows pass vars via `setup-gcp-uv` and `uv run bmt …` steps.
