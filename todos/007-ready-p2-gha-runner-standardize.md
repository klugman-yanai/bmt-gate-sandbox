---
status: ready
priority: p2
issue_id: "007"
tags: [github-actions, infrastructure]
dependencies: []
---

# GHA: Standardize `runs-on` (runner image policy)

## Problem Statement

Mix of `ubuntu-22.04` and possibly `ubuntu-latest` across workflows; no documented policy; OS bumps can break apt/cmake/toolchains.

## Recommended Action

Implement **Task 7** in the plan: grep inventory; choose LTS vs latest policy; align YAML; document in `.github/README.md` or `docs/configuration.md`; smoke test if version changes.

## Acceptance Criteria

- [ ] Single documented policy for hosted Linux jobs
- [ ] Workflows aligned (exceptions documented if any)
- [ ] CI green after any OS change

## Work Log

### 2026-03-24 - Created from epic split

**By:** Cursor Agent

**Actions:** File todo created; implementation pending.
