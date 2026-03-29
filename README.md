# bmt-gcloud

**BMT (benchmark / milestone testing)** for audio models: GitHub Actions hands off to **Google Workflows** and **Cloud Run**, using **GCS** as the shared store. CI exits after dispatch; Cloud Run runs legs, compares scores to a **baseline**, and posts **status / check runs** back to GitHub.

## Layout

```text
bmt-gcloud/
├── benchmarks/   # 1:1 GCS mirror — projects, plugins, inputs, results
├── backend/      # runtime package project; source under src/backend + src/bmtplugin
├── ci/           # kardome-bmt-gate — matrix, handoff, workflow dispatch (`uv run bmt`)
├── tools/        # Developer CLI (`uv run python -m tools`)
├── tests/
├── infra/        # Pulumi, Packer, scripts
└── docs/         # Central reference (architecture, infra, config, ops)
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
- **Portable CI package** — `ci/` is **`kardome-bmt-gate`** (import **`bmtgate`**); consumers: `kardome-bmt-gate = { git = "…", subdirectory = "ci" }` (see `ci/pyproject.toml`).
- **Plugin authoring alias** — `import bmtplugin as bmt` is shipped by the runtime package; source lives under `backend/src/bmtplugin/`.

## Documentation

**First-time contributors:** [CONTRIBUTING.md](CONTRIBUTING.md) · **priorities:** [ROADMAP.md](ROADMAP.md).

| Doc | Purpose |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Pipeline design, storage, glossary, ADR summaries, diagram policy |
| [docs/infrastructure.md](docs/infrastructure.md) | Pulumi, apply order, repo vars, secrets, bootstrap |
| [docs/configuration.md](docs/configuration.md) | Env vars map; points at infra for source of truth |
| [docs/runbook.md](docs/runbook.md) | **Operations:** where to look when a production/staging run fails (not local dev) |
| [docs/contributors.md](docs/contributors.md) | Plugin SDK & `bmt.json` reference |
| [docs/weak-points-remediation.md](docs/weak-points-remediation.md) | Known risks / remediation backlog |
| [CLAUDE.md](CLAUDE.md) | Agent / maintainer conventions |

**Subsystem pointers:** [.github/README.md](.github/README.md) (workflows) · [ci/README.md](ci/README.md) (handoff package) · [benchmarks/projects/README.md](benchmarks/projects/README.md) (stage layout).

**Local planning:** create **`docs/plans/`** yourself if you want epics/todos on disk; that tree is **gitignored** but kept visible to Cursor (see `.cursorignore`).
