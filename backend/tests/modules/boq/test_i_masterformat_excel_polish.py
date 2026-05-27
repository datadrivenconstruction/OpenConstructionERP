"""Epic I10 — Excel/CSV polish: CSI MasterFormat code detection.

The Excel importer now recognises 6-digit MasterFormat codes
(``03 30 00``, ``03.30.00``, ``03-30-00``) and division headers
(``Division 03 — Concrete``) and surfaces them in
``classification.masterformat`` so the MasterFormat rule pack can fire
without manual classification.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.modules.boq.importers.excel import ExcelImporter, _infer_classification

# ── Direct heuristic tests ─────────────────────────────────────────────────


class TestInferClassificationMasterFormat:
    def test_spaced_form(self) -> None:
        c = _infer_classification("03 30 00", "Cast-in-Place Concrete")
        assert c["masterformat"] == "03 30 00"

    def test_dotted_form(self) -> None:
        c = _infer_classification("03.30.00", "Cast-in-Place Concrete")
        # Normalised to spaced canonical form for downstream rules.
        assert c["masterformat"] == "03 30 00"

    def test_dashed_form(self) -> None:
        c = _infer_classification("03-30-00", "Cast-in-Place Concrete")
        assert c["masterformat"] == "03 30 00"

    def test_with_subcode(self) -> None:
        c = _infer_classification("03 30 00.01", "Cast-in-Place Concrete subcode")
        assert c["masterformat"] == "03 30 00.01"

    def test_division_header_in_description(self) -> None:
        c = _infer_classification("", "Division 03 — Concrete")
        assert c["masterformat"] == "03 00 00"

    def test_division_header_with_code_in_cell_keeps_code(self) -> None:
        c = _infer_classification("03 30 00", "Division 03 — Cast-in-Place Concrete")
        # The cell-level 6-digit code wins over the division-only stub.
        assert c["masterformat"] == "03 30 00"

    def test_non_masterformat_falls_back(self) -> None:
        c = _infer_classification("XYZ-001", "Random scope item")
        assert "masterformat" not in c
        assert "nrm" not in c
        assert c["code"] == "XYZ-001"


# ── End-to-end CSV round-trip ──────────────────────────────────────────────


def _build_masterformat_csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Code", "Description", "Unit", "Quantity", "Unit Rate"])
    w.writerow(["", "Division 03 — Concrete", "", "", ""])
    w.writerow(["03 30 00", "Cast-in-Place Concrete", "m3", "85.0", "150.00"])
    w.writerow(["03.31.00", "Structural Concrete", "m3", "200.0", "175.00"])
    w.writerow(["", "Division 26 — Electrical", "", "", ""])
    w.writerow(["26-05-00", "Common Work Results — Electrical", "lsum", "1.0", "12500.00"])
    return buf.getvalue().encode("utf-8")


class TestExcelImporterMasterFormat:
    @pytest.mark.asyncio
    async def test_csv_auto_detects_masterformat_codes(self) -> None:
        result = await ExcelImporter.parse(_build_masterformat_csv())
        sections = [p for p in result.positions if p.is_section]
        rows = [p for p in result.positions if not p.is_section]
        assert len(sections) == 2
        assert len(rows) == 3
        # All three data rows must have a MasterFormat classification.
        for row in rows:
            assert "masterformat" in row.classification, row.ordinal
            # And no generic ``code`` pollution.
            assert "code" not in row.classification
        # Spaced canonical form across all three encodings.
        codes = {r.classification["masterformat"] for r in rows}
        assert codes == {"03 30 00", "03 31 00", "26 05 00"}
