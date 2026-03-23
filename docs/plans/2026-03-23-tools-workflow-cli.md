# tools workflow CLI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a Typer subcommand group `tools workflow` that uses Rich to present a clear, ordered contributor path (onboard → add / test-local → publish → upload to bucket → full verify), keeping `tools onboard` scoped to dev-environment bootstrap only. Contributor-facing Just shorthands: **`just add`**, **`just test-local`**, **`just publish`**, **`just sync-to-bucket`**.

**Architecture:** Put **pure data and probe logic** in a small package `tools/workflow/` (easy to unit test). Put **Typer wiring and Rich rendering** in `tools/cli/workflow_cmd.py`, registered from `tools/__main__.py` with a `rich_help_panel`. Extend `ContributorDocRefs` with a resolved path to `docs/adding-a-project.md` so panels and tests never hardcode repo layout. Start with **read-only** commands (`overview`, `status`); do not duplicate `stage`/`publish` implementation—only **point** at existing `just` / `tools bmt stage` commands.

**Tech Stack:** Python 3.12, Typer ≥0.15, Rich ≥13, `typer.testing.CliRunner`, `pytest`, existing `tools.repo.paths.repo_root`.

---

## Task 1: Doc path for “adding a project”

**Files:**

- Modify: `tools/shared/contributor_docs.py` (add field + helper on `ContributorDocRefs`)
- Create: `tests/tools/test_contributor_docs_workflow_path.py`

**Step 1: Write the failing test**

```python
# tests/tools/test_contributor_docs_workflow_path.py
from __future__ import annotations

from tools.shared.contributor_docs import ContributorDocRefs


def test_adding_a_project_doc_exists() -> None:
    refs = ContributorDocRefs.discover()
    p = refs.adding_a_project
    assert p.name == "adding-a-project.md"
    assert p.is_file()
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/tools/test_contributor_docs_workflow_path.py::test_adding_a_project_doc_exists -v`

Expected: **FAIL** (e.g. `AttributeError: adding_a_project`).

**Step 3: Write minimal implementation**

In `ContributorDocRefs`:

- Add field `adding_a_project: Path`.
- In `discover()`, set `adding_a_project=r / "docs" / "adding-a-project.md"`.
- Add `def adding_a_project_rel(self) -> str: return self._rel(self.adding_a_project)`.

**Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/tools/test_contributor_docs_workflow_path.py -v`

Expected: **PASS**.

**Step 5: Commit**

```bash
git add tools/shared/contributor_docs.py tests/tools/test_contributor_docs_workflow_path.py
git commit -m "feat: ContributorDocRefs path for adding-a-project guide"
```

---

## Task 2: Pure workflow step model (TDD)

**Files:**

- Create: `tools/workflow/__init__.py` (empty or `__all__` only)
- Create: `tools/workflow/guide.py`
- Create: `tests/tools/test_workflow_guide.py`

**Step 1: Write the failing test**

```python
# tests/tools/test_workflow_guide.py
from __future__ import annotations

from tools.workflow.guide import workflow_steps_ordered


def test_workflow_order_matches_onboarding_story() -> None:
    steps = workflow_steps_ordered()
    keys = [s.key for s in steps]
    assert keys[:6] == [
        "onboard",
        "stage_project",
        "edit_scaffold",
        "upload_wav",
        "publish_plugin",
        "enable_bmt",
    ]
    assert "workspace_deploy" in keys
    assert "test" in keys
```

Define a small `@dataclass` in `guide.py` (e.g. `WorkflowStep` with `key`, `title`, `summary`, `primary_command`, `doc_hint`) and `def workflow_steps_ordered() -> list[WorkflowStep]:` returning the ordered list. Match the narrative in `docs/adding-a-project.md` (project → edit → WAV → publish → enable → deploy → CI). **YAGNI:** omit interactive prompts; strings only.

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/tools/test_workflow_guide.py::test_workflow_order_matches_onboarding_story -v`

Expected: **FAIL** (import or missing function).

**Step 3: Implement `guide.py`**

Implement `workflow_steps_ordered()` with stable keys and human titles, e.g.:

