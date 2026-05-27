"""‌⁠‍Unit tests for version-tolerant RvtExporter / IfcExporter invocation.

Pins the v4.6.2 fix for the user-reported bug:

    Converter failed (exit 15): The following arguments were not expected:
      C:\\Users\\diopm\\AppData\\Local\\Temp\\…\\original.xlsx standard -no-collada

The user's installed converter rejects ``standard`` and ``-no-collada``;
running the SAME binary without those tokens succeeds. The fix is two
layers deep:

  1. ``detect_converter_capabilities`` probes the binary up front so the
     first invocation already strips the unsupported tokens.
  2. If a binary slips past the probe (e.g. probe couldn't reach the
     binary but the conversion call can), exit-15 + an "unknown argument"
     stderr triggers a one-shot retry with bare ``[converter, in, out]``.

Both paths are exercised here. A successful retry must:
  * yield a non-None bim_result (geometry usable downstream)
  * stamp ``converter_cli_outdated=True`` on the result so the router
    propagates ``cause="converter_outdated"`` to the UI

A retry that *also* fails must:
  * record a DDC failure with ``cause="converter_outdated"`` so the
    Reinstall CTA renders on the error overlay.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import

# Stderr the user reported verbatim — keep this literal so a future
# regression in the substring matcher is caught here.
USER_REPORTED_STDERR = (
    b"The following arguments were not expected:\n"
    b"  C:\\Users\\diopm\\AppData\\Local\\Temp\\tmp-bim-bg-qkc0_dbs\\original.xlsx "
    b"standard -no-collada\n"
)


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """‌⁠‍Capability + failure caches must be empty per test so cases don't
    leak state into each other."""
    cad_import._CONVERTER_CAPABILITIES.clear()
    ifc_processor._LAST_DDC_FAILURE.clear()
    yield
    cad_import._CONVERTER_CAPABILITIES.clear()
    ifc_processor._LAST_DDC_FAILURE.clear()


def _fake_rvt(tmp_path: Path, name: str = "input.rvt") -> Path:
    """‌⁠‍Materialise a non-empty input file. The processor never reads its
    bytes (the converter would), so the contents don't matter."""
    p = tmp_path / name
    p.write_bytes(b"x" * 256)
    return p


def _fake_converter(tmp_path: Path) -> Path:
    """‌⁠‍Materialise a non-empty binary so ``find_converter``'s size guard
    accepts it."""
    bin_dir = tmp_path / "converter_dir"
    bin_dir.mkdir()
    exe = bin_dir / "RvtExporter.exe"
    exe.write_bytes(b"x" * 4096)
    return exe


class _SubprocessRecorder:
    """‌⁠‍Records every subprocess.run call and answers each one according
    to a per-output-target rule.

    Why per-output instead of FIFO: ``_try_cad2data`` runs the XLSX and
    COLLADA passes in parallel threads, so call order is non-deterministic.
    Routing by the third positional arg (output path) gives us a stable
    test regardless of thread scheduling.
    """

    def __init__(
        self,
        *,
        xlsx_answers: list[tuple[int, bytes, bytes]],
        dae_answers: list[tuple[int, bytes, bytes]],
        create_output_files: bool = True,
    ) -> None:
        self.xlsx_answers = list(xlsx_answers)
        self.dae_answers = list(dae_answers)
        self.calls: list[list[str]] = []
        self.create_output_files = create_output_files

    def __call__(self, args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(args))
        if len(args) < 3:
            raise RuntimeError(f"Unexpected subprocess.run shape: {args!r}")
        out_path = Path(args[2])
        if out_path.suffix.lower() in (".xlsx", ".xls"):
            queue = self.xlsx_answers
        elif out_path.suffix.lower() == ".dae":
            queue = self.dae_answers
        else:
            raise RuntimeError(f"Unexpected output extension: {out_path}")
        if not queue:
            raise RuntimeError(f"No more answers queued for {out_path}: {args!r}")
        rc, stdout, stderr = queue.pop(0)
        if rc == 0 and self.create_output_files:
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(b"FAKE-OUTPUT")
            except OSError:
                pass
        return subprocess.CompletedProcess(args=args, returncode=rc, stdout=stdout, stderr=stderr)

    def calls_for(self, suffix: str) -> list[list[str]]:
        """‌⁠‍Filter recorded calls by output suffix (``.xlsx`` / ``.dae``)."""
        out: list[list[str]] = []
        for call in self.calls:
            if len(call) >= 3 and Path(call[2]).suffix.lower() == suffix.lower():
                out.append(call)
        return out


