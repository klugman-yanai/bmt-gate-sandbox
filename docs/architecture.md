# Architecture

## Production pipeline

```mermaid
sequenceDiagram
    participant GH as "GitHub Actions"
    participant WF as "Google Workflows"
    participant CTRL as "Cloud Run Job: bmt-control"
    participant TASKS as "Cloud Run Jobs: bmt-task-standard / heavy"
    participant GCS as "Cloud Storage"
    participant API as "GitHub API"

    GH->>WF: start execution directly (WIF)
    WF->>CTRL: run plan mode
    CTRL->>GCS: write triggers/plans/<workflow_run_id>.json
    WF->>TASKS: run one task per planned leg
    TASKS->>GCS: write summaries + snapshots
    WF->>CTRL: run coordinator mode
    CTRL->>GCS: update current.json + prune snapshots
    CTRL->>API: finalize status/check
```

## Runtime contract

The active runtime is [`gcp/image/bmt`](gcp/image/bmt).

### Plugin SDK vs stage tree

**Image (`gcp/image/`, including `gcp/image/runtime/sdk/`):** stable contributor imports (`BmtPlugin`, `ExecutionContext`, manifest helpers, compatibility checks). Updating this code requires a **new Cloud Run image**.

**Stage mirror (`gcp/stage/` → GCS):** per-project plugins, `bmt.json`, inputs, `kardome_runner`. Updating these requires **syncing the bucket**, not necessarily an image rebuild. See [ADR 0004](adr/0004-plugin-sdk-boundary.md) and [bmt-python-contributor-protocol.md](bmt-python-contributor-protocol.md).

- `plan` reads enabled manifests and writes `triggers/plans/<workflow_run_id>.json`
- `task` reads the frozen plan and executes exactly one leg selected by `CLOUD_RUN_TASK_INDEX`
- `coordinator` reads summaries, updates pointers, prunes snapshots, and posts GitHub results
- `dataset-import` expands uploaded archives into `projects/<project>/inputs/<dataset>/`

## Storage model

- bucket root mirrors [`gcp/stage`](gcp/stage)
- published manifests live under `projects/<project>/...`
- immutable plugins live under `projects/<project>/plugins/<plugin>/sha256-<digest>/...`
- datasets live extracted under `projects/<project>/inputs/<dataset>/...`

Canonical runtime artifacts:

- `triggers/plans/<workflow_run_id>.json`
- `triggers/summaries/<workflow_run_id>/<project>-<benchmark>.json`
- `projects/<project>/results/<benchmark>/snapshots/<run_id>/latest.json`
- `projects/<project>/results/<benchmark>/snapshots/<run_id>/ci_verdict.json`
- `projects/<project>/results/<benchmark>/current.json`

## Contributor model

- author in [`gcp/stage/projects/<project>/plugin_workspaces`](gcp/stage)
- publish immutable plugin bundles with `just stage publish`
- upload WAV datasets with `just upload-wav`
- inspect the live bucket with `just mount <project>`

The old VM watcher, root orchestrator, and per-project `bmt_manager.py` inheritance stack have been removed from the active codebase. The supported execution path is the direct Workflow -> Cloud Run runtime only.

---

## Pipeline diagrams, glossary, and handoff

> **New to this project?** These diagrams are written to help you understand how the system works. All terms are defined below.
>
> Current state: `ci/check-bmt-gate`, 2026-03-19.

---

## Background

**BMT (Batch Model Testing)** is an automated quality check for audio models. It runs whenever a developer pushes code or opens a Pull Request (PR):

1. GitHub CI builds the code and uploads the test program (**runner**) to Google Cloud Storage (GCS).
2. CI starts a test job in **Google Cloud Run** and finishes immediately. It doesn't wait for the tests to finish.
3. Cloud Run executes the runner against a fixed set of audio files and calculates **NAMUH scores** (an audio quality metric).
4. Cloud Run compares these new scores against the **baseline** (the scores from the last successful run).
5. Cloud Run posts a **pass/fail** result back to the GitHub PR. A PR cannot merge until BMT passes.

### Key terms

