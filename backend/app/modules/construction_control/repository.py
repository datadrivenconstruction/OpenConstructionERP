# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control data access layer."""

import uuid

from sqlalchemy import Integer as SAInteger
from sqlalchemy import cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement, ColumnElement

from app.modules.construction_control.models import (
    AcceptanceCriterion,
    AsBuiltRecord,
    ElementRef,
    HandoverPackage,
    HoldGate,
    Inspection,
    MaterialRecord,
    TestResult,
)

# Number-allocation retry cap; a couple of retries cover any realistic concurrency,
# the cap stops a pathological hot loop (same backstop the NCR repository uses).
_NUMBER_RETRY_LIMIT = 5


class CriterionRepository:
    """Data access for acceptance criteria."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, criterion_id: uuid.UUID) -> AcceptanceCriterion | None:
        return await self.session.get(AcceptanceCriterion, criterion_id)

    async def create(self, criterion: AcceptanceCriterion) -> AcceptanceCriterion:
        self.session.add(criterion)
        await self.session.flush()
        return criterion

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[AcceptanceCriterion], int]:
        base = select(AcceptanceCriterion).where(AcceptanceCriterion.project_id == project_id)
        if category is not None:
            base = base.where(AcceptanceCriterion.category == category)
        if is_active is not None:
            base = base.where(AcceptanceCriterion.is_active == is_active)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(AcceptanceCriterion.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_fields(self, criterion_id: uuid.UUID, **fields: object) -> None:
        await self.session.execute(
            update(AcceptanceCriterion).where(AcceptanceCriterion.id == criterion_id).values(**fields)
        )
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(AcceptanceCriterion, criterion_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, criterion_id: uuid.UUID) -> None:
        criterion = await self.get_by_id(criterion_id)
        if criterion is not None:
            await self.session.delete(criterion)
            await self.session.flush()


class InspectionRepository:
    """Data access for inspections, with collision-safe per-project numbering."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, inspection_id: uuid.UUID) -> Inspection | None:
        return await self.session.get(Inspection, inspection_id)

    async def next_inspection_number(self, project_id: uuid.UUID) -> str:
        """Next ``INS-NNN`` from MAX(suffix)+1.

        Only rows matching the canonical ``INS-<digits>`` shape are considered, so a
        legacy or externally-numbered row never breaks the integer cast (PostgreSQL
        casts non-numeric text strictly, unlike SQLite).
        """
        stmt = (
            select(func.coalesce(func.max(cast(func.substr(Inspection.inspection_number, 5), SAInteger)), 0))
            .where(Inspection.project_id == project_id)
            .where(Inspection.inspection_number.regexp_match("^INS-[0-9]+$"))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"INS-{max_num + 1:03d}"

    async def create(self, inspection: Inspection) -> Inspection:
        """Insert an inspection, deriving ``inspection_number`` with a retry on collision.

        MAX(suffix)+1 can race two concurrent creates onto the same number; the
        per-project unique constraint turns that into an IntegrityError which we
        roll back via savepoint and retry.
        """
        project_id = inspection.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            inspection.inspection_number = await self.next_inspection_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(inspection)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return inspection
        raise RuntimeError(f"Could not allocate a unique inspection number for project {project_id}")

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        inspection_type: str | None = None,
        status: str | None = None,
        party_role: str | None = None,
    ) -> tuple[list[Inspection], int]:
        base = select(Inspection).where(Inspection.project_id == project_id)
        if inspection_type is not None:
            base = base.where(Inspection.inspection_type == inspection_type)
        if status is not None:
            base = base.where(Inspection.status == status)
        if party_role is not None:
            base = base.where(Inspection.party_role == party_role)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(Inspection.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_fields(self, inspection_id: uuid.UUID, **fields: object) -> None:
        await self.session.execute(update(Inspection).where(Inspection.id == inspection_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(Inspection, inspection_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, inspection_id: uuid.UUID) -> None:
        inspection = await self.get_by_id(inspection_id)
        if inspection is not None:
            await self.session.delete(inspection)
            await self.session.flush()


class ElementRefRepository:
    """Data access for the shared Universal Element Reference table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, ref: ElementRef) -> ElementRef:
        self.session.add(ref)
        await self.session.flush()
        return ref

    async def list_for_owner(self, owner_type: str, owner_id: str) -> list[ElementRef]:
        result = await self.session.execute(
            select(ElementRef)
            .where(ElementRef.owner_type == owner_type)
            .where(ElementRef.owner_id == owner_id)
            .order_by(ElementRef.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_for_owners(self, owner_type: str, owner_ids: list[str]) -> dict[str, list[ElementRef]]:
        """Batch-load element refs for many owners (avoids an N+1 over a list page)."""
        grouped: dict[str, list[ElementRef]] = {oid: [] for oid in owner_ids}
        if not owner_ids:
            return grouped
        result = await self.session.execute(
            select(ElementRef)
            .where(ElementRef.owner_type == owner_type)
            .where(ElementRef.owner_id.in_(owner_ids))
            .order_by(ElementRef.created_at.asc())
        )
        for ref in result.scalars().all():
            grouped.setdefault(ref.owner_id, []).append(ref)
        return grouped

    async def delete_for_owner(self, owner_type: str, owner_id: str) -> None:
        for ref in await self.list_for_owner(owner_type, owner_id):
            await self.session.delete(ref)
        await self.session.flush()


class MaterialRecordRepository:
    """Data access for material records, with collision-safe per-project numbering."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, material_id: uuid.UUID) -> MaterialRecord | None:
        return await self.session.get(MaterialRecord, material_id)

    async def next_record_number(self, project_id: uuid.UUID) -> str:
        """Next ``MAT-NNN`` from MAX(suffix)+1 (only canonical ``MAT-<digits>`` rows)."""
        stmt = (
            select(func.coalesce(func.max(cast(func.substr(MaterialRecord.record_number, 5), SAInteger)), 0))
            .where(MaterialRecord.project_id == project_id)
            .where(MaterialRecord.record_number.regexp_match("^MAT-[0-9]+$"))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"MAT-{max_num + 1:03d}"

    async def create(self, material: MaterialRecord) -> MaterialRecord:
        """Insert a material record, deriving ``record_number`` with a retry on collision."""
        project_id = material.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            material.record_number = await self.next_record_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(material)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return material
        raise RuntimeError(f"Could not allocate a unique material number for project {project_id}")

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        material_type: str | None = None,
        gr_id: str | None = None,
    ) -> tuple[list[MaterialRecord], int]:
        base = select(MaterialRecord).where(MaterialRecord.project_id == project_id)
        if status is not None:
            base = base.where(MaterialRecord.status == status)
        if material_type is not None:
            base = base.where(MaterialRecord.material_type == material_type)
        if gr_id is not None:
            base = base.where(MaterialRecord.gr_id == gr_id)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(MaterialRecord.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_fields(self, material_id: uuid.UUID, **fields: object) -> None:
        await self.session.execute(update(MaterialRecord).where(MaterialRecord.id == material_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(MaterialRecord, material_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, material_id: uuid.UUID) -> None:
        material = await self.get_by_id(material_id)
        if material is not None:
            await self.session.delete(material)
            await self.session.flush()


class TestResultRepository:
    """Data access for test results, with collision-safe per-project numbering."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, result_id: uuid.UUID) -> TestResult | None:
        return await self.session.get(TestResult, result_id)

    async def next_result_number(self, project_id: uuid.UUID) -> str:
        """Next ``TST-NNN`` from MAX(suffix)+1 (only canonical ``TST-<digits>`` rows)."""
        stmt = (
            select(func.coalesce(func.max(cast(func.substr(TestResult.result_number, 5), SAInteger)), 0))
            .where(TestResult.project_id == project_id)
            .where(TestResult.result_number.regexp_match("^TST-[0-9]+$"))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"TST-{max_num + 1:03d}"

    async def create(self, test: TestResult) -> TestResult:
        """Insert a test result, deriving ``result_number`` with a retry on collision."""
        project_id = test.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            test.result_number = await self.next_result_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(test)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return test
        raise RuntimeError(f"Could not allocate a unique test-result number for project {project_id}")

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        result: str | None = None,
        material_record_id: str | None = None,
    ) -> tuple[list[TestResult], int]:
        base = select(TestResult).where(TestResult.project_id == project_id)
        if status is not None:
            base = base.where(TestResult.status == status)
        if result is not None:
            base = base.where(TestResult.result == result)
        if material_record_id is not None:
            base = base.where(TestResult.material_record_id == material_record_id)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(TestResult.created_at.desc()).offset(offset).limit(limit)
        result_set = await self.session.execute(stmt)
        return list(result_set.scalars().all()), total

    async def update_fields(self, result_id: uuid.UUID, **fields: object) -> None:
        await self.session.execute(update(TestResult).where(TestResult.id == result_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(TestResult, result_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, result_id: uuid.UUID) -> None:
        test = await self.get_by_id(result_id)
        if test is not None:
            await self.session.delete(test)
            await self.session.flush()


class AsBuiltRecordRepository:
    """Data access for as-built records, with collision-safe per-project numbering."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, record_id: uuid.UUID) -> AsBuiltRecord | None:
        return await self.session.get(AsBuiltRecord, record_id)

    async def next_record_number(self, project_id: uuid.UUID) -> str:
        """Next ``ASB-NNN`` from MAX(suffix)+1 (only canonical ``ASB-<digits>`` rows)."""
        stmt = (
            select(func.coalesce(func.max(cast(func.substr(AsBuiltRecord.record_number, 5), SAInteger)), 0))
            .where(AsBuiltRecord.project_id == project_id)
            .where(AsBuiltRecord.record_number.regexp_match("^ASB-[0-9]+$"))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"ASB-{max_num + 1:03d}"

    async def create(self, record: AsBuiltRecord) -> AsBuiltRecord:
        """Insert an as-built record, deriving ``record_number`` with a retry on collision."""
        project_id = record.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            record.record_number = await self.next_record_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(record)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return record
        raise RuntimeError(f"Could not allocate a unique as-built number for project {project_id}")

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        discipline: str | None = None,
        source_kind: str | None = None,
    ) -> tuple[list[AsBuiltRecord], int]:
        base = select(AsBuiltRecord).where(AsBuiltRecord.project_id == project_id)
        if status is not None:
            base = base.where(AsBuiltRecord.status == status)
        if discipline is not None:
            base = base.where(AsBuiltRecord.discipline == discipline)
        if source_kind is not None:
            base = base.where(AsBuiltRecord.source_kind == source_kind)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(AsBuiltRecord.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_fields(self, record_id: uuid.UUID, **fields: object) -> None:
        await self.session.execute(update(AsBuiltRecord).where(AsBuiltRecord.id == record_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(AsBuiltRecord, record_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, record_id: uuid.UUID) -> None:
        record = await self.get_by_id(record_id)
        if record is not None:
            await self.session.delete(record)
            await self.session.flush()


class HoldGateRepository:
    """Data access for hold/witness/surveillance/review gates, with per-project numbering."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, gate_id: uuid.UUID) -> HoldGate | None:
        return await self.session.get(HoldGate, gate_id)

    async def next_gate_number(self, project_id: uuid.UUID) -> str:
        """Next ``GATE-NNN`` from MAX(suffix)+1 (only canonical ``GATE-<digits>`` rows).

        The numeric suffix starts at offset 6 (``len("GATE-") + 1``), unlike the
        4-character prefixes elsewhere in the module.
        """
        stmt = (
            select(func.coalesce(func.max(cast(func.substr(HoldGate.gate_number, 6), SAInteger)), 0))
            .where(HoldGate.project_id == project_id)
            .where(HoldGate.gate_number.regexp_match("^GATE-[0-9]+$"))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"GATE-{max_num + 1:03d}"

    async def create(self, gate: HoldGate) -> HoldGate:
        """Insert a gate, deriving ``gate_number`` with a retry on collision."""
        project_id = gate.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            gate.gate_number = await self.next_gate_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(gate)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return gate
        raise RuntimeError(f"Could not allocate a unique gate number for project {project_id}")

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        point_type: str | None = None,
        attached_kind: str | None = None,
        attached_id: str | None = None,
    ) -> tuple[list[HoldGate], int]:
        base = select(HoldGate).where(HoldGate.project_id == project_id)
        if status is not None:
            base = base.where(HoldGate.status == status)
        if point_type is not None:
            base = base.where(HoldGate.point_type == point_type)
        if attached_kind is not None:
            base = base.where(HoldGate.attached_kind == attached_kind)
        if attached_id is not None:
            base = base.where(HoldGate.attached_id == attached_id)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(HoldGate.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_blocking(self, project_id: uuid.UUID, attached_kind: str, attached_id: str) -> list[HoldGate]:
        """Pending, blocking gates attached to one entity - the enforcement query."""
        stmt = (
            select(HoldGate)
            .where(HoldGate.project_id == project_id)
            .where(HoldGate.attached_kind == attached_kind)
            .where(HoldGate.attached_id == attached_id)
            .where(HoldGate.blocks_progress.is_(True))
            .where(HoldGate.status == "pending")
            .order_by(HoldGate.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_unreleased_holds(self, project_id: uuid.UUID) -> int:
        """Count pending, blocking gates across the whole project (Pillar-4 gate input)."""
        stmt = (
            select(func.count())
            .select_from(HoldGate)
            .where(HoldGate.project_id == project_id)
            .where(HoldGate.blocks_progress.is_(True))
            .where(HoldGate.status == "pending")
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def update_fields(self, gate_id: uuid.UUID, **fields: object) -> None:
        await self.session.execute(update(HoldGate).where(HoldGate.id == gate_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(HoldGate, gate_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, gate_id: uuid.UUID) -> None:
        gate = await self.get_by_id(gate_id)
        if gate is not None:
            await self.session.delete(gate)
            await self.session.flush()


class HandoverPackageRepository:
    """Data access for handover packages, with collision-safe per-project numbering."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, package_id: uuid.UUID) -> HandoverPackage | None:
        return await self.session.get(HandoverPackage, package_id)

    async def next_package_number(self, project_id: uuid.UUID) -> str:
        """Next ``HOP-NNN`` from MAX(suffix)+1 (only canonical ``HOP-<digits>`` rows)."""
        stmt = (
            select(func.coalesce(func.max(cast(func.substr(HandoverPackage.package_number, 5), SAInteger)), 0))
            .where(HandoverPackage.project_id == project_id)
            .where(HandoverPackage.package_number.regexp_match("^HOP-[0-9]+$"))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"HOP-{max_num + 1:03d}"

    async def create(self, package: HandoverPackage) -> HandoverPackage:
        """Insert a handover package, deriving ``package_number`` with a retry on collision."""
        project_id = package.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            package.package_number = await self.next_package_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(package)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return package
        raise RuntimeError(f"Could not allocate a unique handover-package number for project {project_id}")

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        completion_regime: str | None = None,
        completion_type: str | None = None,
    ) -> tuple[list[HandoverPackage], int]:
        base = select(HandoverPackage).where(HandoverPackage.project_id == project_id)
        if status is not None:
            base = base.where(HandoverPackage.status == status)
        if completion_regime is not None:
            base = base.where(HandoverPackage.completion_regime == completion_regime)
        if completion_type is not None:
            base = base.where(HandoverPackage.completion_type == completion_type)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(HandoverPackage.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_fields(self, package_id: uuid.UUID, **fields: object) -> None:
        await self.session.execute(update(HandoverPackage).where(HandoverPackage.id == package_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(HandoverPackage, package_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, package_id: uuid.UUID) -> None:
        package = await self.get_by_id(package_id)
        if package is not None:
            await self.session.delete(package)
            await self.session.flush()


class ReferenceCountRepository:
    """Counts of the records that point at a row, for the deletion guards.

    Every cross-record link in this module lives in a ``String(36)`` column
    holding the referenced id as text, never a database foreign key. So each
    count compares against ``str(row_id)``: handing SQLAlchemy a raw ``UUID``
    against a ``VARCHAR`` column matches nothing on PostgreSQL, which would make
    a guard silently pass and a delete go through unrefused.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _count(self, model: type, column: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(model).where(column)
        return int((await self.session.execute(stmt)).scalar_one())

    # -- Acceptance criterion holders ----------------------------------------

    async def count_inspections_using_criterion(self, criterion_id: uuid.UUID) -> int:
        return await self._count(Inspection, Inspection.criterion_id == str(criterion_id))

    async def count_materials_using_criterion(self, criterion_id: uuid.UUID) -> int:
        return await self._count(MaterialRecord, MaterialRecord.criterion_id == str(criterion_id))

    async def count_tests_using_criterion(self, criterion_id: uuid.UUID) -> int:
        return await self._count(TestResult, TestResult.criterion_id == str(criterion_id))

    async def count_asbuilt_using_criterion(self, criterion_id: uuid.UUID) -> int:
        return await self._count(AsBuiltRecord, AsBuiltRecord.criterion_id == str(criterion_id))

    async def count_gates_using_criterion(self, criterion_id: uuid.UUID) -> int:
        return await self._count(HoldGate, HoldGate.criterion_id == str(criterion_id))

    # -- Inspection holders ---------------------------------------------------

    async def count_tests_on_inspection(self, inspection_id: uuid.UUID) -> int:
        return await self._count(TestResult, TestResult.inspection_id == str(inspection_id))

    async def count_gates_on_inspection(self, inspection_id: uuid.UUID) -> int:
        """Gates naming this inspection through either of the two columns that can.

        A gate names an inspection as its verification source in
        ``inspection_id`` and, independently, as the thing it is attached to in
        ``attached_kind`` / ``attached_id``. Counting only the first leaves the
        second kind of holder invisible, so the two are unioned per gate id
        rather than added, which would double-count a gate that does both.
        """
        ref = str(inspection_id)
        stmt = (
            select(func.count(func.distinct(HoldGate.id)))
            .select_from(HoldGate)
            .where(
                (HoldGate.inspection_id == ref)
                | ((HoldGate.attached_kind == "inspection") & (HoldGate.attached_id == ref)),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_ncrs_on_inspection(self, inspection_id: uuid.UUID) -> int:
        """Non-conformance reports raised against this inspection.

        Lazy-imported so construction control keeps working in a deployment that
        does not have the NCR module. The reachable case is the module missing
        from disk rather than disabled: ``oe_ncr`` is core and the loader refuses
        to disable it, but nothing enforces ``depends`` at startup, so this module
        boots without it.

        The catch is narrowed to that one case on purpose. A blanket
        ``except ImportError`` also swallows an NCR module that is present but
        broken, and a broken module would then report no holders and let
        evidence be deleted with nothing said. So only ``app.modules.ncr`` (or a
        submodule of it) going missing returns zero; any other name in the
        traceback is somebody else's import failing inside a module that is
        installed, and it is re-raised. A module that imports cleanly but no
        longer defines ``NCR`` raises plain ``ImportError`` rather than
        ``ModuleNotFoundError`` and propagates for the same reason.

        Be precise about what the zero claims. It means no NCR can be COUNTED,
        not that none exists: rows written while the module was present outlive
        its removal in the database, so the zero is sound for a deployment that
        never had the NCR module and optimistic for one that lost it.

        Zero is still the right answer here, because the alternative is worse.
        This is a read-only count feeding a delete guard, so raising instead
        would turn every delete in the module into a 500 the moment the NCR
        module went missing, which fails closed in the wrong direction. The
        trade is a narrow stale-count risk against breaking deletion outright.

        That trade holds only while the write path refuses to degrade.
        ``ncr_bridge.raise_ncr`` and ``ConstructionControlService._raise_ncr_for_failure``
        raise rather than returning ``None`` when the NCR module is gone, which is
        what keeps the window narrow: nothing new can be written that this count
        would then miss. If either is ever made to degrade, this zero stops being
        a narrow risk and becomes a hole, and has to be revisited with it.
        """
        try:
            from app.modules.ncr.models import NCR
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            if missing != "app.modules.ncr" and not missing.startswith("app.modules.ncr."):
                raise
            return 0
        return await self._count(NCR, NCR.linked_inspection_id == str(inspection_id))

    # -- Material record holders ----------------------------------------------

    async def count_tests_on_material(self, material_id: uuid.UUID) -> int:
        return await self._count(TestResult, TestResult.material_record_id == str(material_id))

    # -- Handover package holders ---------------------------------------------

    async def count_gates_on_handover(self, package_id: uuid.UUID) -> int:
        return await self._count(
            HoldGate,
            (HoldGate.attached_kind == "handover_package") & (HoldGate.attached_id == str(package_id)),
        )
