---
status: ready
priority: p2
issue_id: "001"
tags: [github-actions, ci, security, documentation]
dependencies: []
---

# Epic: GitHub Actions modernization + structural hardening

## Problem Statement

CI workflows should align with current GitHub guidance (caching, `pull_request_target` hygiene, summaries, action pinning) and reduce duplicated checkout/WIF/runner patterns. Work is multi-file and spans several PR-sized increments.

## Findings

- Context7 pass and repo audit documented in [`.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md`](../.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md).
- Release template [`scripts/release_templates/workflows/trigger-ci-pr.yml`](../scripts/release_templates/workflows/trigger-ci-pr.yml) uses `pull_request_target` with head checkout; BMT gated for same-repo only; build path needs explicit policy.
- No Gradle/uv `actions/cache` today; checkout SHA repeated across jobs.

## Proposed Solutions

Tracked as **split file todos** `002`–`008` (execute in suggested order in the plan). Epic stays open until children complete or are consciously deferred.

## Recommended Action

1. Use the plan as the implementation contract (checkboxes per task).
2. Close **001** when all child todos are `complete` or moved to deferred with notes.
3. Prefer one PR per file-todo for reviewability; combine only tightly coupled pairs (e.g. cache + pin test).

## Technical Details

**Plan:** [`.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md`](../.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md)

**Child issues:** `002` cache · `003` PRT/security/docs · `004` summaries · `005` checkout composite · `006` WIF dedup · `007` runs-on · `008` guardrails/Dependabot

## Resources

- [pull_request_target security](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows)
- [Dependency caching](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows)

## Acceptance Criteria

- [ ] Child todos triaged (ready/deferred) and linked from this epic
- [ ] Plan checkboxes updated or epic work log notes completion per task
- [ ] Final state: all in-scope tasks done or explicitly deferred with rationale

## Work Log

### 2026-03-24 - Epic + plan split

**By:** Cursor Agent

**Actions:**
- Added repo plan `.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md` with tasks 1–8 and file map.
- Split backlog into `todos/002`–`008` with optional dependencies.

**Learnings:**
- Structural work (checkout/WIF/runners) is isolated into separate todos to limit blast radius per PR.

## Notes

- Optional Task 8 items in plan remain deferrable; do not block epic closure if product declines.
