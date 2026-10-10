# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The price-book half of a Turkish validation payload, read once per run.

Two ``birimfiyat`` rules judge a bill line against the unit-price book it
cites: the unit the book defines the poz in, and the price the book publishes
for it. A rule receives data, never a database session, so the book cannot be
looked up from inside the rule. This module is the caller's side of that
bargain, built the way :mod:`app.core.validation.project_context` builds the
project's half: the surface that validates a bill asks here, in its own
session, and the answer travels in the payload under :data:`POZ_CATALOGUE_KEY`.

Three properties are deliberate.

* **Nothing is paid by a bill that is not Turkish.** The lookup runs only when
  the resolved rule sets reach one of the two rules, which is the same question
  the engine asks the registry. A German project issues no query here.
* **Nothing is remembered between runs.** A national base can be priced into
  another market, which rewrites ``rate`` and ``currency`` of its rows in
  place. A process cache would go on serving the prices from before the
  switch, and the lookup is an index probe, so it is simply run again.
* **A book that could not be read is said to be unread.** The catalogue carries
  a state. ``loaded`` is the only one the rules judge lines under; the others
  make a rule report, once, that the check did not run and why. An absent key
  means nobody asked, and the rules keep quiet.

The base is installation-wide: ``oe_costs_item`` has no tenant, owner or
organisation column, so every tenant of a shared deployment reads the same
``TR_NATIONAL`` rows, and one tenant's market switch is every tenant's.

What the loaded rows do not know: the cost import stores neither the year of
the book nor the institution that published it (``source_year`` and
``source_institution`` are not among the columns it reads, and it leaves
``price_as_of`` empty). An entry therefore carries no edition, and a rule that
quotes a published price cannot say which year's price it is.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The payload key the catalogue travels under.
POZ_CATALOGUE_KEY = "poz_catalogue"

#: The region id of the national unit-price base, the one whose
#: ``CostItem.code`` is the poz number.
TR_POZ_REGION = "TR_NATIONAL"

#: The two rules that read the catalogue. The lookup runs only for a run whose
#: rule sets reach at least one of them.
UNIT_RULE_ID = "birimfiyat.unit_matches_poz_definition"
RATE_RULE_ID = "birimfiyat.unit_rate_within_published_price"
POZ_CATALOGUE_RULE_IDS: frozenset[str] = frozenset({UNIT_RULE_ID, RATE_RULE_ID})

#: The reference document of the Turkish pack that carries the comparison
#: thresholds, and the block inside it.
TR_POZ_RULE_PACK = "bayindirlik_unit_prices"
PRICE_COMPARISON_BLOCK = "published_price_comparison"

#: Codes per ``code IN (...)`` statement. asyncpg accepts 32,767 bind
#: parameters in one statement; 5,000 leaves room for the two other binds and
#: keeps a 5,000 line bill, which rarely cites 5,000 different numbers, to one
#: statement.
POZ_IN_CHUNK = 5000


class PozCatalogueState(StrEnum):
    """Whether the book could be read, and if not, why."""

    LOADED = "loaded"  # the rows were read and are the base's own prices
    NOT_INSTALLED = "not_installed"  # the region holds no rows at all
    REPRICED = "repriced"  # the rows are in another market or currency, or mid-switch
    UNAVAILABLE = "unavailable"  # no session, or the read failed


@dataclass(frozen=True)
class PozEntry:
    """One poz as the installed base defines it.

    There is no edition field because the base does not store one.
    """

    code: str
    unit: str
    rate: Decimal | None  # the published unit price; ``None`` when unreadable
    currency: str


@dataclass(frozen=True)
class PublishedPriceTolerance:
    """How far a rate may sit from the published price before it is a warning.

    Both bounds ship unset. Unset means the difference is stated as
    information and never escalated; it does not mean zero.
    """

    warn_above_percent: Decimal | None = None
    warn_below_percent: Decimal | None = None
    review_status: str = ""


@dataclass(frozen=True)
class PozCatalogue:
    """The entries a bill asked for, and the state the base was found in."""

    region: str
    state: PozCatalogueState
    entries: Mapping[str, PozEntry] = field(default_factory=lambda: MappingProxyType({}))
    asked: int = 0
    home_currency: str = ""
    tolerance: PublishedPriceTolerance = field(default_factory=PublishedPriceTolerance)


def _chunks(codes: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(codes), size):
        yield codes[start : start + size]


