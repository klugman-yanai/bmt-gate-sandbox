# Harden Legacy Runner Scoring and Surface Case-Level Errors

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make runner failures visible — crashed cases should FAIL the leg (not silently produce score 0), and the check run / PR comment should show case-level breakdown so devs see problems without digging into GCS logs.

**Architecture:** Case failures flow through three layers: (1) the legacy runner records per-case errors, (2) the plugin's `score()` aggregates them into `ScorePayload.metrics`, (3) `FinalBmtRow` and `render_final_check_output()` surface them in the GitHub check UI. Each layer gets one new field; no new models or abstractions.

**Tech Stack:** Python 3.12, Pydantic v2 models, dataclasses, pytest

---

## Problem Statement

When `kardome_runner` crashes on a case (e.g. missing `libKardome.so`), the case produces `status="failed"` and `error="runner_exit_127"`, but:

1. **Score silently becomes 0** — `metrics={"namuh_count": float(counter if counter is not None else 0)}` at `legacy_kardome.py:194`. For `lte` comparisons (lower-is-better), crashed cases *help* the score.
2. **No case breakdown in UI** — the check run table shows only `Score: 82.21` with no indication that some cases crashed.
3. **`reason_code` stays `bootstrap_without_baseline`** — the plugin doesn't know about case failures; it only sees averaged scores.

## Design

### Principle: fail-loud on runner errors

- **Plugin `score()` counts failed cases** and stores `cases_ok` / `cases_total` / `cases_failed_ids` in `ScorePayload.metrics`.
- **Plugin `evaluate()` returns FAIL** with `reason_code="runner_case_failures"` when any case has `status != "ok"`, regardless of score.
- **`FinalBmtRow` gets a `cases_detail` string** (e.g. `"22/24 ok"` or `"24/24 ok"`) shown as a new column in the check run table.
- **`FinalCommentView` failure list** includes the case error detail.

### What doesn't change

- `CaseResult` model — already has `status`, `error`, `exit_code` fields (no changes needed).
- `LegSummary` model — `score.metrics` dict is schemaless; new keys go there.
- `ScorePayload` model — unchanged; the new keys are just dict entries in `metrics`.
- GCS snapshot format — `latest.json` already serializes the full `score.metrics`; new keys appear automatically.

---

## Task 1: SK plugin — count failed cases in `score()` and fail in `evaluate()`

**Files:**
- Modify: `gcp/stage/projects/sk/plugins/default/sha256-498dfda6cc4554665a1f0170f7f31db0253e71e3c0ec19eea68ab5f783f0a27c/src/sk_plugin/plugin.py`
- Modify: `gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py` (keep workspace copy in sync)
- Test: `tests/bmt/test_sk_plugin_scoring.py` (new)

### Step 1: Write failing tests

Create `tests/bmt/test_sk_plugin_scoring.py`:

