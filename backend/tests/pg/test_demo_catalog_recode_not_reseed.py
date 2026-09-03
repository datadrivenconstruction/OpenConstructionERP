# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Re-seeding a catalogue that carries the previous codes must not double it.

The catalogue seeder is idempotent by marker bail-out: it looks for one known
``resource_code`` and returns early if it is there. Renaming the thirty-three
codes therefore breaks the guard on every install seeded by an older build. The
marker no longer matches, the seeder runs a second time, and the estate ends up
with sixty-six rows and two of every resource. ``resource_code`` is indexed but
not unique, so the database accepts that silently.

The repair is an UPDATE rather than a delete and reinsert.
``Component.catalog_resource_id`` in the assemblies module is a foreign key
declared ``ondelete="SET NULL"``: deleting these rows would null out every link
an assembly component holds to a catalog resource without raising anything, and
would discard ``usage_count`` along with it. Keeping the row id keeps the links.

That distinction is what
:func:`test_an_estate_on_the_previous_codes_is_recoded_not_reseeded` exists for.
A test that only counted rows would pass under either implementation, because
delete-and-reinsert also lands on thirty-three. Comparing the ids before and
after is the only assertion that separates them.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.catalog.models import CatalogResource
from app.modules.catalog.seed import (
    _LEGACY_CODES,
    _LEGACY_MARKER_CODE,
    _MARKER_CODE,
    _RESOURCES,
    seed_catalog,
)

pytestmark = pytest.mark.asyncio

_CURRENT_CODES = [row[0] for row in _RESOURCES]
_ALL_CODES = set(_CURRENT_CODES) | set(_LEGACY_CODES)


async def _write_legacy_estate(session) -> dict[str, uuid.UUID]:
    """Insert the catalogue as an older build wrote it, under the old codes.

    Returns code -> row id, so a later read can prove the rows are the same
    rows and not replacements wearing the same values.
    """
    ids: dict[str, uuid.UUID] = {}
    for legacy_code, current_code in _LEGACY_CODES.items():
        spec = next(row for row in _RESOURCES if row[0] == current_code)
        _code, name, resource_type, category, unit, base, low, high = spec
        row_id = uuid.uuid4()
        session.add(
            CatalogResource(
                id=row_id,
                resource_code=legacy_code,
                name=name,
                resource_type=resource_type,
                category=category,
                unit=unit,
                base_price=base,
                min_price=low,
                max_price=high,
                currency="EUR",
                # Non-zero on purpose: a delete would take this with it.
                usage_count=7,
                source="manual",
                region="EU",
                specifications={"demo": True, "band": [low, high]},
                is_active=True,
                metadata_={"seed": True, "demo": True},
            )
        )
        ids[legacy_code] = row_id
    await session.flush()
    return ids


async def _codes_present(session) -> list[str]:
    """Catalogue codes this test family owns, read straight from the table."""
    result = await session.execute(
        select(CatalogResource.resource_code).where(CatalogResource.resource_code.in_(_ALL_CODES))
    )
    return sorted(result.scalars().all())


async def _count_owned(session) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(CatalogResource).where(CatalogResource.resource_code.in_(_ALL_CODES))
        )
    ).scalar_one()


async def test_a_fresh_estate_gets_the_full_catalogue_once(pg_session) -> None:
    """The ordinary path: nothing there, everything lands, under the new codes."""
    counts = await seed_catalog(pg_session, [uuid.uuid4()])

    assert counts["catalog_resources"] == len(_RESOURCES)
    assert await _codes_present(pg_session) == sorted(_CURRENT_CODES)


async def test_a_second_run_over_the_same_estate_inserts_nothing(pg_session) -> None:
    """The marker bail-out still holds once the codes are current."""
    await seed_catalog(pg_session, [uuid.uuid4()])
    first = await _count_owned(pg_session)

    again = await seed_catalog(pg_session, [uuid.uuid4()])

    assert again == {}, f"a settled estate should be a no-op, got {again}"
    assert await _count_owned(pg_session) == first == len(_RESOURCES)


async def test_an_estate_on_the_previous_codes_is_recoded_not_reseeded(pg_session) -> None:
    """The branch the rename exists for, and the only test that discriminates.

    Row count alone cannot tell a rename from a delete and reinsert: both end
    on thirty-three. The ids and ``usage_count`` can, and those are exactly what
    a delete would take with it, along with every assembly component link
    pointing at these rows.
    """
    before = await _write_legacy_estate(pg_session)
    assert await _count_owned(pg_session) == len(_RESOURCES)

    counts = await seed_catalog(pg_session, [uuid.uuid4()])

    assert counts == {"catalog_resources_recoded": len(_RESOURCES)}
    assert "catalog_resources" not in counts, "the legacy branch fell through into the insert"

    total = await _count_owned(pg_session)
    assert total == len(_RESOURCES), f"a re-seed over the previous codes left {total} rows, expected {len(_RESOURCES)}"
    assert await _codes_present(pg_session) == sorted(_CURRENT_CODES)

    rows = (
        await pg_session.execute(
            select(CatalogResource.id, CatalogResource.resource_code, CatalogResource.usage_count).where(
                CatalogResource.resource_code.in_(_CURRENT_CODES)
            )
        )
    ).all()
    after = {code: row_id for row_id, code, _usage in rows}
    expected = {_LEGACY_CODES[legacy]: row_id for legacy, row_id in before.items()}
    assert after == expected, "the rows were replaced, not renamed - component links would have been nulled"
    assert {usage for _id, _code, usage in rows} == {7}, "usage_count did not survive the rename"


async def test_a_code_outside_the_map_is_left_alone(pg_session) -> None:
    """The recode is an exact-match map, not a sweep over everything DEMO-.

    A customer is free to code their own resources with that prefix. A blanket
    ``LIKE 'DEMO-%'`` update would rewrite theirs too.
    """
    await _write_legacy_estate(pg_session)
    stranger = "DEMO-CUSTOM-777"
    assert stranger not in _LEGACY_CODES
    pg_session.add(
        CatalogResource(
            id=uuid.uuid4(),
            resource_code=stranger,
            name="Customer's own entry",
            resource_type="material",
            category="Uncategorised",
            unit="pcs",
            base_price="1.00",
            min_price="1.00",
            max_price="1.00",
            currency="EUR",
            usage_count=0,
            source="manual",
            region="EU",
            specifications={},
            is_active=True,
            metadata_={},
        )
    )
    await pg_session.flush()

    await seed_catalog(pg_session, [uuid.uuid4()])

    survivor = (
        await pg_session.execute(
            select(func.count()).select_from(CatalogResource).where(CatalogResource.resource_code == stranger)
        )
    ).scalar_one()
    assert survivor == 1, "a resource the customer coded themselves was rewritten by the recode"


async def test_the_two_markers_name_the_same_resource(pg_session) -> None:
    """Guard the derivation that ties the old marker to the new one.

    If someone reorders ``_RESOURCES`` or changes the prefix constants, the
    legacy marker can silently start naming a code that was never shipped, and
    the recode branch becomes unreachable: the seeder would look for a row that
    does not exist and go straight to inserting a second catalogue.
    """
    assert _RESOURCES[0][0] == _MARKER_CODE
    assert _LEGACY_CODES[_LEGACY_MARKER_CODE] == _MARKER_CODE
    assert len(_LEGACY_CODES) == len(_RESOURCES), "the old-to-new map lost an entry to a collision"
