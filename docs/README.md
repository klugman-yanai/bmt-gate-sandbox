# Documentation index

Start here for structure and day-to-day use.

## Start here

| I want to… | Doc |
| ---------- | --- |
| **Test prod CI locally** with real VM/GCS | [development.md](development.md#testing-production-ci-locally) |
| **Set up config / repo vars** | [configuration.md](configuration.md), [../infra/README.md](../infra/README.md) |
| **Understand the pipeline** (trigger, handoff, results) | [architecture.md](architecture.md), [github-and-ci.md](github-and-ci.md) |
| **Develop and run tests** | [development.md](development.md) |
| **Add a new BMT project** (full: bmt-gcloud + app repo) | [adding-a-new-project.md](adding-a-new-project.md) |
| **Add project / BMT data / manager / JSONs** (quick steps, bmt-gcloud only) | [adding-new-project-and-bmt.md](adding-new-project-and-bmt.md) |
| **Keep sandbox and production in sync** | [sandbox-and-production.md](sandbox-and-production.md) |

---

## Active reference

| Doc | Description |
| --- | --- |
| [architecture.md](architecture.md) | Trigger-and-stop flow, GCS contract, script map, production surface, implementation/data flow, repository structure. |
| [configuration.md](configuration.md) | Env contract, repo vars, VM metadata, secrets, bucket layout. |
| [development.md](development.md) | Setup, testing (unit, local BMT, pointer/snapshot, **testing prod CI locally**), lint/typecheck, Justfile, deploy. |
| [adding-a-new-project.md](adding-a-new-project.md) | How to add a new BMT project (e.g. Skyworth): gcp/image layout, manager script, bmt_jobs.json, app-repo matrix and runner upload, .github/bmt. |
| [adding-new-project-and-bmt.md](adding-new-project-and-bmt.md) | Concise steps: new project (scaffold, bmt_jobs), new BMT .wav data (upload), new manager logic (base class), JSON config. |
| [github-and-ci.md](github-and-ci.md) | Communication flow, GitHub App permissions, Actions/CLI tools, workflow output (intended UX). |
| [preflight-bucket-remote.md](preflight-bucket-remote.md) | Before making gcp/remote a mount: check bucket contents, diff code/ vs gcp/image, and next steps for wipe/mount. |

## Sandbox and production

| Doc | Description |
| --- | --- |
| [sandbox-and-production.md](sandbox-and-production.md) | Maintaining sandbox and production, sandbox mirror production, drift (core-main vs bmt-gcloud). |

## Audits / reference

| Doc | Description |
| --- | --- |
| [audits.md](audits.md) | Terraform outputs, BMT config fields, results prefix layout. |
| [env-vars-audit.md](env-vars-audit.md) | All env vars: which are needed, which are auto-managed, which cause drift; minimal user surface. |

## Plans

See [docs/plans/](plans/) for architecture, migration, and design plans. Dated filenames reflect when they were written.

## Archive

- **[archive/](archive/)** — Ephemeral or one-off docs (merge strategies, CI branch update notes).
