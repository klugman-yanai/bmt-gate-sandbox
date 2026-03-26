"""Step summary markdown for BMT handoff."""

from __future__ import annotations

import json
import os
from pathlib import Path

from bmt_gate.config import BmtConfig
from bmt_gate.handoff_env import HandoffEnv, canonical_repo_slug_for_github_links


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
    pr_url = f"{env.server}/{repo_slug}/pull/{env.pr_number}" if env.pr_number else ""

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

    ok = env.dispatch_confirmed
    bits: list[str] = []
    if pr_url:
        bits.append(f"[PR #{env.pr_number}]({pr_url})")
    if run_url:
        bits.append(f"[Run]({run_url})")
    bits.append(f"`{env.head_sha[:7]}`")
    bits.append("dispatch OK" if ok else "dispatch **not** confirmed")
    proj_s = ", ".join(subtask_projects) if subtask_projects else "—"
    bits.append(f"projects: {proj_s}")

    lines = [
        "## Handoff",
        "",
        " · ".join(bits),
        "",
    ]
    gcp_project = _gcp_project_for_summary(cfg)
    gcs_bucket = _gcs_bucket_for_summary(cfg)
    if gcp_project or gcs_bucket:
        infra = " · ".join(
            x
            for x in (
                f"GCP `{gcp_project}`" if gcp_project else "",
                f"bucket `{gcs_bucket}`" if gcs_bucket else "",
            )
            if x
        )
        lines.extend([infra, ""])
    if env.failure_reason:
        lines.append(_fenced_text_snippet(env.failure_reason))
        lines.append("")
    _append_step_summary("\n".join(lines) + "\n")
