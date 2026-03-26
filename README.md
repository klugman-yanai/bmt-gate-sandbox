# bmt-gcloud

**BMT (benchmark / milestone testing)** for audio models: GitHub Actions hands off to **Google Workflows** and **Cloud Run**, using **GCS** as the shared store. CI exits after dispatch; Cloud Run runs legs, compares scores to a **baseline**, and posts **status / check runs** back to GitHub.

## Layout

```text
bmt-gcloud/
├── benchmarks/   # 1:1 GCS mirror — projects, plugins, inputs, results
├── backend/      # Cloud Run runtime (image-baked)
├── ci/           # bmt-gate — matrix, handoff, workflow dispatch (`uv run bmt`)
├── tools/        # Developer CLI (`uv run python -m tools`)
├── tests/
├── infra/        # Pulumi, Packer, scripts
└── docs/
```

## Quick start

```bash
uv sync
uv run python -m pytest tests/ -v
just list
```

## Highlights

- **Async handoff** — Actions starts Workflows and stops; runtime finishes on GCP.
- **Pointer results** — `current.json` tracks `latest` / `last_passing`; tasks evaluate against baseline.
- **Portable CI package** — `ci/` is the `bmt-gate` workspace member; consumers can depend on it via git/subdir (see `ci/pyproject.toml`).

## Configuration

**Infra and repo vars:** Pulumi in `infra/pulumi/` — see [infra/README.md](infra/README.md) and [docs/configuration.md](docs/configuration.md).

## Documentation

| Doc | Purpose |
| --- | --- |
| [docs/README.md](docs/README.md) | Doc index |
| [docs/architecture.md](docs/architecture.md) | Pipeline, paths, storage |
| [docs/pipeline-dag.md](docs/pipeline-dag.md) | Diagrams + glossary |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, hooks, PR checks |
| [CLAUDE.md](CLAUDE.md) | Agent / maintainer conventions |
