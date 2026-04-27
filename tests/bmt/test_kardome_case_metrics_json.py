from __future__ import annotations

import json
import shutil
import stat
import tempfile
from pathlib import Path

from bmt_sdk.results import CaseResult

from runtime.kardome_case_metrics import (
    RUNNER_CASE_JSON_FORMAT_V1,
    read_metric_from_bmt_case_json,
    read_namuh_from_bmt_case_json,
)
from runtime.kardome_runparams import (
    KardomeRunparamsConfig,
    KardomeRunparamsExecutor,
    execution_mode_for_runparams_case_results,
)
from tests._support.minimal_wav import write_silence_wav

_REPO = Path(__file__).resolve().parents[2]
_SK_TEMPLATE = _REPO / "runtime/assets/sk_kardome_input_template.json"

_LIB_VER_FIXTURE = "3.0.0"


def test_read_metric_runner_case_json_false_alarms_mode() -> None:
    """Runner case JSON: calibration_kws false uses hi_namuh_count."""
    tmp = Path(tempfile.mkdtemp(prefix="bmt-case-"))
    try:
        wav_out = tmp / "one.wav"
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(
            json.dumps(
                {
                    "case_format": RUNNER_CASE_JSON_FORMAT_V1,
                    "kardome_lib_version": _LIB_VER_FIXTURE,
                    "calibration_kws": False,
                    "hi_namuh_count": 2,
                    "keyword_calib_count": 0,
                    "gleo_per_channel": [0, 1, 0, 0],
                    "paths": {
                        "mics": str(tmp / "in.wav"),
                        "refs": "/tmp/dummy/ref.wav",
                        "user_output": str(wav_out),
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        v, p, stub = read_metric_from_bmt_case_json(
            wav_out, metric_keys=("namuh_count", "hi_namuh_count", "namuh", "hi_namuh")
        )
        assert v == 2.0 and p == side
        assert stub is not None
        assert stub["case_format"] == RUNNER_CASE_JSON_FORMAT_V1
        assert stub.get("kardome_lib_version") == _LIB_VER_FIXTURE
        assert "gleo_per_channel_json" in stub
        assert "path_mics" in stub
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runner_case_json_lib_version_artifact_strips_trailing_date() -> None:
    """kardome_lib_version artifact is the first token of the version string."""
    short_ver = "11.1.1"
    tmp = Path(tempfile.mkdtemp(prefix="bmt-case-ver-"))
    try:
        wav = tmp / "a.wav"
        side = wav.with_suffix(".bmt.json")
        side.write_text(
            json.dumps(
                {
                    "case_format": RUNNER_CASE_JSON_FORMAT_V1,
                    "kardome_lib_version": f"{short_ver} Jan  1 2025 12:00:00",
                    "calibration_kws": False,
                    "hi_namuh_count": 0,
                    "keyword_calib_count": 0,
                    "gleo_per_channel": [],
                }
            ),
            encoding="utf-8",
        )
        _v, _p, stub = read_metric_from_bmt_case_json(wav, metric_keys=("hi_namuh_count", "namuh_count"))
        assert stub is not None
        assert stub.get("kardome_lib_version") == short_ver
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_metric_runner_case_json_calibration_mode_uses_calib_count() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bmt-case-"))
    try:
        wav_out = tmp / "c.wav"
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(
            json.dumps(
                {
                    "case_format": RUNNER_CASE_JSON_FORMAT_V1,
                    "calibration_kws": True,
                    "hi_namuh_count": 0,
                    "keyword_calib_count": 4,
                    "gleo_per_channel": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        v, _p, _st = read_metric_from_bmt_case_json(
            wav_out, metric_keys=("namuh_count", "hi_namuh_count", "namuh", "hi_namuh")
        )
        assert v == 4.0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_namuh_krdm_bmt_case_metrics_v1_shape() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "case.wav"
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(
            json.dumps(
                {
                    "hi_namuh_count": 9,
                    "namuh_count": 9,
                    "schema": "krdm_bmt_case_metrics_v1",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        n, p = read_namuh_from_bmt_case_json(wav_out)
        assert n == 9 and p == side
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_namuh_bmt_json_suffix() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "sub" / "case.wav"
        wav_out.parent.mkdir(parents=True)
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(json.dumps({"namuh_count": 7}) + "\n", encoding="utf-8")
        n, p = read_namuh_from_bmt_case_json(wav_out)
        assert n == 7 and p == side
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_namuh_bmt_result_stem() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "case.wav"
        side = tmp / "case_bmt_result.json"
        side.write_text(json.dumps({"metrics": {"hi_namuh_count": 2}}), encoding="utf-8")
        n, p = read_namuh_from_bmt_case_json(wav_out)
        assert n == 2 and p == side
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_metric_from_bmt_case_json_custom_key() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bmt-metrics-"))
    try:
        wav_out = tmp / "case.wav"
        side = wav_out.with_suffix(".bmt.json")
        side.write_text(json.dumps({"metrics": {"wake_hits": 3.5}}), encoding="utf-8")
        value, path, extra = read_metric_from_bmt_case_json(wav_out, metric_keys=("wake_hits",))
        assert value == 3.5
        assert path == side
        assert extra is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _runner_script_body(bmt_json_body: str | None) -> str:
    writer = (
        ""
        if bmt_json_body is None
        else f"pathlib.Path(str(out.with_suffix('.bmt.json'))).write_text({bmt_json_body!r}, encoding='utf-8')"
    )
    return f"""#!/usr/bin/env python3
import pathlib
import sys

def arg(flag):
    idx = sys.argv.index(flag)
    return sys.argv[idx + 1]

out = pathlib.Path(arg("--user-output"))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b"ok")
{writer}
print("Hi NAMUH counter = 999")
"""


def _make_executor(
    tmp_path: Path,
    runner_body: str,
    *,
    metric_name: str = "namuh_count",
    metric_json_keys: tuple[str, ...] = ("namuh_count", "hi_namuh_count", "namuh", "hi_namuh"),
) -> KardomeRunparamsExecutor:
    (tmp_path / "ds").mkdir(parents=True)
    write_silence_wav(tmp_path / "ds" / "one.wav")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "logs").mkdir()

    runner = tmp_path / "fake_runner.py"
    runner.write_text(runner_body, encoding="utf-8")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)

    return KardomeRunparamsExecutor(
        KardomeRunparamsConfig(
            runner_path=runner,
            template_path=_SK_TEMPLATE,
            dataset_root=tmp_path / "ds",
            runtime_root=tmp_path / "runtime",
            outputs_root=tmp_path / "outputs",
            logs_root=tmp_path / "logs",
            parsing={},
            metric_name=metric_name,
            metric_json_keys=metric_json_keys,
        )
    )


def test_metrics_json_is_required(tmp_path: Path) -> None:
    ex = _make_executor(tmp_path, _runner_script_body(bmt_json_body=None))
    result = ex.run()
    assert result.execution_mode_used == "kardome_legacy_metrics_json_missing"
    row = result.case_results[0]
    assert row.status == "failed"
    assert row.error == "metrics_json_missing"
    assert row.artifacts.get("metric_source") == "none"


def test_malformed_bmt_case_json_fails_case(tmp_path: Path) -> None:
    ex = _make_executor(tmp_path, _runner_script_body(bmt_json_body="{not json"))
    result = ex.run()
    row = result.case_results[0]
    assert row.status == "failed"
    assert row.error == "metrics_json_missing"


def test_bmt_case_json_without_counter_fails_case(tmp_path: Path) -> None:
    ex = _make_executor(tmp_path, _runner_script_body(bmt_json_body='{"other": 1}'))
    result = ex.run()
    row = result.case_results[0]
    assert row.status == "failed"
    assert row.error == "metrics_json_missing"


def test_execution_mode_json_only() -> None:
    cases = [
        CaseResult("a.wav", Path("a.wav"), 0, "ok", {}, {"metric_source": "metrics_json"}),
        CaseResult("_dataset_", Path("x"), -1, "failed", {}, {}),
    ]
    assert execution_mode_for_runparams_case_results(cases) == "kardome_legacy_metrics_json"


def test_executor_uses_configured_metric_name_and_keys(tmp_path: Path) -> None:
    ex = _make_executor(
        tmp_path,
        _runner_script_body(bmt_json_body='{"metrics": {"wake_hits": 11}}'),
        metric_name="wake_hits",
        metric_json_keys=("wake_hits",),
    )
    result = ex.run()
    row = result.case_results[0]
    assert row.status == "ok"
    assert row.metrics == {"wake_hits": 11.0}
