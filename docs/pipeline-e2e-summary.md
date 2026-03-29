# BMT pipeline — end-to-end summary

**Purpose:** One place for **when** CI runs BMT, **what** each GitHub job does, **how** handoff and GCP fit together, and **how** GitHub status/checks/comments are updated — with **accurate** wording on failure modes and IDs.

**Related:** [architecture.md](architecture.md) (design, glossary, ADR index) · [diagrams/gcs-storage.md](diagrams/gcs-storage.md) (who writes what in GCS) · [weak-points-remediation.md](weak-points-remediation.md) (prioritized risks) · [contributors.md](contributors.md) (plugin SDK) · [.github/README.md](../.github/README.md) (workflow layout, production bundle notes).

---

## Two different GitHub run IDs

Confusing these breaks debugging.

| ID | Workflow | Role |
| --- | --- | --- |
| **Caller / CI run id** (`ci_run_id` input to `bmt-handoff.yml`) | The workflow that built the repo and (in production) uploaded **`runner-*`** artifacts — e.g. [`trigger-ci-pr.yml`](../.github/workflows/trigger-ci-pr.yml) or a consumer’s `build-and-test` run | **`gh api …/artifacts`** lists **`runner-*`** from **this** run; artifact download uses **this** id |
| **Handoff run id** (`WORKFLOW_RUN_ID` in the **Dispatch** job of `bmt-handoff.yml`) | The **reusable** `bmt-handoff` workflow execution (`github.run_id` **of that** workflow) | Ephemeral GCS paths use **`triggers/.../{wid}/`** where **`wid` is this handoff run id**, **not** `ci_run_id` |

Reusable workflows get their **own** `github.run_id`; inputs like `ci_run_id` are still evaluated in the **caller’s** context when passed from the parent workflow.

---

## When the full BMT path runs vs when it does not

### This repository (`bmt-gcloud`) — as wired today

**Runs**

- [`.github/workflows/trigger-ci-pr.yml`](../.github/workflows/trigger-ci-pr.yml): **`pull_request`** targeting **`dev`** or **`ci/check-bmt-gate`**.
- Job **`bmt`** calls **`bmt-handoff.yml`** only if:
  - **`build_release`** finished **`success`** or **`skipped`**, and
  - **`github.event.pull_request.head.repo.full_name == github.repository`** (same-repo PRs only; fork PRs skip BMT on this path).
- **`bmt`** depends only on **`build_release`**, not on **`build_non_release`** (which uses **`continue-on-error: true`**).

**Does not run (GitHub handoff)**

- [`.github/workflows/trigger-ci.yml`](../.github/workflows/trigger-ci.yml): **`push`** to **`ci/check-bmt-gate`** or **`workflow_dispatch`** → only [`build-and-test-dev.yml`](../.github/workflows/build-and-test-dev.yml) — **no** `bmt-handoff`.
- PRs to branches other than **`dev`** / **`ci/check-bmt-gate`** (no matching trigger).
- Fork PRs (same-repo condition fails).

### Production-shaped consumer (e.g. core-main)

Intent is documented in [`.github/README.md`](../.github/README.md): a **thin** entry workflow (release template may use **`pull_request_target`** with a **same-repo guard** on build/BMT) **`workflow_call`s** a full **build** workflow, then **`bmt-handoff.yml`**. Exact YAML lives in the consumer repo after release copy.

**Note:** [`build-and-test.yml`](../.github/workflows/build-and-test.yml) **does not define a `bmt_handoff` job** — it only stages/uploads **`runner-*`** artifacts from release builds. Handoff is wired by the **caller** (e.g. thin PR workflow), not inside that file.

---

## Dev vs production — workflow behavior

| Topic | This repo (typical dev wiring) | Production intent |
| --- | --- | --- |
| PR trigger | `pull_request` | Often `pull_request_target` + same-repo checks (see README) |
| Build | Placeholder jobs in `trigger-ci-pr.yml` / `build-and-test-dev.yml` | Real CMake/Gradle in `build-and-test.yml` |
| Runner artifacts | `skip_missing_runner_artifacts: true`, manifest-only legs possible | Real binaries required; missing artifact fails publish |
| Mock runner | `use_mock_runner: true` when PR **base** is `ci/check-bmt-gate` | Normally false |
| BMT after push | `trigger-ci.yml` → build **without** handoff | Policy choice per consumer |

---

## GitHub workflows — jobs in detail

### `trigger-ci-pr.yml` (PR → dev / ci/check-bmt-gate)

1. **`checkout` (Snapshot)** — Checkout PR head; [`.github/actions/dev/checkout-presets`](../.github/actions/dev/checkout-presets) emits **`release_presets`** / **`non_release_presets`** JSON for matrices.
2. **`build_release`** — One matrix row per release preset; in this repo a **placeholder** (production: full build + **`uv run bmt preset stage-release-runner`** + upload **`runner-<preset>`**).
3. **`build_non_release`** — Parallel non-release matrix; **`continue-on-error: true`** so it does **not** block BMT.
4. **`bmt`** — Reusable **`bmt-handoff.yml`** with `ci_run_id`, head SHA/branch/ref, PR number, `use_mock_runner`, `skip_missing_runner_artifacts: true`, `vars.CLOUD_RUN_REGION`, `vars.BMT_STATUS_CONTEXT`.