def _install_minimal_dependencies(monkeypatch: pytest.MonkeyPatch, *, converter: Path) -> None:
    """‌⁠‍Patch the cad_import helpers consumed by ``_try_cad2data`` so the
    test focuses on the CLI-tolerance code path and ignores Excel parsing,
    converter discovery, etc."""
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: converter)

    # parse_cad_excel always returns a single fake element row so the
    # downstream code path treats the conversion as successful.
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


def test_exit_15_with_unknown_arg_stderr_retries_with_bare_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """‌⁠‍User-reported bug: exit 15 + 'arguments were not expected' on the
    first call. The retry path must fire and pass bare
    ``[converter, in, out]`` (no depth-mode, no -no-collada). On retry
    success the result carries ``converter_cli_outdated=True``."""
    rvt = _fake_rvt(tmp_path)
    converter = _fake_converter(tmp_path)
    out_dir = tmp_path / "work"

    _install_minimal_dependencies(monkeypatch, converter=converter)

    # Pretend the version probe found a modern banner — that way the
    # first invocation includes ``standard`` + ``-no-collada``, the retry
    # is forced to drop them, and we exercise the substring/exit-15
    # fallback (not the capability matrix). The COLLADA pass is
    # unmodified so it gets one answer too.
    cad_import._CONVERTER_CAPABILITIES[str(converter)] = cad_import._modern_capabilities(
        version_text="usage: RvtExporter input output [standard|complete] [-no-collada]"
    )

    recorder = _SubprocessRecorder(
        xlsx_answers=[
            # First attempt fails with user-reported stderr
            (15, b"", USER_REPORTED_STDERR),
            # Retry with bare args succeeds
            (0, b"", b""),
        ],
        dae_answers=[
            # COLLADA first attempt fails too
            (15, b"", USER_REPORTED_STDERR),
            # Retry succeeds
            (0, b"", b""),
        ],
    )
    monkeypatch.setattr(subprocess, "run", recorder)

    result = ifc_processor._try_cad2data(rvt, out_dir, conversion_depth="standard")

    assert result is not None, "Retry path should have produced a usable bim_result"
    assert result.get("converter_cli_outdated") is True

    # The first XLSX call MUST have shipped the modern tokens (probe said
    # the binary was modern). The retry XLSX call MUST be bare.
    xlsx_calls = recorder.calls_for(".xlsx")
    assert len(xlsx_calls) == 2, f"Expected 1 initial + 1 retry XLSX; got {xlsx_calls}"
    assert "standard" in xlsx_calls[0]
    assert "-no-collada" in xlsx_calls[0]
    assert "standard" not in xlsx_calls[1]
    assert "-no-collada" not in xlsx_calls[1]
    assert len(xlsx_calls[1]) == 3, f"retry must be bare [exe, in, out]; got {xlsx_calls[1]}"

    # COLLADA pass: first call has 'standard' (depth-mode), second is bare.
    dae_calls = recorder.calls_for(".dae")
    assert len(dae_calls) == 2
    assert "standard" in dae_calls[0]
    assert "-no-collada" not in dae_calls[0]  # COLLADA pass never asks for -no-collada
    assert "standard" not in dae_calls[1]
    assert len(dae_calls[1]) == 3


