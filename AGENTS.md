# AGENTS.md

Short guidance for **Codex** and other agents in **bmt-gcloud**.

## What this repo is

**bmt-gcloud** implements the **BMT Cloud Run** pipeline: GitHub Actions → **Google Workflows** → **Cloud Run** jobs, with **GCS** for plans, summaries, and results. The bucket mirrors **`benchmarks`**; **`backend`** is image-baked runtime code.

## Where to read first

- **[CLAUDE.md](CLAUDE.md)** — Full workspace rules (tools layout, time/clocks, testing, CI entrypoints, **shell CLI preferences**)
- **[README.md](README.md)** — Doc links (architecture, infra, config, runbook)
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Setup, lint, tests, PR expectations
- **[docs/architecture.md](docs/architecture.md)** — Pipeline design, storage, diagrams

Implementation plans for agents in this workspace may live under **`.cursor/plans/`**.

Do not duplicate long sections from **CLAUDE.md** here; keep this file as a **pointer** so updates stay single-sourced.
