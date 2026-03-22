# Contributing

## One-time setup

### `uv` (Python tool)

**[uv](https://docs.astral.sh/uv/)** installs and resolves dependencies from `pyproject.toml`/`uv.lock` in one step, and can install Python versions for you—faster and more reproducible than hand-rolled `venv` + `pip` flows.

**Linux — standalone installer** (downloads `uv` and puts it on your `PATH`; [full install options](https://docs.astral.sh/uv/getting-started/installation/)):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Python 3.12** — if you do not already have it, install a managed 3.12 and use it for this repo ([details](https://docs.astral.sh/uv/guides/install-python/)):

```bash
uv python install 3.12
```

### `just` (repo command runner)

**[just](https://github.com/casey/just)** is like a **Makefile** for shell commands: named recipes in a `Justfile`, but with clearer syntax and less implicit magic—this repo’s `just …` shortcuts wrap common tasks.

**Ubuntu** ([other install methods](https://github.com/casey/just#installation)):

```bash
sudo apt update && sudo apt install -y just
```

### Project install

From the repo root:

```bash
uv sync
uv pip install -e .
```

`uv sync` includes the **`dev`** dependency group by default (**ruff**, **pytest**, **prek**, etc.); use `uv sync --no-dev` only when you explicitly want to drop dev tooling.

---

## Git hooks (prek)

This repo uses **[prek](https://prek.j178.dev/)** (pre-commit compatible). After `uv sync`, install the hook once:

```bash
prek install
```

On each commit, hooks typically run:

| Hook | What it does |
| --- | --- |
| **ruff check** | Lint with auto-fix where safe (`ruff check --fix`). |
| **ruff format** | Format Python. |
| **pytest fast gate** | `pytest -m "unit or contract"` (same idea as a quick CI slice). |
| **gcp/ bucket sync check** | If you changed `gcp/`, verifies stage matches the bucket (or set `SKIP_SYNC_VERIFY=1` when intentional). |
| **image-build warning** | Reminder when **infra/packer/** or **gcp/image/** change. |

Run everything the config would run: `prek run --all-files`.

**What is usually *not* a commit hook here**

- **`ty check`** — slower than ruff; run before a PR or rely on CI/IDE ([pyrightconfig.json](pyrightconfig.json)).
- **Full `pytest`** — hooks use the fast `unit`/`contract` slice; run the full suite before a PR.
- **Layout policies** (`just test`) — heavier repo checks; run before a PR or in CI.

Optional additions other teams use (not configured here): **secret scanning** (e.g. gitleaks), **markdown** or **YAML** linters, **pre-push** hooks for `ty` if commit hooks feel too slow.

---

## Daily commands

| Goal | Command |
| --- | --- |
| Run tests | `uv run python -m pytest tests/ -v` |
| Layout / policy checks | `just test` |
| Lint | `ruff check .` (also runs via **prek** on commit) |
| Format | `ruff format .` or rely on **prek** (`ruff format` on commit) |
| Types | `uv run ty check` |

Config lives in [pyproject.toml](pyproject.toml) and [pyrightconfig.json](pyrightconfig.json). Keep Python version aligned with `requires-python` (3.12).

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

**Ruff** is already covered by **prek** if you commit with hooks installed; run manually only if you need a no-fix check:

```bash
ruff format --check .
ruff check .
```

**Always run** (not all are in commit hooks):

```bash
uv run ty check
uv run python -m pytest tests/ -q
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
