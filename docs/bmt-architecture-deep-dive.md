# BMT system architecture — deep dive

This document consolidates a structured review of **bmt-gcloud**: the asynchronous BMT (batch model testing) pipeline, its storage and coordination model, architectural strengths, and **non-trivial weak points** in code and operations (separate from documentation drift). It is intended for maintainers designing changes, debugging cross-service failures, or hardening the system.

**Companion docs:** [architecture.md](architecture.md) (canonical short reference), [pipeline-dag.md](pipeline-dag.md) (diagrams and glossary), [configuration.md](configuration.md) (env and secrets).

---

## 1. Purpose and scope

**BMT** is an automated quality gate for audio-related models: a **runner** processes a fixed dataset; scores (e.g. NAMUH counters) are compared to a **baseline** from the last successful run. A PR or protected branch cannot merge until the gate passes.

**Scope of this document:**

- How GitHub, Google Cloud Workflows, Cloud Run, GCS, and the GitHub API interact.
- Where “truth” lives at each stage and how it can diverge.
- Risks that are **intrinsic** to an object-store-backed async pipeline, plus **repo-specific** issues called out in code review.

**Out of scope:** Step-by-step local setup (see [development.md](development.md)); Pulumi and repo var names (see [configuration.md](configuration.md)).

---

## 2. Executive summary

The production path is **GitHub Actions → Workload Identity Federation → Google Cloud Workflows → Cloud Run Jobs** (`plan` → parallel `task` jobs → `coordinator`). **GCS** holds frozen plans, per-leg summaries, snapshots, and the **`current.json` pointer**. **GitHub** receives commit status, Check Runs, and optional PR-facing signals.

The design **trades** a single long-lived worker for **horizontal parallelism**, **clear stage boundaries**, and **CI that exits quickly**. The cost is **strong reliance on object naming and ordering**, **at-least-once semantics**, and **multiple code paths** that must stay consistent. Several **implementation gaps** (duplicate `results_path`, swallowed errors, ambiguous missing-summary handling) can produce **silent wrong behavior** or **misleading telemetry** if not addressed.

---

## 3. Actors and responsibilities

| Actor | Role |
| ----- | ---- |
| **GitHub Actions** | Build, test, upload runner artifacts, validate config, **start** a Workflows execution, **exit** without waiting for BMT completion. |
| **Google Cloud Workflows** | Orchestrates **plan** job, **N task** jobs (standard/heavy profiles), then **coordinator**; encodes barriers between stages. |
| **Cloud Run Jobs** | Run the packaged runtime (`gcp/image/bmt`): plan mode, task mode (one leg per index), coordinator mode, dataset-import, etc. |
| **GCS** | Shared **artifact store** and **coordination plane**: plans, progress, summaries, reporting metadata, snapshots, pointers, log dumps. |
| **GitHub API** | Commit status, Check Runs, optional comments; authenticated via **GitHub App** installation tokens from the runtime. |

---

## 4. End-to-end pipeline

### 4.1 Sequence (canonical)

The high-level sequence matches [architecture.md](architecture.md):

1. Actions authenticates to GCP (OIDC / WIF), then calls the **Workflow Executions API** to start the named workflow with a JSON **argument** (correlation id, repo metadata, etc.).
2. **Plan** job: reads enabled BMT manifests under the stage layout, partitions legs (e.g. standard vs heavy), writes **`triggers/plans/<workflow_run_id>.json`**, and may create **in-progress** Check Run metadata under **`triggers/reporting/`**.
3. **Task** jobs: each job reads the frozen plan, selects **one leg** via `CLOUD_RUN_TASK_INDEX`, runs the plugin and runner, **evaluates** against baseline (using prior **`current.json`** / snapshots), writes **snapshots** and **leg summaries** under **`triggers/summaries/`**, updates progress, and calls **`publish_progress`** for the Check Run.
4. **Coordinator** job: loads **all** leg summaries, updates **`current.json`** per results root, **prunes** snapshots not retained by the pointer, **finalizes** GitHub (status / Check Run / optional PR comment), **deletes** ephemeral `triggers/` objects for the run.

Detailed diagrams and step tables: [pipeline-dag.md](pipeline-dag.md).

### 4.2 Handoff from Actions

The **`bmt-handoff.yml`** workflow (callable / dispatch) performs prerequisite checks, runner publish/skip logic, and **Workflows API** dispatch. **CI terminates** after a successful start (or posts failure to GitHub on dispatch error). See §7 for **concurrency** (`cancel-in-progress`) and §11.4 for **single-shot HTTP** behavior.