def test_capability_matrix_strips_tokens_up_front(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍When the probe has already flagged the binary as legacy, the very
    first XLSX call must omit ``standard`` and ``-no-collada`` — no
    retry needed. ``converter_cli_outdated`` is still set on the result
    so the UI can warn the user to reinstall."""
    rvt = _fake_rvt(tmp_path)
    converter = _fake_converter(tmp_path)
    out_dir = tmp_path / "work"

    _install_minimal_dependencies(monkeypatch, converter=converter)

    # Probe already concluded "old CLI" — capability flags are False.
    cad_import._CONVERTER_CAPABILITIES[str(converter)] = cad_import._default_capabilities()

    recorder = _SubprocessRecorder(
        xlsx_answers=[(0, b"", b"")],
        dae_answers=[(0, b"", b"")],
    )
    monkeypatch.setattr(subprocess, "run", recorder)

    result = ifc_processor._try_cad2data(rvt, out_dir, conversion_depth="standard")

    assert result is not None
    assert result.get("converter_cli_outdated") is True
    # Two calls total, both bare. No retries.
    assert len(recorder.calls) == 2
    for call in recorder.calls:
        assert "standard" not in call
        assert "-no-collada" not in call
        assert len(call) == 3


def test_genuine_failure_with_unrelated_stderr_does_not_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍A non-zero exit whose stderr doesn't mention 'unknown argument'
    must NOT trigger the retry path — otherwise we'd silently re-run a
    crashing converter with stripped flags and produce misleading
    success/failure pairs. Records cause != ``converter_outdated``."""
    rvt = _fake_rvt(tmp_path)
    converter = _fake_converter(tmp_path)
    out_dir = tmp_path / "work"

    _install_minimal_dependencies(monkeypatch, converter=converter)
    cad_import._CONVERTER_CAPABILITIES[str(converter)] = cad_import._modern_capabilities()

    # Exit 1 + unrelated stderr — license error simulator.
    license_err = b"License probe failed: cannot contact activation server\n"
    recorder = _SubprocessRecorder(
        xlsx_answers=[(1, b"", license_err)],
        dae_answers=[(1, b"", license_err)],
        create_output_files=False,  # failure -> no output file materialised
    )
    monkeypatch.setattr(subprocess, "run", recorder)

    result = ifc_processor._try_cad2data(rvt, out_dir, conversion_depth="standard")

    assert result is None
    # Exactly one call per pass — no retry triggered. (COLLADA may or
    # may not have run depending on thread scheduling; assert there's no
    # spurious third XLSX call which would indicate a wrongful retry.)
    assert len(recorder.calls_for(".xlsx")) == 1
    failure = ifc_processor.last_ddc_failure()
    assert failure.get("cause") != "converter_outdated", (
        "License errors must not be misclassified as a CLI outdated issue"
    )


def test_both_attempts_fail_records_converter_outdated_cause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍Both the original and the bare-retry invocations fail with the
    user-reported stderr. The router consumes the recorded cause to
    decide whether to show the Reinstall CTA; that cause must be
    ``converter_outdated`` so the user sees the right fix path."""
    rvt = _fake_rvt(tmp_path)
    converter = _fake_converter(tmp_path)
    out_dir = tmp_path / "work"

    _install_minimal_dependencies(monkeypatch, converter=converter)
    cad_import._CONVERTER_CAPABILITIES[str(converter)] = cad_import._modern_capabilities()

    recorder = _SubprocessRecorder(
        xlsx_answers=[
            (15, b"", USER_REPORTED_STDERR),
            (15, b"", USER_REPORTED_STDERR),  # bare retry also fails
        ],
        dae_answers=[
            (15, b"", USER_REPORTED_STDERR),
            (15, b"", USER_REPORTED_STDERR),
        ],
        create_output_files=False,
    )
    monkeypatch.setattr(subprocess, "run", recorder)

    result = ifc_processor._try_cad2data(rvt, out_dir, conversion_depth="standard")

    assert result is None
    failure = ifc_processor.last_ddc_failure()
    assert failure.get("cause") == "converter_outdated"
    assert failure.get("reason") == "nonzero_exit"


def test_infer_failure_cause_handles_each_input_class() -> None:
    """‌⁠‍Direct unit test for the heuristic — pins each branch of the
    decision tree so future stderr phrasings can be added safely."""
    # Direct stderr marker → converter_outdated regardless of exit code
    assert (
        ifc_processor._infer_failure_cause(
            reason="nonzero_exit", exit_code=15, stderr_text="arguments were not expected"
        )
        == "converter_outdated"
    )
    assert (
        ifc_processor._infer_failure_cause(reason="nonzero_exit", exit_code=1, stderr_text="Unknown argument: --foo")
        == "converter_outdated"
    )

    # Exit 15 alone (e.g. terse runtime) → converter_outdated as a safe
    # default — Reinstall is the only one-click fix anyway.
    assert (
        ifc_processor._infer_failure_cause(reason="nonzero_exit", exit_code=15, stderr_text="") == "converter_outdated"
    )

    # Other failures keep their existing labels.
    assert ifc_processor._infer_failure_cause(reason="timeout", exit_code=None, stderr_text="") == "timeout"
    assert ifc_processor._infer_failure_cause(reason="empty_output", exit_code=0, stderr_text="") == "empty_output"
    assert (
        ifc_processor._infer_failure_cause(reason="nonzero_exit", exit_code=1, stderr_text="License denied")
        == "unknown"
    )


def test_record_ddc_failure_accepts_explicit_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """‌⁠‍The retry path passes ``cause="converter_outdated"`` explicitly
    so the heuristic doesn't override it. Confirms the override path."""
    # Stub away the version helpers so the test doesn't depend on disk.
    monkeypatch.setattr(
        cad_import,
        "detect_converter_version",
        lambda _ext: {"version": None, "source": None, "binary_path": None},
    )
    monkeypatch.setattr(
        cad_import,
        "read_rvt_revit_version",
        lambda _path: {"format": None, "build": None, "app_name": None},
    )

    ifc_processor._record_ddc_failure(
        "rvt",
        "nonzero_exit",
        exit_code=1,
        stderr=b"completely unrelated error message",
        ifc_path=None,
        cause="converter_outdated",
    )

    failure = ifc_processor.last_ddc_failure()
    assert failure["cause"] == "converter_outdated"
    assert failure["reason"] == "nonzero_exit"
