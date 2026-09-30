# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An Excel 97-2003 workbook imports exactly as the same workbook saved as .xlsx.

Estimating programs still export .xls, and the import used to refuse it with a
request to open the file in Excel and save it again. It is read now, through
the same spreadsheet importer, the same Hungarian profiles and the same
validation, so the tests here compare an .xls with its .xlsx twin and require
the same bill out of both rather than checking the .xls on its own: a reader
that decoded every cell slightly differently (a code ``11`` read as ``11.0``,
an empty cell read as ``""``) would still import something, and only the twin
shows it is not the same thing.

The .xls copies are committed under ``tests/fixtures/xls/``; see
``tests/fixtures/make_hu_xls.py`` for how they are written and when.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.boq.importers import REGISTERED_IMPORTERS, ImporterParseError
from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers._workbook import LegacyWorkbook, open_workbook
from app.modules.boq.importers.excel import ExcelImporter
from app.modules.boq.importers.hungary_workbook import detect_profile
from tests.fixtures.make_hu_xls import SOURCES, XLS_DIR


def _parse(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content))


def _xls(name: str) -> bytes:
    return (XLS_DIR / name).read_bytes()


def _without_format(result: ImportedBOQ) -> dict[str, Any]:
    fields = dataclasses.asdict(result)
    fields.pop("source_format")
    return fields


# ── The same bill out of both formats ────────────────────────────────────


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_the_xls_copy_imports_the_same_bill_as_the_xlsx(name: str) -> None:
    from_xlsx = _parse(SOURCES[name]())
    from_xls = _parse(_xls(name))
    assert from_xls.positions, f"{name}: nothing imported"
    assert _without_format(from_xls) == _without_format(from_xlsx), (
        f"{name}: the .xls copy of the workbook imported differently from the .xlsx. "
        "If the builder changed, write the copy again with tests/fixtures/make_hu_xls.py."
    )


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_the_source_format_says_which_file_it_was(name: str) -> None:
    assert _parse(_xls(name)).source_format == "xls"
    assert _parse(SOURCES[name]()).source_format == "xlsx"


def test_the_building_profile_reads_the_xls_copy() -> None:
    workbook = open_workbook(_xls("hu_building.xls"))
    assert isinstance(workbook, LegacyWorkbook)
    assert detect_profile(workbook) == "building"
    result = _parse(_xls("hu_building.xls"))
    priced = [p for p in result.positions if not p.is_section]
    assert [p.classification["tetelrend"] for p in priced] == ["MA-01-11-01-001"]
    assert priced[0].unit_rate == 110000
    assert result.currency == "HUF"


def test_the_infrastructure_profile_reads_the_xls_copy() -> None:
    assert detect_profile(open_workbook(_xls("hu_infrastructure.xls"))) == "infrastructure"


def test_a_hidden_sheet_in_an_xls_is_named_and_left_out() -> None:
    result = _parse(_xls("hu_trades_hidden.xls"))
    notes = {w["sheet"]: w["reason"] for w in result.warnings if w.get("code") == "sheet_not_read"}
    assert notes.get("Segéd") == "hidden"
    assert "Munkaanyag" not in {p.description for p in result.positions}


def test_whole_numbers_come_back_as_whole_numbers() -> None:
    """The .xls format stores every number as a float; a code must stay ``11``."""
    rows = list(open_workbook(_xls("hu_building.xls"))["MA-01_ÁLT"].iter_rows(values_only=True))
    priced = next(row for row in rows if "Ideiglenes útalap zúzottkőből" in row)
    quantity = priced[20]  # column U
    assert quantity == 10
    assert type(quantity) is int


# ── Choosing the reader ──────────────────────────────────────────────────


def test_the_import_picks_the_spreadsheet_importer_for_an_xls() -> None:
    content = _xls("hu_flat.xls")
    chosen = [importer for importer in REGISTERED_IMPORTERS if importer.detect(content[:4096], "koltsegvetes.xls")]
    assert chosen == [ExcelImporter]


def test_an_xlsx_saved_under_the_xls_name_is_still_read() -> None:
    content = SOURCES["hu_flat.xls"]()
    assert ExcelImporter.detect(content[:4096], "koltsegvetes.xls")
    assert _parse(content).positions


