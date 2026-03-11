# BMT workflow output

## Setup

Workflow triggers and hands off to the BMT runtime in GCP; the VM runs the benchmarks.

- **Setup** — Select VM, preflight, sync metadata, start VM. Prepare matrix and run context.
- **Upload** — Upload runner binaries to GCS per project.
- **Handshake** — Write trigger, wait for VM confimation.
- **Handoff** — Links to checks tab and comment below and other cleanup.

---

## Handshake

| Project | BMT                 | Requested | Accepted |
| ------- | ------------------- | --------- | -------- |
| sk      | false_reject_namuh  | ✓         | ✓        |
| …       | …                   | …         | …        |

---

## Handoff — where to go next

- **Now** — Workflow posted a PR comment: status + links to [PR](https://github.com/<owner>/<repo>/pull/<pr_number>), [workflow run](https://github.com/<owner>/<repo>/actions/runs/<run_id>), and [Checks tab](https://github.com/<owner>/<repo>/pull/<pr_number>/checks).
- **Later** — BMT VM posts another PR comment: pass/fail, scores, logs.
- **Final** — BMT Gate status in branch protection must pass to merge.
