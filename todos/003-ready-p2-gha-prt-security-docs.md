---
status: ready
priority: p2
issue_id: "003"
tags: [github-actions, security, documentation]
dependencies: []
---

# GHA: `pull_request_target`, fork policy, release templates

## Problem Statement

Production PR CI may run fork head builds under `pull_request_target` context; GitHub docs warn against building untrusted head on this event. Need explicit policy, docs, and template changes.

## Findings

- [`scripts/release_templates/workflows/trigger-ci-pr.yml`](../scripts/release_templates/workflows/trigger-ci-pr.yml) uses `pull_request_target` + `secrets: inherit`.
- In-repo [`trigger-ci-pr.yml`](../.github/workflows/trigger-ci-pr.yml) uses `pull_request`.

## Recommended Action

Implement **Task 2** in the plan: README subsection; Option A and/or B; optional explicit `secrets` on `workflow_call` + test updates.

## Acceptance Criteria

- [ ] `.github/README.md` documents PRT + fork + BMT gate behavior
- [ ] Release template (and callers if needed) match chosen option
- [ ] `test_workflow_hardening.py` updated if thin-trigger secret rules change

## Work Log

### 2026-03-24 - Created from epic split

**By:** Cursor Agent

**Actions:** File todo created; implementation pending.