### `bmt-handoff.yml` — Plan → Publish → Dispatch

**`plan`**

- Checkout **`head_sha`**.
- **`prepare-context`**: run context (`pr` vs `dev`), resolve PR number when possible, **`runner_matrix`** from release-runner parsing.
- Optional dev-only synthetic matrix row.
- List **`runner-*`** artifact names for **`ci_run_id`** (or use input override).
- WIF + **`uv run bmt handoff write-context`** and **`uv run bmt runner filter-upload-matrix`**.

**`publish`**

- Skipped when there is nothing to publish (`matrix_publish_keys == '[]'`).
- Per leg: download **`runner-<preset>`** from **`ci_run_id`** (unless `manifest_only`), normalize to **`kardome_runner`** / optional **`libKardome.so`**, **`uv run bmt runner upload-to-gcs`** (or dev manifest path + **`validate-in-repo`**).
- Unsupported projects (no stage layout): notice, not a failure.

**`publish_omitted`**

- Notice-only cells for legs omitted from publish (no bucket BMT layout). `dispatch` does not gate on this job; the workflow YAML documents that `publish_omitted` must stay notice-only while excluded from gating.

**`dispatch`**

- Runs if **`plan`** succeeded and **`publish`** succeeded or was skipped; requires **`!cancelled()`**.
- **`filter-handoff-matrix`**: intersect matrix with bucket → **`accepted_projects`**, **`filtered_matrix`**, **`has_legs`**.
- Unless **`use_mock_runner`**: **`uv run bmt handoff validate-dataset-inputs`** (fail fast if no `.wav` in GCS for accepted projects).
- **`WORKFLOW_RUN_ID: ${{ github.run_id }}`** (this **handoff** workflow’s id) + **`uv run bmt handoff write-context`** + **`uv run bmt dispatch invoke-workflow`** → claims or reloads **`triggers/dispatch/{wid}.json`** and then starts **Google Workflows** (async). Matching `started` receipts are reused instead of issuing a second remote start; mismatched repo / head SHA is a hard failure. `start_execution` retries only explicit HTTP `429`, `503`, and other `5xx` responses. Supersede cancel retries three total attempts with `1s` then `3s` backoff; `BMT_DISPATCH_REQUIRE_CANCEL_OK=true` makes cancel exhaustion abort the new dispatch before remote start.
- Success: summary **`mode: run_success`**; failure: **`failure-fallback`** composite, then job fails.

**Concurrency:** `bmt-handoff.yml` uses **`cancel-in-progress: true`** — a newer handoff can cancel an in-flight one (see smells).

### GCP side (high level)

1. **Plan (Cloud Run)** — Writes **`triggers/plans/{wid}.json`**, **`triggers/reporting/{wid}.json`**, etc. (`wid` = handoff run id).
2. **Task jobs** — Per leg: runner + plugin; **`triggers/progress/`**, **`triggers/summaries/`**, durable **`projects/.../results/.../snapshots/`**. Scoring vs baseline uses **`last_passing`** from **`current.json`** ([architecture.md](architecture.md)).
3. **Coordinator** — Reads all leg summaries, acquires per-results-path leases, runs GitHub reporting preflight, writes **`triggers/finalization/{wid}.json`**, promotes **`current.json`** / prunes snapshots, then attempts GitHub terminal publish. On clean success it removes ephemeral **`triggers/{wid}/`**; on required-but-incomplete publish it exits non-zero and preserves reporting/finalization metadata for reconciliation (see [diagrams/gcs-storage.md](diagrams/gcs-storage.md)).

---

## Handoff — data, runner, and GCS

- **`bmtgate`** (`ci/`, **`uv run bmt`**) prepares context, filters matrices, uploads runners (or dev manifests), validates datasets when not mocking, and invokes Workflows via WIF.
- **`kardome_runner`** (and optional **`libKardome.so`**) come from **release** CI artifacts, keyed by preset; handoff downloads from the **caller** run and uploads into the stage layout mirrored to GCS.
- **`benchmarks/projects/...`** (`bmt.json`, plugins, inputs, published digests) must be **in repo and synced** to the bucket for cloud runtime consistency ([benchmarks/projects/README.md](../benchmarks/projects/README.md)).

---

## GitHub — checks, PR comment, commit status (two identities)

- **GitHub Actions `GITHUB_TOKEN`** — Used in **`failure-fallback`** to **`POST /repos/.../statuses/{sha}`** with **`state=failure`** when classify/dispatch fails, so branch protection can see a **failed** context without waiting for GCP.
- **GitHub App token** (runtime **`resolve_github_app_token`**) — Used for **Check runs** (create in progress, update progress, finalize) and **PR issue comments** (`upsert_*_pr_comment`) from Cloud Run ([`backend/github/reporting.py`](../backend/src/backend/github/reporting.py), [`backend/runtime/github_reporting.py`](../backend/src/backend/runtime/github_reporting.py)).

