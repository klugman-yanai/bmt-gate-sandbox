# bmt-gcloud

Source of truth for the **BMT (batch model testing) Cloud Run** pipeline: GitHub Actions hands off to **Google Workflows**, which runs **Cloud Run** jobs (`bmt-control`, `bmt-task-standard`, `bmt-task-heavy`) and writes results to **GCS**.

## What this repo owns

- **[`gcp/image`](gcp/image)** — Image-baked runtime and config
- **[`gcp/stage`](gcp/stage)** — Staged mirror of bucket-shaped content (manifests, plugins, inputs)
- **[`.github`](.github)** — Workflows, BMT CLI (`uv run bmt`), composite actions
- **[`tools`](tools)** — Contributor CLI (`uv run python -m tools`, `just` recipes)

## Architecture (summary)

- GitHub Actions validates artifacts and **starts** a Google Workflows execution (does not wait for BMT to finish).
- Workflows runs **plan** → parallel **task** jobs (one leg each) → **coordinator**.
- Runtime writes frozen plans, per-leg summaries, snapshots, `ci_verdict.json`, and `current.json` into the bucket (layout mirrors `gcp/stage`).
- BMT logic runs from **immutable plugin bundles** under `gcp/stage/projects/<project>/plugins/...`.

There is **no supported VM-only** execution path for current production design. See **[docs/architecture.md](docs/architecture.md)** and **[docs/pipeline-dag.md](docs/pipeline-dag.md)**.

## Quick start

```bash
git clone <this-repo>
cd bmt-gcloud
uv sync
just test
```

`uv sync` installs this workspace (including dev tools) from `pyproject.toml` / `uv.lock`—no separate editable install step. For hooks, onboarding, and lint details, see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Documentation

| I want to… | Start here |
| ---------- | ---------- |
| **Browse all docs** | **[docs/README.md](docs/README.md)** |
| **Architecture (short)** | [docs/architecture.md](docs/architecture.md), [ARCHITECTURE.md](ARCHITECTURE.md) |
| **Contributing** | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Security disclosure** | [SECURITY.md](SECURITY.md) |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) |
| **Deep dive (maintainers)** | [docs/bmt-architecture-deep-dive.md](docs/bmt-architecture-deep-dive.md) |

## Configuration

Pulumi exports repo variables (`GCS_BUCKET`, `GCP_PROJECT`, `CLOUD_RUN_REGION`, job names, etc.). See **[docs/configuration.md](docs/configuration.md)** and **[infra/README.md](infra/README.md)**.

## Layout

| Path | Role |
| ---- | ---- |
| `gcp/image` | Baked-in VM image code |
| `gcp/stage` | Editable bucket mirror |
| `gcp/mnt` | Optional bucket mounts |
| `data/` | Local datasets (not committed) |
| `tools/` | Dev CLI |
| `infra/` | Pulumi, image build |

## Contributor workflow (high level)

1. `just add-project <project>`
2. `just add-bmt <project> <bmt_slug>`
3. Edit staged plugins in `gcp/stage/projects/<project>/plugin_workspaces/...`
4. `just upload-data <project> <zip-or-folder> [--dataset <name>]`
5. `just publish-bmt <project> <bmt_slug>`
6. Enable the BMT manifest; CI discovers new legs

Useful commands: `just deploy`, `just pulumi`, `just show-env`, `just mount-project` / `just umount-project`.
