"""Step summary markdown for BMT handoff."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ci.config import BmtConfig
from ci.handoff_env import HandoffEnv, canonical_repo_slug_for_github_links


def _append_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        raise RuntimeError("GITHUB_STEP_SUMMARY is not set")
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(text)


def _fenced_text_snippet(body: str) -> str:
    fence = "`" * 3
    while fence in body:
        fence += "`"
    return f"{fence}text\n{body}\n{fence}\n"


def _gcp_project_for_summary(cfg: BmtConfig) -> str:
    return (cfg.gcp_project or os.environ.get("GCP_PROJECT", "") or "").strip()


def _gcs_bucket_for_summary(cfg: BmtConfig) -> str:
    return (cfg.gcs_bucket or os.environ.get("GCS_BUCKET", "") or "").strip()


def write_handoff_step_summary(cfg: BmtConfig, env: HandoffEnv) -> None:
    repo_slug = canonical_repo_slug_for_github_links(env)
    run_url = f"{env.server}/{repo_slug}/actions/runs/{env.run_id}" if env.run_id else ""
    repo_url = f"{env.server}/{repo_slug}"
    pr_url = f"{repo_url}/pull/{env.pr_number}" if env.pr_number else ""

    _matrix = json.loads(env.filtered_matrix_raw)
    if isinstance(_matrix, str):
        _matrix = json.loads(_matrix)
    matrix_include = (_matrix if isinstance(_matrix, dict) else {}).get("include", [])

    _accepted = json.loads(env.accepted_projects_raw)
    if isinstance(_accepted, str):
        _accepted = json.loads(_accepted)
    subtask_projects = [
        str(p).strip() for p in (_accepted if isinstance(_accepted, list) else []) if str(p).strip()
    ]
    if not subtask_projects and isinstance(matrix_include, list):
        seen: set[str] = set()
        for row in matrix_include:
            if isinstance(row, dict) and "project" in row:
                p = str(row.get("project", "")).strip()
                if p and p not in seen:
                    seen.add(p)
                    subtask_projects.append(p)

    link_parts = []
    if pr_url:
        link_parts.append(f"PR [#{env.pr_number}]({pr_url})")
    if run_url:
        link_parts.append(f"[Workflow run]({run_url})")
    link_parts.append(f"`{env.head_sha[:7]}` on `{env.head_branch}`")
    links_line = " · ".join(link_parts)

    subtasks_display = ", ".join(subtask_projects) if subtask_projects else "—"
    ok = env.dispatch_confirmed
    status_line = (
        f"**Cloud job:** ✅ Confirmed · **Subtasks:** {subtasks_display}"
        if ok
        else f"**Cloud job:** ❌ Not confirmed · **Subtasks:** {subtasks_display}"
    )
    gcp_project = _gcp_project_for_summary(cfg)
    gcs_bucket = _gcs_bucket_for_summary(cfg)
    lines = [
        "## BMT Handoff",
        "",
        links_line,
        "",
        status_line,
        "",
    ]
    if gcp_project or gcs_bucket:
        infra_bits: list[str] = []
        if gcp_project:
            infra_bits.append(f"**GCP:** `{gcp_project}`")
        if gcs_bucket:
            infra_bits.append(f"**Bucket:** `{gcs_bucket}`")
        lines.append(" · ".join(infra_bits))
        lines.append("")
    if env.failure_reason:
        lines.append(_fenced_text_snippet(env.failure_reason))
        lines.append("")
    if env.mode != "failure":
        lines.append("_BMT result will appear in the PR **Checks** tab and commit status._")
    else:
        lines.append("_Inspect the trigger and dispatch steps above for details._")
    _append_step_summary("\n".join(lines) + "\n")
