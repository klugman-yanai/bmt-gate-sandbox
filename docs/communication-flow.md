# BMT: GitHub Actions -> VM Handoff -> PR status/checks flow

This document describes the **current** communication model after the handoff-only workflow migration.

## Principle

`bmt.yml` validates handoff health only (trigger + VM handshake).

- Workflow success means handoff completed.
- Workflow failure means handoff failed.
- **BMT final outcome is VM-owned** and appears in PR checks/comments.
- This test repo uses `dummy-build-and-test.yml` (dummy/no-op build steps + runner artifact upload + BMT dispatch).

## Who owns what

| Stage | Owner | Source of truth |
|-------|-------|-----------------|
| Build and dispatch | `dummy-build-and-test.yml` | Actions run result + BMT tail dispatch summary |
| Handoff (trigger + VM ack) | `bmt.yml` | Actions run result + handoff summary |
| BMT pending/final status | VM watcher | PR commit status (`BMT_STATUS_CONTEXT`) |
| Detailed run outcome | VM watcher | PR check run + PR comments |

## Current flow overview

1. `dummy-build-and-test.yml` performs dummy/no-op CI steps, uploads runner artifacts, then dispatches `bmt.yml`.
2. `bmt.yml` prepares context, uploads runners, classifies path, and then:
   - `04A Handoff Skip (No Legs)` when no supported uploaded legs exist, or
   - `04B Handoff Run (Trigger + VM Ack)` when legs exist.
3. In run path, `bmt.yml` writes trigger, starts VM, waits for handshake ack, writes handoff summary, and exits.
4. VM processes legs asynchronously and posts pending/final commit status + check run updates to the PR.
5. If PR is closed:
   - Before pickup: VM acknowledges trigger as skipped and exits without leg execution.
   - During execution: VM stops before next leg, finalizes existing pending signals as cancelled (`check=neutral`, `status=error`), and skips PR comments.
6. If a newer commit arrives on the PR:
   - Older trigger SHA is treated as superseded (`superseded_by_new_commit`).
   - VM completes the current leg, cancels remaining legs between legs, finalizes old SHA signals (`check=neutral`, `status=error`), and does not promote pointers for the superseded run.
   - VM PR comments are upserted per tested SHA and include commit links (tested + superseding when applicable).

## What developers see

| Scenario | What the developer should look at |
|----------|-----------------------------------|
| CI run (dummy-build-and-test) success/failure | Dummy CI result + BMT handoff dispatch summary in workflow run. |
| Handoff success | Green `bmt.yml` run summary confirms VM acknowledged trigger. |
| Handoff failure | Failed `bmt.yml` run summary + diagnostics in Actions logs. |
| BMT in progress/complete | PR **Checks** and PR **Comments** (VM-owned updates). |
| PR closed during/after handoff | Runtime trigger ack/status shows skipped/cancelled PR-closure reason; no new PR comment is posted. |
| New commit supersedes an in-flight run | Older SHA run shows cancelled/superseded, while gating continues on the latest PR head SHA context only. |

## Branch protection

Branch protection should require the commit status context named by `BMT_STATUS_CONTEXT` (default: `BMT Gate`).

- The gate is VM-owned status.
- `bmt.yml` run conclusion is a handoff signal, not final BMT verdict.

## Operational note

If handoff succeeds but PR status does not move, debug VM auth/runtime in watcher logs and VM environment.
