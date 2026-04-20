"""Release marker at ``gs://$BUCKET/_state/release.json``.

The release marker is the single source of truth tying together the four BMT
surfaces that a given git commit produced:

- **Cloud Run image**: manifest digest in Artifact Registry.
- **GCS plugins**: content-hash of the ``plugins/`` mirror as synced to the bucket.
- **PEX**: the ``bmt-vX.Y.Z`` tag whose release asset is what ``setup-bmt-pex`` resolves to.
- **Pulumi stack**: hash of ``pulumi stack export`` capturing current infra state.

Only the ``release.yml`` GitHub Actions workflow writes this marker. The
``Handoff / Plan`` job reads it and asserts that ``git_sha`` matches the
workflow's ``github.sha`` before dispatching the cloud workflow. A mismatch or
missing marker means ``release.yml`` did not complete for this commit and the
cloud pipeline would otherwise be running against stale artifacts — the
assertion fails loud with an actionable message.

See ``docs/superpowers/plans/2026-04-18-ci-driven-release.md`` for the full
architecture.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from kardome_bmt import gcs

__all__ = [
    "MARKER_PATH",
    "ReleaseMarker",
    "ReleaseMarkerMismatchError",
    "assert_matches",
    "marker_uri",
    "read",
    "write",
]


MARKER_PATH = "_state/release.json"
"""Object path within the bucket."""

_REMEDIATION = (
    "The `release.yml` workflow is the sole producer of this marker; "
    "a missing or stale marker means release.yml did not complete for this commit. "
    "See docs/superpowers/plans/2026-04-18-ci-driven-release.md."
)


class ReleaseMarkerMismatchError(RuntimeError):
    """Raised when the release marker is missing, malformed, or disagrees with the expected ``git_sha``.

    Always carries an actionable remediation pointer in the message so CI logs
    surface the fix path without the reader needing to open source to decode it.
    """


@dataclass(frozen=True, slots=True)
class ReleaseMarker:
    """Single-source-of-truth marker for a four-surface BMT release.

    ``image_digest`` / ``plugins_sha`` / ``pex_tag`` / ``pulumi_stack_sha`` may be
    ``None`` when the corresponding release step was skipped (path-filtered) and
    no previous value existed to carry forward. Consumers reading those fields
    should treat ``None`` as "surface was not touched by this release".
    """

    git_sha: str
    image_digest: str | None
    plugins_sha: str | None
    pex_tag: str | None
    pulumi_stack_sha: str | None
    built_at: str

    @classmethod
    def from_mapping(cls, payload: Any) -> ReleaseMarker:
        """Parse a loaded JSON payload into a marker.

        Raises ``ReleaseMarkerMismatchError`` when the payload is not a mapping with
        the required fields, so callers do not need to double-guard on schema.
        """
        if not isinstance(payload, dict):
            raise ReleaseMarkerMismatchError(
                f"release marker is malformed: expected a JSON object, got {type(payload).__name__}. {_REMEDIATION}"
            )
        git_sha = payload.get("git_sha")
        if not isinstance(git_sha, str) or not git_sha:
            raise ReleaseMarkerMismatchError(
                f"release marker is malformed: missing or non-string 'git_sha'. {_REMEDIATION}"
            )
        built_at = payload.get("built_at")
        if not isinstance(built_at, str) or not built_at:
            raise ReleaseMarkerMismatchError(
                f"release marker is malformed: missing or non-string 'built_at'. {_REMEDIATION}"
            )
        return cls(
            git_sha=git_sha,
            image_digest=_optional_str(payload.get("image_digest"), "image_digest"),
            plugins_sha=_optional_str(payload.get("plugins_sha"), "plugins_sha"),
            pex_tag=_optional_str(payload.get("pex_tag"), "pex_tag"),
            pulumi_stack_sha=_optional_str(payload.get("pulumi_stack_sha"), "pulumi_stack_sha"),
            built_at=built_at,
        )


def _optional_str(value: Any, field: str) -> str | None:
    """Accept ``None``/``""``/``str`` for optional fields; reject anything else with a clear error."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    raise ReleaseMarkerMismatchError(
        f"release marker is malformed: field {field!r} is {type(value).__name__}, expected string or null. {_REMEDIATION}"
    )


def marker_uri(bucket: str) -> str:
    """Return the full ``gs://bucket/_state/release.json`` URI for the given bucket."""
    if not bucket:
        raise ValueError("bucket name is empty")
    return f"gs://{bucket}/{MARKER_PATH}"


def write(bucket: str, marker: ReleaseMarker) -> None:
    """Write the marker to GCS. GCS object PUT is atomic, so no explicit temp+rename is required."""
    gcs.upload_json(marker_uri(bucket), asdict(marker))


def read(bucket: str) -> ReleaseMarker | None:
    """Return the marker if present, ``None`` if the object does not exist.

    Propagates :class:`kardome_bmt.gcs.GcsError` for infrastructure failures so
    callers never treat an auth/network outage as "marker missing".
    """
    uri = marker_uri(bucket)
    if not gcs.object_exists(uri):
        return None
    payload, err = gcs.download_json(uri)
    if err is not None or payload is None:
        raise ReleaseMarkerMismatchError(
            f"release marker at {uri} could not be read: {err or 'empty payload'}. {_REMEDIATION}"
        )
    return ReleaseMarker.from_mapping(payload)


def assert_matches(bucket: str, git_sha: str) -> None:
    """Verify the bucket's release marker matches ``git_sha``, else raise.

    Failure modes, all raising :class:`ReleaseMarkerMismatchError`:

    - **Marker missing** — release.yml did not complete for this commit.
    - **Marker malformed** — file exists but is not valid JSON / schema.
    - **git_sha mismatch** — marker is for a different commit; cloud artifacts
      do not match the code that's about to be validated against them.
    """
    if not git_sha:
        raise ValueError("git_sha is empty; cannot assert match")

    uri = marker_uri(bucket)
    if not gcs.object_exists(uri):
        raise ReleaseMarkerMismatchError(
            f"release marker is missing at {uri}. Expected git_sha={git_sha[:12]}. {_REMEDIATION}"
        )

    marker = read(bucket)
    if marker is None:
        raise ReleaseMarkerMismatchError(
            f"release marker at {uri} was not readable after existence check. {_REMEDIATION}"
        )

    if marker.git_sha != git_sha:
        raise ReleaseMarkerMismatchError(
            f"release marker mismatch at {uri}: "
            f"expected git_sha={git_sha[:12]}, marker reports {marker.git_sha[:12]} "
            f"(built_at={marker.built_at}). {_REMEDIATION}"
        )