| Term | Meaning |
| --- | --- |
| **runner** | The compiled program that actually runs the audio tests. |
| **plugin** | A project-specific Python script that sets up and invokes the runner. |
| **leg** | A single test case (one project combined with one BMT configuration). |
| **Benchmark** (path) | Short URL-safe folder name for one benchmark under a project (e.g., `false_rejects`). Paths use the placeholder **`<benchmark>`** so it is not confused with the manifest filename **`bmt.json`**. The same value is stored in **`bmt_slug`** inside `bmt.json`. |
| **snapshot** | All the outputs from a single test run (scores, pass/fail status, and logs). |
| **baseline** | The snapshot from the last successful test run. New scores are compared against this. |
| **GCS** | Google Cloud Storage. Used as a shared storage layer between GitHub CI and Cloud Run. |
| **run_id** | The unique ID of the GitHub Actions workflow. It groups all GCS files together for a single CI run. |

---

## Color key

🟦 **GitHub CI** · 🟩 **☁️ GCP / Cloud Run** · 🟨 **🪣 GCS Storage** · 🟥 **🐙 GitHub API**

---

## 1. End-to-end overview

CI starts the pipeline and stops. All testing and reporting back to GitHub happen asynchronously inside Cloud Run.

```mermaid
%%{init: {'flowchart': {'curve': 'basis'}}}%%
flowchart LR
    classDef ci fill:#eff6ff,stroke:#3b82f6,stroke-width:2px,color:#1e3a8a,rx:8px,ry:8px
    classDef gcp fill:#f0fdf4,stroke:#22c55e,stroke-width:2px,color:#14532d,rx:8px,ry:8px
    classDef gcs fill:#fefce8,stroke:#eab308,stroke-width:2px,color:#713f12,rx:8px,ry:8px
    classDef gh fill:#fff1f2,stroke:#f43f5e,stroke-width:2px,color:#881337,rx:8px,ry:8px
    classDef trigger fill:#f3f4f6,stroke:#6b7280,stroke-width:2px,stroke-dasharray: 5 5,rx:15px,ry:15px

    E([🚀 Push / PR / Manual]):::trigger

    subgraph CI_ENV[GitHub CI Environment]
        direction TB
        B[Compile + Unit Tests]:::ci
        H[Prepare BMT Request]:::ci
        R[Validate Prerequisites]:::ci
        P[Upload Runner to GCS]:::ci
        C[Dispatch to Cloud Run]:::ci

        B --> H --> R --> P --> C
    end

    GCP([☁️ Cloud Run: Run Tests]):::gcp
    GCS[(🪣 Google Cloud Storage)]:::gcs
    GH([🐙 GitHub: Commit / PR]):::gh

    E --> B
    C -->|Async Dispatch| GCP
    C -.->|Dispatch Failure| GH
    GCP <-->|Runner, Config, Results| GCS
    GCP -->|Post Results via App Token| GH
```

> **Security Note:** Cloud Run authenticates back to GitHub using a GitHub App token stored safely in GCP Secrets Manager. No long-lived GitHub secrets are passed to Cloud Run.

---

## 2. Handoff: GitHub CI → Cloud Run (`bmt-handoff.yml`)

This workflow runs after the code builds successfully. It checks requirements, uploads the runner if needed, and starts the Cloud Run job. **CI exits as soon as the Cloud Run job starts.**

