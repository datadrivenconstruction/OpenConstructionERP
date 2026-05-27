"""‌⁠‍Tests that ``_try_cad2data`` builds v18 flag-CLI invocations when the
capability probe identifies a v18 binary.

Mirrors ``test_bim_converter_cli_tolerance`` (which exercises the v17 /
legacy paths) but with the v18 profile cached up-front.  The fake
subprocess routes calls by output-file-suffix walk over args[] rather
than the v17 ``args[2]`` shortcut, because v18 puts the output path
after a ``-x`` / ``-d`` flag.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    cad_import._CONVERTER_CAPABILITIES.clear()
    ifc_processor._LAST_DDC_FAILURE.clear()
    yield
    cad_import._CONVERTER_CAPABILITIES.clear()
    ifc_processor._LAST_DDC_FAILURE.clear()


def _fake_rvt(tmp_path: Path, name: str = "input.rvt") -> Path:
    p = tmp_path / name
    p.write_bytes(b"x" * 256)
    return p


def _fake_converter(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "converter_dir"
    bin_dir.mkdir()
    exe = bin_dir / "RvtExporter.exe"
    exe.write_bytes(b"x" * 4096)
    return exe


class _V18SubprocessRecorder:
    """‌⁠‍Records subprocess calls + materialises output files at the path
    that follows the ``-x`` / ``-d`` flag (v18 shape)."""

    def __init__(
        self,
        *,
        xlsx_rc: int = 0,
        dae_rc: int = 0,
        xlsx_stderr: bytes = b"",
        dae_stderr: bytes = b"",
    ) -> None:
        self.calls: list[list[str]] = []
        self.xlsx_rc = xlsx_rc
        self.dae_rc = dae_rc
        self.xlsx_stderr = xlsx_stderr
        self.dae_stderr = dae_stderr

    @staticmethod
    def _path_after_flag(args: list[str], flag: str) -> Path | None:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return Path(args[i + 1])
        return None

    def __call__(self, args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(args))
        xlsx = self._path_after_flag(args, "-x")
        dae = self._path_after_flag(args, "-d")

        if xlsx is not None and self.xlsx_rc == 0:
            xlsx.parent.mkdir(parents=True, exist_ok=True)
            xlsx.write_bytes(b"FAKE-XLSX")
        if dae is not None and self.dae_rc == 0:
            dae.parent.mkdir(parents=True, exist_ok=True)
            dae.write_bytes(b"FAKE-DAE")

        if xlsx is not None:
            return subprocess.CompletedProcess(args=args, returncode=self.xlsx_rc, stdout=b"", stderr=self.xlsx_stderr)
        if dae is not None:
            return subprocess.CompletedProcess(args=args, returncode=self.dae_rc, stdout=b"", stderr=self.dae_stderr)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    def xlsx_calls(self) -> list[list[str]]:
        return [c for c in self.calls if "-x" in c]

    def dae_calls(self) -> list[list[str]]:
        # A DAE-only call has ``-d`` but no ``-x``; the combined-pass case
        # is handled by xlsx_calls()'s membership check.
        return [c for c in self.calls if "-d" in c and "-x" not in c]


def _install_minimal_dependencies(monkeypatch: pytest.MonkeyPatch, *, converter: Path) -> None:
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: converter)
    fake_rows = [
        {
            "category": "OST_Walls",
            "name": "TestWall",
            "uniqueid": "guid-1",
            "level": "L1",
            "length": "5.0",
            "area": "12.5",
            "volume": "1.5",
        }
    ]
    monkeypatch.setattr(cad_import, "parse_cad_excel", lambda _path: fake_rows)


def test_v18_capability_drives_flag_based_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍End-to-end: cache the v18 capability profile, run ``_try_cad2data``,
    assert both the XLSX pass and the DAE pass use the v18 flag CLI
    (``-x out.xlsx --no-dae -m standard --force-path`` and
    ``-d out.dae --no-xlsx -m standard --force-path``)."""
    rvt = _fake_rvt(tmp_path)
    converter = _fake_converter(tmp_path)
    out_dir = tmp_path / "work"

    _install_minimal_dependencies(monkeypatch, converter=converter)
    cad_import._CONVERTER_CAPABILITIES[str(converter)] = cad_import._v18_capabilities(
        version_text="ddc revit community version: 18.3.0"
    )

    recorder = _V18SubprocessRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    result = ifc_processor._try_cad2data(rvt, out_dir, conversion_depth="standard")

    assert result is not None, "v18 path should produce a usable bim_result"
    # v18 is the CURRENT release — must NOT be flagged as outdated.
    assert result.get("converter_cli_outdated") is not True

    xlsx_calls = recorder.xlsx_calls()
    dae_calls = recorder.dae_calls()
    assert len(xlsx_calls) == 1, f"expected 1 XLSX pass, got {xlsx_calls}"
    assert len(dae_calls) == 1, f"expected 1 DAE pass, got {dae_calls}"

    # XLSX pass must use the v18 flag shape.
    xlsx_args = xlsx_calls[0]
    assert "-x" in xlsx_args
    assert "--no-dae" in xlsx_args
    assert "-m" in xlsx_args
    assert "standard" in xlsx_args
    assert "--force-path" in xlsx_args
    # And MUST NOT carry any of the v17 positional tokens that would crash v18.
    assert "-no-collada" not in xlsx_args, "v17 token must not appear in v18 invocation"

    # DAE pass: same shape with -d / --no-xlsx.
    dae_args = dae_calls[0]
    assert "-d" in dae_args
    assert "--no-xlsx" in dae_args
    assert "-m" in dae_args
    assert "--force-path" in dae_args
    assert "-no-collada" not in dae_args


