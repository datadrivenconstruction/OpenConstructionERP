# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Two owners can each hold the same demo; installing it again never touches the other owner's rows.

The assemblies, equipment, resources, contracts and the demo subcontractor sit in registries whose
``code`` is globally unique and which carry no project key. The installer used to clear them by code
prefix, so a second owner's install deleted the first owner's rows.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.demo_projects import install_demo_project

_DEMO = "consultancy-riyadh"


async def _user(session, label: str) -> uuid.UUID:
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name=label,
        role="manager",
        locale="en",
        is_active=True,
        metadata_={},
    )
    session.add(user)
    await session.flush()
    return user.id


async def _footprint(session, project_id: uuid.UUID) -> dict[str, int]:
    from app.modules.assemblies.models import Assembly
    from app.modules.contracts.models import Contract
    from app.modules.equipment.models import Equipment, EquipmentRental
    from app.modules.resources.models import Resource
    from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor

    async def count(stmt) -> int:
        return (await session.execute(stmt)).scalar_one()

    return {
        "assemblies": await count(select(func.count()).select_from(Assembly).where(Assembly.project_id == project_id)),
        "contracts": await count(select(func.count()).select_from(Contract).where(Contract.project_id == project_id)),
        "resources": await count(
            select(func.count()).select_from(Resource).where(Resource.home_project_id == project_id)
        ),
        "equipment": await count(
            select(func.count(func.distinct(Equipment.id)))
            .select_from(Equipment)
            .join(EquipmentRental, EquipmentRental.equipment_id == Equipment.id)
            .where(EquipmentRental.project_id == project_id)
        ),
        "subcontractors": await count(
            select(func.count(func.distinct(Subcontractor.id)))
            .select_from(Subcontractor)
            .join(SubcontractAgreement, SubcontractAgreement.subcontractor_id == Subcontractor.id)
            .where(SubcontractAgreement.project_id == project_id)
        ),
    }


async def test_second_owner_does_not_delete_the_first_owners_demo_rows() -> None:
    from tests._pg import transactional_session

    async with transactional_session() as session:
        first_owner = await _user(session, "first")
        second_owner = await _user(session, "second")

        first = await install_demo_project(session, _DEMO, owner_id=first_owner)
        first_pid = uuid.UUID(first["project_id"])
        before = await _footprint(session, first_pid)
        assert all(before.values()), before

        second = await install_demo_project(session, _DEMO, owner_id=second_owner)
        second_pid = uuid.UUID(second["project_id"])

        assert second_pid != first_pid
        assert await _footprint(session, first_pid) == before
        assert await _footprint(session, second_pid) == before


async def test_reinstall_replaces_only_the_installing_owners_rows() -> None:
    from tests._pg import transactional_session

    async with transactional_session() as session:
        first_owner = await _user(session, "first")
        second_owner = await _user(session, "second")

        first = await install_demo_project(session, _DEMO, owner_id=first_owner)
        first_pid = uuid.UUID(first["project_id"])
        before = await _footprint(session, first_pid)
        await install_demo_project(session, _DEMO, owner_id=second_owner)

        again = await install_demo_project(session, _DEMO, owner_id=second_owner, force_reinstall=True)
        assert await _footprint(session, first_pid) == before
        assert await _footprint(session, uuid.UUID(again["project_id"])) == before