```python
"""Unit tests for SK plugin score() and evaluate() with case failures."""
from __future__ import annotations

from pathlib import Path

import pytest

from gcp.image.config.bmt_domain_status import BmtLegStatus
from gcp.image.runtime.sdk.results import CaseResult, ExecutionResult, ScoreResult

pytestmark = pytest.mark.unit


def _make_plugin():
    """Import and instantiate SkPlugin."""
    from sk_plugin.plugin import SkPlugin
    return SkPlugin()


def _case(case_id: str, namuh: float, *, status: str = "ok", error: str = "") -> CaseResult:
    return CaseResult(
        case_id=case_id,
        input_path=Path(f"/data/{case_id}"),
        exit_code=0 if status == "ok" else 127,
        status=status,
        metrics={"namuh_count": namuh},
        error=error,
    )


def _exec_result(*cases: CaseResult) -> ExecutionResult:
    return ExecutionResult(execution_mode_used="kardome_legacy_stdout", case_results=list(cases))


def _make_context(*, comparison: str = "lte", tolerance: float = 0.25):
    """Build a minimal mock context with plugin_config."""
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.bmt_manifest.plugin_config = {"comparison": comparison, "tolerance_abs": tolerance}
    return ctx


class TestScoreAggregation:
    def test_all_ok_cases_average_correctly(self) -> None:
        plugin = _make_plugin()
        result = _exec_result(_case("a.wav", 10), _case("b.wav", 90))
        score = plugin.score(result, None, _make_context())
        assert score.aggregate_score == 50.0
        assert score.metrics["case_count"] == 2
        assert score.metrics["cases_ok"] == 2
        assert score.metrics["cases_failed"] == 0

    def test_failed_cases_excluded_from_average(self) -> None:
        plugin = _make_plugin()
        result = _exec_result(
            _case("a.wav", 10),
            _case("b.wav", 0, status="failed", error="runner_exit_127"),
            _case("c.wav", 90),
        )
        score = plugin.score(result, None, _make_context())
        # Failed case excluded: average of [10, 90] = 50, not [10, 0, 90] = 33.3
        assert score.aggregate_score == 50.0
        assert score.metrics["case_count"] == 3
        assert score.metrics["cases_ok"] == 2
        assert score.metrics["cases_failed"] == 1
        assert score.metrics["cases_failed_ids"] == ["b.wav"]

    def test_all_cases_failed_score_is_zero(self) -> None:
        plugin = _make_plugin()
        result = _exec_result(
            _case("a.wav", 0, status="failed", error="runner_exit_127"),
        )
        score = plugin.score(result, None, _make_context())
        assert score.aggregate_score == 0.0
        assert score.metrics["cases_ok"] == 0
        assert score.metrics["cases_failed"] == 1


class TestEvaluateFailsOnCaseErrors:
    def test_case_failures_force_fail_even_with_good_score(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 2, "cases_failed": 1, "cases_failed_ids": ["b.wav"]},
        )
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.status == BmtLegStatus.FAIL.value
        assert verdict.reason_code == "runner_case_failures"
        assert not verdict.passed

    def test_no_case_failures_bootstrap_passes(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 3, "cases_failed": 0},
        )
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.status == BmtLegStatus.PASS.value
        assert verdict.reason_code == "bootstrap_without_baseline"

    def test_no_case_failures_with_baseline_uses_tolerance(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 3, "cases_failed": 0},
        )
        baseline = ScoreResult(aggregate_score=50.0, metrics={})
        verdict = plugin.evaluate(score, baseline, _make_context(comparison="lte"))
        assert verdict.status == BmtLegStatus.PASS.value
        assert verdict.reason_code == "score_within_tolerance"
```

### Step 2: Run tests to verify they fail

```bash
uv run python -m pytest tests/bmt/test_sk_plugin_scoring.py -v
```

Expected: FAIL — `cases_ok` key missing from metrics, `evaluate()` doesn't check for case failures.

### Step 3: Update the SK plugin

In `plugin.py`, modify `score()` (lines 68-80):

```python
def score(
    self,
    execution_result: ExecutionResult,
    baseline: ScoreResult | None,
    context: ExecutionContext,
) -> ScoreResult:
    ok_cases = [r for r in execution_result.case_results if r.status == "ok"]
    failed_cases = [r for r in execution_result.case_results if r.status != "ok"]
    values = [r.metrics.get("namuh_count", 0.0) for r in ok_cases]
    aggregate = sum(float(v) for v in values) / len(values) if values else 0.0
    return ScoreResult(
        aggregate_score=aggregate,
        metrics={
            "case_count": len(execution_result.case_results),
            "cases_ok": len(ok_cases),
            "cases_failed": len(failed_cases),
            "cases_failed_ids": [r.case_id for r in failed_cases],
        },
        extra={"baseline_present": baseline is not None},
    )
```

Modify `evaluate()` (lines 82-115) — add case-failure check before the baseline logic:

```python
def evaluate(
    self,
    score_result: ScoreResult,
    baseline: ScoreResult | None,
    context: ExecutionContext,
) -> VerdictResult:
    comparison = str(context.bmt_manifest.plugin_config.get("comparison", "gte")).strip().lower()
    tolerance = float(context.bmt_manifest.plugin_config.get("tolerance_abs", 0.25) or 0.25)

    # Any case-level failure is an unconditional FAIL.
    cases_failed = int(score_result.metrics.get("cases_failed", 0))
    if cases_failed > 0:
        return VerdictResult(
            passed=False,
            status=BmtLegStatus.FAIL.value,
            reason_code="runner_case_failures",
            summary={
                "aggregate_score": score_result.aggregate_score,
                "comparison": comparison,
                "cases_failed": cases_failed,
                "cases_failed_ids": score_result.metrics.get("cases_failed_ids", []),
            },
        )

    if baseline is None:
        return VerdictResult(
            passed=True,
            status=BmtLegStatus.PASS.value,
            reason_code="bootstrap_without_baseline",
            summary={
                "aggregate_score": score_result.aggregate_score,
                "comparison": comparison,
                "baseline_score": None,
            },
        )
    if comparison == "lte":
        passed = score_result.aggregate_score <= baseline.aggregate_score + tolerance
    else:
        passed = score_result.aggregate_score >= baseline.aggregate_score - tolerance
    return VerdictResult(
        passed=passed,
        status=BmtLegStatus.PASS.value if passed else BmtLegStatus.FAIL.value,
        reason_code="score_within_tolerance" if passed else "score_outside_tolerance",
        summary={
            "aggregate_score": score_result.aggregate_score,
            "baseline_score": baseline.aggregate_score,
            "comparison": comparison,
            "tolerance_abs": tolerance,
        },
    )
```

Apply the same changes to the workspace copy at `gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py`.

### Step 4: Run tests to verify they pass

```bash
uv run python -m pytest tests/bmt/test_sk_plugin_scoring.py -v
```

Expected: all PASS.

### Step 5: Commit

```bash
git add tests/bmt/test_sk_plugin_scoring.py gcp/stage/projects/sk/plugins/default/sha256-498dfda6cc4554665a1f0170f7f31db0253e71e3c0ec19eea68ab5f783f0a27c/src/sk_plugin/plugin.py gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py
git commit -m "fix(sk-plugin): exclude failed cases from score average, FAIL on runner errors"
```

---

## Task 2: Add `runner_case_failures` to presentation reason labels

**Files:**
- Modify: `gcp/image/github/presentation.py:10-20`
- Test: existing `tests/github/test_github_presentation.py` (extend)

### Step 1: Add reason label

In `presentation.py`, add to `REASON_LABELS` dict (line ~16):

```python
"runner_case_failures": "runner crashed on one or more test files",
```

### Step 2: Verify existing tests still pass + add new test

Add to `test_github_presentation.py`:

```python
def test_human_reason_runner_case_failures() -> None:
    from gcp.image.github.presentation import human_reason
    assert human_reason("runner_case_failures") == "runner crashed on one or more test files"
```

### Step 3: Run tests

```bash
uv run python -m pytest tests/github/test_github_presentation.py -v
```

### Step 4: Commit

```bash
git add gcp/image/github/presentation.py tests/github/test_github_presentation.py
git commit -m "feat(presentation): add runner_case_failures reason label"
```

---

## Task 3: Add `cases_detail` column to check run table

**Files:**
- Modify: `gcp/image/github/presentation.py` — `FinalBmtRow`, `ProgressBmtRow`, `render_final_check_output()`, `render_progress_check_output()`
- Modify: `gcp/image/runtime/github_reporting.py:264-273` — `_final_view()`, `_progress_view()`
- Test: `tests/github/test_github_presentation.py` (update existing)

### Step 1: Add `cases_detail` to `FinalBmtRow` and `ProgressBmtRow`

In `presentation.py`:

```python
@dataclass(frozen=True, slots=True)
class FinalBmtRow:
    project: str
    bmt: str
    status: str
    aggregate_score: float
    reason_code: str
    duration_sec: int | None = None
    execution_mode_used: str = ""
    cases_detail: str = ""          # e.g. "22/24 ok" or ""
```

```python
@dataclass(frozen=True, slots=True)
class ProgressBmtRow:
    project: str
    bmt: str
    status: str
    duration_sec: int | None = None
    aggregate_score: float | None = None
    execution_mode_used: str = ""
    cases_detail: str = ""          # e.g. "22/24 ok" or ""
```

### Step 2: Add Cases column to table rendering

In `render_final_check_output()`, change the table header (line 204) and row rendering (lines 214-227):

