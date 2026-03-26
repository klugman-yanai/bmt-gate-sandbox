"""VM lifecycle: Compute SDK helpers and VmManager (select, start, sync_metadata)."""

from __future__ import annotations

import os
import tempfile
import time
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

from backend.config.bmt_config import (
    VM_RECOVERY_START_DELAY_SEC,
    VM_STABILIZATION_SEC,
    VM_START_RECOVERY_ATTEMPTS,
    VM_START_TIMEOUT_SEC,
    VM_STOP_WAIT_TIMEOUT_SEC,
)

from ci import config, core, gcs
from ci.actions import gh_error, gh_notice, gh_warning, write_github_output

_VM_STOPPING_WAIT_SEC = 120

_compute_client: Any = None


def _get_compute_client() -> Any:
    global _compute_client
    if _compute_client is None:
        from google.cloud import compute_v1

        _compute_client = compute_v1.InstancesClient()
    return _compute_client


def vm_start(project: str, zone: str, instance_name: str) -> None:
    try:
        op = _get_compute_client().start(project=project, zone=zone, instance=instance_name)
        op.result()
    except Exception as exc:
        raise core.GcloudError(f"Failed to start VM {instance_name}: {exc}") from exc


def vm_stop(project: str, zone: str, instance_name: str) -> None:
    try:
        op = _get_compute_client().stop(project=project, zone=zone, instance=instance_name)
        op.result()
    except Exception as exc:
        raise core.GcloudError(f"Failed to stop VM {instance_name}: {exc}") from exc


def vm_describe(project: str, zone: str, instance_name: str) -> dict[str, Any]:
    try:
        from google.cloud.compute_v1.types import Instance
        from google.protobuf.json_format import MessageToDict

        instance: Instance = _get_compute_client().get(
            project=project, zone=zone, instance=instance_name
        )
        return MessageToDict(instance._pb, preserving_proto_field_name=True)
    except Exception as exc:
        raise core.GcloudError(f"Failed to describe VM {instance_name}: {exc}") from exc


def vm_list_names(project: str, zone: str, *, filter_expr: str | None = None) -> list[str]:
    try:
        client = _get_compute_client()
        if filter_expr:
            from google.cloud.compute_v1.types import ListInstancesRequest

            request = ListInstancesRequest(project=project, zone=zone, filter=filter_expr)
            it = client.list(request=request)
        else:
            it = client.list(project=project, zone=zone)
        return [inst.name for inst in it if getattr(inst, "name", None)]
    except Exception as exc:
        raise core.GcloudError(f"Failed to list instances in {project}/{zone}: {exc}") from exc


def vm_serial_output(project: str, zone: str, instance_name: str) -> str:
    try:
        resp = _get_compute_client().get_serial_port_output(
            project=project, zone=zone, instance=instance_name
        )
        return resp.contents or ""
    except Exception as exc:
        raise core.GcloudError(f"Failed to get serial output for {instance_name}: {exc}") from exc


def vm_serial_output_retry(
    project: str, zone: str, instance_name: str, *, attempts: int = 4, base_delay_sec: float = 2.0
) -> str:
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            return vm_serial_output(project, zone, instance_name)
        except core.GcloudError as exc:
            last_error = str(exc)
            if attempt >= attempts:
                break
            time.sleep(base_delay_sec * (2 ** (attempt - 1)))
    raise core.GcloudError(last_error or f"Failed to get serial output for {instance_name}")


def vm_add_metadata(
    project: str,
    zone: str,
    instance_name: str,
    metadata: dict[str, str],
    *,
    metadata_files: dict[str, Path] | None = None,
) -> None:
    if not metadata and not metadata_files:
        raise core.GcloudError(f"No metadata provided for {instance_name}")
    try:
        from google.cloud.compute_v1.types import Items, Metadata

        instance = _get_compute_client().get(
            project=project, zone=zone, instance=instance_name
        )
        existing = {}
        fingerprint = ""
        if instance.metadata:
            fingerprint = instance.metadata.fingerprint or ""
            for item in instance.metadata.items_:
                existing[item.key] = item.value
        existing.update(metadata)
        if metadata_files:
            for key, path in metadata_files.items():
                existing[key] = Path(path).read_text(encoding="utf-8")
        items = [Items(key=k, value=v) for k, v in existing.items()]
        meta = Metadata(items=items, fingerprint=fingerprint)
        op = _get_compute_client().set_metadata(
            project=project,
            zone=zone,
            instance=instance_name,
            metadata_resource=meta,
        )
        op.result()
    except core.GcloudError:
        raise
    except Exception as exc:
        raise core.GcloudError(f"Failed to update VM metadata for {instance_name}: {exc}") from exc


