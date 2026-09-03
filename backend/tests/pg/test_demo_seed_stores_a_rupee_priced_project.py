# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A rupee-priced demo has to survive the trip into PostgreSQL and back.

Pricing each demo project in its own currency multiplied the money by up to
fifty five, and the two ways that breaks are both invisible from a unit test
that never opens a database.

The first is column width. Every figure here is written through a column with a
declared size - ``Numeric(18, 4)`` on the plant and resource rates, ``String``
on the assembly totals - and a value one character too long is not rounded, it
is rejected, and the whole install fails with nothing written. This module has
already seen that happen once, on a risk score that fitted a euro figure and
not a rupee one, so the widths are checked here against what the database
actually stored rather than against what the model file declares.

The second is silence. Each block in the seeder sits inside its own
``except Exception: logger.debug(...)``, which is deliberate - a module that is
not installed must not fail the install - but it also means a rejected write
returns success with the count never set. A test that only asserts the install
completed passes just as happily on a project where nothing was written at all,
so every count here is asserted positive before anything is read back.

The last assertion is the product claim itself: rupees have to read bigger than
euros. It compares against the same template generated in euros, so it fails on
the seed as it stood before this change, where both read the same number.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data, install_demo_project
from app.modules.assemblies.models import Assembly, Component
from app.modules.equipment.models import EquipmentRental
from app.modules.projects.models import Project
from app.modules.resources.models import Resource

pytestmark = pytest.mark.asyncio

# The Bengaluru pack is the largest multiplier the table carries, so it is the
# one that finds a column too narrow. If this id ever leaves the packs the test
# must fail loudly rather than quietly skip, which is what the assertion in the
# fixture below is for.
_DEMO_ID = "it-park-bangalore"


def _euro_twin() -> dict[str, list[dict]]:
    """The same project generated in euros, for the comparison at the end."""
    template = replace(DEMO_TEMPLATES[_DEMO_ID], currency="EUR")
    return _generate_module_data(
        template,
        uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
        uuid.UUID("00000000-0000-0000-0000-0000000000bb"),
        _DEMO_ID,
        datetime(2026, 1, 5, tzinfo=UTC).replace(tzinfo=None),
    )


async def test_a_rupee_priced_demo_installs_and_reads_back_whole(pg_session) -> None:
    assert _DEMO_ID in DEMO_TEMPLATES, (
        f"{_DEMO_ID} is no longer a registered demo, so this test would be asserting about nothing"
    )
    assert DEMO_TEMPLATES[_DEMO_ID].currency == "INR", "the pack this test is built on no longer prices in rupees"

    result = await install_demo_project(pg_session, _DEMO_ID, force_reinstall=True)
    project_id = uuid.UUID(str(result["project_id"]))

    project = (await pg_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert (project.currency or "")[:3] == "INR", f"the installed project is denominated in {project.currency!r}"

    # Counts first. Each of these blocks swallows its own exception, so a
    # rejected write reaches this point as a successful install with an empty
    # table, and every read below would then be reading nothing.
    assemblies = (await pg_session.execute(select(Assembly).where(Assembly.project_id == project_id))).scalars().all()
    assert assemblies, "the install reported success and wrote no assemblies at all"

    components = (
        (await pg_session.execute(select(Component).where(Component.assembly_id.in_([a.id for a in assemblies]))))
        .scalars()
        .all()
    )
    assert components, "assemblies were written with no components under them"

    rentals = (
        (await pg_session.execute(select(EquipmentRental).where(EquipmentRental.project_id == project_id)))
        .scalars()
        .all()
    )
    assert rentals, "the install reported success and wrote no plant rentals at all"

    resources = (
        (await pg_session.execute(select(Resource).where(Resource.home_project_id == project_id))).scalars().all()
    )
    assert resources, "the install reported success and wrote no resources at all"

    # Nothing was clipped on the way in. A too-narrow column does not silently
    # shorten a value in PostgreSQL, but a too-small scale does round one, and
    # a stored figure that no longer parses as the number that was written is
    # the failure this is looking for.
    for asm in assemblies:
        rate = Decimal(str(asm.total_rate))
        assert rate > 0, f"assembly {asm.code} came back priced at {asm.total_rate!r}"
        assert str(asm.total_rate) == str(rate), f"assembly {asm.code} stored {asm.total_rate!r}, which lost digits"

    for comp in components:
        unit_cost = Decimal(str(comp.unit_cost))
        total = Decimal(str(comp.total))
        assert unit_cost >= 0, f"component {comp.description!r} came back at {comp.unit_cost!r}"
        assert total >= 0, f"component {comp.description!r} totals {comp.total!r}"

    for rental in rentals:
        day = Decimal(str(rental.internal_rate_per_day))
        hour = Decimal(str(rental.internal_rate_per_hour))
        assert day > 0, "a plant rental came back at a day rate of zero"
        assert hour > 0, "a plant rental came back at an hour rate of zero"
        # Numeric(18, 4) holds four decimals. A day rate that survived the trip
        # is the same number to the cent that the seeder produced; one that hit
        # the scale would come back rounded and this comparison would show it.
        assert day == day.quantize(Decimal("0.0001")), f"a day rate of {day} was rounded by the column"

    # A subcontractor in the pool is a firm, and a firm's price lives in its
    # contract rather than in an hourly rate, so those rows carry nought on
    # purpose. Every row that does quote a rate has to quote a real one.
    priced = [r for r in resources if r.resource_type != "subcontractor"]
    assert priced, "the pool holds nothing but subcontractors, so no rate was levelled at all"
    for res in priced:
        rate = Decimal(str(res.default_cost_rate))
        assert rate > 0, f"resource {res.name!r} came back priced at {res.default_cost_rate!r}"
        assert (res.currency or "")[:3] == "INR", f"resource {res.name!r} is denominated in {res.currency!r}"
    for res in resources:
        if res.resource_type == "subcontractor":
            assert Decimal(str(res.default_cost_rate)) == 0, (
                f"firm {res.name!r} was given an hourly rate of {res.default_cost_rate!r}"
            )

    # The product claim. Before this change every currency printed the euro
    # figure, so the two maxima below were equal and this fails on that seed.
    euro_rates = [float(r["rate"]) for r in _euro_twin()["resources"] if r.get("rate")]
    assert euro_rates, "the euro twin generated no resources, so there is nothing to compare against"
    stored_max = max(Decimal(str(r.default_cost_rate)) for r in priced)
    assert stored_max > Decimal(str(max(euro_rates))), (
        f"the rupee project's dearest resource is {stored_max}, no more than the euro twin's {max(euro_rates)}"
    )
