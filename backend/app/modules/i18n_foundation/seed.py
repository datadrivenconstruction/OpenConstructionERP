# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seed loader for oe_i18n_foundation module.

Loads countries, work calendars, and tax configurations from JSON files.
Idempotent: checks row count before inserting. Only seeds empty tables.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import Country, TaxConfiguration, WorkCalendar
from app.modules.i18n_foundation.subdivisions import normalize_subdivision
from app.modules.i18n_foundation.tax_rules import validate_tax_row

logger = logging.getLogger(__name__)

_SEED_DIR = Path(__file__).parent / "seed_data"


def _load_json(filename: str) -> list[dict]:
    """Load and parse a JSON seed file from the seed_data directory."""
    path = _SEED_DIR / filename
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def _count_rows(session: AsyncSession, model: type) -> int:
    """Return the number of rows in a table."""
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def _seed_countries(session: AsyncSession) -> int:
    """Seed country records from countries.json.

    Returns the number of records inserted (0 if table was already populated).
    """
    count = await _count_rows(session, Country)
    if count > 0:
        logger.info("oe_i18n_country already has %d rows, skipping seed.", count)
        return 0

    objects = [country_from_seed_row(row) for row in load_country_seed_rows()]
    session.add_all(objects)
    await session.flush()
    logger.info("Seeded %d countries.", len(objects))
    return len(objects)


def load_country_seed_rows() -> list[dict]:
    """Every country this release ships, straight out of the seed file.

    Public for the reason :func:`load_tax_seed_rows` is: the explicit reference
    data update in :mod:`app.modules.i18n_foundation.reference_data_update`
    compares an installed database against these rows and must read the same
    file the seeder does, not a copy of it.
    """
    return _load_json("countries.json")


def country_from_seed_row(row: dict) -> Country:
    """Build one ORM row from one country seed line.

    Shared by the seeder and the reference data update so that a country added
    to an old install is field for field the one a new install is seeded with.
    """
    return Country(
        iso_code=row["iso_code"],
        iso_code_3=row.get("iso_code_3"),
        name_en=row["name_en"],
        name_translations=row["name_translations"],
        currency_default=row.get("currency_default"),
        measurement_default=row.get("measurement_default"),
        phone_code=row.get("phone_code"),
        region_group=row.get("region_group"),
        is_active=True,
        metadata_={},
    )


async def _seed_work_calendars(session: AsyncSession) -> int:
    """Seed work calendar records from work_calendars.json.

    Returns the number of records inserted (0 if table was already populated).
    """
    count = await _count_rows(session, WorkCalendar)
    if count > 0:
        logger.info("oe_i18n_work_calendar already has %d rows, skipping seed.", count)
        return 0

    data = load_work_calendar_seed_rows()
    objects = [work_calendar_from_seed_row(row) for row in data]
    session.add_all(objects)
    await session.flush()
    logger.info("Seeded %d work calendars.", len(objects))
    return len(objects)


def load_work_calendar_seed_rows() -> list[dict]:
    """Every work calendar this release ships, straight out of the seed file.

    Public for the reason :func:`load_tax_seed_rows` is public. The boot-path
    reconciler in
    :mod:`app.modules.i18n_foundation.work_calendar_seed_reconcile` hands these
    rows to an install that was seeded before they were added, and it reads
    them from here rather than carrying a copy.

    A copy would be worse here than it is for a tax rate. A stale working week
    is five plausible numbers, and this table has already shipped one week
    written under the wrong weekday convention, which no reader can see by
    looking at it. Two copies of that are two chances to fix only one.
    """
    return _load_json("work_calendars.json")


def work_calendar_from_seed_row(row: dict) -> WorkCalendar:
    """Build one ORM row from one work-calendar seed line.

    The seeder and the reconciler both come through here, so a calendar
    delivered to an old install is field for field the calendar a new install
    would have been seeded with, including the defaults filled in for keys the
    file leaves out.
    """
    return WorkCalendar(
        country_code=row["country_code"],
        name=row["name"],
        name_translations=row.get("name_translations"),
        year=row["year"],
        work_hours_per_day=row.get("work_hours_per_day", "8"),
        work_days=row["work_days"],
        exceptions=row.get("exceptions", []),
        metadata_={},
    )


