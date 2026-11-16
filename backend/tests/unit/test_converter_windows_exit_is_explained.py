"""A converter killed by Windows reaches the user as a cause and a fix, not as -1073741674.

Four users reported the RVT converter failing on every file with that number,
also after reinstalling Visual C++. The pre-flight now checks the runtime before
spawning, and every path that reports a failed run names the Windows status.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import, ddc_runner


@pytest.fixture(autouse=True)
def _clear_health_cache() -> Any:
    cad_import._HEALTH_CACHE.clear()
    yield
    cad_import._HEALTH_CACHE.clear()


def test_a_killed_run_reports_the_windows_status_as_its_failure() -> None:
    run = ddc_runner.ConverterRun(fmt="rvt", command=[], returncode=-1073741674)
    failure = run.failure
    assert failure is not None
    assert failure["code"] == "STATUS_PRIVILEGED_INSTRUCTION"
    assert "0xC0000096" in failure["message_en"]
    assert "-1073741674" not in failure["message_en"]


def test_the_converters_own_error_still_wins() -> None:
    stdout = '{"error": {"code": "RVT_VERSION", "message_en": "Saved with a newer Revit."}}'
    run = ddc_runner.ConverterRun(fmt="rvt", command=[], returncode=-1073741674, stdout=stdout)
    assert run.failure == {"code": "RVT_VERSION", "message_en": "Saved with a newer Revit."}


def test_an_ordinary_exit_code_is_not_dressed_up() -> None:
    run = ddc_runner.ConverterRun(fmt="ifc", command=[], returncode=2)
    assert run.failure is None


@pytest.mark.parametrize(
    ("code", "cause"),
    [(-1073741674, "blocked_instruction"), (-1073741515, "runtime_missing"), (-1073741819, "native_crash")],
)
def test_the_cause_follows_the_windows_status(code: int, cause: str) -> None:
    assert ifc_processor._infer_failure_cause(reason="nonzero_exit", exit_code=code, stderr_text="") == cause


def test_a_plain_nonzero_exit_stays_unknown() -> None:
    assert ifc_processor._infer_failure_cause(reason="nonzero_exit", exit_code=15, stderr_text="") == "unknown"


def _installed(tmp_path: Path) -> Path:
    folder = tmp_path / "ifc_windows"
    folder.mkdir()
    exe = folder / "DDC_CONVERTER_IFC.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 2048)
    return exe


def test_preflight_refuses_a_converter_without_the_vc_runtime(tmp_path: Path) -> None:
    exe = _installed(tmp_path)
    spawn = mock.Mock()
    with (
        mock.patch.object(cad_import, "find_converter", return_value=exe),
        mock.patch.object(cad_import, "missing_companion_files", return_value=[]),
        mock.patch.object(cad_import, "missing_vc_runtime", return_value=["vcruntime140_1.dll"]),
        mock.patch("subprocess.run", spawn),
    ):
        health = cad_import.smoke_test_converter("ifc", force=True)
    assert health["status"] == "failed"
    assert "vcruntime140_1.dll" in health["message"]
    assert "install_vc_redist" in health["suggested_actions"]
    spawn.assert_not_called()


def test_preflight_explains_a_crash_at_start(tmp_path: Path) -> None:
    exe = _installed(tmp_path)
    completed = mock.Mock(returncode=-1073741819, stdout=b"", stderr=b"")
    with (
        mock.patch.object(cad_import, "find_converter", return_value=exe),
        mock.patch.object(cad_import, "missing_companion_files", return_value=[]),
        mock.patch.object(cad_import, "missing_vc_runtime", return_value=[]),
        mock.patch("subprocess.run", return_value=completed),
    ):
        health = cad_import.smoke_test_converter("ifc", force=True)
    assert health["status"] == "failed"
    assert "0xC0000005" in health["message"]
    assert "-1073741819" not in health["message"]
