# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Levies, payment discount and bidder search for subcontracts.

:func:`set_subcontract_terms` is the entry point the tender award calls to
carry the negotiated levies and payment discount into the subcontract. The
rest serves the API: the company levy catalogue, per-subcontract terms, the
deduction statement of a payment application, and the bidder picker's radius
search and favourites.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.core.validation.messages import translate
from app.modules.subcontractors.models import (
    PaymentApplication,
    RetentionLedger,
    SubcontractAgreement,
    Subcontractor,
)
from app.modules.subcontractors.terms import (
    LevyTerm,
    PaymentTerms,
    build_deductions,
    money,
    retention_cap_amount,
)
from app.modules.subcontractors.terms_models import (
    FirmLocation,
    LevyCatalogueItem,
    SubcontractLevy,
    SubcontractorFavourite,
    SubcontractTerms,
)
from app.modules.subcontractors.terms_schemas import (
    BidderRow,
    BidderSearchResponse,
    FirmLocationResponse,
    LevyCatalogueItemIn,
    PackLevyDefault,
    SubcontractTermsIn,
    SubcontractTermsResponse,
    ValidationRow,
)

logger = logging.getLogger(__name__)

#: Rule set run on a deduction statement (core reconciliation plus pack rules).
TERMS_RULE_SET = "subcontract_terms"
#: Rule set run on the bidder list of a radius search.
BIDDER_RULE_SET = "bidder_search"
#: File a country pack ships beside its manifest to suggest levy names.
PACK_LEVY_FILE = "subcontract_levies.json"
#: Pay applications already counted as paid or payable for the retention cap.
_COUNTED_STATES = ("foreman_approved", "finance_approved", "paid")
#: The most firms one radius search reads.
_SEARCH_CAP = 2000


def _not_found(key: str = "errors.resource_not_found") -> HTTPException:
    return HTTPException(status_code=404, detail=translate(key, locale=get_locale()))


