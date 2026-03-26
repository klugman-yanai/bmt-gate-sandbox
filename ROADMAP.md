# Roadmap

Scaffold for **internal** planning. Edit this file as priorities change; delete placeholder rows you do not need.

## Now

| Item | Notes |
| ---- | ----- |
| _— add rows as needed —_ | |

## Next

| Item | Notes |
| ---- | ----- |
| **bmt-workflow readability** | Phased plan in **Later / backlog** — docs map (phase A) before YAML refactor (B–D). |

## Later / backlog

- **Simplify and harden `bmt-workflow` (Google Workflows) structure.**

  **Problem:** The deployed workflow (source: [`infra/pulumi/workflow.yaml`](infra/pulumi/workflow.yaml), rendered by Pulumi in [`infra/pulumi/__main__.py`](infra/pulumi/__main__.py)) is **correct** but **hard to read** in the Cloud Console graph: flat step list plus `switch` / nested `try/except` produces **crossing edges** and looks more parallel than the real **sequential** semantics (plan → optional standard job → optional heavy job → coordinator).

  **Goals (in order):**

  1. **Single source of truth for control flow** in repo docs (operators and maintainers can reason without staring at the console).
  2. **Optional refactor** of YAML to reduce duplication and clarify structure **without changing runtime behavior** (same Cloud Run jobs, env vars, GCS plan read, task counts, coordinator, and outer `finalize-failure` path).
  3. **Regression safety** after any structural change (see verification below).

  **Non-goals (unless a new ADR says otherwise):**

  - Running **standard** and **heavy** Cloud Run jobs in **true parallel** (today they are **sequential phases**; changing that affects wall time and failure semantics).
  - Replacing Workflows with another orchestrator.

  **Phased plan**

  | Phase | Deliverable | Notes |
  | ----- | ----------- | ----- |
  | **A — Map** | Short “execution map” in docs | Add a subsection (e.g. under [`docs/architecture.md`](docs/architecture.md) or [`docs/pipeline-dag.md`](docs/pipeline-dag.md)) listing **exact** step order: `init` → `run_plan_job` → `read_plan` → `parse_plan` → `derive_plan_counts` → `maybe_run_standard` → `run_standard_job?` → `maybe_run_heavy` → `run_heavy_job?` → `run_coordinator_job`, plus outer `except` → `finalize-failure`. Include a **mermaid** `flowchart TD` or `sequenceDiagram` that mirrors YAML, not the console layout. Link **`tasks_failed`** and per-job `try/except` behavior in one paragraph. |
  | **B — Dedupe** | Shared pattern for “run task job + note failure” | Today `run_standard_job` and `run_heavy_job` duplicate connector call shape and `except` assign. Extract a **subworkflow** or shared step block per [Google Workflows sub-workflows](https://cloud.google.com/workflows/docs/reference/syntax/subworkflows) (same file, `call:` with `params`) so only **job name** and **`BMT_TASK_PROFILE`** differ. Keep **`result`** variables distinct (`standard_job_execution` / `heavy_job_execution`). |
  | **C — Clarify switches** | Readable branching | Replace opaque `condition: true` fall-through with a **named default** step or comment in YAML (where syntax allows) so “skip standard → go to heavy gate” is obvious. Optionally reorder steps **only** if it improves readability **without** altering `next` semantics (validate with a side-by-side execution trace). |
  | **D — Console / ops** | Runbook one-liner | In [`docs/runbook.md`](docs/runbook.md), add how to open an execution, which steps are **expected** to skip when counts are zero, and that a “busy” graph is **normal**. |

  **Verification (must pass before calling the refactor done)**

  - **Static:** `pulumi preview` (or CI) shows only intended `Workflow` / `source_contents` diff; no accidental change to job names, SA, or connector timeout token.
  - **Behavioral (staging or controlled prod run):** At least one run each for: **standard-only**, **heavy-only**, **both**, **neither** (zero tasks → coordinator still runs with counts from plan), **injected task failure** (standard or heavy path sets `tasks_failed` and coordinator still runs), **failure before coordinator** (outer `except` runs `finalize-failure` with `BMT_FAILURE_REASON`). Compare execution logs and GCS artifacts to pre-refactor behavior.
  - **Contract:** [`docs/architecture.md`](docs/architecture.md) sequence (plan → tasks → coordinator) unchanged.

  **Risks**

  - Subworkflow **`call`** boundaries can change **error propagation** or variable scope; test `except` paths explicitly.
  - Pulumi **`render_workflow_source`** / template placeholders (`__CONNECTOR_TIMEOUT_SEC__`) must stay wired after edits.

  **References:** [`infra/pulumi/workflow.yaml`](infra/pulumi/workflow.yaml), [`docs/architecture.md`](docs/architecture.md), [`docs/adr/0001-accept-workflows-cloud-run.md`](docs/adr/0001-accept-workflows-cloud-run.md).

- **Cron sweep for stale pending BMT Gate status.**

  **What it does:** A scheduled GitHub Actions workflow that runs on a cron (e.g. every 15 minutes). It lists open PRs, checks each head SHA for a "BMT Gate" commit status or Check Run that has been stuck on pending / in-progress longer than a staleness threshold (e.g. 45 minutes — well beyond any normal BMT run), and posts a terminal `error` commit status so the PR is unblocked. Uses the existing `bmt handoff post-timeout-status` CLI command, which already checks whether the status is already terminal before posting (idempotent, safe under concurrent runs). Runs entirely on GitHub Actions with `GITHUB_TOKEN` — no GCP credentials needed.

  **When it is needed:** Only when the entire Google Cloud side fails to run any code at all — meaning no Python ever executes to post a terminal status. Examples: Cloud Run image pull failure (bad digest, deleted tag, registry outage), Google Workflows execution silently dropped or stuck, GCP-wide service disruption, or the Workflow exception handler's `finalize-failure` job itself crashing before it can report back. All cases where Cloud Run code *does* run (including crashes mid-execution) are already handled by the coordinator's finally block, `publish_github_failure` retry logic, and the Workflow exception handler.

  **Expected frequency:** Rare. This is a last-resort safety net, not a routine mechanism. It would fire only during GCP infrastructure incidents or after a bad image deploy that breaks container startup. In normal operation it should find nothing to do. The cost is minimal (one lightweight Actions runner every 15 minutes scanning the GitHub API) and the benefit is avoiding a PR blocked indefinitely with no way to recover short of manual intervention.

## References (stable docs)

- [docs/architecture.md](docs/architecture.md) — Pipeline, diagrams, maintainer deep dive (weak points, remediation ideas).
- [docs/runbook.md](docs/runbook.md) — Production debugging.
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contributor workflow.

**History:** Older roadmap and plan write-ups were removed from the tree; use **git history** if you need retired markdown.