- `onboard` → `just onboard` / `uv sync`
- `stage_project` → `just stage project <name>`
- `edit_scaffold` → paths only, no single command
- `upload_wav` → `just upload-wav …`
- `publish_plugin` → `just publish` / `just publish <project> <bmt_folder>` (Typer `tools publish`; enables BMT by default)
- `enable_bmt` → edit `bmt.json` / `enabled: true`
- `workspace_deploy` → `just sync-to-bucket` (same as `just workspace deploy`)
- `test` → `just test`

Use **terminology from docs:** “project name”, “BMT folder under `bmts/`”, not “slug” in user-facing titles.

**Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/tools/test_workflow_guide.py -v`

Expected: **PASS**.

**Step 5: Commit**

```bash
git add tools/workflow/ tests/tools/test_workflow_guide.py
git commit -m "feat: ordered contributor workflow step model"
```

---

## Task 3: Repo “hints” for status (TDD)

**Files:**

- Modify: `tools/workflow/guide.py`
- Modify: `tests/tools/test_workflow_guide.py`

**Step 1: Write the failing test**

```python
def test_repo_hints_fresh_repo(tmp_path, monkeypatch) -> None:
    from tools.workflow.guide import repo_workflow_hints

    monkeypatch.chdir(tmp_path)
    h = repo_workflow_hints(repo_root=tmp_path)
    assert h.has_venv is False
    assert h.stage_project_names == []
```

(Adjust import/signature to match implementation; optionally add a second test with a fake `gcp/stage/projects/foo` tree.)

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/tools/test_workflow_guide.py -k repo_hints -v`

Expected: **FAIL**.

**Step 3: Implement `repo_workflow_hints`**

- `@dataclass` `RepoWorkflowHints`: `has_venv: bool`, `stage_project_names: list[str]`.
- `def repo_workflow_hints(*, repo_root: Path) -> RepoWorkflowHints:`  
  - `has_venv`: e.g. `(repo_root / ".venv").is_dir()` (same rough signal as other tooling).  
  - `stage_project_names`: sorted directories under `repo_root / "gcp" / "stage" / "projects"` that are dirs and not dotfiles.

**Step 4: Run tests**

Run: `uv run python -m pytest tests/tools/test_workflow_guide.py -v`

Expected: **PASS**.

**Step 5: Commit**

```bash
git add tools/workflow/guide.py tests/tools/test_workflow_guide.py
git commit -m "feat: repo hints for workflow status"
```

---

## Task 4: Typer `workflow` group — `overview`

**Files:**

- Create: `tools/cli/workflow_cmd.py`
- Modify: `tools/__main__.py` (import + `register_workflow` or inline `add_typer`)
- Create: `tests/tools/test_workflow_cmd.py`

**Step 1: Write the failing test**

```python
# tests/tools/test_workflow_cmd.py
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tools.__main__ import app, register_subcommands

pytestmark = pytest.mark.integration

runner = CliRunner()


def test_workflow_help_lists_subcommands() -> None:
    register_subcommands(app)
    r = runner.invoke(app, ["workflow", "--help"])
    assert r.exit_code == 0
    assert "overview" in r.stdout


def test_workflow_overview_exits_zero() -> None:
    register_subcommands(app)
    r = runner.invoke(app, ["workflow", "overview"])
    assert r.exit_code == 0
    assert "onboard" in r.stdout.lower() or "stage" in r.stdout.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/tools/test_workflow_cmd.py -v`

Expected: **FAIL** (unknown command `workflow`).

**Step 3: Implement CLI**

- In `workflow_cmd.py`, create `app = typer.Typer(no_args_is_help=True, help="…")`.
- `@app.command("overview")` → build a Rich `Table` or `Panel` from `workflow_steps_ordered()` + footer with `ContributorDocRefs.discover().adding_a_project_rel()`. On non-TTY (`sys.stdout.isatty()` is False), print plain lines (like `tools/scripts/just_list_recipes.py`) so tests and pipes stay readable.
- Add `def register_workflow(target: typer.Typer) -> None:` that does `target.add_typer(app, name="workflow", rich_help_panel="Contributor workflow")`.
- In `tools/__main__.py`, call `register_workflow(target)` next to other registrations.

