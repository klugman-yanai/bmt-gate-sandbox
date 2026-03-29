# BMT weak points — remediation backlog

Expands the short index at [architecture.md § Maintainer: risks & weak points](architecture.md#maintainer-risks-weak-points). For each item: **why it matters**, then **recommendations**.

Implementation work should land in focused PRs. The [priority table](#priority-snapshot) at the bottom is the triage view.

> **Compounding risk note:** B.1 + B.3 + A.4 can chain silently — a shared `results_path` causes the coordinator to write a corrupted `current.json`, GitHub is updated with that corrupted state, and there is no automated way to detect or recover it. Fix B.1 first; it short-circuits the chain.

---

## Part A — Design-level

### A.1 GCS as coordination plane

**Why it matters:** There are no ACID transactions. Races, partial writes, and eventual visibility can undermine trust in the merge gate if workflow barriers or cleanup order are wrong.

**Recommendations:**

- Invariants are now documented in [diagrams/gcs-storage.md](diagrams/gcs-storage.md) (who writes what, in what order).
- Optional: **generation counters** or TTL on ephemeral `triggers/` objects; align with [runbook.md](runbook.md) incident flow.
- Keep workflow YAML as the **barrier** between plan → tasks → coordinator (see also A.5).

### A.2 Contract fragility (paths and JSON)

**Why it matters:** Plan, summary, and pointer shapes are a **public contract** between CI, Workflows, Cloud Run, and tools. Drift breaks multiple packages at once.

**Recommendations:**

- Centralize **artifact path builders** in one module used by CI, runtime, and tools where feasible; add **contract tests** for critical JSON shapes.
- Version or migrate bucket layout changes with a short note in [architecture.md — ADR summaries](architecture.md#adr-summaries).

### A.3 Operational surface (GCP + GitHub)

**Why it matters:** WIF, Workflows, Cloud Run jobs, Secret Manager, and GitHub App wiring multiply misconfiguration risk.

**Recommendations:**

- IaC review checklist; staged rollouts; narrow IAM; cross-link [configuration.md](configuration.md) and [runbook.md](runbook.md).

### A.4 Workflow concurrency and supersession guard

**Why it matters:** `cancel-in-progress` can interrupt uploads or leave partial remote state. The supersession guard (`triggers/reporting/pr-active/{pr}.json`) is managed solely by the bmtgate dispatch layer — if two Workflows executions both reach coordinator stage (e.g., a Workflows retry or a late cancel), both will write `current.json` with no conflict detection. Last writer silently corrupts `last_passing`.

**Recommendations:**

- Make handoff steps **idempotent** where possible, or document which steps are unsafe under cancel.
- Consider a coordinator-side check: read and verify the `pr-active` key before writing `current.json`, or add a generation-condition write.

### A.5 No application-level coordinator completeness check

**Why it matters:** The coordinator merges leg results from `triggers/summaries/{wid}/`. Its only guarantee that all legs have written their summaries comes from Google Workflows step ordering. The coordinator itself has no application-level guard — it runs on whatever summaries are present and treats absent legs as failure (`reason_code="runner_failures"`). A task crash, a Workflows partial retry, or a leg that was never scheduled produces a silent missing-vs-failure conflation at the result level, not just the reason-code level (see also B.2).

**Recommendations:**

- **P1:** On coordinator startup, compare the leg list in the plan (`triggers/plans/{wid}.json`) against the set of present summaries. If the sets differ, emit a structured warning with the missing leg IDs before finalizing. Treat this as `incomplete_plan`, not `runner_failures`.

---

## Part B — Implementation-level

### B.1 Duplicate `results_path` / pointer collision

**Why it matters:** The coordinator updates `current.json` and prunes snapshots **per `results_path`**. Two legs sharing the same path can **overwrite** pointers and **prune** another leg's data — **silent corruption**. This is the highest-priority item because it can corrupt the baseline used by all future runs.

**Recommendations:**

- **P0:** Validate **unique `results_path`** per plan in `build_plan()` (fail fast), **or** namespace pointers by `bmt_id` under a shared prefix.

### B.2 Missing summary conflated with runner failure

**Why it matters:** `_load_summary_or_failure` in `backend/src/backend/runtime/entrypoint.py` maps `FileNotFoundError` to `reason_code="runner_failures"`, mixing **missing artifact** with **real runner failure** — wrong ops signals. See also A.5 for the structural gap this exposes.

**Recommendations:**

- **P1:** Distinct `reason_code` (e.g. `summary_missing`, `incomplete_plan`) and metrics/alerts.

### B.3 GitHub outcome vs GCS divergence

**Why it matters:** The coordinator writes `current.json` to GCS first, then calls the GitHub API to finalize the check run. These are two separate side effects with no rollback. `github_reporting.py` may swallow exceptions; GitHub checks can stay **stale** while GCS already has the true verdict — **split-brain** for reviewers. A PR can be blocked by a phantom failure with no automated recovery path.

**Recommendations:**

- **P1/P2:** Retries with backoff for finalize; structured logging; metrics on finalize failures; optional non-zero exit or reconciliation job.

### B.4 `object_exists` and infra errors (CI)

**Why it matters:** `ci/src/bmtgate/clients/gcs.py` — `object_exists` raises `GcsError` on non–not-found failures (auth/quota/network errors are not treated as "missing"). A quota spike or transient auth failure silently becomes a wrong "object absent" signal.

**Residual:** Audit other GCS helpers for the same anti-pattern if any remain.

### B.5 Workflows `start_execution` single HTTP attempt

**Why it matters:** One `POST` can fail on transient 5xx/429 — handoff fails without retry and the entire pipeline is aborted.

**Recommendations:**

- **P2:** Retry with backoff; design **idempotency** if the API can be invoked twice for the same logical run.

### B.6 CI ↔ runtime contract drift

**Why it matters:** `kardome-bmt-gate` and `kardome-bmt-runtime` (`backend/`) are separate packages; duplicated constants or path logic can drift silently.

**Recommendations:**

- **P3:** Shared **contract tests** and, where justified, a thin shared constants module or generated parity checks.

### B.7 Broad `except Exception`

**Why it matters:** Collapses error types; hides validation failures in `ci/src/bmtgate/clients/github.py`, `ci/src/bmtgate/config/settings.py`, etc.

**Recommendations:**

- **P3:** Narrow exceptions; structured error types where helpful.

### B.8 Large orchestration modules / test gaps

**Why it matters:** `entrypoint.py` and the CI handoff concentrate failure modes; rare branches (B.1–B.4 paths) may lack tests.

**Recommendations:**

- **P3:** Targeted tests for B.1–B.5 paths; optional split of orchestration modules when touching them.

### B.9 `log-dumps/` unbounded growth

**Why it matters:** The coordinator writes `log-dumps/{wid}.txt` on every failed run and no cleanup mechanism exists. Unlike ephemeral `triggers/{wid}/` (deleted by coordinator), `log-dumps/` accumulates indefinitely. High-churn repos or repos with recurring flaky legs will grow this prefix without bound.

**Recommendations:**

- **P3:** GCS lifecycle rule on `log-dumps/` prefix (e.g., delete after 30 days), or coordinator-side cleanup of old dumps beyond a rolling count. The signed URL already has a 3-day expiry so the object outlives its usefulness quickly.

---

## Priority snapshot

| Priority | Items |
| -------- | ----- |
| **P0** | Unique `results_path` validation — B.1 |
| **P1** | Coordinator completeness check — A.5 · Summary reason codes — B.2 · `object_exists` error handling — B.4 · GitHub finalize split-brain — B.3 |
| **P2** | Workflows retry / idempotency — B.5 · Path centralization + contract tests — A.2 |
| **P3** | Supersession guard hardening — A.4 · CI/runtime contract drift — B.6 · Broad except — B.7 · Test coverage — B.8 · `log-dumps/` lifecycle — B.9 · Ops docs — A.3 |
