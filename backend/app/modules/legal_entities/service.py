# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legal entity and branch business logic.

Two invariants the service holds that the table alone does not:

* **At most one default entity.** Marking an entity default clears the flag on
  every other one in the same transaction, so a reader asking "which company
  does this document belong to when nothing says" gets one answer.
* **Codes are unique.** An entity code across the install, a branch code
  within its entity. A clash is a 409 naming the code, not a database error.

Every write runs :mod:`app.modules.legal_entities.validators` on the row as it
would be stored, so an update is checked against the merged row rather than the
fields the patch happened to send.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.legal_entities.models import Branch, LegalEntity
from app.modules.legal_entities.repository import BranchRepository, LegalEntityRepository
from app.modules.legal_entities.validators import Issue, errors, validate_branch, validate_entity
from app.modules.projects.models import Project


def _raise_on_errors(issues: list[Issue]) -> list[Issue]:
    """Raise a 422 carrying every error; return the warnings otherwise."""
    found = errors(issues)
    if found:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"rule_id": i.rule_id, "field": i.field, "message": i.message} for i in found],
        )
    return [i for i in issues if i.severity == "warning"]


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


class LegalEntityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entities = LegalEntityRepository(session)
        self.branches = BranchRepository(session)

    # ── Entities ──────────────────────────────────────────────────────────

    async def list_entities(self, *, include_inactive: bool = False) -> list[LegalEntity]:
        return await self.entities.list(include_inactive=include_inactive)

    async def get_entity(self, entity_id: uuid.UUID) -> LegalEntity:
        entity = await self.entities.get(entity_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal entity not found")
        return entity

    async def default_entity(self) -> LegalEntity | None:
        """The entity a document falls back to when nothing names one, or None."""
        return await self.entities.get_default()

    async def create_entity(self, data: dict[str, Any]) -> LegalEntity:
        _raise_on_errors(
            validate_entity(
                code=data["code"],
                country_code=data["country_code"],
                subdivision_code=data.get("subdivision_code"),
                functional_currency=data["functional_currency"],
            )
        )
        if await self.entities.get_by_code(data["code"]) is not None:
            raise _conflict(f"A legal entity with code {data['code']} already exists.")
        if data.get("is_default"):
            await self.entities.clear_default()
        entity = LegalEntity(
            code=data["code"],
            name=data["name"],
            country_code=data["country_code"],
            subdivision_code=data.get("subdivision_code"),
            functional_currency=data["functional_currency"],
            registration_number=data.get("registration_number"),
            tax_id=data.get("tax_id"),
            is_default=bool(data.get("is_default")),
            is_active=data.get("is_active", True),
            metadata_=dict(data.get("metadata") or {}),
        )
        return await self.entities.add(entity)

    async def update_entity(self, entity_id: uuid.UUID, data: dict[str, Any]) -> LegalEntity:
        entity = await self.get_entity(entity_id)
        merged = {
            "code": data.get("code") or entity.code,
            "country_code": data.get("country_code") or entity.country_code,
            "subdivision_code": data.get("subdivision_code", entity.subdivision_code),
            "functional_currency": data.get("functional_currency") or entity.functional_currency,
        }
        _raise_on_errors(validate_entity(**merged))
        if merged["code"] != entity.code:
            clash = await self.entities.get_by_code(merged["code"])
            if clash is not None and clash.id != entity.id:
                raise _conflict(f"A legal entity with code {merged['code']} already exists.")
        if data.get("is_default"):
            await self.entities.clear_default(except_id=entity.id)
        for field in ("code", "name", "country_code", "functional_currency", "is_default", "is_active"):
            if data.get(field) is not None:
                setattr(entity, field, data[field])
        for field in ("subdivision_code", "registration_number", "tax_id"):
            if field in data:
                setattr(entity, field, data[field])
        if data.get("metadata") is not None:
            entity.metadata_ = dict(data["metadata"])
        await self.session.flush()
        return entity

    async def delete_entity(self, entity_id: uuid.UUID) -> None:
        entity = await self.get_entity(entity_id)
        in_use = await self.session.scalar(
            select(func.count()).select_from(Project).where(Project.legal_entity_id == entity.id)
        )
        if in_use:
            raise _conflict(f"Legal entity {entity.code} owns {in_use} project(s); move them first.")
        await self.entities.delete(entity)

    # ── Projects ──────────────────────────────────────────────────────────

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return project

    async def project_entity(self, project_id: uuid.UUID) -> tuple[LegalEntity | None, str]:
        """The entity that owns the project and whether it was named or fell back."""
        project = await self._project(project_id)
        if project.legal_entity_id is not None:
            entity = await self.entities.get(project.legal_entity_id)
            if entity is not None:
                return entity, "assigned"
        default = await self.default_entity()
        return default, "default" if default is not None else "none"

    async def assign_project(
        self, project_id: uuid.UUID, entity_id: uuid.UUID | None
    ) -> tuple[LegalEntity | None, str]:
        """Name the entity that owns a project, or clear it with None."""
        project = await self._project(project_id)
        if entity_id is not None:
            entity = await self.get_entity(entity_id)
            if not entity.is_active:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Legal entity {entity.code} is inactive and cannot take new projects.",
                )
        project.legal_entity_id = entity_id
        await self.session.flush()
        return await self.project_entity(project_id)

    # ── Branches ──────────────────────────────────────────────────────────

    async def _get_branch(self, entity: LegalEntity, branch_id: uuid.UUID) -> Branch:
        branch = await self.branches.get(branch_id)
        if branch is None or branch.legal_entity_id != entity.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")
        return branch

    async def create_branch(self, entity_id: uuid.UUID, data: dict[str, Any]) -> tuple[Branch, list[Issue]]:
        entity = await self.get_entity(entity_id)
        country = data.get("country_code") or entity.country_code
        warnings = _raise_on_errors(
            validate_branch(
                code=data["code"],
                country_code=country,
                subdivision_code=data.get("subdivision_code"),
                entity_country_code=entity.country_code,
            )
        )
        if await self.branches.get_by_code(entity.id, data["code"]) is not None:
            raise _conflict(f"Entity {entity.code} already has a branch with code {data['code']}.")
        branch = Branch(
            legal_entity_id=entity.id,
            code=data["code"],
            name=data["name"],
            country_code=country,
            subdivision_code=data.get("subdivision_code"),
            is_active=data.get("is_active", True),
        )
        await self.branches.add(branch)
        await self.session.refresh(entity, attribute_names=["branches"])
        return branch, warnings

    async def update_branch(
        self, entity_id: uuid.UUID, branch_id: uuid.UUID, data: dict[str, Any]
    ) -> tuple[Branch, list[Issue]]:
        entity = await self.get_entity(entity_id)
        branch = await self._get_branch(entity, branch_id)
        merged_code = data.get("code") or branch.code
        merged_country = data.get("country_code") or branch.country_code
        warnings = _raise_on_errors(
            validate_branch(
                code=merged_code,
                country_code=merged_country,
                subdivision_code=data.get("subdivision_code", branch.subdivision_code),
                entity_country_code=entity.country_code,
            )
        )
        if merged_code != branch.code:
            clash = await self.branches.get_by_code(entity.id, merged_code)
            if clash is not None and clash.id != branch.id:
                raise _conflict(f"Entity {entity.code} already has a branch with code {merged_code}.")
        for field in ("code", "name", "country_code", "is_active"):
            if data.get(field) is not None:
                setattr(branch, field, data[field])
        if "subdivision_code" in data:
            branch.subdivision_code = data["subdivision_code"]
        await self.session.flush()
        return branch, warnings

    async def delete_branch(self, entity_id: uuid.UUID, branch_id: uuid.UUID) -> None:
        entity = await self.get_entity(entity_id)
        await self.branches.delete(await self._get_branch(entity, branch_id))
        await self.session.refresh(entity, attribute_names=["branches"])