def load_tax_seed_rows() -> list[dict]:
    """Every tax rate this release ships, straight out of the seed file.

    Public because the seeder is not the only reader any more. The boot-path
    reconciler in :mod:`app.modules.i18n_foundation.tax_seed_reconcile` hands
    the same rows to an install that was seeded before they were added, and it
    has to read them from here rather than carry a copy: a second copy is a
    second thing to update, and the one that gets forgotten is the one nobody
    notices, because a stale copy of a tax rate still looks like a tax rate.
    """
    return _load_json("tax_configurations.json")


def tax_configuration_from_seed_row(row: dict) -> TaxConfiguration:
    """Build one ORM row from one seed-file line, through the write rules.

    Shared by the seeder and the reconciler for the same reason
    :func:`load_tax_seed_rows` is: a row that arrives on an upgraded install
    has to be indistinguishable from the one a fresh install gets, field for
    field, or the two cohorts start answering differently.

    ``validate_tax_row`` runs here because this is a write path into
    ``oe_i18n_tax_config`` that never passes through the API schema. It is what
    stops a mislabelled row reaching the one place it would be permanent and
    would ship to every new installation.
    """
    subdivision = normalize_subdivision(row.get("subdivision_code"))
    validate_tax_row(row["country_code"], row["combination"], subdivision, rate_pct=row["rate_pct"])
    return TaxConfiguration(
        country_code=row["country_code"],
        tax_name=row["tax_name"],
        tax_name_translations=row.get("tax_name_translations"),
        tax_code=row.get("tax_code"),
        rate_pct=row["rate_pct"],
        tax_type=row["tax_type"],
        combination=row["combination"],
        subdivision_code=subdivision,
        effective_from=row.get("effective_from"),
        effective_to=row.get("effective_to"),
        is_default=row.get("is_default", False),
        metadata_={},
    )


async def _seed_tax_configurations(session: AsyncSession) -> int:
    """Seed tax configuration records from tax_configurations.json.

    Returns the number of records inserted (0 if table was already populated).

    That early return is the whole reason
    :mod:`app.modules.i18n_foundation.tax_seed_reconcile` exists. A rate added
    to the seed file in a later release never reaches a database that was
    seeded before it, and this function is where that stops.
    """
    count = await _count_rows(session, TaxConfiguration)
    if count > 0:
        logger.info("oe_i18n_tax_config already has %d rows, skipping seed.", count)
        return 0

    objects = [tax_configuration_from_seed_row(row) for row in load_tax_seed_rows()]
    session.add_all(objects)
    await session.flush()
    logger.info("Seeded %d tax configurations.", len(objects))
    return len(objects)


async def seed_i18n_data(session: AsyncSession) -> dict[str, int]:
    """Load seed data for countries, work calendars, and tax configurations.

    Idempotent -- checks count before inserting. Only inserts if tables are empty.
    Returns counts of seeded records per entity.

    Does NOT repair an already-seeded table, and does not fill one either. Both
    live in the boot-path repair registry instead, because that is where a
    write to existing customer data gets a ledger, a health signal and a gate:
    :mod:`app.modules.i18n_foundation.tax_subdivision_repair` for the rows that
    are here but incomplete, and
    :mod:`app.modules.i18n_foundation.tax_seed_reconcile` for the rows a later
    release added to the file and this install therefore never received.

    Countries carry the same early return and have no boot reconciler; see
    ``tax_seed_reconcile`` for why that was left rather than generalised. What
    covers them, and every field change the boot path may not make on its own,
    is the explicit update an administrator previews and confirms:
    :mod:`app.modules.i18n_foundation.reference_data_update`.
    """
    countries = await _seed_countries(session)
    calendars = await _seed_work_calendars(session)
    taxes = await _seed_tax_configurations(session)

    result = {"countries": countries, "calendars": calendars, "taxes": taxes}
    logger.info("i18n seed complete: %s", result)
    return result
