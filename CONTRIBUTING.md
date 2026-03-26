# Contributing

## One-time setup

Install tooling in this order: **`uv`** first (required), then **`just`** (optional but recommended), then run **`just onboard`** from the repo root.

### 1. Install uv

**[uv](https://docs.astral.sh/uv/)** manages Python versions and installs dependencies from `pyproject.toml` / `uv.lock`. Nothing in the repo assumes a system Python layout until `uv` exists.

**Linux (standalone installer):**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new shell or ensure `~/.local/bin` is on your **`PATH`**. Verify:

```bash
uv --version
```

**Python 3.12** — if you need an interpreter, use uv ([guide](https://docs.astral.sh/uv/guides/install-python/)):

```bash
uv python install 3.12
```

### 2. Install just (optional)

**[just](https://github.com/casey/just)** runs named recipes from the `Justfile` (similar idea to a Makefile).

**Ubuntu:**

```bash
sudo apt update && sudo apt install -y just
```

### 3. Onboard this repository

From the **repository root**:

```bash
just onboard
```

That runs [`tools/scripts/bootstrap_dev_env.sh`](tools/scripts/bootstrap_dev_env.sh): **`uv sync`** (creates/updates `.venv`), installs **prek** shims for **pre-commit** and **pre-push**, then **`uv run python -m tools onboard`** for a **Rich** summary of hooks and next steps. It does **not** run `ty`, `pytest`, or `prek run`.

Without `just`:

```bash
bash tools/scripts/bootstrap_dev_env.sh
```

**Dry run** (no `uv sync` / no `prek install`; still requires **`uv`** on `PATH`):

```bash
just onboard --dry-run
```

If **prek** hooks are **already** installed from an earlier run, dry-run reports that and does not claim it would install them again. If **`core.hooksPath`** is set (hooks live outside `.git/hooks`), dry-run skips prek install quietly — that is expected when hooks are managed elsewhere.

**Manual equivalent** (same end state as `just onboard`):

```bash
uv sync
uv run prek install -t pre-commit -f
uv run prek install -t pre-push -f
uv run python -m tools onboard
```

`uv sync` includes the **`dev`** dependency group by default (**ruff**, **pytest**, **prek**, **PyJWT** for GitHub App helpers, etc.) and installs this workspace in editable mode. Use `uv sync --no-dev` only when you explicitly want to drop dev tooling. A separate `uv pip install -e .` is not required for normal work.

**Workspace:** one **uv** workspace, one lockfile. Members: **`bmt-gate`** (`ci/`) and **`bmt-runtime`** (`backend`). Examples: `uv run --package bmt-gate …`, `uv run --package bmt-runtime …`; list with `uv workspace list`.

**CLIs:** **`uv run bmt`** — console script from **`bmt-gate`** (implementation under `ci/src/bmtgate/`). **`uv run python -m tools`** — Typer CLI for repo tooling.

**Rare escape hatch:** ad-hoc `uv pip install …` in an existing venv is sometimes used in CI or one-off debugging; for reproducible work, prefer **`uv sync`** (and lockfile changes) so everyone matches `uv.lock`.

---

## Git hooks (prek)

This repo uses **[prek](https://prek.j178.dev/)** (pre-commit compatible). After `uv sync`, install the Git shims (both **commit** and **push**):

```bash
uv run prek install -t pre-commit -f
uv run prek install -t pre-push -f
```

(`just onboard` runs the same commands.)

If **`prek install` fails** with `core.hooksPath`, Git is redirecting hooks elsewhere. Unset it (local or global), then reinstall:

```bash
git config --unset-all core.hooksPath
uv run prek install -t pre-commit -f
uv run prek install -t pre-push -f
```

### On `git commit` (pre-commit stage)

| Hook | What it does |
| --- | --- |
| **ruff check** | Lint with auto-fix where safe (`ruff check --fix`). |
| **ruff format** | Format Python. |
| **bucket sync check** | If you changed `backend/` or `benchmarks/`, verifies stage matches the bucket (or set `SKIP_SYNC_VERIFY=1` when intentional). |
| **image-build warning** | Reminder when **infra/packer/** or **backend/** change. |

### On `git push` (pre-push stage)

| Hook | What it does |
| --- | --- |
| **ty check** | Project typecheck (`uv run ty check`). |
| **pytest fast gate** | `pytest -m "unit or contract"` only—**unmarked tests do not run** here. |

Run hooks manually: `prek run --all-files` (see `prek run --help` for `--stage`).

**Heavier checks** (not in hooks): full **`pytest`**, **`just test`** (layout / policy)—**run before opening a PR**; do not rely on pre-push alone to run the full test tree.

---

## Daily commands

| Goal | Command |
| --- | --- |
| Run tests | `uv run python -m pytest tests/ -v` |
| Layout / policy checks | `just test` |
| Lint | `ruff check .` (also on **commit** via prek) |
| Format | `ruff format .` or rely on prek on commit |
| Types | `uv run ty check` (also on **pre-push** via prek) |

Types: `uv run ty check` — config under `[tool.ty]` in [pyproject.toml](pyproject.toml). Ruff: [ruff.toml](ruff.toml). Python **3.12** (`requires-python` on the workspace packages).

**Optional env / duplication sweep:** `just tools doctor` (vulture + pylint duplicate-code on env-related modules). Not part of `just test`; see [docs/configuration.md — Env inventory appendix](docs/configuration.md#env-inventory-appendix).

---

## Adding or changing a project

Use the scaffold and CLI flow—see **[docs/adding-a-project.md](docs/adding-a-project.md)** and **[docs/local-bmt-testing.md](docs/local-bmt-testing.md)**. **What `just add`, `just publish`, `sync-to-bucket`, `upload-wav`, `stage`, and `workspace` mean**: **[docs/contributor-commands.md](docs/contributor-commands.md)**. For a terminal checklist, run **`just workflow`**; **`just status`** shows `.venv` and folders under `benchmarks/projects/` (alias: `just workflow-status`).

Short version: **`just add <name> [--bmt=<folder>] [--data=<path>]`** → edit under `benchmarks/projects/<name>/` → **`just test-local`** → **`just tools bmt verify <name> <benchmark>`** → **`just publish`** (or `just publish <name> <benchmark>` if several BMTs exist; **`publish` sets `enabled`: true** by default) → **`just sync-to-bucket`** (same as `just workspace deploy`). `<benchmark>` is the folder under `bmts/`; the manifest field is still `bmt_slug`.

---

## Bucket and `benchmarks/`

- If you change files under `benchmarks/`, pre-commit may expect the bucket to match **`just sync-to-bucket`** (same as **`just workspace deploy`**, with `GCS_BUCKET` set). If you must commit without syncing, use `SKIP_SYNC_VERIFY=1` on purpose only.
- Infra and GitHub vars: Pulumi is the source of truth; **`just workspace pulumi`** applies. Details: [docs/configuration.md](docs/configuration.md), [infra/README.md](infra/README.md).

---

## Local layout

| Path | Role |
| --- | --- |
| `backend/` | Cloud Run runtime (image) |
| `benchmarks/` | Staged bucket mirror (projects, plugins, inputs) |
| `gcp/mnt/` | Optional FUSE mount points (gitignored) |

**Recipes:** `just list` · `just workflow` / `just status` · `just add` · `just test-local` · `just publish` · `just sync-to-bucket` · `just test`. FUSE: `just mount <project>` / `just unmount <project>` (wraps `tools bucket …`). Maintainer Typer: `just tools --help`.

## WAV dataset upload (`just upload-wav`)

```bash
just upload-wav <project> <zip-or-folder> [--dataset <name>]
```

**Entry:** [`tools/remote/bucket_upload_dataset.py`](tools/remote/bucket_upload_dataset.py) (`BucketUploadDataset`).

- **Archives (zip):** Large archives should use the **Cloud Run dataset-import** path. Set **`GCP_PROJECT`**, **`CLOUD_RUN_REGION`**, and **`BMT_CONTROL_JOB`** (and related vars your environment uses). If those are missing, extract locally and pass a **directory**, or configure Cloud Run.
- **Directories:** Sync uses **`gcloud storage`** (rsync-style).
- **Pre-flight / completion:** The uploader may print a **pre-flight** summary and a **completion** summary after success.

## Verification (after changing tools or CI)

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m pytest tests/ -q
```

Focused subset while iterating:

```bash
uv run python -m pytest tests/bmt tests/ci tests/infra tests/tools -q
```

**Smoke:** `uv run bmt --help`, `uv run bmt handoff write-context --help`, `uv run python -m tools repo show-env` and `uv run python -m tools repo validate` when touching those areas.

**Integration boundary (mental model):** publish staged plugin → upload dataset → invoke Workflow (CI or manual) → `triggers/plans/<workflow_run_id>.json` → task summaries → coordinator writes `current.json`.

**Troubleshooting:** Layout / policy: `just test`. Bucket out of sync: **`just sync-to-bucket`** before committing `gcp/` (or `SKIP_SYNC_VERIFY=1` intentionally). Vars vs Pulumi: [docs/configuration.md](docs/configuration.md), `just workspace validate`.

## Before you open a PR

**Ruff** runs on **commit** via prek if hooks are installed. For a no-fix check:

```bash
ruff format --check .
ruff check .
```

**`ty`** and the **pytest fast gate** run on **pre-push** if hooks are installed. Still run a full check before opening a PR (CI is the backstop):

```bash
uv run ty check
uv run python -m pytest tests/ -q
just test
```

Optional: `uv run python -m tools repo validate`, `uv run bmt handoff write-context --help`.

---

## Docs

- Index: [docs/README.md](docs/README.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- If you change behavior, env vars, or bucket layout, update README / CLAUDE.md / the relevant doc in the same PR when practical.

**Agent / Cursor implementation plans** for this repo live under **`.cursor/plans/`** (not under `docs/`).

---

## E2E / mock CI

Local readiness: **`just workspace e2e`** (or `uv run python -m tools e2e-preflight`). Exercise handoff via `gh workflow run` on `bmt-handoff.yml` with mock-runner options as documented in workflow inputs and `.github/README.md`.

---

## Maintainer-heavy areas

Orchestration / GitHub reporting often touches **`backend/runtime/`**, **`ci/src/bmtgate/`**, **`infra/pulumi/`**, or **`tools/repo/`** — mention these in the PR when relevant.
