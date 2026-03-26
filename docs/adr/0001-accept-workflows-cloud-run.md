# ADR 0001: Google Workflows + Cloud Run for BMT

## Status

Accepted

## Context

BMT (batch model testing) must run as a **merge gate** with **horizontal scaling** (multiple legs), **async** GitHub Actions (CI does not block for the full audio workload), and **clear** separation between planning, execution, and aggregation.

Alternatives included a long-lived VM polling triggers, or running all work inside a single Actions job (timeout and resource limits).

## Decision

Use **Google Cloud Workflows** to orchestrate:

1. **Plan** — `bmt-control` in plan mode writes `triggers/plans/<workflow_run_id>.json`
2. **Tasks** — `bmt-task-standard` / `bmt-task-heavy` run one leg per task
3. **Coordinator** — `bmt-control` in coordinator mode updates `current.json`, prunes snapshots, finalizes GitHub

GitHub Actions **starts** the workflow via WIF and the Workflow Executions API, then **exits**.

## Consequences

- **Positive:** Parallel legs, bounded Actions time, frozen plan artifact for auditability
- **Negative:** Operational surface (Workflows + multiple job definitions + IAM); correctness relies on GCS object conventions and workflow barriers

## References

- [docs/architecture.md](../architecture.md)
- [docs/pipeline-dag.md](../pipeline-dag.md)
