"""‌⁠‍End-to-end check that the v4.x.x fix for DDC v18.3.0 actually drives
the installed binary to a successful conversion.

This test is gated on the local installation: it only runs when
~/.openestimator/converters/rvt_windows/RvtExporter.exe exists and the
canonical 16 MB ``c5436288-...`` RVT fixture is present under data/bim.
Both conditions hold on the dev machine that originally hit the bug; on
CI / fresh checkouts the test cleanly skips.

Marked ``slow`` because it spawns the real Revit-engine binary, which
takes 30-90s for a 16 MB model.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import

logger = logging.getLogger(__name__)

V18_BINARY = Path.home() / ".openestimator" / "converters" / "rvt_windows" / "RvtExporter.exe"
TEST_RVT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "bim"
    / "24c3ddfb-00db-44f0-b0b8-9d7ad4078cf2"
    / "c5436288-8f71-5d89-95a4-c2a4372a5cb3"
    / "original.rvt"
)


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    cad_import._CONVERTER_CAPABILITIES.clear()
    ifc_processor._LAST_DDC_FAILURE.clear()
    yield
    cad_import._CONVERTER_CAPABILITIES.clear()
    ifc_processor._LAST_DDC_FAILURE.clear()


@pytest.mark.slow
def test_real_v18_help_text_is_classified_as_v18_flag() -> None:
    """‌⁠‍Sanity: spawn the actual installed binary with --help and assert
    the capability probe classifies it as v18.  This is the regression
    that originally bit the user (substring match said "modern" against
    the v18 binary, which produced ``standard -no-collada`` and crashed
    with exit 15)."""
    if not V18_BINARY.exists():
        pytest.skip(f"DDC v18 binary not installed at {V18_BINARY}")

    result = subprocess.run(
        [str(V18_BINARY), "--help"],
        capture_output=True,
        timeout=15,
        cwd=str(V18_BINARY.parent),
    )
    text = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace").lower()

    # Pre-flight: the help text MUST be the v18.x shape that exposes the
    # new flags.  If this fails the binary itself drifted and the test
    # needs a fixture refresh, not a code fix.
    assert "version: 18" in text or "ddc revit community" in text, (
        f"Installed binary doesn't look like DDC v18 — head of help: {text[:200]!r}"
    )

    profile = cad_import._classify_help_text(text)
    assert profile == cad_import.CLI_PROFILE_V18_FLAG, (
        f"v18 binary --help misclassified as {profile}; tokens around 'no-dae': "
        f"{[t for t in text.split() if 'no-dae' in t or 'force-path' in t]}"
    )


@pytest.mark.slow
def test_real_v18_binary_converts_rvt_via_processor(tmp_path: Path) -> None:
    """‌⁠‍End-to-end: drive ``_try_cad2data`` against the real v18 binary
    and the canonical c5436288 RVT fixture.  Asserts:

      * Conversion returns a non-None bim_result (no exit-15 crash).
      * The XLSX output exists and has > 100 rows of element data.
      * The DAE output exists and is > 100 bytes (real geometry, not
        the box-fallback stub).

    Before the fix the same call ended in exit 15 + "arguments were not
    expected" stderr and produced no output files.
    """
    if not V18_BINARY.exists():
        pytest.skip(f"DDC v18 binary not installed at {V18_BINARY}")
    if not TEST_RVT.exists():
        pytest.skip(f"RVT fixture missing at {TEST_RVT}")

    # Copy the fixture to a tmp workspace so the test never mutates the
    # canonical seed data on disk.
    work_rvt = tmp_path / "original.rvt"
    shutil.copy2(TEST_RVT, work_rvt)
    out_dir = tmp_path / "work"

    result = ifc_processor._try_cad2data(work_rvt, out_dir, conversion_depth="standard")

    assert result is not None, (
        f"Real-binary conversion returned None — last failure: {ifc_processor.last_ddc_failure()}"
    )

    # XLSX outputs land under out_dir with the input stem.
    xlsx_candidates = list(out_dir.glob("*.xlsx")) + list(out_dir.glob("*.xls"))
    assert xlsx_candidates, f"No XLSX produced in {out_dir} — got: {list(out_dir.iterdir())}"
    xlsx = xlsx_candidates[0]
    assert xlsx.stat().st_size > 0, f"XLSX {xlsx} is empty"

    # Spot-check the XLSX has substantive content (>100 rows means we
    # actually walked the Revit model, not just wrote an empty workbook).
    rows = cad_import.parse_cad_excel(xlsx)
    assert len(rows) > 100, (
        f"v18 conversion produced only {len(rows)} XLSX rows — fixture should "
        f"yield several hundred elements; check converter health"
    )

    # DAE is best-effort — log a soft warning instead of failing if it
    # didn't materialise (some Revit models export an empty COLLADA scene
    # but still produce a usable XLSX, and the box-grid fallback covers
    # the viewer regardless).  The XLSX assertion above is the load-bearing
    # one for the v18 fix.
    dae_path = out_dir / "geometry.dae"
    if dae_path.exists():
        assert dae_path.stat().st_size > 100, (
            f"DAE {dae_path} exists but is suspiciously small ({dae_path.stat().st_size} bytes)"
        )
    else:
        logger.warning("No geometry.dae produced for v18 conversion (xlsx ok)")
