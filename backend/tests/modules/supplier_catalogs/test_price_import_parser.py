"""Price list file parser (xlsx, SAP-style csv), import-row validation and the import routes."""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.supplier_catalogs import router as sc_router
from app.modules.supplier_catalogs.price_import import ImportFileError, read_table
from app.modules.supplier_catalogs.schemas import CatalogItemCreate, VendorCreate
from app.modules.supplier_catalogs.service import SupplierCatalogsService
from tests._pg import transactional_session


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _errors(table) -> dict[int, list[str]]:
    return {r.row: r.errors for r in table.rows}


def test_xlsx_keeps_decimals_exact_and_reads_discount_and_unit() -> None:
    raw = _xlsx(
        [
            ["Article No", "List price", "Unit", "Discount %"],
            ["A-1", "12.35", "kg", 7.5],
            ["A-2", 0.1, "m2", None],
        ]
    )
    table, mapping, preset = read_table("p.xlsx", raw, None, None)
    assert preset == "generic"
    assert mapping["discount_pct"] == "Discount %"
    first, second = table.rows
    assert first.values["unit_price"] == Decimal("12.35")
    assert first.values["discount_pct"] == Decimal("7.5")
    assert isinstance(second.values["unit_price"], Decimal)
    assert not first.errors and not second.errors


def test_sap_csv_uses_decimal_comma_and_price_unit() -> None:
    raw = b"MATNR;KBETR;KPEIN;KMEIN;KONWA;DATAB;DATBI\nM-1;1.234,50;100;KG;EUR;20260101;99991231\n"
    table, _, preset = read_table("a017.csv", raw, None, None)
    assert preset == "sap_condition"
    row = table.rows[0]
    assert row.values["unit_price"] == Decimal("12.3450")
    assert row.values["valid_from"] == "2026-01-01"
    assert not row.errors


def test_row_rules_missing_negative_discount_unit() -> None:
    raw = (
        b"Article No;Price;Unit;Discount\n"
        b"A-1;;kg;0\n"
        b"A-2;-3;kg;0\n"
        b"A-3;5;kg;100.5\n"
        b"A-4;5;kg;-1\n"
        b"A-5;5;florb;10\n"
        b"A-6;5;ST;100\n"
    )
    errs = _errors(read_table("r.csv", raw, None, None)[0])
    assert errs[2] == ["missing_price"]
    assert errs[3] == ["negative_price"]
    assert errs[4] == ["discount_out_of_range"]
    assert errs[5] == ["discount_out_of_range"]
    assert errs[6] == ["unknown_unit"]
    assert errs[7] == []


def test_unreadable_and_empty_files_are_refused() -> None:
    with pytest.raises(ImportFileError):
        read_table("x.xlsx", b"not a workbook", None, None)
    with pytest.raises(ImportFileError):
        read_table("e.csv", b"\n\n", None, None)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _allow_project_access(monkeypatch) -> None:
    async def _noop(project_id, user_id, session):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr("app.dependencies.verify_project_access", _noop)


def _upload(name: str, raw: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(raw), filename=name)


async def test_import_routes_preview_then_commit_with_row_discount(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    tag = uuid.uuid4().hex[:8].upper()
    vendor = await svc.create_vendor(VendorCreate(code=f"V-{tag}", name="Cement Co"))
    item = await svc.create_catalog_item(CatalogItemCreate(sku=f"S-{tag}", name="Cement", unit_of_measure="kg"))
    raw = _xlsx([["sku", "price", "unit", "discount"], [item.sku, "10.00", "kg", 15], ["NOPE", "1", "kg", 0]])

    preview = await sc_router.preview_price_list_import(
        vendor.id,
        "u",
        file=_upload("l.xlsx", raw),
        mapping=None,
        preset=None,
        price_list_id=None,
        currency=None,
        service=svc,
    )
    assert preview.counts["create"] == 1 and preview.counts["unmatched"] == 1

    result = await sc_router.commit_price_list_import(
        vendor.id,
        "u",
        file=_upload("l.xlsx", raw),
        mapping=None,
        preset=None,
        price_list_id=None,
        name="Q4",
        currency="EUR",
        valid_from=None,
        valid_to=None,
        service=svc,
    )
    page = await svc.list_price_list_entries(result.price_list_id)
    row = page.items[0]
    assert (row.gross_price, row.net_price, row.discount_pct) == (Decimal("10"), Decimal("8.5000"), Decimal("15"))
    assert row.discount_source == "manual"


async def test_routes_refuse_bad_mapping_and_oversize(session: AsyncSession, monkeypatch) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await svc.create_vendor(VendorCreate(code=f"V-{uuid.uuid4().hex[:8]}", name="X"))
    with pytest.raises(HTTPException) as bad:
        await sc_router.preview_price_list_import(
            vendor.id,
            "u",
            file=_upload("a.csv", b"sku,price\nA,1\n"),
            mapping="[1]",
            preset=None,
            price_list_id=None,
            currency=None,
            service=svc,
        )
    assert bad.value.status_code == 422
    monkeypatch.setattr(sc_router, "_MAX_IMPORT_BYTES", 10)
    with pytest.raises(HTTPException) as big:
        await sc_router.preview_price_list_import(
            vendor.id,
            "u",
            file=_upload("a.csv", b"sku,price\nA,1\n"),
            mapping=None,
            preset=None,
            price_list_id=None,
            currency=None,
            service=svc,
        )
    assert big.value.status_code == 413
