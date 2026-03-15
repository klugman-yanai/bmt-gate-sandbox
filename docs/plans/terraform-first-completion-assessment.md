# Terraform-first setup: completion assessment

**Date:** 2026-03-15  
**Plan reference:** [.cursor/plans/terraform_vm_migration_plan_0c69b647.plan.md](../.cursor/plans/terraform_vm_migration_plan_0c69b647.plan.md)

## Verdict: **docs complete; ops pending**

The **code and workflow** for a Terraform-first BMT VM are in place. **Documentation** tasks (3.4, 4.1, 4.2, 5.2, 5.3) and the infra/README path fix are implemented. **Operational steps** (Phases 1–3) must still be run in a real project to reach fully complete.

---

## What is complete (in repo)

| Item | Status | Notes |
|------|--------|------|
| **Terraform** | Done | [infra/terraform/main.tf](infra/terraform/main.tf): `google_compute_instance.bmt_vm`, `desired_status = "TERMINATED"`, lifecycle prevent_destroy, Pub/Sub topic/subscription, outputs including `bmt_vm_name`. |
| **Provision workflow** | Done | [.github/workflows/bmt-vm-provision.yml](.github/workflows/bmt-vm-provision.yml): separate plan vs plan-destroy; apply uses `tfplan`; destroy step runs `terraform apply -auto-approve tfplan` (correct for destroy plan). Concurrency `terraform-apply-${{ inputs.bmt_vm_name }}`. Post-apply updates `BMT_LIVE_VM` repo variable. |
| **Export script** | Done | [tools/terraform/terraform_repo_vars.py](tools/terraform/terraform_repo_vars.py); `just terraform-export-vars` / `just terraform-export-vars-apply`. |
| **Handoff** | Done | Handoff workflow reads `vars.BMT_LIVE_VM` (and pool/label); select-available-vm, start-vm, sync-vm-metadata use it. |
| **Task 5.1 (legacy image script)** | Done | [infra/scripts/build_bmt_image.py](infra/scripts/build_bmt_image.py) has legacy comment; [gcp/image/scripts/README.md](gcp/image/scripts/README.md) points to infra and says “legacy; prefer Packer”. |

---

## What is not complete

### Operational (Phases 1–3) — require real GCP/GitHub

These cannot be “done” from the repo alone; someone must run them in the target project and repo:

- **Phase 1:** Terraform backend init, confirm Packer image exists, `terraform plan` / `apply`, record VM name, list console VMs to retire.
- **Phase 2:** `just terraform`, optional pool/label vars, `just validate`, confirm sync-vm-metadata.
- **Phase 3:** `just deploy`, trigger BMT handoff and confirm Terraform VM is used, delete console-created VM(s), document that production uses Terraform VM(s).

### Documentation (plan Tasks 3.4, 4.1, 4.2, 5.2, 5.3) — done

| Task | Required change | Current state |
|------|-----------------|---------------|
| **3.4** | Document “BMT uses Terraform-managed VM(s); BMT_LIVE_VM from Terraform or bmt-vm-provision”. | [docs/development.md](docs/development.md) mentions Terraform-exported vars but does not state that the BMT VM is Terraform-managed or that console VMs are retired. |
| **4.1** | One sentence: Terraform-managed VM is **blue**; when using `create_bmt_green_vm.py`, set `BMT_LIVE_VM` to that VM. | [gcp/image/scripts/README.md](gcp/image/scripts/README.md) has table rows for create_bmt_green_vm / cutover / rollback but no “Terraform VM = blue” sentence. |
| **4.2** | Short section: Blue = Terraform VM, Green = create_bmt_green_vm.py, Cutover = cutover_bmt_vm.py, Rollback = rollback_bmt_vm.py. | No dedicated blue/green section in README or [docs/architecture.md](docs/architecture.md). |
| **5.2** | development.md + CLAUDE.md: state that BMT VM is Terraform-managed and console-created VMs are not required; reference `just terraform-export-vars-apply` and bmt-vm-provision. | CLAUDE.md and development.md describe Terraform export and vars but do not explicitly say “BMT VM is Terraform-managed” or “no console requirement”. |
| **5.3** | infra/README.md: add “VM lifecycle” paragraph (Terraform creates VM from Packer image; run terraform-export-vars-apply so CI uses it; blue/green via create_bmt_green_vm + cutover/rollback). | [infra/README.md](infra/README.md) has Flow 1–2–3 and “Infra-derived vars” but no VM lifecycle paragraph. |

### Small doc fix — done

- [infra/README.md](infra/README.md) Flow step 3 and Bootstrap step 2 now use `uv run python -m tools.terraform.terraform_repo_vars` and `just terraform-export-vars-apply`.

---

## Checklist to reach “fully complete”

1. **Run Phases 1–3** in the target project (init, apply, export vars, validate handoff, retire console VMs). Execute them per the migration plan: [.cursor/plans/terraform_vm_migration_plan_0c69b647.plan.md](../.cursor/plans/terraform_vm_migration_plan_0c69b647.plan.md) (Phase 1 – Prerequisites, Phase 2 – Point CI at Terraform VM, Phase 3 – Validate and retire console VMs).
2. **Implement doc tasks:** 3.4, 4.1, 4.2, 5.2, 5.3 (and fix infra/README export script path). *(Done as of this implementation.)*
3. **Optionally** mark plan frontmatter todos as completed for finished tasks (e.g. 1.6, 5.1).

After (1) and (2), the Terraform-first setup is fully complete in both behavior and documentation.
