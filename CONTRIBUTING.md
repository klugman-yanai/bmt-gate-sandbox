# Contributing

## One-time setup

Install **`just`** (optional but recommended), then run **`just setup`** from the repo root.

### 1. Install just (optional)

**[just](https://github.com/casey/just)** runs named recipes from the `Justfile`.

**Ubuntu:**

```bash
sudo apt update && sudo apt install -y just
```

### 2. Run setup

From the **repository root**:

```bash
just setup
```

`just setup` runs [`tools/scripts/setup.sh`](tools/scripts/setup.sh): installs **uv** (if missing), installs **gcloud CLI** (if missing), authenticates Application Default Credentials, syncs the Python workspace (**`uv sync`**), and installs **prek** shims for **pre-commit** and **pre-push**.

For a full developer environment (adds **shellcheck**, **actionlint**, **Pulumi**):

```bash
just setup --dev
```

**Dry run** (no installs or `uv sync`; reports what would happen):

```bash
just setup --dry-run
```

**Manual equivalent** (without `just`):

```bash
bash tools/scripts/setup.sh
```

Re-running `just setup` on an already-configured machine is safe and fast — each step is idempotent.

---

**Workspace:** the repo root is a **uv workspace** with one lockfile. Member packages include **`kardome-bmt`** (`ci/`), **`bmt-runtime`** (`runtime/`), and **`bmt-sdk`** (`sdk/`). Run commands in a member’s context with `uv run --package kardome-bmt …` or `uv run --package bmt-runtime …`; list members with `uv workspace list`.

**CLIs:** CI/driver commands use **`uv run kardome-bmt`** (the `ci` package also installs a legacy **`bmt`** console alias). Contributor tooling uses **`uv run python -m tools`** (Typer). The root package does not define a separate `[project.scripts]` alias for `tools`—one entrypoint keeps docs and PATH predictable.

**`uv sync`:** includes the **`dev`** dependency group by default (**ruff**, **pytest**, **prek**, **PyJWT** for GitHub App helpers, etc.) and installs this workspace in editable mode. Use `uv sync --no-dev` only when you explicitly want to drop dev tooling. A separate `uv pip install -e .` is not required for normal work.

**Rare escape hatch:** ad-hoc `uv pip install …` in an existing venv is sometimes used in CI or one-off debugging; for reproducible work, prefer **`uv sync`** (and lockfile changes) so everyone matches `uv.lock`.

---

## Git hooks (prek)

This repo uses **[prek](https://prek.j178.dev/)** (pre-commit compatible). After `uv sync`, install the Git shims (both **commit** and **push**):

```bash
uv run prek install -t pre-commit -f
uv run prek install -t pre-push -f
```

(`just setup` runs the same commands.)

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
| **gcp/ bucket sync check** | If you changed `gcp/`, verifies stage matches the bucket (or set `SKIP_SYNC_VERIFY=1` when intentional). |
| **image-build warning** | Reminder when **infra/packer/** or **`runtime/`** (Dockerfile) change. |

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

Config lives in [pyproject.toml](pyproject.toml) and [pyrightconfig.json](pyrightconfig.json). Keep Python version aligned with `requires-python` (3.12).

**Optional env / duplication sweep:** `just doctor` runs **vulture** (dead code) and **pylint** duplicate-code on env-related modules only. Not part of `just test`; see [docs/configuration.md — Env inventory appendix](docs/configuration.md#env-inventory-appendix).

---

## Adding or changing a project

Use the scaffold and CLI flow—see **[docs/adding-a-project.md](docs/adding-a-project.md)**.

Short version: `just add-project <slug>` → edit under `gcp/stage/projects/<slug>/` → data → `just publish-bmt` → set `"enabled": true` in the right `bmt.json` → `just deploy` so the bucket matches.

---

## Bucket and `gcp/`

- If you change files under `gcp/`, pre-commit may expect the bucket to match **`just deploy`** (with `GCS_BUCKET` set). If you must commit without syncing, use `SKIP_SYNC_VERIFY=1` on purpose only.
- Infra and GitHub vars: Pulumi is the source of truth; **`just pulumi`** applies. Details: [docs/configuration.md](docs/configuration.md), [infra/README.md](infra/README.md).

---

## Local layout (contributor)

- [`runtime/`](runtime) — Image-baked orchestration (`bmt-runtime`)
- [`gcp/stage`](gcp/stage) — Editable staged mirror of bucket manifests, plugins, assets
- [`gcp/mnt`](gcp/mnt) — Optional read-only bucket mount for inspection
- Dataset archives may live anywhere; `just upload-data` takes an explicit path

**Common commands:** `just add-project`, `just add-bmt`, `just publish-bmt`, `just upload-data`, `just mount-project` / `just umount-project` (see `just --list`).

## Dataset upload (`just upload-data`)

```bash
just upload-data <project> <zip-or-folder> [--dataset <name>]
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

**Smoke:** `uv run kardome-bmt --help`, `uv run kardome-bmt handoff write-context --help`, `uv run python -m tools repo show-env` and `uv run python -m tools repo validate` when touching those areas.

**Integration boundary (mental model):** publish staged plugin → upload dataset → invoke Workflow (CI or manual) → `triggers/plans/<workflow_run_id>.json` → task summaries → coordinator writes `current.json`.

**Troubleshooting:** Layout / policy: `just test`. Bucket out of sync: `just deploy` before committing `gcp/` (or `SKIP_SYNC_VERIFY=1` intentionally). Vars vs Pulumi: [docs/configuration.md](docs/configuration.md), `just validate`.

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

Optional: `uv run python -m tools repo validate`, `uv run kardome-bmt handoff write-context --help`.

---

## Docs

- **Local BMT / runner / plugin loop (no full pipeline):** [docs/developer-workflow.md](docs/developer-workflow.md)
- Index: [docs/README.md](docs/README.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- If you change behavior, env vars, or bucket layout, update README / CLAUDE.md / the relevant doc in the same PR when practical.

**Agent / Cursor implementation plans** for this repo live under **`.cursor/plans/`** (not under `docs/`).

---

## E2E / mock CI

Exercise handoff via `gh workflow run` on `bmt-handoff.yml` as documented in workflow inputs and `.github/README.md`.

---

## Maintainer-heavy areas

Big changes to orchestration or GitHub reporting may touch `runtime/`, `ci/kardome_bmt/`, or `tools/repo/gh_repo_vars.py`—call that out in the PR.
