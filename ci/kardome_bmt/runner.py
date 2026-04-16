"""Runner: upload to GCS, validate in repo, filter upload matrix, resolve uploaded, summarize."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

from whenever import Instant

from kardome_bmt import config, core, gcs
from kardome_bmt.actions import gh_notice, gh_warning, write_github_output
from kardome_bmt.config import BmtConfig, BmtContext, WorkflowContext
from kardome_bmt.runner_provenance import write_runner_provenance
from kardome_bmt.workflow_env import read_workflow_str


def _project_has_bmt_stage_layout(project: str) -> bool:
    """True when this repo declares BMT for ``project`` under ``plugins/projects/<project>/``."""
    slug = str(project).strip().lower()
    if not slug:
        return False
    base = Path("plugins/projects") / slug
    return (base / "project.json").is_file() or (base / "bmts").is_dir()


def _runner_meta_in_gcs(root: str, project: str, preset: str) -> dict[str, Any] | None:
    # New layout: projects/{project}/{meta}
    for name in ("runner_meta.json", "runner_latest_meta.json"):
        payload, _ = gcs.download_json(f"{root}/projects/{project}/{name}")
        if isinstance(payload, dict):
            return payload
    # Old layout (bucket_upload_runner.py): {project}/runners/{preset}/{meta}
    payload, _ = gcs.download_json(f"{root}/{project}/runners/{preset}/runner_latest_meta.json")
    if isinstance(payload, dict):
        return payload
    # Local repo fallback: plugins/projects/{project}/runner_latest_meta.json.
    # Present when the runner is configured in this repo's plugins layout (bucket may not yet
    # be synced, but the file's presence confirms a runner is intended for this project).
    local = Path("plugins/projects") / project / "runner_latest_meta.json"
    if local.is_file():
        try:
            data = json.loads(local.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"::warning::Failed to parse local runner meta {local}: {e}", file=sys.stderr)
    return None


def _ci_run_id_for_markers() -> str:
    """Prefer parent CI run id (``BMT_CI_RUN_ID``) so GCS markers align with build-and-test."""
    rid = (os.environ.get("BMT_CI_RUN_ID") or "").strip()
    return rid or core.workflow_run_id()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_nonempty_file(path: Path, *, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} not found: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"{label} is empty (placeholder artifact refused): {path}")


class RunnerManager:
    def __init__(self, cfg: BmtConfig, ctx: BmtContext | None) -> None:
        self._cfg = cfg
        self._ctx = ctx

    @classmethod
    def from_env(cls) -> RunnerManager:
        return cls(config.get_config(), config.get_context())

    def _w(self) -> WorkflowContext | None:
        return self._ctx.workflow if self._ctx else None

    def validate_in_repo(self) -> None:
        project = core.require_env("PROJECT")
        preset = core.require_env("PRESET")
        run_id = _ci_run_id_for_markers()
        root = core.workflow_runtime_root()
        canonical_runner_uri = f"{root}/projects/{project}/kardome_runner"
        try:
            exists = gcs.object_exists(canonical_runner_uri)
        except gcs.GcsError as exc:
            print(f"::warning::Could not verify runner in GCS ({exc}); checking local fallbacks.")
            exists = False
        if exists:
            print(f"::notice::Requested runner exists in bucket: {canonical_runner_uri} (validated for handoff).")
        else:
            local_candidates = (
                Path("plugins") / project / "runners" / preset / "kardome_runner",
                Path("plugins/projects") / project / "kardome_runner",
            )
            for candidate in local_candidates:
                if candidate.is_file():
                    print(f"::notice::Requested runner exists in repo mirror: {candidate} (validated for handoff).")
                    break
            else:
                gh_warning(
                    "VM does not support this BMT: requested runner not found in bucket at "
                    f"{canonical_runner_uri} (or local stage mirror fallback paths). "
                    "No handoff leg will run for this project."
                )
                return
        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
        try:
            gcs.write_object(marker_uri, "{}")
        except gcs.GcsError as exc:
            raise RuntimeError(f"Failed to write uploaded marker {marker_uri}: {exc}") from exc
        print(f"Marked project {project} as validated for handoff -> {marker_uri}")

    def filter_upload_matrix(self) -> None:
        w = self._w()
        skip_publish = read_workflow_str(w, "bmt_skip_publish_runners", "BMT_SKIP_PUBLISH_RUNNERS").lower() in (
            "1",
            "true",
            "yes",
        )
        if skip_publish:
            out: dict[str, Any] = {"include": []}
            path = Path(core.require_env("GITHUB_OUTPUT"))
            with path.open("a", encoding="utf-8") as f:
                matrix_need_upload_str = f"""matrix_need_upload<<FILTER_EOF
{json.dumps(out)}
FILTER_EOF
"""
                f.write(matrix_need_upload_str)
                f.write("matrix_need_upload_keys=[]\n")
                matrix_publish_str = f"""matrix_publish<<PUBLISH_EOF
{json.dumps(out)}
PUBLISH_EOF
"""
                f.write(matrix_publish_str)
                f.write("matrix_publish_keys=[]\n")
            print(
                "::notice::Filter upload matrix: BMT_SKIP_PUBLISH_RUNNERS=true — no publish jobs (runners assumed in bucket)."
            )
            return
        runner_matrix_raw = read_workflow_str(w, "runner_matrix", "RUNNER_MATRIX")
        head_sha = read_workflow_str(w, "head_sha", "HEAD_SHA")
        preseeded = read_workflow_str(w, "bmt_runners_preseeded_in_gcs", "BMT_RUNNERS_PRESEEDED_IN_GCS").lower() in (
            "1",
            "true",
            "yes",
        )
        available_artifacts_raw = read_workflow_str(w, "available_artifacts", "AVAILABLE_ARTIFACTS", "[]")
        github_run_id = (os.environ.get("BMT_CI_RUN_ID") or "").strip() or (
            read_workflow_str(w, "github_run_id", "GITHUB_RUN_ID") or core.workflow_run_id()
        )
        if not runner_matrix_raw or not head_sha:
            raise RuntimeError("RUNNER_MATRIX and HEAD_SHA are required")
        matrix = json.loads(runner_matrix_raw)
        include = matrix.get("include", [])
        if not isinstance(include, list):
            raise TypeError("RUNNER_MATRIX.include must be a JSON array")
        try:
            available_artifacts = json.loads(available_artifacts_raw)
        except json.JSONDecodeError:
            available_artifacts = []
        artifact_set = {
            str(a).strip()
            for a in (available_artifacts if isinstance(available_artifacts, list) else [])
            if str(a).strip()
        }
        root = core.workflow_runtime_root()
        run_id = github_run_id
        need_include: list[dict[str, Any]] = []
        publish_include: list[dict[str, Any]] = []
        projects_written = set()
        for entry in include:
            if not isinstance(entry, dict):
                continue
            project = str(entry.get("project", "")).strip()
            preset = str(entry.get("preset", "")).strip()
            if not project or not preset:
                continue
            supported = "true" if _project_has_bmt_stage_layout(project) else "false"
            payload = _runner_meta_in_gcs(root, project, preset)
            if payload is not None:
                # Use GCS runner when: explicitly preseeded, SHA matches, OR no GitHub
                # artifacts are available (this repo doesn't build runners).
                use_gcs = preseeded or not artifact_set or str(payload.get("source_ref", "")).strip() == head_sha
                if use_gcs:
                    if project not in projects_written:
                        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                        try:
                            gcs.write_object(marker_uri, "{}")
                        except gcs.GcsError as e:
                            gh_warning(f"Could not write uploaded marker {marker_uri}: {e}")
                        projects_written.add(project)
                    reason = (
                        "preseeded"
                        if preseeded
                        else ("no GitHub artifacts" if not artifact_set else f"ref {head_sha[:7]}")
                    )
                    print(
                        f"::notice::Skip upload for {project}/{preset}: runner in GCS ({reason}) (will show as Skipped)."
                    )
                    continue
            # No GitHub artifacts provided — caller doesn't build runners).
            # Fall back: check if the runner binary itself already exists in GCS
            # (new layout: projects/{project}/kardome_runner;
            #  old layout: {project}/runners/{preset}/kardome_runner).
            if not artifact_set:
                binary_exists = False
                for binary_uri in (
                    f"{root}/projects/{project}/kardome_runner",
                    f"{root}/{project}/runners/{preset}/kardome_runner",
                ):
                    try:
                        if gcs.object_exists(binary_uri):
                            binary_exists = True
                            break
                    except gcs.GcsError:
                        pass
                if binary_exists:
                    if project not in projects_written:
                        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                        try:
                            gcs.write_object(marker_uri, "{}")
                        except gcs.GcsError as e:
                            gh_warning(f"Could not write uploaded marker {marker_uri}: {e}")
                        projects_written.add(project)
                    print(
                        f"::notice::No artifact list; runner binary in GCS for {project}/{preset}: "
                        "using bucket runner (will show as Skipped)."
                    )
                    continue
            if artifact_set and f"runner-{preset}" not in artifact_set:
                print(
                    f"::notice::Skip upload for {project}/{preset}: artifact not in available list (will show as Skipped)."
                )
                continue
            row = cast(dict[str, Any], dict(entry))
            row["bmt_supported"] = supported
            publish_include.append(row)
            if supported == "true":
                need_include.append(dict(entry))
        out = {"include": need_include}
        pub = {"include": publish_include}
        out_json = json.dumps(out, separators=(",", ":"))
        pub_json = json.dumps(pub, separators=(",", ":"))
        path = Path(core.require_env("GITHUB_OUTPUT"))
        with path.open("a", encoding="utf-8") as f:
            matrix_need_upload_str = f"""matrix_need_upload<<FILTER_EOF
{out_json}
FILTER_EOF
"""
            f.write(matrix_need_upload_str)
            keys = [f"{e['project']}|{e['preset']}" for e in need_include]
            f.write(f"matrix_need_upload_keys={json.dumps(keys)}\n")
            matrix_publish_str = f"""matrix_publish<<PUBLISH_EOF
{pub_json}
PUBLISH_EOF
"""
            f.write(matrix_publish_str)
            pub_keys = [f"{e['project']}|{e['preset']}" for e in publish_include]
            f.write(f"matrix_publish_keys={json.dumps(pub_keys)}\n")
        print(
            f"::notice::Filter upload matrix: {len(need_include)} publish job(s) for supported BMT; "
            f"{len(publish_include)} total artifact leg(s); "
            f"{len(include) - len(publish_include)} already on GCS or no artifact (will show as Skipped)."
        )

    def upload(self) -> None:
        self._cfg.require_gcp()
        bucket = self._cfg.gcs_bucket
        project = core.require_env("PROJECT")
        preset = core.require_env("PRESET")
        source_ref = os.environ.get("SOURCE_REF", "")
        runner_dir = Path(os.environ.get("RUNNER_DIR", "artifact/Runners"))
        lib_dir_raw = os.environ.get("LIB_DIR", "artifact/Kardome")
        lib_dir = Path(lib_dir_raw) if lib_dir_raw else None
        if not runner_dir.is_dir():
            raise RuntimeError(f"Runner directory does not exist: {runner_dir}")
        if lib_dir is not None and not lib_dir.is_dir():
            lib_dir = None
        root = core.bucket_root_uri(bucket)
        dest_prefix = f"projects/{project}"
        meta_dest = f"{root}/{dest_prefix}/runner_meta.json"
        runner_binary = runner_dir / "kardome_runner"
        _require_nonempty_file(runner_binary, label="kardome_runner")
        local_files = [
            {
                "name": "kardome_runner",
                "size": runner_binary.stat().st_size,
                "sha256": _sha256_file(runner_binary),
                "path": str(runner_binary),
                "dest": f"{root}/{dest_prefix}/kardome_runner",
            },
        ]
        if lib_dir is not None:
            lib_file = lib_dir / "libKardome.so"
            if lib_file.is_file():
                _require_nonempty_file(lib_file, label="libKardome.so")
                local_files.append(
                    {
                        "name": "libKardome.so",
                        "size": lib_file.stat().st_size,
                        "sha256": _sha256_file(lib_file),
                        "path": str(lib_file),
                        "dest": f"{root}/{dest_prefix}/libKardome.so",
                    }
                )
        remote_meta, _ = gcs.download_json(meta_dest)
        remote_files = {}
        if isinstance(remote_meta, dict) and isinstance(remote_meta.get("files"), list):
            for row in remote_meta["files"]:
                if isinstance(row, dict) and str(row.get("name", "")).strip():
                    remote_files[str(row["name"])] = row
        uploaded = []
        skipped = []
        for row in local_files:
            name = str(row["name"])
            local_size = int(row.get("size", 0) or 0)
            local_sha = str(row["sha256"])
            remote = remote_files.get(name, {})
            remote_size = (
                int(remote.get("size", -1))
                if isinstance(remote.get("size"), (int, str)) and str(remote.get("size")).isdigit()
                else -1
            )
            remote_sha = str(remote.get("sha256", "")).strip().lower()
            if remote_size == local_size and remote_sha == local_sha:
                skipped.append(name)
                continue
            try:
                gcs.write_object(str(row["dest"]), Path(str(row["path"])).read_bytes())
            except gcs.GcsError as exc:
                raise RuntimeError(f"Failed to upload {name}: {exc}") from exc
            uploaded.append({"name": name, "size": local_size, "sha256": local_sha})
            print(f"Uploaded {name} -> {row['dest']}")
        if not uploaded:
            print(
                f"Runner upload skipped: no content changes for {project}/{preset} ({', '.join(skipped) if skipped else 'none'})"
            )
            write_runner_provenance(bucket, root, dest_prefix, local_files, source_ref, project, preset)
            return
        meta = {
            "uploaded_at": Instant.now().format_iso(unit="second"),
            "source_ref": source_ref,
            "project": project,
            "preset": preset,
            "files": [
                {"name": str(r["name"]), "size": int(r["size"]), "sha256": str(r["sha256"])} for r in local_files
            ],
            "uploaded_files": uploaded,
            "skipped_unchanged_files": skipped,
        }
        try:
            gcs.upload_json(meta_dest, meta)
        except gcs.GcsError as exc:
            raise RuntimeError(f"Failed to upload runner_meta.json: {exc}") from exc
        print(f"Uploaded runner_meta.json -> {meta_dest}")
        write_runner_provenance(bucket, root, dest_prefix, local_files, source_ref, project, preset)
        print(f"Runner upload complete: {len(uploaded)} changed file(s) for {project}/{preset}")

    def upload_runner_to_gcs(self) -> None:
        runner_dir = Path("artifact/Runners")
        if (runner_dir / "kardome_runner").is_file():
            with contextlib.suppress(OSError):
                (runner_dir / "kardome_runner").chmod(0o755)
        self.upload()

    def resolve_uploaded_projects(self) -> None:
        run_id = _ci_run_id_for_markers()
        root = core.workflow_runtime_root()
        prefix = f"{root}/_workflow/uploaded/{run_id}/"
        uris = gcs.list_prefix(prefix)
        uploaded_projects = {u.split("/")[-1].replace(".json", "").strip() for u in uris if u.endswith(".json")}
        w = self._w()
        runner_matrix_raw = read_workflow_str(w, "runner_matrix", "RUNNER_MATRIX")
        if runner_matrix_raw:
            try:
                runner_matrix = json.loads(runner_matrix_raw)
                include: list[object] = runner_matrix.get("include", []) if isinstance(runner_matrix, dict) else []
                if isinstance(include, list):
                    for entry in include:
                        if not isinstance(entry, dict):
                            continue
                        entry_d = cast(dict[str, object], entry)
                        project_raw = entry_d.get("project")
                        preset_raw = entry_d.get("preset")
                        project = str(project_raw).strip() if isinstance(project_raw, str) else ""
                        preset = str(preset_raw).strip() if isinstance(preset_raw, str) else ""
                        if not project or not preset:
                            continue
                        if _runner_meta_in_gcs(root, project, preset) is not None:
                            uploaded_projects.add(project)
            except json.JSONDecodeError as exc:
                gh_warning(f"Invalid RUNNER_MATRIX JSON; skipping GCS runner pre-scan: {exc}")
        names = sorted(uploaded_projects)
        accepted = json.dumps(names)
        Path("accepted.txt").write_text(accepted)
        write_github_output(os.environ.get("GITHUB_OUTPUT"), "accepted_projects", accepted)
        gh_notice(f"Runners uploaded for projects: {accepted}")

    def summarize_matrix_handshake(self) -> None:
        w = self._w()
        runner_matrix_raw = read_workflow_str(w, "runner_matrix", "RUNNER_MATRIX", "{}")
        filtered_raw = read_workflow_str(w, "filtered_matrix", "FILTERED_MATRIX", "{}")
        if not runner_matrix_raw or not filtered_raw:
            raise RuntimeError("RUNNER_MATRIX and FILTERED_MATRIX are required")
        json.loads(runner_matrix_raw)
        accepted_raw = read_workflow_str(w, "accepted", "ACCEPTED", "[]")
        accepted = json.loads(accepted_raw)
        filtered_matrix = json.loads(filtered_raw)
        bmt_jobs = sorted({str(e.get("project", "")).strip() for e in filtered_matrix.get("include", []) if e})
        print(f"::notice::Matrix handshake: uploaded={len(accepted)} legs={len(bmt_jobs)}")
