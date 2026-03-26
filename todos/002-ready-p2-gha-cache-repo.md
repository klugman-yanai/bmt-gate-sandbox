---
status: ready
priority: p2
issue_id: "002"
tags: [github-actions, performance, caching]
dependencies: []
---

# GHA: `cache-repo` composite + Gradle + uv caches

## Problem Statement

Build matrices repeat Gradle and uv downloads every run; no `actions/cache` today. Need faster CI without weakening fork/`pull_request_target` safety.

## Findings

- `GRADLE_USER_HOME` set in [`.github/workflows/build-and-test.yml`](../.github/workflows/build-and-test.yml).
- Pin pattern exists: `upload-artifact-repo`, `setup-uv-repo`.

## Recommended Action

Implement **Task 1** in [`.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md`](../.cursor/plans/2026-03-24-gha-modern-conventions-upgrade.md): add `cache-repo`, wire Gradle + uv keys, document fork policy.

## Acceptance Criteria

- [ ] `cache-repo` composite with SHA-pinned `actions/cache`
- [ ] Caches wired in build workflow(s) per plan
- [ ] Fork/PRT policy documented (README or PR)
- [ ] `pytest tests/ci/test_workflow_hardening.py` passes (extend in **008** if pin test deferred)

## Work Log

### 2026-03-24 - Created from epic split

**By:** Cursor Agent

**Actions:** File todo created; implementation pending.
