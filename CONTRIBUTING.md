# Contributing

## Development setup

- **Python 3.12** and [uv](https://docs.astral.sh/uv/). From repo root: `uv sync`, `uv pip install -e .`
- **Lint/typecheck:** `ruff check .`, `ruff format --check .`, `basedpyright` (see [pyproject.toml](pyproject.toml))
- **Tests:** `uv run python -m pytest tests/ -v`. See [docs/development.md](docs/development.md) for local BMT and testing prod CI locally.

## Layout and tools

- **Layout validators:** `just test` runs gcp + repo layout policies.
- **Pre-commit:** Commits that touch `gcp/` require the bucket to be in sync (`just deploy`); use `SKIP_SYNC_VERIFY=1` to bypass.
- **Config:** Pulumi is the source of truth for non-secret config; run `just pulumi` to apply and push repo vars. See [docs/configuration.md](docs/configuration.md) and [infra/README.md](infra/README.md).

## Docs and roadmap

- **Doc index:** [docs/README.md](docs/README.md). **Roadmap:** [ROADMAP.md](ROADMAP.md) and [docs/roadmap/](docs/roadmap/).
- Keep README and CLAUDE.md in sync with docs when changing behavior or env vars.
