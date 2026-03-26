# Finalize-failure when reporting metadata is missing

## Problem

If a PR is closed or the Google Workflow aborts **before** the plan-mode job runs `ensure_reporting_metadata_for_plan`, there is no `triggers/reporting/{workflow_run_id}.json` with `check_run_id` and `workflow_execution_url`. `publish_github_failure` then skips closing a GitHub Check because there is nothing to PATCH.

## What we ship today

- **Synthetic `ExecutionPlan`** from `ENV_BMT_FINALIZE_*` (and optional `BMT_HANDOFF_RUN_URL`, `BMT_GCS_BUCKET_NAME`) so finalize can still run when `triggers/plans/{id}.json` is missing.
- **Clearer skip logging** when metadata is missing: operators see `workflow_run_id`, `handoff_run_url`, and `gcs_bucket` in the log line.
- **pr-active** and PR/check **correlation block** (handoff Actions URL, GCS browse, run id) so operators can debug without the Workflow console alone.

## Future: create a completed check from finalize

Possible enhancement: if metadata is absent but app token + `repository` + `head_sha` are valid, call the GitHub Checks API to **create** a completed failed check with a short body (handoff + GCS links). **Not implemented** here: extra API surface, idempotency with `external_id`, and risk of duplicate checks if metadata appears later. Revisit if dangling gates remain common after the correlation UX improvements.
