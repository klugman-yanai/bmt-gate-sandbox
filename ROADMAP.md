# Roadmap

Scaffold for **internal** planning. Edit this file as priorities change; delete placeholder rows you do not need.

## Now

| Item | Notes |
| ---- | ----- |
| _— add rows as needed —_ | |

## Next

| Item | Notes |
| ---- | ----- |
| _— add rows as needed —_ | |

## Later / backlog

- **Cron sweep for stale pending BMT Gate status.**

  **What it does:** A scheduled GitHub Actions workflow that runs on a cron (e.g. every 15 minutes). It lists open PRs, checks each head SHA for a "BMT Gate" commit status or Check Run that has been stuck on pending / in-progress longer than a staleness threshold (e.g. 45 minutes — well beyond any normal BMT run), and posts a terminal `error` commit status so the PR is unblocked. Uses the existing `bmt handoff post-timeout-status` CLI command, which already checks whether the status is already terminal before posting (idempotent, safe under concurrent runs). Runs entirely on GitHub Actions with `GITHUB_TOKEN` — no GCP credentials needed.

  **When it is needed:** Only when the entire Google Cloud side fails to run any code at all — meaning no Python ever executes to post a terminal status. Examples: Cloud Run image pull failure (bad digest, deleted tag, registry outage), Google Workflows execution silently dropped or stuck, GCP-wide service disruption, or the Workflow exception handler's `finalize-failure` job itself crashing before it can report back. All cases where Cloud Run code *does* run (including crashes mid-execution) are already handled by the coordinator's finally block, `publish_github_failure` retry logic, and the Workflow exception handler.

  **Expected frequency:** Rare. This is a last-resort safety net, not a routine mechanism. It would fire only during GCP infrastructure incidents or after a bad image deploy that breaks container startup. In normal operation it should find nothing to do. The cost is minimal (one lightweight Actions runner every 15 minutes scanning the GitHub API) and the benefit is avoiding a PR blocked indefinitely with no way to recover short of manual intervention.

## References (stable docs)

- [docs/architecture.md](docs/architecture.md) — Pipeline, diagrams, maintainer deep dive (weak points, remediation ideas).
- [docs/runbook.md](docs/runbook.md) — Production debugging.
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contributor workflow.

**History:** Older roadmap and plan write-ups were removed from the tree; use **git history** if you need retired markdown.
