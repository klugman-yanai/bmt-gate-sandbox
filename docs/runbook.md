# Runbook

**Purpose:** **How-to** for **operators** debugging **production or staging** BMT runs (GCP, GCS, GitHub). For local development, use [CONTRIBUTING.md](../CONTRIBUTING.md).

A **runbook** is not architecture theory: it answers **“something is wrong — what do I check, in what order?”**

## Correlation ID

Use **`workflow_run_id`** (GitHub Actions run id) to correlate:

- **GCS:** `triggers/plans/<id>.json`, `triggers/summaries/<id>/…`, `triggers/reporting/<id>.json` (see [architecture.md](architecture.md))
- **Dispatch intent:** `triggers/dispatch/<id>.json`
- **Coordinator state:** `triggers/finalization/<id>.json` when terminal publish/promotion needs inspection
- **GCP:** Workflow execution in Cloud console
- **Logs:** Cloud Run jobs — control (plan/coordinator) vs task (standard/heavy)

## Where to look first

1. **GitHub** — workflow run, commit status, Check Run for the BMT context.
2. **Workflows** — failed plan, task, or coordinator; leg index and profile.
3. **GCS** — plan present; per-leg summaries; snapshots under `projects/<project>/results/<bmt_slug>/snapshots/`.
4. **`uv run bmt ops doctor --workflow-run-id <id>`** — repo-owned summary of dispatch receipt, finalization state, preserved reporting metadata, leases, and log-dump presence.
5. **`triggers/`** — after success, plan/progress/summaries/reporting should be cleaned up and lease files released; a surviving `triggers/finalization/<id>.json` or `triggers/dispatch/<id>.json` is expected evidence when publish/promotion or dispatch did not complete cleanly.

## Useful commands

- `uv run bmt ops doctor --workflow-run-id <id>`
- `uv run bmt ops doctor --scan-stale --older-than-hours 24`

## Common symptoms

| Symptom | Likely checks |
| --- | --- |
| Stuck **pending** | Coordinator never ran; GitHub finalize failed — [architecture.md — Maintainer risks](architecture.md#maintainer-risks-weak-points) |
| Gate vs bucket disagree | Split-brain: `ci_verdict.json` vs Check Run |
| Missing leg summary | Task crash; GCS eventual consistency delay; inspect `expected_leg_count` / `missing_leg_keys` in `triggers/finalization/<id>.json` |
| Dispatch reused or aborted unexpectedly | Inspect `triggers/dispatch/<id>.json` for `state`, repo, head SHA, and execution URL |

## Cancellation and preserved reporting metadata

- **GitHub Actions `cancel-in-progress` does not cancel Google Workflows by itself.** A newer handoff can stop the prior Actions job while the earlier workflow execution is still running remotely.
- **PR close uses** [`.github/workflows/bmt-cancel-on-pr-close.yml`](../.github/workflows/bmt-cancel-on-pr-close.yml) to cancel the indexed workflow execution and run `finalize-failure` when possible.
- If a coordinator run had a real GitHub publish obligation and still exits with publish incomplete, the runtime now preserves **`triggers/reporting/<workflow_run_id>.json`** instead of deleting it immediately. Treat that as a reconciliation/debug signal, not as normal leftover trigger noise.
- `uv run bmt ops doctor --scan-stale` treats preserved reporting metadata, stale leases, stale finalization records, stale dispatch receipts, and old `log-dumps/` as the first-pass reconciliation inventory.

## Secrets and access

- **CI → GCP:** WIF (no long-lived keys in Actions).
- **Runtime → GitHub:** App tokens from Secret Manager — [infrastructure.md](infrastructure.md).

Do not paste tokens or keys into public issues.

## Related

- [infrastructure.md](infrastructure.md) — vars, Pulumi, secrets
- [architecture.md](architecture.md) — pipeline and storage
- [.github/README.md](../.github/README.md) — workflow behavior