def _as_rate(raw: Any) -> Decimal | None:
    """A stored rate as a positive :class:`Decimal`, or ``None``."""
    try:
        rate = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    return rate if rate.is_finite() and rate > 0 else None


async def _read(session: AsyncSession, codes: list[str], region: str, chunk_size: int) -> PozCatalogue:
    from sqlalchemy import select

    from app.modules.costs.base_state import read_base_state
    from app.modules.costs.models import CostItem
    from app.modules.costs.region_currency import REGION_CURRENCY

    home_currency = REGION_CURRENCY.get(region, "")
    entries: dict[str, PozEntry] = {}
    for chunk in _chunks(codes, chunk_size):
        # An index probe per code. On a 78,000 row table PostgreSQL 16 chose
        # the unique index uq_costs_code_region (code, region) and filtered
        # is_active on the row; ix_costs_region_active_code (region,
        # is_active, code) covers the same three predicates. The components
        # JSON, by far the widest column, is not selected.
        stmt = select(CostItem.code, CostItem.unit, CostItem.rate, CostItem.currency).where(
            CostItem.region == region,
            CostItem.is_active.is_(True),
            CostItem.code.in_(chunk),
        )
        for code, unit, rate, currency in (await session.execute(stmt)).all():
            entries[code] = PozEntry(
                code=code,
                unit=str(unit or "").strip(),
                rate=_as_rate(rate),
                # An older import stored no currency on a row; such a row is
                # in the currency of its region, which is how every read path
                # of the cost module resolves it. It is not a switched market.
                currency=str(currency or "").strip().upper() or home_currency,
            )

    if not entries:
        # Nothing matched. That is a bill citing numbers the book does not
        # have, unless the book is not there at all; one probe tells them apart.
        present = (await session.execute(select(CostItem.id).where(CostItem.region == region).limit(1))).first()
        state = PozCatalogueState.LOADED if present is not None else PozCatalogueState.NOT_INSTALLED
        return PozCatalogue(region=region, state=state, asked=len(codes), home_currency=home_currency)

    # A base priced into another market holds that market's rates under the
    # same poz numbers. The stored state says so; a row stamped with another
    # currency says so too, for a base switched before the state was recorded.
    stored = await read_base_state(session, region)
    switched = stored is not None and bool(stored.active_market or stored.switching_to)
    foreign = not home_currency or any(entry.currency != home_currency for entry in entries.values())
    return PozCatalogue(
        region=region,
        state=PozCatalogueState.REPRICED if switched or foreign else PozCatalogueState.LOADED,
        entries=MappingProxyType(entries),
        asked=len(codes),
        home_currency=home_currency,
    )


async def load_poz_catalogue(
    session: AsyncSession | None,
    codes: Iterable[str],
    region: str = TR_POZ_REGION,
    *,
    chunk_size: int = POZ_IN_CHUNK,
) -> PozCatalogue:
    """Read the book's definition of every poz in ``codes``, in the caller's session.

    One ``code IN (...)`` statement per :data:`POZ_IN_CHUNK` distinct codes,
    then at most one more: a one-row probe when nothing matched, or the read of
    the base's market state when something did. No statement at all for an
    empty ``codes``.

    The read runs inside a savepoint, so a failure leaves the caller's
    transaction usable and comes back as ``unavailable`` instead of raising.

    Args:
        session: The caller's live session. ``None`` yields ``unavailable``.
        codes: Poz numbers as the rules normalise them. Duplicates and blanks
            are dropped.
        region: The cost-base region to read.
        chunk_size: Codes per statement.

    Returns:
        An immutable catalogue holding only the codes that were asked for and
        found. Its tolerance is unset; :func:`with_poz_catalogue_for_rule_sets`
        fills it.
    """
    wanted = sorted({code for code in codes if isinstance(code, str) and code.strip()})
    if not wanted:
        return PozCatalogue(region=region, state=PozCatalogueState.LOADED)
    if session is None:
        return PozCatalogue(region=region, state=PozCatalogueState.UNAVAILABLE, asked=len(wanted))
    try:
        async with session.begin_nested():
            return await _read(session, wanted, region, max(1, chunk_size))
    except Exception:  # noqa: BLE001 - a report is still owed to the caller
        logger.warning("Could not read the unit-price base %s for validation", region, exc_info=True)
        return PozCatalogue(region=region, state=PozCatalogueState.UNAVAILABLE, asked=len(wanted))


