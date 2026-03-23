"""GitHub Check Runs API integration for BMT Gate (Checks tab).

Output format per docs/architecture.md (GitHub and CI): pass/fail, scores, logs. The Check Run
appears on the PR Checks tab; branch protection can require it to pass before merge.
"""

import json
from typing import Any, NotRequired, TypedDict

import httpx

from gcp.image.config.constants import HTTP_TIMEOUT
from gcp.image.github.github_auth import github_api_headers

# GitHub REST API documents large max for check run output fields; stay under a safe UTF-8 byte cap.
GITHUB_CHECK_OUTPUT_FIELD_MAX_BYTES = 65535


def clamp_utf8_by_bytes(text: str, max_bytes: int = GITHUB_CHECK_OUTPUT_FIELD_MAX_BYTES) -> str:
    """Truncate ``text`` so its UTF-8 encoding does not exceed ``max_bytes`` (valid Unicode suffix)."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    truncated = raw[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


class CheckRunOutput(TypedDict):
    """GitHub Checks API ``output`` object (``text`` and ``annotations`` optional)."""

    title: str
    summary: str
    text: NotRequired[str]
    annotations: NotRequired[list[dict[str, Any]]]


def _normalize_check_output(output: CheckRunOutput | dict[str, Any]) -> dict[str, Any]:
    """Omit empty optional ``text`` / ``annotations``; GitHub accepts title + summary only."""
    out = {k: v for k, v in output.items() if v is not None}
    if isinstance(out.get("summary"), str):
        out["summary"] = clamp_utf8_by_bytes(out["summary"])
    if isinstance(out.get("text"), str):
        out["text"] = clamp_utf8_by_bytes(out["text"])
    if out.get("text") == "":
        out.pop("text", None)
    if not out.get("annotations"):
        out.pop("annotations", None)
    return out


def _check_run_id_from_create_response(response: httpx.Response) -> int:
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise ValueError("GitHub check-runs create response was not valid JSON") from e
    if not isinstance(data, dict):
        raise TypeError("GitHub check-runs create response JSON must be an object")
    raw_id = data.get("id")
    if not isinstance(raw_id, int):
        raise TypeError("GitHub check-runs create response missing integer id field")
    return raw_id


def create_check_run(
    token: str,
    repo: str,
    sha: str,
    name: str,
    status: str,
    output: CheckRunOutput | dict[str, Any],
    *,
    details_url: str | None = None,
    external_id: str | None = None,
) -> int:
    """Create a GitHub Check Run.

    Args:
        token: GitHub token with checks:write permission
        repo: Repository in format "owner/name"
        sha: Commit SHA
        name: Check run name (e.g., "BMT Gate")
        status: Check run status ("queued", "in_progress", "completed")
        output: Output dict with ``title``, ``summary``, and optional ``text`` (Markdown)

    Returns:
        Check run ID for future updates

    Raises:
        httpx.HTTPError: If the GitHub API request fails
        ValueError: If the response body is not valid JSON
        TypeError: If the decoded JSON is not an object or ``id`` is not an integer
    """
    url = f"https://api.github.com/repos/{repo}/check-runs"
    headers = github_api_headers(token)

    payload: dict[str, Any] = {
        "name": name,
        "head_sha": sha,
        "status": status,
        "output": _normalize_check_output(output),
    }
    if details_url:
        payload["details_url"] = details_url
    if external_id:
        payload["external_id"] = external_id

    response = httpx.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return _check_run_id_from_create_response(response)


def update_check_run(
    token: str,
    repo: str,
    check_run_id: int,
    status: str | None = None,
    conclusion: str | None = None,
    output: CheckRunOutput | dict[str, Any] | None = None,
    details_url: str | None = None,
) -> None:
    """Update an existing Check Run.

    Args:
        token: GitHub token with checks:write permission
        repo: Repository in format "owner/name"
        check_run_id: ID returned from create_check_run
        status: New status ("in_progress", "completed"), or None to keep current
        conclusion: Conclusion when status="completed" ("success", "failure", etc.)
        output: New output dict with ``title``, ``summary``, optional ``text``, or None to keep current

    Raises:
        httpx.HTTPError: If the GitHub API request fails
    """
    url = f"https://api.github.com/repos/{repo}/check-runs/{check_run_id}"
    headers = github_api_headers(token)

    payload: dict[str, Any] = {}
    if status is not None:
        payload["status"] = status
    if conclusion is not None:
        payload["conclusion"] = conclusion
    if output is not None:
        payload["output"] = _normalize_check_output(output)
    if details_url is not None:
        payload["details_url"] = details_url

    response = httpx.patch(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
