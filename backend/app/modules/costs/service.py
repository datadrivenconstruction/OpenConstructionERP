# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost item service - business logic for cost database management.

Stateless service layer. Handles:
- Cost item CRUD
- Search with filters
- Bulk import
- BIM-element cost suggestions
- Event publishing for cost changes
"""

from __future__ import annotations

import base64
import binascii
import json as _json
import logging
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.costs.models import CostCatalog, CostItem
from app.modules.costs.region_currency import REGION_CURRENCY
from app.modules.costs.repository import CostItemRepository
from app.modules.costs.schemas import (
    CostCatalogCreate,
    CostCatalogUpdate,
    CostItemCreate,
    CostItemUpdate,
    CostSearchQuery,
    CostSuggestion,
)

logger = logging.getLogger(__name__)


def _currency_for_region(currency: str | None, region: str | None) -> str:
    """Return the currency a cost item should be stored with.

    A price without a currency is not a price, so no write path may leave the
    column empty while the row itself says which money it is in. The region tag
    is that statement: a CWICR catalogue is imported per region and every rate
    in it is denominated in that region's local currency, which is why
    :data:`REGION_CURRENCY` is keyed by region and why the importer resolves it
    once per import.

    The service layer did not, and rows created through ``POST /v1/costs/`` and
    the bulk import carried whatever the caller sent - an empty string by
    schema default. An item inside a catalog inherited the catalog currency and
    an item outside one inherited nothing.

    Precedence, and why:

    * A currency the caller supplied always wins. It is the most specific
      statement about the row and may legitimately differ from the region's
      (a Swiss firm quoting a German catalogue in CHF).
    * Then the owning catalog's currency, applied by the caller before this
      helper runs. A catalog is a container with a REQUIRED currency, so it is
      a stronger signal than the region of a single row inside it.
    * Then the region.
    * Then empty, unchanged. An unrecognised region is left blank on purpose -
      see :mod:`app.modules.costs.region_currency`. Stamping a default here
      would turn "we do not know" into a wrong answer that reads exactly like a
      right one.
    """
    if isinstance(currency, str) and currency.strip():
        # Returned verbatim rather than normalised: filling a blank is this
        # helper's job, rewriting a value the caller chose is not.
        return currency
    if isinstance(region, str) and region.strip():
        return REGION_CURRENCY.get(region.strip().upper(), "")
    return ""


# ── Keyset cursor codec ────────────────────────────────────────────────────
#
# Cursors are opaque to the client. We encode the (code, id) pair as a
# base64-encoded JSON object. Base64 is URL-safe (no padding hassles when
# the cursor flows back as a query parameter) and JSON keeps the payload
# self-describing for debugging. The codec is intentionally tolerant:
# any decode error returns ``None`` so the router can map it to a 400
# without leaking parser internals to the caller.


def encode_cursor(code: str, item_id: str) -> str:
    """Pack ``(code, id)`` into a URL-safe base64 cursor token."""
    payload = _json.dumps({"code": code, "id": item_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(token: str) -> tuple[str, str] | None:
    """Decode a cursor back to ``(code, id)``.

    Returns ``None`` for any malformed input - empty / wrong base64 /
    non-JSON / missing keys - so callers can map the failure to a 400
    without distinguishing the underlying cause.
    """
    if not token or not isinstance(token, str):
        return None
    try:
        # urlsafe_b64decode is strict about padding; pad on the fly so a
        # cursor that round-tripped through a URL without padding still
        # decodes.
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    try:
        data = _json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    code = data.get("code")
    item_id = data.get("id")
    if not isinstance(code, str) or not isinstance(item_id, str):
        return None
    return code, item_id


# ── Mass-based pricing conversion ──────────────────────────────────────────
#
# A structural-steel section is priced by mass: its linear mass (kg per one
# length unit) times the length gives a mass, and the rate is quoted per tonne
# or per kg. This pure helper converts a mass-basis rate into the effective
# rate per ONE length unit, so a normal length-based BOQ line (quantity x
# unit_rate) lands on the correct total without a second unit system.
#
#     effective_rate_per_unit = mass_per_unit * rate / (1000 if basis == "t" else 1)
#
# Worked example (the customer's "360UB"): a 360 mm Universal Beam at
# 44.7 kg/m priced at 1850 per tonne ->
#     44.7 * 1850 / 1000 = 82.695 per metre.
# Applied to a 12 m member: 12 * 82.695 = 992.34 (i.e. 12 m * 44.7 kg/m =
# 536.4 kg = 0.5364 t * 1850 = 992.34). Money stays Decimal throughout.

_TONNE_KG = Decimal("1000")


def mass_effective_unit_rate(
    rate: str | Decimal | float | None,
    mass_per_unit: str | Decimal | float | None,
    mass_basis: str | None,
) -> Decimal | None:
    """Effective rate per ONE length unit for a mass-priced section.

    Returns ``None`` when the item is not mass-priced (``mass_basis`` is not
    ``"t"`` / ``"kg"``, or ``mass_per_unit`` is missing / not a positive
    finite number) so the caller falls back to the plain catalog ``rate``.
    A non-finite or negative ``rate`` also yields ``None`` - never a poisoned
    figure.
    """
    basis = (mass_basis or "").strip().lower()
    if basis not in ("t", "kg"):
        return None
    try:
        mpu = Decimal(str(mass_per_unit).strip()) if mass_per_unit not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None
    if mpu is None or not mpu.is_finite() or mpu <= 0:
        return None
    try:
        rate_dec = Decimal(str(rate).strip()) if rate not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError):
        return None
    if not rate_dec.is_finite() or rate_dec < 0:
        return None
    effective = mpu * rate_dec
    if basis == "t":
        effective = effective / _TONNE_KG
    if not effective.is_finite() or effective < 0:
        return None
    return effective


# ── Rate freshness by price date (re-price-due flag) ───────────────────────
#
# The certainty badge grades a rate by how OFTEN and how RECENTLY it has been
# APPLIED (the usage ledger). That misses a distinct risk: a rate can be
# applied every week yet still carry a unit price that was last set years ago.
# Price freshness closes that gap. Each cost item / resource base-price can
# record a ``price_as_of`` date - the day its price was last set or verified -
# and these pure helpers grade that date against a configurable staleness
# horizon, independently of usage frequency:
#
#   * green  - the price date is comfortably within the horizon (fresh).
#   * yellow - the price date is approaching the horizon (verify soon).
#   * red    - the price date has passed the horizon: RE-PRICE DUE.
#   * None   - no price date on record: no opinion, so the usage badge stands
#     and the millions of imported rows without a price date are unaffected.
#
# When a rate is re-price-due the one-click fix offers an ESCALATED value: the
# recorded price carried forward to today by an annual escalation rate
# (compounded per full year, then pro-rated linearly across the trailing
# partial year). Everything stays Decimal end to end; the horizon, the warning
# lead and the escalation rate are all overridable so a tenant can tune them.

# Default: a unit price older than one year is due for re-pricing. Aligned
# with ``intelligence.CERTAINTY_GREEN_MAX_AGE_DAYS`` so the two freshness
# signals agree on what "a year" means.
PRICE_STALENESS_HORIZON_DAYS = 365
# Start nudging (yellow) once the price date has aged past this fraction of the
# horizon - three quarters of the way, by default.
PRICE_STALENESS_WARN_FRACTION = 0.75
# Default annual construction-cost escalation applied by the one-click fix. A
# plain, conservative figure; a real per-region index can override it.
PRICE_DEFAULT_ANNUAL_ESCALATION_PCT = Decimal("3.0")
# Guard against a pathological price date (e.g. a year-1000 typo) blowing up
# the compounding exponent; no real price is older than this many years.
_MAX_ESCALATION_YEARS = 200

PriceFreshnessBand = Literal["green", "yellow", "red"]


def _coerce_price_date(value: date | str | None) -> date | None:
    """Parse a ``price_as_of`` value into a plain ``date``.

    Accepts a ``date`` as-is, a ``datetime`` (its date part is taken), an ISO
    ``YYYY-MM-DD`` string (the JSON wire form), or ``None`` / blank. Any
    unparseable value yields ``None`` so a junk date never poisons the age
    math - it simply reads as "no date on record".

    Args:
        value: The stored / supplied price date in any accepted form.

    Returns:
        A ``date``, or ``None`` when nothing usable was given.
    """
    if value is None or value == "":
        return None
    # ``datetime`` is a subclass of ``date`` - check it first to take the day.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None


def _resolve_today(today: date | None) -> date:
    """Return ``today`` when given, else the current UTC date."""
    return today if today is not None else datetime.now(UTC).date()


def _positive_decimal(value: str | Decimal | float | None) -> Decimal | None:
    """Parse ``value`` into a strictly-positive finite ``Decimal``, else ``None``."""
    if value is None or value == "":
        return None
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not dec.is_finite() or dec <= 0:
        return None
    return dec


def price_age_days(price_as_of: date | str | None, *, today: date | None = None) -> int | None:
    """Age of a recorded price in whole days, or ``None`` when no date is set.

    Args:
        price_as_of: The day the price was last set / verified.
        today: Reference day; defaults to the current UTC date. Pass it
            explicitly to keep tests deterministic.

    Returns:
        Whole days elapsed since ``price_as_of`` (a future date clamps to
        ``0``, never negative), or ``None`` when no price date is on record.
    """
    as_of = _coerce_price_date(price_as_of)
    if as_of is None:
        return None
    delta = (_resolve_today(today) - as_of).days
    return delta if delta > 0 else 0


def is_reprice_due(
    price_as_of: date | str | None,
    *,
    horizon_days: int = PRICE_STALENESS_HORIZON_DAYS,
    today: date | None = None,
) -> bool:
    """Whether a recorded price date has aged past ``horizon_days``.

    Independent of usage frequency by design: a heavily-used but long-unpriced
    rate is still due. Returns ``False`` when there is no price date (we do not
    invent staleness we cannot prove) or the horizon is non-positive (the
    check is effectively switched off).

    Args:
        price_as_of: The day the price was last set / verified.
        horizon_days: Age at or beyond which the price is due for re-pricing.
        today: Reference day; defaults to the current UTC date.

    Returns:
        ``True`` when the price is due for re-pricing, else ``False``.
    """
    if horizon_days <= 0:
        return False
    age = price_age_days(price_as_of, today=today)
    return age is not None and age >= horizon_days


def classify_price_freshness(
    price_as_of: date | str | None,
    *,
    horizon_days: int = PRICE_STALENESS_HORIZON_DAYS,
    warn_fraction: float = PRICE_STALENESS_WARN_FRACTION,
    today: date | None = None,
) -> PriceFreshnessBand | None:
    """Grade a price date green / yellow / red, or ``None`` when unknown.

    Reuses the same three-colour vocabulary as the usage certainty badge so
    the UI can render one shared traffic-light control:

    * ``None``     - no price date on record: no opinion.
    * ``"red"``    - aged at/past ``horizon_days``: re-price due.
    * ``"yellow"`` - aged past ``warn_fraction`` of the horizon: verify soon.
    * ``"green"``  - comfortably within the horizon.

    Args:
        price_as_of: The day the price was last set / verified.
        horizon_days: Re-price-due horizon in days.
        warn_fraction: Fraction of the horizon (clamped to ``[0, 1]``) at
            which the band steps up to yellow.
        today: Reference day; defaults to the current UTC date.

    Returns:
        The freshness band, or ``None`` when no price date is on record or the
        horizon is non-positive.
    """
    age = price_age_days(price_as_of, today=today)
    if age is None or horizon_days <= 0:
        return None
    if age >= horizon_days:
        return "red"
    frac = min(max(warn_fraction, 0.0), 1.0)
    if age >= int(horizon_days * frac):
        return "yellow"
    return "green"


def escalated_reprice_value(
    rate: str | Decimal | float | None,
    price_as_of: date | str | None,
    *,
    annual_pct: Decimal | float | str = PRICE_DEFAULT_ANNUAL_ESCALATION_PCT,
    today: date | None = None,
) -> Decimal | None:
    """The current price escalated forward from ``price_as_of`` to today.

    The re-price-due one-click fix: take the recorded ``rate`` and carry it
    forward by ``annual_pct`` per year - compounded for each full year, then
    pro-rated linearly across the trailing partial year - so an estimator can
    accept a defensible refreshed rate in a single click. All-Decimal; the
    result is quantised to four places (matching the usage ledger's
    ``Numeric(18, 4)`` and the regional-adjust output).

    Args:
        rate: The price to escalate.
        price_as_of: The day the price was last set / verified.
        annual_pct: Annual escalation as a percent (e.g. ``3.0`` for 3 %/yr).
        today: Reference day; defaults to the current UTC date.

    Returns:
        The escalated Decimal value, or ``None`` when there is nothing to
        escalate: no price date, a non-positive age (price set today or in the
        future), a missing / invalid / non-positive rate, or a non-finite
        escalation rate.
    """
    age = price_age_days(price_as_of, today=today)
    if age is None or age <= 0:
        return None
    rate_dec = _positive_decimal(rate)
    if rate_dec is None:
        return None
    try:
        r = Decimal(str(annual_pct).strip()) / Decimal("100")
    except (InvalidOperation, ValueError):
        return None
    if not r.is_finite():
        return None

    one_plus_r = Decimal("1") + r
    if one_plus_r < 0:
        # A cut so deep the compounding base goes negative is not meaningful;
        # floor it at zero rather than emit an oscillating figure.
        one_plus_r = Decimal("0")

    full_years = min(age // 365, _MAX_ESCALATION_YEARS)
    remainder_days = age % 365
    # Integer-exponent power is exact under the Decimal context; no float.
    factor = one_plus_r**full_years
    if remainder_days > 0:
        partial = Decimal(remainder_days) / Decimal("365")
        factor *= Decimal("1") + r * partial

    escalated = rate_dec * factor
    if not escalated.is_finite() or escalated < 0:
        return None
    return escalated.quantize(Decimal("0.0001"))


def price_freshness(
    price_as_of: date | str | None,
    rate: str | Decimal | float | None = None,
    *,
    horizon_days: int = PRICE_STALENESS_HORIZON_DAYS,
    warn_fraction: float = PRICE_STALENESS_WARN_FRACTION,
    annual_pct: Decimal | float | str = PRICE_DEFAULT_ANNUAL_ESCALATION_PCT,
    today: date | None = None,
) -> dict[str, Any]:
    """One-stop price-date freshness read for the certainty response.

    Bundles everything a caller needs to surface the re-price-due state next
    to a cost item or resource base-price, so wiring it into the existing
    certainty badge is a single merge. The returned dict carries:

    * ``price_as_of`` (``date | None``) - the recorded date, echoed back.
    * ``price_age_days`` (``int | None``) - whole days, ``None`` when no date.
    * ``reprice_due`` (``bool``) - aged at/past the horizon.
    * ``price_freshness_band`` (``str | None``) - green / yellow / red, or
      ``None`` when there is no price date. Namespaced so it never collides
      with the usage badge's ``confidence_badge`` when the two are merged.
    * ``staleness_horizon_days`` (``int``) - the horizon in force.
    * ``suggested_reprice_value`` (``Decimal | None``) - the escalated
      one-click fix. Populated only when the item is ``reprice_due`` and there
      is a valid positive rate to escalate, so the "offer" is tied to the flag
      and never shown for a fresh price.

    ``reprice_due`` and the band are computed purely from the date and the
    horizon, never from usage frequency, so a heavily-used but long-unpriced
    rate is still flagged.

    Args:
        price_as_of: The day the price was last set / verified.
        rate: The current price, used to compute the escalated fix.
        horizon_days: Re-price-due horizon in days.
        warn_fraction: Fraction of the horizon at which the band turns yellow.
        annual_pct: Annual escalation percent for the one-click fix.
        today: Reference day; defaults to the current UTC date.

    Returns:
        A JSON-friendly dict as described above.
    """
    as_of = _coerce_price_date(price_as_of)
    due = is_reprice_due(as_of, horizon_days=horizon_days, today=today)
    suggested = escalated_reprice_value(rate, as_of, annual_pct=annual_pct, today=today) if due else None
    return {
        "price_as_of": as_of,
        "price_age_days": price_age_days(as_of, today=today),
        "reprice_due": due,
        "price_freshness_band": classify_price_freshness(
            as_of,
            horizon_days=horizon_days,
            warn_fraction=warn_fraction,
            today=today,
        ),
        "staleness_horizon_days": horizon_days,
        "suggested_reprice_value": suggested,
    }


# ── Fuzzy-branch offset cursor ─────────────────────────────────────────────
#
# The fuzzy (trigram-ranked) search path orders rows by a computed relevance
# score, so the (code, id) keyset cursor above does not apply - there is no
# monotonic column pair to resume after. That branch paginates by OFFSET/LIMIT
# and packs the next offset into the SAME opaque cursor channel, so cursor-based
# clients (e.g. the BOQ "Add from Database" infinite scroll) keep working
# without knowing which ranking mode produced the page. The tradeoff vs a true
# keyset cursor is the standard OFFSET one: a concurrent insert or delete can
# shift a row across a page boundary. That is acceptable for a relevance-ranked
# search where the top matches (page 1) are what matter most.


def encode_offset_cursor(offset: int) -> str:
    """Pack a fuzzy-branch OFFSET into a URL-safe base64 cursor token."""
    payload = _json.dumps({"o": int(offset)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_offset_cursor(token: str) -> int | None:
    """Decode a fuzzy-branch offset cursor back to its integer offset.

    Returns ``None`` for any malformed input or a token that is not an offset
    cursor (e.g. a stale keyset ``(code, id)`` cursor from a non-fuzzy request),
    so the caller can map the failure to a 400 and let the client restart from
    the first page.
    """
    if not token or not isinstance(token, str):
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    try:
        data = _json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    offset = data.get("o")
    # ``bool`` is a subclass of ``int``; reject it so a stray ``true`` is not
    # read as offset 1.
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return None
    return offset


class CostItemService:
    """Business logic for cost item operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CostItemRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_cost_item(self, data: CostItemCreate) -> CostItem:
        """Create a new cost item.

        Raises HTTPException 409 if code already exists, 422 when an
        unknown ``catalog_id`` is referenced. An item created into a
        catalog without its own currency inherits the catalog currency.
        """
        existing = await self.repo.get_by_code(data.code, region=data.region)
        if existing is not None:
            region_label = data.region or "global"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cost item with code '{data.code}' already exists for region '{region_label}'",
            )

        currency = data.currency
        if data.catalog_id is not None:
            catalog = await self.session.get(CostCatalog, data.catalog_id)
            if catalog is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Cost catalog '{data.catalog_id}' does not exist",
                )
            if not currency.strip():
                currency = catalog.currency
        currency = _currency_for_region(currency, data.region)

        item = CostItem(
            code=data.code,
            description=data.description,
            descriptions=data.descriptions,
            unit=data.unit,
            rate=str(data.rate),
            currency=currency,
            source=data.source,
            classification=data.classification,
            components=data.components,
            tags=data.tags,
            region=data.region,
            mass_per_unit=data.mass_per_unit,
            mass_basis=data.mass_basis,
            catalog_id=data.catalog_id,
            metadata_=data.metadata,
        )
        item = await self.repo.create(item)

        await _safe_publish(
            "costs.item.created",
            {"item_id": str(item.id), "code": item.code},
            source_module="oe_costs",
        )

        logger.info("Cost item created: %s (%s)", item.code, item.unit)
        return item

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_cost_item(self, item_id: uuid.UUID) -> CostItem:
        """Get cost item by ID. Raises 404 if not found."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )
        return item

    async def get_by_codes(self, codes: list[str]) -> list[CostItem]:
        """Get multiple cost items by their codes."""
        return await self.repo.get_by_codes(codes)

    async def mass_apply_preview(self, item_id: uuid.UUID, quantity: Decimal) -> dict[str, Any]:
        """Preview applying a (possibly mass-priced) cost item to a length quantity.

        For a mass-priced section (``mass_basis`` ``t`` / ``kg`` with a
        positive ``mass_per_unit``), returns the effective per-unit rate
        (``mass_per_unit * rate / 1000`` for tonnes), the derived total mass,
        and the line total for ``quantity`` units - all as Decimal-strings so
        a JS client never rounds through float. For a non-mass item it falls
        back to the plain catalog rate, so the same endpoint is safe to call
        for any item. Raises 404 when the item does not exist.
        """
        item = await self.get_cost_item(item_id)

        try:
            qty = quantity if isinstance(quantity, Decimal) else Decimal(str(quantity))
        except (InvalidOperation, ValueError):
            qty = Decimal("0")
        if not qty.is_finite() or qty < 0:
            qty = Decimal("0")

        try:
            base_rate = Decimal(str(item.rate))
        except (InvalidOperation, ValueError):
            base_rate = Decimal("0")
        if not base_rate.is_finite() or base_rate < 0:
            base_rate = Decimal("0")

        effective = mass_effective_unit_rate(item.rate, item.mass_per_unit, item.mass_basis)
        mass_priced = effective is not None
        unit_rate = effective if effective is not None else base_rate

        # Total mass only makes sense for a mass-priced section.
        total_mass_kg: Decimal | None = None
        if mass_priced:
            try:
                mpu = Decimal(str(item.mass_per_unit))
            except (InvalidOperation, ValueError):
                mpu = Decimal("0")
            total_mass_kg = qty * mpu

        line_total = qty * unit_rate

        return {
            "cost_item_id": str(item.id),
            "code": item.code,
            "unit": item.unit,
            "quantity": qty,
            "mass_priced": mass_priced,
            "mass_basis": item.mass_basis or "",
            "mass_per_unit": item.mass_per_unit or "",
            "base_rate": base_rate,
            "effective_unit_rate": unit_rate,
            "total_mass_kg": total_mass_kg,
            "total_mass_t": (total_mass_kg / _TONNE_KG) if total_mass_kg is not None else None,
            "line_total": line_total,
            "currency": item.currency or "",
        }

    async def search_for_autocomplete(
        self,
        *,
        q: str,
        region: str | None = None,
        limit: int = 8,
    ) -> list[CostItem]:
        """Autocomplete-tuned search delegating to the repository.

        See :meth:`CostItemRepository.search_for_autocomplete` - pushes
        the "items WITH components first" priority into the SQL
        ORDER BY so the router never has to over-fetch + re-sort.
        """
        return await self.repo.search_for_autocomplete(
            q=q,
            region=region,
            limit=limit,
        )

    async def search_costs(self, query: CostSearchQuery) -> tuple[list[CostItem], int]:
        """Search cost items with filters and pagination (legacy offset path).

        This wrapper preserves the older 2-tuple return shape used by the
        autocomplete endpoint and external callers that don't care about
        cursor pagination. The new keyset-aware search lives in
        :meth:`search_costs_paginated`.
        """
        items, total, _ = await self.repo.search(
            q=query.q,
            name=query.name,
            description=query.description,
            unit=query.unit,
            source=query.source,
            region=query.region,
            category=query.category,
            classification_path=query.classification_path,
            catalog_id=query.catalog_id,
            min_rate=query.min_rate,
            max_rate=query.max_rate,
            offset=query.offset,
            limit=query.limit,
            cursor=None,
            skip_count=False,
            fuzzy=query.fuzzy,
        )
        # ``total`` is guaranteed non-None here because skip_count=False.
        assert total is not None
        return items, total

    async def search_costs_paginated(
        self,
        query: CostSearchQuery,
        *,
        skip_count: bool = False,
    ) -> tuple[list[CostItem], int | None, bool, str | None]:
        """Search with cursor-aware pagination.

        Returns ``(items, total_or_None, has_more, next_cursor_or_None)``.
        ``total`` is computed only when no cursor was supplied (first page)
        and the caller did NOT pass ``skip_count=True``.
        ``next_cursor`` is the encoded cursor for the next page, or ``None``
        when there is no next page.

        ``skip_count`` exists for the case where the caller already knows
        the total from another aggregate (e.g. the prewarmed
        ``_region_cache["stats"]`` totals) and wants to skip the COUNT(*)
        on the first page. Cursor-paginated requests still skip count
        automatically - this flag is for first-page no-filter fast paths.
        """
        # Fuzzy (trigram-ranked) branch: relevance ordering cannot use the
        # (code, id) keyset cursor, so it paginates by OFFSET and encodes the
        # next offset into the cursor channel (see encode_offset_cursor). Only
        # taken when the query opted into fuzzy AND pg_trgm is available on the
        # bound PostgreSQL database; otherwise we fall through to the keyset
        # path below unchanged.
        if await self.repo.fuzzy_search_enabled(query.q, query.fuzzy):
            return await self._search_fuzzy_paginated(query, skip_count=skip_count)

        decoded_cursor: tuple[str, str] | None = None
        if query.cursor:
            decoded_cursor = decode_cursor(query.cursor)
            if decoded_cursor is None:
                # Malformed cursor → 400. The frontend treats this as a
                # signal to drop the bookmark and refetch the first page.
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid pagination cursor",
                )

        items, total, has_more = await self.repo.search(
            q=query.q,
            fuzzy=query.fuzzy,
            name=query.name,
            description=query.description,
            unit=query.unit,
            source=query.source,
            region=query.region,
            category=query.category,
            classification_path=query.classification_path,
            catalog_id=query.catalog_id,
            min_rate=query.min_rate,
            max_rate=query.max_rate,
            offset=query.offset,
            limit=query.limit,
            cursor=decoded_cursor,
            skip_count=skip_count or decoded_cursor is not None,
        )

        next_cursor: str | None = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(last.code, str(last.id))

        return items, total, has_more, next_cursor

    async def _search_fuzzy_paginated(
        self,
        query: CostSearchQuery,
        *,
        skip_count: bool,
    ) -> tuple[list[CostItem], int | None, bool, str | None]:
        """OFFSET-paginated fuzzy search returning the same 4-tuple shape.

        Rows are ranked by trigram relevance (exact, then prefix, then
        similarity) in the repository. Pagination is by OFFSET/LIMIT because the
        relevance ordering has no monotonic keyset to resume after; the offset
        is carried in the opaque cursor token so cursor-based clients keep
        paging. An incoming cursor, when present, is a fuzzy offset cursor from a
        previous page; a malformed or wrong-mode cursor yields a 400 so the
        client drops the bookmark and refetches from the first page, matching the
        keyset path's contract. ``total`` is computed on the first page (no
        cursor) and omitted afterwards, exactly like the keyset branch.
        """
        page_offset = query.offset
        if query.cursor:
            decoded = decode_offset_cursor(query.cursor)
            if decoded is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid pagination cursor",
                )
            page_offset = decoded

        items, total, has_more = await self.repo.search(
            q=query.q,
            name=query.name,
            description=query.description,
            unit=query.unit,
            source=query.source,
            region=query.region,
            category=query.category,
            classification_path=query.classification_path,
            catalog_id=query.catalog_id,
            min_rate=query.min_rate,
            max_rate=query.max_rate,
            offset=page_offset,
            limit=query.limit,
            cursor=None,
            skip_count=skip_count or bool(query.cursor),
            fuzzy=True,
        )

        next_cursor = encode_offset_cursor(page_offset + query.limit) if has_more else None
        return items, total, has_more, next_cursor

    async def category_tree(
        self,
        region: str | None = None,
        depth: int = 4,
        parent_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the classification tree, optionally filtered by region.

        ``depth`` (1..4) limits how many classification levels to return -
        callers asking for a fast first paint pass ``depth=2`` and lazily
        drill deeper with ``parent_path``. Caching is the router's job
        (``_category_tree_cache``) - keep this layer stateless so
        background callers (e.g. event handlers) don't share a stale
        snapshot with HTTP clients.
        """
        return await self.repo.category_tree(region=region, depth=depth, parent_path=parent_path)

    # ── Update ────────────────────────────────────────────────────────────

    async def update_cost_item(self, item_id: uuid.UUID, data: CostItemUpdate) -> CostItem:
        """Update a cost item. Raises 404 if not found, 409 on code conflict."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert rate float → string for storage
        if "rate" in fields and fields["rate"] is not None:
            fields["rate"] = str(fields["rate"])

        # Merge (not overwrite) metadata_ so a partial PATCH that sends only a
        # few keys keeps the rest. CWICR import populates labor/material/
        # equipment costs, variants and scope_of_work here; a wholesale assign
        # would silently drop every key the caller did not resend.
        if "metadata" in fields:
            fields["metadata_"] = merge_metadata(item.metadata_, fields.pop("metadata"))

        # Check code uniqueness if code or region is being changed
        new_code = fields.get("code", item.code)
        new_region = fields.get("region", item.region)
        if new_code != item.code or new_region != item.region:
            existing = await self.repo.get_by_code(new_code, region=new_region)
            if existing is not None and existing.id != item_id:
                region_label = new_region or "global"
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cost item with code '{new_code}' already exists for region '{region_label}'",
                )

        if fields:
            await self.repo.update_fields(item_id, **fields)

        updated = await self.repo.get_by_id(item_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        await _safe_publish(
            "costs.item.updated",
            {"item_id": str(item_id), "code": updated.code, "fields": list(fields.keys())},
            source_module="oe_costs",
        )

        logger.info("Cost item updated: %s", updated.code)
        return updated

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_cost_item(self, item_id: uuid.UUID) -> None:
        """Soft-delete a cost item (set is_active=False). Raises 404 if not found."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        # Save the code before the deactivating write below
        item_code = item.code

        await self.repo.update_fields(item_id, is_active=False)

        await _safe_publish(
            "costs.item.deleted",
            {"item_id": str(item_id), "code": item_code},
            source_module="oe_costs",
        )

        logger.info("Cost item deleted (soft): %s", item_code)

    # ── Bulk import ───────────────────────────────────────────────────────

    async def bulk_import(self, items_data: list[CostItemCreate]) -> list[CostItem]:
        """Bulk import cost items. Skips items with duplicate codes.

        Returns the list of successfully created items.
        """
        created: list[CostItem] = []
        skipped_codes: list[str] = []
        # Track (code, region) pairs already queued in this batch so an
        # intra-payload duplicate skips the same way a DB duplicate does.
        # Without this the second occurrence also passes the DB existence
        # check, both rows reach bulk_create, and the flush violates the
        # uq_costs_code_region unique constraint with an uncaught
        # IntegrityError that 500s the whole import.
        seen: set[tuple[str, str | None]] = set()

        # Items created into a catalog without their own currency inherit
        # the catalog currency (same contract as create_cost_item). Resolve
        # each distinct catalog_id once instead of per row.
        catalog_currencies: dict[uuid.UUID, str] = {}
        pending_catalog_ids = {
            data.catalog_id for data in items_data if data.catalog_id is not None and not data.currency.strip()
        }
        if pending_catalog_ids:
            result = await self.session.execute(
                select(CostCatalog.id, CostCatalog.currency).where(CostCatalog.id.in_(pending_catalog_ids))
            )
            catalog_currencies = {row.id: row.currency for row in result.all()}

        for data in items_data:
            key = (data.code, data.region)
            if key in seen:
                skipped_codes.append(data.code)
                continue

            existing = await self.repo.get_by_code(data.code, region=data.region)
            if existing is not None:
                skipped_codes.append(data.code)
                continue

            seen.add(key)

            currency = data.currency
            if data.catalog_id is not None and not currency.strip():
                currency = catalog_currencies.get(data.catalog_id, currency)
            currency = _currency_for_region(currency, data.region)

            item = CostItem(
                code=data.code,
                description=data.description,
                descriptions=data.descriptions,
                unit=data.unit,
                rate=str(data.rate),
                currency=currency,
                source=data.source,
                classification=data.classification,
                components=data.components,
                tags=data.tags,
                region=data.region,
                mass_per_unit=data.mass_per_unit,
                mass_basis=data.mass_basis,
                catalog_id=data.catalog_id,
                metadata_=data.metadata,
            )
            created.append(item)

        if created:
            created = await self.repo.bulk_create(created)

        payload: dict[str, object] = {
            "created_count": len(created),
            "skipped_count": len(skipped_codes),
            "skipped_codes": skipped_codes[:20],  # Limit for event payload size
        }
        # A price-base import loads one region at a time; when every created row
        # shares a single non-null region, pass it so the Cost Explorer reverse
        # index can rebuild just that region (bounded by the region, and not
        # blocked by the global auto-rebuild size cap the way a whole-catalog
        # pass would be for a second large base).
        created_regions = {item.region for item in created}
        if len(created_regions) == 1:
            only_region = next(iter(created_regions))
            if only_region is not None:
                payload["region"] = only_region
        await _safe_publish("costs.items.bulk_imported", payload, source_module="oe_costs")

        logger.info(
            "Bulk import: %d created, %d skipped (duplicate codes)",
            len(created),
            len(skipped_codes),
        )
        return created

    # ── BIM-element suggestions ───────────────────────────────────────────

    async def suggest_for_bim_element(
        self,
        element_type: str | None,
        name: str | None,
        discipline: str | None,
        properties: dict[str, Any] | None,
        quantities: dict[str, float] | None,
        classification: dict[str, str] | None,
        *,
        limit: int = 5,
        region: str | None = None,
    ) -> list[CostSuggestion]:
        """Return ranked CWICR cost items that best match a BIM element.

        Ranking factors (in priority order):
          1. Classification overlap - same OmniClass / UniFormat / DIN-276 code
          2. Element type keyword match in description (e.g. element_type='Walls'
             matches 'wall', 'wall panel', 'concrete wall')
          3. Material match - ``properties['material']`` vs description
          4. Family/type match - ``name`` vs description
          5. Tag overlap with element discipline / category

        Returns at most ``limit`` results, sorted by score descending.  Each
        result has a ``score`` field 0..1 so the UI can show confidence.

        Implementation notes:
            The DB query uses plain SQLAlchemy ``ilike`` + ``JSON`` column
            access so the same code path works on PostgreSQL AND SQLite.
            We fetch a wider candidate window (``limit * 20`` capped at 200)
            via keyword OR-ILIKE and then rank in Python.  No pgvector / FTS
            required.
        """
        _ = quantities  # Currently unused in ranking; accepted for API symmetry.

        keywords = self._build_keywords(element_type, name, discipline, properties)
        material = self._extract_material(properties)

        # ── Build candidate query ────────────────────────────────────────
        #
        # Strategy: OR across keyword ILIKE on description + code, plus any
        # items whose classification dict contains any of the provided
        # classification codes (we do this in Python post-filter to stay
        # DB-agnostic).
        base = select(CostItem).where(CostItem.is_active.is_(True))
        if region:
            base = base.where(CostItem.region == region)

        conditions: list[Any] = []
        for kw in keywords:
            if len(kw) < 3:
                continue
            pattern = f"%{kw}%"
            conditions.append(CostItem.description.ilike(pattern))
            conditions.append(CostItem.code.ilike(pattern))

        candidate_cap = max(limit * 20, 50)
        if conditions:
            base = base.where(or_(*conditions))
        # If no keywords at all, we still allow classification-only matching
        # but we bound the candidate pool hard.
        stmt = base.limit(candidate_cap)

        result = await self.session.execute(stmt)
        candidates: list[CostItem] = list(result.scalars().all())

        # ── Rank candidates in Python ────────────────────────────────────
        scored: list[tuple[float, list[str], CostItem]] = []
        for item in candidates:
            score, reasons = self._score_candidate(
                item=item,
                element_type=element_type,
                name=name,
                discipline=discipline,
                material=material,
                classification=classification or {},
                keywords=keywords,
            )
            if score > 0:
                scored.append((score, reasons, item))

        # Sort by score descending, then by code for stable output.
        scored.sort(key=lambda t: (-t[0], t[2].code))

        suggestions: list[CostSuggestion] = []
        for score, reasons, item in scored[:limit]:
            try:
                rate_val: float | str = float(item.rate)
            except (ValueError, TypeError):
                rate_val = str(item.rate)
            suggestions.append(
                CostSuggestion(
                    cost_item_id=str(item.id),
                    code=item.code,
                    description=item.description,
                    unit=item.unit,
                    unit_rate=rate_val,
                    classification=dict(item.classification or {}),
                    score=round(min(score, 1.0), 4),
                    match_reasons=reasons,
                )
            )

        logger.debug(
            "suggest_for_bim_element: element_type=%s keywords=%s -> %d candidates, %d returned",
            element_type,
            keywords,
            len(candidates),
            len(suggestions),
        )
        return suggestions

    # ── Helpers for BIM-element suggestions ───────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lower-case word tokenizer, drops words shorter than 3 chars."""
        return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3]

    @classmethod
    def _build_keywords(
        cls,
        element_type: str | None,
        name: str | None,
        discipline: str | None,
        properties: dict[str, Any] | None,
    ) -> list[str]:
        """Collect unique keywords from BIM element attributes."""
        bag: list[str] = []
        for src in (element_type, name, discipline):
            if src:
                bag.extend(cls._tokenize(str(src)))
        if properties:
            material = cls._extract_material(properties)
            if material:
                bag.extend(cls._tokenize(material))
            # Pull other obvious string props that often describe the element.
            for key in ("family", "type", "category", "system"):
                val = properties.get(key) if isinstance(properties, dict) else None
                if isinstance(val, str) and val:
                    bag.extend(cls._tokenize(val))
        # Normalize common Revit plural forms ("walls" -> "wall", etc.).
        normalized: list[str] = []
        for token in bag:
            normalized.append(token)
            if token.endswith("s") and len(token) > 3:
                normalized.append(token[:-1])
        # Deduplicate preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for t in normalized:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    @staticmethod
    def _extract_material(properties: dict[str, Any] | None) -> str | None:
        """Try a handful of common keys where material may live."""
        if not isinstance(properties, dict):
            return None
        for key in ("material", "Material", "structural_material", "StructuralMaterial"):
            val = properties.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    @classmethod
    def _score_candidate(
        cls,
        *,
        item: CostItem,
        element_type: str | None,
        name: str | None,
        discipline: str | None,
        material: str | None,
        classification: dict[str, str],
        keywords: list[str],
    ) -> tuple[float, list[str]]:
        """Compute a relevance score + human-readable reasons for one item.

        Returns a tuple (score, reasons).  Score is an unbounded positive
        float that the caller clamps to [0, 1].  A rough budget:
            classification exact match  -> +0.45
            element_type token in desc  -> +0.25
            material token in desc      -> +0.15
            family/name token in desc   -> +0.10
            discipline/tag overlap      -> +0.05
        """
        reasons: list[str] = []
        score = 0.0

        desc_lower = (item.description or "").lower()
        code_lower = (item.code or "").lower()
        item_class = item.classification or {}
        item_tags = [str(t).lower() for t in (item.tags or [])]

        # 1. Classification overlap ---------------------------------------
        for key, val in classification.items():
            if not isinstance(val, str) or not val:
                continue
            other = item_class.get(key)
            if isinstance(other, str) and other and other == val:
                score += 0.45
                reasons.append(f"{key}={val} exact match")
                break
            # Prefix match (e.g. DIN 276 "330" vs "331") - weaker.
            if isinstance(other, str) and other and (other.startswith(val) or val.startswith(other)):
                score += 0.2
                reasons.append(f"{key}={val} prefix match")
                break

        # 2. Element type keyword in description --------------------------
        if element_type:
            for token in cls._tokenize(str(element_type)):
                norm_tokens = {token}
                if token.endswith("s") and len(token) > 3:
                    norm_tokens.add(token[:-1])
                for t in norm_tokens:
                    if t in desc_lower or t in code_lower:
                        score += 0.25
                        reasons.append(f"element_type={t}")
                        break
                else:
                    continue
                break

        # 3. Material match -----------------------------------------------
        if material:
            for token in cls._tokenize(material):
                if token in desc_lower:
                    score += 0.15
                    reasons.append(f"material={token}")
                    break

        # 4. Family/name match --------------------------------------------
        if name:
            for token in cls._tokenize(str(name)):
                if token in desc_lower:
                    score += 0.1
                    reasons.append(f"name={token}")
                    break

        # 5. Discipline / tag overlap -------------------------------------
        if discipline:
            disc_lower = str(discipline).lower()
            if disc_lower in item_tags or disc_lower in desc_lower:
                score += 0.05
                reasons.append(f"discipline={disc_lower}")

        # Small bonus per extra keyword hit (bounded) ---------------------
        extra_hits = 0
        for kw in keywords:
            if kw in desc_lower:
                extra_hits += 1
        if extra_hits > 1:
            score += min(0.05 * (extra_hits - 1), 0.15)
            reasons.append(f"+{extra_hits - 1} keyword hits")

        return score, reasons


