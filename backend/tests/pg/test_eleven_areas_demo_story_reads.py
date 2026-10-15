# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the two demo projects of the eleven-areas pack read back after a fresh install.

Each test reads what a viewer of the demo would see and checks it against the story: the staffing plan
puts every story person on the role the story gives them, every commitment item sits on a cost line, and
the cost frame shows the bound works package under a cost group rather than nothing.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.pg.elf_qa_fixtures import World, boot_world

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("OE_API_SMOKE", "") != "1", reason="full-boot lane: set OE_API_SMOKE=1"),
]


@pytest_asyncio.fixture(scope="module")
async def world(pg_async_url, tmp_path_factory):
    async for w in boot_world(pg_async_url, str(tmp_path_factory.mktemp("elf_story_reads"))):
        yield w


async def test_every_story_person_holds_the_role_the_story_gives_them(world: World) -> None:
    from app.modules.staffing.models import PositionFill, StaffingPosition
    from app.modules.teams.models import RosterMember

    for demo_id, pid in world.projects.items():
        async with world.factory() as s:
            rows = (
                await s.execute(
                    select(StaffingPosition.role_code, RosterMember.display_name, RosterMember.site_role)
                    .join(PositionFill, PositionFill.position_id == StaffingPosition.id)
                    .join(RosterMember, RosterMember.id == PositionFill.roster_member_id)
                    .where(StaffingPosition.project_id == pid)
                )
            ).all()
        assert rows, demo_id
        wrong = [(role, name, site_role) for role, name, site_role in rows if role != site_role]
        assert wrong == [], (demo_id, wrong)


async def test_every_commitment_item_sits_on_a_cost_line(world: World) -> None:
    from app.modules.commitment_release.models import CommitmentItem

    for demo_id, pid in world.projects.items():
        async with world.factory() as s:
            rows = (
                await s.execute(
                    select(CommitmentItem.code, CommitmentItem.cost_line_id).where(CommitmentItem.project_id == pid)
                )
            ).all()
        assert rows, demo_id
        assert [code for code, line in rows if line is None] == [], demo_id


async def test_the_bound_works_package_shows_under_a_cost_group(world: World) -> None:
    pid = world.projects["residential-regensburg"]
    resp = await world.client.get(f"/api/v1/economics/projects/{pid}/cost-frame", headers=world.headers("admin"))
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    totals = body["totals"]
    assert totals["committed_available"] is True, totals
    per_group = sum((Decimal(r["committed"]) for r in body["lines"] if r["committed"] is not None), Decimal(0))
    assert per_group > 0, body["lines"]
    assert per_group == Decimal(totals["committed"]), totals
    assert Decimal(totals["committed_unassigned"]) == 0, totals
