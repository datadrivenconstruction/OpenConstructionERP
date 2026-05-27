"""‌⁠‍Unit tests for the v18 flag-driven CLI profile added in Task #164.

DDC v18.3.0 ships a new ``RvtExporter --help`` layout:

    OPTIONS:
      -x,     --xlsx PATH         XLSX output (on by default; PATH overrides auto-name)
      -d,     --dae PATH          Collada output (on by default; PATH overrides auto-name)
              --no-dae            Disable Collada output
              --no-xlsx           Disable XLSX output
      -m,     --mode TEXT:{basic,standard,complete,custom} [standard]
              --force-path        Don't add timestamp suffix to existing output paths

It REJECTS the legacy v17 positional output + ``standard`` + ``-no-collada``
shape with ``exit 15: The following arguments were not expected``.

The previous substring-based capability probe false-positively detected
the v18 binary as "modern" because the help text contains the word
``complete`` (in the mode-preset enum), which matched the legacy
``_MODERN_HELP_MARKERS``.  This test suite pins:

  1. Token-based ``_classify_help_text`` returns ``v18_flag`` for the v18
     help blob and ``v17_positional`` for the v17 help blob — even though
     both contain the word ``complete``.
  2. ``detect_converter_capabilities`` now wires a v18 binary to the v18
     capability profile (``cli_profile=v18_flag``, all the new ``-x`` /
     ``-d`` / ``--no-dae`` / ``--force-path`` flags True).
  3. ``build_ddc_args`` emits the right v18 command line for an XLSX
     pass, a DAE pass, and a combined pass — and the legacy positional
     shape for the v17 profile.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.boq import cad_import

# Real v18.3.0 ``RvtExporter --help`` output (captured from the binary
# at ~/.openestimator/converters/rvt_windows/RvtExporter.exe).  Pinning
# the literal text here means a future CLI change that drops one of the
# v18-exclusive tokens shows up as a test failure instead of a silent
# regression in production.
V18_HELP_TEXT = """\
===========================================
         DataDrivenConstruction
         DDC Revit Community
         Version: 18.3.0
===========================================

RvtExporter — Revit to XLSX/DAE/JSON/CSV/OBJ/glTF converter


Usage: [OPTIONS] [input]


POSITIONALS:
  input TEXT                  Input .rvt / .rfa file

OPTIONS:
  -h,     --help              Print this help message and exit
          --force-path        Don't add timestamp suffix to existing output paths
[Option Group: Data outputs]
  Element properties and parameters


OPTIONS:
  -x,     --xlsx PATH         XLSX output (on by default; PATH overrides auto-name)
  -j,     --json PATH         Enable JSON output (optional PATH; auto-named if omitted)
          --csv PATH          Enable CSV output (optional PATH; auto-named if omitted)
          --no-xlsx           Disable XLSX output
[Option Group: Geometry outputs]
  3D scene formats


OPTIONS:
  -d,     --dae PATH          Collada output (on by default; PATH overrides auto-name)
          --obj PATH          Enable Wavefront OBJ output (.mtl sidecar; optional PATH)
          --gltf PATH         Enable glTF output
          --no-dae            Disable Collada output
[Option Group: Export mode]
  Category preset + custom override


OPTIONS:
  -m,     --mode TEXT:{basic,standard,complete,custom} [standard]
                              Export mode preset
  -c,     --categories PATH   Category list file (required when --mode custom)
"""

# Synthetic v17 help text — the older positional CLI that DOES accept
# ``standard`` and ``-no-collada`` and DOES NOT advertise the v18-exclusive
# ``--no-dae`` / ``--no-xlsx`` / ``--force-path`` tokens.
V17_HELP_TEXT = """\
RvtExporter v17.2.1
Usage: RvtExporter <input.rvt> <output.xlsx> [standard|complete] [-no-collada]

