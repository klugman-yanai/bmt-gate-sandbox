# BMT weak points — remediation backlog

This document tracks **design-level** and **implementation-level** issues called out in [bmt-architecture-deep-dive.md](../bmt-architecture-deep-dive.md) (§10–11). For each item: **why it matters**, then **recommendations** to fix or harden.

**Related:** [bmt-architecture-deep-dive.md §15](../bmt-architecture-deep-dive.md#15-prioritized-remediation-roadmap) (summary table). Implementation work should be done in focused PRs, not as a single batch unless scoped.

---

## Part A — Design-level

### A.1 GCS as coordination plane

**Why it matters:** There are no ACID transactions. Races, partial writes, and eventual visibility can undermine trust in the merge gate if workflow barriers or cleanup order are wrong.

**Recommendations:**

- Document **invariants** (who writes what, in what order; coordinator after all tasks).
- Optional: **generation counters** or TTL on ephemeral `triggers/` objects; align with [docs/runbook.md](../runbook.md) incident flow.
- Keep workflow YAML as the **barrier** between plan → tasks → coordinator.

### A.2 Contract fragility (paths and JSON)

**Why it matters:** Plan, summary, and pointer shapes are a **public contract** between CI, Workflows, Cloud Run, and tools. Drift breaks multiple packages at once.

**Recommendations:**

- Centralize **artifact path builders** in one module used by CI, runtime, and tools where feasible; add **contract tests** for critical JSON shapes.
- Version or migrate bucket layout changes with a short migration note in ADRs.

### A.3 Operational surface (GCP + GitHub)

**Why it matters:** WIF, Workflows, Cloud Run jobs, Secret Manager, and GitHub App wiring multiply misconfiguration risk.

**Recommendations:**

- IaC review checklist; staged rollouts; narrow IAM; cross-link [docs/configuration.md](../configuration.md) and [docs/runbook.md](../runbook.md).

### A.4 Workflow concurrency (`cancel-in-progress`)

**Why it matters:** Cancelling an in-flight handoff can interrupt uploads or leave partial remote state.

**Recommendations:**

- Make handoff steps **idempotent** where possible, or document which steps are unsafe under cancel; consider concurrency policy changes if this bites production.

---

## Part B — Implementation-level

### B.1 Duplicate `results_path` / pointer collision

**Why it matters:** The coordinator updates `current.json` and prunes snapshots **per `results_path`**. Two legs sharing the same path can **overwrite** pointers and **prune** another leg’s data — **silent corruption**.

**Recommendations:**

- **P0:** Validate **unique `results_path`** per plan in `build_plan()` (fail fast), **or** namespace pointers by `bmt_id` under a shared prefix.

### B.2 Missing summary conflated with runner failure

**Why it matters:** `_load_summary_or_failure` in `gcp/image/runtime/entrypoint.py` maps `FileNotFoundError` to `reason_code="runner_failures"`, mixing **missing artifact** with **real runner failure** — wrong ops signals.

**Recommendations:**

- **P1:** Distinct `reason_code` (e.g. `summary_missing`, `incomplete_plan`) and metrics/alerts.

### B.3 GitHub outcome vs GCS divergence

**Why it matters:** `github_reporting.py` may swallow exceptions; GitHub checks can stay **stale** while GCS already has the true verdict — **split-brain** for reviewers.

**Recommendations:**

- **P1/P2:** Retries with backoff for finalize; structured logging; metrics on finalize failures; optional non-zero exit or reconciliation job.

### B.4 `object_exists` hides infra errors (CI)

**Why it matters:** In `.github/bmt/ci/gcs.py`, `object_exists` returns `False` on **any** exception — auth/quota/network look like “missing object” and wrong branches run.

**Recommendations:**

- **P1:** Return **False** only for not-found; raise or return **`GcsError`** for other failures so callers can distinguish.

### B.5 Workflows `start_execution` single HTTP attempt

**Why it matters:** One `POST` can fail on transient 5xx/429 — handoff fails without retry.

**Recommendations:**

- **P2:** Retry with backoff; design **idempotency** if the API can be invoked twice for the same logical run.

### B.6 CI ↔ `gcp.image` import coupling

**Why it matters:** `.github/bmt/ci/core.py` imports `gcp.image.config`; refactors there can break `uv run bmt` unexpectedly.

**Recommendations:**

- **P3:** Thin **stable facade** for constants/decisions used only by CI.

### B.7 Broad `except Exception`

**Why it matters:** Collapses error types; hides validation failures in `ci/github.py`, `ci/config.py`, etc.

**Recommendations:**

- **P3:** Narrow exceptions; structured error types where helpful.

### B.8 Large orchestration modules / test gaps

**Why it matters:** `entrypoint.py`, CI handoff concentrate failure modes; rare branches may lack tests.

**Recommendations:**

- **P3:** Targeted tests for B.1–B.4 paths; optional split of orchestration modules when touching them.

---

## Priority snapshot

| Priority | Themes |
| -------- | ------ |
| P0 | Unique `results_path` (B.1) |
| P1 | Summary reason codes (B.2), `object_exists` (B.4), GitHub finalize visibility (B.3) |
| P2 | Workflows retry (B.5), path centralization (A.2) |
| P3 | CI facade (B.6), broad except (B.7), tests (B.8), ops docs (A.3–A.4) |