**Plan (cloud)** creates an **in_progress** check and optional **started** PR comment when metadata and token exist. **Coordinator** finalizes the check and posts **final** commit status + PR comment.

---

## Pending / failure handling — no “never dangling” guarantee

The pipeline **tries hard** not to leave a check **stuck in `in_progress`**, but wording should stay precise:

- **`publish_github_failure`** (coordinator / abort paths): loads summaries (or synthetic failures), calls **`publish_final_results`**, then retries finalize with explicit failure description if needed; if legs **aggregate to pass** but APIs failed, code **retries success** and **avoids a false red** — if that still fails, it **logs** rather than forcing failure ([`github_reporting.py`](../backend/src/backend/runtime/github_reporting.py)).
- If **no** reporting metadata exists (**no** `check_run_id` / URL — e.g. cancelled before plan wrote metadata), **`publish_github_failure` may no-op**; there is **nothing** to finalize on GitHub.
- **Missing leg summary** is treated as failure at aggregation ([diagrams/gcs-storage.md](diagrams/gcs-storage.md)); that closes the gate **red**, not pending.
- If GitHub publish is required but preflight cannot get the runtime reporter ready, the coordinator exits **non-zero before touching `current.json`**.
- After preflight succeeds, the side-effect order is still **preflight → pointer promotion → GitHub finalize**. If terminal publish still does not complete, the coordinator exits **non-zero** and preserves `triggers/reporting/{wid}.json` plus `triggers/finalization/{wid}.json` for reconciliation, but `current.json` may already reflect the run.
- **`uv run bmt ops doctor --workflow-run-id <wid>`** is the repo-owned inspection path for dispatch receipts, finalization state, preserved reporting metadata, lease residue, and log-dump presence. **`uv run bmt ops doctor --scan-stale --older-than-hours <N>`** scans for stale control-plane residue across runs.
- Handoff job output **`bmt_recovery_used`** is set **`true`** when dispatch did **not** succeed and the fallback path ran. **`bmt_dispatch_fallback_used`** remains as a deprecated alias.

---

## Adding BMTs and the plugin SDK

- New benchmark: **`benchmarks/projects/<id>/bmts/<slug>/bmt.json`**, **`inputs/`**, **`plugin.json`** + implementation; publish plugin digests and sync bucket ([contributors.md](contributors.md), [benchmarks/projects/README.md](../benchmarks/projects/README.md)).
- **`import bmtplugin as bmt`** — implement **`BmtPlugin`** (`prepare`, `execute`, `score`, `evaluate`; **`teardown`** in `finally` after successful `prepare`). **`plugin.json` `api_version`** must match the runtime image.

---

## Smells, unclear behaviors, and unhandled cases

These are **known gaps, ambiguities, or risks** — not an exhaustive bug list. Prioritized detail lives in [weak-points-remediation.md](weak-points-remediation.md).

**Workflow / CI**

- **`cancel-in-progress`** on build and BMT can abort uploads or handoff mid-flight; cloud work may still run until superseded or cancelled ([`bmt-cancel-on-pr-close.yml`](../.github/workflows/bmt-cancel-on-pr-close.yml) addresses PR close via `cancel-pr-execution`).
- Overlapping coordinators are still the sharpest residual race: dispatch retries supersede cancel, but if cancel keeps failing and strict mode is left off, a newer run can still start while an older remote execution is alive.
- Dispatch retries and `triggers/dispatch/{wid}.json` receipts reduce duplicate-start risk, but a crash after remote start and before receipt update would still need reconciliation.

**GCS / coordinator**

- **No transactions** — ordering and idempotent writers still matter. Duplicate **`results_path`** is guarded in the normal plan path, but stale/injected plans would still be dangerous (see weak-points **B.1**).
- **Coordinator** now uses `incomplete_plan` for missing summaries in coordinator/failure-publish flows and records expected/present leg counts plus missing/extra keys on `triggers/finalization/{wid}.json`, but completeness still needs stronger metrics/signals (**B.2**, **A.5**).
- **Transactional finalization** makes incomplete terminal publish explicit, but the current order is still GCS promotion before GitHub finalize. A `failed_github_publish` record means operators may see durable results state advance before GitHub catches up (**B.3**, **B.5**).

**GitHub / gates**

- **Check run** may never be created if plan/reporting preconditions fail (no URL, no App token) — then there is **no** `in_progress` check to “unstick”; **commit status** from Actions fallback only covers **handoff** failures, not all cloud abort shapes.
- **Pass on disk + GitHub API broken** — retry logic avoids false red but may leave **inconsistent** UI vs GCS truth; required-but-incomplete publish now exits non-zero and keeps reporting metadata for follow-up instead of looking fully clean.

**Operational / repo hygiene**

- **Production** wiring is **contractual** (release bundle, vars, secrets); this repo’s **trimmed** tree may not include every template path referenced in README — verify consumer repos against [.github/README.md](../.github/README.md).

---

## Changelog (this doc)

- Initial version: aligns narrative with current YAML/runtime, fixes overstated “never pending” claims, documents **dual run ids** and **dual GitHub identities**, and adds the smells section with pointers to **weak-points-remediation.md**.
