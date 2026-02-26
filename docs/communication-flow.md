# BMT: GitHub Actions -> VM Handoff -> PR status/checks flow

This document describes the **current** communication model after the handoff-only workflow migration.

## Principle

`bmt.yml` validates handoff health only (trigger + VM handshake).

- Workflow success means handoff completed.
- Workflow failure means handoff failed.
- **BMT final outcome is VM-owned** and appears in PR checks/comments.
- `build-and-test.yml` keeps a prod-immutable base (`original_build-and-test.yml`) plus an append-only BMT tail.

## Who owns what

| Stage | Owner | Source of truth |
|-------|-------|-----------------|
| Build and dispatch | `build-and-test.yml` | Actions run result + BMT tail dispatch summary |
| Handoff (trigger + VM ack) | `bmt.yml` | Actions run result + handoff summary |
| BMT pending/final status | VM watcher | PR commit status (`BMT_STATUS_CONTEXT`) |
| Detailed run outcome | VM watcher | PR check run + PR comments |

## Current flow overview

1. `build-and-test.yml` builds artifacts from the immutable base, then append-only BMT tail dispatches `bmt.yml`.
2. `bmt.yml` prepares context, uploads runners, classifies path, and then:
   - `04A Handoff Skip (No Legs)` when no supported uploaded legs exist, or
   - `04B Handoff Run (Trigger + VM Ack)` when legs exist.
3. In run path, `bmt.yml` writes trigger, starts VM, waits for handshake ack, writes handoff summary, and exits.
4. VM processes legs asynchronously and posts pending/final commit status + check run updates to the PR.

## What developers see

| Scenario | What the developer should look at |
|----------|-----------------------------------|
| CI run (build-and-test) success/failure | Build/test result + BMT handoff dispatch summary in workflow run. |
| Handoff success | Green `bmt.yml` run summary confirms VM acknowledged trigger. |
| Handoff failure | Failed `bmt.yml` run summary + diagnostics in Actions logs. |
| BMT in progress/complete | PR **Checks** and PR **Comments** (VM-owned updates). |

## Branch protection

Branch protection should require the commit status context named by `BMT_STATUS_CONTEXT` (default: `BMT Gate`).

- The gate is VM-owned status.
- `bmt.yml` run conclusion is a handoff signal, not final BMT verdict.

## Operational note

If handoff succeeds but PR status does not move, debug VM auth/runtime in watcher logs and VM environment.
