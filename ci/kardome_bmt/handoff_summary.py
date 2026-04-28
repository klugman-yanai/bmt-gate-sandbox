"""Step summary markdown for BMT handoff."""

from __future__ import annotations

import json
import os
from pathlib import Path

from kardome_bmt.config import BmtConfig
from kardome_bmt.handoff_env import HandoffEnv, canonical_repo_slug_for_github_links


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


def _cell(text: str) -> str:
    return text.replace("\n", " ").replace("|", "\\|")


def _diagnostics_artifact_name(env: HandoffEnv) -> str:
    custom = (os.environ.get("DIAGNOSTICS_ARTIFACT") or "").strip()
    if custom:
        return custom
    if env.run_id:
        return f"bmt-handoff-diagnostics-{env.run_id}"
    return "bmt-handoff-diagnostics"


def _matrix_leg_count_and_projects(filtered_matrix_raw: str) -> tuple[int, list[str]]:
    try:
        parsed = json.loads(filtered_matrix_raw)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
    except (json.JSONDecodeError, TypeError):
        return 0, []
    rows = (parsed if isinstance(parsed, dict) else {}).get("include", [])
    if not isinstance(rows, list):
        return 0, []
    projects: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        p = str(row.get("project", "")).strip()
        if p and p not in seen:
            seen.add(p)
            projects.append(p)
    return len(rows), projects


def _maybe_verbose_matrix_block(filtered_matrix_raw: str) -> str:
    if (os.environ.get("BMT_HANDOFF_VERBOSE_SUMMARY") or "").strip() != "1":
        return ""
    body = filtered_matrix_raw.strip() or '{"include":[]}'
    try:
        pretty = json.dumps(json.loads(body), indent=2)
    except (json.JSONDecodeError, TypeError):
        pretty = body
    return f"\n<details><summary>Filtered matrix (JSON)</summary>\n\n```json\n{pretty}\n```\n\n</details>\n"


def write_handoff_step_summary(cfg: BmtConfig, env: HandoffEnv) -> None:
    repo_slug = canonical_repo_slug_for_github_links(env)
    run_url = f"{env.server}/{repo_slug}/actions/runs/{env.run_id}" if env.run_id else ""
    repo_url = f"{env.server}/{repo_slug}"
    pr_url = f"{repo_url}/pull/{env.pr_number}" if env.pr_number else ""

    leg_count, matrix_projects = _matrix_leg_count_and_projects(env.filtered_matrix_raw)

    try:
        accepted = json.loads(env.accepted_projects_raw)
        if isinstance(accepted, str):
            accepted = json.loads(accepted)
    except (json.JSONDecodeError, TypeError):
        accepted = []
    subtask_projects = [str(p).strip() for p in (accepted if isinstance(accepted, list) else []) if str(p).strip()]
    if not subtask_projects:
        subtask_projects = matrix_projects

    projects_label = ", ".join(subtask_projects) if subtask_projects else "none"
    legs_suffix = f" x{leg_count}" if leg_count else ""

    git_bits: list[str] = []
    if pr_url and env.pr_number:
        git_bits.append(f"[PR #{env.pr_number}]({pr_url})")
    git_bits.append(f"`{env.head_sha[:7]}`" if len(env.head_sha) >= 7 else f"`{env.head_sha}`")
    git_bits.append(f"`{env.head_branch}`")
    git_line = " · ".join(git_bits)

    exec_url = (os.environ.get("WORKFLOW_EXECUTION_URL") or "").strip()
    exec_state = (os.environ.get("WORKFLOW_EXECUTION_STATE") or "").strip()
    classify_outcome = (os.environ.get("CLASSIFY_OUTCOME") or "").strip()
    invoke_outcome = (os.environ.get("INVOKE_OUTCOME") or "").strip()
    dispatch_reason = (os.environ.get("DISPATCH_REASON") or "").strip()
    force_pass_active = (os.environ.get("BMT_FORCE_PASS_RESOLVED") or "").strip() == "true"

    lines: list[str] = ["## BMT", ""]

    if env.mode == "failure":
        lines.append(f"- **Git:** {_cell(git_line)}")
        if run_url:
            lines.append(f"- **Run:** [{_cell('Handoff workflow')}]({run_url})")
        gcp_project = _gcp_project_for_summary(cfg)
        gcs_bucket = _gcs_bucket_for_summary(cfg)
        storage_bits = [f"`{gcp_project}`" if gcp_project else "", f"`{gcs_bucket}`" if gcs_bucket else ""]
        storage_line = " · ".join(s for s in storage_bits if s)
        if storage_line:
            lines.append(f"- **Storage:** {_cell(storage_line)}")
        lines.append(f"- **Scope:** {_cell(projects_label)}{legs_suffix}")
        if classify_outcome or invoke_outcome:
            c = classify_outcome or "n/a"
            i = invoke_outcome or "n/a"
            lines.append(f"- **Steps:** classify `{c}` · invoke `{i}`")
        if dispatch_reason:
            lines.append(f"- **Reason code:** `{_cell(dispatch_reason)}`")
        if exec_url:
            state = exec_state or "unknown"
            lines.append(f"- **Cloud:** [{_cell('GCP execution')}]({exec_url}) (`{state}`)")
        lines.append("")
        if env.failure_reason:
            lines.append(_fenced_text_snippet(env.failure_reason))
            lines.append("")
        lines.append(f"- **Debug:** `{_diagnostics_artifact_name(env)}`")
        lines.append("")
        lines.append("_Inspect the failing steps above; BMT verdict (if any) remains in **Checks**._")
        lines.append(_maybe_verbose_matrix_block(env.filtered_matrix_raw))
        _append_step_summary("\n".join(lines) + "\n")
        return

    lines.append(f"- **Git:** {_cell(git_line)}")
    if run_url:
        lines.append(f"- **Run:** [{_cell('Handoff workflow')}]({run_url})")

    ok = env.dispatch_confirmed
    cloud_bits: list[str] = []
    if exec_url:
        label = "GCP execution"
        if exec_state:
            cloud_bits.append(f"[{label}]({exec_url}) (`{exec_state}`)")
        else:
            cloud_bits.append(f"[{label}]({exec_url})")
    elif exec_state:
        cloud_bits.append(f"`{exec_state}`")
    cloud_bits.append(f"**{projects_label}**{legs_suffix} · cloud {'confirmed' if ok else 'not confirmed'}")
    lines.append(f"- **Cloud:** {_cell(' · '.join(cloud_bits))}")
    if force_pass_active and ok:
        lines.append(
            "- **Force pass:** dispatch enabled — Cloud Run runs the **full** BMT workload; see **Checks** for results."
        )

    gcp_project = _gcp_project_for_summary(cfg)
    gcs_bucket = _gcs_bucket_for_summary(cfg)
    storage_bits = [f"`{gcp_project}`" if gcp_project else "", f"`{gcs_bucket}`" if gcs_bucket else ""]
    storage_line = " · ".join(s for s in storage_bits if s)
    if storage_line:
        lines.append(f"- **Storage:** {_cell(storage_line)}")

    lines.append(f"- **Debug:** `{_diagnostics_artifact_name(env)}`")
    lines.append("")
    if env.mode != "failure":
        lines.append("_BMT result will appear in the PR **Checks** tab and commit status._")
    lines.append(_maybe_verbose_matrix_block(env.filtered_matrix_raw))
    _append_step_summary("\n".join(lines) + "\n")
