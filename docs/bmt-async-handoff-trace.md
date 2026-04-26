# BMT async handoff — artifact trace

This document maps one `workflow_run_id` (GitHub Actions handoff “run id” / BMT correlation id) through GCS and Cloud Run. Use it when validating an end-to-end run.

## 1. Actions → Workflows API

`uv run kardome-bmt dispatch invoke-workflow` builds a payload in `ci/kardome_bmt/workflow_dispatch.py` and starts the Google Workflow execution. Important fields: `workflow_run_id`, `bucket`, `repository`, `head_sha`, `head_branch`, `head_event`, `pr_number`, `run_context`, `accepted_projects_json`, `status_context`.

## 2. Google Workflow → Cloud Run

`infra/pulumi/workflow.yaml` runs `bmt-control` (plan), then task jobs, then `bmt-control` (coordinator). The plan job receives GitHub context env vars (`BMT_HEAD_SHA`, `BMT_ACCEPTED_PROJECTS_JSON`, etc.). Task jobs receive `BMT_WORKFLOW_RUN_ID` and load the frozen plan from disk (see below).

## 3. Frozen plan (GCS)

`workflow_run_id` matches `core.workflow_run_id()` from the handoff context (typically `${{ github.run_id }}` from the workflow that invoked handoff).

- Plan path: `triggers/plans/{workflow_run_id}.json` (`runtime/artifacts.py` → `plan_path`).
- Leg summaries: `triggers/summaries/{workflow_run_id}/{project}-{bmt_slug}.json` (`summary_path`).
- Reporting metadata: `triggers/reporting/{workflow_run_id}.json` (`reporting_metadata_path`).

Task execution reads `ExecutionPlan` from the plan file (`runtime/execution.py`).

## 4. Coordinator → GitHub

After tasks write summaries, the coordinator aggregates and calls `runtime/github_reporting.py` (commit status + check runs using the GitHub App secrets on the Cloud Run job). The handoff workflow in Actions only confirms dispatch; final pass/fail appears on the commit and Checks tab asynchronously.

## 5. Local / dev handoff exercise

For PR-shaped CI in **this** repo without a full core-main build matrix, use **`build-and-test-dev.yml`** (placeholder builds + unified handoff; relies on bucket runners and real datasets). To exercise **`bmt-handoff.yml`** alone, use **`gh workflow run`** on that workflow with the documented `workflow_dispatch` inputs (see **`.github/README.md`**).

For **local legs, runner output, and plugins** without this GCS trace, see **[developer-workflow.md](developer-workflow.md)**.
