# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Price list import, contractor discounts, net prices and item documents.

A mixin of :class:`app.modules.supplier_catalogs.service.SupplierCatalogsService`;
it uses the facade's ``session`` and repositories. Kept apart so the main
service file stays readable.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.supplier_catalogs import pricing
from app.modules.supplier_catalogs.models import (
    CatalogEntry,
    CatalogItem,
    CatalogItemAttachment,
    DiscountAgreement,
    ItemCategory,
    PriceList,
    Vendor,
)
from app.modules.supplier_catalogs.price_import import (
    PREVIEW_ROWS,
    ImportFileError,
    iter_keys,
    read_table,
)
from app.modules.supplier_catalogs.schemas import (
    DiscountAgreementCreate,
    DiscountAgreementUpdate,
    ImportRowResult,
    PriceListEntriesResponse,
    PriceListEntryRow,
    PriceListImportCommitResult,
    PriceListImportPreview,
    PriceListResponse,
)
from app.modules.supplier_catalogs.validators import (
    duplicate_skus,
    net_above_gross,
    price_list_expired,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _msg(key: str, **params: Any) -> str:
    return translate(f"supplier_catalogs.{key}", locale=get_locale(), **params)


def _unprocessable(key: str, **params: Any) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_msg(key, **params))


def _today() -> date:
    return date.today()


def pl_in_force(pl: PriceList, on: date) -> bool:
    """Active and inside its validity window on ``on``."""
    if pl.status != "active" or price_list_expired(pl.valid_to, on):
        return False
    if pl.valid_from:
        try:
            return date.fromisoformat(str(pl.valid_from)[:10]) <= on
        except ValueError:
            return True
    return True


