# CLAUDE.md

Agent rules for **bmt-gcloud**: **Actions (WIF)** → **Google Workflows** → **Cloud Run** (`bmt-control` + `bmt-task-*`); **GCS** holds plans (`triggers/`), results/snapshots/`current.json`. Bucket root mirrors **`gcp/stage`**; **`gcp/image`** is baked into Cloud Run. Ignore legacy VM/vm_watcher docs.

**Read next:** [docs/architecture.md](docs/architecture.md) (pipeline) · [docs/README.md](docs/README.md) (index) · [CONTRIBUTING.md](CONTRIBUTING.md) · [.github/README.md](.github/README.md) (workflows).

## Code layout

| Area | Path |
| ---- | ---- |
| Cloud Run runtime | `gcp/image/runtime/`, entry `gcp/image/main.py` |
| Stage mirror (bucket) | `gcp/stage/` (incl. `projects/.../plugins/`) |
| CI / handoff CLI | `uv run bmt` → `.github/bmt/ci/` (`bmt` workspace member; `uv sync` at root) |
| Contributor Typer CLI | `uv run python -m tools --help` |
| Shared libs | `tools/shared/` |
| GCS sync/verify | `tools/remote/` |
| Local BMT (not Cloud Run path) | `tools/bmt/` |
| Layout / repo vars | `tools/repo/` |
| Pulumi → GitHub vars | `tools/pulumi/` |

**Recipes:** `just` (see `just list`). Common: `just test`, `just sync-to-bucket` (= `just workspace deploy`, needs `GCS_BUCKET`). Layout policy: `just test` or `uv run python -m tools.repo.gcp_layout_policy`. Infra vars: `just workspace pulumi` / `validate` — [infra/README.md](infra/README.md), [docs/configuration.md](docs/configuration.md).

## Time

| Need | Use |
| ---- | --- |
| Wall clock / TTL | `whenever.Instant.now()` (+ ISO helpers / [tools/shared/time_utils.py](tools/shared/time_utils.py)) |
| Durations / timeouts | `time.monotonic()` |
| Sleep / backoff | `time.sleep()` |

Avoid new `time.time()` / `datetime.now()` (CI/`gcp/` may keep local helpers for bucket sync).

## Lint / types

```bash
uv sync && ruff check . && ruff format --check . && uv run ty check
```

Config: `pyproject.toml`, `pyrightconfig.json`. Fix types honestly (concrete unions/ABCs, LSP-safe `Protocol`, narrow ignores with rationale)—not blanket `cast`/`# type: ignore` to silence checkers.

**Path map:** CI → `uv run bmt` / `.github/bmt/ci/`. Bucket → `tools/remote/bucket_*.py`. Local batch → `tools/bmt/`.

## Tests

- Unit: `uv run python -m pytest tests/ -v` (no GCS).
- Real bucket / snapshots: [CONTRIBUTING.md](CONTRIBUTING.md), [docs/configuration.md](docs/configuration.md). E2E via CI / `bmt-handoff` dispatch.

## Onboarding / `gcp/` commits

`just onboard` or `bash tools/scripts/bootstrap_dev_env.sh` (`uv sync`, **prek** hooks, `uv run python -m tools onboard`). Pre-commit can block `gcp/` changes unless bucket matches (`SKIP_SYNC_VERIFY=1` to bypass on purpose). Upload: `GCS_BUCKET=… uv run python -m tools.remote.bucket_sync_gcp` or `just sync-to-bucket`.

## Shell (when available)

Prefer **`rg`** (not `grep -r`), **`fd`** (not `find`), **`jq`**, **`yq`** (mikefarah/go-yq—not kislyuk’s Python wrapper), **`uv`**, **`just`**, optional **`sd`**, **`ast-grep`**. Fall back to POSIX tools in minimal environments.
