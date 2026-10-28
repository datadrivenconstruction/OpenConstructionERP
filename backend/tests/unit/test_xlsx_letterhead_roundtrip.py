# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Exports that carry the company letterhead import back as the same records.

Tasks, field reports, contacts and requirements each have an Excel export and
an Excel import. With a company profile set, the export puts the firm's name
and address above the table, and the importer used to take row 1 as the
header: the file would map no column and import nothing, silently. For every
one of the four pairs:

* an export with a letterhead re-imports to exactly the records the same
  export gives without one, with the full profile, with a logo, and with a
  firm whose one-word name is one of that importer's column names;
* without a company profile the workbook is byte for byte what the exporter
  itself wrote.

The tasks, field reports and contacts importers also name a refused record by
the row the spreadsheet shows, under a letterhead and past blank rows alike.

Route handlers are called directly, DB-free, with stub services or sessions
and the access checks stubbed out. The profile is set through the PDF layer's
readers, where the letterhead decision is made.
"""

from __future__ import annotations

import asyncio
import base64
import io
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from openpyxl import load_workbook
from PIL import Image as PILImage

from app.core import pdf_branding, xlsx_branding
from app.core.company_profile import DEFAULT_COMPANY_PROFILE

_PROJECT = uuid.UUID("33333333-3333-3333-3333-333333333333")

#: What a user types that a spreadsheet would run if it were stored as one.
_FORMULA_TEXT = "=SUM(A1:A5)"

_PROFILE = {
    "legal_name": "Acme & Sons Construction GmbH",
    "address": "Hauptstrasse 1\n10115 Berlin\nGermany",
    "registration_line": "HRB 12345 · VAT DE123456789",
    "phone": "+49 30 1234567",
    "email": "office@acme.example",
    "website": "acme.example",
}


def _png_data_url() -> str:
    out = io.BytesIO()
    PILImage.new("RGB", (400, 100), (20, 60, 140)).save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


@pytest.fixture
def use_profile(monkeypatch: pytest.MonkeyPatch):
    """Set the company profile; the default is an empty workspace."""

    def _set(profile: dict[str, str] | None = None) -> None:
        full = dict(DEFAULT_COMPANY_PROFILE)
        full.update(profile or {})
        monkeypatch.setattr(pdf_branding, "_read_company_profile", lambda *_args, **_kw: dict(full))
        monkeypatch.setattr(pdf_branding, "_read_branding", lambda *_args, **_kw: {})
        monkeypatch.setattr(pdf_branding, "_read_appearance", lambda *_args, **_kw: {})

    _set()
    return _set


async def _allowed(*_args: Any, **_kwargs: Any) -> Any:
    return True


class _Session:
    """Answers ``await session.execute(stmt)`` with fixed rows."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> Any:
        rows = self._rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(rows)))


def _body(response: Any) -> bytes:
    async def _collect() -> bytes:
        chunks = [chunk async for chunk in response.body_iterator]
        return b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in chunks)

    return asyncio.run(_collect())


# -- The export and import pairs -------------------------------------------------


