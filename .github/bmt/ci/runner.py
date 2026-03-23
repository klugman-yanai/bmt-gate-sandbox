"""Runner: upload to GCS, validate in repo, filter upload matrix, resolve uploaded, summarize."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

from whenever import Instant

from ci import config, core, gcs
from ci.actions import gh_notice, gh_warning, write_github_output
from ci.config import BmtConfig, BmtContext, WorkflowContext
from ci.runner_provenance import write_runner_provenance
from ci.workflow_env import read_workflow_str


def _project_has_bmt_stage_layout(project: str) -> bool:
    """True when this repo declares BMT for ``project`` under ``gcp/stage/projects/<project>/``."""
    slug = str(project).strip().lower()
    if not slug:
        return False
    base = Path("gcp/stage/projects") / slug
    return (base / "project.json").is_file() or (base / "bmts").is_dir()


def _runner_meta_in_gcs(root: str, project: str, _preset: str) -> dict[str, Any] | None:
    for name in ("runner_meta.json", "runner_latest_meta.json"):
        payload, _ = gcs.download_json(f"{root}/projects/{project}/{name}")
        if isinstance(payload, dict):
            return payload
    return None


def _ci_run_id_for_markers() -> str:
    """Prefer parent CI run id (``BMT_CI_RUN_ID``) so GCS markers align with build-and-test."""
    rid = (os.environ.get("BMT_CI_RUN_ID") or "").strip()
    return rid if rid else core.workflow_run_id()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pair_sha256_from_file_rows(rows: list[dict[str, Any]]) -> str:
    """Single digest for kardome_runner + optional libKardome.so (order-independent)."""
    pairs = sorted(
        (str(r["name"]), str(r["sha256"]).strip().lower())
        for r in rows
        if str(r.get("name", "")).strip() and str(r.get("sha256", "")).strip()
    )
    canonical = "\n".join(f"{n}:{h}" for n, h in pairs)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _remote_pair_sha256_for_local_files(
    remote_meta: Any, local_files: list[dict[str, Any]]
) -> str | None:
    """Recompute pair digest from remote ``runner_meta.json`` ``files`` for the same names as local."""
    if not isinstance(remote_meta, dict):
        return None
    files = remote_meta.get("files")
    if not isinstance(files, list):
        return None
    by_name: dict[str, str] = {}
    for row in files:
        if not isinstance(row, dict):
            continue
        n = str(row.get("name", "")).strip()
        h = str(row.get("sha256", "")).strip().lower()
        if n and h:
            by_name[n] = h
    remote_rows: list[dict[str, Any]] = []
    for lf in local_files:
        n = str(lf["name"])
        h = by_name.get(n)
        if not h:
            return None
        remote_rows.append({"name": n, "sha256": h})
    if len(remote_rows) != len(local_files):
        return None
    return _pair_sha256_from_file_rows(remote_rows)


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
            print(
                f"::notice::Requested runner exists in bucket: {canonical_runner_uri} (validated for handoff)."
            )
        else:
            local_candidates = (
                Path("gcp/stage") / project / "runners" / preset / "kardome_runner",
                Path("gcp/stage/projects") / project / "kardome_runner",
            )
            for candidate in local_candidates:
                if candidate.is_file():
                    print(
                        f"::notice::Requested runner exists in repo mirror: {candidate} (validated for handoff)."
                    )
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
        skip_publish = read_workflow_str(
            w, "bmt_skip_publish_runners", "BMT_SKIP_PUBLISH_RUNNERS"
        ).lower() in ("1", "true", "yes")
        if skip_publish:
            out = {"include": []}
            path = Path(core.require_env("GITHUB_OUTPUT"))
            with path.open("a", encoding="utf-8") as f:
                f.write(f"matrix_need_upload<<FILTER_EOF\n{json.dumps(out)}\nFILTER_EOF\n")
                f.write("matrix_need_upload_keys=[]\n")
                f.write(f"matrix_publish<<PUBLISH_EOF\n{json.dumps(out)}\nPUBLISH_EOF\n")
                f.write("matrix_publish_keys=[]\n")
            print(
                "::notice::Filter upload matrix: BMT_SKIP_PUBLISH_RUNNERS=true — no publish jobs (runners assumed in bucket)."
            )
            return
        runner_matrix_raw = read_workflow_str(w, "runner_matrix", "RUNNER_MATRIX")
        head_sha = read_workflow_str(w, "head_sha", "HEAD_SHA")
        preseeded = read_workflow_str(
            w, "bmt_runners_preseeded_in_gcs", "BMT_RUNNERS_PRESEEDED_IN_GCS"
        ).lower() in ("1", "true", "yes")
        available_artifacts_raw = read_workflow_str(
            w, "available_artifacts", "AVAILABLE_ARTIFACTS", "[]"
        )
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
        skip_missing = read_workflow_str(
            w, "skip_missing_runner_artifacts", "SKIP_MISSING_RUNNER_ARTIFACTS", ""
        ).lower() in ("1", "true", "yes")
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
                if preseeded:
                    if project not in projects_written:
                        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                        try:
                            gcs.write_object(marker_uri, "{}")
                        except gcs.GcsError as e:
                            gh_warning(f"Could not write uploaded marker {marker_uri}: {e}")
                        projects_written.add(project)
                    print(
                        f"::notice::Preseeded GCS runner for {project}/{preset}: verified in GCS (will show as Skipped)."
                    )
                    continue
                if str(payload.get("source_ref", "")).strip() == head_sha:
                    if project not in projects_written:
                        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                        try:
                            gcs.write_object(marker_uri, "{}")
                        except gcs.GcsError as e:
                            gh_warning(f"Could not write uploaded marker {marker_uri}: {e}")
                        projects_written.add(project)
                    print(
                        f"::notice::Skip upload for {project}/{preset}: already on GCS for ref {head_sha[:7]} (will show as Skipped)."
                    )
                    continue
            if skip_missing and f"runner-{preset}" not in artifact_set:
                print(
                    f"::notice::Skip upload for {project}/{preset}: no runner artifact in caller run "
                    "(skip_missing_runner_artifacts; dev placeholder CI)."
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
            f.write(f"matrix_need_upload<<FILTER_EOF\n{out_json}\nFILTER_EOF\n")
            keys = [f"{e['project']}|{e['preset']}" for e in need_include]
            f.write(f"matrix_need_upload_keys={json.dumps(keys)}\n")
            f.write(f"matrix_publish<<PUBLISH_EOF\n{pub_json}\nPUBLISH_EOF\n")
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
        if not runner_binary.is_file():
            raise RuntimeError(f"kardome_runner not found in {runner_dir}")
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
        local_pair = _pair_sha256_from_file_rows(local_files)
        stored_pair: str | None = None
        if isinstance(remote_meta, dict):
            raw_pair = remote_meta.get("pair_sha256")
            if isinstance(raw_pair, str) and raw_pair.strip():
                stored_pair = raw_pair.strip().lower()
        remote_computed = _remote_pair_sha256_for_local_files(remote_meta, local_files)
        skip_binaries = local_pair == stored_pair or (
            stored_pair is None and remote_computed is not None and local_pair == remote_computed
        )
        if skip_binaries:
            print(
                f"::notice::Runner upload skipped: pair_sha256 unchanged for {project}/{preset} "
                f"({local_pair[:12]}...)."
            )
            write_runner_provenance(
                bucket, root, dest_prefix, local_files, source_ref, project, preset
            )
            return

        uploaded = []
        for row in local_files:
            name = str(row["name"])
            local_size = int(row.get("size", 0) or 0)
            local_sha = str(row["sha256"])
            try:
                gcs.write_object(str(row["dest"]), Path(str(row["path"])).read_bytes())
            except gcs.GcsError as exc:
                raise RuntimeError(f"Failed to upload {name}: {exc}") from exc
            uploaded.append({"name": name, "size": local_size, "sha256": local_sha})
            print(f"Uploaded {name} -> {row['dest']}")
        meta = {
            "uploaded_at": Instant.now().format_iso(unit="second"),
            "source_ref": source_ref,
            "project": project,
            "preset": preset,
            "pair_sha256": local_pair,
            "files": [
                {"name": str(r["name"]), "size": int(r["size"]), "sha256": str(r["sha256"])}
                for r in local_files
            ],
            "uploaded_files": uploaded,
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
        uploaded_projects = {
            u.split("/")[-1].replace(".json", "").strip() for u in uris if u.endswith(".json")
        }
        w = self._w()
        runner_matrix_raw = read_workflow_str(w, "runner_matrix", "RUNNER_MATRIX")
        if runner_matrix_raw:
            try:
                runner_matrix = json.loads(runner_matrix_raw)
                include = (
                    runner_matrix.get("include", []) if isinstance(runner_matrix, dict) else []
                )
                if isinstance(include, list):
                    for entry in include:
                        if not isinstance(entry, dict):
                            continue
                        project = str(entry.get("project", "")).strip()
                        preset = str(entry.get("preset", "")).strip()
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
        bmt_jobs = sorted(
            {str(e.get("project", "")).strip() for e in filtered_matrix.get("include", []) if e}
        )
        print(f"::notice::Matrix handshake: uploaded={len(accepted)} legs={len(bmt_jobs)}")