# ── User cost catalogs ──────────────────────────────────────────────────────


class CostCatalogService:
    """Business logic for user-owned cost catalogs.

    A catalog is a named, currency-bearing container for :class:`CostItem`
    rows. Items reference it through the bare ``CostItem.catalog_id``
    column, so all delete semantics (detach vs soft-delete) are handled
    here rather than by an FK ON DELETE clause.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _assert_name_available(
        self,
        name: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Raise 409 when another catalog already uses the name (case-insensitive).

        The file-import dedup key stamps the catalog name as the items'
        region tag, so two same-name catalogs would silently dedupe
        against each other's rows.
        """
        stmt = select(CostCatalog.id).where(func.lower(CostCatalog.name) == name.strip().lower()).limit(1)
        if exclude_id is not None:
            stmt = stmt.where(CostCatalog.id != exclude_id)
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A cost catalog named '{name.strip()}' already exists. Choose a different name.",
            )

    async def create_catalog(
        self,
        data: CostCatalogCreate,
        *,
        created_by: uuid.UUID | None = None,
        source: str = "manual",
    ) -> CostCatalog:
        """Create a catalog. Currency is validated/uppercased by the schema.

        Raises 409 when another catalog already uses the name
        (case-insensitive) - the import dedup key uses the catalog name as
        region, so same-name catalogs would silently collide.
        """
        await self._assert_name_available(data.name)
        catalog = CostCatalog(
            name=data.name.strip(),
            description=data.description,
            currency=data.currency,
            source=source,
            created_by=created_by,
        )
        self.session.add(catalog)
        await self.session.commit()
        await self.session.refresh(catalog)
        logger.info("Cost catalog created: %s (%s)", catalog.name, catalog.currency)
        return catalog

    async def get_catalog(self, catalog_id: uuid.UUID) -> CostCatalog:
        """Get a catalog by id. Raises 404 if not found."""
        catalog = await self.session.get(CostCatalog, catalog_id)
        if catalog is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost catalog not found",
            )
        return catalog

    async def get_owned_catalog(
        self,
        catalog_id: uuid.UUID,
        *,
        owner_id: uuid.UUID | None,
        is_admin: bool = False,
    ) -> CostCatalog:
        """Get a catalog the caller is allowed to write to. Raises 404 otherwise.

        Ownership is checked against ``CostCatalog.created_by`` (the same
        ownership model used across the codebase). A non-admin caller who is
        not the owner gets a 404 - not a 403 - so the response is
        indistinguishable from a missing catalog and cannot be used as a
        UUID-existence oracle, matching ``verify_project_access``. Admins
        bypass the ownership check.
        """
        catalog = await self.get_catalog(catalog_id)
        if is_admin:
            return catalog
        if owner_id is not None and catalog.created_by == owner_id:
            return catalog
        # Mask access-denied as not-found to avoid leaking existence.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cost catalog not found",
        )

    async def count_items(self, catalog_id: uuid.UUID) -> int:
        """Count ACTIVE items currently attached to the catalog."""
        result = await self.session.execute(
            select(func.count(CostItem.id)).where(
                CostItem.catalog_id == catalog_id,
                CostItem.is_active.is_(True),
            )
        )
        return int(result.scalar_one())

    async def list_catalogs(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        is_admin: bool = False,
    ) -> list[tuple[CostCatalog, int]]:
        """List catalogs with their active item count (single query).

        Ownership scoping (mirrors the project access model elsewhere in the
        codebase): a non-admin caller sees ONLY the catalogs they created
        (``CostCatalog.created_by == owner_id``). Admins (and callers passed
        ``is_admin=True``) see every catalog. When ``owner_id`` is ``None``
        and the caller is not an admin the result is empty rather than
        leaking other users' catalogs.
        """
        stmt = (
            select(CostCatalog, func.count(CostItem.id))
            .outerjoin(
                CostItem,
                and_(CostItem.catalog_id == CostCatalog.id, CostItem.is_active.is_(True)),
            )
            .group_by(CostCatalog.id)
            .order_by(CostCatalog.created_at.desc())
        )
        if not is_admin:
            # Non-admins are restricted to their own catalogs. A missing
            # owner id (unparseable / absent subject) sees nothing.
            stmt = stmt.where(CostCatalog.created_by == owner_id)
        result = await self.session.execute(stmt)
        return [(catalog, int(count)) for catalog, count in result.all()]

    async def update_catalog(self, catalog_id: uuid.UUID, data: CostCatalogUpdate) -> CostCatalog:
        """Update a catalog. Raises 404 if missing, 409 on unsafe changes.

        A currency change is REJECTED while the catalog holds ANY items
        (soft-deleted included): the stored rates are denominated in the
        old currency, and silently re-labelling them would corrupt every
        figure. The caller must create a new catalog (or empty this one)
        instead. A rename to a name another catalog already uses
        (case-insensitive) is rejected the same way.
        """
        catalog = await self.get_catalog(catalog_id)
        fields = data.model_dump(exclude_unset=True)

        new_name = fields.get("name")
        if isinstance(new_name, str) and new_name.strip():
            await self._assert_name_available(new_name, exclude_id=catalog_id)

        new_currency = fields.get("currency")
        if new_currency is not None and new_currency != catalog.currency:
            # Count ALL rows including soft-deleted ones: a restored item
            # would otherwise come back mislabeled in the new currency.
            result = await self.session.execute(
                select(func.count(CostItem.id)).where(CostItem.catalog_id == catalog_id)
            )
            item_count = int(result.scalar_one())
            if item_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot change catalog currency from {catalog.currency} to "
                        f"{new_currency}: the catalog has {item_count} items whose rates "
                        f"are denominated in {catalog.currency}. Re-labelling them would "
                        f"corrupt the figures. Create a new catalog for the other "
                        f"currency, or remove the items first."
                    ),
                )

        for key, value in fields.items():
            if key == "name" and isinstance(value, str):
                value = value.strip()
            setattr(catalog, key, value)
        await self.session.commit()
        await self.session.refresh(catalog)
        logger.info("Cost catalog updated: %s", catalog.name)
        return catalog

    async def delete_catalog(self, catalog_id: uuid.UUID, *, mode: str = "keep_items") -> int:
        """Delete a catalog. Returns the number of affected items.

        ``mode``:
            * ``keep_items``   - detach items (``catalog_id`` set to NULL);
              the rows stay in the global cost table.
            * ``delete_items`` - soft-delete the items (``is_active=False``),
              consistent with single-item deletion.
        """
        catalog = await self.get_catalog(catalog_id)
        catalog_name = catalog.name

        if mode == "delete_items":
            stmt = sa_update(CostItem).where(CostItem.catalog_id == catalog_id).values(is_active=False)
        else:
            stmt = sa_update(CostItem).where(CostItem.catalog_id == catalog_id).values(catalog_id=None)
        result = await self.session.execute(stmt)
        affected = int(result.rowcount or 0)

        await self.session.delete(catalog)
        await self.session.commit()

        await _safe_publish(
            "costs.catalog.deleted",
            {"catalog_id": str(catalog_id), "name": catalog_name, "mode": mode, "items": affected},
            source_module="oe_costs",
        )
        logger.info("Cost catalog deleted: %s (mode=%s, items=%d)", catalog_name, mode, affected)
        return affected


