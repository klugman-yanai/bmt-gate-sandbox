# AGENTS.md

Short guidance for **Codex** and other agents in **bmt-gcloud**.

## What this repo is

**bmt-gcloud** implements the **BMT Cloud Run** pipeline: GitHub Actions → **Google Workflows** → **Cloud Run** jobs, with **GCS** for plans, summaries, and results. The bucket mirrors **`gcp/stage`**; **`runtime/`** is the image-baked **`bmt-runtime`** code.

## Where to read first

- **[CLAUDE.md](CLAUDE.md)** — Full workspace rules (tools layout, time/clocks, testing, CI entrypoints, architecture summary, **shell CLI preferences**). Includes **PR-first BMT**: open a PR into `ci/check-bmt-gate` to trigger and review the full pipeline; do not treat direct `push` as the default substitute.
- **[docs/README.md](docs/README.md)** — Task and role index
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Setup, lint, tests, PR expectations
- **[docs/architecture.md](docs/architecture.md)** — Canonical pipeline description (diagrams + maintainer deep dive)
- **[docs/bmt-pipeline-signal.md](docs/bmt-pipeline-signal.md)** — Repo vs handoff vs cloud signal; **`force_pass`** semantics; consumer `workflow_call` checklist
- **[docs/adding-a-project.md](docs/adding-a-project.md)** — Scaffold flow plus **SK** as the reference plugin / extension pattern

Implementation plans for agents in this workspace may live under **`.cursor/plans/`**.

Do not duplicate long sections from **CLAUDE.md** here; keep this file as a **pointer** so updates stay single-sourced.
