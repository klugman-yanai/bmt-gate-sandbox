"""Tests for gcp.image.config.bmt_domain_status."""

from __future__ import annotations

import pytest

from runtime.config.bmt_domain_status import (
    BmtLegStatus,
    BmtProgressStatus,
    leg_status_is_fail,
    leg_status_is_pass,
    progress_status_is_in_flight,
    summary_dict_leg_passed,
)

pytestmark = pytest.mark.unit


def test_leg_pass_and_fail_synonym() -> None:
    assert leg_status_is_pass(BmtLegStatus.PASS.value)
    assert not leg_status_is_pass(BmtLegStatus.FAIL.value)
    assert leg_status_is_fail(BmtLegStatus.FAIL.value)
    assert leg_status_is_fail("failure")


def test_progress_in_flight() -> None:
    assert progress_status_is_in_flight(BmtProgressStatus.PENDING.value)
    assert progress_status_is_in_flight(BmtProgressStatus.RUNNING.value)
    assert not progress_status_is_in_flight(BmtLegStatus.PASS.value)


def test_summary_dict_leg_passed() -> None:
    assert summary_dict_leg_passed({"passed": True, "status": "fail"})
    assert summary_dict_leg_passed({"status": BmtLegStatus.PASS.value})
    assert not summary_dict_leg_passed({"status": BmtLegStatus.FAIL.value})
    assert not summary_dict_leg_passed({"passed": False, "status": BmtLegStatus.PASS.value})
