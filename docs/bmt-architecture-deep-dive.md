# BMT architecture — deep dive

Maintainer-oriented view: async pipeline, storage, strengths, and **known weak points** (design + implementation). For the short reference see [architecture.md](architecture.md); for diagrams see [pipeline-dag.md](pipeline-dag.md).

---

## 1. Scope

**In scope:** GitHub ↔ Workflows ↔ Cloud Run ↔ GCS ↔ GitHub API; where truth lives; failure and drift modes.

**Out of scope:** Day-to-day setup → [CONTRIBUTING.md](../CONTRIBUTING.md); env names → [configuration.md](configuration.md).

---

## 2. Executive summary

**Path:** GitHub Actions → WIF → Google Workflows → Cloud Run Jobs (`plan` → per-leg `task` jobs → `coordinator`). **GCS** holds plans, summaries, snapshots, **`current.json`**. **GitHub** gets status, Check Runs, optional PR signals.

**Tradeoff:** Fast CI exit and horizontal task scaling vs reliance on **object naming**, **ordering**, and **at-least-once** behavior. Contract drift or ambiguous failures can produce **silent wrong outcomes** if not guarded.

---

## 3. Actors

| Actor | Role |
| --- | --- |
| **GitHub Actions** | Build, upload runner, start Workflow execution, **exit** |
| **Google Workflows** | Barriers: plan → tasks → coordinator |
| **Cloud Run Jobs** | `backend/` runtime: plan / task / coordinator / dataset-import |
| **GCS** | Artifacts + coordination (`triggers/`, `projects/`) |
| **GitHub API** | Status / checks / comments (GitHub App token from runtime) |

---

## 4. Pipeline sequence

1. Actions calls **Workflow Executions API** with run metadata.
2. **Plan** writes `triggers/plans/<workflow_run_id>.json` and reporting metadata under `triggers/reporting/`.
3. **Task** jobs: each reads the plan, selects one leg (`CLOUD_RUN_TASK_INDEX`), runs plugin + runner, **evaluates** vs baseline, writes snapshot + `triggers/summaries/`, updates Check Run via `publish_progress`.
4. **Coordinator** loads summaries, updates `current.json`, prunes, finalizes GitHub, deletes ephemeral `triggers/*` for the run.

Handoff workflow: **`bmt-handoff.yml`** — prerequisite checks, runner publish, dispatch; **concurrency** `cancel-in-progress` can abort in-flight work (steps should be idempotent).

**Gating:** scoring / pass-fail in **task**; coordinator **merges** outcomes and pointers only.

---

## 5. Runtime and storage

- **Runtime source:** `backend/` (image).
- **Bucket mirror:** `benchmarks/` → GCS root (see [architecture.md](architecture.md#storage-model-gcs)).

**Modes:** `plan` | `task` | `coordinator` | `dataset-import`.

**Ephemeral:** `triggers/plans`, `progress`, `summaries`, `reporting` (cleaned after success).

---

## 6. Coordination (distributed-systems)

GCS is not transactional. Correctness assumes: stable **workflow_run_id**, deterministic **keys**, Workflow **ordering** (coordinator after tasks). Assume **retries**; writers should be **idempotent** where possible. **Partial failure** (missing summary) must not look like an ordinary runner failure — see §11.2.

---

## 7. Strengths

1. CI does not block on long audio work.
2. Frozen **plan** artifact answers “what was scheduled?”
3. One **task** per leg; **standard** / **heavy** **job definitions** separate CPU/memory needs.
4. **Separation:** `ci/src/bmtgate/` (handoff, clients), `backend/runtime/` (execution), `tools/` (local).
5. **Security direction:** WIF to GCP; GitHub App + short-lived tokens at runtime.

---

## 8. Weak points — design

| Area | Risk |
| --- | --- |
| **GCS as queue** | Races, partial writes, cleanup mistakes |
| **JSON contracts** | Plan / summary / pointer shape changes need coordinated rollout |
| **Ops surface** | WIF, Workflows, multiple jobs, IAM, App config |
| **Handoff concurrency** | New run cancels old — uploads/dispatch must tolerate interruption |

---

## 9. Weak points — implementation

### 9.1 Duplicate `results_path` / pointer collision

`build_plan()` in `backend/runtime/planning.py` does not enforce unique `results_path` per leg. `run_coordinator_mode` in `backend/runtime/entrypoint.py` writes `current.json` per leg’s `results_root` — **colliding paths** can overwrite pointers and prune the wrong snapshots.

**Mitigation:** Validate at plan time or namespace by `bmt_id`.

### 9.2 Missing summary vs runner failure

`_load_summary_or_failure` may map a missing file into a synthetic failure resembling **runner_failures**, conflating “never wrote summary” with “runner failed”.

**Mitigation:** Distinct reason codes (`summary_missing`, etc.) and metrics.

### 9.3 GitHub vs GCS divergence

`backend/runtime/github_reporting.py` — broad `except Exception` on GitHub calls can leave checks stale while GCS is already final.

**Mitigation:** Retries, structured errors, non-zero exit or reconciliation when finalize fails.

### 9.4 GCS “exists” checks (historical note)

Older CI code treated **all** GCS errors like “missing object”. Current `ci/src/bmtgate/clients/gcs.py` **`object_exists`** raises **`GcsError`** on infrastructure failures so callers do not confuse auth/quota with absence.

### 9.5 Single Workflows `POST`

`start_execution` in `ci/src/bmtgate/clients/workflows.py` uses **one** `POST` (60s timeout). Transient 5xx/429 can fail handoff; retries need idempotency design.

### 9.6 Contract drift across packages

Path and URI helpers appear in **CI**, **runtime**, and **tools**. **Tests and shared contract modules** are the main guard against drift (no single import bridge from `bmtgate` into `backend`).

### 9.7 Large modules

`backend/runtime/entrypoint.py` and handoff pipelines concentrate branches — keep **focused tests** for failure paths.

---

## 10. Security

| Concern | Practice |
| --- | --- |
| Actions → GCP | OIDC / WIF |
| Runtime → GitHub | App installation tokens; secrets in Secret Manager |
| Logs | No full tokens / signed URLs at INFO |

---

## 11. Remediation index

Full narrative: [plans/bmt-weak-points-remediation.md](plans/bmt-weak-points-remediation.md).

| Priority | Item |
| --- | --- |
| P0 | Unique `results_path` per plan (or namespaced pointers) |
| P1 | Distinct codes for missing summary vs runner failure |
| P1 | Harden GitHub finalize + observe failures |
| P2 | Retry policy for Workflow start + GitHub with clear idempotency |
| P2 | Centralize path/URI builders and schema tests |

---

## 12. References

| Doc | Use |
| --- | --- |
| [architecture.md](architecture.md) | Canonical pipeline + paths |
| [pipeline-dag.md](pipeline-dag.md) | Diagrams + glossary |
| [configuration.md](configuration.md) | Env / Pulumi |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Local workflow |
| [adding-a-project.md](adding-a-project.md) | New BMTs |