class PriceListOps:
    """Import, discounts, net prices and item documents."""

    session: AsyncSession

    # ── Lookups ──────────────────────────────────────────────────────────────

    async def _vendor_or_404(self, vendor_id: uuid.UUID) -> Vendor:
        vendor = await self.session.get(Vendor, vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        return vendor

    async def _price_list_or_404(self, price_list_id: uuid.UUID) -> PriceList:
        pl = await self.session.get(PriceList, price_list_id)
        if pl is None:
            raise HTTPException(status_code=404, detail=_msg("price_list_not_found"))
        return pl

    async def _item_or_404(self, item_id: uuid.UUID) -> CatalogItem:
        item = await self.session.get(CatalogItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=_msg("catalog_item_not_found"))
        return item

    async def _category_parents(self) -> dict[uuid.UUID, uuid.UUID | None]:
        rows = (await self.session.execute(select(ItemCategory.id, ItemCategory.parent_id))).all()
        return {r[0]: r[1] for r in rows}

    async def _agreements(self, vendor_ids: set[uuid.UUID]) -> list[DiscountAgreement]:
        if not vendor_ids:
            return []
        stmt = select(DiscountAgreement).where(
            DiscountAgreement.vendor_id.in_(vendor_ids), DiscountAgreement.active.is_(True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def attachment_counts(self, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not item_ids:
            return {}
        stmt = (
            select(CatalogItemAttachment.catalog_item_id, func.count())
            .where(CatalogItemAttachment.catalog_item_id.in_(item_ids))
            .group_by(CatalogItemAttachment.catalog_item_id)
        )
        return {r[0]: int(r[1]) for r in (await self.session.execute(stmt)).all()}

    # ── Net prices ───────────────────────────────────────────────────────────

    async def resolve_entries(
        self,
        rows: list[tuple[CatalogEntry, PriceList, CatalogItem]],
        on: date | None = None,
    ) -> dict[uuid.UUID, pricing.NetPrice]:
        """Net price of each entry (keyed by entry id), resolved live on ``on``."""
        on = on or _today()
        parents = await self._category_parents()
        agreements = await self._agreements({pl.vendor_id for _, pl, _ in rows})
        out: dict[uuid.UUID, pricing.NetPrice] = {}
        for entry, pl, item in rows:
            gross = Decimal(entry.unit_price)
            net = pricing.resolve_net(
                gross=gross,
                vendor_id=pl.vendor_id,
                price_list_id=pl.id,
                catalog_item_id=item.id,
                category_chain=pricing.category_chain(item.category_id, parents),
                agreements=agreements,
                on=on,
            )
            # A discount column in the vendor's own file applies when no agreement does.
            if net.source == pricing.SOURCE_NONE and entry.discount_source == pricing.SOURCE_MANUAL:
                if entry.discount_pct is not None:
                    net = pricing.NetPrice(
                        gross,
                        pricing.apply_pct(gross, Decimal(entry.discount_pct)),
                        Decimal(entry.discount_pct),
                        pricing.SOURCE_MANUAL,
                        None,
                    )
            out[entry.id] = net
        return out

    async def recompute_net_prices(self, vendor_id: uuid.UUID, price_list_id: uuid.UUID | None = None) -> int:
        """Store the current net price, discount and its source on the vendor's entries.

        Returns the number of entries whose stored net changed. Orders already
        placed keep the price they were created with (POLine holds its own).
        """
        stmt = (
            select(CatalogEntry, PriceList, CatalogItem)
            .join(PriceList, PriceList.id == CatalogEntry.price_list_id)
            .join(CatalogItem, CatalogItem.id == CatalogEntry.catalog_item_id)
            .where(PriceList.vendor_id == vendor_id)
        )
        if price_list_id is not None:
            stmt = stmt.where(PriceList.id == price_list_id)
        rows = [(r[0], r[1], r[2]) for r in (await self.session.execute(stmt)).all()]
        resolved = await self.resolve_entries(rows)
        changed = 0
        for entry, _, _ in rows:
            np = resolved[entry.id]
            if entry.net_price is None or Decimal(entry.net_price) != np.net or entry.discount_source != np.source:
                changed += 1
            entry.net_price = np.net
            entry.discount_pct = np.discount_pct
            entry.discount_source = np.source
            entry.discount_agreement_id = np.agreement_id
        await self.session.flush()
        return changed

    async def current_entries_for_item(
        self,
        item_id: uuid.UUID,
        vendor_id: uuid.UUID | None = None,
        on: date | None = None,
    ) -> list[tuple[CatalogEntry, PriceList, Vendor, pricing.NetPrice]]:
        """Entries of price lists in force on ``on`` for an item, cheapest net first."""
        on = on or _today()
        stmt = (
            select(CatalogEntry, PriceList, Vendor, CatalogItem)
            .join(PriceList, PriceList.id == CatalogEntry.price_list_id)
            .join(Vendor, Vendor.id == PriceList.vendor_id)
            .join(CatalogItem, CatalogItem.id == CatalogEntry.catalog_item_id)
            .where(CatalogEntry.catalog_item_id == item_id, PriceList.status == "active", Vendor.status == "active")
        )
        if vendor_id is not None:
            stmt = stmt.where(PriceList.vendor_id == vendor_id)
        rows = [(r[0], r[1], r[2], r[3]) for r in (await self.session.execute(stmt)).all()]
        rows = [r for r in rows if pl_in_force(r[1], on)]
        resolved = await self.resolve_entries([(e, pl, it) for e, pl, _, it in rows], on)
        out = [(e, pl, v, resolved[e.id]) for e, pl, v, _ in rows]
        return sorted(out, key=lambda r: (r[3].net, r[0].lead_time_days))

    async def price_for_order_line(
        self,
        *,
        vendor_id: uuid.UUID,
        catalog_item_id: uuid.UUID | None,
        catalog_entry_id: uuid.UUID | None,
        on: date,
        strict: bool = True,
    ) -> tuple[CatalogEntry, pricing.NetPrice] | None:
        """The vendor price a new order line takes, or ``None`` when none applies.

        ``strict=False`` (a hand-entered price will be used) only looks the
        current price up and never refuses because an old list has expired.

        Raises:
            HTTPException: 422 when the named entry belongs to another vendor or
                its price list has expired (rule no_expired_price_list_on_po).
        """
        if catalog_entry_id is not None:
            entry = await self.session.get(CatalogEntry, catalog_entry_id)
            if entry is None:
                raise _unprocessable("entry_not_found")
            pl = await self.session.get(PriceList, entry.price_list_id)
            assert pl is not None
            if pl.vendor_id != vendor_id:
                raise _unprocessable("entry_other_vendor")
            if price_list_expired(pl.valid_to, on) or pl.status != "active":
                raise _unprocessable("price_list_expired", name=pl.name, valid_to=pl.valid_to or "")
            item = await self._item_or_404(entry.catalog_item_id)
            return entry, (await self.resolve_entries([(entry, pl, item)], on))[entry.id]
        if catalog_item_id is None:
            return None
        current = await self.current_entries_for_item(catalog_item_id, vendor_id=vendor_id, on=on)
        if current:
            entry, _, _, np = current[0]
            return entry, np
        # Only an expired or future list quotes this item: say so instead of pricing at zero.
        stmt = (
            select(PriceList)
            .join(CatalogEntry, CatalogEntry.price_list_id == PriceList.id)
            .where(CatalogEntry.catalog_item_id == catalog_item_id, PriceList.vendor_id == vendor_id)
        )
        stale = list((await self.session.execute(stmt)).scalars().all())
        expired = [p for p in stale if price_list_expired(p.valid_to, on)]
        if expired and strict:
            raise _unprocessable("price_list_expired", name=expired[0].name, valid_to=expired[0].valid_to or "")
        return None

    # ── Price list views ─────────────────────────────────────────────────────

    async def list_price_lists(self, vendor_id: uuid.UUID) -> list[PriceListResponse]:
        await self._vendor_or_404(vendor_id)
        counts = (
            select(CatalogEntry.price_list_id, func.count().label("n")).group_by(CatalogEntry.price_list_id).subquery()
        )
        stmt = (
            select(PriceList, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.price_list_id == PriceList.id)
            .where(PriceList.vendor_id == vendor_id)
            .order_by(PriceList.created_at.desc())
        )
        today = _today()
        out = []
        for pl, n in (await self.session.execute(stmt)).all():
            resp = PriceListResponse.model_validate(pl)
            resp.entry_count = int(n)
            resp.expired = price_list_expired(pl.valid_to, today)
            out.append(resp)
        return out

    async def list_price_list_entries(
        self,
        price_list_id: uuid.UUID,
        *,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> PriceListEntriesResponse:
        pl = await self._price_list_or_404(price_list_id)
        base = (
            select(CatalogEntry, CatalogItem)
            .join(CatalogItem, CatalogItem.id == CatalogEntry.catalog_item_id)
            .where(CatalogEntry.price_list_id == price_list_id)
        )
        if search:
            like = f"%{search.strip()}%"
            base = base.where(
                CatalogItem.sku.ilike(like)
                | CatalogItem.name.ilike(like)
                | CatalogEntry.vendor_sku.ilike(like)
                | CatalogItem.mpn.ilike(like)
            )
        total = int((await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
        rows = (await self.session.execute(base.order_by(CatalogItem.sku).offset(offset).limit(limit))).all()
        pairs = [(r[0], r[1]) for r in rows]
        resolved = await self.resolve_entries([(e, pl, it) for e, it in pairs])
        att = await self.attachment_counts([it.id for _, it in pairs])
        items = []
        for e, it in pairs:
            np = resolved[e.id]
            items.append(
                PriceListEntryRow(
                    entry_id=e.id,
                    catalog_item_id=it.id,
                    sku=it.sku,
                    name=it.name,
                    unit_of_measure=it.unit_of_measure,
                    vendor_sku=e.vendor_sku,
                    mpn=it.mpn,
                    gtin=it.gtin,
                    gross_price=np.gross,
                    net_price=np.net,
                    discount_pct=np.discount_pct,
                    discount_source=np.source,
                    discount_agreement_id=np.agreement_id,
                    min_order_qty=e.min_order_qty,
                    lead_time_days=e.lead_time_days,
                    product_url=it.product_url,
                    attachment_count=att.get(it.id, 0),
                )
            )
        resp = PriceListResponse.model_validate(pl)
        resp.entry_count = total if not search else resp.entry_count
        resp.expired = price_list_expired(pl.valid_to, _today())
        return PriceListEntriesResponse(price_list=resp, items=items, total=total, offset=offset, limit=limit)

    # ── Import ───────────────────────────────────────────────────────────────

    async def _plan_import(
        self,
        vendor_id: uuid.UUID,
        filename: str,
        raw: bytes,
        mapping: dict[str, str] | None,
        preset: str | None,
        target_price_list_id: uuid.UUID | None,
        currency: str | None,
    ) -> tuple[PriceListImportPreview, list[tuple[ImportRowResult, dict[str, Any]]]]:
        await self._vendor_or_404(vendor_id)
        target: PriceList | None = None
        if target_price_list_id is not None:
            target = await self._price_list_or_404(target_price_list_id)
            if target.vendor_id != vendor_id:
                raise HTTPException(status_code=404, detail=_msg("price_list_not_found"))
        try:
            table, used, preset_name = read_table(filename, raw, mapping, preset)
        except ImportFileError as exc:
            raise _unprocessable("import_unreadable", reason=exc.code) from exc
        if "unit_price" not in used:
            raise _unprocessable("import_needs_price_column")

        # Candidate items, one query per key kind.
        wanted: dict[str, set[str]] = {k: set() for k in ("vendor_sku", "mpn", "gtin", "sku")}
        for pr in table.rows:
            for key, value in iter_keys(pr.values):
                wanted[key].add(value)
        by_key: dict[str, dict[str, CatalogItem]] = {k: {} for k in wanted}
        if wanted["vendor_sku"]:
            stmt = (
                select(CatalogEntry.vendor_sku, CatalogItem)
                .join(CatalogItem, CatalogItem.id == CatalogEntry.catalog_item_id)
                .join(PriceList, PriceList.id == CatalogEntry.price_list_id)
                .where(PriceList.vendor_id == vendor_id, func.upper(CatalogEntry.vendor_sku).in_(wanted["vendor_sku"]))
            )
            for vsku, item in (await self.session.execute(stmt)).all():
                by_key["vendor_sku"].setdefault(str(vsku).strip().upper(), item)
        for key, col in (("mpn", CatalogItem.mpn), ("gtin", CatalogItem.gtin), ("sku", CatalogItem.sku)):
            if wanted[key]:
                stmt = select(CatalogItem).where(func.upper(col).in_(wanted[key]))
                for item in (await self.session.execute(stmt)).scalars().all():
                    by_key[key].setdefault(str(getattr(item, key)).strip().upper(), item)
        # The vendor SKU of a row may also be our own SKU (vendors often quote it back).
        if wanted["vendor_sku"]:
            stmt = select(CatalogItem).where(func.upper(CatalogItem.sku).in_(wanted["vendor_sku"]))
            for item in (await self.session.execute(stmt)).scalars().all():
                by_key["vendor_sku"].setdefault(item.sku.strip().upper(), item)

        existing: dict[uuid.UUID, CatalogEntry] = {}
        if target is not None:
            stmt = select(CatalogEntry).where(CatalogEntry.price_list_id == target.id)
            existing = {e.catalog_item_id: e for e in (await self.session.execute(stmt)).scalars().all()}

        counts = {"create": 0, "update": 0, "unchanged": 0, "unmatched": 0, "error": 0}
        planned: list[tuple[ImportRowResult, dict[str, Any]]] = []
        seen_items: set[uuid.UUID] = set()
        dups = duplicate_skus([pr.values.get("vendor_sku") for pr in table.rows])
        dup_set = set(dups)
        days_from: list[str] = []
        days_to: list[str] = []
        currencies: set[str] = set()
        for pr in table.rows:
            vals = pr.values
            res = ImportRowResult(
                row=pr.row,
                action="error",
                vendor_sku=vals.get("vendor_sku"),
                new_price=vals.get("unit_price"),
                currency=(vals.get("currency") or currency or (target.currency if target else None)),
                errors=list(pr.errors),
            )
            if vals.get("currency"):
                currencies.add(str(vals["currency"]).upper())
            if vals.get("valid_from"):
                days_from.append(vals["valid_from"])
            if vals.get("valid_to"):
                days_to.append(vals["valid_to"])
            vsku = (vals.get("vendor_sku") or "").strip().upper()
            if vsku and vsku in dup_set:
                res.errors.append("duplicate_vendor_sku")
            if res.errors:
                counts["error"] += 1
                planned.append((res, vals))
                continue
            item = None
            for key, value in iter_keys(vals):
                item = by_key[key].get(value)
                if item is not None:
                    res.matched_by = key
                    break
            if item is None:
                res.action = "unmatched"
                counts["unmatched"] += 1
                planned.append((res, vals))
                continue
            res.catalog_item_id, res.sku, res.item_name = item.id, item.sku, item.name
            if item.id in seen_items:
                res.action, res.errors = "error", ["duplicate_item"]
                counts["error"] += 1
                planned.append((res, vals))
                continue
            seen_items.add(item.id)
            old = existing.get(item.id)
            if old is None:
                res.action = "create"
            else:
                res.old_price = Decimal(old.unit_price)
                res.action = "unchanged" if Decimal(old.unit_price) == vals["unit_price"] else "update"
            counts[res.action] += 1
            planned.append((res, vals))

        preview = PriceListImportPreview(
            preset=preset_name,
            sheet=table.sheet,
            headers=table.headers,
            mapping=used,
            sample=table.sample,
            total_rows=len(table.rows),
            counts=counts,
            duplicate_vendor_skus=dups[:50],
            valid_from=min(days_from) if days_from else None,
            valid_to=max(days_to) if days_to else None,
            currencies=sorted(currencies),
            rows=[r for r, _ in planned[:PREVIEW_ROWS]],
            rows_truncated=len(planned) > PREVIEW_ROWS,
        )
        return preview, planned

    async def preview_price_list_import(
        self,
        vendor_id: uuid.UUID,
        filename: str,
        raw: bytes,
        *,
        mapping: dict[str, str] | None = None,
        preset: str | None = None,
        price_list_id: uuid.UUID | None = None,
        currency: str | None = None,
    ) -> PriceListImportPreview:
        """Dry run: read, map and match the file, write nothing."""
        preview, _ = await self._plan_import(vendor_id, filename, raw, mapping, preset, price_list_id, currency)
        return preview

    async def commit_price_list_import(
        self,
        vendor_id: uuid.UUID,
        filename: str,
        raw: bytes,
        *,
        mapping: dict[str, str] | None = None,
        preset: str | None = None,
        price_list_id: uuid.UUID | None = None,
        name: str | None = None,
        currency: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        user_id: str | None = None,
    ) -> PriceListImportCommitResult:
        """Write the rows the preview called create or update; report the rest.

        Rows with an error refuse the whole import only when they are repeated
        vendor SKUs (rule no_duplicate_sku_in_price_list); other bad rows are
        skipped and reported.
        """
        preview, planned = await self._plan_import(vendor_id, filename, raw, mapping, preset, price_list_id, currency)
        if preview.duplicate_vendor_skus:
            raise _unprocessable("duplicate_vendor_sku", skus=", ".join(preview.duplicate_vendor_skus[:10]))
        vf = valid_from or preview.valid_from
        vt = valid_to or preview.valid_to
        if vf and vt and vt < vf:
            raise _unprocessable("valid_to_before_valid_from")
        if price_list_id is None:
            pl = PriceList(
                vendor_id=vendor_id,
                name=(name or filename or "Imported price list")[:255],
                valid_from=vf,
                valid_to=vt,
                currency=(currency or (preview.currencies[0] if len(preview.currencies) == 1 else None) or "EUR")[:10],
                status="active",
                uploaded_by=user_id,
            )
            self.session.add(pl)
            await self.session.flush()
        else:
            pl = await self._price_list_or_404(price_list_id)
            if valid_from or valid_to:
                pl.valid_from, pl.valid_to = vf, vt
        stmt = select(CatalogEntry).where(CatalogEntry.price_list_id == pl.id)
        existing = {e.catalog_item_id: e for e in (await self.session.execute(stmt)).scalars().all()}
        for res, vals in planned:
            if res.action not in {"create", "update"} or res.catalog_item_id is None:
                continue
            entry = existing.get(res.catalog_item_id)
            if entry is None:
                entry = CatalogEntry(price_list_id=pl.id, catalog_item_id=res.catalog_item_id)
                self.session.add(entry)
                existing[res.catalog_item_id] = entry
            entry.unit_price = vals["unit_price"]
            if vals.get("discount_pct") is not None:
                entry.discount_pct, entry.discount_source = vals["discount_pct"], pricing.SOURCE_MANUAL
            elif entry.discount_source == pricing.SOURCE_MANUAL:
                entry.discount_pct, entry.discount_source = None, pricing.SOURCE_NONE
            if vals.get("vendor_sku"):
                entry.vendor_sku = str(vals["vendor_sku"])[:100]
            if vals.get("min_order_qty") is not None:
                entry.min_order_qty = vals["min_order_qty"]
            if vals.get("lead_time_days") is not None:
                entry.lead_time_days = int(vals["lead_time_days"])
            if vals.get("notes"):
                entry.notes = str(vals["notes"])
        await self.session.flush()
        await self.recompute_net_prices(vendor_id, pl.id)
        rows = [r for r, _ in planned]
        return PriceListImportCommitResult(
            price_list_id=pl.id,
            counts=preview.counts,
            unmatched=[r for r in rows if r.action in {"unmatched", "error"}][:PREVIEW_ROWS],
            changed=[r for r in rows if r.action == "update"][:PREVIEW_ROWS],
        )

    # ── Discount agreements ──────────────────────────────────────────────────

    async def list_discounts(self, vendor_id: uuid.UUID) -> list[DiscountAgreement]:
        await self._vendor_or_404(vendor_id)
        stmt = (
            select(DiscountAgreement)
            .where(DiscountAgreement.vendor_id == vendor_id)
            .order_by(DiscountAgreement.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _check_fixed_net(self, agreement: DiscountAgreement) -> None:
        """Refuse a fixed net above the item's list price on any of the vendor's lists in scope."""
        if agreement.fixed_net_price is None or agreement.catalog_item_id is None:
            return
        stmt = (
            select(CatalogEntry.unit_price)
            .join(PriceList, PriceList.id == CatalogEntry.price_list_id)
            .where(
                CatalogEntry.catalog_item_id == agreement.catalog_item_id,
                PriceList.vendor_id == agreement.vendor_id,
            )
        )
        if agreement.price_list_id is not None:
            stmt = stmt.where(PriceList.id == agreement.price_list_id)
        for (gross,) in (await self.session.execute(stmt)).all():
            if net_above_gross(gross, agreement.fixed_net_price):
                raise _unprocessable("net_above_gross", net=str(agreement.fixed_net_price), gross=str(gross))

    async def create_discount(self, vendor_id: uuid.UUID, data: DiscountAgreementCreate) -> DiscountAgreement:
        await self._vendor_or_404(vendor_id)
        if data.price_list_id is not None:
            pl = await self._price_list_or_404(data.price_list_id)
            if pl.vendor_id != vendor_id:
                raise HTTPException(status_code=404, detail=_msg("price_list_not_found"))
        if data.category_id is not None and await self.session.get(ItemCategory, data.category_id) is None:
            raise _unprocessable("category_not_found")
        if data.catalog_item_id is not None:
            await self._item_or_404(data.catalog_item_id)
        agreement = DiscountAgreement(
            vendor_id=vendor_id,
            price_list_id=data.price_list_id,
            category_id=data.category_id,
            catalog_item_id=data.catalog_item_id,
            name=data.name,
            reference=data.reference,
            discount_pct=data.discount_pct,
            fixed_net_price=data.fixed_net_price,
            valid_from=data.valid_from.isoformat() if data.valid_from else None,
            valid_to=data.valid_to.isoformat() if data.valid_to else None,
            active=data.active,
            notes=data.notes,
        )
        await self._check_fixed_net(agreement)
        self.session.add(agreement)
        await self.session.flush()
        await self.recompute_net_prices(vendor_id)
        return agreement

    async def _discount_or_404(self, agreement_id: uuid.UUID) -> DiscountAgreement:
        agreement = await self.session.get(DiscountAgreement, agreement_id)
        if agreement is None:
            raise HTTPException(status_code=404, detail=_msg("discount_not_found"))
        return agreement

    async def update_discount(self, agreement_id: uuid.UUID, data: DiscountAgreementUpdate) -> DiscountAgreement:
        agreement = await self._discount_or_404(agreement_id)
        payload = data.model_dump(exclude_unset=True)
        for key in ("valid_from", "valid_to"):
            if key in payload and payload[key] is not None:
                payload[key] = payload[key].isoformat()
        for key, value in payload.items():
            setattr(agreement, key, value)
        if (agreement.discount_pct is None) == (agreement.fixed_net_price is None):
            raise _unprocessable("discount_basis")
        if agreement.fixed_net_price is not None and agreement.catalog_item_id is None:
            raise _unprocessable("discount_basis")
        if agreement.valid_from and agreement.valid_to and agreement.valid_to < agreement.valid_from:
            raise _unprocessable("valid_to_before_valid_from")
        await self._check_fixed_net(agreement)
        await self.session.flush()
        await self.recompute_net_prices(agreement.vendor_id)
        return agreement

    async def delete_discount(self, agreement_id: uuid.UUID) -> None:
        agreement = await self._discount_or_404(agreement_id)
        vendor_id = agreement.vendor_id
        await self.session.delete(agreement)
        await self.session.flush()
        await self.recompute_net_prices(vendor_id)

    # ── Item documents ───────────────────────────────────────────────────────

    async def list_item_attachments(self, item_id: uuid.UUID) -> list[CatalogItemAttachment]:
        await self._item_or_404(item_id)
        stmt = (
            select(CatalogItemAttachment)
            .where(CatalogItemAttachment.catalog_item_id == item_id)
            .order_by(CatalogItemAttachment.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def document_project(self, document_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        """``(project_id, name)`` of a documents row, 404 when there is none."""
        from app.modules.documents.models import Document  # noqa: PLC0415

        doc = await self.session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=translate("errors.document_not_found", locale=get_locale()))
        return doc.project_id, str(doc.name or "")

    async def add_item_attachment(
        self,
        item_id: uuid.UUID,
        *,
        document_id: uuid.UUID,
        project_id: uuid.UUID,
        kind: str,
        title: str,
        user_id: str | None,
    ) -> CatalogItemAttachment:
        await self._item_or_404(item_id)
        stmt = select(CatalogItemAttachment).where(
            CatalogItemAttachment.catalog_item_id == item_id, CatalogItemAttachment.document_id == document_id
        )
        found = (await self.session.execute(stmt)).scalar_one_or_none()
        if found is not None:
            return found
        att = CatalogItemAttachment(
            catalog_item_id=item_id,
            document_id=document_id,
            project_id=project_id,
            kind=kind,
            title=title[:255] or kind,
            added_by=user_id,
        )
        self.session.add(att)
        await self.session.flush()
        return att

    async def get_item_attachment(self, item_id: uuid.UUID, attachment_id: uuid.UUID) -> CatalogItemAttachment:
        att = await self.session.get(CatalogItemAttachment, attachment_id)
        if att is None or att.catalog_item_id != item_id:
            raise HTTPException(status_code=404, detail=_msg("attachment_not_found"))
        return att

    async def delete_item_attachment(self, att: CatalogItemAttachment) -> None:
        await self.session.delete(att)
        await self.session.flush()
