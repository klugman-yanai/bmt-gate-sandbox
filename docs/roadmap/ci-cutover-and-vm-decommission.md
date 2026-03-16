# CI Cutover and VM Decommission

**Status:** Proposed
**Urgency:** LOWER PRIORITY
**Goal:** Replace async VM polling with Eventarc-driven Cloud Run Job execution (CI writes trigger; Eventarc → Workflows → Job → coordinator), validate via shadow testing, cut over to Cloud Run as the primary BMT executor, and safely decommission the VM fleet.

---

## Reading Guide

This document is part of a 5-document roadmap series, split from the former holistic serverless migration plan.

| # | Document | Focus | Urgency |
| --- | ---------- | ------- | --------- |
| 1 | [gcp-data-separation-and-dev-workflow.md](gcp-data-separation-and-dev-workflow.md) | Bug fixes, manifest, FUSE, WorkspaceLayout | MOST URGENT |
| 2 | [gcp-image-refactor.md](gcp-image-refactor.md) | Constants, types, entrypoint, decoupling | HIGH |
| 3 | [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) | Protocol, BaseBmtManager, contributor workflow | HIGH |
| 4 | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | Dockerfile, Cloud Run, Pulumi, coordinator | MEDIUM |
| **5** | **ci-cutover-and-vm-decommission.md** (this) | Eventarc primary, shadow testing, cutover | **LOWER** |

**Dependency chain:** 1 → 2+3 → 4 → 5

**Depends on:** Document 4 (Cloud Run containerization and infra) must be completed first.

**Implementation note:** The handoff between the workflow (CI → trigger write) and the VM implementation is currently bugged and does not work end-to-end. The migration direction is single-path Cloud Run/Eventarc execution; VM dual-support is intentionally being removed.

---

## Phase 7: CI/CD Integration (Eventarc Primary)

**Goal:** Replace async VM polling with trigger-and-event handoff. CI writes the run trigger to GCS; Eventarc fires on object finalize; Workflows invokes the Cloud Run Job and runs the coordinator. Single trigger path — no direct API invocation from CI.

- [x] **7.0 Trigger + Handshake Semantics (Eventarc Model)**
  - **Task:** CI writes exactly one run trigger file to `triggers/runs/<workflow_run_id>.json` (e.g. with `if_generation_match=0` to avoid duplicates). CI does **not** call `gcloud run jobs execute`.
  - **Task:** Document handshake equivalence: Eventarc delivery + Workflows execution replaces VM ack semantics. Workflow runs the job and then the coordinator step; completion of the Workflow execution is the synchronous boundary (job finished, status/check posted).
  - **Task:** Define explicit failure fallback when the job fails before summary aggregation. Coordinator runs in Workflow (or as a post-job step); pointer/status/cleanup run exactly once per run (see Phase 6.4 in [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md)).

- [x] **7.1 CI Trigger-Only Handoff**
  - **File:** `.github/workflows/bmt-handoff.yml` (or equivalent handoff workflow).
  - **Task:** CI step writes the run trigger JSON to GCS and exits. No `gcloud run jobs execute`. Rely on Eventarc (GCS object finalize) to start the Workflow → Job pipeline.
  - **Task:** Optional: add a follow-up step that waits for status/check (e.g. poll GCS or GitHub API) so the workflow run is gated on BMT outcome; otherwise the workflow completes when the write succeeds and status appears asynchronously.

- [x] **7.2 CI Identity (No Run Invoker)**
  - **Task:** CI identity (e.g. GitHub WIF) needs only `roles/storage.objectCreator` (or equivalent) on the bucket prefix `triggers/runs/`. **Do not** grant `roles/run.invoker` to CI; the Workflow SA invokes the Job.
  - **Task:** Enforce repository/branch attribute conditions on WIF for storage access if applicable.

- [x] **7.3 Eventarc Primary (Single Trigger Path)**
  - **Task:** Eventarc trigger is the **primary** execution path: GCS finalize on `triggers/runs/*.json` → Workflows (prefix filter, dedup) → Cloud Run Job. Provision and maintain `gcp.eventarc.Trigger` and Workflow as in [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) and the design doc.
  - **Requirement:** No direct API invocation from CI for the same runs; single trigger path to prevent duplicate executions. Workflows 24h dedup and CI `if_generation_match=0` support this.

- [ ] **7.4 Cleanup Ownership in Job Model**
  - **Task:** Assign ownership for trigger/ack/status/summaries cleanup to the coordinator stage (Workflow step or coordinator job).
  - **Task:** Define cleanup order (e.g. post status/check last, then delete trigger/ack/status) and retention rule (e.g. delete only after N hours or after run is finalized) so artifacts needed for postmortems are not removed too early.

### Research Insights (Phase 7)

**Best Practices:**

- Single trigger path (Eventarc) keeps IAM and failure semantics simple; CI does not need run.invoker.
- Define status/check ownership explicitly: coordinator (in Workflow or post-job) posts status and finalizes Check Run after job completion.

**Implementation Details:**

- CI trigger write: include `workflow_run_id`, `repository`, `sha`, `legs`, `run_context` in trigger JSON. Use digest-pinned image in the Job definition (Workflows invokes the job; image is set at deploy time).
- Ensure job/Workflow logs include `workflow_run_id`, `run_id`, `project`, `bmt_id`, `leg_index` as structured fields for debugging.