def with_poz_catalogue(data: dict[str, Any], catalogue: PozCatalogue) -> dict[str, Any]:
    """Return ``data`` plus the catalogue, under :data:`POZ_CATALOGUE_KEY`.

    ``data`` is left unmodified; a new mapping is returned, as
    :func:`app.core.validation.project_context.with_project_context` does.
    """
    return {**data, POZ_CATALOGUE_KEY: catalogue}


def rule_sets_reach_poz_catalogue(rule_sets: Iterable[str]) -> bool:
    """Whether a run over ``rule_sets`` executes a rule that reads the catalogue."""
    from app.core.validation.engine import rule_registry

    return any(
        rule.rule_id in POZ_CATALOGUE_RULE_IDS and rule.enabled
        for rule in rule_registry.get_rules_for_sets(list(rule_sets))
    )


def _percent(raw: Any, name: str) -> Decimal | None:
    """A threshold as written in the document, or ``None`` when it is unset or unreadable."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        logger.warning("Ignoring %s=%r in %s: not a number", name, raw, TR_POZ_RULE_PACK)
        return None
    if not value.is_finite() or value < 0:
        logger.warning("Ignoring %s=%r in %s: not a percentage", name, raw, TR_POZ_RULE_PACK)
        return None
    return value


def tolerance_from_document(document: Mapping[str, Any] | None) -> PublishedPriceTolerance:
    """Read the comparison thresholds out of the pack's reference document.

    A missing document, a missing block or a null bound all yield an unset
    bound. Nothing here supplies a number the document does not state.
    """
    block = (document or {}).get(PRICE_COMPARISON_BLOCK)
    if not isinstance(block, Mapping):
        return PublishedPriceTolerance()
    return PublishedPriceTolerance(
        warn_above_percent=_percent(block.get("warn_above_percent"), "warn_above_percent"),
        warn_below_percent=_percent(block.get("warn_below_percent"), "warn_below_percent"),
        review_status=str(block.get("review_status") or ""),
    )


def read_published_price_tolerance() -> PublishedPriceTolerance:
    """The thresholds the installed Turkish pack states, read from its document.

    The file is read on every call. It is a few kilobytes, it is only read for
    a run that reaches the rules, and an edited threshold then applies to the
    next run instead of the next restart. Without the pack there is no
    document, and the bounds stay unset.
    """
    try:
        from app.core.validation.pack_coverage import _discover_pack_files

        for file in _discover_pack_files():
            if file.path.stem == TR_POZ_RULE_PACK:
                return tolerance_from_document(json.loads(file.path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - an unreadable document means unset thresholds
        logger.warning("Could not read the comparison thresholds from %s", TR_POZ_RULE_PACK, exc_info=True)
    return PublishedPriceTolerance()


def _ministry_poz_codes(data: Mapping[str, Any]) -> set[str]:
    """The poz numbers in ``data`` that the two rules would look up."""
    # Imported here: the rules import this module's key and types at the top
    # of their file, so a top-level import the other way would be a cycle.
    # The normalisation is the rules' own, so what is asked for is exactly
    # what a rule will look up.
    from app.core.validation.rules import ministry_poz_of

    positions = data.get("positions")
    if not isinstance(positions, list):
        return set()
    return {code for pos in positions if isinstance(pos, dict) and (code := ministry_poz_of(pos))}


async def with_poz_catalogue_for_rule_sets(
    session: AsyncSession | None,
    data: dict[str, Any],
    rule_sets: Iterable[str],
) -> dict[str, Any]:
    """Attach the catalogue when, and only when, ``rule_sets`` reach a rule that reads it.

    This is the one line a BOQ validation surface adds. For any run that does
    not reach the two rules it returns ``data`` itself, having touched neither
    the database nor the pack's document.

    Args:
        session: The caller's live session, or ``None`` where none is in scope.
        data: The payload about to be validated; ``data["positions"]`` is read.
        rule_sets: The resolved rule sets of the run, the list handed to the engine.

    Returns:
        ``data`` unchanged, or a new mapping carrying it plus the catalogue.
    """
    if not isinstance(data, dict) or not rule_sets_reach_poz_catalogue(rule_sets):
        return data
    catalogue = await load_poz_catalogue(session, _ministry_poz_codes(data))
    return with_poz_catalogue(data, replace(catalogue, tolerance=read_published_price_tolerance()))
