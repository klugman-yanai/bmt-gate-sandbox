# Documentation index

Start here for structure and day-to-day use. Plans and historical docs live under `plans/` and `archive/`.

## Active reference

| Doc | Description |
|-----|-------------|
| [architecture.md](architecture.md) | Trigger-and-stop flow, GCS contract, script map, production surface. |
| [configuration.md](configuration.md) | Env contract, repo vars, VM metadata, secrets, bucket layout. |
| [development.md](development.md) | Setup, testing, lint/typecheck, Justfile, deploy. |
| [implementation.md](implementation.md) | Data flow, reliability, limitations. |
| [communication-flow.md](communication-flow.md) | Commit status and Check Runs; failure handling. |
| [github-app-permissions.md](github-app-permissions.md) | GitHub App permissions and how to check them. |
| [github-actions-and-cli-tools.md](github-actions-and-cli-tools.md) | Actions summaries, re-run, debug; `gh` CLI; retention policy. |
| [testing-production-ci-locally.md](testing-production-ci-locally.md) | Canonical how-to: test prod CI locally with real VM/GCS. |
| [repository-structure-and-design.md](repository-structure-and-design.md) | Repo layout: `.github/bmt`, `deploy/`, `config/`, `tools/`. |

## Sandbox and production

| Doc | Description |
|-----|-------------|
| [maintaining-sandbox-and-production.md](maintaining-sandbox-and-production.md) | Keeping sandbox and production in sync. |
| [sandbox-mirror-production.md](sandbox-mirror-production.md) | How the sandbox workflow mirrors production. |
| [drift-core-main-vs-bmt-gcloud.md](drift-core-main-vs-bmt-gcloud.md) | Drift between core-main and this repo; `just diff-core-main`. |

## Plans

| Doc | Description |
|-----|-------------|
| [plans/PLAN.md](plans/PLAN.md) | Hard cutover: remove `BMT_BUCKET_PREFIX` end-to-end. |
| [plans/future-architecture.md](plans/future-architecture.md) | Planned changes (SDK, Pydantic, bmt_lib, PR comments). |
| [plans/high-level-design-improvements.md](plans/high-level-design-improvements.md) | Purpose-driven design improvements. |
| [plans/migration-to-production.md](plans/migration-to-production.md) | Enabling BMT in production repo. |
| [plans/bmt-support-plan.md](plans/bmt-support-plan.md) | VM-decides runtime support; handshake contract. |
| [plans/admin-repo-vs-production-standard-practice.md](plans/admin-repo-vs-production-standard-practice.md) | Canonical repo + sync approach; core-main constraint. |

**Audit reports:** [plans/structure-audit-202603.md](plans/structure-audit-202603.md) — Structure and bloat audit (root, docs, tools, deploy bootstrap). [plans/archive/trim-the-fat-report.md](plans/archive/trim-the-fat-report.md) — Earlier trim-the-fat audit.

## Archive

- **plans/archive/** — Completed or superseded plans (e.g. trim-the-fat-report, cursor plans).
- **archive/** — Other archived artifacts (e.g. original_build-and-test.yml reference copy).
