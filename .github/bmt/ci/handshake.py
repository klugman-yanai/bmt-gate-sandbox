"""Handshake: wait for VM ack, timeout diagnostics, force clean VM restart."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Literal

from ci import config, core, gcs
from ci.actions import gh_endgroup, gh_group, gh_notice, write_github_output
from ci.vm import _as_int, _vm_status, vm_describe, vm_serial_tail, vm_start, vm_stop

HandshakeReasonCode = Literal[
    "ok",
    "trigger_missing",
    "vm_not_running",
    "ack_unreadable",
    "ack_not_written",
]


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _compact_error(message: str | None, max_len: int = 180) -> str:
    if not message:
        return ""
    one_line = " ".join(message.strip().split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 3] + "..."


def _sibling_vm_name(name: str) -> str:
    if name.endswith("-blue"):
        return f"{name[:-5]}-green"
    if name.endswith("-green"):
        return f"{name[:-6]}-blue"
    return ""


def _ctx_str(w: Any, attr: str, env_var: str, default: str = "") -> str:
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

    def _instance_name(self) -> str:
        """Concrete VM instance name (e.g. bmt-gate-blue). Prefer BMT_VM_NAME from step env."""
        return (os.environ.get("BMT_VM_NAME") or "").strip() or self._cfg.bmt_vm_name

    def wait(self, timeout_sec: int | None = None) -> None:
        """Wait for VM handshake ack at triggers/acks/<workflow_run_id>.json."""
        self._cfg.require_gcp()
        bucket = self._cfg.gcs_bucket
        run_id = core.require_env("GITHUB_RUN_ID")
        github_output = core.require_env("GITHUB_OUTPUT")
        if timeout_sec is None:
            w = self._ctx.workflow if self._ctx else None
            vm_reused = _ctx_str(w, "vm_reused_running", "VM_REUSED_RUNNING", "false").lower() in (
                "true",
                "1",
                "yes",
            )
            restart_vm = _ctx_str(w, "restart_vm", "RESTART_VM", "false").lower() in (
                "true",
                "1",
                "yes",
            )
            if vm_reused:
                timeout_sec = self._cfg.bmt_handshake_timeout_sec_reuse_running
                gh_notice(f"Handshake branch=reuse-running timeout={timeout_sec}s")
            elif restart_vm:
                stale = _ctx_str(w, "stale_cleanup_count", "STALE_CLEANUP_COUNT", "0")
                timeout_sec = self._cfg.bmt_handshake_timeout_sec + 60
                print(
                    f"::notice::Handshake branch=post-cleanup-restart stale_cleanup_count={stale} timeout={timeout_sec}s"
                )
            else:
                timeout_sec = self._cfg.bmt_handshake_timeout_sec
                gh_notice(f"Handshake branch=standard timeout={timeout_sec}s")

        if not (1 <= timeout_sec <= 3600):
            raise RuntimeError(f"Handshake timeout must be 1-3600s, got {timeout_sec}")
        poll_interval_sec = 5
        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        instance_name = self._instance_name()

        root = core.bucket_root_uri(bucket)
        ack_uri = core.run_handshake_uri(root, run_id)
        trigger_uri = core.run_trigger_uri(root, run_id)
        runtime_status_uri = core.run_status_uri(root, run_id)
        diag_uri = f"{root}/triggers/diagnostics/{run_id}.json"
        recovery_enabled = _is_truthy(os.environ.get("BMT_HANDSHAKE_RECOVERY_RESTART_ON_STALL", "1"))
        recovery_threshold_sec = int(os.environ.get("BMT_HANDSHAKE_RECOVERY_THRESHOLD_SEC", "180"))
        recovery_extension_sec = int(os.environ.get("BMT_HANDSHAKE_RECOVERY_EXTENSION_SEC", "300"))
        recovery_attempted = False
        recovery_switched_vm = ""
        snapshot_interval_sec = int(os.environ.get("BMT_HANDSHAKE_STATUS_SNAPSHOT_SEC", "30"))

        def _record_handshake_failure(
            *,
            reason: HandshakeReasonCode,
            reason_detail: str,
            trigger_exists: bool,
            runtime_status_exists: bool,
            vm_status: str,
            serial_tail: str,
        ) -> str:
            diagnostics_payload = {
                "reason_code": reason,
                "reason_detail": reason_detail,
                "workflow_run_id": run_id,
                "vm_name": instance_name,
                "gcp_project": project,
                "gcp_zone": zone,
                "trigger_uri": trigger_uri,
                "ack_uri": ack_uri,
                "runtime_status_uri": runtime_status_uri,
                "trigger_exists": trigger_exists,
                "runtime_status_exists": runtime_status_exists,
                "vm_status": vm_status,
                "recovery_enabled": recovery_enabled,
                "recovery_attempted": recovery_attempted,
                "recovery_threshold_sec": recovery_threshold_sec,
                "recovery_extension_sec": recovery_extension_sec,
                "recovery_switched_vm": recovery_switched_vm,
                "serial_tail": serial_tail,
            }
            uploaded_diag_uri = ""
            try:
                gcs.upload_json(diag_uri, diagnostics_payload)
                uploaded_diag_uri = diag_uri
            except gcs.GcsError:
                uploaded_diag_uri = ""
            write_github_output(github_output, "handshake_reason_code", reason)
            write_github_output(github_output, "handshake_reason_detail", reason_detail)
            if uploaded_diag_uri:
                write_github_output(github_output, "handshake_diagnostics_uri", uploaded_diag_uri)
            return uploaded_diag_uri

        print(f"Waiting for VM handshake ack at {ack_uri} (timeout={timeout_sec}s)")
        print(f"Trigger file: {trigger_uri}")
        print(
            "Handshake recovery config: "
            f"enabled={recovery_enabled} threshold={recovery_threshold_sec}s "
            f"extension={recovery_extension_sec}s snapshot_interval={snapshot_interval_sec}s"
        )
        if timeout_sec < 300:
            print(
                f"::notice::Handshake timeout={timeout_sec}s; consider BMT_HANDSHAKE_TIMEOUT_SEC=300 for cold-start"
            )

        if not gcs.object_exists(trigger_uri):
            _record_handshake_failure(
                reason="trigger_missing",
                reason_detail="Trigger file missing before handshake wait",
                trigger_exists=False,
                runtime_status_exists=gcs.object_exists(runtime_status_uri),
                vm_status=_vm_status(project, zone, instance_name),
                serial_tail=vm_serial_tail(project, zone, instance_name, lines=40),
            )
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
                if elapsed >= snapshot_interval_sec and int(elapsed) % snapshot_interval_sec < 15:
                    trigger_exists = gcs.object_exists(trigger_uri)
                    runtime_payload, runtime_error = gcs.download_json(runtime_status_uri)
                    runtime_state = (
                        str(runtime_payload.get("state", "")).strip()
                        if isinstance(runtime_payload, dict)
                        else ""
                    )
                    runtime_phase = (
                        str(runtime_payload.get("phase", "")).strip()
                        if isinstance(runtime_payload, dict)
                        else ""
                    )
                    candidate_reason = (
                        "trigger_missing"
                        if not trigger_exists
                        else (
                            "vm_not_running"
                            if last_vm_status != "RUNNING"
                            else ("ack_unreadable" if last_error else "ack_not_written")
                        )
                    )
                    print(
                        "  ... status snapshot: "
                        f"candidate_reason={candidate_reason} "
                        f"trigger_exists={trigger_exists} "
                        f"ack_error={_compact_error(last_error) or '<none>'} "
                        f"runtime_error={_compact_error(runtime_error) or '<none>'} "
                        f"runtime_state={runtime_state or '<none>'} "
                        f"runtime_phase={runtime_phase or '<none>'}"
                    )
                if (
                    recovery_enabled
                    and not recovery_attempted
                    and elapsed >= recovery_threshold_sec
                    and last_vm_status == "RUNNING"
                    and not runtime_exists
                ):
                    print(
                        "::warning::Handshake appears stalled with RUNNING VM and no runtime status; "
                        f"attempting one clean restart of {instance_name}."
                    )
                    try:
                        vm_stop(project, zone, instance_name)
                        vm_start(project, zone, instance_name)
                        recovery_attempted = True
                        deadline = max(deadline, time.monotonic() + recovery_extension_sec)
                        print(
                            f"::notice::Recovery restart submitted; extending handshake wait by "
                            f"{recovery_extension_sec}s."
                        )
                    except core.GcloudError as exc:
                        sibling = _sibling_vm_name(instance_name)
                        if not sibling:
                            recovery_attempted = True
                            print(f"::warning::Recovery restart failed: {exc}")
                        else:
                            print(
                                f"::warning::Recovery restart failed on {instance_name}: {exc}; "
                                f"trying sibling VM {sibling}."
                            )
                            try:
                                sibling_status = _vm_status(project, zone, sibling)
                                if sibling_status != "RUNNING":
                                    vm_start(project, zone, sibling)
                                instance_name = sibling
                                recovery_switched_vm = sibling
                                recovery_attempted = True
                                deadline = max(deadline, time.monotonic() + recovery_extension_sec)
                                print(
                                    f"::notice::Recovery switched to sibling VM {sibling}; extending "
                                    f"handshake wait by {recovery_extension_sec}s."
                                )
                            except core.GcloudError as sibling_exc:
                                recovery_attempted = True
                                print(
                                    "::warning::Sibling failover also failed: "
                                    f"{sibling_exc}"
                                )
                last_full_progress = elapsed
            if remaining > 0:
                time.sleep(min(poll_interval_sec, deadline - time.monotonic()))

        if payload is None:
            last_vm_status = _vm_status(project, zone, instance_name)
            trigger_exists = gcs.object_exists(trigger_uri)
            runtime_exists = gcs.object_exists(runtime_status_uri)
            reason: HandshakeReasonCode = (
                "trigger_missing"
                if not trigger_exists
                else (
                    "vm_not_running"
                    if last_vm_status != "RUNNING"
                    else ("ack_unreadable" if last_error else "ack_not_written")
                )
            )
            serial = vm_serial_tail(project, zone, instance_name, lines=40)
            details = f"; last_error={last_error}" if last_error else ""
            _record_handshake_failure(
                reason=reason,
                reason_detail=last_error or "",
                trigger_exists=trigger_exists,
                runtime_status_exists=runtime_exists,
                vm_status=last_vm_status,
                serial_tail=serial,
            )
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
                requested_legs.append(
                    {
                        "index": idx,
                        "project": str(leg.get("project", "?")),
                        "bmt_id": str(leg.get("bmt_id", "?")),
                        "run_id": str(leg.get("run_id", "?")),
                        "decision": "accepted",
                        "reason": None,
                    }
                )
            for rej in rejected_legs:
                if not isinstance(rej, dict):
                    continue
                requested_legs.append(
                    {
                        "index": _as_int(rej.get("index"), len(requested_legs)),
                        "project": str(rej.get("project", "?")),
                        "bmt_id": str(rej.get("bmt_id", "?")),
                        "run_id": str(rej.get("run_id", "?")),
                        "decision": "rejected",
                        "reason": str(rej.get("reason") or "invalid_leg_type"),
                    }
                )
        support_resolution_version = str(
            payload.get("support_resolution_version")
            or ("v2" if isinstance(requested_legs_raw, list) else "v1")
        )
        run_disposition = str(
            payload.get("run_disposition")
            or ("accepted" if accepted_count > 0 else "accepted_but_empty")
        )

        write_github_output(github_output, "handshake_uri", ack_uri)
        write_github_output(
            github_output, "handshake_payload", json.dumps(payload, separators=(",", ":"))
        )
        write_github_output(github_output, "handshake_requested_leg_count", str(requested_count))
        write_github_output(github_output, "handshake_accepted_leg_count", str(accepted_count))
        write_github_output(
            github_output,
            "handshake_accepted_legs",
            json.dumps(accepted_legs, separators=(",", ":")),
        )
        write_github_output(
            github_output, "handshake_support_resolution_version", support_resolution_version
        )
        write_github_output(
            github_output,
            "handshake_requested_legs",
            json.dumps(requested_legs, separators=(",", ":")),
        )
        write_github_output(
            github_output,
            "handshake_rejected_legs",
            json.dumps(rejected_legs, separators=(",", ":")),
        )
        write_github_output(github_output, "handshake_run_disposition", run_disposition)
        write_github_output(github_output, "handshake_reason_code", "ok")
        elapsed_sec = max(0, int(time.monotonic() - wait_start))
        write_github_output(github_output, "handshake_elapsed_sec", str(elapsed_sec))
        print(
            f"VM handshake received in {elapsed_sec}s: requested={requested_count} accepted={accepted_count} vm_status={last_vm_status}"
        )

    def wait_watcher_ready(self, timeout_sec: int | None = None) -> None:
        """Wait for VM watcher health marker before writing run trigger."""
        self._cfg.require_gcp()
        bucket = self._cfg.gcs_bucket
        github_output = core.require_env("GITHUB_OUTPUT")
        if timeout_sec is None:
            timeout_sec = int(os.environ.get("BMT_WATCHER_READY_TIMEOUT_SEC", "180"))
        if not (1 <= timeout_sec <= 1800):
            raise RuntimeError(f"Watcher-ready timeout must be 1-1800s, got {timeout_sec}")
        freshness_sec = int(os.environ.get("BMT_WATCHER_READY_FRESHNESS_SEC", "300"))
        poll_interval_sec = 5
        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        instance_name = self._instance_name()

        root = core.bucket_root_uri(bucket)
        health_uri = f"{root}/triggers/status/health/{instance_name}.json"
        print(
            f"Waiting for watcher readiness at {health_uri} "
            f"(timeout={timeout_sec}s, freshness={freshness_sec}s)"
        )

        deadline = time.monotonic() + timeout_sec
        wait_start = time.monotonic()
        last_status = "unknown"
        last_detail = ""
        last_age = -1
        while time.monotonic() < deadline:
            elapsed = int(time.monotonic() - wait_start)
            payload, error = gcs.download_json(health_uri)
            vm_status = _vm_status(project, zone, instance_name)
            last_status = vm_status
            if payload is not None:
                stage = str(payload.get("stage", "")).strip()
                detail = str(payload.get("detail", "")).strip()
                updated_at = str(payload.get("updated_at", "")).strip()
                age_sec = -1
                if updated_at:
                    try:
                        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=UTC)
                        age_sec = int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds())
                    except Exception:
                        age_sec = -1
                last_age = age_sec
                last_detail = detail
                fresh_enough = age_sec >= 0 and age_sec <= freshness_sec
                stage_ready = stage in {"watcher_launching", "watcher_running", "runtime_validated"}
                if vm_status == "RUNNING" and fresh_enough and stage_ready:
                    write_github_output(github_output, "watcher_ready_uri", health_uri)
                    write_github_output(github_output, "watcher_ready_stage", stage)
                    write_github_output(github_output, "watcher_ready_age_sec", str(age_sec))
                    print(
                        f"Watcher ready: vm_status={vm_status} stage={stage} age={age_sec}s "
                        f"detail={detail or '<none>'}"
                    )
                    return
                print(
                    f"  ... watcher not ready yet ({elapsed}s): vm_status={vm_status} "
                    f"stage={stage or '<none>'} age={age_sec}s fresh={fresh_enough} "
                    f"detail={detail or '<none>'}"
                )
            else:
                print(
                    f"  ... watcher marker unavailable ({elapsed}s): vm_status={vm_status} "
                    f"error={_compact_error(error) or '<none>'}"
                )
            time.sleep(poll_interval_sec)

        raise RuntimeError(
            "Timed out waiting for watcher readiness: "
            f"uri={health_uri} vm_status={last_status} last_age_sec={last_age} detail={last_detail or '<none>'}"
        )

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
        instance_name = (os.environ.get("BMT_VM_NAME") or "").strip() or cfg.bmt_vm_name
        try:
            payload = vm_describe(cfg.gcp_project, cfg.gcp_zone, instance_name)
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
            serial = vm_serial_tail(cfg.gcp_project, cfg.gcp_zone, instance_name, lines=200)
            for line in serial.splitlines():
                print(line)
        except Exception:
            pass
        gh_endgroup()

    def force_clean_vm_restart(self) -> None:
        """Stop VM and wait for TERMINATED so the next start step gets a clean state."""

        self._cfg.require_gcp()
        ctx = self._ctx
        w = ctx.workflow if ctx else None
        stale_count = _ctx_str(w, "stale_cleanup_count", "STALE_CLEANUP_COUNT", "0")
        print(f"Stale trigger cleanup removed {stale_count} file(s); forcing clean VM restart.")
        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        instance_name = self._instance_name()
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
