"""Terminal width detection for Rich layouts.

Bands use fixed thresholds (**60 · 80 · 100 · 120** columns) so contributor UIs
stay readable on phones, laptop splits, and wide terminals. Width comes from
:class:`rich.console.Console` (same basis Rich uses for wrapping).

========  =====  =======  ==========================================
Band      cols   Flags    Typical behaviour
========  =====  =======  ==========================================
**xs**    ≤60    tight+n  Extra stacking (footer links, run hints)
**sm**    ≤80    tight+n  Stacked footers, stacked quick-path hints
**md**    ≤100   narrow   Single-column tables; hints under commands
**lg**    ≤120   wide     Inline hints; two-column recipe table
**xl**    >120   wide     Full width; same layout as lg
========  =====  =======  ==========================================

Use :func:`rich_layout_profile` so contributor CLIs share one breakpoint story.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console

# Avoid unusable layouts on broken size reports.
_MIN_COLUMNS = 52

# Inclusive upper bounds for each band (see module docstring).
LAYOUT_XS_MAX = 60
LAYOUT_SM_MAX = 80
LAYOUT_MD_MAX = 100
LAYOUT_LG_MAX = 120


def detected_terminal_columns() -> int:
    """Return current terminal width in columns, with a sensible floor.

    Uses Rich's ``Console`` measurement so it stays aligned with how Rich wraps output.
    """
    return max(_MIN_COLUMNS, Console().size.width)


def layout_band(columns: int) -> int:
    """Return layout band index 0..4 for *columns* (after floor clamp)."""
    c = max(_MIN_COLUMNS, columns)
    if c <= LAYOUT_XS_MAX:
        return 0
    if c <= LAYOUT_SM_MAX:
        return 1
    if c <= LAYOUT_MD_MAX:
        return 2
    if c <= LAYOUT_LG_MAX:
        return 3
    return 4


def prefer_narrow_rich_layout(columns: int) -> bool:
    """True when tables should use a single combined column (≤100 cols)."""
    return layout_band(columns) <= 2


def prefer_tight_rich_layout(columns: int) -> bool:
    """True when footers and hints should stack vertically (≤80 cols)."""
    return layout_band(columns) <= 1


@dataclass(frozen=True)
class RichLayoutProfile:
    """Width-derived layout flags for contributor Rich UIs."""

    columns: int
    band: int

    @property
    def tight(self) -> bool:
        """≤80: stack doc/run footers and the “more recipes” hint."""
        return self.band <= 1

    @property
    def narrow(self) -> bool:
        """≤100: single-column recipe table; quick-path gloss under the command."""
        return self.band <= 2

    @property
    def wide(self) -> bool:
        return not self.narrow

    @property
    def xs(self) -> bool:
        """≤60: most constrained; shorten inline chrome where possible."""
        return self.band == 0

    @property
    def xl(self) -> bool:
        """>120: very wide terminal."""
        return self.band >= 4

    def table_width(self) -> int:
        """Width Rich should use for full-bleed tables (caps ultra-wide)."""
        if self.xl:
            return min(self.columns, 128)
        return self.columns


def rich_layout_profile(columns: int | None = None) -> RichLayoutProfile:
    """Resolve *columns* (default: live terminal) into band + derived flags."""
    c = detected_terminal_columns() if columns is None else max(_MIN_COLUMNS, columns)
    return RichLayoutProfile(columns=c, band=layout_band(c))
