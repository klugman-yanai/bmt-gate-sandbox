## BMT VM Pre-Baked Image Rollout Plan (Blue/Green, Script-First, Native GCloud)

### Summary
Implement a safe, phased migration to a **pre-baked VM image** for BMT runtime using native `gcloud` flows, while keeping your current architecture intact:

- Runtime code still syncs from `gs://<bucket>/code` on each boot.
- VM image pre-bakes OS/runtime dependencies to reduce cold-start variability.
- Cutover is **blue/green** using `BMT_VM_NAME` switch (instant rollback path).
- Delivery is **scripted first**, then automated via Cloud Build in phase 2.

This plan is decision-complete with your chosen defaults:
- Cutover: **Blue/Green swap**
- Automation: **Script now, pipeline next**
- Bake scope: **Deps-only prebake (code still from GCS)**

---

## Grounded Current State (from repo inspection)
1. VM startup currently does:
- `startup_wrapper.sh` syncs `gs://<bucket>/code` -> `/opt/bmt`.
- `startup_example.sh` resolves `uv`, installs deps if missing, loads app secrets, runs watcher, self-stops.

2. Workflow side currently does:
- `bmt-handoff-run` calls `sync-vm-metadata` then `start-vm`.
- VM metadata sync already manages `GCS_BUCKET`, `BMT_REPO_ROOT`, inline startup script.

3. Risk in current boot model:
- Dependency install can still happen at boot (slow/failure-prone).
- No strict fingerprint gate for “deps match current code lockfile”.

---

## Important Interface / Contract Changes

### 1) New bootstrap scripts (bmt-gcloud repo)
Add:
- `remote/code/bootstrap/build_bmt_image.sh`
- `remote/code/bootstrap/create_bmt_green_vm.sh`
- `remote/code/bootstrap/cutover_bmt_vm.sh`
- `remote/code/bootstrap/rollback_bmt_vm.sh`
- `remote/code/bootstrap/export_vm_spec.sh` (read-only snapshot helper)

These are operator scripts; no workflow trigger contract changes required.

### 2) VM dependency fingerprint contract (internal runtime)
Update:
- `remote/code/bootstrap/install_deps.sh`
- `remote/code/bootstrap/startup_example.sh`

Add persistent stamp file:
- `/opt/bmt/.venv/.bmt_dep_fingerprint`

Fingerprint input:
- hash of `/opt/bmt/pyproject.toml` + `/opt/bmt/uv.lock` (and optionally pinned uv checksum file)

Behavior:
- If fingerprint mismatch at boot, run `install_deps.sh`, then refresh stamp.
- If match, skip reinstall.

This keeps prebake fast but safe when lockfile changes.

### 3) Optional metadata labeling (non-breaking)
Add (optional) VM labels/metadata for ops traceability:
- `bmt_image_family`
- `bmt_image_version`
- `bmt_bake_timestamp`

No CI contract dependence; observability only.

---

## Phase Plan (Actionable)

## Phase 0: Baseline + Safety Rails (No Cutover Yet)
1. Export current VM spec (machine type, SA, scopes, network, tags, disk, metadata) to artifact file.
2. Validate current startup metadata and bucket objects are healthy.
3. Define naming conventions:
- Image family: `bmt-runtime`
- Image name: `bmt-runtime-YYYYMMDD-HHMM`
- Green VM: `${BMT_VM_NAME}-v2`
- Blue VM: existing `${BMT_VM_NAME}`

Acceptance:
- You can recreate current VM behavior from exported spec.
- Rollback script target and naming are fixed.

## Phase 1: Build Pre-Baked Image (Scripted, Deterministic)
1. `build_bmt_image.sh`:
- Create temporary builder VM from pinned Ubuntu family.
- Install required system packages + Python + `uv` tooling.
- Sync `gs://<bucket>/code` to `/opt/bmt`.
- Run `/opt/bmt/bootstrap/install_deps.sh /opt/bmt`.
- Write `/opt/bmt/.image_manifest.json` with:
  - bake timestamp
  - source image
  - lockfile hash
  - uv binary checksum/version
- Stop builder VM.
- Create custom image in family `bmt-runtime`.
- Delete builder VM.

