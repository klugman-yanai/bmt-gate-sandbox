# Documentation index

Start here for structure and day-to-day use. Plans and archived docs are in their own sections.

## Start here

| I want to… | Doc |
| ---------- | --- |
| **Test prod CI locally** with real VM/GCS | [development.md](development.md#testing-production-ci-locally) |
| **Set up config / repo vars** | [configuration.md](configuration.md), [../infra/README.md](../infra/README.md) |
| **Understand the pipeline** (trigger, handoff, results) | [architecture.md](architecture.md), [github-and-ci.md](github-and-ci.md) |
| **Develop and run tests** | [development.md](development.md) |
| **Add a new BMT project** | [adding-a-new-project.md](adding-a-new-project.md) |
| **Keep sandbox and production in sync** | [sandbox-and-production.md](sandbox-and-production.md) |

---

## Active reference

| Doc | Description |
| --- | --- |
| [architecture.md](architecture.md) | Trigger-and-stop flow, GCS contract, script map, production surface, implementation/data flow, repository structure. |
| [configuration.md](configuration.md) | Env contract, repo vars, VM metadata, secrets, bucket layout. |
| [development.md](development.md) | Setup, testing (unit, local BMT, pointer/snapshot, **testing prod CI locally**), lint/typecheck, Justfile, deploy. |
| [adding-a-new-project.md](adding-a-new-project.md) | How to add a new BMT project (e.g. Skyworth): gcp/code layout, manager script, bmt_jobs.json, app-repo matrix and runner upload, .github/bmt. |
| [github-and-ci.md](github-and-ci.md) | Communication flow, GitHub App permissions, Actions/CLI tools, workflow output (intended UX). |

## Sandbox and production

| Doc | Description |
| --- | --- |
| [sandbox-and-production.md](sandbox-and-production.md) | Maintaining sandbox and production, sandbox mirror production, drift (core-main vs bmt-gcloud). |

## Audits / reference

| Doc | Description |
| --- | --- |
| [audits.md](audits.md) | Terraform outputs, BMT config fields, results prefix layout. |

## Plans

Plans under `docs/plans/` (only existing files listed):

| Doc | Description |
| --- | --- |
| [plans/future-architecture.md](plans/future-architecture.md) | Planned changes (SDK, Pydantic, bmt_lib, PR comments). |
| [plans/high-level-design-improvements.md](plans/high-level-design-improvements.md) | Purpose-driven design improvements. |
| [plans/migration-to-production.md](plans/migration-to-production.md) | Enabling BMT in production repo. |
| [plans/2025-03-11-centralized-bmt-config.md](plans/2025-03-11-centralized-bmt-config.md) | Centralized BMT config implementation plan. |
| [plans/2025-03-11-vm-idle-then-terminate-and-reuse-running.md](plans/2025-03-11-vm-idle-then-terminate-and-reuse-running.md) | VM idle-then-terminate and RUNNING reuse. |

## Archive

- **[archive/](archive/)** — Ephemeral or one-off docs (merge strategies, CI branch update notes).