```mermaid
%%{init: {'flowchart': {'curve': 'monotoneY'}}}%%
flowchart TD
    classDef action fill:#faf5ff,stroke:#a855f7,stroke-width:2px,color:#4c1d95,rx:6px,ry:6px
    classDef fail fill:#fff1f2,stroke:#e11d48,stroke-width:2px,color:#881337,rx:15px,ry:15px
    classDef term fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d,rx:15px,ry:15px
    classDef decision fill:#fffbeb,stroke:#d97706,stroke-width:2px,color:#78350f,rx:4px,ry:4px

    subgraph J1[Job 1 — Resolve Request]
        direction TB
        A1[Validate Repo Config]:::action
        A2[Authenticate to GCP]:::action
        A3[Save Run Details]:::action
        A4[Check Upload Needed]:::action
        A1 --> A2 --> A3 --> A4
    end

    subgraph J2[Job 2 — Publish Runner]
        B1[Verify Runner Exists]:::action
    end

    subgraph J3[Job 3 — Start Cloud Job]
        direction TB
        C1[Authenticate to GCP]:::action
        C2[Classify Request]:::action
        C3[Call Workflows API]:::action
        C4[Write Actions Summary]:::action
        C5[Post Error to GitHub]:::fail
        OC{Did Dispatch Succeed?}:::decision

        C1 --> C2 --> C3
        C3 -->|Success| C4 --> OC
        C3 -.->|Failure| C5 -.-> OC
    end

    DONE([✅ CI Exits: Tests running async]):::term
    BAIL([❌ CI Fails: Dispatch error]):::fail

    J1 --> J2
    J1 --> J3
    J2 --> J3

    OC -->|Yes| DONE
    OC -.->|No| BAIL
```

| Step | What it does |
| --- | --- |
| **Validate repo config** | Checks that all required GitHub variables are set correctly (e.g., `GCS_BUCKET`, `GCP_PROJECT`). |
| **Authenticate to GCP** | Trades a GitHub OIDC token for a short-lived Google Cloud token. No persistent secrets are used. |
| **Save run details** | Saves information like the commit SHA, branch name, and PR number to a shared context file. |
| **Check upload needed** | Skips uploading the runner if the exact same content digest is already in GCS. |
| **Verify runner exists** | Confirms the compiled runner artifact is present before attempting to upload it. |
| **Classify request** | Determines which test legs need to run based on the project configuration. |
| **Call Workflows API** | Triggers the `bmt-workflow` in Cloud Run via REST API. CI's job terminates here. |
| **Post error status** | If Cloud Run dispatch fails, it immediately posts an error state to GitHub so the PR is not stuck pending forever. |

---

## 3. Cloud Run workflow: test execution + reporting (`bmt-workflow`)

This runs entirely in Google Cloud after CI has exited. It executes in three sequential stages: **Plan** → **Parallel Tasks** → **Coordinator**.

```mermaid
%%{init: {'flowchart': {'curve': 'basis'}}}%%
flowchart TD
    classDef gcp fill:#f0fdf4,stroke:#22c55e,stroke-width:2px,color:#14532d,rx:6px,ry:6px
    classDef gcs fill:#fefce8,stroke:#eab308,stroke-width:2px,color:#713f12,rx:6px,ry:6px
    classDef gh fill:#fff1f2,stroke:#f43f5e,stroke-width:2px,color:#881337,rx:15px,ry:15px
    classDef entry fill:#f3f4f6,stroke:#6b7280,stroke-width:2px,rx:15px,ry:15px

    ENTRY([☁️ Cloud Run Execution Starts]):::entry

    subgraph PLAN[Stage 1 — Plan]
        direction TB
        P1[Load Config & Auth]:::gcp
        P2[Partition Standard & Heavy Legs]:::gcp
        P3[(Write Plan to GCS)]:::gcs
        P1 --> P2 --> P3
    end

    subgraph TASKS[Stage 2 — Task Jobs in Parallel]
        direction TB
        T1[(Read Plan)]:::gcs
        T2[Run Audio Tests]:::gcp
        T3[(Save Snapshot & Signal)]:::gcs
        T4[Notify GitHub: In Progress]:::gcp
        T1 --> T2 --> T3 --> T4
    end

    subgraph COORD[Stage 3 — Coordinator]
        direction TB
        C1[(Load leg summaries from GCS)]:::gcs
        C2[(Read last_passing from current.json)]:::gcs
        C3[Write current.json & prune snapshots]:::gcp
        C4[Finalize GitHub status Check PR]:::gcp
        C1 --> C2 --> C3 --> C4
    end

    CG([🐙 Post Status to Commit]):::gh
    CH([🐙 Update Check Run]):::gh
    CI([🐙 Post Score Summary to PR]):::gh

    ENTRY --> PLAN
    PLAN -->|Spawns N Standard + M Heavy Jobs| TASKS
    TASKS --> COORD
    C4 --> CG & CH & CI
```