# ── Cost benchmarks: own-portfolio distribution (Phase 2) ──────────────────


def _parse_decimal(raw: object) -> Decimal | None:
    """Parse a money / area string into a positive Decimal, or None.

    Project money and area columns and BOQ position totals are stored as
    locale-independent decimal strings. Blank, missing, non-numeric or
    non-positive values are treated as "no data" so they never poison the
    aggregation - the goal is honest real numbers, not invented ones.
    """
    from decimal import Decimal, InvalidOperation

    if raw is None:
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _percentile(sorted_values: list[Decimal], pct: float) -> Decimal:
    """Linear-interpolation percentile over a pre-sorted list (pct in 0..100).

    Matches the numpy "linear" method so the median (pct=50) of an even-length
    list is the average of the two middle elements. Caller guarantees the list
    is non-empty and sorted ascending.
    """
    from decimal import Decimal

    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = Decimal(str(rank - low))
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def _position_in_distribution(value: Decimal, sorted_values: list[Decimal]) -> float:
    """Return where ``value`` sits in ``sorted_values`` as a 0-100 percentile.

    Uses the fraction of portfolio values at or below ``value`` (the
    empirical CDF). Returns 0 when below everything, 100 when at or above
    everything.
    """
    n = len(sorted_values)
    if n == 0:
        return 0.0
    below = sum(1 for v in sorted_values if v <= value)
    return round((below / n) * 100.0, 1)


