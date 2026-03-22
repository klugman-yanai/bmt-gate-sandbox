# AGENTS.md

Short guidance for **Codex** and other agents in **bmt-gcloud**.

## What this repo is

**bmt-gcloud** implements the **BMT Cloud Run** pipeline: GitHub Actions → **Google Workflows** → **Cloud Run** jobs, with **GCS** for plans, summaries, and results. The bucket mirrors **`gcp/stage`**; **`gcp/image`** is image-baked runtime code.

## Where to read first

- **[CLAUDE.md](CLAUDE.md)** — Full workspace rules (tools layout, time/clocks, testing, CI entrypoints, architecture summary)
- **[docs/README.md](docs/README.md)** — Task and role index
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Setup, lint, tests, PR expectations
- **[docs/architecture.md](docs/architecture.md)** — Canonical pipeline description

## Security

Report vulnerabilities per **[SECURITY.md](SECURITY.md)** — not via public issues.

Do not duplicate long sections from **CLAUDE.md** here; keep this file as a **pointer** so updates stay single-sourced.