### 4.3 Gating semantics

**Baseline comparison and per-leg pass/fail** are intended to occur in the **task** (plugin `evaluate`). The **coordinator** merges **leg outcomes** into new pointer values and **does not re-score**. If task and coordinator disagree on what “done” means (e.g. missing summary treated as failure — §11.1), GitHub and GCS can reflect different stories.

---

## 5. Runtime contract (`gcp/image/bmt`)

The active runtime lives under [`gcp/image/bmt`](../gcp/image/bmt) (see [architecture.md](architecture.md)).

| Mode | Responsibility |
| ---- | ---------------- |
| **plan** | Discover enabled manifests, build **`ExecutionPlan`**, write plan JSON to GCS, seed reporting metadata. |
| **task** | Execute **exactly one** leg per invocation (task index + profile); write snapshot + summary. |
| **coordinator** | Load summaries; update **`current.json`**; prune snapshots; **finalize** GitHub; **cleanup** ephemeral triggers. |
| **dataset-import** | Expand uploaded archives into `projects/<project>/inputs/<dataset>/`. |

The old **VM watcher / root orchestrator / per-project `bmt_manager`** stack is **not** the supported path; contributor-facing docs in some files may still mention it — see §13.

---

## 6. Storage model

- **Bucket root** mirrors [`gcp/stage`](../gcp/stage) (see [architecture.md](architecture.md)).
- **Immutable** plugin bundles: `projects/<project>/plugins/<plugin>/sha256-<digest>/...`
- **Datasets:** `projects/<project>/inputs/<dataset>/...`
- **Results:** `projects/<project>/results/<bmt_slug>/` with **`current.json`** and **`snapshots/<run_id>/`**

**Ephemeral** (typically deleted after successful coordinator): `triggers/plans/`, `triggers/progress/`, `triggers/summaries/`, `triggers/reporting/`, etc.

