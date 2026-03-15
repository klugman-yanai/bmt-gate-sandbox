"""Handshake: wait for VM ack, timeout diagnostics, force clean VM restart."""

from __future__ import annotations

import json
import time
from typing import Any

from ci import config, core, gcs
from ci.actions import gh_group, gh_notice, gh_endgroup, write_github_output
from ci.vm import vm_describe, vm_stop, _vm_status, vm_serial_tail, _as_int


def _ctx_str(w: Any, attr: str, env_var: str, default: str = "") -> str:
    import os

    if w is not None:
        return (getattr(w, attr, None) or default).strip()
    return (os.environ.get(env_var) or default).strip()


class HandshakeManager:
    def __init__(self, cfg: Any, ctx: Any) -> None:
        self._cfg = cfg
        self._ctx = ctx

    @classmethod
    def from_env(cls) -> HandshakeManager:
        return cls(config.get_config(), config.get_context())

    def wait(self, timeout_sec: int | None = None) -> None:
        """Wait for VM handshake ack at triggers/acks/<workflow_run_id>.json."""
        self._cfg.require_gcp()
        bucket = self._cfg.gcs_bucket
        run_id = core.require_env("GITHUB_RUN_ID")
        github_output = core.require_env("GITHUB_OUTPUT")
        if timeout_sec is None:
            w = self._ctx.workflow if self._ctx else None
            vm_reused = _ctx_str(w, "vm_reused_running", "VM_REUSED_RUNNING", "false").lower() in ("true", "1", "yes")
            restart_vm = _ctx_str(w, "restart_vm", "RESTART_VM", "false").lower() in ("true", "1", "yes")
            if vm_reused:
                timeout_sec = self._cfg.bmt_handshake_timeout_sec_reuse_running
                gh_notice(f"Handshake branch=reuse-running timeout={timeout_sec}s")
            elif restart_vm:
                stale = _ctx_str(w, "stale_cleanup_count", "STALE_CLEANUP_COUNT", "0")
                timeout_sec = self._cfg.bmt_handshake_timeout_sec + 60
                print(f"::notice::Handshake branch=post-cleanup-restart stale_cleanup_count={stale} timeout={timeout_sec}s")
            else:
                timeout_sec = self._cfg.bmt_handshake_timeout_sec
                gh_notice(f"Handshake branch=standard timeout={timeout_sec}s")

        if not (1 <= timeout_sec <= 3600):
            raise RuntimeError(f"Handshake timeout must be 1-3600s, got {timeout_sec}")
        poll_interval_sec = 5
        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        instance_name = self._cfg.bmt_vm_name

        root = core.bucket_root_uri(bucket)
        ack_uri = core.run_handshake_uri(root, run_id)
        trigger_uri = core.run_trigger_uri(root, run_id)
        runtime_status_uri = core.run_status_uri(root, run_id)

        print(f"Waiting for VM handshake ack at {ack_uri} (timeout={timeout_sec}s)")
        print(f"Trigger file: {trigger_uri}")
        if timeout_sec < 300:
            print(f"::notice::Handshake timeout={timeout_sec}s; consider BMT_HANDSHAKE_TIMEOUT_SEC=300 for cold-start")

        if not gcs.object_exists(trigger_uri):
            raise RuntimeError(f"Trigger file missing before handshake wait: {trigger_uri}")

        deadline = time.monotonic() + timeout_sec
        wait_start = time.monotonic()
        payload: dict[str, Any] | None = None
        last_error: str | None = None
        last_progress = 0.0
        last_full_progress = 0.0
        last_vm_status = _vm_status(project, zone, instance_name)

        while time.monotonic() < deadline:
            elapsed = time.monotonic() - wait_start
            payload, error = gcs.download_json(ack_uri)
            if payload is not None:
                break
            last_error = error
            remaining = max(0, int(deadline - time.monotonic()))
            if elapsed - last_progress >= poll_interval_sec:
                print(f"  ... waiting {int(elapsed)}s / {timeout_sec}s (remaining ~{remaining}s)")
                last_progress = elapsed
            if elapsed - last_full_progress >= 15:
                last_vm_status = _vm_status(project, zone, instance_name)
                runtime_exists = gcs.object_exists(runtime_status_uri)
                print(
                    f"  ... waiting {int(elapsed)}s / {timeout_sec}s "
                    f"vm_status={last_vm_status} runtime_status_exists={runtime_exists}"
                )
                last_full_progress = elapsed
            if remaining > 0:
                time.sleep(min(poll_interval_sec, deadline - time.monotonic()))

        if payload is None:
            last_vm_status = _vm_status(project, zone, instance_name)
            trigger_exists = gcs.object_exists(trigger_uri)
            runtime_exists = gcs.object_exists(runtime_status_uri)
            reason = "trigger_missing" if not trigger_exists else ("vm_not_running" if last_vm_status != "RUNNING" else ("ack_unreadable" if last_error else "ack_not_written"))
            serial = vm_serial_tail(project, zone, instance_name, lines=40)
            details = f"; last_error={last_error}" if last_error else ""
            raise RuntimeError(
                f"Timed out waiting for VM handshake at {ack_uri}{details}; "
                f"reason={reason}; vm_status={last_vm_status}; trigger_exists={trigger_exists}; "
                f"runtime_status_exists={runtime_exists}\n--- serial tail ---\n{serial}"
            )

        accepted_legs = payload.get("accepted_legs", []) or []
        rejected_legs = payload.get("rejected_legs", []) or []
        requested_legs_raw = payload.get("requested_legs")
        requested_count = _as_int(
            payload.get("requested_leg_count"),
            len(requested_legs_raw) if isinstance(requested_legs_raw, list) else len(accepted_legs),
        )
        accepted_count = _as_int(payload.get("accepted_leg_count"), len(accepted_legs))
        requested_legs: list[dict[str, Any]]
        if isinstance(requested_legs_raw, list):
            requested_legs = [e for e in requested_legs_raw if isinstance(e, dict)]
        else:
            requested_legs = []
            for idx, leg in enumerate(accepted_legs):
                if not isinstance(leg, dict):
                    continue
                requested_legs.append({
                    "index": idx, "project": str(leg.get("project", "?")),
                    "bmt_id": str(leg.get("bmt_id", "?")), "run_id": str(leg.get("run_id", "?")),
                    "decision": "accepted", "reason": None,
                })
            for rej in rejected_legs:
                if not isinstance(rej, dict):
                    continue
                requested_legs.append({
                    "index": _as_int(rej.get("index"), len(requested_legs)),
                    "project": str(rej.get("project", "?")), "bmt_id": str(rej.get("bmt_id", "?")),
                    "run_id": str(rej.get("run_id", "?")), "decision": "rejected",
                    "reason": str(rej.get("reason") or "invalid_leg_type"),
                })
        support_resolution_version = str(
            payload.get("support_resolution_version") or ("v2" if isinstance(requested_legs_raw, list) else "v1")
        )
        run_disposition = str(
            payload.get("run_disposition") or ("accepted" if accepted_count > 0 else "accepted_but_empty")
        )

        write_github_output(github_output, "handshake_uri", ack_uri)
        write_github_output(github_output, "handshake_payload", json.dumps(payload, separators=(",", ":")))
        write_github_output(github_output, "handshake_requested_leg_count", str(requested_count))
        write_github_output(github_output, "handshake_accepted_leg_count", str(accepted_count))
        write_github_output(github_output, "handshake_accepted_legs", json.dumps(accepted_legs, separators=(",", ":")))
        write_github_output(github_output, "handshake_support_resolution_version", support_resolution_version)
        write_github_output(github_output, "handshake_requested_legs", json.dumps(requested_legs, separators=(",", ":")))
        write_github_output(github_output, "handshake_rejected_legs", json.dumps(rejected_legs, separators=(",", ":")))
        write_github_output(github_output, "handshake_run_disposition", run_disposition)
        elapsed_sec = max(0, int(time.monotonic() - wait_start))
        write_github_output(github_output, "handshake_elapsed_sec", str(elapsed_sec))
        print(f"VM handshake received in {elapsed_sec}s: requested={requested_count} accepted={accepted_count} vm_status={last_vm_status}")

    def timeout_diagnostics(self) -> None:
        """Print GCS trigger/ack and VM diagnostics for handshake timeout debugging."""
        run_id = core.workflow_run_id()
        root = core.workflow_runtime_root()
        trigger_uri = f"{root}/triggers/runs/{run_id}.json"
        ack_uri = f"{root}/triggers/acks/{run_id}.json"
        cfg = self._cfg
        gh_group("GCS trigger/ack diagnostics")
        print(f"Trigger URI: {trigger_uri}")
        print(f"Ack URI: {ack_uri}")
        for uri in (trigger_uri, ack_uri):
            try:
                raw = gcs.read_object(uri)
                text = raw.decode("utf-8", errors="replace")
                for line in text.splitlines()[:120]:
                    print(line)
            except gcs.GcsError:
                pass
        gh_endgroup()
        gh_group("VM instance diagnostics")
        try:
            payload = vm_describe(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name)
            for k in ("name", "status", "lastStartTimestamp", "lastStopTimestamp"):
                print(f"{k}: {payload.get(k)}")
            items = (payload.get("metadata") or {}).get("items") or []
            for item in items:
                if isinstance(item, dict):
                    print(f"  {item.get('key')}: {item.get('value')}")
        except core.GcloudError:
            pass
        gh_endgroup()
        gh_group("VM serial output tail")
        try:
            serial = vm_serial_tail(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name, lines=200)
            for line in serial.splitlines():
                print(line)
        except Exception:
            pass
        gh_endgroup()

    def force_clean_vm_restart(self) -> None:
        """Stop VM and wait for TERMINATED so the next start step gets a clean state."""
        import os

        self._cfg.require_gcp()
        ctx = self._ctx
        w = ctx.workflow if ctx else None
        stale_count = _ctx_str(w, "stale_cleanup_count", "STALE_CLEANUP_COUNT", "0")
        print(f"Stale trigger cleanup removed {stale_count} file(s); forcing clean VM restart.")
        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        instance_name = self._cfg.bmt_vm_name
        try:
            payload = vm_describe(project, zone, instance_name)
            status_before = str(payload.get("status", "UNKNOWN"))
        except core.GcloudError:
            status_before = "UNKNOWN"
        print(f"VM status before restart action: {status_before}")
        if status_before != "TERMINATED":
            try:
                vm_stop(project, zone, instance_name)
            except core.GcloudError as exc:
                from ci.actions import gh_warning

                gh_warning(f"VM stop command failed: {exc}; will continue polling for TERMINATED.")
        for _ in range(24):
            try:
                payload = vm_describe(project, zone, instance_name)
                status_now = str(payload.get("status", "UNKNOWN"))
            except core.GcloudError:
                status_now = "UNKNOWN"
            if status_now == "TERMINATED":
                print("VM reached TERMINATED; proceeding with normal start step.")
                return
            time.sleep(5)
        raise RuntimeError("VM did not reach TERMINATED before restart sequence.")
