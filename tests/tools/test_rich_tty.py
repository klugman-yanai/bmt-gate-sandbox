"""TTY width helpers for Rich output."""

from __future__ import annotations

import pytest

from tools.shared.rich_tty import (
    LAYOUT_LG_MAX,
    LAYOUT_MD_MAX,
    LAYOUT_SM_MAX,
    LAYOUT_XS_MAX,
    layout_band,
    prefer_narrow_rich_layout,
    prefer_tight_rich_layout,
    rich_layout_profile,
)


@pytest.mark.parametrize(
    ("cols", "expected_band"),
    [
        (52, 0),
        (LAYOUT_XS_MAX, 0),
        (LAYOUT_XS_MAX + 1, 1),
        (LAYOUT_SM_MAX, 1),
        (LAYOUT_SM_MAX + 1, 2),
        (LAYOUT_MD_MAX, 2),
        (LAYOUT_MD_MAX + 1, 3),
        (LAYOUT_LG_MAX, 3),
        (LAYOUT_LG_MAX + 1, 4),
    ],
)
def test_layout_band_thresholds(cols: int, expected_band: int) -> None:
    assert layout_band(cols) == expected_band


def test_prefer_narrow_layout_at_100_101() -> None:
    assert prefer_narrow_rich_layout(LAYOUT_MD_MAX) is True
    assert prefer_narrow_rich_layout(LAYOUT_MD_MAX + 1) is False


def test_prefer_tight_layout_at_80_81() -> None:
    assert prefer_tight_rich_layout(LAYOUT_SM_MAX) is True
    assert prefer_tight_rich_layout(LAYOUT_SM_MAX + 1) is False


def test_rich_layout_profile_orders_flags() -> None:
    p121 = rich_layout_profile(columns=LAYOUT_LG_MAX + 1)
    assert p121.columns == LAYOUT_LG_MAX + 1
    assert p121.band == 4
    assert p121.tight is False
    assert p121.narrow is False
    assert p121.wide is True
    assert p121.xl is True
    assert p121.table_width() == min(p121.columns, 128)

    p120 = rich_layout_profile(columns=LAYOUT_LG_MAX)
    assert p120.band == 3
    assert p120.xl is False

    p100 = rich_layout_profile(columns=LAYOUT_MD_MAX)
    assert p100.tight is False
    assert p100.narrow is True
    assert p100.table_width() == LAYOUT_MD_MAX

    p80 = rich_layout_profile(columns=LAYOUT_SM_MAX)
    assert p80.tight is True
    assert p80.narrow is True

    p60 = rich_layout_profile(columns=LAYOUT_XS_MAX)
    assert p60.xs is True
    assert p60.tight is True
    assert p60.narrow is True
