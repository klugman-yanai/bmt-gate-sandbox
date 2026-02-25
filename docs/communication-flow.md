# BMT: GitHub Actions → PR status/checks communication flow

This document maps how commit status and Check Runs get from the workflows and VM to the PR, and where gaps exist (and how they are closed).

## Principle: the developer is never left in the dark

**Whoever opens the PR or merge request must always get a clear BMT result** — never a perpetual spinner, never silence. Every path (success, failure, timeout, crash) must produce a commit status (and where applicable a Check Run) with an **actionable description**: what happened and, when relevant, what to do next (e.g. "Check Actions logs", "just gcs-trigger RUN_ID", "just vm-serial").

| Scenario | What the dev sees |
|----------|-------------------|
| CI build fails | Build job fails; BMT is not triggered. No BMT status (expected). |
| Trigger BMT fails (e.g. 403) | **Failure** status: "Trigger BMT failed. Check Actions logs." |
| BMT workflow fails before context | **Failure** status: "BMT workflow failed before context. Check Actions logs." |
| BMT workflow fails after context (e.g. handshake timeout) | **Failure** status with handshake hint (Actions logs; `just gcs-trigger RUN_ID`; `just vm-serial`). |
| VM handshake succeeds, then runs to completion | **Pending** → **Success** or **Failure** (commit status + Check Run with details). |
| VM posts pending then crashes / raises | **Failure** status + Check Run concluded as failure (VM exception handler). |
| VM has no GitHub auth | Workflow-side status only (pending then failure on handshake timeout). |

All failure descriptions are kept within GitHub’s 140-character limit and point the dev to logs or local commands where possible.

## Flow overview

| Stage | Who | What is posted to GitHub |
|-------|-----|--------------------------|
| **CI (ci.yml)** | Trigger BMT job | *(none today)* — CI does not post status. If Trigger BMT fails (e.g. 403), PR has no indication. **Closed by:** posting failure when Trigger BMT step fails. |
| **BMT workflow start** | bmt.yml | *(none until handshake)* — PR has no BMT status until VM handshake succeeds. **Closed by:** optional early "BMT started" pending job. |
| **BMT after handshake** | bmt.yml job 06 | **Commit status: pending** — "BMT running on VM; status will update when complete." Only runs when vm-handshake job succeeds. |
| **BMT on workflow failure** | bmt.yml job 07 | **Commit status: failure** — When any job fails (e.g. handshake timeout), so PR is not stuck pending. |
| **BMT when bmt-context failed** | bmt.yml | *(gap)* — If bmt-context or very early jobs fail, job 07 does not run (it needs bmt-context.result == 'success'). **Closed by:** job that runs when bmt-context failed and posts failure using `github.event.inputs.head_sha`. |
| **VM picks up trigger** | vm_watcher.py | Writes handshake ack to GCS; then **Commit status: pending** + **Check Run created (in_progress)**. |
| **VM per leg** | vm_watcher.py | **Check Run** progress updated. |
| **VM completes** | vm_watcher.py | **Check Run: completed** (success/failure) + **Commit status: success/failure**. |
| **VM exception mid-run** | — | *(gap)* — If _process_run_trigger raises after posting pending but before final status, PR stays pending. **Closed by:** try/except in VM that posts failure on exception. |
| **VM no auth** | vm_watcher.py | Logs "No GitHub auth"; never posts. PR relies on workflow-side status only. |

## Implemented closures

- **post-failure-status** (BMT job 07): runs when `failure() && needs.bmt-context.result == 'success'`, posts failure with context and description (handshake timeout hint when vm-handshake failed).
- **CI Trigger BMT failure**: CI job has `permissions: statuses: write` and a step that runs `if: failure()` and posts failure status so the PR is not left without a BMT result when Trigger BMT fails.
- **BMT early failure (no bmt-context)** (job 08): runs when `failure() && needs.bmt-context.result == 'failure'`, posts failure using `github.event.inputs.head_sha`.
- **BMT early pending** (job 01): runs after bmt-context, posts pending "BMT started; waiting for VM handshake…" so the PR shows BMT status before handshake.
- **VM exception**: In _process_run_trigger, the main work (legs, aggregate, final status) is wrapped in try/except; on exception we post failure commit status, complete the Check Run as failure, delete the trigger, and return so the watcher keeps running.

## What devs see in GitHub (browser)

Optimized for the in-browser experience (no local TUI):

- **PR status line** — The BMT commit status description updates as each leg completes (e.g. "BMT: 1/2 legs · 1 pass, 1 running — 4m"). Devs see progress without opening the check. Final state shows "BMT: 2/2 passed" or "BMT: 1 failed, 1 passed".
- **Check Run (click the status)** — One-line headline (e.g. "Running — 1/2 legs complete · Elapsed: 4m · ETA: ~2m left"), then a table of legs (Project | BMT | Status | Progress | Duration). Footer: "Refresh this page to see latest progress." Check Run content is updated after each leg; devs refresh the check page to see updates.
- **Gate** — Merge approval relies on the **commit status** (e.g. "BMT Gate"); the Check Run is for visibility and details only.

## Branch protection

Branch protection should require the **commit status** named by `BMT_STATUS_CONTEXT` (default "BMT Gate") to pass. Check Runs are for UX; the gate is the commit status.

## Further reading

For more tools and API options (GitHub Actions job summaries, re-run, debug logging; `gh run watch`, `gh pr checks --watch` / `--web`; Check Run annotations and images), see **docs/github-actions-and-cli-tools.md**.
