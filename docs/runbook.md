# Operations runbook

**Audience:** Operators debugging **production** or **staging** BMT runs (GCP, GCS, GitHub). For local development and contributor workflows, see [development.md](development.md).

## Correlation ID

Every CI run is keyed by **`workflow_run_id`** (GitHub Actions run id) or the equivalent id passed into Google Workflows. Use it to find:

- **GCS:** `triggers/plans/<workflow_run_id>.json`, `triggers/summaries/<workflow_run_id>/...`, ephemeral `triggers/reporting/<workflow_run_id>.json` (see [architecture.md](architecture.md) and [pipeline-dag.md](pipeline-dag.md))
- **GCP:** Workflow execution in the Google Cloud console (URL may be recorded under `triggers/reporting/` for Check Run details)
- **Logs:** Cloud Run job logs for `bmt-control` (plan/coordinator) and `bmt-task-standard` / `bmt-task-heavy` (task legs)

## Where to look first

1. **GitHub** — Workflow run for `build-and-test` / handoff; commit status and Check Run for the BMT context.
2. **Workflows execution** — Failed plan, task, or coordinator stage; task index and profile (standard vs heavy).
3. **GCS** — Plan file present; per-leg summaries present; snapshots under `projects/<project>/results/<bmt_slug>/snapshots/<run_id>/`.
4. **Ephemeral `triggers/`** — Should be cleaned up after a successful coordinator; orphaned objects may indicate a failed or partial run.

## Common symptoms

| Symptom | Likely checks |
| ------- | ------------- |
| Stuck **pending** status | Coordinator never ran; GitHub API finalize failed; see [bmt-architecture-deep-dive.md](bmt-architecture-deep-dive.md) §11.3 |
| Gate shows fail but bucket looks pass (or reverse) | Split-brain between GitHub and GCS; compare `ci_verdict.json` vs Check Run |
| Missing leg summary | Task crash before write; eventual consistency delay; see remediation doc §B.2 |

## Secrets and access

- **CI → GCP:** Workload Identity Federation; no long-lived keys in Actions.
- **Runtime → GitHub:** GitHub App installation tokens from **Secret Manager** (see [configuration.md](configuration.md)).

Do **not** paste tokens, private keys, or bucket URLs with embedded credentials into public issues. Use [SECURITY.md](../SECURITY.md) for vulnerability reports.

## Related docs

- [configuration.md](configuration.md) — Env vars, Pulumi, branch protection
- [bmt-architecture-deep-dive.md](bmt-architecture-deep-dive.md) — Design risks and operational notes
- [plans/bmt-weak-points-remediation.md](plans/bmt-weak-points-remediation.md) — Known code-level backlog
