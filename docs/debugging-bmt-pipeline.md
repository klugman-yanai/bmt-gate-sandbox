# Debugging the BMT pipeline

How to find logs and diagnose failures for the vm_watcher / root_orchestrator pipeline.

## Where logs live

- **On the VM:** Rotating log files under `workspace_root/logs/`:
  - `vm_watcher.log` — trigger polling, run processing, status/check posting
  - `root_orchestrator.log` — per-leg orchestration and manager invocation
- **Stdout:** When the watcher is run via the startup script, the same logs are also emitted to stdout so the Ops Agent can send them to Cloud Logging (if configured).
- **Cloud Logging:** Configure the [Ops Agent](https://cloud.google.com/logging/docs/agent/ops-agent/configuration) with a `files` receiver for `workspace_root/logs/vm_watcher.log` and `workspace_root/logs/root_orchestrator.log`, and attach to the default pipeline. No JSON formatter is required; the agent can tail the existing format.

## Correlating a run

- **workflow_run_id** — GitHub Actions run ID; appears in log messages, GCS trigger/ack/status paths, and commit status.
- **run_id** — BMT run identifier from the trigger; appears in GCS snapshots and status files.
- **Commit SHA** — In log lines and in GCS trigger payload; use it to match a PR or branch.

Filter Cloud Logging (or grep the log files) by `workflow_run_id` or `run_id` to see everything for one run.

## Where to look when something fails

1. **GitHub commit status and Check Run** — First place to check. The BMT Gate status and Checks tab show pass/fail, per-leg reasons, and (on failure) a **log dump** link when the VM uploaded one (e.g. on unhandled exception or when kardome_runner failed). The link is a signed URL and expires in 3 days.
2. **Cloud Logging** — If the VM is configured to send logs to Cloud Logging, filter by `workflow_run_id` or `run_id` and severity to see watcher and orchestrator messages.
3. **GCS `log-dumps/`** — If a dump was requested or uploaded on crash, the object lives under `gs://<bucket>/<runtime_prefix>/log-dumps/`. The Check Run or PR comment will include a signed URL to download it.

## How to request a log dump

When the VM is running (or will be on the next poll), you can request a one-off log dump:

1. Upload a JSON object to `gs://<bucket>/<runtime_prefix>/log-dump-requests/<request_id>.json` with at least:
   - `request_id` or `requested_at`: an identifier (e.g. UUID or timestamp).
2. The VM lists that prefix each poll; when it sees a request, it builds a tail of watcher + orchestrator logs, uploads to `log-dumps/<request_id>.log`, generates a signed URL, and writes a **response object** to `log-dump-requests/<request_id>.response.json` with `signed_url` and `expires_in_days` (3). It then deletes the request file.
3. Read the response object to get the download link. The VM does **not** post this link to the PR or Check Run; it is for on-demand debugging only.

The VM stays idle for a period after each run (`IDLE_TIMEOUT_SEC`, default 600s) so consecutive workflow runs avoid cold starts and so log-dump requests can be processed on the next poll.

## Idle timeout

`bmt_config.IDLE_TIMEOUT_SEC` (default 600) controls how long the VM waits after each run with no new trigger before exiting (when `--exit-after-run` is used). This keeps the VM warm for follow-up triggers and for processing log-dump requests. See [architecture.md](architecture.md) and the startup script for how the watcher is invoked.
