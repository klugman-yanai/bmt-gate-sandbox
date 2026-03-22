# Dev env bootstrap and prek hook staging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a dependency-free shell bootstrap (`just onboard` / direct `bash`) that installs uv (if needed), ensures Python 3.12, runs `uv sync`, and installs prek hooks—without running `ty` or pytest. Restage prek so **commit** hooks stay fast (ruff + repo guards) and **`ty` + pytest fast gate** run on **pre-push** only.

**Architecture:** One bash script under `tools/scripts/` invoked from `Justfile`; no `.venv` required before the script runs. The script bootstraps `uv`, ensures a 3.12 interpreter (system or uv-managed), then uses `uv sync` to create/sync `.venv` and `uv run prek install` for git hooks. Hook config remains a single [`.pre-commit-config.yaml`](../../../.pre-commit-config.yaml) (prek-compatible) with explicit `stages` for `pre-commit` vs `pre-push`.

**Tech Stack:** `bash`, `uv`, `prek`, `ruff`, `ty`, `pytest` (hooks only—not in bootstrap).

**Canonical plan:** This file replaces earlier Cursor-scoped drafts of the same feature.

**Implementation status:** Landed in-repo (bootstrap script, `just onboard`, hook staging, docs).

---

## File map

| File | Role |
| --- | --- |
| [`tools/scripts/bootstrap_dev_env.sh`](../../../tools/scripts/bootstrap_dev_env.sh) | Create: idempotent onboarding; no Python from repo until `uv` exists |
| [`Justfile`](../../../Justfile) | Modify: add `onboard` recipe calling the script |
| [`.pre-commit-config.yaml`](../../../.pre-commit-config.yaml) | Modify: `ty` + `pytest-fast` → `stages: [pre-push]`; commit stage keeps ruff + gcp + image; **ty before pytest** on pre-push |
| [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) | Modify: `just onboard`, commit vs pre-push table, remove stale “ty not in hooks” / pytest-on-commit wording; align `uv sync`-only install story |
| [`pyproject.toml`](../../../pyproject.toml) | Optional: comment tweak under `[dependency-groups]` if still misleading |
| [`CLAUDE.md`](../../../CLAUDE.md) | Optional: one paragraph if devtools section contradicts new hook layout |

---

### Task 1: Add `tools/scripts/bootstrap_dev_env.sh`

**Files:**
- Create: [`tools/scripts/bootstrap_dev_env.sh`](../../../tools/scripts/bootstrap_dev_env.sh)

- [ ] **Step 1: Create script skeleton**

Use `#!/usr/bin/env bash` and `set -euo pipefail`. At top, resolve repo root: walk upward from script directory until `pyproject.toml` with `name = "bmt-gcloud"` or simply until `pyproject.toml` exists at expected root—fail with a clear message if not found.

- [ ] **Step 2: `uv` detection and install**

If `command -v uv` fails, print short text + run (unless `BOOTSTRAP_NONINTERACTIVE=1` or `SKIP_UV_INSTALL=1`—then only print the curl one-liner and exit non-zero):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Document that the user may need to `source` their profile or open a new shell so `uv` is on `PATH`, then re-run the script.

- [ ] **Step 3: Python 3.12**

Prefer: `uv python install 3.12` when no 3.12 satisfies the project (check with `uv python find 3.12` or `python3.12 -V`). **Uv-managed vs system does not matter** as long as `requires-python` (`>=3.12,<3.13`) is satisfied.

- [ ] **Step 4: Sync environment**

From repo root:

```bash
uv sync
```

Do **not** run `ty`, `pytest`, or `prek run` here. Do **not** add `uv pip install -e .` unless you verify `uv sync` does not install the workspace editably (default is editable; omit redundant pip step).

- [ ] **Step 5: Prek install**

If `.git` exists:

```bash
uv run prek install
```

If prek supports installing the **pre-push** hook explicitly (e.g. flags similar to `pre-commit install --hook-type pre-push`), use the documented invocation so **both** commit and pre-push fire—**verify against `prek install --help`** in this repo’s prek version.

- [ ] **Step 6: Success message**

Print: `just help`, link to [`CONTRIBUTING.md`](../../../CONTRIBUTING.md), and reminder that **pre-push** runs `ty` + pytest fast gate.

- [ ] **Step 7: Syntax check**

