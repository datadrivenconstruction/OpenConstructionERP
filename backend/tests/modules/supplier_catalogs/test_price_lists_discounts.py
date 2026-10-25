"""Vendor price list import, contractor discounts, net prices on orders, item links.

Covers:
    - discount resolution precedence (pure, no database)
    - import preview is a dry run; matching by vendor SKU / MPN / GTIN / SKU
    - SAP condition export preset: KBETR per KPEIN, decimal comma, SAP dates
    - commit creates then updates entries and reports changed / unmatched rows
    - net price propagates into a new PO and stays there when the agreement changes
    - validation rules: net above gross, discount range, expired list on a new PO,
      repeated vendor SKU, unsafe product link
    - permissions of the new routes and the project check on item documents
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import ValidationContext
from app.modules.supplier_catalogs import pricing
from app.modules.supplier_catalogs import validators as rules
from app.modules.supplier_catalogs.models import CatalogEntry, CatalogItemAttachment, POLine
from app.modules.supplier_catalogs.schemas import (
    CatalogEntryCreate,
    CatalogItemCreate,
    CatalogItemUpdate,
    DiscountAgreementCreate,
    DiscountAgreementUpdate,
    ItemAttachmentCreate,
    ItemCategoryCreate,
    POCreateExt,
    POLineCreate,
    PriceListCreate,
    VendorCreate,
)
from app.modules.supplier_catalogs.service import SupplierCatalogsService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _allow_project_access(monkeypatch) -> None:
    async def _noop(project_id, user_id, session):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr("app.dependencies.verify_project_access", _noop)


def _tag() -> str:
    return uuid.uuid4().hex[:8].upper()


async def _vendor(svc: SupplierCatalogsService):
    return await svc.create_vendor(VendorCreate(code=f"V-{_tag()}", name="Steel Supplies"))


async def _item(svc: SupplierCatalogsService, **kw):
    tag = _tag()
    data = {"sku": f"SKU-{tag}", "name": f"Rebar {tag}", "unit_of_measure": "kg"} | kw
    return await svc.create_catalog_item(CatalogItemCreate(**data))


# ── Precedence (pure) ────────────────────────────────────────────────────────


@dataclass
class _A:
    vendor_id: uuid.UUID
    price_list_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    catalog_item_id: uuid.UUID | None = None
    discount_pct: Decimal | None = None
    fixed_net_price: Decimal | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    active: bool = True
    id: uuid.UUID = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.id = self.id or uuid.uuid4()


V, PL, ITEM, CAT, PARENT = (uuid.uuid4() for _ in range(5))
TODAY = date(2026, 10, 23)


def _resolve(*agreements: _A, chain=(CAT, PARENT)) -> pricing.NetPrice:
    return pricing.resolve_net(
        gross=Decimal("200"),
        vendor_id=V,
        price_list_id=PL,
        catalog_item_id=ITEM,
        category_chain=list(chain),
        agreements=agreements,
        on=TODAY,
    )


def test_no_agreement_means_net_equals_gross() -> None:
    r = _resolve()
    assert (r.net, r.source, r.discount_pct) == (Decimal("200"), "none", None)


def test_item_fixed_net_beats_item_percentage_category_and_overall() -> None:
    r = _resolve(
        _A(V, discount_pct=Decimal("5")),
        _A(V, category_id=CAT, discount_pct=Decimal("10")),
        _A(V, catalog_item_id=ITEM, discount_pct=Decimal("15")),
        _A(V, catalog_item_id=ITEM, fixed_net_price=Decimal("150")),
    )
    assert (r.net, r.source, r.discount_pct) == (Decimal("150.0000"), "item_fixed", Decimal("25.0000"))


def test_item_percentage_beats_category() -> None:
    r = _resolve(
        _A(V, category_id=CAT, discount_pct=Decimal("10")), _A(V, catalog_item_id=ITEM, discount_pct=Decimal("15"))
    )
    assert (r.net, r.source) == (Decimal("170.0000"), "item")


def test_nearest_category_beats_parent_and_overall() -> None:
    r = _resolve(
        _A(V, discount_pct=Decimal("5")),
        _A(V, category_id=PARENT, discount_pct=Decimal("8")),
        _A(V, category_id=CAT, discount_pct=Decimal("12")),
    )
    assert (r.net, r.source) == (Decimal("176.0000"), "category")
    assert _resolve(
        _A(V, discount_pct=Decimal("5")), _A(V, category_id=PARENT, discount_pct=Decimal("8"))
    ).net == Decimal("184.0000")


def test_price_list_agreement_beats_vendor_wide_on_the_same_level() -> None:
    r = _resolve(_A(V, discount_pct=Decimal("5")), _A(V, price_list_id=PL, discount_pct=Decimal("7")))
    assert r.net == Decimal("186.0000")


def test_out_of_force_other_vendor_and_other_list_are_ignored() -> None:
    r = _resolve(
        _A(V, discount_pct=Decimal("50"), valid_to="2026-01-01"),
        _A(V, discount_pct=Decimal("50"), active=False),
        _A(uuid.uuid4(), discount_pct=Decimal("50")),
        _A(V, price_list_id=uuid.uuid4(), discount_pct=Decimal("50")),
        _A(V, discount_pct=Decimal("2")),
    )
    assert (r.net, r.source) == (Decimal("196.0000"), "overall")


# ── Validation rules ─────────────────────────────────────────────────────────


def test_rule_checks() -> None:
    assert rules.net_above_gross(Decimal("10"), Decimal("10.01"))
    assert not rules.net_above_gross(Decimal("10"), Decimal("10"))
    assert rules.discount_out_of_range(Decimal("-0.1")) and rules.discount_out_of_range(101)
    assert not rules.discount_out_of_range(Decimal("100"))
    assert rules.price_list_expired("2026-10-22", TODAY) and not rules.price_list_expired("2026-10-23", TODAY)
    assert rules.duplicate_skus(["a-1", " A-1 ", "b", None]) == ["A-1"]
    assert rules.url_problem("javascript:alert(1)") == "scheme"
    assert rules.url_problem("ftp://x.example/a") == "scheme"
    assert rules.url_problem("https://") == "host"
    assert rules.url_problem("https://shop.example.com/p/1 2") == "whitespace"
    assert rules.url_problem("https://shop.example.com/p/12") is None


async def test_rule_set_reports_each_problem() -> None:
    ctx = ValidationContext(
        data={
            "prices": [{"ref": "A", "gross": "10", "net": "12"}],
            "discounts": [{"ref": "D", "discount_pct": "120"}],
            "po_price_lists": [{"ref": "PL", "valid_to": "2026-01-31"}],
            "order_date": "2026-10-23",
            "price_list_rows": [{"vendor_sku": "X"}, {"vendor_sku": "x"}],
            "urls": [{"ref": "U", "url": "javascript:alert(1)"}, {"ref": "H", "url": "http://shop.example.com"}],
        }
    )
    failed = {}
    for rule_cls in rules.RULES:
        for res in await rule_cls().validate(ctx):
            if not res.passed:
                failed.setdefault(res.rule_id, []).append(str(res.severity))
    assert set(failed) == {
        "supplier_catalogs.net_not_above_gross",
        "supplier_catalogs.discount_in_range",
        "supplier_catalogs.no_expired_price_list_on_po",
        "supplier_catalogs.no_duplicate_sku_in_price_list",
        "supplier_catalogs.product_url_safe",
    }
    assert sorted(failed["supplier_catalogs.product_url_safe"]) == ["error", "warning"]


def test_schemas_refuse_unsafe_url_and_bad_discount() -> None:
    with pytest.raises(ValidationError):
        CatalogItemCreate(sku="S", name="N", product_url="javascript:alert(1)")
    with pytest.raises(ValidationError):
        CatalogItemUpdate(product_url="file:///etc/passwd")
    assert CatalogItemUpdate(product_url="  ").product_url is None
    with pytest.raises(ValidationError):
        DiscountAgreementCreate(name="x", discount_pct=Decimal("100.5"))
    with pytest.raises(ValidationError):
        DiscountAgreementCreate(name="x", fixed_net_price=Decimal("5"))  # fixed net needs an item
    with pytest.raises(ValidationError):
        DiscountAgreementCreate(name="x")  # neither basis
    with pytest.raises(ValidationError):
        DiscountAgreementUpdate(discount_pct=Decimal("-1"))


# ── Import ───────────────────────────────────────────────────────────────────


async def test_preview_matches_by_vendor_sku_mpn_gtin_and_writes_nothing(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    a = await _item(svc)
    b = await _item(svc, mpn=f"MPN-{_tag()}")
    c = await _item(svc, gtin=f"40{uuid.uuid4().int % 10**11:011d}")
    pl = await svc.create_price_list(
        vendor.id,
        PriceListCreate(
            name="2025",
            entries=[CatalogEntryCreate(catalog_item_id=a.id, vendor_sku="ART-1", unit_price=Decimal("10"))],
        ),
    )
    csv = (
        "Article No;MPN;EAN;List price;Valid from\n"
        f"ART-1;;;12,50;01.01.2026\n"
        f";{b.mpn};;7,00;01.01.2026\n"
        f";;{c.gtin};3,10;01.01.2026\n"
        "NOPE-9;;;1,00;01.01.2026\n"
        ";;;;\n"
    ).encode("cp1252")
    before = (await session.execute(select(CatalogEntry).where(CatalogEntry.price_list_id == pl.id))).scalars().all()

    preview = await svc.preview_price_list_import(vendor.id, "list.csv", csv, price_list_id=pl.id)

    assert preview.preset == "generic"
    assert preview.mapping["vendor_sku"] == "Article No" and preview.mapping["unit_price"] == "List price"
    by_row = {r.row: r for r in preview.rows}
    assert (by_row[2].action, by_row[2].matched_by, by_row[2].old_price, by_row[2].new_price) == (
        "update",
        "vendor_sku",
        Decimal("10.0000"),
        Decimal("12.50"),
    )
    assert (by_row[3].action, by_row[3].matched_by) == ("create", "mpn")
    assert (by_row[4].action, by_row[4].matched_by) == ("create", "gtin")
    assert by_row[5].action == "unmatched"
    assert preview.counts == {"create": 2, "update": 1, "unchanged": 0, "unmatched": 1, "error": 0}
    assert preview.valid_from == "2026-01-01"
    after = (await session.execute(select(CatalogEntry).where(CatalogEntry.price_list_id == pl.id))).scalars().all()
    assert len(after) == len(before) == 1 and after[0].unit_price == Decimal("10")


async def test_sap_condition_export_divides_by_price_unit(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    item = await _item(svc)
    csv = (f"MATNR;KBETR;KPEIN;KMEIN;KONWA;DATAB;DATBI\n{item.sku};1.234,50;100;KG;EUR;20260101;99991231\n").encode()

    preview = await svc.preview_price_list_import(vendor.id, "a017.csv", csv)

    assert preview.preset == "sap_condition"
    row = preview.rows[0]
    assert (row.action, row.matched_by, row.new_price) == ("create", "vendor_sku", Decimal("12.3450"))
    assert (preview.valid_from, preview.valid_to, preview.currencies) == ("2026-01-01", None, ["EUR"])

    result = await svc.commit_price_list_import(vendor.id, "a017.csv", csv, name="SAP 2026")
    entry = (
        await session.execute(select(CatalogEntry).where(CatalogEntry.price_list_id == result.price_list_id))
    ).scalar_one()
    assert entry.unit_price == Decimal("12.3450") and entry.vendor_sku == item.sku
    lists = await svc.list_price_lists(vendor.id)
    assert [(p.name, p.valid_from, p.entry_count) for p in lists] == [("SAP 2026", "2026-01-01", 1)]


async def test_commit_updates_and_reports_changed_rows(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    item = await _item(svc)
    first = await svc.commit_price_list_import(vendor.id, "p.csv", f"sku,unit price\n{item.sku},10\n".encode())
    assert first.counts["create"] == 1

    second = await svc.commit_price_list_import(
        vendor.id,
        "p.csv",
        f"sku,unit price\n{item.sku},11\nUNKNOWN,1\n".encode(),
        price_list_id=first.price_list_id,
    )
    assert second.counts["update"] == 1 and second.counts["unmatched"] == 1
    assert [r.sku for r in second.changed] == [item.sku]
    assert [r.action for r in second.unmatched] == ["unmatched"]


async def test_repeated_vendor_sku_refuses_the_commit(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    a, b = await _item(svc), await _item(svc)
    csv = f"vendor sku,sku,price\nX-1,{a.sku},1\nx-1,{b.sku},2\n".encode()
    preview = await svc.preview_price_list_import(vendor.id, "d.csv", csv)
    assert preview.duplicate_vendor_skus == ["X-1"] and preview.counts["error"] == 2
    with pytest.raises(HTTPException) as exc:
        await svc.commit_price_list_import(vendor.id, "d.csv", csv)
    assert exc.value.status_code == 422


async def test_explicit_mapping_overrides_the_guess(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    item = await _item(svc)
    csv = f"Code,Netto,Brutto\n{item.sku},5,9\n".encode()
    preview = await svc.preview_price_list_import(
        vendor.id, "m.csv", csv, mapping={"sku": "Code", "unit_price": "Brutto"}
    )
    assert preview.rows[0].new_price == Decimal("9")


# ── Discounts and net prices ─────────────────────────────────────────────────


async def test_discounts_store_net_and_source_on_entries(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    cat = await svc.create_category(ItemCategoryCreate(code=f"C-{_tag()}", name="Reinforcement"))
    a = await _item(svc, category_id=cat.id)
    b = await _item(svc)
    pl = await svc.create_price_list(
        vendor.id,
        PriceListCreate(
            name="2026",
            entries=[
                CatalogEntryCreate(catalog_item_id=a.id, unit_price=Decimal("100")),
                CatalogEntryCreate(catalog_item_id=b.id, unit_price=Decimal("50")),
            ],
        ),
    )
    await svc.create_discount(vendor.id, DiscountAgreementCreate(name="Frame", discount_pct=Decimal("10")))
    await svc.create_discount(
        vendor.id, DiscountAgreementCreate(name="Rebar", category_id=cat.id, discount_pct=Decimal("20"))
    )
    page = await svc.list_price_list_entries(pl.id)
    rows = {r.catalog_item_id: r for r in page.items}
    assert (rows[a.id].net_price, rows[a.id].discount_source) == (Decimal("80.0000"), "category")
    assert (rows[b.id].net_price, rows[b.id].discount_source) == (Decimal("45.0000"), "overall")
    stored = {
        e.catalog_item_id: e
        for e in (await session.execute(select(CatalogEntry).where(CatalogEntry.price_list_id == pl.id))).scalars()
    }
    assert stored[a.id].net_price == Decimal("80") and stored[a.id].discount_source == "category"
    comparison = await svc.compare_prices(a.id)
    assert comparison[0]["net_price"] == Decimal("80.0000") and comparison[0]["gross_price"] == Decimal("100")


async def test_fixed_net_above_list_price_is_refused(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    item = await _item(svc)
    await svc.create_price_list(
        vendor.id,
        PriceListCreate(name="L", entries=[CatalogEntryCreate(catalog_item_id=item.id, unit_price=Decimal("10"))]),
    )
    with pytest.raises(HTTPException) as exc:
        await svc.create_discount(
            vendor.id, DiscountAgreementCreate(name="x", catalog_item_id=item.id, fixed_net_price=Decimal("11"))
        )
    assert exc.value.status_code == 422


async def test_po_takes_the_net_price_and_keeps_it(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    item = await _item(svc)
    await svc.create_price_list(
        vendor.id,
        PriceListCreate(name="2026", entries=[CatalogEntryCreate(catalog_item_id=item.id, unit_price=Decimal("40"))]),
    )
    agreement = await svc.create_discount(vendor.id, DiscountAgreementCreate(name="Frame", discount_pct=Decimal("25")))

    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(catalog_item_id=item.id, description="Rebar", ordered_qty=Decimal("10")),
                POLineCreate(
                    catalog_item_id=item.id,
                    description="Rebar agreed",
                    ordered_qty=Decimal("1"),
                    unit_price=Decimal("29"),
                ),
            ],
        )
    )
    auto, manual = sorted(po.lines, key=lambda line: line.description)
    assert (auto.unit_price, auto.gross_unit_price, auto.discount_pct, auto.discount_source) == (
        Decimal("30"),
        Decimal("40"),
        Decimal("25"),
        "overall",
    )
    assert auto.line_total == Decimal("300") and po.subtotal == Decimal("329")
    assert (manual.unit_price, manual.discount_source) == (Decimal("29"), "manual")

    await svc.update_discount(agreement.id, DiscountAgreementUpdate(discount_pct=Decimal("50")))
    line = (await session.execute(select(POLine).where(POLine.id == auto.id))).scalar_one()
    await session.refresh(line)
    assert line.unit_price == Decimal("30")  # the order keeps the net it was created with


async def test_expired_price_list_cannot_price_a_new_po(session: AsyncSession) -> None:
    svc = SupplierCatalogsService(session)
    vendor = await _vendor(svc)
    item = await _item(svc)
    old = (date.today() - timedelta(days=1)).isoformat()
    pl = await svc.create_price_list(
        vendor.id,
        PriceListCreate(
            name="2024",
            valid_to=old,
            entries=[CatalogEntryCreate(catalog_item_id=item.id, unit_price=Decimal("10"))],
        ),
    )
    entry = (await session.execute(select(CatalogEntry).where(CatalogEntry.price_list_id == pl.id))).scalar_one()
    for line in (
        POLineCreate(catalog_item_id=item.id, description="x", ordered_qty=Decimal("1")),
        POLineCreate(catalog_entry_id=entry.id, description="x", ordered_qty=Decimal("1")),
    ):
        with pytest.raises(HTTPException) as exc:
            await svc.create_po(POCreateExt(vendor_id=vendor.id, project_id=uuid.uuid4(), lines=[line]))
        assert exc.value.status_code == 422
    # A hand-agreed price is still allowed.
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id, description="x", ordered_qty=Decimal("1"), unit_price=Decimal("9")
                )
            ],
        )
    )
    assert po.lines[0].unit_price == Decimal("9")


# ── Permissions and project check on the new routes ──────────────────────────


def _route_permissions() -> dict[tuple[str, str], set[str]]:
    from app.modules.supplier_catalogs.router import router

    out: dict[tuple[str, str], set[str]] = {}
    for route in router.routes:
        perms = {getattr(d.call, "permission", None) for d in route.dependant.dependencies}
        for method in route.methods:
            out[(method, route.path)] = {p for p in perms if p}
    return out


@pytest.mark.parametrize(
    ("method", "path", "permission"),
    [
        ("GET", "/price-list-import-presets", "supplier_catalogs.catalog.read"),
        ("POST", "/price-lists/{vendor_id}/import/preview", "supplier_catalogs.catalog.write"),
        ("POST", "/price-lists/{vendor_id}/import/commit", "supplier_catalogs.catalog.write"),
        ("GET", "/vendors/{vendor_id}/price-lists", "supplier_catalogs.catalog.read"),
        ("GET", "/price-lists/{price_list_id}/entries", "supplier_catalogs.catalog.read"),
        ("GET", "/price-lists/{price_list_id}/validation", "supplier_catalogs.catalog.read"),
        ("GET", "/vendors/{vendor_id}/discounts", "supplier_catalogs.discount.read"),
        ("POST", "/vendors/{vendor_id}/discounts", "supplier_catalogs.discount.manage"),
        ("PATCH", "/discounts/{agreement_id}", "supplier_catalogs.discount.manage"),
        ("DELETE", "/discounts/{agreement_id}", "supplier_catalogs.discount.manage"),
        ("GET", "/catalog-items/{item_id}/attachments", "supplier_catalogs.catalog.read"),
        ("POST", "/catalog-items/{item_id}/attachments", "supplier_catalogs.catalog.write"),
        ("DELETE", "/catalog-items/{item_id}/attachments/{attachment_id}", "supplier_catalogs.catalog.write"),
    ],
)
def test_new_routes_require_their_permission(method: str, path: str, permission: str) -> None:
    assert _route_permissions()[(method, path)] == {permission}


def test_discount_terms_are_closed_to_viewers() -> None:
    from app.core.permissions import Role, permission_registry
    from app.modules.supplier_catalogs.permissions import register_supplier_catalogs_permissions

    register_supplier_catalogs_permissions()
    assert not permission_registry.role_has_permission(Role.VIEWER, "supplier_catalogs.discount.read")
    assert not permission_registry.role_has_permission(Role.EDITOR, "supplier_catalogs.discount.manage")
    assert permission_registry.role_has_permission(Role.MANAGER, "supplier_catalogs.discount.manage")


async def test_item_document_of_a_foreign_project_is_refused_and_hidden(session: AsyncSession, monkeypatch) -> None:
    from app.modules.supplier_catalogs import router as r

    svc = SupplierCatalogsService(session)
    item = await _item(svc)
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    docs = {uuid.uuid4(): mine, uuid.uuid4(): theirs}

    async def _doc_project(self, document_id):  # noqa: ANN001
        return docs[document_id], "Datasheet.pdf"

    async def _gate(project_id, user_id, session):  # noqa: ANN001, ARG001
        if project_id != mine:
            raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(SupplierCatalogsService, "document_project", _doc_project)
    monkeypatch.setattr(r, "verify_project_access", _gate)
    mine_doc, their_doc = list(docs)

    att = await r.add_item_attachment(item.id, ItemAttachmentCreate(document_id=mine_doc), "u1", session, svc)
    assert (att.kind, att.title, att.project_id) == ("datasheet", "Datasheet.pdf", mine)
    with pytest.raises(HTTPException) as exc:
        await r.add_item_attachment(
            item.id, ItemAttachmentCreate(document_id=their_doc, kind="drawing"), "u1", session, svc
        )
    assert exc.value.status_code == 404

    # A link someone else made into a project this caller cannot open stays invisible and undeletable.
    foreign = CatalogItemAttachment(
        catalog_item_id=item.id, document_id=their_doc, project_id=theirs, kind="drawing", title="D"
    )
    session.add(foreign)
    await session.flush()
    listed = await r.list_item_attachments(item.id, "u1", session, svc)
    assert [a.document_id for a in listed] == [mine_doc]
    with pytest.raises(HTTPException) as exc:
        await r.delete_item_attachment(item.id, foreign.id, "u1", session, svc)
    assert exc.value.status_code == 404
    with pytest.raises(ValidationError):
        ItemAttachmentCreate(document_id=mine_doc, kind="script")
