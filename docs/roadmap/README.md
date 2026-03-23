# Roadmap

Implementation and design plans. Root [ROADMAP.md](../../ROADMAP.md) links here.

## Active Plans (ordered by urgency)

| # | File | Focus | Urgency |
|---|------|-------|---------|
| 1 | [gcp-data-separation-and-dev-workflow.md](gcp-data-separation-and-dev-workflow.md) | Bug fixes, manifest-based dataset visibility, FUSE mounts, WorkspaceLayout, gcp/remote rename | **MOST URGENT** |
| 2 | [gcp-image-refactor.md](gcp-image-refactor.md) | Constants, enums, value classes, config-driven entrypoint, structural decoupling (Phases 1-3) | **HIGH** |
| 3 | [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) | BmtManagerProtocol, BaseBmtManager, contributor workflow, artifact contract, reference examples | **HIGH** |
| 4 | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | Dockerfile, Cloud Run Job + GCS Fuse (Pulumi), scalability, coordinator model (Phases 4-6) | MEDIUM |
| 5 | [ci-cutover-and-vm-decommission.md](ci-cutover-and-vm-decommission.md) | Direct API handoff, shadow testing, cutover, rollback drill, VM decommission (Phases 7-8) | LOWER |

**Dependency chain:** 1 → 2+3 → 4 → 5

## Archived

Superseded plans moved to [../archive/](../archive/).