2. Enforce script fail-fast:
- Any missing object/hash mismatch aborts image creation.
- No silent fallback to unpinned state.

Acceptance:
- Image exists and is reproducible from script inputs.
- Manifest inside image captures provenance.

## Phase 2: Create Green VM (No Traffic Switch Yet)
1. `create_bmt_green_vm.sh`:
- Create new VM from baked image using exported blue spec (same SA/scopes/network/tags).
- Set identical BMT metadata keys (`GCS_BUCKET`, `BMT_REPO_ROOT`, startup-script via existing sync tooling).
- Keep blue VM unchanged.

2. Smoke validation on green:
- Start green VM once.
- Confirm startup path reaches watcher and self-stop.
- Confirm no dependency reinstall when fingerprint matches.
- Confirm `gcloud`/secret access works.

Acceptance:
- Green VM is operational and self-stops correctly.
- Cold boot no longer depends on full dependency bootstrap.

## Phase 3: Sandbox Cutover + Runtime Validation
1. In `bmt-gate-sandbox`, update repo var `BMT_VM_NAME` -> green VM.
2. Run one PR merge test (normal flow, no manual trigger).
3. Validate:
- Trigger write, handshake ack, status file progression.
- Runtime completion + `BMT Gate` terminal result.
- Bucket retention behavior unchanged (`runs` drain; `acks/status` bounded).

Acceptance:
- Full BMT cycle passes on green VM in sandbox.
- No regression in status/check behavior.

## Phase 4: Core-Main Cutover
1. Update `Kardome-org/core-main` repo var `BMT_VM_NAME` -> same green VM.
2. Run one controlled PR merge into `ci/check-bmt-gate`.
3. Run one additional reproducibility run.

Acceptance:
- Core-main passes same end-to-end checks.
- No infra drift between sandbox and core-main.

## Phase 5: Rollback and Finalize
1. Keep blue VM stopped but intact for fast rollback window (for example 72 hours).
2. If failure:
- switch `BMT_VM_NAME` back to blue
- rerun one validation PR
3. If stable:
- retire blue VM
- keep last N images (for example 3) and delete older.

Acceptance:
- Rollback is one variable change + re-test.
- Image lifecycle is bounded and auditable.

## Phase 6 (Next): Cloud Build Automation
1. Add `cloudbuild.bmt-image.yaml` to build image from script in CI environment.
2. Add trigger (manual + optional scheduled).
3. Keep promotion/cutover manual approval gate.
4. Store bake logs/metadata centrally (Cloud Logging + artifact bucket path).

Acceptance:
- Image build is reproducible and centrally logged.
- Human-controlled promotion remains in place.

---

## Exact Validation Matrix

1. **Boot determinism**
- First boot on green from baked image succeeds.
- `startup_example.sh` skips reinstall when fingerprint matches.

2. **Lockfile drift handling**
- Change `uv.lock` in code root.
- Next boot must detect mismatch and run install once, then update fingerprint.

3. **Secret/runtime auth**
- VM can load prod/test app secrets using existing canonical/alias logic.
- No change in GitHub status posting permissions.

4. **End-to-end handoff**
- Trigger -> ack -> status -> terminal gate all succeed on green VM.

5. **Rollback drill**
- Repoint `BMT_VM_NAME` to blue and verify one full successful run.

---

## Monitoring and Operational Checks
1. Track per-run:
- VM start-to-ack duration
- ack-to-terminal duration
- dependency sync path taken (fingerprint hit vs reinstall)

2. Add serial log markers:
- `prebake_fingerprint_match=true|false`
- `deps_reinstalled=true|false`
- image version and manifest id

3. Keep ops checks:
- `audit_vm_and_bucket.sh` before and after cutover
- retained snapshot/image count

---

## Explicit Assumptions / Defaults Chosen
1. Both repos continue to share one VM and bucket during this rollout.
2. Runtime code remains GCS-synced at boot (image does not become code source of truth).
3. Blue/green swap is done via `BMT_VM_NAME` repo var change.
4. No default branch policy changes are required for this infrastructure migration.
5. Cloud Build automation is phase 2 (not in first cutover implementation).
