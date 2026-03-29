# Runbook

**Purpose:** **How-to** for **operators** debugging **production or staging** BMT runs (GCP, GCS, GitHub). For local development, use [CONTRIBUTING.md](../CONTRIBUTING.md).

A **runbook** is not architecture theory: it answers **“something is wrong — what do I check, in what order?”**

## Correlation ID

Use **`workflow_run_id`** (GitHub Actions run id) to correlate:

- **GCS:** `triggers/plans/<id>.json`, `triggers/summaries/<id>/…`, `triggers/reporting/<id>.json` (see [architecture.md](architecture.md))
- **GCP:** Workflow execution in Cloud console
- **Logs:** Cloud Run jobs — control (plan/coordinator) vs task (standard/heavy)

## Where to look first

1. **GitHub** — workflow run, commit status, Check Run for the BMT context.
2. **Workflows** — failed plan, task, or coordinator; leg index and profile.
3. **GCS** — plan present; per-leg summaries; snapshots under `projects/<project>/results/<bmt_slug>/snapshots/`.
4. **`triggers/`** — after success, coordinator should have cleaned up; leftovers may mean partial failure.

## Common symptoms

| Symptom | Likely checks |
| --- | --- |
| Stuck **pending** | Coordinator never ran; GitHub finalize failed — [architecture.md — Maintainer risks](architecture.md#maintainer-risks-weak-points) |
| Gate vs bucket disagree | Split-brain: `ci_verdict.json` vs Check Run |
| Missing leg summary | Task crash; GCS eventual consistency delay |

## Secrets and access

- **CI → GCP:** WIF (no long-lived keys in Actions).
- **Runtime → GitHub:** App tokens from Secret Manager — [infrastructure.md](infrastructure.md).

Do not paste tokens or keys into public issues.

## Related

- [infrastructure.md](infrastructure.md) — vars, Pulumi, secrets
- [architecture.md](architecture.md) — pipeline and storage
- [.github/README.md](../.github/README.md) — workflow behavior