```python
# Table header
"| Project | BMT | Status | Score | Cases | Reason | Duration |",
"|---------|-----|--------|-------|-------|--------|----------|",

# Row rendering — add cases_detail between score and reason
"| "
+ " | ".join(
    [
        row.project,
        row.bmt,
        _final_status_label(row.status),
        score_s,
        row.cases_detail or "—",
        human_reason(row.reason_code),
        _format_duration(row.duration_sec),
    ]
)
+ " |"
```

Similarly update `render_progress_check_output()` table header (line 170-172) and row (line 182):

```python
"| Project | BMT | Status | Score | Cases | Duration |",
"|---------|-----|--------|-------|-------|----------|",

# Row:
f"| {row.project} | {row.bmt} | {_progress_status_label(row.status)} | {score_s} | {row.cases_detail or '—'} | {_format_duration(row.duration_sec)} |"
```

### Step 3: Populate `cases_detail` from `score.metrics` in `_final_view()` and `_progress_view()`

In `github_reporting.py`, modify `_final_view()` (line ~264):

```python
def _cases_detail_from_metrics(metrics: dict[str, Any]) -> str:
    cases_ok = metrics.get("cases_ok")
    case_count = metrics.get("case_count")
    if cases_ok is None or case_count is None:
        return ""
    return f"{cases_ok}/{case_count} ok"
```

Use it in the `FinalBmtRow` construction:

```python
FinalBmtRow(
    project=summary.project,
    bmt=summary.bmt_slug,
    status=summary.status,
    aggregate_score=summary.score.aggregate_score,
    reason_code=summary.reason_code,
    duration_sec=summary.duration_sec,
    execution_mode_used=summary.execution_mode_used,
    cases_detail=_cases_detail_from_metrics(summary.score.metrics),
)
```

And in `_progress_view()` (line ~220) for completed legs:

```python
ProgressBmtRow(
    project=summary.project,
    bmt=summary.bmt_slug,
    status=summary.status,
    duration_sec=summary.duration_sec,
    aggregate_score=summary.score.aggregate_score,
    execution_mode_used=summary.execution_mode_used,
    cases_detail=_cases_detail_from_metrics(summary.score.metrics),
)
```

Add `from typing import Any` import if not already present in `github_reporting.py`.

### Step 4: Update existing presentation tests

In `test_github_presentation.py`, update all assertions that match table headers/rows:

- `test_render_final_failure_check_output_owns_the_detailed_table` — update header assertion and row assertions to include the `Cases` column.
- `test_render_progress_check_output_shows_bmt_table_and_progress` — same.
- `test_render_final_check_output_mock_runner_shows_placeholder_not_zero` — same.

Example for the final failure test:

```python
assert "| Project | BMT | Status | Score | Cases | Reason | Duration |" in output["summary"]
# Add cases_detail="22/24 ok" to FinalBmtRow construction in test fixtures
assert "| sk | false_rejects | FAIL | 41.25 | 22/24 ok | score dropped below baseline | 1m 5s |" in output["summary"]
```

### Step 5: Run all presentation + reporting tests

```bash
uv run python -m pytest tests/github/test_github_presentation.py tests/bmt/test_runtime_github_reporting.py -v
```

### Step 6: Commit

```bash
git add gcp/image/github/presentation.py gcp/image/runtime/github_reporting.py tests/github/test_github_presentation.py
git commit -m "feat(check-run): add Cases column showing per-file ok/total breakdown"
```

---

## Task 4: Include case errors in PR comment failure list

**Files:**
- Modify: `gcp/image/runtime/github_reporting.py:179-183` — `publish_final_results()`
- Test: `tests/bmt/test_runtime_github_reporting.py` (extend)

### Step 1: Enhance failure detail in PR comment

In `publish_final_results()`, extend the `failed_bmts` list to include case detail (line ~179):

```python
failed_bmts=[
    (
        summary.bmt_slug,
        human_reason(summary.reason_code)
        + (
            f" ({summary.score.metrics.get('cases_failed', '?')} of"
            f" {summary.score.metrics.get('case_count', '?')} cases crashed)"
            if summary.reason_code == "runner_case_failures"
            else ""
        ),
    )
    for summary in summaries
    if not leg_status_is_pass(summary.status)
],
```

