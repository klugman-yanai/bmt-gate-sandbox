# Python structural cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve structure, typing, and lint hygiene without trading real clarity for green checks.

**Architecture:** Phased refactors (GCS client, CLI protocols, shared regex tuples, handoff typing, targeted noqa removal) with tests and `ruff` / `ty` after each phase.

**Tech Stack:** Python 3.12+, Ruff, ty (Pyright), pytest, Typer, Pydantic (`WorkflowContext`).

---

## Lint and type checks vs. code smell

Do **not** “fix” Ruff or `ty` by introducing **sustained** code smell:

| Avoid as a default | Prefer instead |
| ------------------ | -------------- |
| `cast(...)` purely to satisfy assignment to a `Protocol` or union | Prefer a **union of concrete classes** at the call site when implementations differ by keyword-only params (inheritance from a `Protocol` often breaks LSP); or a shared ABC; or a small factory with an explicit return type |
| Blanket `# type: ignore` / `# noqa` on a whole block | Narrow ignores to a single line with a one-line rationale, or fix the underlying type/API |
| Disabling a rule repo-wide to silence churn | Local, justified exception or refactor |

If the only apparent fix is a cast or a broad ignore, **stop** and refactor boundaries (helpers, Protocols, nominal bases) until the types are honest.

---

## Phase A: GCS client without `global`

- [x] Refactor [`.github/bmt/ci/gcs.py`](../../../.github/bmt/ci/gcs.py): `@functools.lru_cache(maxsize=1)` for one `storage.Client` per process.
- [x] Verify: `pytest tests/ci/test_workflow_resolve_uploaded_projects.py tests/tools/test_upload_runner_dedup.py`, `ruff check`, `uv run ty check` on touched paths.

---

## Phase B: Bucket deploy runners (no cast smell)

- [x] Type the deploy loop with a **union of concrete runner classes** (or compatible ABC), not `cast()` to a `Protocol` — explicit `Protocol` subclasses often violate LSP vs `run(..., **kwargs)`.
- [x] Verify: `ruff`, `ty`, tests touching bucket CLI if any.

---

## Phase C: `layout_patterns` DRY

- [x] Introduce `_ARTIFACT_EXCLUDES` and compose `DEFAULT_CODE_EXCLUDES`, `FORBIDDEN_RUNTIME_SEED`, `BLOAT_PATTERNS`, `FORBIDDEN_RUNTIME_PATTERNS` without changing regex strings.
- [x] Verify: `pytest tests/tools/test_bucket_sync_inputs_guard.py`, `uv run python -m tools.repo.gcp_layout_policy`.

---

## Phase D: Handoff workflow context

- [x] Prefer typed [`WorkflowContext`](../../../.github/bmt/ci/config.py) / `isinstance` path in [`handoff.py`](../../../.github/bmt/ci/handoff.py) where applicable; keep env fallback behavior identical.

---

## Phase E: Targeted noqa / hygiene (honest types)

- [x] [`github_auth.py`](../../../gcp/image/github/github_auth.py): reduce `PLR0911` via small helpers (not via extra `return None` spam).
- [x] [`artifacts.py`](../../../gcp/image/runtime/artifacts.py), [`importer.py`](../../../gcp/image/runtime/importer.py): replace `print` / T201 with `logging` where appropriate.
- [x] [`testutils.py`](../../../tests/support/testutils.py): address `TRY004` with `TypeError` for invalid types (tests should still assert clearly).
- [x] [`gh_app_perms.py`](../../../tools/repo/gh_app_perms.py): optional `jwt` via `import jwt` + `.encode` binding without conflicting `encode`/`None` declarations.
- [x] [`facade.py`](../../../gcp/image/runtime/facade.py): `traceback.print_stack` only when `frame is not None` (`FrameType | None`).

---

## Phase F (optional): Test monkeypatch helpers

- [x] Skipped: gcs monkeypatch patterns exist but a shared helper is not clearly justified (YAGNI).

---

## Final gate

```bash
ruff check .
ruff format --check .
uv run ty check
uv run python -m pytest tests/ -v
```

Optional: kieran-python-reviewer on the final diff.

---

## Follow-up polish (addressed)

- **JWT binding:** `github_auth` and `gh_app_perms` share `encode_github_app_jwt_rs256` + `_jwt_encode` / `_PyJWTRS256Encode` Protocol.
- **`gcs.object_exists`:** Raises `GcsError` on API failures; `RunnerManager.validate_in_repo` catches GCS errors and falls back to local paths with a warning.
- **`legacy_kardome` PERF403:** Dict comprehension for non-`LD_LIBRARY_PATH` env merge.
- **Repo formatting:** `ruff format` applied to previously unformatted files (`reporting.py`, `assemble_release.py`, `contributor_docs.py`, stage plugin copy).
- **Integration test:** `test_runtime_modes_write_plan_summary_and_pointer` uses `publish_bmt(..., sync=False)` so it does not require live GCS when `GCS_BUCKET` is set.