def _str_money(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _str_money(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_str_money(v) for v in value]
    return value


def _rows(report: Any) -> list[ValidationRow]:
    return [
        ValidationRow(
            rule_id=r.rule_id,
            severity=r.severity.value,
            passed=r.passed,
            message=r.message,
            element_ref=r.element_ref,
            suggestion=r.suggestion,
        )
        for r in report.results
    ]


# ── Pack defaults ────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _pack_levy_files() -> tuple[tuple[str, str, dict], ...]:
    """``(slug, country, parsed file)`` of every pack that ships levy names."""
    try:
        from app.core.partner_pack.discovery import discover_packs, read_pack_file
    except Exception:  # noqa: BLE001 - packs are optional
        return ()
    out: list[tuple[str, str, dict]] = []
    try:
        packs = discover_packs()
    except Exception:  # noqa: BLE001
        logger.debug("subcontract levies: pack discovery failed", exc_info=True)
        return ()
    for pack in packs:
        try:
            data = read_pack_file(pack.slug, PACK_LEVY_FILE)
            if not data:
                continue
            raw = json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001 - one broken pack file costs only that pack
            logger.warning("subcontract levies: unreadable %s in pack %s", PACK_LEVY_FILE, pack.slug)
            continue
        if not isinstance(raw, dict):
            continue
        country = str(raw.get("country") or (pack.metadata or {}).get("country") or "").upper()
        if country:
            out.append((pack.slug, country, raw))
    return tuple(out)


def pack_levy_defaults(
    countries: Iterable[str], locale: str = "en", extra: Sequence[tuple[str, str, dict]] | None = None
) -> list[PackLevyDefault]:
    """Levy names the packs of ``countries`` suggest. ``extra`` lets tests inject pack data."""
    wanted = {c.strip().upper() for c in countries if c and c.strip() and c != "*"}
    if not wanted:
        return []
    lang = (locale or "en").split("-")[0].lower()
    out: list[PackLevyDefault] = []
    for slug, country, raw in extra if extra is not None else _pack_levy_files():
        if country not in wanted:
            continue
        for entry in raw.get("levies") or []:
            if not isinstance(entry, dict) or not entry.get("code"):
                continue
            names = entry.get("name") if isinstance(entry.get("name"), dict) else {"en": str(entry.get("name"))}
            out.append(
                PackLevyDefault(
                    code=str(entry["code"])[:60],
                    name=str(names.get(lang) or names.get("en") or next(iter(names.values()), entry["code"]))[:255],
                    basis="fixed" if entry.get("basis") == "fixed" else "percent",
                    applies_at="final_account" if entry.get("applies_at") == "final_account" else "each_invoice",
                    country=country,
                    pack=slug,
                    source_note=str(raw.get("source") or "")[:500],
                )
            )
    return out


async def _workspace_countries(session: AsyncSession, payload: dict[str, Any], user_id: str) -> list[str]:
    try:
        from app.modules.doc_templates.service import workspace_countries
    except Exception:  # noqa: BLE001 - no doc_templates module means no market profile reader
        return []
    return await workspace_countries(session, payload, user_id)


# ── Award entry point ────────────────────────────────────────────────────


def _apply_terms(entity: SubcontractTerms, data: SubcontractTermsIn) -> None:
    entity.retention_cap_percent = data.retention_cap_percent
    entity.payment_discount_percent = data.payment_discount_percent
    entity.payment_discount_days = data.payment_discount_days
    entity.payment_discount_agreed = data.payment_discount_agreed
    entity.levies = [
        SubcontractLevy(
            catalogue_id=levy.catalogue_id,
            code=levy.code,
            name=levy.name,
            basis=levy.basis,
            rate_percent=levy.rate_percent if levy.basis == "percent" else None,
            fixed_amount=levy.fixed_amount if levy.basis == "fixed" else None,
            applies_at=levy.applies_at,
            levy_base=levy.levy_base,
            sort_order=index,
        )
        for index, levy in enumerate(data.levies)
    ]


async def _find_terms(
    session: AsyncSession, *, agreement_id: uuid.UUID | None, contract_id: uuid.UUID | None
) -> SubcontractTerms | None:
    if agreement_id is not None:
        found = (
            await session.execute(select(SubcontractTerms).where(SubcontractTerms.agreement_id == agreement_id))
        ).scalar_one_or_none()
        if found is not None:
            return found
    if contract_id is not None:
        return (
            await session.execute(select(SubcontractTerms).where(SubcontractTerms.contract_id == contract_id))
        ).scalar_one_or_none()
    return None


async def set_subcontract_terms(
    session: AsyncSession,
    *,
    agreement_id: uuid.UUID | None = None,
    contract_id: uuid.UUID | None = None,
    terms: SubcontractTermsIn | dict[str, Any],
    source: str = "award",
    user_id: str | None = None,
) -> SubcontractTerms:
    """Store the levies and payment discount of a subcontract (create or replace).

    The tender award calls this once it has created the subcontract, with the
    agreement, the contracts-module contract, or both. Terms already stored for
    either id are replaced, never duplicated; the levy list is replaced whole.
    Flushes, does not commit: the caller owns the transaction.

    Args:
        session: The caller's session.
        agreement_id: ``oe_subcontractors_agreement.id`` of the subcontract.
        contract_id: ``oe_contracts_contract.id`` writing the same subcontract.
        terms: The terms; a dict is validated as :class:`SubcontractTermsIn`.
        source: ``award`` or ``manual``.
        user_id: Who set them.

    Returns:
        The stored terms row with its levies.

    Raises:
        ValueError: Neither id was given.
    """
    if agreement_id is None and contract_id is None:
        raise ValueError("set_subcontract_terms needs an agreement_id or a contract_id")
    data = terms if isinstance(terms, SubcontractTermsIn) else SubcontractTermsIn.model_validate(terms)
    if contract_id is None and agreement_id is not None:
        agreement = await session.get(SubcontractAgreement, agreement_id)
        contract_id = agreement.contract_id if agreement is not None else None
    entity = await _find_terms(session, agreement_id=agreement_id, contract_id=contract_id)
    if entity is None:
        entity = SubcontractTerms(created_by=user_id, levies=[])
        session.add(entity)
    if agreement_id is not None:
        entity.agreement_id = agreement_id
    if contract_id is not None:
        entity.contract_id = contract_id
    entity.source = source[:20]
    _apply_terms(entity, data)
    await session.flush()
    return entity


def terms_to_calc(
    entity: SubcontractTerms | None, *, retention_percent: Decimal, contract_sum: Decimal
) -> PaymentTerms:
    """Turn stored terms into the calculator's :class:`PaymentTerms`."""
    if entity is None:
        return PaymentTerms(retention_percent=retention_percent)
    return PaymentTerms(
        retention_percent=retention_percent,
        retention_cap_amount=retention_cap_amount(contract_sum, entity.retention_cap_percent),
        payment_discount_percent=entity.payment_discount_percent,
        payment_discount_days=entity.payment_discount_days,
        payment_discount_agreed=bool(entity.payment_discount_agreed),
        levies=tuple(
            LevyTerm(
                code=levy.code,
                name=levy.name,
                basis=levy.basis,
                rate_percent=levy.rate_percent,
                fixed_amount=levy.fixed_amount,
                applies_at=levy.applies_at,
                levy_base=levy.levy_base,
            )
            for levy in entity.levies
        ),
    )


class SubcontractTermsService:
    """Levy catalogue, subcontract terms, deduction statements and bidder search."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Catalogue ────────────────────────────────────────────────────────

    async def list_catalogue(self, *, active_only: bool = False) -> list[LevyCatalogueItem]:
        stmt = select(LevyCatalogueItem).order_by(LevyCatalogueItem.sort_order, LevyCatalogueItem.name)
        if active_only:
            stmt = stmt.where(LevyCatalogueItem.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def _code_taken(self, code: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(LevyCatalogueItem).where(LevyCatalogueItem.code == code)
        if exclude is not None:
            stmt = stmt.where(LevyCatalogueItem.id != exclude)
        return bool((await self.session.execute(stmt)).scalar_one())

    async def create_catalogue_item(self, data: LevyCatalogueItemIn, *, source: str = "company") -> LevyCatalogueItem:
        if await self._code_taken(data.code):
            raise HTTPException(status_code=409, detail=translate("errors.levy_code_taken", locale=get_locale()))
        entity = LevyCatalogueItem(**data.model_dump(), source=source)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update_catalogue_item(self, item_id: uuid.UUID, data: LevyCatalogueItemIn) -> LevyCatalogueItem:
        entity = await self.session.get(LevyCatalogueItem, item_id)
        if entity is None:
            raise _not_found()
        if await self._code_taken(data.code, exclude=item_id):
            raise HTTPException(status_code=409, detail=translate("errors.levy_code_taken", locale=get_locale()))
        for key, value in data.model_dump().items():
            setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def delete_catalogue_item(self, item_id: uuid.UUID) -> None:
        entity = await self.session.get(LevyCatalogueItem, item_id)
        if entity is None:
            raise _not_found()
        await self.session.delete(entity)
        await self.session.flush()

    async def import_pack_defaults(self, defaults: Sequence[PackLevyDefault]) -> int:
        """Add the pack's levy names the catalogue lacks, inactive and without a rate."""
        have = {item.code for item in await self.list_catalogue()}
        added = 0
        for index, entry in enumerate(defaults):
            if entry.code in have:
                continue
            self.session.add(
                LevyCatalogueItem(
                    code=entry.code,
                    name=entry.name,
                    basis=entry.basis,
                    applies_at=entry.applies_at,
                    # No rate is sourced; the company enters its own before using it.
                    is_active=False,
                    sort_order=100 + index,
                    source=f"pack:{entry.pack}"[:60],
                )
            )
            have.add(entry.code)
            added += 1
        await self.session.flush()
        return added

    async def catalogue_defaults_for(
        self, payload: dict[str, Any], user_id: str, items: Sequence[LevyCatalogueItem]
    ) -> list[PackLevyDefault]:
        countries = await _workspace_countries(self.session, payload, user_id)
        codes = {item.code for item in items}
        defaults = pack_levy_defaults(countries, get_locale())
        return [d.model_copy(update={"in_catalogue": d.code in codes}) for d in defaults]

    # ── Terms ────────────────────────────────────────────────────────────

    async def _agreement(self, agreement_id: uuid.UUID) -> SubcontractAgreement:
        agreement = await self.session.get(SubcontractAgreement, agreement_id)
        if agreement is None:
            raise _not_found("errors.agreement_not_found")
        return agreement

    async def get_terms(self, agreement_id: uuid.UUID) -> SubcontractTermsResponse:
        agreement = await self._agreement(agreement_id)
        entity = await _find_terms(self.session, agreement_id=agreement.id, contract_id=agreement.contract_id)
        if entity is None:
            return SubcontractTermsResponse(
                agreement_id=agreement.id, contract_id=agreement.contract_id, is_default=True
            )
        return SubcontractTermsResponse.model_validate(entity)

    async def put_terms(
        self, agreement_id: uuid.UUID, data: SubcontractTermsIn, user_id: str | None
    ) -> SubcontractTermsResponse:
        agreement = await self._agreement(agreement_id)
        entity = await set_subcontract_terms(
            self.session,
            agreement_id=agreement.id,
            contract_id=agreement.contract_id,
            terms=data,
            source="manual",
            user_id=user_id,
        )
        await self.session.refresh(entity, attribute_names=["levies"])
        return SubcontractTermsResponse.model_validate(entity)

    async def _retained_before(self, agreement_id: uuid.UUID, exclude_pa: uuid.UUID | None) -> Decimal:
        stmt = select(
            func.coalesce(func.sum(RetentionLedger.accrued_amount), 0),
            func.coalesce(func.sum(RetentionLedger.released_amount), 0),
        ).where(RetentionLedger.agreement_id == agreement_id)
        if exclude_pa is not None:
            stmt = stmt.where(
                (RetentionLedger.payment_application_id.is_(None))
                | (RetentionLedger.payment_application_id != exclude_pa)
            )
        accrued, released = (await self.session.execute(stmt)).one()
        return money(accrued) - money(released)

    async def _project_country(self, project_id: uuid.UUID) -> str | None:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            return None
        return (project.country_code or "").strip().upper() or None

    async def deduction_statement(
        self,
        agreement_id: uuid.UUID,
        *,
        payment_application_id: uuid.UUID | None = None,
        work_value: Decimal | None = None,
        final_account: bool = False,
        invoice_date: date | None = None,
        paid_on: date | None = None,
    ) -> dict[str, Any]:
        """The deduction statement of a payment application (or of a typed work value)."""
        agreement = await self._agreement(agreement_id)
        pa: PaymentApplication | None = None
        if payment_application_id is not None:
            pa = await self.session.get(PaymentApplication, payment_application_id)
            if pa is None or pa.agreement_id != agreement.id:
                raise _not_found()
        if work_value is None:
            work_value = (
                money(pa.approved_gross_amount if pa.approved_gross_amount is not None else pa.gross_amount)
                if pa is not None
                else Decimal("0")
            )
        if pa is not None:
            invoice_date = invoice_date or (pa.submitted_at.date() if pa.submitted_at else None)
            paid_on = paid_on or (pa.paid_at.date() if pa.paid_at else None)
        entity = await _find_terms(self.session, agreement_id=agreement.id, contract_id=agreement.contract_id)
        contract_sum = money(agreement.total_value)
        calc = terms_to_calc(entity, retention_percent=money(agreement.retention_percent), contract_sum=contract_sum)
        statement = build_deductions(
            work_value,
            calc,
            retained_to_date=await self._retained_before(agreement.id, payment_application_id),
            final_account=final_account,
            invoice_date=invoice_date,
            paid_on=paid_on,
        )
        country = await self._project_country(agreement.project_id)
        payload = {
            **_str_money(statement),
            "country_code": country,
            "element_ref": pa.application_number if pa is not None else agreement.title,
        }
        report = await validation_engine.validate(
            data=payload,
            rule_sets=[TERMS_RULE_SET],
            target_type="subcontract_deductions",
            target_id=str(payment_application_id or agreement.id),
            project_id=str(agreement.project_id),
            metadata={"locale": get_locale(), "operation": "read"},
        )
        return {
            **statement,
            "agreement_id": agreement.id,
            "payment_application_id": payment_application_id,
            "application_number": pa.application_number if pa is not None else None,
            "currency": agreement.currency or "",
            "contract_sum": contract_sum,
            "validation": _rows(report),
        }

    async def record_deductions(self, agreement_id: uuid.UUID, payment_application_id: uuid.UUID) -> dict[str, Any]:
        """Freeze the statement on the payment application, so later term edits do not rewrite it."""
        statement = await self.deduction_statement(agreement_id, payment_application_id=payment_application_id)
        pa = await self.session.get(PaymentApplication, payment_application_id)
        if pa is None:
            raise _not_found()
        meta = dict(pa.metadata_ or {})
        meta["deductions"] = {
            **_str_money({k: v for k, v in statement.items() if k != "validation"}),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        pa.metadata_ = meta
        await self.session.flush()
        return statement

    # ── Bidder search ────────────────────────────────────────────────────

    async def _site(self, project_id: uuid.UUID) -> tuple[Decimal, Decimal] | None:
        try:
            from app.modules.geo_hub.models import GeoAnchor
        except Exception:  # noqa: BLE001 - geo_hub is optional
            return None
        anchor = (
            await self.session.execute(select(GeoAnchor).where(GeoAnchor.project_id == project_id))
        ).scalar_one_or_none()
        if anchor is None or (anchor.lat == 0 and anchor.lon == 0):
            return None
        return (Decimal(anchor.lat), Decimal(anchor.lon))

    async def favourite_ids(self, trade: str | None) -> set[uuid.UUID]:
        stmt = select(SubcontractorFavourite.subcontractor_id)
        if trade:
            stmt = stmt.where(SubcontractorFavourite.trade == trade)
        return set((await self.session.execute(stmt)).scalars().all())

    async def search_bidders(
        self,
        *,
        project_id: uuid.UUID | None,
        trade: str | None,
        radius_km: Decimal | None,
        favourites_only: bool = False,
        include_outside: bool = False,
        search: str | None = None,
    ) -> BidderSearchResponse:
        """Firms for a trade, nearest first, favourites on top; blocked firms are never listed."""
        from app.modules.geo_hub.coord_reconcile import distance_km

        subs = list(
            (
                await self.session.execute(
                    select(Subcontractor)
                    .where(Subcontractor.is_active.is_(True))
                    .order_by(Subcontractor.legal_name)
                    .limit(_SEARCH_CAP)
                )
            )
            .scalars()
            .all()
        )
        hidden_blocked = sum(1 for s in subs if s.is_blocked)
        subs = [s for s in subs if not s.is_blocked]
        if trade:
            subs = [s for s in subs if trade in (s.trade_categories or [])]
        if search:
            needle = search.strip().lower()
            subs = [
                s
                for s in subs
                if needle in s.legal_name.lower()
                or needle in (s.trade_name or "").lower()
                or any(needle in str(c).lower() for c in s.trade_categories or [])
            ]
        favourites = await self.favourite_ids(trade)
        if favourites_only:
            subs = [s for s in subs if s.id in favourites]
        ids = [s.id for s in subs]
        locations = (
            {
                loc.subcontractor_id: loc
                for loc in (
                    await self.session.execute(select(FirmLocation).where(FirmLocation.subcontractor_id.in_(ids)))
                ).scalars()
            }
            if ids
            else {}
        )
        site = await self._site(project_id) if project_id is not None else None

        rows: list[BidderRow] = []
        outside: list[dict[str, Any]] = []
        for sub in subs:
            loc = locations.get(sub.id)
            distance: Decimal | None = None
            if loc is not None and site is not None:
                distance = Decimal(str(round(distance_km(site, (loc.lat, loc.lon)), 1)))
            within: bool | None = None
            if distance is not None and radius_km is not None:
                within = distance <= radius_km
            if within is False:
                outside.append({"id": str(sub.id), "name": sub.legal_name, "distance_km": str(distance)})
                if not include_outside:
                    continue
            address = sub.address if isinstance(sub.address, dict) else {}
            rows.append(
                BidderRow(
                    id=sub.id,
                    legal_name=sub.legal_name,
                    trade_name=sub.trade_name,
                    trade_categories=list(sub.trade_categories or []),
                    prequalification_status=sub.prequalification_status,
                    city=(address.get("city") or None),
                    has_coordinates=loc is not None,
                    distance_km=distance,
                    within_radius=within,
                    is_favourite=sub.id in favourites,
                )
            )
        rows.sort(
            key=lambda r: (
                not r.is_favourite,
                r.distance_km is None,
                r.distance_km if r.distance_km is not None else Decimal("0"),
                r.legal_name.lower(),
            )
        )
        validation: list[ValidationRow] = []
        if include_outside and outside and radius_km is not None:
            report = await validation_engine.validate(
                data={"radius_km": str(radius_km), "recipients": outside},
                rule_sets=[BIDDER_RULE_SET],
                target_type="bidder_search",
                target_id=str(project_id or ""),
                project_id=str(project_id) if project_id else None,
                metadata={"locale": get_locale(), "operation": "read"},
            )
            validation = [row for row in _rows(report) if not row.passed]
        return BidderSearchResponse(
            items=rows,
            total=len(rows),
            radius_km=radius_km,
            site_has_coordinates=site is not None,
            without_coordinates=sum(1 for r in rows if not r.has_coordinates),
            hidden_blocked=hidden_blocked,
            validation=validation,
        )

    # ── Firm location ────────────────────────────────────────────────────

    async def _sub(self, sub_id: uuid.UUID) -> Subcontractor:
        sub = await self.session.get(Subcontractor, sub_id)
        if sub is None:
            raise _not_found()
        return sub

    @staticmethod
    def _location_out(sub_id: uuid.UUID, loc: FirmLocation | None, reason: str | None = None) -> FirmLocationResponse:
        if loc is None:
            return FirmLocationResponse(subcontractor_id=sub_id, has_coordinates=False, reason=reason)
        return FirmLocationResponse(
            subcontractor_id=sub_id,
            has_coordinates=True,
            lat=loc.lat,
            lon=loc.lon,
            source=loc.source,
            precision=loc.precision,
            located_at=loc.located_at,
        )

    async def _location(self, sub_id: uuid.UUID) -> FirmLocation | None:
        return (
            await self.session.execute(select(FirmLocation).where(FirmLocation.subcontractor_id == sub_id))
        ).scalar_one_or_none()

    async def get_location(self, sub_id: uuid.UUID) -> FirmLocationResponse:
        await self._sub(sub_id)
        return self._location_out(sub_id, await self._location(sub_id), reason="not_located")

    async def set_location(
        self,
        sub_id: uuid.UUID,
        lat: Decimal,
        lon: Decimal,
        *,
        source: str = "manual",
        precision: str | None = None,
        address_text: str | None = None,
    ) -> FirmLocationResponse:
        await self._sub(sub_id)
        loc = await self._location(sub_id)
        if loc is None:
            loc = FirmLocation(subcontractor_id=sub_id, lat=lat, lon=lon)
            self.session.add(loc)
        loc.lat, loc.lon, loc.source, loc.precision = lat, lon, source, precision
        loc.address_text = (address_text or None) and address_text[:500]
        loc.located_at = datetime.now(UTC)
        await self.session.flush()
        return self._location_out(sub_id, loc)

    async def clear_location(self, sub_id: uuid.UUID) -> None:
        await self.session.execute(delete(FirmLocation).where(FirmLocation.subcontractor_id == sub_id))
        await self.session.flush()

    async def geocode(self, sub_id: uuid.UUID) -> FirmLocationResponse:
        """Locate a firm from its address through geo_hub; say why when it cannot."""
        from app.modules.geo_hub.geocoder import geocode_address, project_address_from_jsonb

        sub = await self._sub(sub_id)
        raw = dict(sub.address) if isinstance(sub.address, dict) else {}
        if not raw.get("country") and sub.country:
            raw["country"] = sub.country
        address = project_address_from_jsonb(raw)
        if address is None or not (address.city or address.postal_code or address.street):
            return self._location_out(sub_id, await self._location(sub_id), reason="no_address")
        try:
            result = await geocode_address(address, session=self.session)
        except Exception:  # noqa: BLE001 - offline or blocked: report, never fail the request
            logger.info("subcontractor geocode failed for %s", sub_id, exc_info=True)
            result = None
        if result is None:
            return self._location_out(sub_id, await self._location(sub_id), reason="geocoder_unavailable")
        return await self.set_location(
            sub_id,
            result.lat,
            result.lon,
            source="geocoder",
            precision=str(result.precision),
            address_text=result.display_name,
        )

    # ── Favourites ───────────────────────────────────────────────────────

    async def list_favourites(self, trade: str | None = None) -> list[SubcontractorFavourite]:
        stmt = select(SubcontractorFavourite).order_by(SubcontractorFavourite.trade)
        if trade:
            stmt = stmt.where(SubcontractorFavourite.trade == trade)
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_favourite(self, sub_id: uuid.UUID, trade: str, user_id: str | None) -> None:
        await self._sub(sub_id)
        exists = (
            await self.session.execute(
                select(SubcontractorFavourite).where(
                    SubcontractorFavourite.subcontractor_id == sub_id, SubcontractorFavourite.trade == trade
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            self.session.add(SubcontractorFavourite(subcontractor_id=sub_id, trade=trade, created_by=user_id))
            await self.session.flush()

    async def remove_favourite(self, sub_id: uuid.UUID, trade: str) -> None:
        await self.session.execute(
            delete(SubcontractorFavourite).where(
                SubcontractorFavourite.subcontractor_id == sub_id, SubcontractorFavourite.trade == trade
            )
        )
        await self.session.flush()


__all__ = [
    "BIDDER_RULE_SET",
    "PACK_LEVY_FILE",
    "TERMS_RULE_SET",
    "SubcontractTermsService",
    "pack_levy_defaults",
    "set_subcontract_terms",
    "terms_to_calc",
]
