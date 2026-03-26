---
status: ready
priority: p2
issue_id: "004"
tags: [github-actions, observability]
dependencies: []
---

# GHA: Job summaries for handoff (and optional build)

## Problem Statement

Operators dig through logs for `head_sha`, `ci_run_id`, and dispatch outcomes. `GITHUB_STEP_SUMMARY` should surface high-signal fields on the run summary page.

## Recommended Action

Implement **Task 3** in [`.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md`](../.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md): extend handoff (and optionally build) summaries; prefer [`bmt-write-summary`](../.github/actions/bmt-write-summary/action.yml) if it keeps logic centralized.

## Acceptance Criteria

- [ ] Handoff run shows key fields in job summary (no secrets)
- [ ] Optional build matrix lines documented or implemented
- [ ] Sample run verified on GitHub UI

## Work Log

### 2026-03-24 - Created from epic split

**By:** Cursor Agent

**Actions:** File todo created; implementation pending.
