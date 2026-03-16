# CI Cutover and VM Decommission

**Status:** Proposed
**Urgency:** LOWER PRIORITY
**Goal:** Replace async VM polling with synchronous Cloud Run Job handoffs, validate via shadow testing, cut over to Cloud Run as the primary BMT executor, and safely decommission the VM fleet.

---

## Reading Guide

This document is part of a 5-document roadmap series, split from the former holistic serverless migration plan.

| # | Document | Focus | Urgency |
|---|----------|-------|---------|
| 1 | [gcp-data-separation-and-dev-workflow.md](gcp-data-separation-and-dev-workflow.md) | Bug fixes, manifest, FUSE, WorkspaceLayout | MOST URGENT |
| 2 | [gcp-image-refactor.md](gcp-image-refactor.md) | Constants, types, entrypoint, decoupling | HIGH |
| 3 | [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) | Protocol, BaseBmtManager, contributor workflow | HIGH |
| 4 | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | Dockerfile, Cloud Run, Pulumi, coordinator | MEDIUM |
| **5** | **ci-cutover-and-vm-decommission.md** (this) | Direct API, shadow testing, cutover | **LOWER** |

**Dependency chain:** 1 → 2+3 → 4 → 5

**Depends on:** Document 4 (Cloud Run containerization and infra) must be completed first.

---

## Phase 7: CI/CD Integration & Direct API

**Goal:** Replace async polling with synchronous, observable handoffs.

- [ ] **7.0 Trigger + Handshake Semantics (Cloud Run Model)**
  - **Task:** Define whether CI still writes run trigger files when direct API execution is used.
  - **Task:** Document handshake equivalence: `gcloud run jobs execute --wait` completion replaces VM ack semantics.
  - **Task:** Define explicit failure fallback behavior when job execution fails before summary aggregation. Align with Phase 6.4 (in [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md)): who runs the coordinator when using `--wait` (same job's final task vs CI step) so pointer/status/cleanup always run exactly once.

- [ ] **7.1 Direct API Handoff**
  - **File:** `.github/workflows/bmt-handoff.yml`
  - **Task:** Use `gcloud run jobs execute` with the `--wait` flag. Pass the image digest (or tag that resolves to digest) so the executed image is immutable for the run.
  - **Task:** Stream container logs directly to the CI console.

- [ ] **7.2 WIF Identity Alignment**
  - **Task:** Grant GitHub WIF `roles/run.invoker` (or `roles/run.developer` only when deploy mutation is needed) and `roles/iam.serviceAccountUser` scoped to execution SA.
  - **Task:** Enforce repository/branch attribute conditions for WIF principal bindings.

- [ ] **7.3 Eventarc (Secondary/Internal Trigger)**
  - **Task:** Provision `gcp.eventarc.Trigger` as a fallback for GCS file-based triggers.
  - **Requirement:** Eventarc path must be mutually exclusive with direct API execution mode to prevent duplicate runs.

- [ ] **7.4 Cleanup Ownership in Job Model**
  - **Task:** Assign ownership for trigger/ack/status/summaries cleanup to the coordinator stage.
  - **Task:** Define cleanup order (e.g. post status/check last, then delete trigger/ack/status) and retention rule (e.g. delete only after N hours or after run is finalized) so artifacts needed for postmortems are not removed too early.

### Research Insights (Phase 7)

**Best Practices:**
- Keep CI handoff synchronous (`--wait`) for deterministic workflow outcome and simpler rollback handling.
- Define status/check ownership explicitly (CI post-step vs job-side coordinator) before removing VM steps.

**Implementation Details:**
- Standardize execution command shape (`--tasks`, payload override/env, `--wait`) and failure interpretation.
- Ensure logs include `workflow_run_id`, `run_id`, `project`, `bmt_id`, `leg_index` as structured fields.
- If Eventarc remains, define exact non-overlapping activation condition vs direct API path.
- Enforce digest-pinned image execution for all production CI invocations.

**Edge Cases:**
- `--wait` completion does not by itself guarantee pointer update/status posting unless coordinator duties are explicitly wired.
- CLI output formatting on failures can vary; rely on execution state/artifact checks, not only CLI stdout parsing.

**References:**
- [Execute Cloud Run jobs](https://cloud.google.com/run/docs/execute/jobs)
- [Eventarc overview](https://cloud.google.com/eventarc/docs)

---

## Phase 8: Migration, Validation & Cutover

**Goal:** Safely decommission the VM fleet.

- [ ] **8.1 Shadow Testing (1-2 Days)**
  - **Task:** Run BOTH the VM and the Job in parallel.
  - **Task:** Compare `ci_verdict.json` parity.

- [ ] **8.2 Direct API Cutover**
  - **Task:** Set Cloud Run Job as the primary `BMT Gate` status provider.
  - **Task:** Remove `start-vm` and `wait-handshake` steps from CI.

- [ ] **8.2a Rollback Drill (Mandatory Before Decommission)**
  - **Task:** Execute a documented rollback to VM path (`BMT_EXECUTOR=vm` and legacy handoff path restoration) and verify one full successful gate run. Ensure the workflow (or bmt command) reads `BMT_EXECUTOR`; when `vm`, use start-vm + wait-handshake and do not call `gcloud run jobs execute`. Document where the variable is set and the exact conditional.
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
- Keep a fast kill switch (`BMT_EXECUTOR=vm|job|shadow`) during hypercare.

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
| **7** | This document | `gh run view` — logs streaming in GitHub Actions + fallback behavior verification |
| **8** | This document | Verdict parity analysis |
| **8.2a** | This document | Recorded rollback drill with successful VM-gated run |

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
