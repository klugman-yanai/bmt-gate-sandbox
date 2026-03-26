"""Runner: upload to GCS, validate in repo, filter upload matrix, resolve uploaded, summarize."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from whenever import Instant

from ci import config, core, gcs
from ci.actions import gh_notice, gh_warning, write_github_output

_SLSA_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
_SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
_SLSA_BUILD_TYPE = "https://kardome.com/bmt/runner-upload/v1"


def _ctx_str(w: Any, attr: str, env_var: str, default: str = "") -> str:
    if w is not None:
        return (getattr(w, attr, None) or default).strip()
    return (os.environ.get(env_var) or default).strip()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_runner_provenance(
    bucket: str, root: str, dest_prefix: str,
    local_files: list[dict[str, Any]], source_ref: str, project: str, preset: str,
) -> None:
    now = Instant.now().format_iso(unit="second")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    git_sha = os.environ.get("GITHUB_SHA", "")
    builder_id = f"https://github.com/{repository}/.github/workflows/build-and-test.yml" if repository else _SLSA_BUILD_TYPE
    provenance = {
        "_type": _SLSA_STATEMENT_TYPE,
        "subject": [{"name": f"{root}/{dest_prefix}/{r['name']}", "digest": {"sha256": str(r["sha256"])}} for r in local_files],
        "predicateType": _SLSA_PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": _SLSA_BUILD_TYPE,
                "externalParameters": {"source_ref": source_ref, "project": project, "preset": preset},
                "resolvedDependencies": [{"uri": f"https://github.com/{repository}", "digest": {"gitCommit": git_sha}}] if git_sha else [],
            },
            "runDetails": {
                "builder": {"id": builder_id},
                "metadata": {"invocationId": run_id, "startedOn": now, "finishedOn": now, "github_repository": repository, "github_run_id": run_id, "gcs_bucket": bucket, "dest_prefix": dest_prefix},
            },
        },
    }
    dest = f"{root}/{dest_prefix}/runner.slsa.json"
    try:
        gcs.write_object(dest, json.dumps(provenance, indent=2) + "\n")
    except gcs.GcsError as exc:
        print(f"::warning::Failed to upload runner provenance: {exc}")
        return
    print(f"Uploaded runner provenance (SLSA v1.0) -> {dest}")


class RunnerManager:
    def __init__(self, cfg: Any, ctx: Any) -> None:
        self._cfg = cfg
        self._ctx = ctx

    @classmethod
    def from_env(cls) -> RunnerManager:
        return cls(config.get_config(), config.get_context())

    def validate_in_repo(self) -> None:
        project = core.require_env("PROJECT")
        preset = core.require_env("PRESET")
        run_id = core.workflow_run_id()
        root = core.workflow_runtime_root()
        runner_path = Path("benchmarks") / project / "runners" / preset / "kardome_runner"
        if not runner_path.is_file():
            gh_warning(
                f"VM does not support this BMT: requested runner not found at {runner_path}. "
                "No handoff leg will run for this project."
            )
            return
        print(f"::notice::Requested runner exists: {runner_path} (validated for handoff).")
        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
        try:
            gcs.write_object(marker_uri, "{}")
        except gcs.GcsError as exc:
            raise RuntimeError(f"Failed to write uploaded marker {marker_uri}: {exc}") from exc
        print(f"Marked project {project} as validated for handoff -> {marker_uri}")

    def filter_upload_matrix(self) -> None:
        w = self._ctx.workflow if self._ctx else None
        runner_matrix_raw = _ctx_str(w, "runner_matrix", "RUNNER_MATRIX")
        head_sha = _ctx_str(w, "head_sha", "HEAD_SHA")
        preseeded = _ctx_str(w, "bmt_runners_preseeded_in_gcs", "BMT_RUNNERS_PRESEEDED_IN_GCS").lower() in ("1", "true", "yes")
        available_artifacts_raw = _ctx_str(w, "available_artifacts", "AVAILABLE_ARTIFACTS", "[]")
        github_run_id = _ctx_str(w, "github_run_id", "GITHUB_RUN_ID") or core.workflow_run_id()
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
        artifact_set = {str(a).strip() for a in (available_artifacts if isinstance(available_artifacts, list) else []) if str(a).strip()}
        root = core.workflow_runtime_root()
        run_id = github_run_id
        need_include = []
        projects_written = set()
        for entry in include:
            if not isinstance(entry, dict):
                continue
            project = str(entry.get("project", "")).strip()
            preset = str(entry.get("preset", "")).strip()
            if not project or not preset:
                continue
            meta_uri = f"{root}/{project}/runners/{preset}/runner_meta.json"
            payload, _ = gcs.download_json(meta_uri)
            if payload is not None:
                if preseeded:
                    if project not in projects_written:
                        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                        try:
                            gcs.write_object(marker_uri, "{}")
                        except gcs.GcsError as e:
                            gh_warning(f"Could not write uploaded marker {marker_uri}: {e}")
                        projects_written.add(project)
                    print(f"::notice::Preseeded GCS runner for {project}/{preset}: verified in GCS (will show as Skipped).")
                    continue
                if str(payload.get("source_ref", "")).strip() == head_sha:
                    if project not in projects_written:
                        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                        try:
                            gcs.write_object(marker_uri, "{}")
                        except gcs.GcsError as e:
                            gh_warning(f"Could not write uploaded marker {marker_uri}: {e}")
                        projects_written.add(project)
                    print(f"::notice::Skip upload for {project}/{preset}: already on GCS for ref {head_sha[:7]} (will show as Skipped).")
                    continue
            if artifact_set and f"runner-{preset}" not in artifact_set:
                print(f"::notice::Skip upload for {project}/{preset}: artifact not in available list (will show as Skipped).")
                continue
            need_include.append(entry)
        out = {"include": need_include}
        out_json = json.dumps(out, separators=(",", ":"))
        path = Path(core.require_env("GITHUB_OUTPUT"))
        with path.open("a", encoding="utf-8") as f:
            f.write(f"matrix_need_upload<<FILTER_EOF\n{out_json}\nFILTER_EOF\n")
            keys = [f"{e['project']}|{e['preset']}" for e in need_include]
            f.write(f"matrix_need_upload_keys={json.dumps(keys)}\n")
        print(f"::notice::Filter upload matrix: {len(need_include)} job(s) need upload; {len(include) - len(need_include)} already on GCS or no artifact (will show as Skipped).")

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
        dest_prefix = f"{project}/runners/{preset}"
        meta_dest = f"{root}/{dest_prefix}/runner_meta.json"
        runner_binary = runner_dir / "kardome_runner"
        if not runner_binary.is_file():
            raise RuntimeError(f"kardome_runner not found in {runner_dir}")
        local_files = [
            {"name": "kardome_runner", "size": runner_binary.stat().st_size, "sha256": _sha256_file(runner_binary), "path": str(runner_binary), "dest": f"{root}/{dest_prefix}/kardome_runner"},
        ]
        if lib_dir is not None:
            lib_file = lib_dir / "libKardome.so"
            if lib_file.is_file():
                local_files.append({"name": "libKardome.so", "size": lib_file.stat().st_size, "sha256": _sha256_file(lib_file), "path": str(lib_file), "dest": f"{root}/{dest_prefix}/libKardome.so"})
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
            remote_size = int(remote.get("size", -1)) if isinstance(remote.get("size"), (int, str)) and str(remote.get("size")).isdigit() else -1
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
            print(f"Runner upload skipped: no content changes for {project}/{preset} ({', '.join(skipped) if skipped else 'none'})")
            _write_runner_provenance(bucket, root, dest_prefix, local_files, source_ref, project, preset)
            return
        meta = {
            "uploaded_at": Instant.now().format_iso(unit="second"),
            "source_ref": source_ref, "project": project, "preset": preset,
            "files": [{"name": str(r["name"]), "size": int(r["size"]), "sha256": str(r["sha256"])} for r in local_files],
            "uploaded_files": uploaded, "skipped_unchanged_files": skipped,
        }
        try:
            gcs.upload_json(meta_dest, meta)
        except gcs.GcsError as exc:
            raise RuntimeError(f"Failed to upload runner_meta.json: {exc}") from exc
        print(f"Uploaded runner_meta.json -> {meta_dest}")
        _write_runner_provenance(bucket, root, dest_prefix, local_files, source_ref, project, preset)
        print(f"Runner upload complete: {len(uploaded)} changed file(s) for {project}/{preset}")

    def upload_runner_to_gcs(self) -> None:
        runner_dir = Path("artifact/Runners")
        if (runner_dir / "kardome_runner").is_file():
            with contextlib.suppress(OSError):
                (runner_dir / "kardome_runner").chmod(0o755)
        self.upload()

    def resolve_uploaded_projects(self) -> None:
        run_id = core.workflow_run_id()
        root = core.workflow_runtime_root()
        prefix = f"{root}/_workflow/uploaded/{run_id}/"
        uris = gcs.list_prefix(prefix)
        uploaded_projects = {u.split("/")[-1].replace(".json", "").strip() for u in uris if u.endswith(".json")}
        w = self._ctx.workflow if self._ctx else None
        runner_matrix_raw = _ctx_str(w, "runner_matrix", "RUNNER_MATRIX")
        if runner_matrix_raw:
            try:
                runner_matrix = json.loads(runner_matrix_raw)
                include = runner_matrix.get("include", []) if isinstance(runner_matrix, dict) else []
                if isinstance(include, list):
                    for entry in include:
                        if not isinstance(entry, dict):
                            continue
                        project = str(entry.get("project", "")).strip()
                        preset = str(entry.get("preset", "")).strip()
                        if not project or not preset:
                            continue
                        meta_uri = f"{root}/{project}/runners/{preset}/runner_meta.json"
                        payload, _ = gcs.download_json(meta_uri)
                        if isinstance(payload, dict):
                            uploaded_projects.add(project)
            except json.JSONDecodeError as exc:
                gh_warning(f"Invalid RUNNER_MATRIX JSON; skipping GCS runner pre-scan: {exc}")
        names = sorted(uploaded_projects)
        accepted = json.dumps(names)
        Path("accepted.txt").write_text(accepted)
        write_github_output(os.environ.get("GITHUB_OUTPUT"), "accepted_projects", accepted)
        gh_notice(f"Runners uploaded for projects: {accepted}")

    def summarize_matrix_handshake(self) -> None:
        w = self._ctx.workflow if self._ctx else None
        runner_matrix_raw = _ctx_str(w, "runner_matrix", "RUNNER_MATRIX", "{}")
        filtered_raw = _ctx_str(w, "filtered_matrix", "FILTERED_MATRIX", "{}")
        if not runner_matrix_raw or not filtered_raw:
            raise RuntimeError("RUNNER_MATRIX and FILTERED_MATRIX are required")
        json.loads(runner_matrix_raw)
        accepted_raw = _ctx_str(w, "accepted", "ACCEPTED", "[]")
        accepted = json.loads(accepted_raw)
        filtered_matrix = json.loads(filtered_raw)
        bmt_jobs = sorted({str(e.get("project", "")).strip() for e in filtered_matrix.get("include", []) if e})
        print(f"::notice::Matrix handshake: uploaded={len(accepted)} legs={len(bmt_jobs)}")