def _records(numbered: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    """The records of a ``(row number, record)`` list, for comparing contents."""
    return [record for _number, record in numbered]


def _tasks(
    monkeypatch: pytest.MonkeyPatch, *, bad: bool = False, formula_text: bool = False
) -> tuple[Callable[[], bytes], Callable[[bytes], list[dict[str, Any]]]]:
    from app.modules.tasks import router as tasks_router

    monkeypatch.setattr(tasks_router, "verify_project_access", _allowed)
    tasks = [
        SimpleNamespace(
            title="Pour slab L3",
            task_type="task",
            status="open",
            priority="high",
            responsible_id=None,
            due_date="2026-10-01",
            created_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
            checklist=[{"text": "Formwork", "completed": True}, {"text": "Rebar", "completed": False}],
        ),
        SimpleNamespace(
            title="Order rebar",
            task_type="decision",
            status="in_progress",
            priority="normal",
            responsible_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            due_date="2026-09-25",
            created_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
            checklist=[],
        ),
    ]
    if formula_text:
        tasks.append(
            SimpleNamespace(
                title=_FORMULA_TEXT,
                task_type="task",
                status="open",
                priority="normal",
                responsible_id=None,
                due_date="2026-10-02",
                created_at=datetime(2026, 9, 4, 9, 0, tzinfo=UTC),
                checklist=[],
            )
        )
    if bad:
        tasks.append(
            SimpleNamespace(
                title="Fix hoarding",
                task_type="task",
                status="open",
                priority="low",
                responsible_id=None,
                due_date="01.10.2026",
                created_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
                checklist=[],
            )
        )

    async def _list_tasks(*_args: Any, **_kwargs: Any) -> tuple[list[Any], int]:
        return tasks, len(tasks)

    service = SimpleNamespace(list_tasks=_list_tasks)
    produce = lambda: _body(  # noqa: E731
        asyncio.run(tasks_router.export_tasks(session=None, project_id=_PROJECT, user_id="user", service=service))
    )
    return produce, lambda blob: _records(tasks_router._parse_task_rows_from_excel(blob))


def _field_reports(
    monkeypatch: pytest.MonkeyPatch, *, bad: bool = False, formula_text: bool = False
) -> tuple[Callable[[], bytes], Callable[[bytes], list[dict[str, Any]]]]:
    from app.modules.fieldreports import router as fieldreports_router

    monkeypatch.setattr(fieldreports_router, "verify_project_access", _allowed)

    def _reports() -> list[Any]:
        reports = [
            SimpleNamespace(
                report_date=date(2026, 9, 10),
                workforce=[{"trade": "concrete", "count": 6}],
                equipment_on_site=["crane"],
                weather_condition="cloudy",
                temperature_c=18.5,
                wind_speed="12 km/h",
                work_performed="Slab L3 poured",
                notes="Pump arrived late",
            ),
            SimpleNamespace(
                report_date=date(2026, 9, 11),
                workforce=[],
                equipment_on_site=[],
                weather_condition="rain",
                temperature_c=14.0,
                wind_speed=None,
                work_performed="Curing, no pour",
                notes=None,
            ),
        ]
        if formula_text:
            reports.append(
                SimpleNamespace(
                    report_date=date(2026, 9, 8),
                    workforce=[],
                    equipment_on_site=[],
                    weather_condition="clear",
                    temperature_c=None,
                    wind_speed=None,
                    work_performed=_FORMULA_TEXT,
                    notes=None,
                )
            )
        if bad:
            # The oldest date, so the newest-first export puts it last.
            reports.append(
                SimpleNamespace(
                    report_date=date(2026, 9, 9),
                    workforce=[],
                    equipment_on_site=[],
                    weather_condition="volcanic ash",
                    temperature_c=None,
                    wind_speed=None,
                    work_performed="Site closed",
                    notes=None,
                )
            )
        return reports

    async def _all_for_project(_project_id: Any) -> list[Any]:
        return _reports()

    service = SimpleNamespace(repo=SimpleNamespace(all_for_project=_all_for_project))
    produce = lambda: _body(  # noqa: E731
        asyncio.run(
            fieldreports_router.export_field_reports(
                session=None, project_id=_PROJECT, _user_id="user", _perm=None, service=service
            )
        )
    )
    return produce, lambda blob: _records(fieldreports_router._parse_report_rows_from_excel(blob))


def _contacts(
    monkeypatch: pytest.MonkeyPatch, *, bad: bool = False, formula_text: bool = False
) -> tuple[Callable[[], bytes], Callable[[bytes], list[dict[str, Any]]]]:
    from app.modules.contacts import router as contacts_router

    monkeypatch.setattr(contacts_router, "_is_admin", _allowed)
    rows = [
        SimpleNamespace(
            company_name="Painter Ltd",
            first_name="Dana",
            last_name="Smith",
            contact_type="subcontractor",
            primary_email="dana@painter.example",
            primary_phone="+44 20 7946 0000",
            country_code="GB",
            vat_number="GB123456789",
            prequalification_status="approved",
            payment_terms_days=30,
        ),
        SimpleNamespace(
            company_name="Steel Supply GmbH",
            first_name=None,
            last_name=None,
            contact_type="supplier",
            primary_email="sales@steel.example",
            primary_phone=None,
            country_code="DE",
            vat_number=None,
            prequalification_status=None,
            payment_terms_days=None,
        ),
    ]
    if formula_text:
        rows.append(
            SimpleNamespace(
                company_name=_FORMULA_TEXT,
                first_name=None,
                last_name=None,
                contact_type="supplier",
                primary_email=None,
                primary_phone=None,
                country_code=None,
                vat_number=None,
                prequalification_status=None,
                payment_terms_days=None,
            )
        )
    if bad:
        rows.append(
            SimpleNamespace(
                company_name="Broken Mail Co",
                first_name=None,
                last_name=None,
                contact_type="supplier",
                primary_email="not-an-email",
                primary_phone=None,
                country_code="FR",
                vat_number=None,
                prequalification_status=None,
                payment_terms_days=None,
            )
        )
    produce = lambda: _body(  # noqa: E731
        asyncio.run(contacts_router.export_contacts(session=_Session(rows), user_id="user", _perm=None))
    )
    return produce, lambda blob: _records(contacts_router._parse_contact_rows_from_excel(blob))


def _budgets(
    monkeypatch: pytest.MonkeyPatch, *, bad: bool = False, formula_text: bool = False
) -> tuple[Callable[[], bytes], Callable[[bytes], list[dict[str, Any]]]]:
    from decimal import Decimal

    from app.modules.finance import router as finance_router

    monkeypatch.setattr(finance_router, "_require_project_access", _allowed)
    rows = [
        SimpleNamespace(
            wbs_id="1.1",
            category="labor",
            original_budget=Decimal("123456789.99"),
            revised_budget=Decimal("130000000.00"),
            committed=Decimal("40000.00"),
            actual=Decimal("25000.00"),
            forecast_final=Decimal("129000000.00"),
        ),
        SimpleNamespace(
            wbs_id="2.3",
            category="material",
            original_budget=Decimal("8000.00"),
            revised_budget=Decimal("8000.00"),
            committed=Decimal("0"),
            actual=Decimal("0"),
            forecast_final=Decimal("8200.00"),
        ),
    ]
    if formula_text:
        rows.append(
            SimpleNamespace(
                wbs_id=_FORMULA_TEXT,
                category="other",
                original_budget=Decimal("1.00"),
                revised_budget=Decimal("1.00"),
                committed=Decimal("0"),
                actual=Decimal("0"),
                forecast_final=Decimal("1.00"),
            )
        )
    produce = lambda: _body(  # noqa: E731
        asyncio.run(
            finance_router.export_budgets(session=_Session(rows), _user_id="user", project_id=_PROJECT, _perm=None)
        )
    )
    return produce, finance_router._parse_budget_rows_from_excel


_REQUIREMENTS = [
    {
        "entity": "Walls",
        "attribute": "FireRating",
        "constraint_type": "regex",
        "constraint_value": "^F\\d{2,3}$",
        "unit": "",
        "category": "fire_safety",
        "priority": "must",
        "source_ref": "DIN 4102",
        "notes": "Required by local building code",
    },
    {
        "entity": "IfcSlab",
        "attribute": "Pset_SlabCommon.ThermalTransmittance",
        "constraint_type": "max",
        "constraint_value": "0.24",
        "unit": "W/m2K",
        "category": "thermal",
        "priority": "should",
        "source_ref": "",
        "notes": "",
    },
]


def _parse_requirements(blob: bytes) -> list[dict[str, Any]]:
    from app.modules.requirements.excel_io import parse_xlsx

    rows, warnings = parse_xlsx(blob)
    assert warnings == []
    return rows


def _requirements(
    monkeypatch: pytest.MonkeyPatch, *, bad: bool = False, formula_text: bool = False
) -> tuple[Callable[[], bytes], Callable[[bytes], list[dict[str, Any]]]]:
    from app.modules.requirements.excel_io import export_xlsx

    rows = [dict(row) for row in _REQUIREMENTS]
    if formula_text:
        rows.append({**_REQUIREMENTS[0], "entity": _FORMULA_TEXT})

    return lambda: export_xlsx([dict(row) for row in rows], title="Fire safety set"), _parse_requirements


#: (export/import pair, sheet, a record field, its values in export order,
#: a one-word firm name that is one of this importer's column names)
_PAIRS = {
    "tasks": (_tasks, "Tasks", "title", ["Pour slab L3", "Order rebar"], "Title"),
    "field_reports": (
        _field_reports,
        "Field Reports",
        "work_performed",
        ["Curing, no pour", "Slab L3 poured"],
        "Notes",
    ),
    "contacts": (_contacts, "Contacts", "company_name", ["Painter Ltd", "Steel Supply GmbH"], "Company"),
    "requirements": (_requirements, "Fire safety set", "entity", ["Walls", "IfcSlab"], "Entity"),
    "budgets": (_budgets, "Budgets", "wbs_id", ["1.1", "2.3"], "Budget"),
}

_VARIANTS = ("full profile", "with a logo", "name is a column")


def _profile(variant: str, column_name: str) -> dict[str, str]:
    if variant == "with a logo":
        return {**_PROFILE, "document_logo_data_url": _png_data_url()}
    if variant == "name is a column":
        return {"legal_name": column_name}
    return dict(_PROFILE)


@pytest.mark.parametrize("variant", _VARIANTS)
@pytest.mark.parametrize("name", sorted(_PAIRS))
def test_an_export_with_a_letterhead_imports_back_as_the_same_records(
    use_profile, monkeypatch: pytest.MonkeyPatch, name: str, variant: str
) -> None:
    make, sheet, field, values, column_name = _PAIRS[name]
    produce, parse = make(monkeypatch)

    plain = parse(produce())
    assert [record[field] for record in plain] == values

    profile = _profile(variant, column_name)
    use_profile(profile)
    branded = produce()

    # The letterhead is really there: row 1 holds the firm's name and nothing
    # else, so the table's header is further down.
    ws = load_workbook(io.BytesIO(branded))[sheet]
    assert [cell.value for cell in ws[1] if cell.value is not None] == [profile["legal_name"]]

    assert parse(branded) == plain


@pytest.mark.parametrize("name", sorted(_PAIRS))
def test_without_a_profile_the_export_is_byte_identical(
    use_profile, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    make, sheet, *_rest = _PAIRS[name]
    produce, _parse = make(monkeypatch)
    wired = produce()

    calls: list[str] = []

    def _no_letterhead(ws: Any, **_kwargs: Any) -> int:
        calls.append(ws.title)
        return 1

    monkeypatch.setattr(xlsx_branding, "apply_company_header", _no_letterhead)
    unwired = produce()

    # The exporter really calls the helper, on the right sheet, once: a
    # comparison with a patch that never took effect would prove nothing.
    assert calls == [sheet]
    assert _parts(wired) == _parts(unwired)


def _parts(blob: bytes) -> dict[str, bytes]:
    """Every part of the package but the one carrying save timestamps."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name != "docProps/core.xml"}


def test_requirements_warnings_name_the_row_the_spreadsheet_shows(use_profile) -> None:
    from app.modules.requirements.excel_io import COLUMNS, export_xlsx, parse_xlsx

    use_profile(_PROFILE)
    rows = [dict(_REQUIREMENTS[0]), {**_REQUIREMENTS[1], "constraint_type": "approx"}]
    blob = export_xlsx(rows, title="Fire safety set")

    ws = load_workbook(io.BytesIO(blob)).active
    operator_column = COLUMNS.index("constraint_type") + 1
    bad_row = next(row for row in range(1, 40) if ws.cell(row=row, column=operator_column).value == "approx")
    assert bad_row > 3

    parsed, warnings = parse_xlsx(blob)
    assert [record["entity"] for record in parsed] == ["Walls", "IfcSlab"]
    assert warnings == [f"Row {bad_row}: unknown operator 'approx', defaulting to equals"]


def test_import_templates_carry_no_letterhead(use_profile) -> None:
    # Templates are blank forms for the user to fill in, not documents the
    # firm sends out, and the importers' own row 1 rule reads them.
    from app.modules.contacts import router as contacts_router
    from app.modules.fieldreports import router as fieldreports_router
    from app.modules.requirements.excel_io import build_template_xlsx
    from app.modules.tasks import router as tasks_router

    use_profile(_PROFILE)
    blobs = [
        _body(asyncio.run(tasks_router.download_task_template())),
        _body(asyncio.run(fieldreports_router.download_field_reports_template(_user_id="user"))),
        _body(asyncio.run(contacts_router.download_contacts_template(_user_id="user", _perm=None))),
        build_template_xlsx(),
    ]
    for blob in blobs:
        for ws in load_workbook(io.BytesIO(blob)).worksheets:
            assert _PROFILE["legal_name"] not in [cell.value for row in ws.iter_rows(max_row=10) for cell in row]


@pytest.mark.parametrize("branded", [False, True])
@pytest.mark.parametrize("name", sorted(_PAIRS))
def test_text_that_looks_like_a_formula_comes_back_as_it_was_typed(
    use_profile, monkeypatch: pytest.MonkeyPatch, name: str, branded: bool
) -> None:
    # openpyxl types a cell from its value, so a note a user typed as
    # "=SUM(A1:A5)" would be stored as a formula: Excel would run it, and the
    # letterhead would have to move references inside someone's prose.
    make, sheet, field, _values, _collision = _PAIRS[name]
    produce, parse = make(monkeypatch, formula_text=True)
    if branded:
        use_profile(_PROFILE)

    blob = produce()

    ws = load_workbook(io.BytesIO(blob))[sheet]
    written = [cell for row in ws.iter_rows() for cell in row if cell.value == _FORMULA_TEXT]
    assert [cell.data_type for cell in written] == ["s"]
    assert _FORMULA_TEXT in [str(record.get(field, "")) for record in parse(blob)]


def test_the_bim_element_importer_reads_a_letterheaded_sheet(use_profile) -> None:
    # The BIM element importer takes files from other tools, and one of those
    # can carry a letterhead of its own, so it looks for the header the same way.
    from openpyxl import Workbook

    from app.core.xlsx_branding import apply_company_header
    from app.modules.bim_hub.router import _parse_bim_rows_from_excel

    use_profile(_PROFILE)
    wb = Workbook()
    ws = wb.active
    for column, (header, value) in enumerate(
        [("element_id", "wall-a"), ("element_type", "IfcWall"), ("category", "Walls")], 1
    ):
        ws.cell(row=1, column=column, value=header)
        ws.cell(row=2, column=column, value=value)
    assert apply_company_header(ws, title="Elements") > 1
    out = io.BytesIO()
    wb.save(out)

    assert _parse_bim_rows_from_excel(out.getvalue()) == [
        {"element_id": "wall-a", "element_type": "IfcWall", "_category": "Walls"}
    ]


# -- Import errors name the row the spreadsheet shows ------------------------------


async def _accepted(*_args: Any, **_kwargs: Any) -> None:
    return None


def _upload(blob: bytes, filename: str) -> Any:
    from fastapi import UploadFile

    return UploadFile(file=io.BytesIO(blob), filename=filename)


def _import_tasks(blob: bytes) -> dict[str, Any]:
    from app.modules.tasks import router as tasks_router

    return asyncio.run(
        tasks_router.import_tasks_file(
            user_id="user",
            session=None,
            project_id=_PROJECT,
            file=_upload(blob, "tasks.xlsx"),
            _perm=None,
            service=SimpleNamespace(create_task=_accepted),
        )
    )


def _import_field_reports(blob: bytes) -> dict[str, Any]:
    from app.modules.fieldreports import router as fieldreports_router

    return asyncio.run(
        fieldreports_router.import_field_reports_file(
            session=None,
            project_id=_PROJECT,
            _user_id="user",
            _perm=None,
            file=_upload(blob, "field_reports.xlsx"),
            service=SimpleNamespace(create_report=_accepted),
        )
    )


def _import_contacts(blob: bytes) -> dict[str, Any]:
    from app.modules.contacts import router as contacts_router

    return asyncio.run(
        contacts_router.import_contacts_file(
            _user_id="user",
            file=_upload(blob, "contacts.xlsx"),
            _perm=None,
            service=SimpleNamespace(create_contact=_accepted),
        )
    )


#: (export/import pair, the import route, a cell of the one record it refuses)
_IMPORTS = {
    "tasks": (_tasks, _import_tasks, "Fix hoarding"),
    "field_reports": (_field_reports, _import_field_reports, "Site closed"),
    "contacts": (_contacts, _import_contacts, "Broken Mail Co"),
}


@pytest.mark.parametrize("name", sorted(_IMPORTS))
def test_an_import_error_names_the_row_of_the_letterheaded_sheet(
    use_profile, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    make, import_file, marker = _IMPORTS[name]
    produce, _parse = make(monkeypatch, bad=True)
    use_profile(_PROFILE)
    blob = produce()

    ws = load_workbook(io.BytesIO(blob)).active
    bad_row = next(row for row in range(1, 40) if marker in [cell.value for cell in ws[row]])
    # Well below the letterhead, so counting from the table would miss it.
    assert bad_row > 6

    result = import_file(blob)

    assert [error["row"] for error in result["errors"]] == [bad_row]
    assert result["imported"] == 2


#: (router module, parser name prefix, two header cells, two data rows)
_PARSERS = {
    "tasks": ("app.modules.tasks.router", "_parse_task_rows", ("Title", "Status"), ("Pour slab", "open")),
    "field_reports": (
        "app.modules.fieldreports.router",
        "_parse_report_rows",
        ("Date", "Notes"),
        ("2026-09-10", "Pump late"),
    ),
    "contacts": ("app.modules.contacts.router", "_parse_contact_rows", ("Company", "Email"), ("Painter Ltd", "a@b.c")),
}


@pytest.mark.parametrize("name", sorted(_PARSERS))
def test_a_blank_row_does_not_shift_the_row_numbers(name: str) -> None:
    import importlib

    from openpyxl import Workbook

    module_name, prefix, header, values = _PARSERS[name]
    module = importlib.import_module(module_name)

    wb = Workbook()
    ws = wb.active
    for column, (title, value) in enumerate(zip(header, values, strict=True), 1):
        ws.cell(row=1, column=column, value=title)
        ws.cell(row=2, column=column, value=value)
        ws.cell(row=4, column=column, value=value)
    out = io.BytesIO()
    wb.save(out)
    excel_rows = getattr(module, f"{prefix}_from_excel")(out.getvalue())

    lines = [",".join(header), ",".join(values), "", ",".join(values)]
    csv_rows = getattr(module, f"{prefix}_from_csv")(("\n".join(lines) + "\n").encode("utf-8"))

    assert [number for number, _record in excel_rows] == [2, 4]
    assert [number for number, _record in csv_rows] == [2, 4]