**Canonical artifact list** (short form): [architecture.md](architecture.md#storage-model). **Cross-writer table:** [pipeline-dag.md](pipeline-dag.md#cross-diagram-data-flow).

---

## 7. Coordination model and distributed-systems properties

GCS is **not** a transactional database. The system relies on:

- **Immutable workflow run id** (and per-leg `run_id` in the plan) as **correlation id**.
- **Object keys** that encode intent (`triggers/plans/{id}.json`, summaries keyed by project and slug).
- **Workflow barriers** between plan → tasks → coordinator (correctness depends on the workflow not starting the coordinator until tasks complete or fail).

**Implications:**

- **At-least-once** delivery and **retries** must be assumed; writers should be **idempotent** where possible (e.g. check-run metadata, pointer updates with clear semantics).
- **Listing** or “latest” without a **generation** or **single writer** discipline is unsafe under concurrency (mitigated here by **one coordinator** per run id after tasks).
- **Partial failure** (one task never writes its summary) must be visible as **incomplete**, not silently folded into another **reason code** — see §11.1.

---

## 8. Architectural strengths

1. **Async handoff:** Actions does not block on long audio jobs; wall-clock and **Actions billing** stay bounded relative to full BMT duration.
2. **Explicit staging:** Plan → parallel tasks → coordinator yields clear ownership and audit artifacts (frozen plan, per-leg summaries).
3. **Horizontal scaling:** One task per leg, with **standard** vs **heavy** job profiles, avoids a single bottleneck process.
4. **Auditable inputs:** The plan file answers “what was scheduled for this workflow run?”
5. **Separation of packages:** `.github/bmt/ci/` (CI CLI and handoff), `gcp/image/runtime/` (orchestration), `tools/` (local dev) map to different deployment surfaces.
6. **Security direction:** WIF from Actions to GCP; GitHub App + short-lived tokens at runtime — **when fully wired**, avoids long-lived keys in CI.

---

## 9. Ports and adapters (hexagonal view)

This is a **conceptual** map, not a literal package layout.

| Layer | Contents |
| ----- | -------- |
| **Domain core** | Leg evaluation: load inputs, run runner/plugin, parse scores, compare to baseline, produce **leg verdict** and snapshot payloads. |
| **Inbound ports** | Workflow/task invocation (env: `BMT_WORKFLOW_RUN_ID`, `CLOUD_RUN_TASK_INDEX`, profile), frozen **plan** JSON, BMT manifests. |
| **Outbound ports** | **Object store** (read/write plans, summaries, snapshots, pointers), **GitHub** (checks, status), **secrets** (App key via Secret Manager), **logging/metrics**. |
| **Adapters** | `gcs` helpers in CI; runtime artifact writers/readers; `github_reporting` / PyGithub wrappers; Workflows API client. |

**Leakage risk:** Path strings and JSON field names duplicated across CI, runtime, and tools weaken the “port” boundary; central **contract** modules and tests reduce drift.

---

## 10. Weak points — design-level (non-documentation)

### 10.1 GCS as coordination plane

- No **ACID** transactions; **race** and **partial write** scenarios depend on workflow ordering and cleanup logic.
- **Cost and complexity:** Many objects and lifecycle rules; ephemeral paths must be **deleted** or TTL’d to avoid clutter and mistaken reads.

### 10.2 Contract fragility

- Changes to **plan**, **summary**, or **pointer** shapes require coordinated updates across **Workflows**, Cloud Run images, and possibly **CI** validators.
- **Duplication** of trigger/path logic between `.github/bmt/ci/`, `gcp/image/runtime/artifacts.py`, and `tools/shared/trigger_uris.py` (parity often **asserted in comments**, not enforced by a single module) increases **drift risk**.

### 10.3 Operational surface area

- **WIF**, **Workflows**, multiple **Cloud Run** job definitions, **Secret Manager**, bucket IAM, and GitHub App configuration must stay aligned; misconfiguration has a **large blast radius**.

### 10.4 Workflow concurrency

- `bmt-handoff.yml` may use **`concurrency`** with **`cancel-in-progress`**. A newer run can **cancel** an in-flight handoff, risking **partial uploads** or **overlapping** remote state unless every step is safe to interrupt or **idempotent**.

---

## 11. Weak points — implementation-level (code and behavior)

### 11.1 Duplicate `results_path` / pointer collision

**`build_plan()`** (`gcp/image/runtime/planning.py`) appends one **`PlanLeg` per enabled manifest** but does **not** enforce uniqueness of **`results_path`** across legs.

The **coordinator** (`run_coordinator_mode` in `gcp/image/runtime/entrypoint.py`) loops each leg and, for each:

- Resolves **`results_root = stage_root / leg.results_path`**
- Reads/writes **`current.json`** and **prunes snapshots** under that root

If two enabled BMTs share the same **`results_path`**, later legs **overwrite** the pointer and **prune** snapshots needed by earlier legs — **silent data loss** or **wrong baselines**.

**Mitigation direction:** Validate at **plan** time (fail fast) or namespace pointers by **`bmt_id`** under a shared prefix.

### 11.2 Missing summary conflated with runner failure

`_load_summary_or_failure` catches **`FileNotFoundError`** and returns a synthetic **`LegSummary`** with **`reason_code="summary_missing"`** and **`status=FAIL`**.

That conflates:

- **Artifact never written** (task crash, path bug, workflow ordering, eventual consistency lag)
- **Actual runner/plugin failure** after a summary would have been written differently

**Mitigation direction:** Distinct **`reason_code`** (e.g. `summary_missing`, `incomplete_plan`) and alerting hooks.

### 11.3 GitHub outcome can diverge from GCS

**`gcp/image/runtime/github_reporting.py`** catches `GithubException` (not broad `Exception`) but
without retry — a single transient GitHub API error on `finalize_check_run` silently logs a warning
and moves on. **GCS** will already reflect the true BMT outcome while **GitHub Checks** may remain
stale.

**Mitigation direction:** Structured retries with backoff, **non-zero exit** or explicit **reconciliation** when finalization fails, **metrics** on finalize failures.

### 11.4 `object_exists` swallows infrastructure errors — RESOLVED

**Status: Fixed.** The implementation in **`.github/bmt/ci/gcs.py`** now raises `GcsError` for
all non-404 failures, not `False`. Callers see `GcsError` on auth failure, quota, or network
error — distinct from `False` for a legitimate missing object.

Current implementation (`gcs.py:107–122`):

```python
def object_exists(uri: str) -> bool:
    “””Return True if the GCS object exists.

    Raises :exc:`ValueError` for invalid ``gs://`` URIs. Propagates :exc:`GcsError` on
    GCS/network/auth failures so callers do not treat infrastructure errors as “missing”.
    “””
    try:
        bucket_name, path = parse_gs_uri(uri)
        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        return blob.exists()
    except ValueError:
        raise
    except Exception as exc:
        raise GcsError(f”Failed to check existence of {uri}: {exc}”) from exc
```

### 11.5 Workflows dispatch: single HTTP attempt

**`start_execution`** in **`.github/bmt/ci/workflows_api.py`** performs a **single** `POST` with a fixed timeout. Transient **5xx/429** can fail the handoff. Retries require **care** (idempotency, duplicate execution ids) if added.

### 11.6 CI ↔ `gcp.image` import coupling

**`.github/bmt/ci/core.py`** (and related modules) import **`gcp.image.config`** and related symbols. Refactors under **`gcp/image/config`** can break **`uv run bmt`** without a **stable, narrow** interface.

### 11.7 Broad exception handling elsewhere

Patterns such as **`except Exception`** in **`ci/github.py`**, **`download_json`** / **`load_context_from_file`** in **`ci/config.py`**, and runtime reporting **collapse** error types and can **hide** validation failures.

### 11.8 Large orchestration modules

**`gcp/image/runtime/entrypoint.py`** centralizes multiple modes; CI **handoff** aggregates many steps. This **concentrates** failure modes and can make **unit test coverage** uneven for rare branches.

---

## 12. Security and credentials

| Concern | Practice |
| ------- | -------- |
| **Actions → GCP** | OIDC + **Workload Identity Federation**; avoid long-lived GCP JSON keys in GitHub. |
| **Least privilege** | Separate IAM for “upload from CI” vs “runtime worker” where feasible; scope **attribute conditions** on repo/ref. |
| **GitHub App** | Private key in **Secret Manager**; runtime mints **short-lived installation tokens**. |
| **Secrets in logs** | Ensure tokens and signed URLs never land in **INFO** logs at full length. |

See [configuration.md](configuration.md) for variable and secret names.

---

## 13. Documentation alignment

Canonical runtime description: [architecture.md](architecture.md) (Workflows + Cloud Run; VM stack removed).

**AGENTS.md**, **CLAUDE.md**, and the **docs hub** are maintained to match **Workflows + Cloud Run** (see [architecture.md](architecture.md)). If you find leftover VM-era wording in any file, treat it as a bug and fix or remove it (except historical notes under `docs/archive/`).

---

## 14. Observability and operations

Recommended practices (industry-standard for this architecture):

- **Structured logs** with `workflow_run_id`, repo, commit, leg identifiers on every line.
- **Metrics:** time from plan write to **terminal** GitHub check; counts of **missing summaries**, **finalize failures**, **GcsError** by type.
- **Reconciliation / watchdog:** optional job to find **stuck** pending checks or **orphan** triggers beyond a TTL.
- **Alerting** on auth failures to GitHub API, GCS permission errors, and rising **synthetic** `summary_missing` reason codes from §11.2 (previously `runner_failures` before 2026-04-13 rename).

---

## 15. Prioritized remediation roadmap

The **full backlog** (why + recommendations per issue) lives in **[plans/bmt-weak-points-remediation.md](plans/bmt-weak-points-remediation.md)**. The table below is a short index only.

| Priority | Item | Rationale |
| -------- | ---- | --------- |
| P0 | Enforce **unique `results_path`** per plan (or namespace pointers) | Prevents silent cross-leg corruption. |
| P1 | **Distinct reason codes** for missing summary vs runner failure | Correct operations and debugging. |
| ~~P1~~ | ~~**Fix `object_exists`**~~ — **RESOLVED** | Fixed: raises `GcsError` for non-404; see §11.4. |
| P2 | **Retry/backoff** for Workflows start + GitHub finalize with clear idempotency rules | Reduces flaky handoff and split-brain. |
| P2 | **Centralize** path/URI builders and critical JSON schemas | Reduces contract drift. |
| P3 | Introduce a **thin stable API** between CI package and `gcp.image` config | Safer refactors. |

---

## 16. References

| Document | Use |
| -------- | --- |
| [architecture.md](architecture.md) | Short canonical pipeline and paths |
| [pipeline-dag.md](pipeline-dag.md) | Diagrams, glossary, handoff steps |
| [configuration.md](configuration.md) | Env, Pulumi, branch protection |
| [development.md](development.md) | Local and Cloud Run testing |
| [adding-a-project.md](adding-a-project.md) | New projects and BMTs |

---

*Generated as a maintainer-facing architecture review; update this file when the production pipeline or critical contracts change.*
