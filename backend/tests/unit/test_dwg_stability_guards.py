"""Unit tests for DWG pre-conversion stability guards.

Covers the Phase-2 fixes added on 2026-05-13 for the Indian-user DWG
stability ticket:

* ``_sniff_dwg_version`` reads the 6-byte ACxxxx magic prefix.
* ``_dwg_version_too_old`` rejects pre-R2010 files (AC1018 / AC1021 etc).
* Renamed-PDF / renamed-ZIP uploads return ``(None, "")`` so the upper
  layer can surface a clean 422 instead of letting DwgExporter spend
  90+ seconds on garbage input.
"""

from __future__ import annotations

from pathlib import Path

from app.modules.dwg_takeoff.service import (
    _DWG_MIN_SUPPORTED_VERSION_CODE,
    _dwg_version_too_old,
    _sniff_dwg_version,
)


# ── _sniff_dwg_version ────────────────────────────────────────────────


def test_sniff_recognises_autocad_2018(tmp_path: Path) -> None:
    """The R22 (AutoCAD 2018) magic prefix returns a friendly label."""
    p = tmp_path / "modern.dwg"
    p.write_bytes(b"AC1032" + b"\x00" * 100)

    code, label = _sniff_dwg_version(str(p))

    assert code == "AC1032"
    assert "2018" in label


def test_sniff_recognises_autocad_2010(tmp_path: Path) -> None:
    """The R18 (AutoCAD 2010) magic prefix returns a friendly label."""
    p = tmp_path / "r2010.dwg"
    p.write_bytes(b"AC1024" + b"\x00" * 100)

    code, label = _sniff_dwg_version(str(p))

    assert code == "AC1024"
    assert "2010" in label


def test_sniff_recognises_legacy_autocad_2007(tmp_path: Path) -> None:
    """The R17 (AutoCAD 2007) magic prefix returns a friendly label.

    This file IS a real DWG but it's older than what DDC supports — the
    caller uses ``_dwg_version_too_old`` to decide whether to reject.
    """
    p = tmp_path / "lt2007.dwg"
    p.write_bytes(b"AC1021" + b"\x00" * 100)

    code, label = _sniff_dwg_version(str(p))

    assert code == "AC1021"
    assert "2007" in label


def test_sniff_rejects_pdf_renamed_to_dwg(tmp_path: Path) -> None:
    """Renamed PDF uploads return ``(None, "")``."""
    p = tmp_path / "actually-a.pdf.dwg"
    p.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"\x00" * 100)

    code, label = _sniff_dwg_version(str(p))

    assert code is None
    assert label == ""


def test_sniff_rejects_zip_renamed_to_dwg(tmp_path: Path) -> None:
    """Renamed ZIP archives return ``(None, "")``."""
    p = tmp_path / "archive.dwg"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 100)

    code, label = _sniff_dwg_version(str(p))

    assert code is None
    assert label == ""


def test_sniff_rejects_empty_file(tmp_path: Path) -> None:
    """0-byte / sub-6-byte files return ``(None, "")`` without raising."""
    p = tmp_path / "empty.dwg"
    p.write_bytes(b"")

    code, label = _sniff_dwg_version(str(p))

    assert code is None
    assert label == ""


def test_sniff_handles_missing_file(tmp_path: Path) -> None:
    """A nonexistent path returns ``(None, "")`` instead of raising."""
    code, label = _sniff_dwg_version(str(tmp_path / "does-not-exist.dwg"))

    assert code is None
    assert label == ""


def test_sniff_rejects_non_ascii_header(tmp_path: Path) -> None:
    """High-bit bytes in the first 6 → not a DWG."""
    p = tmp_path / "weird.dwg"
    p.write_bytes(b"\xff\xfe\xfd\xfc\xfb\xfa" + b"\x00" * 100)

    code, label = _sniff_dwg_version(str(p))

    assert code is None
    assert label == ""


def test_sniff_rejects_ascii_but_wrong_pattern(tmp_path: Path) -> None:
    """Files starting with ASCII letters that don't match ``AC\\d{4}``
    are rejected — guards against accidentally accepting random text
    files whose first 6 bytes happen to be printable ASCII."""
    p = tmp_path / "fake.dwg"
    p.write_bytes(b"HELLO!" + b"\x00" * 100)

    code, label = _sniff_dwg_version(str(p))

    assert code is None
    assert label == ""


# ── _dwg_version_too_old ──────────────────────────────────────────────


def test_too_old_accepts_r14_and_newer() -> None:
    """R14 (1997) and every newer release are supported.

    v3.0.6 lowered the floor to AC1014 (R14): the ezdxf-backed DWG
    path reads R14 cleanly, so refusing it was a needless block for
    legacy drawing sets still in circulation.
    """
    for code in ("AC1014", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"):
        assert _dwg_version_too_old(code) is False, code


def test_too_old_rejects_pre_r14_versions() -> None:
    """R13 and older (AC1012 / AC1009 / AC1006) → rejected as too old."""
    for code in ("AC1012", "AC1009", "AC1006"):
        assert _dwg_version_too_old(code) is True, code


def test_too_old_unknown_codes_treated_as_supported() -> None:
    """Future codes like AC2099 should NOT trip the guard.

    Numeric tail < 1024 → too old. Numeric tail ≥ 1024 → supported.
    A hypothetical AC2099 satisfies the numeric check, so we let it
    through and rely on the actual converter to reject if needed.
    """
    assert _dwg_version_too_old("AC2099") is False
    # Non-numeric tail → don't reject; the magic-byte sniff would
    # already have rejected this earlier.
    assert _dwg_version_too_old("ACFOO!") is False


def test_too_old_handles_none() -> None:
    """``None`` is the "couldn't sniff" sentinel — never report it as
    too old. The caller already has a separate path for that case."""
    assert _dwg_version_too_old(None) is False


def test_min_supported_version_is_autocad_r14() -> None:
    """Pin the minimum supported DWG version at R14 (AC1014).

    v3.0.6 lowered the floor from R18 to R14: the ezdxf-backed DWG
    path reads R14 cleanly and legacy drawing sets are still common.
    If this assertion fails because we moved the floor again, also
    update the user-facing error message in ``_handle_dwg``.
    """
    assert _DWG_MIN_SUPPORTED_VERSION_CODE == "AC1014"