def _instance_status(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    return str(status).strip() if status is not None else ""


def _last_start_timestamp(payload: dict[str, Any]) -> str | None:
    raw = payload.get("lastStartTimestamp")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _metadata_items(payload: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return out
    items = metadata.get("items")
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


def _is_truthy(raw: str | None) -> bool:
    value = (raw or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _vm_status(project: str, zone: str, instance_name: str) -> str:
    if not project or not zone or not instance_name:
        return "unknown"
    try:
        payload = vm_describe(project, zone, instance_name)
    except core.GcloudError:
        return "unknown"
    return str(payload.get("status", "")).strip() or "unknown"


def vm_serial_tail(project: str, zone: str, instance_name: str, lines: int = 50) -> str:
    """Return last N lines of VM serial output for diagnostics."""
    if not project or not zone or not instance_name:
        return "<serial-unavailable: missing GCP_PROJECT/GCP_ZONE/BMT_LIVE_VM>"
    try:
        serial = vm_serial_output_retry(
            project, zone, instance_name, attempts=4, base_delay_sec=2.0
        )
    except core.GcloudError as exc:
        return f"<serial-unavailable: {exc}>"
    tail = "\n".join(serial.splitlines()[-lines:])
    return tail.strip() or "<serial-empty>"


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class VmManager:
    """VM lifecycle: select from pool, start, sync metadata."""

    def __init__(self, cfg: Any) -> None:
        self._cfg = cfg

    @classmethod
    def from_env(cls) -> VmManager:
        return cls(config.get_config())

    def select(self) -> None:
        """Select a VM from the pool; write selected_vm and vm_reused_running to GITHUB_OUTPUT."""
        self._cfg.require_gcp()
        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        github_output = core.require_env("GITHUB_OUTPUT")

        pool: list[str] = []
        pool_label = (os.environ.get("BMT_VM_POOL_LABEL") or "").strip()
        if pool_label:
            if ":" in pool_label:
                key, val = pool_label.split(":", 1)
                key_safe = key.strip().replace("_", "-")
                filter_expr = f"labels.{key_safe}={val.strip()}"
            else:
                filter_expr = f"labels.{pool_label.strip()}=*"
            pool = vm_list_names(project, zone, filter_expr=filter_expr)
            pool.sort()
            print(f"VM pool from label {pool_label!r} ({len(pool)} instance(s)): {pool}")
        if not pool and self._cfg.bmt_vm_name and self._cfg.bmt_vm_name.strip():
            # Derive blue/green pool from VM name (declarative convention; no repo var).
            name = self._cfg.bmt_vm_name.strip()
            if name.endswith("-blue") or name.endswith("-green"):
                base = (name.removesuffix("-green").removesuffix("-blue").rstrip("-"))
                if base:
                    pool = [f"{base}-blue", f"{base}-green"]
                    print(f"VM pool from BMT_LIVE_VM blue/green (2 instance(s)): {pool}")
        if not pool:
            if not (self._cfg.bmt_vm_name and self._cfg.bmt_vm_name.strip()):
                gh_error(
                    "BMT VM pool is empty and BMT_LIVE_VM is not set. Set BMT_VM_POOL_LABEL or BMT_LIVE_VM."
                )
                raise RuntimeError("BMT VM pool must not be empty.")
            pool = [self._cfg.bmt_vm_name]
            print(f"VM pool from BMT_LIVE_VM (1 instance): {pool}")
        elif not pool_label:
            print(f"VM pool ({len(pool)} instance(s)): {pool}")

        if not pool:
            gh_error("BMT VM pool is empty.")
            raise RuntimeError("BMT VM pool must not be empty.")

        statuses: dict[str, str] = {}
        missing: list[str] = []
        for vm_name in pool:
            status = _vm_status(project, zone, vm_name)
            statuses[vm_name] = status
            if status == "unknown":
                missing.append(vm_name)
            else:
                print(f"  {vm_name}: {status}")
        if missing:
            gh_error(f"VM(s) not found in {project}/{zone}: {missing}.")
            raise RuntimeError(f"BMT VM pool has missing instance(s): {missing}")

        run_id_str = os.environ.get("GITHUB_RUN_ID", "0")
        run_id_int = int(run_id_str) if run_id_str.isdigit() else 0

        terminated = [v for v in pool if statuses.get(v) == "TERMINATED"]
        if terminated:
            idx = run_id_int % len(terminated)
            selected = terminated[idx]
            print(f"Selected VM: {selected} (TERMINATED — will start and assign this run)")
            write_github_output(github_output, "selected_vm", selected)
            write_github_output(github_output, "vm_reused_running", "false")
            return

        running = [v for v in pool if statuses.get(v) == "RUNNING"]
        if running:
            idx = run_id_int % len(running)
            selected = running[idx]
            print(f"Selected VM: {selected} (RUNNING — reusing)")
            write_github_output(github_output, "selected_vm", selected)
            write_github_output(github_output, "vm_reused_running", "true")
            return

        status_summary = ", ".join(f"{v}={s}" for v, s in statuses.items())
        msg = f"No selectable VM state for pool ({status_summary})."
        gh_error(f"No BMT VM is available. {msg}")
        raise RuntimeError(msg)

    def start(self) -> None:
        """Start the BMT VM."""
        self._cfg.require_gcp()
        timeout_sec = VM_START_TIMEOUT_SEC
        poll_interval_sec = 5
        stabilization_sec = VM_STABILIZATION_SEC
        recovery_attempts_max = VM_START_RECOVERY_ATTEMPTS
        recovery_start_delay_sec = VM_RECOVERY_START_DELAY_SEC

        if not _is_truthy(os.environ.get("GITHUB_ACTIONS")) and not _is_truthy(
            os.environ.get("BMT_ALLOW_MANUAL_VM_START")
        ):
            raise RuntimeError(
                "Manual VM start is blocked. Set BMT_ALLOW_MANUAL_VM_START=1 for explicit manual starts."
            )

        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        instance_name = self._cfg.bmt_vm_name
        before_status = ""
        before_last_start: str | None = None
        try:
            before = vm_describe(project, zone, instance_name)
            before_status = _instance_status(before)
            before_last_start = _last_start_timestamp(before)
        except core.GcloudError as exc:
            gh_warning(f"Could not describe VM before start: {exc}")

        def is_idempotent(exc: core.GcloudError) -> bool:
            text = str(exc).lower()
            return any(
                t in text
                for t in (
                    "already running", "already started", "is starting", "being started",
                    "operation in progress", "currently stopping", "is stopping",
                    "not ready", "resource not ready", "resource fingerprint changed",
                    "please try again",
                )
            )

        def request_start(reason: str) -> None:
            try:
                vm_start(project, zone, instance_name)
            except core.GcloudError as exc:
                if is_idempotent(exc):
                    gh_warning(str(exc))
                    return
                gh_error(str(exc))
                raise
            print(f"Start command submitted for VM {instance_name} (zone={zone}) [{reason}]")

        stop_retry_done = False
        recovery_attempts = 0
        recovery_pending = False
        deadline = time.monotonic() + timeout_sec

        def start_after_stop(reason: str) -> None:
            nonlocal stop_retry_done
            if recovery_attempts == 0:
                stop_retry_done = True
            if recovery_attempts > 0 and recovery_start_delay_sec > 0:
                bounded = min(recovery_start_delay_sec, max(0, int(deadline - time.monotonic())))
                print(f"Waiting {bounded}s after TERMINATED before start.")
                time.sleep(bounded)
            request_start(reason)

        def stabilize() -> str:
            stable_deadline = time.monotonic() + stabilization_sec
            while time.monotonic() < stable_deadline:
                try:
                    d = vm_describe(project, zone, instance_name)
                    s = _instance_status(d)
                    if s != "RUNNING":
                        return s or "<unknown>"
                except core.GcloudError as exc:
                    gh_warning(f"Stabilization check: {exc}")
                remaining = stable_deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(max(1, poll_interval_sec), remaining))
            return ""

        request_start("initial start")
        print(
            f"Waiting for RUNNING (timeout={timeout_sec}s); "
            f"previous status={before_status or '<unknown>'} lastStart={before_last_start or '<none>'}"
        )

        last_seen_status = ""
        last_seen_start: str | None = None
        while time.monotonic() < deadline:
            try:
                describe = vm_describe(project, zone, instance_name)
                last_seen_status = _instance_status(describe)
                last_seen_start = _last_start_timestamp(describe)
            except core.GcloudError as exc:
                gh_warning(f"Transient error describing VM: {exc}")
                time.sleep(poll_interval_sec)
                continue

            if last_seen_status == "STOPPING" and (not stop_retry_done or recovery_attempts > 0):
                stop_deadline = time.monotonic() + min(
                    _VM_STOPPING_WAIT_SEC, max(0, int(deadline - time.monotonic()))
                )
                gh_notice("VM is STOPPING; waiting for TERMINATED then retrying start.")
                while time.monotonic() < stop_deadline:
                    describe = vm_describe(project, zone, instance_name)
                    s = _instance_status(describe)
                    if s == "TERMINATED":
                        print("VM reached TERMINATED; issuing retry start.")
                        start_after_stop("retry after VM stopped")
                        break
                    time.sleep(min(poll_interval_sec, stop_deadline - time.monotonic()))
                continue

            if last_seen_status == "TERMINATED" and (not stop_retry_done or recovery_attempts > 0):
                gh_notice("VM is TERMINATED; issuing retry start.")
                start_after_stop("retry after VM stopped")
                continue

            running = last_seen_status == "RUNNING"
            start_advanced = before_last_start is None or (
                last_seen_start is not None and last_seen_start != before_last_start
            )
            already_running = before_status == "RUNNING" and running
            if running and (start_advanced or already_running or recovery_pending):
                recovery_pending = False
                print(f"VM ready: status={last_seen_status} lastStart={last_seen_start or '<none>'}")
                if stabilization_sec <= 0:
                    return
                print(f"Stabilizing RUNNING for {stabilization_sec}s")
                unstable = stabilize()
                if unstable:
                    recovery_attempts += 1
                    if recovery_attempts > recovery_attempts_max:
                        raise RuntimeError(
                            f"VM unstable; recovery exhausted (status={unstable})"
                        )
                    gh_warning(f"VM unstable (status={unstable}); recovery {recovery_attempts}/{recovery_attempts_max}")
                    before_status = unstable
                    before_last_start = last_seen_start
                    recovery_pending = True
                    request_start(f"recovery attempt {recovery_attempts}")
                    continue
                print("VM stabilization passed.")
                return
            time.sleep(max(1, poll_interval_sec))

        raise RuntimeError(
            f"VM did not reach ready; last status={last_seen_status or '<unknown>'} "
            f"lastStart={last_seen_start or '<none>'}"
        )

    def sync_metadata(self) -> None:
        """Sync VM metadata and inline startup script from ci.resources."""
        self._cfg.require_gcp()
        project = self._cfg.gcp_project
        zone = self._cfg.gcp_zone
        instance_name = self._cfg.bmt_vm_name
        bucket = self._cfg.gcs_bucket
        repo_root = self._cfg.effective_repo_root

        try:
            entrypoint = importlib_resources.files("ci.resources").joinpath("startup_entrypoint.sh")
            startup_script = entrypoint.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
            raise RuntimeError(
                "Missing packaged startup entrypoint: ci.resources/startup_entrypoint.sh"
            ) from exc
        if not startup_script.strip():
            raise RuntimeError("Packaged startup entrypoint is empty.")

        try:
            described = vm_describe(project, zone, instance_name)
        except core.GcloudError:
            described = None
        if described:
            current = _metadata_items(described)
            if current.get("BMT_BUCKET_PREFIX", "").strip():
                raise RuntimeError(
                    f"Legacy BMT_BUCKET_PREFIX found on {instance_name}. Clear VM metadata."
                )

        metadata = {
            "GCS_BUCKET": bucket,
            "BMT_REPO_ROOT": repo_root,
            "startup-script-url": "",
        }
        force = _is_truthy(os.environ.get("BMT_FORCE_SYNC"))
        if not force and described:
            current = _metadata_items(described)
            if (
                all(current.get(k) == v for k, v in metadata.items())
                and current.get("startup-script", "").strip() == startup_script.strip()
            ):
                print(f"VM metadata for {instance_name} already in sync; skipping.")
                return

        with tempfile.TemporaryDirectory(prefix="bmt_startup_") as tmp_dir:
            entrypoint_path = Path(tmp_dir) / "startup_entrypoint.sh"
            entrypoint_path.write_text(startup_script, encoding="utf-8")
            vm_add_metadata(
                project, zone, instance_name, metadata,
                metadata_files={"startup-script": entrypoint_path},
            )
        described = vm_describe(project, zone, instance_name)
        items = _metadata_items(described)
        if items.get("GCS_BUCKET", "").strip() != bucket:
            raise RuntimeError("VM metadata verification failed: GCS_BUCKET did not persist.")
        if items.get("BMT_REPO_ROOT", "").strip() != repo_root:
            raise RuntimeError("VM metadata verification failed: BMT_REPO_ROOT did not persist.")
        if not (items.get("startup-script", "")).strip():
            raise RuntimeError("VM metadata verification failed: startup-script missing.")
        if (items.get("startup-script-url", "")).strip():
            raise RuntimeError("VM metadata verification failed: startup-script-url not cleared.")
        print(f"Synced VM metadata for {instance_name}: GCS_BUCKET={bucket} BMT_REPO_ROOT={repo_root}")