def test_another_office_file_is_not_claimed_by_name_alone() -> None:
    content = _xls("hu_flat.xls")
    assert not ExcelImporter.detect(content[:4096], "model.rvt")
    assert not ExcelImporter.detect(content[:4096], "letter.doc")


# ── What cannot be read says why ─────────────────────────────────────────


def test_a_truncated_xls_is_refused_with_a_parse_error() -> None:
    with pytest.raises(ImporterParseError):
        _parse(_xls("hu_flat.xls")[:600])


def test_a_compound_file_without_a_workbook_is_refused_as_such() -> None:
    """A .doc or a .msg named .xls opens as a compound file and holds no workbook."""
    content = _xls("hu_flat.xls").replace("Workbook".encode("utf-16-le"), "Document".encode("utf-16-le"))
    with pytest.raises(ImporterParseError, match="holds no Excel workbook"):
        _parse(content)


def test_a_password_protected_workbook_is_refused_with_the_reason() -> None:
    """A protected .xlsx is a compound file holding an ``EncryptedPackage`` stream."""
    # The directory names the stream in UTF-16, which is all the reader looks for.
    content = _xls("hu_flat.xls").replace("Workbook".encode("utf-16-le"), "Document".encode("utf-16-le"))
    content += "EncryptedPackage".encode("utf-16-le")
    with pytest.raises(ImporterParseError, match="password"):
        _parse(content)


def test_a_readable_workbook_is_not_taken_for_a_protected_one() -> None:
    """The stream name can occur in a valid file's bytes; only an unreadable one is asked."""
    content = _xls("hu_flat.xls") + "EncryptedPackage".encode("utf-16-le")
    assert _parse(content).positions


# ── The same validation ──────────────────────────────────────────────────


class _Service:
    def __init__(self, positions: list[SimpleNamespace]) -> None:
        self.session = object()
        self._data = SimpleNamespace(project_id=uuid.uuid4(), positions=positions)

    async def get_boq_with_positions(self, _boq_id: uuid.UUID) -> SimpleNamespace:
        return self._data


class _ProjectRepo:
    project = SimpleNamespace(
        region="HU",
        country_code="HU",
        classification_standard="tetelrend",
        validation_rule_sets=["boq_quality"],
    )

    def __init__(self, _session: Any) -> None:
        pass

    async def get_by_id(self, _project_id: uuid.UUID) -> SimpleNamespace:
        return self.project


def _as_rows(result: ImportedBOQ) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=uuid.uuid4(),
            parent_id=None,
            ordinal=p.ordinal,
            description=p.description,
            unit=p.unit,
            quantity=p.quantity,
            unit_rate=p.unit_rate,
            total=p.quantity * p.unit_rate,
            classification=p.classification,
            source="import",
            metadata=p.metadata,
        )
        for p in result.positions
    ]


def _validate(result: ImportedBOQ, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from app.config import get_settings
    from app.core.validation.rules import register_builtin_rules
    from app.modules.boq.router import _run_import_validation

    register_builtin_rules()
    get_settings.cache_clear()
    monkeypatch.delenv("IMPORT_INLINE_VALIDATION", raising=False)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _ProjectRepo)
    service = _Service(_as_rows(result))
    report = asyncio.run(_run_import_validation(uuid.uuid4(), service, service.session))  # type: ignore[arg-type]
    assert report is not None, "the import validation returned no report"
    return report


def test_the_xls_bill_runs_through_the_hungarian_rules_as_the_xlsx_does(monkeypatch: pytest.MonkeyPatch) -> None:
    from_xls = _validate(_parse(_xls("hu_building.xls")), monkeypatch)
    from_xlsx = _validate(_parse(SOURCES["hu_building.xls"]()), monkeypatch)
    assert "hungary" in from_xls["rule_sets"]
    hungarian = [r for r in from_xls["results"] if r["rule_id"].startswith("hungary")]
    assert hungarian, "no Hungarian rule reported on the .xls bill"

    def outcome(report: dict[str, Any]) -> list[tuple[str, str, bool]]:
        return sorted((r["rule_id"], r["severity"], r["passed"]) for r in report["results"])

    assert outcome(from_xls) == outcome(from_xlsx)
