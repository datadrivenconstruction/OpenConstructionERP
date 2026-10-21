# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A PATCH of metadata merges keys; tags survive and can be set explicitly."""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assemblies.schemas import AssemblyCreate, AssemblyUpdate
from app.modules.assemblies.service import AssemblyService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _make(service: AssemblyService):
    return await service.create_assembly(
        AssemblyCreate(code=f"A-{uuid.uuid4().hex[:6]}", name="Wall", unit="m2", metadata={"tags": ["za"], "x": 1}),
        owner_id=str(uuid.uuid4()),
    )


async def test_other_key_patch_keeps_tags(session: AsyncSession) -> None:
    service = AssemblyService(session)
    asm = await _make(service)
    updated = await service.update_assembly(asm.id, AssemblyUpdate(metadata={"note": "hi"}))
    assert updated.metadata_ == {"tags": ["za"], "x": 1, "note": "hi"}


async def test_null_deletes_a_key(session: AsyncSession) -> None:
    service = AssemblyService(session)
    asm = await _make(service)
    updated = await service.update_assembly(asm.id, AssemblyUpdate(metadata={"x": None}))
    assert updated.metadata_ == {"tags": ["za"]}


async def test_tags_field_replaces_and_normalises(session: AsyncSession) -> None:
    service = AssemblyService(session)
    asm = await _make(service)
    updated = await service.update_assembly(asm.id, AssemblyUpdate(tags=[" Roads ", "roads", "", "ZA"]))
    assert updated.metadata_["tags"] == ["roads", "za"]
    assert updated.metadata_["x"] == 1


async def test_tags_endpoint_path_still_normalises(session: AsyncSession) -> None:
    service = AssemblyService(session)
    asm = await _make(service)
    updated = await service.update_tags(asm.id, [" A ", "a", "B"])
    assert updated.metadata_["tags"] == ["a", "b"]