Converts Revit files to Excel + Collada output.
"""

# Synthetic legacy banner — pre-v17 binary that knows nothing beyond
# positional input + output.
LEGACY_HELP_TEXT = """\
RvtExporter v3.0.0
Usage: RvtExporter <input.rvt> <output.xlsx>
"""


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    cad_import._CONVERTER_CAPABILITIES.clear()
    yield
    cad_import._CONVERTER_CAPABILITIES.clear()


def _fake_binary(tmp_path: Path, name: str = "RvtExporter") -> Path:
    binary = tmp_path / name
    binary.write_bytes(b"x" * 4096)
    return binary


def _stub_subprocess(monkeypatch: pytest.MonkeyPatch, *, stdout: bytes) -> dict[str, int]:
    """‌⁠‍Replace subprocess.run with a fake that returns the given stdout."""
    import subprocess as _subprocess

    counter = {"calls": 0}

    class _Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = stdout
            self.stderr = b""

    def fake_run(*_args: object, **_kwargs: object) -> _Proc:
        counter["calls"] += 1
        return _Proc()

    monkeypatch.setattr(_subprocess, "run", fake_run)
    return counter


# ── Token classifier ──────────────────────────────────────────────────────


def test_v18_help_text_classified_as_v18_flag() -> None:
    """‌⁠‍The literal v18.3.0 help blob must classify as v18 even though it
    contains the word ``complete`` (which used to false-positive the
    substring-based ``_MODERN_HELP_MARKERS``)."""
    profile = cad_import._classify_help_text(V18_HELP_TEXT.lower())
    assert profile == cad_import.CLI_PROFILE_V18_FLAG


def test_v17_help_text_classified_as_v17_positional() -> None:
    """‌⁠‍The v17 help text (still in the wild on older installs) must keep
    being routed to the v17 positional profile so the existing CLI works."""
    profile = cad_import._classify_help_text(V17_HELP_TEXT.lower())
    assert profile == cad_import.CLI_PROFILE_V17_POSITIONAL


def test_legacy_help_text_classified_as_legacy() -> None:
    """‌⁠‍A bare ``Usage: RvtExporter <in> <out>`` banner with no v18 or v17
    markers stays on the conservative legacy profile."""
    profile = cad_import._classify_help_text(LEGACY_HELP_TEXT.lower())
    assert profile == cad_import.CLI_PROFILE_LEGACY


def test_classify_handles_punctuation_around_tokens() -> None:
    """‌⁠‍CLI11 help formatters sometimes append commas after flag aliases
    (``--no-dae, --skip-collada``).  The tokenizer must strip trailing
    punctuation so an alias-list still triggers the v18 detection."""
    blob = "options:\n    --no-dae,    disable collada output\n"
    assert cad_import._classify_help_text(blob) == cad_import.CLI_PROFILE_V18_FLAG


def test_classify_word_complete_alone_does_not_imply_v18() -> None:
    """‌⁠‍Bare ``complete`` (in any English-language context) must NOT
    trigger v18 — it has to be one of the v18-exclusive flag tokens.
    This is the regression that the new probe is specifically designed
    to prevent."""
    blob = "the export is complete after the standard parsing step"
    # Lacks all v18 AND v17 tokens → legacy.
    assert cad_import._classify_help_text(blob) == cad_import.CLI_PROFILE_LEGACY


# ── Capability detection ──────────────────────────────────────────────────


def test_v18_binary_probe_returns_v18_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍End-to-end probe: stub subprocess to return the v18 help blob,
    assert the cached capability dict has the v18 flag profile and all
    the new flag capabilities flipped to True."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    _stub_subprocess(monkeypatch, stdout=V18_HELP_TEXT.encode("utf-8"))

    caps = cad_import.detect_converter_capabilities("rvt")

    assert caps["cli_profile"] == cad_import.CLI_PROFILE_V18_FLAG
    assert caps["accepts_flag_xlsx"] is True
    assert caps["accepts_flag_dae"] is True
    assert caps["accepts_flag_no_dae"] is True
    assert caps["accepts_flag_no_xlsx"] is True
    assert caps["accepts_flag_mode"] is True
    assert caps["accepts_flag_force_path"] is True
    # v18 doesn't accept the legacy positional output or -no-collada
    assert caps["accepts_depth_mode"] is False
    assert caps["accepts_no_collada_flag"] is False
    assert caps["legacy_positional_input_output"] is False


def test_v17_binary_probe_returns_v17_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍v17 binaries stay on the v17 positional profile — the existing
    fix from v4.6.2 keeps working."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    _stub_subprocess(monkeypatch, stdout=V17_HELP_TEXT.encode("utf-8"))

    caps = cad_import.detect_converter_capabilities("rvt")

    assert caps["cli_profile"] == cad_import.CLI_PROFILE_V17_POSITIONAL
    assert caps["accepts_depth_mode"] is True
    assert caps["accepts_no_collada_flag"] is True
    # v17 doesn't know any of the v18 flags
    assert caps["accepts_flag_no_dae"] is False
    assert caps["accepts_flag_force_path"] is False


def test_legacy_binary_probe_returns_legacy_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍A binary that emits no recognised flag tokens stays on the legacy
    bare-positional profile.  This is the user-reported v4.6.2 path that
    must not regress."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    _stub_subprocess(monkeypatch, stdout=LEGACY_HELP_TEXT.encode("utf-8"))

    caps = cad_import.detect_converter_capabilities("rvt")

    assert caps["cli_profile"] == cad_import.CLI_PROFILE_LEGACY
    assert caps["accepts_depth_mode"] is False
    assert caps["accepts_no_collada_flag"] is False
    assert caps["accepts_flag_no_dae"] is False


def test_v18_help_with_complete_token_does_not_trigger_v17(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """‌⁠‍THE regression test for task #164: the v18 binary's help mentions
    ``complete`` in the ``{basic,standard,complete,custom}`` mode enum.
    The previous substring-based probe used that as a "modern v17" signal
    and emitted ``standard`` + ``-no-collada`` against a v18 binary, which
    crashed with exit 15.  The token-based probe must classify this as
    v18 and NEVER as v17 positional."""
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: binary)
    _stub_subprocess(monkeypatch, stdout=V18_HELP_TEXT.encode("utf-8"))

    caps = cad_import.detect_converter_capabilities("rvt")

    # Critical guarantee: the depth-mode + -no-collada legacy booleans
    # must remain False on v18 so ifc_processor never emits the v17
    # positional shape against a v18 binary.
    assert caps["accepts_depth_mode"] is False, (
        "v18 binary must NOT advertise depth-mode acceptance — the legacy "
        "positional ``standard`` token crashes v18 with exit 15"
    )
    assert caps["accepts_no_collada_flag"] is False, (
        "v18 binary must NOT advertise -no-collada acceptance — v18 dropped that flag in favour of --no-dae"
    )


# ── Invocation builder ────────────────────────────────────────────────────


def _v18_caps() -> dict[str, object]:
    return cad_import._v18_capabilities(version_text=V18_HELP_TEXT)


def _v17_caps() -> dict[str, object]:
    return cad_import._modern_capabilities(version_text=V17_HELP_TEXT)


def test_build_args_v18_xlsx_only_pass(tmp_path: Path) -> None:
    """‌⁠‍v18 XLSX-only pass: input + ``-x`` + path + ``--no-dae`` (suppress
    DAE since we don't want it) + ``-m standard`` + ``--force-path``."""
    converter = tmp_path / "RvtExporter.exe"
    input_path = tmp_path / "in.rvt"
    xlsx_out = tmp_path / "out.xlsx"

    args = cad_import.build_ddc_args(
        converter,
        input_path,
        caps=_v18_caps(),
        xlsx_out=xlsx_out,
        mode="standard",
        include_no_dae=True,
    )

    assert args == [
        str(converter),
        str(input_path),
        "-x",
        str(xlsx_out),
        "--no-dae",
        "-m",
        "standard",
        "--force-path",
    ]


def test_build_args_v18_dae_only_pass(tmp_path: Path) -> None:
    """‌⁠‍v18 DAE-only pass: input + ``-d`` + path + ``--no-xlsx`` +
    ``-m standard`` + ``--force-path``."""
    converter = tmp_path / "RvtExporter.exe"
    input_path = tmp_path / "in.rvt"
    dae_out = tmp_path / "out.dae"

    args = cad_import.build_ddc_args(
        converter,
        input_path,
        caps=_v18_caps(),
        dae_out=dae_out,
        mode="standard",
        include_no_xlsx=True,
    )

    assert args == [
        str(converter),
        str(input_path),
        "-d",
        str(dae_out),
        "--no-xlsx",
        "-m",
        "standard",
        "--force-path",
    ]


def test_build_args_v18_combined_pass(tmp_path: Path) -> None:
    """‌⁠‍v18 combined pass: both ``-x`` and ``-d`` in the same call so the
    RVT only loads once for both outputs."""
    converter = tmp_path / "RvtExporter.exe"
    input_path = tmp_path / "in.rvt"
    xlsx_out = tmp_path / "out.xlsx"
    dae_out = tmp_path / "out.dae"

    args = cad_import.build_ddc_args(
        converter,
        input_path,
        caps=_v18_caps(),
        xlsx_out=xlsx_out,
        dae_out=dae_out,
        mode="complete",
    )

    assert args == [
        str(converter),
        str(input_path),
        "-x",
        str(xlsx_out),
        "-d",
        str(dae_out),
        "-m",
        "complete",
        "--force-path",
    ]


def test_build_args_v17_xlsx_pass(tmp_path: Path) -> None:
    """‌⁠‍v17 positional XLSX pass: input + output + ``standard`` +
    ``-no-collada``.  Skipping COLLADA via the v17 flag."""
    converter = tmp_path / "RvtExporter.exe"
    input_path = tmp_path / "in.rvt"
    xlsx_out = tmp_path / "out.xlsx"

    args = cad_import.build_ddc_args(
        converter,
        input_path,
        caps=_v17_caps(),
        xlsx_out=xlsx_out,
        mode="standard",
        include_no_dae=True,  # maps to -no-collada on the v17 profile
    )

    assert args == [
        str(converter),
        str(input_path),
        str(xlsx_out),
        "standard",
        "-no-collada",
    ]


def test_build_args_legacy_bare(tmp_path: Path) -> None:
    """‌⁠‍Legacy profile: just ``[exe, input, output]`` — no depth-mode, no
    -no-collada, no v18 flags.  The bare-retry fallback that the
    v4.6.2 fix added."""
    converter = tmp_path / "RvtExporter.exe"
    input_path = tmp_path / "in.rvt"
    xlsx_out = tmp_path / "out.xlsx"

    args = cad_import.build_ddc_args(
        converter,
        input_path,
        caps=cad_import._default_capabilities(),
        xlsx_out=xlsx_out,
        mode="standard",
        include_no_dae=True,  # legacy profile ignores it (no flag accepted)
    )

    assert args == [str(converter), str(input_path), str(xlsx_out)]


def test_build_args_v18_no_outputs_requested_emits_minimal_call(tmp_path: Path) -> None:
    """‌⁠‍v18 without any output target: still emits a valid minimal call
    (mode preset + force-path).  Lets callers drive an "auto-named
    everything" run if they want; never raises like the legacy profile."""
    converter = tmp_path / "RvtExporter.exe"
    input_path = tmp_path / "in.rvt"

    args = cad_import.build_ddc_args(
        converter,
        input_path,
        caps=_v18_caps(),
        mode="standard",
    )

    assert args == [str(converter), str(input_path), "-m", "standard", "--force-path"]


def test_build_args_legacy_requires_output_path(tmp_path: Path) -> None:
    """‌⁠‍Legacy profile can't run without an output target (positional CLI).
    Surface this as ValueError so callers don't silently invoke a
    converter that would output to cwd in an unpredictable way."""
    converter = tmp_path / "RvtExporter.exe"
    input_path = tmp_path / "in.rvt"

    with pytest.raises(ValueError):
        cad_import.build_ddc_args(
            converter,
            input_path,
            caps=cad_import._default_capabilities(),
            mode="standard",
        )
