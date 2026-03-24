---
status: ready
priority: p2
issue_id: "008"
tags: [github-actions, testing, supply-chain]
dependencies: ["002"]
---

# GHA: Hardening tests for cache pin + Dependabot (optional) + actionlint

## Problem Statement

New `actions/cache` usage must follow “pin only in composite” rule. Optional Dependabot reduces drift for GitHub-owned actions.

## Findings

- [`tests/ci/test_workflow_hardening.py`](../tests/ci/test_workflow_hardening.py) already guards `setup-uv`, upload/download artifacts.

## Recommended Action

Implement **Task 4** in the plan after **002** (cache composite exists): assert `actions/cache@` only in `cache-repo`; optional `.github/dependabot.yml` for `github-actions`; run actionlint on touched workflows.

## Acceptance Criteria

- [ ] Pytest hardening includes cache pin assertion when composite lands
- [ ] Dependabot added or explicitly deferred in epic notes
- [ ] actionlint passes on changed workflow files

## Work Log

### 2026-03-24 - Created from epic split

**By:** Cursor Agent

**Actions:** File todo created; `dependencies: ["002"]` so pin test follows cache composite.
