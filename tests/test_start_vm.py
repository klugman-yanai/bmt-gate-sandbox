"""Tests for .github/scripts/ci/commands/start_vm.py — project derivation from SA email."""

import pytest

from ci.commands.start_vm import _project_from_sa_email


def test_project_from_sa_email_standard():
    assert _project_from_sa_email("bmt-runner@train-kws-202311.iam.gserviceaccount.com") == "train-kws-202311"
    assert _project_from_sa_email("my-sa@my-project.iam.gserviceaccount.com") == "my-project"


def test_project_from_sa_email_whitespace():
    assert _project_from_sa_email("  bmt@proj.iam.gserviceaccount.com  ") == "proj"


def test_project_from_sa_email_invalid_returns_none():
    assert _project_from_sa_email("") is None
    assert _project_from_sa_email("no-at-sign") is None
    assert _project_from_sa_email("user@gmail.com") is None
    assert _project_from_sa_email("x@other.domain.com") is None
