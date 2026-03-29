# BMT weak points — remediation backlog

Expands the short index at [architecture.md § Maintainer: risks & weak points](architecture.md#maintainer-risks-weak-points). For each item: **why it matters**, then **recommendations**.

Implementation work should land in focused PRs. The [priority table](#priority-snapshot) at the bottom is the triage view.

> **Compounding risk note:** The normal plan path now rejects duplicate `results_path` values before execution, which short-circuits the old B.1 + B.3 + A.4 corruption chain. The remaining risk is coordinator/GitHub split-brain plus overlapping executions when plan-time guards are bypassed or a stale plan is injected.

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

- Shared **artifact path builders** and versioned models now live in `contracts/src/bmtcontract`; keep CI/runtime/tools on those re-exports and extend **contract tests** when new control-plane files are added.
- Version or migrate bucket layout changes with a short note in [architecture.md — ADR summaries](architecture.md#adr-summaries).

### A.3 Operational surface (GCP + GitHub)

**Why it matters:** WIF, Workflows, Cloud Run jobs, Secret Manager, and GitHub App wiring multiply misconfiguration risk.

**Recommendations:**

- IaC review checklist; staged rollouts; narrow IAM; cross-link [configuration.md](configuration.md) and [runbook.md](runbook.md).

### A.4 Workflow concurrency and supersession guard

**Why it matters:** `cancel-in-progress` can interrupt uploads or leave partial remote state. The supersession guard (`triggers/reporting/pr-active/{pr}.json`) is still managed by the bmtgate dispatch layer, which now also records `triggers/dispatch/{wid}.json` before remote start. The coordinator acquires per-`results_path` leases under `triggers/leases/` and records `triggers/finalization/{wid}.json` before promotion. The residual risk is no longer silent double-promotion; it is overlapping remote executions when cancel exhausts and strict mode is left off, stale dispatch intent, orphaned lease artifacts after abnormal exits, or operators ignoring a failed reconciliation record.

**Recommendations:**

- Keep `BMT_DISPATCH_REQUIRE_CANCEL_OK=false` as the default and document the tradeoff: non-strict mode favors forward progress, while `true` is the safety-first switch that aborts a new dispatch when supersede cancel still fails after retries. Keep `BMT_ALLOW_UNSAFE_SUPERSEDE` only as a legacy inverse compatibility flag.
- Use `uv run bmt ops doctor --workflow-run-id <wid>` or `--scan-stale --older-than-hours <N>` as the repo-owned reconciliation surface for stale `triggers/dispatch/`, `triggers/finalization/`, `triggers/leases/`, and preserved reporting metadata.
- Optional follow-up: promote those signals into external alerting if operators need push-based notification instead of pull-based inspection.

### A.5 Coordinator completeness signaling exists, but alerting is still thin

**Why it matters:** The coordinator now compares the expected leg list from `triggers/plans/{wid}.json` against the summaries present under `triggers/summaries/{wid}/`, logs the diff, and persists completeness fields on `triggers/finalization/{wid}.json`. That closes the old ambiguity, but operators still need better alerting around `needs_reconciliation=true` and repeated incomplete-plan cases (see also B.2).

**Recommendations:**

- Treat `FinalizationRecordV2.needs_reconciliation` plus the completeness counts as the canonical operator signal for missing-summary cases.
- Optional: add external metrics/alerts for repeated `incomplete_plan` finalizations if the structured logs + `bmt ops doctor` surface is not enough operationally.

---

## Part B — Implementation-level

### B.1 Duplicate `results_path` / pointer collision (guarded in normal plan flow)

**Why it matters:** The coordinator updates `current.json` and prunes snapshots **per `results_path`**. Two legs sharing the same path can **overwrite** pointers and **prune** another leg's data — **silent corruption**. The normal `build_plan()` path now rejects duplicate paths before execution; the residual risk is limited to injected/stale plans or future regressions around that guard.

**Recommendations:**

- Keep the plan-time **unique `results_path`** guard covered by tests.
- Optional: add coordinator-side assertion/validation as defense in depth if externally supplied plan files remain a concern.

### B.2 Missing summary is explicit, but operator alerts are still thin

**Why it matters:** Coordinator and failure-publish paths now require explicit missing-summary handling and persist expected/present leg counts plus missing/extra leg keys on the finalization record. The core gate/finalization flow no longer reports those cases as generic runner failures. The remaining gap is observability and consistency outside those call sites.

**Recommendations:**

- **P1:** Add metrics/alerts so missing-summary cases are visible operationally without requiring a human to poll logs or `bmt ops doctor`.
- Optional: continue auditing any future summary loaders so ambiguous defaults do not creep back in.

### B.3 GitHub outcome vs GCS divergence

**Why it matters:** The coordinator now records explicit finalization state and runs a preflight before pointer writes, but the durable side-effect order is still **preflight → pointer promotion → GitHub finalize**. GitHub API failures therefore leave a `failed_github_publish` finalization record that is explicit and recoverable, but `current.json` may already have advanced before GitHub catches up.

**Recommendations:**

- Keep retries/backoff plus structured logging, including the per-attempt `finalize_ok` / `commit_ok` terminal publish events.
- Use `uv run bmt ops doctor --workflow-run-id <wid>` as the first reconciliation step for `failed_github_publish` records and preserved `triggers/reporting/{wid}.json`.
- Optional: add external alerting around `failed_github_publish` records so operators can see that GitHub is lagging durable result promotion without manual inspection.

### B.4 `object_exists` and infra errors (CI)

**Why it matters:** `ci/src/bmtgate/clients/gcs.py` — `object_exists` raises `GcsError` on non–not-found failures (auth/quota/network errors are not treated as "missing"). A quota spike or transient auth failure silently becomes a wrong "object absent" signal.

**Residual:** Audit other GCS helpers for the same anti-pattern if any remain.

### B.5 Workflows dispatch is retried and receipt-based, but not fully transactional

**Why it matters:** The Workflows client now retries `start_execution` only for explicit HTTP `429`, `503`, and other `5xx` responses, while supersede cancel retries happen in the dispatch layer with the same `1s` / `3s` cadence. Handoff records `triggers/dispatch/{wid}.json` so matching reruns can reuse an existing started execution instead of blindly issuing a second remote start. The residual risk is a crash after the remote execution begins but before the receipt is updated; that would still need reconciliation.

**Recommendations:**

- Keep the dispatch receipt contract and use `bmt ops doctor --scan-stale` to detect old `pending_start` / `start_failed` receipts.
- Optional: add deeper remote reconciliation if the residual post-start / pre-receipt-update crash window becomes operationally significant.

### B.6 CI ↔ runtime contract drift

**Why it matters:** `kardome-bmt-gate`, `backend`, and tooling now share `bmtcontract`, but drift can still reappear if new control-plane constants or path rules are added outside that package.

**Recommendations:**

- **P3:** Keep expanding **contract tests** and keep wrappers thin; new control-plane primitives should be added in `bmtcontract` first, not redefined locally.

### B.7 Broad `except Exception`

**Why it matters:** Broad catches collapse error types and hide validation failures. The highest-risk pipeline adapters now catch narrower SDK/transport/validation failures, but the wider repo still has older broad handlers outside that first pass.

**Recommendations:**

- Keep the repo policy tests that block new broad catches in the selected pipeline adapters/tooling.
- Continue the wider repo audit opportunistically instead of letting broad catches spread back into the control plane.

### B.8 Large orchestration modules / test gaps

**Why it matters:** `entrypoint.py` and the CI handoff concentrate failure modes; rare branches (B.1–B.4 paths) may lack tests.

**Recommendations:**

- **P3:** Targeted tests for B.1–B.5 paths; optional split of orchestration modules when touching them.

### B.9 `log-dumps/` unbounded growth

**Why it matters:** The coordinator writes `log-dumps/{wid}.txt` on failed runs. Repo-owned retention now deletes dumps older than 30 days and caps the prefix at the newest 200 files, which removes the unbounded-growth failure mode. Residual risk is limited to cleanup warnings or environments that want bucket-native lifecycle rules on top.

**Recommendations:**

- Keep the coordinator-side retention in place and warn only on cleanup failures so reporting is never blocked by housekeeping.
- Optional: add a bucket lifecycle rule if operators want defense in depth outside the runtime process.

---

## Priority snapshot

| Priority | Items |
| -------- | ----- |
| **P1** | External alerting for `needs_reconciliation` / `incomplete_plan` — A.5 · Missing-summary observability — B.2 · Failed GitHub publish reconciliation / alerting — B.3 |
| **P2** | Dispatch receipt / lease / finalization operational cleanup — A.4 · Residual dispatch crash-window hardening — B.5 |
| **P3** | CI/runtime contract drift guardrails — B.6 · Wider broad-exception audit — B.7 · Test coverage / structural extraction follow-up — B.8 · Ops docs / IAM hygiene — A.3 |
