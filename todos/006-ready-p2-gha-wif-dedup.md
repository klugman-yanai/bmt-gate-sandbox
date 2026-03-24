---
status: ready
priority: p2
issue_id: "006"
tags: [github-actions, gcp, oidc]
dependencies: []
---

# GHA: Consolidate WIF / `setup-gcp-uv` repetition

## Problem Statement

Handoff and related jobs repeat `permissions` + GCP auth + uv setup patterns; easy to introduce inconsistent `id-token` or scopes.

## Recommended Action

Implement **Task 6** in the plan: inventory duplicates; consolidate via `setup-gcp-uv` extension or new thin wrapper; document standard job shape in `.github/README.md`.

## Acceptance Criteria

- [ ] No accidental broadening of checkout or secret scope
- [ ] Handoff publish/dispatch legs still authenticate to GCP
- [ ] Pytest + actionlint green

## Work Log

### 2026-03-24 - Created from epic split

**By:** Cursor Agent

**Actions:** File todo created; implementation pending.
