"""Path builders for coordination-plane objects and result artifacts."""

from __future__ import annotations

from hashlib import sha256

from bmtcontract.constants import CI_VERDICT_JSON, CURRENT_JSON, LATEST_JSON, LOG_DUMPS_PREFIX


def plan_path(workflow_run_id: str) -> str:
    return f"triggers/plans/{workflow_run_id}.json"


def summary_path(workflow_run_id: str, project: str, bmt_slug: str) -> str:
    return f"triggers/summaries/{workflow_run_id}/{project}-{bmt_slug}.json"


def progress_path(workflow_run_id: str, project: str, bmt_slug: str) -> str:
    return f"triggers/progress/{workflow_run_id}/{project}-{bmt_slug}.json"


def reporting_metadata_path(workflow_run_id: str) -> str:
    return f"triggers/reporting/{workflow_run_id}.json"


def dispatch_receipt_path(workflow_run_id: str) -> str:
    return f"triggers/dispatch/{workflow_run_id}.json"


def finalization_record_path(workflow_run_id: str) -> str:
    return f"triggers/finalization/{workflow_run_id}.json"


def pr_active_execution_path(pr_number: str) -> str:
    return f"triggers/reporting/pr-active/{pr_number}.json"


def results_pointer_path(results_path: str) -> str:
    return f"{results_path}/{CURRENT_JSON}"


def snapshot_root(results_path: str, run_id: str) -> str:
    return f"{results_path}/snapshots/{run_id}"


def latest_result_path(results_path: str, run_id: str) -> str:
    return f"{snapshot_root(results_path, run_id)}/{LATEST_JSON}"


def verdict_result_path(results_path: str, run_id: str) -> str:
    return f"{snapshot_root(results_path, run_id)}/{CI_VERDICT_JSON}"


def case_digest_result_path(results_path: str, run_id: str) -> str:
    return f"{snapshot_root(results_path, run_id)}/case_digest.json"


def log_dump_path(workflow_run_id: str) -> str:
    return f"{LOG_DUMPS_PREFIX}/{workflow_run_id}.txt"


def results_path_lease_key(results_path: str) -> str:
    return sha256(results_path.encode("utf-8")).hexdigest()[:32]


def lease_object_path(lease_key: str) -> str:
    return f"triggers/leases/{lease_key}.json"
