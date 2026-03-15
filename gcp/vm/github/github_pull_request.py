"""GitHub pull request state helpers for VM-side run cancellation decisions."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from gcp.vm.config.constants import GITHUB_API_VERSION
from gcp.vm.utils import _now_iso


def get_pr_state(
    token: str,
    repository: str,
    pr_number: int,
    *,
    attempts: int = 3,
    timeout_sec: int = 10,
) -> dict[str, str | bool | None]:
    """Fetch PR state from GitHub.

    Returns a dict with:
    - state: open|closed|unknown
    - merged: bool|None
    - head_sha: str|None
    - checked_at: ISO8601 timestamp
    - error: error string|None

    This function never raises; unknown state is returned on failures.
    """
    checked_at = _now_iso()
    unknown = {
        "state": "unknown",
        "merged": None,
        "head_sha": None,
        "checked_at": checked_at,
        "error": None,
    }

    if not token or not repository or pr_number <= 0:
        unknown["error"] = "invalid_input"
        return unknown

    owner, _, repo = repository.partition("/")
    if not owner or not repo:
        unknown["error"] = "invalid_repository"
        return unknown

    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    max_attempts = max(1, int(attempts or 1))
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                raw_state = str(payload.get("state", "")).strip().lower()
                if raw_state not in {"open", "closed"}:
                    raw_state = "unknown"
                merged_raw = payload.get("merged")
                merged = merged_raw if isinstance(merged_raw, bool) else None
                head_raw = payload.get("head")
                head_sha: str | None = None
                if isinstance(head_raw, dict):
                    head_sha_raw = head_raw.get("sha")
                    if isinstance(head_sha_raw, str):
                        head_sha = head_sha_raw.strip() or None
                return {
                    "state": raw_state,
                    "merged": merged,
                    "head_sha": head_sha,
                    "checked_at": checked_at,
                    "error": None,
                }
        except urllib.error.HTTPError as exc:
            last_error = f"http_{exc.code}"
            # Retry only transient/rate-limited responses.
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = f"network_error: {exc}"
        except json.JSONDecodeError as exc:
            last_error = f"invalid_json: {exc}"
            break

        if attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 5))

    unknown["error"] = last_error or "unknown_error"
    return unknown
