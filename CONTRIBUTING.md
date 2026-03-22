# Contributing

## Development setup

- **Python 3.12** and [uv](https://docs.astral.sh/uv/). From repo root: `uv sync`, `uv pip install -e .`
- **Lint / format / typecheck:** `ruff check .`, `ruff format --check .`, `uv run ty check` (see `[tool.ty]` in [pyproject.toml](pyproject.toml)). Keep **`pythonVersion`** in [pyrightconfig.json](pyrightconfig.json) aligned with **`requires-python`** (3.12).
- **Tests:** `uv run python -m pytest tests/ -v`

## Layout and tools

- **Layout validators:** `just test` runs gcp + repo layout policies.
- **Pre-commit:** Commits that touch `gcp/` expect the bucket in sync with `just deploy`; use `SKIP_SYNC_VERIFY=1` only when intentional.
- **Config:** Pulumi is the source of truth for non-secret config; `just pulumi` applies and pushes repo vars. See [docs/configuration.md](docs/configuration.md) and [infra/README.md](infra/README.md).

## Dataset upload and Cloud Run import

`just upload-data <project> <source>` uploads datasets into the bucket layout under `projects/<project>/inputs/...`.

- **Archives:** Prefer the **Cloud Run dataset-import** job for large zips; requires **`GCP_PROJECT`**, **`CLOUD_RUN_REGION`**, **`BMT_CONTROL_JOB`** (and any other vars your stack uses). Without them, use a **directory** or extract locally—see [docs/development.md](docs/development.md#dataset-upload-just-upload-data).
- **Directories:** Synced with `gcloud storage` tooling; progress may appear on the terminal.

## Verification before a PR

```bash
ruff check .
ruff format --check .
uv run ty check
uv run python -m pytest tests/ -q
```

Optional smoke: `uv run python -m tools repo validate`, `uv run bmt write-context --help`.

## E2E / mock CI

For a scripted mock handoff flow, see **[docs/plans/2026-03-22-e2e-ci-validation.md](docs/plans/2026-03-22-e2e-ci-validation.md)**.

## Documentation

- **Hub:** [docs/README.md](docs/README.md)
- **Security reporting:** [SECURITY.md](SECURITY.md)
- **Changelog:** [CHANGELOG.md](CHANGELOG.md)
- When you change behavior, env vars, or bucket contracts, update **README**, **CLAUDE.md**, and the relevant **docs/** page in the same PR when practical.

## Maintainer-heavy areas

Large orchestration or reporting changes may involve `gcp/image/runtime/github_reporting.py`, `gcp/image/runtime/entrypoint.py`, `.github/bmt/ci/handoff.py`, or `tools/repo/gh_repo_vars.py` — coordinate via PR description and existing engineering plans.
