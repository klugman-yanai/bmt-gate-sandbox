# Roadmap

Internal planning scratchpad. Edit as priorities change.

## Now

| Item | Notes |
| --- | --- |
| — | Add rows as needed |

## Next

| Item | Notes |
| --- | --- |
| **bmt-workflow readability** | Map in docs (phase A) before YAML refactor (B–D); details in **Later** |

## Later / backlog

### Simplify `bmt-workflow` (Google Workflows)

**Source:** [`infra/pulumi/workflow.yaml`](infra/pulumi/workflow.yaml) (rendered by [`infra/pulumi/__main__.py`](infra/pulumi/__main__.py)).

**Goals:** (1) Document exact step order in-repo (operators should not rely on the Cloud Console graph). (2) Optional YAML dedupe/clarity **without** behavior change. (3) Regression checks after edits.

**Phases (summary):**

| Phase | Deliverable |
| --- | --- |
| **A — Map** | Extend Mermaid / sequence coverage in [docs/architecture.md](docs/architecture.md) where gaps remain |
| **B — Dedupe** | Subworkflow or shared block for standard/heavy task runner + failure capture |
| **C — Switches** | Readable branching / named defaults where syntax allows |
| **D — Ops** | [docs/runbook.md](docs/runbook.md) — expected skips, “busy graph is normal” |

**Verification:** `pulumi preview` diffs only what you intend; staged runs covering standard-only, heavy-only, both, neither, task failure, pre-coordinator failure.

**Non-goals:** True parallel standard+heavy phases (would change semantics); replacing Workflows.

### Cron sweep for stale pending BMT Gate status

Scheduled Actions job: find PRs whose BMT status stayed pending too long → post terminal error via existing `bmt` timeout helper. **Rare** safety net when GCP never runs (image pull, workflow stuck, etc.).

## References

- [docs/architecture.md](docs/architecture.md) · [docs/runbook.md](docs/runbook.md) · [docs/weak-points-remediation.md](docs/weak-points-remediation.md) · [CONTRIBUTING.md](CONTRIBUTING.md)
- Ephemeral planning notes: create **`docs/plans/`** locally (gitignored); see [README.md](README.md#documentation).
