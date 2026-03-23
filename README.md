---
title: bmt-gcloud
shortTitle: bmt-gcloud
intro: >-
  Internal repo for the BMT (batch model testing) Cloud Run pipeline — GitHub Actions,
  Google Workflows, Cloud Run jobs, GCS. Bucket layout mirrors gcp/stage.
---

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/kardome-logo-light.svg">
    <img alt="Kardome" src="docs/assets/kardome-logo-dark.svg" width="280">
  </picture>
</p>

<!-- markdownlint-disable-next-line MD025 -->
# bmt-gcloud

Internal repo for the **BMT (batch model testing) Cloud Run** pipeline: **GitHub Actions** starts **Google Workflows**,
which runs **Cloud Run** jobs (`bmt-control`, `bmt-task-standard`, `bmt-task-heavy`) and writes results to **GCS**.
The bucket layout mirrors [`gcp/stage`](gcp/stage).

## Prerequisites

- **Python 3.12+**, **[uv](https://docs.astral.sh/uv/)**, **[just](https://github.com/casey/just)** (recommended)
- GCP-related vars and repo configuration: **[docs/configuration.md](docs/configuration.md)**

## Quick start

```bash
git clone https://github.com/klugman-yanai/bmt-gcloud.git
cd bmt-gcloud
just onboard
just test
```

Run **`just`** (no arguments) for the **typical workflow** steps; **`just list`** prints the full recipe table. **`just tools`** is the full Typer CLI (includes maintainer commands such as `release`). [`CONTRIBUTING.md`](CONTRIBUTING.md) has the full setup story (hooks, lint, tests).

## Architecture (summary)

- Actions builds and validates, then **starts** Workflows and exits (it does not wait for BMT to finish).
- Workflows runs **plan** → parallel **task** jobs (one leg each) → **coordinator**.
- Plans, summaries, snapshots, and `current.json` live under the bucket; see
  **[docs/architecture.md](docs/architecture.md)** (includes diagrams and maintainer deep dive).

There is **no** supported legacy VM-only path for current production.

## Documentation

| I want to… | Start here |
| ---------- | ---------- |
| **Doc index** | [docs/README.md](docs/README.md) |
| **Architecture** | [docs/architecture.md](docs/architecture.md) |
| **Configuration / env** | [docs/configuration.md](docs/configuration.md) |
| **Add a project / BMT** | [docs/adding-a-project.md](docs/adding-a-project.md) |
| **Before publish (local checks)** | [docs/local-bmt-testing.md](docs/local-bmt-testing.md) |
| **Ops / incidents** | [docs/runbook.md](docs/runbook.md) |
| **Roadmap** | [ROADMAP.md](ROADMAP.md) |
| **Contributing** | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) |

## Configuration

Pulumi drives infra and synced GitHub variables (`GCS_BUCKET`, `GCP_PROJECT`, `CLOUD_RUN_REGION`, job names, etc.).
See **[docs/configuration.md](docs/configuration.md)** and **[infra/README.md](infra/README.md)**.

## Repository layout

| Path | Role |
| ---- | ---- |
| `gcp/image` | Runtime baked into the Cloud Run image |
| `gcp/stage` | Editable mirror of bucket-shaped content |
| `gcp/mnt` | Optional local bucket mount for inspection |
| `.github` | Workflows, `uv run bmt` CLI |
| `tools/` | Contributor CLI (`uv run python -m tools`) |
| `infra/` | Pulumi, image build |
| `tests/` | Pytest |
| `data/` | Local datasets (not committed) |

## Contributor workflow (high level)

1. `just add <project> [--bmt=<benchmark>] [--data=<zip-or-dir>]` (or use `just stage project` / `stage bmt` / `upload-wav` separately)
2. Edit staged plugins under `gcp/stage/projects/<project>/plugin_workspaces/...`
3. `just test-local` then `just tools bmt verify <project> <benchmark>` (see [docs/local-bmt-testing.md](docs/local-bmt-testing.md))
4. `just publish` (or `just publish <project> <benchmark>`; enables `bmt.json` by default)
5. `just sync-to-bucket` (full `gcp/` mirror; same as `just workspace deploy`)

Other useful commands: `just mount` / `just unmount`. Infra and Cloud Run image work lives under **`just tools`** (e.g. `workspace pulumi`, `repo show-env`, `ship`, `build orchestrator-image`).