| Stage | What it does |
| --- | --- |
| **Plan** | Reads project settings from GCS, partitions the test cases into standard or heavy workloads, and writes a test plan file. |
| **Task jobs** | Each job handles one test leg independently. It invokes the plugin, runs the runner, and **evaluates** the leg (including score vs baseline) inside the plugin. It captures NAMUH scores and logs, saves a snapshot to GCS, writes `triggers/progress/` and `triggers/summaries/`, and calls `publish_progress` for the Check Run. Standard and heavy tasks run in parallel. |
| **Coordinator** | Runs after the Workflow has finished all task jobs. It loads each **leg summary** from GCS, reads the prior **`last_passing`** pointer from `current.json`, **updates** `current.json` and prunes old snapshots, posts the final GitHub payload (`publish_final_results`), then **deletes** ephemeral `triggers/` files for this run (`cleanup_ephemeral_triggers`). It does **not** re-run scoring; comparison already happened in the task. |

> **Understanding `current.json`:** This file acts as a pointer. It stores the `run_id` of the `latest` run and the `last_passing` run. **Baseline comparison for gating** happens during each **task** (plugin `evaluate` using the prior `last_passing` snapshot). The **coordinator** only merges **leg outcomes** into new pointer values and prunes snapshots.
> **GitHub Check Runs:** After the plan is written to GCS, the **plan job** creates an in-progress Check Run (GitHub App) and writes `triggers/reporting/{run_id}.json` with `check_run_id`, `workflow_execution_url` (from `BMT_WORKFLOW_EXECUTION_URL`, set by the parent GCP Workflow from built-in env vars), and `started_at`. Task jobs call `publish_progress` to update that Check Run; the coordinator finalizes it. If GitHub is unavailable, the job logs a warning and BMT still runs; **commit status** and **PR comment** remain the primary pass/fail signals.

---

## 4. GCS bucket structure

```text
🪣 gs://bucket/
├── ⚡ triggers/                     # Ephemeral - deleted after coordinator succeeds
│   ├── plans/
│   │   └── run_id.json
│   ├── progress/
│   │   └── run_id/
│   │       └── project-bmt.json
│   ├── summaries/
│   │   └── run_id/
│   │       └── project-bmt.json
│   └── reporting/
│       └── run_id.json             # check_run_id + workflow console URL (plan job)
├── 📁 projects/                    # Persistent - seed data & results
│   └── project/
│       ├── project.json
│       ├── bmts/
│       │   └── benchmark/
│       │       └── bmt.json        # Test settings (thresholds, args)
│       ├── plugins/
│       │   └── name/
│       │       └── digest/
│       ├── plugin_workspaces/
│       │   └── name/
│       ├── inputs/
│       │   └── benchmark/
│       │       └── *.wav           # Input audio dataset
│       ├── mock_kardome_runner     # ⚙️ Compiled runner binary
│       └── results/
│           └── benchmark/
│               ├── current.json    # Run pointer (baseline)
│               └── snapshots/
│                   └── run_id/     # One snapshot per execution
│                       ├── latest.json       # Full score details
│                       ├── ci_verdict.json   # Pass/Fail boolean
│                       └── logs/             # Execution logs
└── 🗑️ log-dumps/                   # Temporary - 3-day TTL
    └── run_id.txt                  # Full error dump linked in PR comment
```

### Directory roles

| Directory | Contents | Lifetime |
| --- | --- | --- |
| `triggers/` | Coordination state files used by Cloud Run tasks (plans, progress, signals). | **Ephemeral:** Deleted by **`cleanup_ephemeral_triggers`** in the coordinator after **`publish_final_results`** succeeds (plan, progress, summaries, reporting JSON for that `run_id`). |
| `projects/` | Core configuration, plugins, input datasets, runner binaries, and all historical test snapshots. | **Persistent:** Written once, updated only upon deployment or a new run completion. |
| `log-dumps/` | Large execution logs for failed runs, viewable via a signed URL. | **Temporary:** Automatically deleted after 3 days. |

---

## Cross-diagram data flow

If you need to trace where a file is written and read across the architecture, use this reference:

| File / Artifact | Written by | Read by |
| --- | --- | --- |
| `triggers/plans/{run_id}.json` | Plan job | Task jobs (read plan), coordinator (read then delete) |
| `triggers/progress/{run_id}/…` | Task jobs (per leg) | Same task’s `publish_progress` (reads for Check Run body); not read by GitHub directly |
| `triggers/summaries/{run_id}/…` | Task jobs | Coordinator loads each leg summary |
| `results/{benchmark}/snapshots/{run_id}/` | Task Jobs | Coordinator, Local Dev Tools |
| `results/{benchmark}/current.json` | Coordinator | Next run (baseline), Local Dev Tools |
| `log-dumps/{run_id}.txt` | Coordinator (on failure) | Developers (via signed URL in PR comment) |
| `triggers/reporting/{run_id}.json` | Plan job (after `triggers/plans/…`) | Task jobs (`publish_progress`), coordinator (`finalize_check_run`); deleted after coordinator succeeds |

---

## Maintainer deep dive

### 1. Purpose and scope

**BMT** is an automated quality gate for audio-related models: a **runner** processes a fixed dataset; scores (e.g. NAMUH counters) are compared to a **baseline** from the last successful run. A PR or protected branch cannot merge until the gate passes.

**Scope of this document:**

- How GitHub, Google Cloud Workflows, Cloud Run, GCS, and the GitHub API interact.
- Where “truth” lives at each stage and how it can diverge.
- Risks that are **intrinsic** to an object-store-backed async pipeline, plus **repo-specific** issues called out in code review.

**Out of scope:** Step-by-step local setup (see [CONTRIBUTING.md](../CONTRIBUTING.md)); Pulumi and repo var names (see [configuration.md](configuration.md)).

---

### 2. Executive summary

The production path is **GitHub Actions → Workload Identity Federation → Google Cloud Workflows → Cloud Run Jobs** (`plan` → parallel `task` jobs → `coordinator`). **GCS** holds frozen plans, per-leg summaries, snapshots, and the **`current.json` pointer**. **GitHub** receives commit status, Check Runs, and optional PR-facing signals.

The design **trades** a single long-lived worker for **horizontal parallelism**, **clear stage boundaries**, and **CI that exits quickly**. The cost is **strong reliance on object naming and ordering**, **at-least-once semantics**, and **multiple code paths** that must stay consistent. Several **implementation gaps** (duplicate `results_path`, swallowed errors, ambiguous missing-summary handling) can produce **silent wrong behavior** or **misleading telemetry** if not addressed.

---

### 3. Actors and responsibilities

| Actor | Role |
| ----- | ---- |
| **GitHub Actions** | Build, test, upload runner artifacts, validate config, **start** a Workflows execution, **exit** without waiting for BMT completion. |
| **Google Cloud Workflows** | Orchestrates **plan** job, **N task** jobs (standard/heavy profiles), then **coordinator**; encodes barriers between stages. |
| **Cloud Run Jobs** | Run the packaged runtime (`gcp/image/bmt`): plan mode, task mode (one leg per index), coordinator mode, dataset-import, etc. |
| **GCS** | Shared **artifact store** and **coordination plane**: plans, progress, summaries, reporting metadata, snapshots, pointers, log dumps. |
| **GitHub API** | Commit status, Check Runs, optional comments; authenticated via **GitHub App** installation tokens from the runtime. |

---

### 4. End-to-end pipeline

### 4.1 Sequence (canonical)

The high-level sequence matches [architecture.md](architecture.md):

1. Actions authenticates to GCP (OIDC / WIF), then calls the **Workflow Executions API** to start the named workflow with a JSON **argument** (correlation id, repo metadata, etc.).
2. **Plan** job: reads enabled BMT manifests under the stage layout, partitions legs (e.g. standard vs heavy), writes **`triggers/plans/<workflow_run_id>.json`**, and may create **in-progress** Check Run metadata under **`triggers/reporting/`**.
3. **Task** jobs: each job reads the frozen plan, selects **one leg** via `CLOUD_RUN_TASK_INDEX`, runs the plugin and runner, **evaluates** against baseline (using prior **`current.json`** / snapshots), writes **snapshots** and **leg summaries** under **`triggers/summaries/`**, updates progress, and calls **`publish_progress`** for the Check Run.
4. **Coordinator** job: loads **all** leg summaries, updates **`current.json`** per results root, **prunes** snapshots not retained by the pointer, **finalizes** GitHub (status / Check Run / optional PR comment), **deletes** ephemeral `triggers/` objects for the run.