class CostBenchmarkService:
    """Computes the tenant's own cost-per-m2 portfolio distribution.

    The industry reference ranges live on the client (the static benchmark
    table). This service supplies only the part the client cannot compute:
    a real distribution derived from the user's own projects, where each
    project's cost-per-m2 is its BOQ grand total divided by its recorded
    gross floor area. Projects without both a cost and an area are skipped.

    Multi-tenant scoping mirrors the project list endpoint: a non-admin
    caller only sees projects they own or are a team member of, and the
    active partner-pack scope is honoured.
    """

    # Confidence thresholds on the usable-project count. A thin portfolio is
    # honestly labelled low so the UI never overstates how solid the
    # comparison is - the same spirit as CostCertaintyService.
    _CONF_HIGH_MIN = 8
    _CONF_MEDIUM_MIN = 3

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def portfolio_distribution(
        self,
        *,
        owner_id: uuid.UUID,
        is_admin: bool = False,
        building_type: str | None = None,
        region: str | None = None,
        currency: str | None = None,
        cost_per_m2: Decimal | None = None,
        metric: str = "cost_per_m2",
    ) -> dict[str, Any]:
        """Build the own-portfolio distribution payload for the chosen metric.

        Returns a plain dict shaped for ``BenchmarkResponse``. The default metric
        ``cost_per_m2`` is the BOQ grand total over gross floor area, the figure
        the original benchmark positions, and is currency-scoped. ``overrun_pct``
        and ``recovery_rate`` benchmark the same tenant projects on two
        dimensionless ratios, so a firm can read its own cost-overrun and
        recovery-rate distribution - by region when the ``region`` filter is set.
        For every metric ``own_portfolio`` / ``percentile_vs_own`` are None when
        no project in the filtered set yields a value for it. ``cost_per_m2`` is
        the optional value to position, read in the unit of the selected metric.
        """
        metric = (metric or "cost_per_m2").strip().lower()

        # ── 1. Resolve the candidate projects (tenant-scoped + filtered) ──
        projects = await self._candidate_projects(
            owner_id=owner_id,
            is_admin=is_admin,
            building_type=building_type,
            region=region,
        )
        if not projects:
            return self._empty(metric)

        if metric in ("overrun_pct", "recovery_rate"):
            return await self._ratio_distribution(projects, metric=metric, input_value=cost_per_m2)

        # Default (and fallback for an unknown metric): the money-denominated
        # cost-per-m2 distribution.
        return await self._cost_per_m2_distribution(projects, currency=currency, cost_per_m2=cost_per_m2)

    async def _cost_per_m2_distribution(
        self,
        projects: list[Any],
        *,
        currency: str | None,
        cost_per_m2: Decimal | None,
    ) -> dict[str, Any]:
        """The original metric: each project's BOQ grand total over its area.

        Currency-scoped and never blended: only same-currency projects share a
        distribution, and a supplied ``cost_per_m2`` is positioned only when the
        request named its currency (so the percentile is never cross-currency).
        """
        totals_by_project = await self._boq_totals_by_project(projects)

        # Per-project cost/m2, currency-scoped, never blending. Each entry is
        # (cost_per_m2, project_currency); a per-unit figure exists only when the
        # project has BOTH a positive total cost AND a positive recorded area.
        per_project: list[tuple[Decimal, str]] = []
        for proj in projects:
            total = totals_by_project.get(proj.id)
            area = _parse_decimal(self._project_area(proj))
            if total is None or area is None or area <= 0:
                continue
            proj_currency = (getattr(proj, "currency", "") or "").strip().upper()
            per_project.append((total / area, proj_currency))

        if not per_project:
            return self._empty("cost_per_m2")

        # ── 4. Pick the currency bucket (never mix currencies) ────────────
        requested_currency = (currency or "").strip().upper()
        target_currency = requested_currency
        if not target_currency:
            # Use the dominant currency among the usable projects.
            counts: dict[str, int] = {}
            for _, cur in per_project:
                counts[cur] = counts.get(cur, 0) + 1
            target_currency = max(counts, key=lambda c: counts[c])

        values = sorted(v for v, cur in per_project if cur == target_currency)
        if not values:
            if requested_currency:
                # The caller pinned a currency that no usable project matches.
                # Do NOT fall back to a different-currency bucket; say so plainly
                # so the percentile is never computed across currencies.
                return {
                    "currency": requested_currency,
                    "metric": "cost_per_m2",
                    "own_portfolio": None,
                    "percentile_vs_own": None,
                    "explanation": (
                        f"No comparable projects priced in {requested_currency} to position your value against."
                    ),
                }
            return self._empty(cost_per_m2)

        # ── 5. Distribution statistics ────────────────────────────────────
        count = len(values)
        portfolio = {
            "project_count": count,
            "min": values[0],
            "p25": _percentile(values, 25),
            "median": _percentile(values, 50),
            "p75": _percentile(values, 75),
            "max": values[-1],
            "confidence": self._confidence(count),
            # "1 of your projects" - the partitive stays plural at every count,
            # so there is no singular form to switch to here.
            "note": f"Based on {count} of your projects with cost and area.",
            "note_code": "cost_and_area",
        }

        # ── 6. Position the caller's value, but only within ITS OWN currency.
        # ``cost_per_m2`` is a bare number with no currency attached. We may
        # only position it against ``values`` when we KNOW it is denominated
        # in ``target_currency``. That is true only when the request named the
        # currency explicitly: then ``values`` was filtered to that same
        # currency above, so the comparison is single-currency. When the
        # currency was omitted, ``target_currency`` is the auto-selected
        # dominant bucket, which may differ from the caller's value currency,
        # so positioning would silently compare across currencies. In that
        # case we return ``percentile_vs_own=None`` with a note rather than a
        # misleading percentile.
        percentile_vs_own: float | None = None
        explanation = ""
        explanation_code = ""
        if cost_per_m2 is not None:
            if requested_currency:
                percentile_vs_own = _position_in_distribution(cost_per_m2, values)
                explanation_code = self._explain_code(cost_per_m2, portfolio["median"])
                explanation = self._explain(cost_per_m2, portfolio["median"], percentile_vs_own)
            else:
                explanation_code = "specify_currency"
                explanation = (
                    "Specify the currency of your value to position it against your "
                    f"portfolio. The distribution below is in {target_currency}."
                )

        return {
            "currency": target_currency,
            "metric": "cost_per_m2",
            "own_portfolio": portfolio,
            "percentile_vs_own": percentile_vs_own,
            "explanation": explanation,
            "explanation_code": explanation_code,
        }

    # ── Metric variants: regional overrun / recovery-rate benchmarks (#21) ──

    async def _boq_totals_by_project(self, projects: list[Any]) -> dict[uuid.UUID, Decimal]:
        """Each project's BOQ grand total in its OWN base currency.

        Mirrors the canonical BOQ rollup: section rows are skipped and every
        leaf is converted into the project base via the project's FX table
        before accumulating, so a project's total is genuinely single-currency
        (Issues #111/#131/#88/#157) rather than a blind sum that would blend
        per-position currencies. A project with no positive priced leaf is
        absent from the result. Shared by the cost-per-m2 and overrun metrics.
        """
        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.service import (
            _is_section,
            _leaf_total_base_with_resources,
            _project_fx_map,
        )

        project_ids = [p.id for p in projects]
        projects_by_id = {p.id: p for p in projects}
        rows = (
            await self.session.execute(
                select(BOQ.project_id, Position)
                .join(Position, Position.boq_id == BOQ.id)
                .where(BOQ.project_id.in_(project_ids))
            )
        ).all()
        fx_by_project: dict[uuid.UUID, tuple[str, dict[str, str]]] = {}
        totals_by_project: dict[uuid.UUID, Decimal] = {}
        for proj_id, pos in rows:
            if _is_section(pos):
                continue
            fx = fx_by_project.get(proj_id)
            if fx is None:
                proj = projects_by_id.get(proj_id)
                base_ccy = (getattr(proj, "currency", "") or "").strip().upper()
                fx = (base_ccy, _project_fx_map(proj))
                fx_by_project[proj_id] = fx
            base_ccy, fx_map = fx
            amount = _leaf_total_base_with_resources(pos, fx_map, base_ccy)
            if amount is None or amount <= 0:
                continue
            totals_by_project[proj_id] = totals_by_project.get(proj_id, Decimal("0")) + amount
        return totals_by_project

    async def _ratio_distribution(
        self,
        projects: list[Any],
        *,
        metric: str,
        input_value: Decimal | None,
    ) -> dict[str, Any]:
        """Distribution payload for a dimensionless ratio metric over *projects*.

        ``overrun_pct`` and ``recovery_rate`` are fractions, not money, so the
        distribution is NOT currency-scoped: a ratio is comparable across
        currencies. Reuses the same percentile statistics and confidence model
        as the cost-per-m2 metric. ``input_value`` (a fraction in the metric's
        own unit) is positioned against the distribution when supplied.
        """
        if metric == "overrun_pct":
            values = await self._overrun_values(projects)
            basis = "with an approved budget and a priced BOQ"
            note_code = "budget_and_boq"
        else:  # recovery_rate
            values = await self._recovery_values(projects)
            basis = "with a recovery ledger"
            note_code = "recovery_ledger"

        values = sorted(values)
        if not values:
            return self._empty(metric)

        count = len(values)
        portfolio = {
            "project_count": count,
            "min": values[0],
            "p25": _percentile(values, 25),
            "median": _percentile(values, 50),
            "p75": _percentile(values, 75),
            "max": values[-1],
            "confidence": self._confidence(count),
            "note": f"Based on {count} of your projects {basis}.",
            "note_code": note_code,
        }

        percentile_vs_own: float | None = None
        explanation = ""
        explanation_code = ""
        if input_value is not None:
            percentile_vs_own = _position_in_distribution(input_value, values)
            explanation_code = self._explain_code(input_value, portfolio["median"])
            explanation = self._explain(input_value, portfolio["median"], percentile_vs_own)

        return {
            # A ratio is dimensionless, so there is no currency to report.
            "currency": "",
            "metric": metric,
            "own_portfolio": portfolio,
            "percentile_vs_own": percentile_vs_own,
            "explanation": explanation,
            "explanation_code": explanation_code,
        }

    async def _overrun_values(self, projects: list[Any]) -> list[Decimal]:
        """Per-project cost overrun as a fraction: (priced BOQ - budget) / budget.

        The priced BOQ grand total (the project's current priced scope, in its
        base currency) measured against the project's approved
        ``budget_estimate``. A project counts only when it has BOTH a positive
        approved budget AND a BOQ total; both are in the project's own currency,
        so the ratio is single-currency and dimensionless. The value can be
        negative (the priced scope is under the approved budget).
        """
        totals = await self._boq_totals_by_project(projects)
        out: list[Decimal] = []
        for proj in projects:
            total = totals.get(proj.id)
            budget = _parse_decimal(getattr(proj, "budget_estimate", None))
            if total is None or budget is None or budget <= 0:
                continue
            out.append((total - budget) / budget)
        return out

    async def _recovery_values(self, projects: list[Any]) -> list[Decimal]:
        """Per-project recovery rate (recovered / chargeable), a fraction in [0, 1].

        Uses the cost-recovery engine's primary-currency headline rate per
        project, which never blends currencies. A project with nothing
        chargeable has no rate and is skipped. Imported locally so this lower
        level never takes a module-load dependency on cost_recovery.
        """
        from app.modules.cost_recovery.recovery_analytics import RecoveryItem, compute_recovery_performance
        from app.modules.cost_recovery.service import list_back_charges, to_back_charge_item

        out: list[Decimal] = []
        for proj in projects:
            rows = await list_back_charges(self.session, proj.id)
            items = [
                RecoveryItem(
                    chargeable=bc.chargeable_amount,
                    recovered=bc.recovered_amount,
                    currency=bc.currency,
                    traceability_band="",
                    status=bc.status,
                )
                for bc in (to_back_charge_item(row) for row in rows)
            ]
            performance = compute_recovery_performance(items)
            if performance.primary_rate is not None:
                out.append(performance.primary_rate)
        return out

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _candidate_projects(
        self,
        *,
        owner_id: uuid.UUID,
        is_admin: bool,
        building_type: str | None,
        region: str | None,
    ) -> list[Any]:
        """Tenant-scoped, filtered project rows (no relationships loaded)."""
        from sqlalchemy.orm import noload

        from app.core.partner_pack.scope import scope_project_query
        from app.modules.projects.models import Project
        from app.modules.teams.access import member_project_ids_subquery

        base = select(Project)
        # Honour the active partner-pack workspace scope, fail-soft.
        try:
            base = scope_project_query(base, Project)
        except Exception:  # noqa: BLE001 - scoping must never break the read
            logger.debug("Benchmark: partner-pack scoping skipped", exc_info=True)
        if not is_admin:
            base = base.where((Project.owner_id == owner_id) | (Project.id.in_(member_project_ids_subquery(owner_id))))
        base = base.where(Project.status != "archived")
        if building_type:
            base = base.where(_func_lower(Project.project_type) == building_type.strip().lower())
        if region:
            base = base.where(_func_lower(Project.region) == region.strip().lower())

        stmt = base.options(
            noload(Project.wbs_nodes),
            noload(Project.milestones),
            noload(Project.children),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _project_area(proj: Any) -> object:
        """Resolve a project's gross floor area from the column or metadata.

        Preference order: the real ``gross_floor_area`` column, then a
        ``gross_floor_area`` key in ``metadata_`` or ``custom_fields`` so
        projects that stored area before the column existed still count.
        """
        direct = getattr(proj, "gross_floor_area", None)
        if direct not in (None, ""):
            return direct
        for container_name in ("metadata_", "custom_fields"):
            container = getattr(proj, container_name, None)
            if isinstance(container, dict):
                for key in ("gross_floor_area", "gfa", "area_m2"):
                    val = container.get(key)
                    if val not in (None, ""):
                        return val
        return None

    @classmethod
    def _confidence(cls, count: int) -> str:
        if count >= cls._CONF_HIGH_MIN:
            return "high"
        if count >= cls._CONF_MEDIUM_MIN:
            return "medium"
        return "low"

    # The English sentence is derived from the code rather than written beside
    # it, so a change to the thresholds below cannot leave the two disagreeing.
    # Only the code reaches the client's translator; this text is the fallback
    # for any consumer reading ``explanation`` directly.
    _EXPLAIN_SENTENCES = {
        "below_median": "Your value sits below your own portfolio median.",
        "above_median": "Your value sits above your own portfolio median.",
        "at_median": "Your value sits right at your own portfolio median.",
    }

    @staticmethod
    def _explain_code(value: Decimal, median: Decimal) -> str:
        """Which reading applies, as a stable token the client can translate."""
        if value < median:
            return "below_median"
        if value > median:
            return "above_median"
        return "at_median"

    @classmethod
    def _explain(cls, value: Decimal, median: Decimal, percentile: float) -> str:
        return cls._EXPLAIN_SENTENCES[cls._explain_code(value, median)]

    @staticmethod
    def _empty(metric: str = "cost_per_m2") -> dict[str, Any]:
        return {
            "currency": "",
            "metric": metric,
            "own_portfolio": None,
            "percentile_vs_own": None,
            "explanation": "",
        }


def _func_lower(column: Any) -> Any:
    """Case-insensitive comparison helper that tolerates NULL columns."""
    from sqlalchemy import func as _func

    return _func.lower(_func.coalesce(column, ""))