Run: `bash -n tools/scripts/bootstrap_dev_env.sh`  
Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add tools/scripts/bootstrap_dev_env.sh
git commit -m "chore: add bootstrap_dev_env.sh for local onboarding"
```

---

### Task 2: Wire `just onboard`

**Files:**
- Modify: [`Justfile`](../../../Justfile)

- [ ] **Step 1: Add recipe**

Near other dev/validate entries, add:

```just
# One-time local setup: uv, Python 3.12, uv sync, prek hooks (no ty/pytest)
onboard:
    bash tools/scripts/bootstrap_dev_env.sh
```

- [ ] **Step 2: Update `just help` / default help text** if the Justfile prints a manual list—add one line for `just onboard`.

- [ ] **Step 3: Commit**

```bash
git add Justfile
git commit -m "chore(just): add onboard recipe"
```

---

### Task 3: Restage `.pre-commit-config.yaml`

**Files:**
- Modify: [`.pre-commit-config.yaml`](../../../.pre-commit-config.yaml)

- [ ] **Step 1: Remove pytest from commit stage**

Change `pytest-fast` from `stages: [pre-commit]` to `stages: [pre-push]`.

- [ ] **Step 2: Add `ty` hook on pre-push**

Add a hook, e.g. id `ty-check`:

```yaml
- id: ty-check
  name: ty check
  entry: uv run ty check
  language: system
  pass_filenames: false
  always_run: true
  stages: [pre-push]
```

Place **`ty-check` above `pytest-fast`** in the file so pre-push runs typecheck before tests.

- [ ] **Step 3: Header comment**

Update the file header to state: dev deps via `uv sync`; commit = ruff + guards; pre-push = ty + pytest fast.

- [ ] **Step 4: Validate config**

Run: `uv run prek validate-config`  
Expected: success (fix YAML if not).

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore(hooks): move ty and pytest to pre-push"
```

---

### Task 4: Update `CONTRIBUTING.md`

**Files:**
- Modify: [`CONTRIBUTING.md`](../../../CONTRIBUTING.md)

- [ ] **Step 1: One-time setup**

Add **`just onboard`** (or `bash tools/scripts/bootstrap_dev_env.sh`) as the preferred path; keep manual uv/just install bullets for those who refuse automation.

- [ ] **Step 2: Project install**

Remove redundant `uv pip install -e .` **if** Task 1 confirms `uv sync` suffices (match repo practice).

- [ ] **Step 3: Git hooks table**

Split into **Commit** vs **Pre-push**:
  - Commit: ruff check, ruff format, gcp sync check, image warning.
  - Pre-push: `ty check`, pytest fast gate (`unit` or `contract`).

Remove text claiming pytest runs on every commit or that ty is “not in hooks.”

- [ ] **Step 4: “Before you open a PR”**

Align with reality: pre-push may already run `ty` + fast pytest; full `pytest tests/` and `just test` remain manual/CI as today.

- [ ] **Step 5: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: onboard script and pre-commit vs pre-push hooks"
```

---

### Task 5: Optional docs parity

**Files:**
- Modify: [`CLAUDE.md`](../../../CLAUDE.md) (only if the devtools/pre-commit section conflicts)

- [ ] **Step 1:** Search `CLAUDE.md` for pre-commit / pytest / ty; adjust one short paragraph to match Task 4.

- [ ] **Step 2: Commit** if changed.

---

### Task 6: Manual verification (human or agent)

- [ ] Fresh shell without `uv`: run `bash tools/scripts/bootstrap_dev_env.sh` (or dry-run with env skips) and confirm messages.
- [ ] After install: `git commit` triggers ruff only on staged Python; `git push` runs pre-push (`ty` then pytest)—or run `uv run prek run --hook-stage pre-push --all-files` if such a flag exists (check `prek run --help`).
- [ ] Confirm `prek install` created **both** `pre-commit` and `pre-push` shims under `.git/hooks/` (list directory).

---

## Plan review loop

After implementation, optionally run a focused doc/code review on this plan vs the diff; if hooks do not fire on push, fix `prek install` invocation first.

---

## Execution handoff

**Plan complete and saved to [`docs/superpowers/plans/2026-03-22-dev-env-bootstrap-and-prek-hooks.md`](./2026-03-22-dev-env-bootstrap-and-prek-hooks.md).**

**1. Subagent-driven (recommended)** — fresh subagent per task + review between tasks.

**2. Inline execution** — single session with checkpoints.

**Which approach?** (Reply to proceed.)
