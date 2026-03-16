# Roadmap

Planned work and implementation plans. Full files live in [docs/roadmap/](docs/roadmap/).

## Current

| Plan | Description |
|------|-------------|
| [gcp-data-separation-and-dev-workflow](docs/roadmap/gcp-data-separation-and-dev-workflow.md) | Bug fixes blocking dev, manifest-based dataset visibility, WorkspaceLayout. **Most urgent.** |
| [gcp-image-refactor](docs/roadmap/gcp-image-refactor.md) | Constants, types, config-driven entrypoint, structural decoupling. |
| [contributor-api-and-manager-contract](docs/roadmap/contributor-api-and-manager-contract.md) | Protocol, BaseBmtManager, contributor workflow, artifact contract. |
| [cloud-run-containerization-and-infra](docs/roadmap/cloud-run-containerization-and-infra.md) | Dockerfile, Cloud Run Job + GCS Fuse, Pulumi, coordinator model. |
| [ci-cutover-and-vm-decommission](docs/roadmap/ci-cutover-and-vm-decommission.md) | Direct API handoff, shadow testing, cutover, VM decommission. |

**Dependency chain:** 1 → 2+3 → 4 → 5. See [docs/roadmap/](docs/roadmap/) for urgency ranking.

## Index

See [docs/roadmap/](docs/roadmap/) for active plans. Older design notes in [docs/plans/](docs/plans/). Archived plans in [docs/archive/](docs/archive/).