Detailed diagrams and step tables: [Pipeline diagrams, glossary, and handoff](#pipeline-diagrams-glossary-and-handoff) (above).

### 4.2 Handoff from Actions

The **`bmt-handoff.yml`** workflow (callable / dispatch) performs prerequisite checks, runner publish/skip logic, and **Workflows API** dispatch. **CI terminates** after a successful start (or posts failure to GitHub on dispatch error). See §7 for **concurrency** (`cancel-in-progress`) and §11.4 for **single-shot HTTP** behavior.

### 4.3 Gating semantics

**Baseline comparison and per-leg pass/fail** are intended to occur in the **task** (plugin `evaluate`). The **coordinator** merges **leg outcomes** into new pointer values and **does not re-score**. If task and coordinator disagree on what “done” means (e.g. missing summary treated as failure — §11.1), GitHub and GCS can reflect different stories.

---

### 5. Runtime contract (`gcp/image/bmt`)

The active runtime lives under [`gcp/image/bmt`](../gcp/image/bmt) (see [architecture.md](architecture.md)).

| Mode | Responsibility |
| ---- | ---------------- |
| **plan** | Discover enabled manifests, build **`ExecutionPlan`**, write plan JSON to GCS, seed reporting metadata. |
| **task** | Execute **exactly one** leg per invocation (task index + profile); write snapshot + summary. |
| **coordinator** | Load summaries; update **`current.json`**; prune snapshots; **finalize** GitHub; **cleanup** ephemeral triggers. |
| **dataset-import** | Expand uploaded archives into `projects/<project>/inputs/<dataset>/`. |

The old **VM watcher / root orchestrator / per-project `bmt_manager`** stack is **not** the supported path; contributor-facing docs in some files may still mention it — see §13.

---

### 6. Storage model

- **Bucket root** mirrors [`gcp/stage`](../gcp/stage) (see [architecture.md](architecture.md)).
- **Immutable** plugin bundles: `projects/<project>/plugins/<plugin>/sha256-<digest>/...`
- **Datasets:** `projects/<project>/inputs/<dataset>/...`
- **Results:** `projects/<project>/results/<benchmark>/` with **`current.json`** and **`snapshots/<run_id>/`**

**Ephemeral** (typically deleted after successful coordinator): `triggers/plans/`, `triggers/progress/`, `triggers/summaries/`, `triggers/reporting/`, etc.

**Canonical artifact list** (short form): [Storage model](#storage-model) (above). **Cross-writer table:** [Cross-diagram data flow](#cross-diagram-data-flow) (above).

---

### 7. Coordination model and distributed-systems properties

GCS is **not** a transactional database. The system relies on:

- **Immutable workflow run id** (and per-leg `run_id` in the plan) as **correlation id**.
- **Object keys** that encode intent (`triggers/plans/{id}.json`, summaries keyed by project and benchmark folder name).
- **Workflow barriers** between plan → tasks → coordinator (correctness depends on the workflow not starting the coordinator until tasks complete or fail).

**Implications:**

- **At-least-once** delivery and **retries** must be assumed; writers should be **idempotent** where possible (e.g. check-run metadata, pointer updates with clear semantics).
- **Listing** or “latest” without a **generation** or **single writer** discipline is unsafe under concurrency (mitigated here by **one coordinator** per run id after tasks).
- **Partial failure** (one task never writes its summary) must be visible as **incomplete**, not silently folded into another **reason code** — see §11.1.

---

### 8. Architectural strengths

1. **Async handoff:** Actions does not block on long audio jobs; wall-clock and **Actions billing** stay bounded relative to full BMT duration.
2. **Explicit staging:** Plan → parallel tasks → coordinator yields clear ownership and audit artifacts (frozen plan, per-leg summaries).
3. **Horizontal scaling:** One task per leg, with **standard** vs **heavy** job profiles, avoids a single bottleneck process.
4. **Auditable inputs:** The plan file answers “what was scheduled for this workflow run?”
5. **Separation of packages:** `.github/bmt/ci/` (CI CLI and handoff), `gcp/image/runtime/` (orchestration), `tools/` (local dev) map to different deployment surfaces.
6. **Security direction:** WIF from Actions to GCP; GitHub App + short-lived tokens at runtime — **when fully wired**, avoids long-lived keys in CI.

---

### 9. Ports and adapters (hexagonal view)

This is a **conceptual** map, not a literal package layout.

| Layer | Contents |
| ----- | -------- |
| **Domain core** | Leg evaluation: load inputs, run runner/plugin, parse scores, compare to baseline, produce **leg verdict** and snapshot payloads. |
| **Inbound ports** | Workflow/task invocation (env: `BMT_WORKFLOW_RUN_ID`, `CLOUD_RUN_TASK_INDEX`, profile), frozen **plan** JSON, BMT manifests. |
| **Outbound ports** | **Object store** (read/write plans, summaries, snapshots, pointers), **GitHub** (checks, status), **secrets** (App key via Secret Manager), **logging/metrics**. |
| **Adapters** | `gcs` helpers in CI; runtime artifact writers/readers; `github_reporting` / PyGithub wrappers; Workflows API client. |

**Leakage risk:** Path strings and JSON field names duplicated across CI, runtime, and tools weaken the “port” boundary; central **contract** modules and tests reduce drift.

---

### 10. Weak points — design-level (non-documentation)

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

### 11. Weak points — implementation-level (code and behavior)

### 11.1 Duplicate `results_path` / pointer collision

**`build_plan()`** (`gcp/image/runtime/planning.py`) appends one **`PlanLeg` per enabled manifest** but does **not** enforce uniqueness of **`results_path`** across legs.

The **coordinator** (`run_coordinator_mode` in `gcp/image/runtime/entrypoint.py`) loops each leg and, for each:

- Resolves **`results_root = stage_root / leg.results_path`**
- Reads/writes **`current.json`** and **prunes snapshots** under that root

If two enabled BMTs share the same **`results_path`**, later legs **overwrite** the pointer and **prune** snapshots needed by earlier legs — **silent data loss** or **wrong baselines**.

**Mitigation direction:** Validate at **plan** time (fail fast) or namespace pointers by **`bmt_id`** under a shared prefix.

### 11.2 Missing summary conflated with runner failure

`_load_summary_or_failure` catches **`FileNotFoundError`** and returns a synthetic **`LegSummary`** with **`reason_code="runner_failures"`** and **`status=FAIL`**.

That conflates:

- **Artifact never written** (task crash, path bug, workflow ordering, eventual consistency lag)
- **Actual runner/plugin failure** after a summary would have been written differently

**Mitigation direction:** Distinct **`reason_code`** (e.g. `summary_missing`, `incomplete_plan`) and alerting hooks.

### 11.3 GitHub outcome can diverge from GCS

**`gcp/image/runtime/github_reporting.py`** uses **`except Exception`** in several places (e.g. **`create_started_check_run`**, finalize paths). **Transient** GitHub API errors can leave **Checks or status stale** while **GCS** already reflects the true BMT outcome.

**Mitigation direction:** Structured retries with backoff, **non-zero exit** or explicit **reconciliation** when finalization fails, **metrics** on finalize failures.

### 11.4 `object_exists` swallows infrastructure errors

In **`.github/bmt/ci/gcs.py`**, **`object_exists`** catches **any** `Exception` and returns **`False`**:

```106:115:/home/yanai/sandbox/bmt-gcloud/.github/bmt/ci/gcs.py
def object_exists(uri: str) -> bool:
    """Return True if the GCS object exists."""
    try:
        bucket_name, path = parse_gs_uri(uri)
        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        return blob.exists()
    except Exception:
        return False
```

Callers cannot distinguish **“object missing”** from **auth failure, quota, or network error** — leading to **wrong control-flow** (e.g. skip upload, wrong branch).

**Mitigation direction:** Let **`NotFound` / false** be distinct from **`GcsError`** for other failures.

### 11.5 Workflows dispatch: single HTTP attempt

**`start_execution`** in **`.github/bmt/ci/workflows_api.py`** performs a **single** `POST` with a fixed timeout. Transient **5xx/429** can fail the handoff. Retries require **care** (idempotency, duplicate execution ids) if added.

### 11.6 CI ↔ `gcp.image` import coupling

**`.github/bmt/ci/core.py`** (and related modules) import **`gcp.image.config`** and related symbols. Refactors under **`gcp/image/config`** can break **`uv run bmt`** without a **stable, narrow** interface.

### 11.7 Broad exception handling elsewhere

Patterns such as **`except Exception`** in **`ci/github.py`**, **`download_json`** / **`load_context_from_file`** in **`ci/config.py`**, and runtime reporting **collapse** error types and can **hide** validation failures.

### 11.8 Large orchestration modules

**`gcp/image/runtime/entrypoint.py`** centralizes multiple modes; CI **handoff** aggregates many steps. This **concentrates** failure modes and can make **unit test coverage** uneven for rare branches.

---

### 12. Security and credentials

| Concern | Practice |
| ------- | -------- |
| **Actions → GCP** | OIDC + **Workload Identity Federation**; avoid long-lived GCP JSON keys in GitHub. |
| **Least privilege** | Separate IAM for “upload from CI” vs “runtime worker” where feasible; scope **attribute conditions** on repo/ref. |
| **GitHub App** | Private key in **Secret Manager**; runtime mints **short-lived installation tokens**. |
| **Secrets in logs** | Ensure tokens and signed URLs never land in **INFO** logs at full length. |

See [configuration.md](configuration.md) for variable and secret names.

---

### 13. Documentation alignment

Canonical runtime description: [architecture.md](architecture.md) (Workflows + Cloud Run; VM stack removed).

**AGENTS.md**, **CLAUDE.md**, and **docs/README.md** are maintained to match **Workflows + Cloud Run** (this document). If you find leftover VM-era wording, treat it as a bug and fix or remove it.

---

### 14. Observability and operations

Recommended practices (industry-standard for this architecture):

- **Structured logs** with `workflow_run_id`, repo, commit, leg identifiers on every line.
- **Metrics:** time from plan write to **terminal** GitHub check; counts of **missing summaries**, **finalize failures**, **GcsError** by type.
- **Reconciliation / watchdog:** optional job to find **stuck** pending checks or **orphan** triggers beyond a TTL.
- **Alerting** on auth failures to GitHub API, GCS permission errors, and rising **synthetic** `runner_failures` from §11.2.

---

### 15. Prioritized remediation roadmap

The **full backlog** (why + recommendations per issue) lives in **[plans/bmt-weak-points-remediation.md](plans/bmt-weak-points-remediation.md)**. The table below is a short index only.

| Priority | Item | Rationale |
| -------- | ---- | --------- |
| P0 | Enforce **unique `results_path`** per plan (or namespace pointers) | Prevents silent cross-leg corruption. |
| P1 | **Distinct reason codes** for missing summary vs runner failure | Correct operations and debugging. |
| P1 | **Fix `object_exists`** (and similar) to surface non-404 errors | Prevents wrong CI branches on infra failure. |
| P2 | **Retry/backoff** for Workflows start + GitHub finalize with clear idempotency rules | Reduces flaky handoff and split-brain. |
| P2 | **Centralize** path/URI builders and critical JSON schemas | Reduces contract drift. |
| P3 | Introduce a **thin stable API** between CI package and `gcp.image` config | Safer refactors. |

---

### 16. References

| Document | Use |
| -------- | --- |
| [architecture.md](architecture.md) | Short canonical pipeline and paths |
| *Above: Pipeline diagrams section* | Diagrams, glossary, handoff steps |
| [configuration.md](configuration.md) | Env, Pulumi, branch protection |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Local workflows and testing |
| [adding-a-project.md](adding-a-project.md) | New projects and BMTs |

---

*Generated as a maintainer-facing architecture review; update this file when the production pipeline or critical contracts change.*