**Edge Cases:**

- Event delivery delay: CI step may complete before the job starts; use optional wait/poll step if the workflow must block on BMT outcome.
- Job or Workflow failure before coordinator: define fallback (e.g. timeout, retry, or manual remediation) so status/check are eventually updated.

**References:**

- [Eventarc overview](https://cloud.google.com/eventarc/docs)
- [Cloud Storage triggers for Eventarc](https://cloud.google.com/eventarc/docs/cloud-storage-triggers)
- [Workflows](https://cloud.google.com/workflows/docs)

---

## Phase 8: Migration, Validation & Cutover

**Goal:** Safely decommission the VM fleet.

- [ ] **8.1 Shadow Testing (1-2 Days)**
  - **Task:** Run BOTH the VM and the Job in parallel.
  - **Task:** Compare `ci_verdict.json` parity.

- [x] **8.2 Cloud Run Job Cutover**
  - **Task:** Set Cloud Run Job (Eventarc → Workflows → Job) as the primary `BMT Gate` status provider.
  - **Task:** Remove `start-vm` and `wait-handshake` steps from CI; CI only writes trigger to GCS.

- [ ] **8.2a Rollback Drill (Mandatory Before Decommission)**
  - **Task:** Execute a documented rollback within the Cloud Run/Eventarc model (for example: disable Eventarc trigger and restore previous Cloud Run workflow revision), then verify one full successful gate run.
  - **Task:** Capture rollback RTO and operator checklist in roadmap references.

- [ ] **8.3 Decommissioning**
  - **Task:** Remove `infra/packer/` and `infra/scripts/enforce-image-family-policy.sh`.
  - **Task:** Delete GCE instances and images.

### Research Insights (Phase 8)

**Best Practices:**

- Use time-boxed shadow runs with explicit parity criteria before cutover.
- Require rollback drill completion before decommissioning VM infrastructure.

**Implementation Details:**

- Gate cutover on measurable checks: parity rate target, zero untriaged diffs, status/check correctness, and cleanup correctness.
- Keep a fast kill switch within Cloud Run/Eventarc controls (for example: trigger enable/disable and workflow/job revision pinning) during hypercare.

**Edge Cases:**

- Superseded/closed PR logic must remain equivalent after migration to avoid posting stale statuses.
- Verify metadata cleanup and trigger deletion semantics still hold under job-based flow.

**References:**

- [Shadow shipping pattern](https://mergify.com/blog/shadow-shipping-how-we-double-executed-code-to-ship-safely)

---

## Complete Verification Matrix (All Phases)

This consolidated matrix covers all 5 roadmap documents. Each document also includes its own phase-specific verification rows.

| Phase | Document | Verification Method |
| :--- | :--- | :--- |
| **0** | [gcp-data-separation-and-dev-workflow.md](gcp-data-separation-and-dev-workflow.md) | `pytest tests/` passes with fixed pattern; `just validate-layout` passes; unit test for `local_digest()` asserts `inputs/` WAVs are excluded; manifest JSON generated and round-trips through `InputFileRegistry` |
| **1-3** | [gcp-image-refactor.md](gcp-image-refactor.md) + [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) | `pytest tests/` — unit tests for types, extraction, gate logic, contributor API contract |
| **4** | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | `docker run` — local FUSE simulation |
| **5-6** | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | `just deploy` + Manual Job Execution in GCP Console |
| **5.5** | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | IAM/WIF policy validation (resource-scoped secrets/storage, attribute conditions, digest policy checks) |
| **6** | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | Run matrix of >=20 legs and single leg with 40GB dataset; document resource tier and success criteria |
| **7** | This document | Trigger write succeeds; Eventarc→Job→coordinator completes; status/check visible in GitHub; fallback behavior verified |
| **8** | This document | Verdict parity analysis |
| **8.2a** | This document | Recorded rollback drill for Cloud Run/Eventarc path |

**Interpretation note:** Phase-level checks are blocking criteria for advancing to the next phase; Research Insights targets are optimization/quality goals unless promoted into checklist tasks.

### Suggested Quantitative Targets

- **Parity:** 100% verdict match for deterministic legs, or documented tolerance with triage for non-deterministic metrics.
- **Reliability:** Job completion success >= 99% over shadow window.
- **Performance:** Define baseline-relative target for heavy (40GB) legs and track p50/p95 runtime.
- **Security:** Verify effective IAM/WIF conditions before cutover.

### Additional Verification Checks

- Pointer correctness (`current.json latest/last_passing`) after mixed pass/fail task outcomes.
- Status/check run correctness for success, timeout, superseded, and schema-invalid scenarios.
- Log dump signed URL present in Check Run `output.summary` for all `failure` conclusions (gate fail, timeout, crash); Check Run finalized even when log dump upload fails (degraded note instead).
- Cleanup behavior for triggers/acks/status artifacts after each workflow run family.
- Contributor API contract checks: stub/type compatibility, base-class hook coverage, and reference manager conformance.
- Artifact contract checks: canonical JSON schema validation and JSONL parse-error budget enforcement.
