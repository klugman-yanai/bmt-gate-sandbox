# bmt-gcloud

Development repo for the BMT (Benchmark/Milestone Testing) cloud pipeline. Orchestrates remote VM-based BMT execution via Google Cloud, scoring audio quality metrics against a baseline to gate CI.

## Repository layout

```
bmt-gcloud/
├── benchmarks/       # 1:1 GCS bucket mirror — projects, runners, inputs, outputs
├── backend/          # VM runtime — config, orchestrator, watcher, per-project managers
├── ci/               # BMT CI package (bmt-gate) — portable, distributable
│   └── src/bmt_gate/ #   matrix, trigger, handshake, VM lifecycle
├── tools/            # Developer CLI — bucket sync, layout policy, shared libs
├── tests/            # pytest (unit + integration)
├── infra/            # Terraform IaC
└── docs/             # Architecture, configuration, development guides
```

**Benchmark work:** `benchmarks/` — projects, runner binaries, datasets.
**Framework code:** `backend/` — the VM runtime that executes benchmarks.
**CI package:** `ci/` — standalone `bmt-gate` package; consumer repos install via git dep.

## Quick start

```bash
uv sync                          # Install all deps
uv run python -m pytest tests/   # Run tests (no GCS/VM needed)
just                             # See all recipes
```

## Features

- **Trigger-and-stop handoff** — CI writes a run trigger, starts the VM, waits for handshake, then exits. The VM runs BMT legs and posts final outcome.
- **Commit status and Check Run** — VM posts pending then success/failure; branch protection gates on `BMT_STATUS_CONTEXT`.
- **Pointer-based results** — `current.json` points to latest and last-passing runs; baseline from last-passing snapshot.
- **Portable CI** — `ci/` package has zero `backend.*` imports; works in consumer repos via `bmt-gate` git dependency.

## Configuration

**Terraform is the source of truth** for all non-secret configuration. See [infra/README.md](infra/README.md) and [docs/configuration.md](docs/configuration.md).

## Documentation

| Doc | Description |
| --- | --- |
| [CLAUDE.md](CLAUDE.md) | AI/maintainer guide — layout, devtools, lint/test |
| [docs/README.md](docs/README.md) | Full docs index |
| [docs/architecture.md](docs/architecture.md) | Pipeline, GCS contract, script map |
| [docs/configuration.md](docs/configuration.md) | Env vars, repo vars, secrets |
