# Documentation index

Start here. Full entry: [README](../README.md).

## Start here

| I want to… | Doc |
| ---------- | --- |
| **Test prod CI locally** (real VM/GCS) | [development.md](development.md#testing-production-ci-locally) |
| **Set up config / repo vars** | [configuration.md](configuration.md), [infra/README.md](../infra/README.md) |
| **Understand the pipeline** | [architecture.md](architecture.md), [github-and-ci.md](github-and-ci.md) |
| **Develop and run tests** | [development.md](development.md) |
| **Add a project or BMT** | [adding-a-project.md](adding-a-project.md) |
| **Sandbox vs production** | [sandbox-and-production.md](sandbox-and-production.md) |

## Reference

| Doc | Description |
| --- | --- |
| [architecture.md](architecture.md) | Trigger-and-stop flow, GCS contract, script map, data flow. |
| [configuration.md](configuration.md) | Env contract, repo vars, VM metadata, secrets, bucket layout. |
| [development.md](development.md) | Setup, testing, lint/typecheck, Justfile, deploy. |
| [github-and-ci.md](github-and-ci.md) | Communication flow, GitHub App, Actions/CLI, workflow output. |
| [adding-a-project.md](adding-a-project.md) | Full checklist (bmt-gcloud + app repo) and quick steps (bmt-gcloud only). |
| [debugging-bmt-pipeline.md](debugging-bmt-pipeline.md) | Logs, correlating a run, failure debugging. |
| [preflight-bucket-remote.md](preflight-bucket-remote.md) | Pre-flight: bucket check, diff code/ vs gcp/image. |

## Roadmap and plans

| Location | Description |
| -------- | ----------- |
| [ROADMAP.md](../ROADMAP.md) | Current roadmap index (root). |
| [roadmap/](roadmap/) | Dated implementation plans. |
| [plans/](plans/) | Design and migration plans. |

## Audits

| Doc | Description |
| --- | --- |
| [audits/bmt-config-and-results.md](audits/bmt-config-and-results.md) | BMT config fields, results prefix layout, infra → repo vars. |
| [audits/agent-native-and-complexity-audit.md](audits/agent-native-and-complexity-audit.md) | Agent-native and complexity audit. |
| [audits/agent-native-image-vars-workflow.md](audits/agent-native-image-vars-workflow.md) | Agent-native: image build, variables, workflow. |
| [env-vars-audit.md](env-vars-audit.md) | Env vars: minimal set, by source, drift, override policy. |