**Step 4: Run tests**

Run: `uv run python -m pytest tests/tools/test_workflow_cmd.py -v`

Expected: **PASS**.

**Step 5: Run broader smoke**

Run: `uv run python -m pytest tests/tools/test_cli_entry.py -v`

Expected: **PASS** (update `test_tools_help` to assert `workflow` appears in top-level help if that test enumerates groups).

**Step 6: Commit**

```bash
git add tools/cli/workflow_cmd.py tools/__main__.py tests/tools/test_workflow_cmd.py
git commit -m "feat: tools workflow overview command"
```

---

## Task 5: Typer `workflow status`

**Files:**

- Modify: `tools/cli/workflow_cmd.py`
- Modify: `tests/tools/test_workflow_cmd.py`

**Step 1: Write the failing test**

```python
def test_workflow_status_exits_zero() -> None:
    register_subcommands(app)
    r = runner.invoke(app, ["workflow", "status"])
    assert r.exit_code == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/tools/test_workflow_cmd.py::test_workflow_status_exits_zero -v`

Expected: **FAIL**.

**Step 3: Implement `status` command**

- Call `repo_workflow_hints(repo_root=repo_root())` (import `repo_root` from `tools.repo.paths`).
- Rich: small `Table` (“Signal” / “Value”): venv present, `gcp/stage/projects/*` listing (truncate if >10 with “+ N more”).
- Plain: same facts as lines.

**Step 4: Run tests**

Run: `uv run python -m pytest tests/tools/test_workflow_cmd.py -v`

Expected: **PASS**.

**Step 5: Commit**

```bash
git add tools/cli/workflow_cmd.py tests/tools/test_workflow_cmd.py
git commit -m "feat: tools workflow status command"
```

---

## Task 6: Documentation cross-link

**Files:**

- Modify: `docs/adding-a-project.md` (1 short paragraph after the title or in “New project” intro)

**Step 1: Add text**

Add one paragraph:

- Run `uv run python -m tools workflow overview` for a compact ordered checklist; `workflow status` for quick repo signals.

**Step 2: No automated test required** (markdown); optional: `rg "workflow overview" docs/adding-a-project.md` locally.

**Step 3: Commit**

```bash
git add docs/adding-a-project.md
git commit -m "docs: link adding-a-project guide to tools workflow"
```

---

## Task 7: Verification gate

**Files:** none

**Step 1: Lint and types**

Run:

```bash
ruff check tools/workflow tools/cli/workflow_cmd.py tools/shared/contributor_docs.py tests/tools/
ruff format --check tools/workflow tools/cli/workflow_cmd.py
uv run ty check
```

Expected: clean.

**Step 2: Tests**

Run:

```bash
uv run python -m pytest tests/tools/test_workflow_guide.py tests/tools/test_workflow_cmd.py tests/tools/test_contributor_docs_workflow_path.py tests/tools/test_cli_entry.py -v
```

Expected: all **PASS**.

**Step 3: Manual smoke (human)**

Run:

```bash
uv run python -m tools workflow overview
uv run python -m tools workflow status
```

Expected: readable output; TTY shows Rich formatting.

**Step 4: Commit** (only if fixes were needed from Step 1–2)

---

## Out of scope (YAGNI for this plan)

- Interactive `Prompt` / wizard flows (Rich **B**-style).
- Duplicating `just stage` / publisher logic inside `workflow`.
- Shell completion for project names (optional follow-up).
- Changing `just_list_recipes.py` intro (optional follow-up; not required for MVP).

---

**Plan complete and saved to `docs/plans/2026-03-23-tools-workflow-cli.md`. Two execution options:**

1. **Subagent-driven (this session)** — fresh subagent per task, review between tasks, fast iteration (**superpowers:subagent-driven-development**).
2. **Parallel session (separate)** — new session in a dedicated worktree with **superpowers:executing-plans**, batch execution with checkpoints.

**Which approach?**
