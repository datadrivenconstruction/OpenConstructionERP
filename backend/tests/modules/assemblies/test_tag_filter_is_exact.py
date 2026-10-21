# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The tag filter matches whole tags, case-insensitively, not substrings."""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assemblies.models import Assembly
from app.modules.assemblies.repository import AssemblyRepository, AssemblyTemplateRepository
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def test_assembly_tag_filter_is_exact(session: AsyncSession) -> None:
    owner = uuid.uuid4()
    for code, tags in (("T-AB", ["ab"]), ("T-ABC", ["abc"]), ("T-MIX", ["Ab", "x"])):
        session.add(
            Assembly(
                code=f"{code}-{owner.hex[:6]}",
                name=code,
                unit="m2",
                total_rate="0",
                currency="EUR",
                bid_factor="1",
                owner_id=owner,
                metadata_={"tags": tags, "other": "abc"},
            )
        )
    await session.flush()
    rows, total = await AssemblyRepository(session).list_all(tag="ab", owner_id=owner)
    assert total == 2
    assert {r.name for r in rows} == {"T-AB", "T-MIX"}


async def test_template_tag_filter_is_exact(session: AsyncSession) -> None:
    repo = AssemblyTemplateRepository(session)
    tag = f"zz{uuid.uuid4().hex[:6]}"
    for name, tags in ((f"{tag}-a", [tag]), (f"{tag}-b", [tag + "x"]), (f"{tag}-c", [tag.upper(), "q"])):
        await repo.upsert_by_name(
            {"name": name, "category": "test", "unit": "m2", "components": [], "tags": tags, "classification": {}}
        )
    rows, total = await repo.list_all(tag=tag)
    assert total == 2
    assert {r.name for r in rows} == {f"{tag}-a", f"{tag}-c"}
