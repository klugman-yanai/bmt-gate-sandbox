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

Same thing without passing a flag through `just`:

```bash
just onboard-dry
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

**Workspace:** the repo root is a **uv workspace** with one lockfile. Member packages include **`bmt`** (under `.github/bmt`) and **`bmt-runtime`** (`gcp/image`). Run commands in a member’s context with `uv run --package bmt …` or `uv run --package bmt-runtime …`; list members with `uv workspace list`.

**CLIs:** CI/driver commands use **`uv run bmt`** (console scripts from the `bmt` member). Contributor tooling uses **`uv run python -m tools`** (Typer). The root package does not define a separate `[project.scripts]` alias for `tools`—one entrypoint keeps docs and PATH predictable.

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
| **gcp/ bucket sync check** | If you changed `gcp/`, verifies stage matches the bucket (or set `SKIP_SYNC_VERIFY=1` when intentional). |
| **image-build warning** | Reminder when **infra/packer/** or **gcp/image/** change. |

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

**Optional env / duplication sweep:** `just doctor` runs **vulture** (dead code) and **pylint** duplicate-code on env-related modules only. Not part of `just test`; see [docs/configuration/env-inventory-appendix.md](docs/configuration/env-inventory-appendix.md).

---

## Adding or changing a project

Use the scaffold and CLI flow—see **[docs/adding-a-project.md](docs/adding-a-project.md)**.

Short version: `just add-project <slug>` → edit under `gcp/stage/projects/<slug>/` → data → `just publish-bmt` → set `"enabled": true` in the right `bmt.json` → `just deploy` so the bucket matches.

---

## Bucket and `gcp/`

- If you change files under `gcp/`, pre-commit may expect the bucket to match **`just deploy`** (with `GCS_BUCKET` set). If you must commit without syncing, use `SKIP_SYNC_VERIFY=1` on purpose only.
- Infra and GitHub vars: Pulumi is the source of truth; **`just pulumi`** applies. Details: [docs/configuration.md](docs/configuration.md), [infra/README.md](infra/README.md).

---

## Dataset upload

```bash
just upload-data <project> <zip-or-folder> [--dataset <name>]
```

Large zips may need the Cloud Run import path and env vars (`GCP_PROJECT`, `CLOUD_RUN_REGION`, `BMT_CONTROL_JOB`, etc.). If those are not set, prefer a directory or extract locally—[docs/development.md](docs/development.md#dataset-upload-just-upload-data).

---

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

Optional: `uv run python -m tools repo validate`, `uv run bmt write-context --help`.

---

## Docs and security

- Index: [docs/README.md](docs/README.md)
- Security: [SECURITY.md](SECURITY.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- If you change behavior, env vars, or bucket layout, update README / CLAUDE.md / the relevant doc in the same PR when practical.

---

## E2E / mock CI

Scripted mock handoff: [docs/plans/2026-03-22-e2e-ci-validation.md](docs/plans/2026-03-22-e2e-ci-validation.md).

---

## Maintainer-heavy areas

Big changes to orchestration or GitHub reporting may touch `gcp/image/runtime/`, `.github/bmt/ci/`, or `tools/repo/gh_repo_vars.py`—call that out in the PR and link any existing plan.
