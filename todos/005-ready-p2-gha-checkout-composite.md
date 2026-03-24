---
status: ready
priority: p2
issue_id: "005"
tags: [github-actions, refactor]
dependencies: []
---

# GHA: `checkout-repo-head` composite (single checkout pin)

## Problem Statement

Same `actions/checkout` pin and `repository`/`ref` expressions are copy-pasted across jobs; bumps and drift risk.

## Recommended Action

Implement **Task 5** in the plan: new `.github/actions/checkout-repo-head/action.yml`; replace call sites in `build-and-test.yml`, `trigger-ci-pr.yml`, etc.; extend hardening test so checkout SHA lives only in composite.

## Acceptance Criteria

- [ ] Composite covers PR / PRT / default ref behavior equivalent to current YAML
- [ ] `test_workflow_hardening.py` + `test_local_composite_action_paths_resolve` pass
- [ ] actionlint clean

## Work Log

### 2026-03-24 - Created from epic split

**By:** Cursor Agent

**Actions:** File todo created; implementation pending.
