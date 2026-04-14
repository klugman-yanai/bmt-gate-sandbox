"""Human-readable duration strings shared by Check Run markdown helpers."""

from __future__ import annotations


def format_duration_seconds(seconds: int | None) -> str:
    """Format duration for display (e.g. ``2m 15s``). ``None`` maps to an em dash."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes = seconds // 60
        remainder = seconds % 60
        return f"{minutes}m {remainder}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"