def test_v18_complete_depth_emits_mode_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍``conversion_depth="complete"`` must surface as ``-m complete`` on
    the v18 flag CLI (the v18 ``-m`` enum is
    ``{basic,standard,complete,custom}``)."""
    rvt = _fake_rvt(tmp_path)
    converter = _fake_converter(tmp_path)
    out_dir = tmp_path / "work"

    _install_minimal_dependencies(monkeypatch, converter=converter)
    cad_import._CONVERTER_CAPABILITIES[str(converter)] = cad_import._v18_capabilities()

    recorder = _V18SubprocessRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    result = ifc_processor._try_cad2data(rvt, out_dir, conversion_depth="complete")
    assert result is not None
    assert recorder.xlsx_calls(), "no xlsx call recorded"

    xlsx_args = recorder.xlsx_calls()[0]
    # ``-m complete`` MUST be contiguous and the next-token-after-``-m`` MUST be ``complete``.
    idx = xlsx_args.index("-m")
    assert xlsx_args[idx + 1] == "complete"


def test_v18_exit_15_retries_with_reduced_v18_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍If v18 itself rejects something (e.g. user has a partial v18 build
    that doesn't grok --no-dae yet), the retry path must stay on the v18
    shape — never fall back to the v17 positional bare form that v18
    also can't parse.

    The recorder feeds an exit-15 + "arguments were not expected" stderr
    on the first call, then accepts the reduced retry.
    """
    rvt = _fake_rvt(tmp_path)
    converter = _fake_converter(tmp_path)
    out_dir = tmp_path / "work"

    _install_minimal_dependencies(monkeypatch, converter=converter)
    cad_import._CONVERTER_CAPABILITIES[str(converter)] = cad_import._v18_capabilities()

    # Mutate the recorder mid-flight: each .__call__ first returns exit 15,
    # then exits 0 on the retry.  We track per-(xlsx_or_dae) state because
    # both passes run in parallel threads.
    state = {"xlsx_calls": 0, "dae_calls": 0}

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        is_xlsx = "-x" in args
        key = "xlsx_calls" if is_xlsx else "dae_calls"
        state[key] += 1
        if state[key] == 1:
            return subprocess.CompletedProcess(
                args=args,
                returncode=15,
                stdout=b"",
                stderr=b"The following arguments were not expected: --some-flag\n",
            )
        # Retry — materialise the output file and report success.
        out_path = None
        for i, a in enumerate(args):
            if a in ("-x", "-d") and i + 1 < len(args):
                out_path = Path(args[i + 1])
                break
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"FAKE")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    calls: list[list[str]] = []

    def recording_fake_run(args: list[str], **kw: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(args))
        return fake_run(args, **kw)

    monkeypatch.setattr(subprocess, "run", recording_fake_run)

    result = ifc_processor._try_cad2data(rvt, out_dir, conversion_depth="standard")

    assert result is not None
    assert result.get("converter_cli_outdated") is True, (
        "retry success must surface as converter_cli_outdated for the UI badge"
    )

    # Retry must keep v18 shape: ``-x`` or ``-d`` flag + path, no
    # positional ``standard`` token.
    xlsx_calls = [c for c in calls if "-x" in c]
    assert len(xlsx_calls) >= 2, "expected at least one initial + one retry XLSX call"
    retry_xlsx = xlsx_calls[1]
    assert "-x" in retry_xlsx, "retry must keep the v18 -x flag"
    assert "standard" not in retry_xlsx, "retry must NOT emit v17 positional token"
    assert "-no-collada" not in retry_xlsx, "retry must NOT emit v17 -no-collada"
