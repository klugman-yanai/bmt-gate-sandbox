"""Runner: upload to GCS, validate in repo, filter upload matrix, resolve uploaded, summarize."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

from whenever import Instant

from bmtgate import core
from bmtgate import settings as config
from bmtgate.clients import gcs
from bmtgate.clients.actions import gh_notice, gh_warning, write_github_output
from bmtgate.contract.env_parse import is_truthy_env_value
from bmtgate.handoff.env import read_workflow_str
from bmtgate.matrix.provenance import write_runner_provenance
from bmtgate.settings import BmtConfig, BmtContext, WorkflowContext


def _project_has_bmt_stage_layout(project: str) -> bool:
    """True when this repo declares BMT for ``project`` under ``benchmarks/projects/<project>/``."""
    slug = str(project).strip().lower()
    if not slug:
        return False
    base = Path(core.DEFAULT_STAGE_ROOT) / "projects" / slug
    return (
        (base / "project.json").is_file()
        or (base / "bmts").is_dir()
        or (base / "benchmarks").is_dir()
    )


def _runner_meta_in_gcs(root: str, project: str, _preset: str) -> dict[str, Any] | None:
    for name in ("runner_meta.json", "runner_latest_meta.json"):
        payload, _ = gcs.download_json(f"{root}/projects/{project}/{name}")
        if isinstance(payload, dict):
            return payload
    return None


def _project_has_bmts_in_bucket(root: str, project: str) -> bool:
    """True when the bucket has objects under ``projects/<project>/benchmarks/`` or ``.../bmts/``."""
    slug = str(project).strip().lower()
    if not slug:
        return False
    base = root.rstrip("/")
    for suffix in ("benchmarks/", "bmts/"):
        prefix_uri = f"{base}/projects/{slug}/{suffix}"
        try:
            if len(gcs.list_prefix(prefix_uri)) > 0:
                return True
        except gcs.GcsError as exc:
            gh_warning(
                f"Could not list bucket BMT prefix for project {slug!r} ({exc}); "
                "treating as no bucket BMT layout (dev publish matrix will omit this project)."
            )
            return False
    return False


def _append_filter_matrix_step_summary(
    *,
    omitted_bucket: list[tuple[str, str]],
    skipped_preseeded: list[tuple[str, str]],
    skipped_same_ref: list[tuple[str, str]],
    trimmed_production: list[tuple[str, str, str]],
    publish_keys: list[str],
) -> None:
    """Compact note for legs omitted/skipped vs publish matrix (graph view hides reasons)."""
    path_raw = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path_raw:
        return
    path = Path(path_raw)
    pub = ", ".join(f"`{k}`" for k in publish_keys) if publish_keys else "*(none)*"
    lines: list[str] = [
        "## Upload matrix",
        "",
        f"**Publish:** {len(publish_keys)} — {pub}",
    ]
    extras: list[str] = []
    if omitted_bucket:
        extras.append(
            "**No bucket BMT:** "
            + ", ".join(f"`{p}/{pr}`" for p, pr in omitted_bucket)
            + " *(no `projects/…/benchmarks/` or `…/bmts/`)*"
        )
    if skipped_preseeded:
        extras.append("**Preseeded:** " + ", ".join(f"`{p}/{pr}`" for p, pr in skipped_preseeded))
    if skipped_same_ref:
        extras.append(
            "**Same SHA in GCS:** " + ", ".join(f"`{p}/{pr}`" for p, pr in skipped_same_ref)
        )
    if trimmed_production:
        extras.append(
            "**Prod trim:** "
            + "; ".join(f"`{p}/{pr}` ({reason})" for p, pr, reason in trimmed_production)
        )
    if extras:
        lines.append("")
        lines.extend(extras)
    lines.append("")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


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
        if is_truthy_env_value(os.environ.get("BMT_DEV_MANIFEST_ONLY")):
            self._write_handoff_uploaded_marker()
            return
        project = core.require_env("PROJECT")
        preset = core.require_env("PRESET")
        root = core.workflow_runtime_root()
        canonical_runner_uri = f"{root}/projects/{project}/kardome_runner"
        try:
            exists = gcs.object_exists(canonical_runner_uri)
        except gcs.GcsError as exc:
            raise RuntimeError(f"Failed to verify runner in GCS at {canonical_runner_uri}: {exc}") from exc
        if exists:
            print(
                f"::notice::Requested runner exists in bucket: {canonical_runner_uri} (validated for handoff)."
            )
        else:
            local_candidates = (
                Path(core.DEFAULT_STAGE_ROOT) / project / "runners" / preset / "kardome_runner",
                Path(core.DEFAULT_STAGE_ROOT) / "projects" / project / "kardome_runner",
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
        self._write_handoff_uploaded_marker()

    def _write_handoff_uploaded_marker(self) -> None:
        project = core.require_env("PROJECT")
        run_id = _ci_run_id_for_markers()
        root = core.workflow_runtime_root()
        marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
        try:
            gcs.write_object(marker_uri, "{}")
        except gcs.GcsError as exc:
            raise RuntimeError(f"Failed to write uploaded marker {marker_uri}: {exc}") from exc
        print(f"Marked project {project} as validated for handoff -> {marker_uri}")

    def upload_dev_publish_manifest(self) -> None:
        """Upload a dev-placeholder manifest (no binaries) under ``_workflow/dev_publish_manifest/``."""
        self._cfg.require_gcp()
        project = core.require_env("PROJECT")
        preset = core.require_env("PRESET")
        source_ref = (os.environ.get("SOURCE_REF") or "").strip()
        root = core.workflow_runtime_root()
        run_id = _ci_run_id_for_markers()
        safe_key = f"{project}__{preset}".replace("/", "_")
        uri = f"{root}/_workflow/dev_publish_manifest/{run_id}/{safe_key}.json"
        dest_runner = f"{root}/projects/{project}/kardome_runner"
        dest_lib = f"{root}/projects/{project}/libKardome.so"
        payload: dict[str, Any] = {
            "kind": "bmt_ci_dev_publish_manifest",
            "schema_version": 1,
            "project": project,
            "preset": preset,
            "source_ref": source_ref,
            "would_publish": {
                "kardome_runner": dest_runner,
                "libKardome.so": dest_lib,
            },
            "note": (
                "CI dev placeholder: caller has no runner-* artifact; this manifest records "
                "the layout that a real publish would upload."
            ),
            "uploaded_at": Instant.now().format_iso(unit="second"),
        }
        gcs.upload_json(uri, payload)
        print(f"::notice::Wrote dev publish manifest -> {uri}")

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
                f.write(f"matrix_publish_omitted<<OMIT_EOF\n{json.dumps(out)}\nOMIT_EOF\n")
                f.write("matrix_publish_omitted_keys=[]\n")
            print(
                "::notice::Filter upload matrix: BMT_SKIP_PUBLISH_RUNNERS=true — no publish jobs (runners assumed in bucket)."
            )
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary_path:
                with Path(summary_path).open("a", encoding="utf-8") as sf:
                    sf.write(
                        "## Upload matrix\n\n"
                        "**Skipped** — `BMT_SKIP_PUBLISH_RUNNERS`; no publish jobs.\n\n"
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
        omitted_bucket: list[tuple[str, str]] = []
        omitted_bucket_rows: list[dict[str, Any]] = []
        skipped_preseeded: list[tuple[str, str]] = []
        skipped_same_ref: list[tuple[str, str]] = []
        for entry in include:
            if not isinstance(entry, dict):
                continue
            project = str(entry.get("project", "")).strip()
            preset = str(entry.get("preset", "")).strip()
            if not project or not preset:
                continue
            allow_synthetic_unsupported = project == "ci_dev_unsupported" and is_truthy_env_value(
                os.environ.get("BMT_DEV_APPEND_UNSUPPORTED_RUNNER_LEG")
            )
            if not allow_synthetic_unsupported and not _project_has_bmts_in_bucket(root, project):
                omitted_bucket.append((project, preset))
                sr = cast(dict[str, Any], dict(entry))
                sr["shadow"] = True
                omitted_bucket_rows.append(sr)
                print(
                    f"::notice::Omit {project}/{preset} from publish matrix: "
                    f"no objects under projects/{project.lower()}/benchmarks/ or .../bmts/ in bucket."
                )
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
                    skipped_preseeded.append((project, preset))
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
                    skipped_same_ref.append((project, preset))
                    print(
                        f"::notice::Skip upload for {project}/{preset}: already on GCS for ref {head_sha[:7]} (will show as Skipped)."
                    )
                    continue
            if skip_missing and f"runner-{preset}" not in artifact_set:
                row_m = cast(dict[str, Any], dict(entry))
                row_m["bmt_supported"] = supported
                row_m["publish_mode"] = "manifest_only"
                publish_include.append(row_m)
                if supported == "true":
                    need_include.append(dict(entry))
                print(
                    f"::notice::Dev manifest-only publish leg for {project}/{preset} "
                    "(skip_missing_runner_artifacts; no runner-* artifact on caller run)."
                )
                continue
            row = cast(dict[str, Any], dict(entry))
            row["bmt_supported"] = supported
            row["publish_mode"] = "binary"
            publish_include.append(row)
            if supported == "true":
                need_include.append(dict(entry))
        out = {"include": need_include}
        out_json = json.dumps(out, separators=(",", ":"))
        # Bucket: omit legs with no objects under projects/<p>/benchmarks/ or .../bmts/ (dev and prod).
        # Dev skip_missing adds manifest-only legs for supported presets missing runner-* artifacts.
        # Production publish_for_workflow: supported + binary only (after publish_include).
        publish_for_workflow: list[dict[str, Any]]
        if skip_missing:
            publish_for_workflow = publish_include
        else:
            publish_for_workflow = [
                r
                for r in publish_include
                if str(r.get("bmt_supported", "")).strip() == "true"
                and str(r.get("publish_mode", "")).strip() == "binary"
            ]
        pub_wf = {"include": publish_for_workflow}
        pub_json = json.dumps(pub_wf, separators=(",", ":"))
        path = Path(core.require_env("GITHUB_OUTPUT"))
        with path.open("a", encoding="utf-8") as f:
            f.write(f"matrix_need_upload<<FILTER_EOF\n{out_json}\nFILTER_EOF\n")
            keys = [f"{e['project']}|{e['preset']}" for e in need_include]
            f.write(f"matrix_need_upload_keys={json.dumps(keys)}\n")
            f.write(f"matrix_publish<<PUBLISH_EOF\n{pub_json}\nPUBLISH_EOF\n")
            pub_keys = [f"{e['project']}|{e['preset']}" for e in publish_for_workflow]
            f.write(f"matrix_publish_keys={json.dumps(pub_keys)}\n")
            pub_omit = {"include": omitted_bucket_rows}
            omit_json = json.dumps(pub_omit, separators=(",", ":"))
            f.write(f"matrix_publish_omitted<<OMIT_EOF\n{omit_json}\nOMIT_EOF\n")
            omit_keys = [f"{e['project']}|{e['preset']}" for e in omitted_bucket_rows]
            f.write(f"matrix_publish_omitted_keys={json.dumps(omit_keys)}\n")
        skipped_gcs = len(include) - len(publish_include)
        trimmed = len(publish_include) - len(publish_for_workflow)
        trim_note = ""
        if not skip_missing and trimmed > 0:
            trim_note = (
                f" ({trimmed} leg(s) not in workflow matrix: unsupported or non-binary upload)"
            )
        print(
            f"::notice::Filter upload matrix: {len(need_include)} supported leg(s) for handoff; "
            f"{len(publish_include)} internal publish row(s); {skipped_gcs} row(s) omitted (already on GCS); "
            f"workflow matrix {len(publish_for_workflow)} leg(s){trim_note}."
        )
        trimmed_production: list[tuple[str, str, str]] = []
        if not skip_missing:
            wf_key_set = set(pub_keys)
            for r in publish_include:
                k = f"{r['project']}|{r['preset']}"
                if k in wf_key_set:
                    continue
                sup = str(r.get("bmt_supported", "")).strip()
                mode = str(r.get("publish_mode", "")).strip()
                if sup != "true":
                    trimmed_production.append(
                        (
                            str(r["project"]),
                            str(r["preset"]),
                            "Unsupported project (no benchmarks BMT layout).",
                        )
                    )
                elif mode != "binary":
                    trimmed_production.append(
                        (
                            str(r["project"]),
                            str(r["preset"]),
                            "Manifest-only or non-binary leg; production workflow matrix is binary-only.",
                        )
                    )
                else:
                    trimmed_production.append(
                        (
                            str(r["project"]),
                            str(r["preset"]),
                            "Excluded from workflow publish matrix.",
                        )
                    )
        _append_filter_matrix_step_summary(
            omitted_bucket=omitted_bucket,
            skipped_preseeded=skipped_preseeded,
            skipped_same_ref=skipped_same_ref,
            trimmed_production=trimmed_production,
            publish_keys=pub_keys,
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