This produces PR comment lines like:
```
- `false_rejects`: runner crashed on one or more test files (2 of 24 cases crashed)
```

### Step 2: Add/update test in `test_runtime_github_reporting.py`

Extend an existing test or add one that verifies the case-crash detail appears in the PR comment `failed_bmts` data when `reason_code == "runner_case_failures"`.

### Step 3: Run tests

```bash
uv run python -m pytest tests/bmt/test_runtime_github_reporting.py -v
```

### Step 4: Commit

```bash
git add gcp/image/runtime/github_reporting.py tests/bmt/test_runtime_github_reporting.py
git commit -m "feat(pr-comment): include case crash count in failure detail"
```

---

## Task 5: Remove dead VM fake code

**Files:**
- Delete: `tests/support/fakes/vm.py`
- Modify: `tests/_support/harness.py` — remove VM re-exports
- Modify: `tests/README.md` — remove VM references

### Step 1: Delete `vm.py`

```bash
rm tests/support/fakes/vm.py
```

### Step 2: Remove VM re-exports from `tests/_support/harness.py`

Remove the import line:
```python
from tests.support.fakes.vm import FakeVmBackend, VmDescribeStatus, VmMetadataCallRecord
```

Remove from `__all__`:
```python
"FakeVmBackend",
"VmDescribeStatus",
"VmMetadataCallRecord",
```

### Step 3: Update `tests/README.md`

Remove the `vm.py` line from the fakes table and the `FakeVmBackend` import example.

### Step 4: Run all tests to verify nothing breaks

```bash
uv run python -m pytest tests/ -v
```

### Step 5: Commit

```bash
git add -u tests/support/fakes/vm.py tests/_support/harness.py tests/README.md
git commit -m "chore: remove dead FakeVmBackend (VM era code, unused)"
```

---

## Task 6: Rebuild and push Docker image, verify E2E

### Step 1: Run full test suite

```bash
uv run python -m pytest tests/ -v
```

### Step 2: Rebuild and push

```bash
docker buildx build --load -t bmt-orchestrator:latest -f gcp/image/Dockerfile .
IMAGE="europe-west4-docker.pkg.dev/train-kws-202311/bmt-images/bmt-orchestrator:latest"
docker tag bmt-orchestrator:latest "$IMAGE"
docker push "$IMAGE"
```

### Step 3: Push and trigger CI

```bash
git push origin ci/check-bmt-gate
```

### Step 4: Verify check run output

After the workflow completes, confirm:
- Check run table has a `Cases` column showing `N/N ok`
- If any cases fail: `reason_code` is `runner_case_failures`, status is FAIL
- PR comment shows case crash count for failed BMTs
- Score excludes failed cases from the average

---

## Expected check run output after this plan

### All cases pass (normal):
```
| Project | BMT | Status | Score | Cases | Reason | Duration |
|---------|-----|--------|-------|-------|--------|----------|
| sk | false_alarms | PASS | 2.00 | 6/6 ok | first run — baseline established | 24s |
| sk | false_rejects | PASS | 82.21 | 24/24 ok | first run — baseline established | 17m 6s |
```

### Runner crashes on 2 files:
```
| Project | BMT | Status | Score | Cases | Reason | Duration |
|---------|-----|--------|-------|-------|--------|----------|
| sk | false_rejects | FAIL | 87.50 | 22/24 ok | runner crashed on one or more test files | 15m 2s |
```

PR comment:
```
- `false_rejects`: runner crashed on one or more test files (2 of 24 cases crashed)
```

---

## Critical files

| File | Role |
|------|------|
| `gcp/stage/projects/sk/plugins/.../plugin.py` | Score aggregation and verdict logic |
| `gcp/image/github/presentation.py` | Check run table rendering |
| `gcp/image/runtime/github_reporting.py` | PR comment and check run population |
| `gcp/image/runtime/legacy_kardome.py` | Runner execution (already has error fields) |
| `tests/bmt/test_sk_plugin_scoring.py` | New: plugin scoring unit tests |
| `tests/github/test_github_presentation.py` | Updated: table column assertions |
