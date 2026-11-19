# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Legal entity and branch business logic.

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

from app.modules.legal_entities.models import Branch, LegalEntity, LegalEntityMember
from app.modules.legal_entities.repository import BranchRepository, LegalEntityRepository
from app.modules.legal_entities.tax_ids import clean
from app.modules.legal_entities.validators import (
    Issue,
    check_active_for_new_project,
    check_cross_entity,
    check_duplicate_code,
    check_site_entity,
    check_tax_ids,
    errors,
    validate_branch,
    validate_entity,
)
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


def _duplicate(code: str, *, site: bool = False) -> HTTPException:
    return _conflict(check_duplicate_code(code, taken=True, site=site)[0].message)


def _address(value: Any) -> dict[str, str] | None:
    if not value:
        return None
    cleaned = {k: str(v).strip() for k, v in dict(value).items() if v is not None and str(v).strip()}
    return cleaned or None


def _bank(value: Any) -> dict[str, str] | None:
    """A bank account with blanks dropped; the IBAN without spaces, upper-cased."""
    cleaned = _address(value)
    if cleaned and cleaned.get("iban"):
        cleaned["iban"] = cleaned["iban"].replace(" ", "").upper()
    return cleaned


def _entity_logo(value: Any) -> str | None:
    """A raster logo data URL, ``None`` to clear; anything else is refused."""
    if not value:
        return None
    from app.core.company_profile import accepted_logo

    logo = accepted_logo(value)
    if not logo or logo.startswith("data:image/svg"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The logo must be a PNG, JPEG or WebP image within the size limit",
        )
    return logo


#: Invoice statuses that mean the document has left the building.
_ISSUED_STATUSES = ("issued", "sent", "approved", "paid", "partially_paid", "overdue")


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
            raise _duplicate(data["code"])
        # The first company of an install is the default: nothing names one yet.
        first = not await self.entities.list(include_inactive=True)
        if data.get("is_default") or first:
            await self.entities.clear_default()
        entity = LegalEntity(
            code=data["code"],
            name=data["name"],
            country_code=data["country_code"],
            subdivision_code=data.get("subdivision_code"),
            functional_currency=data["functional_currency"],
            registration_number=data.get("registration_number"),
            tax_id=data.get("tax_id"),
            legal_name=(data.get("legal_name") or "").strip() or None,
            address=_address(data.get("address")),
            tax_ids=clean(data.get("tax_ids")),
            invoice_prefix=(data.get("invoice_prefix") or "").strip() or None,
            default_signatory=(data.get("default_signatory") or "").strip() or None,
            bank=_bank(data.get("bank")),
            logo_data_url=_entity_logo(data.get("logo_data_url")),
            is_default=bool(data.get("is_default")) or first,
            is_active=data.get("is_active", True),
            metadata_=dict(data.get("metadata") or {}),
        )
        return await self.entities.add(entity)

    def entity_warnings(self, entity: LegalEntity) -> list[Issue]:
        """Non-blocking findings on an entity as stored: tax id shapes the country data does not expect."""
        return check_tax_ids(entity.country_code, entity.tax_ids)

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
                raise _duplicate(merged["code"])
        if data.get("is_default") is False and entity.is_default:
            # Unsetting the only default would leave documents with no seller to fall back to.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Make another company the default instead of clearing this one.",
            )
        if data.get("is_default"):
            await self.entities.clear_default(except_id=entity.id)
        for field in ("code", "name", "country_code", "functional_currency", "is_default", "is_active"):
            if data.get(field) is not None:
                setattr(entity, field, data[field])
        for field in ("subdivision_code", "registration_number", "tax_id"):
            if field in data:
                setattr(entity, field, data[field])
        for field in ("legal_name", "invoice_prefix", "default_signatory"):
            if field in data:
                setattr(entity, field, (data[field] or "").strip() or None)
        if "bank" in data:
            entity.bank = _bank(data["bank"])
        if "logo_data_url" in data:
            entity.logo_data_url = _entity_logo(data["logo_data_url"])
        if "address" in data:
            entity.address = _address(data["address"])
        if data.get("tax_ids") is not None:
            entity.tax_ids = clean(data["tax_ids"])
        if data.get("metadata") is not None:
            entity.metadata_ = dict(data["metadata"])
        await self.session.flush()
        return entity

    async def delete_entity(self, entity_id: uuid.UUID) -> None:
        entity = await self.get_entity(entity_id)
        in_use = (await self.project_counts()).get(entity.id, 0)
        if in_use:
            raise _conflict(f"Legal entity {entity.code} owns {in_use} project(s); deactivate it instead.")
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
        self,
        project_id: uuid.UUID,
        entity_id: uuid.UUID | None,
        branch_id: uuid.UUID | None = None,
    ) -> tuple[LegalEntity | None, str, list[Issue]]:
        """Name the entity (and optionally the site) that owns a project, or clear it with None.

        Returns the entity that now answers, how, and the warnings of the move:
        ``entity.cross_entity_reference`` when invoices already issued under the
        old company stay behind.
        """
        project = await self._project(project_id)
        before, _ = await self.project_entity(project_id)
        if entity_id is not None and entity_id != project.legal_entity_id:
            entity = await self.get_entity(entity_id)
            _raise_on_errors(check_active_for_new_project(code=entity.code, is_active=entity.is_active))
        if branch_id is not None:
            branch = await self.branches.get(branch_id)
            if branch is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
            owner = entity_id
            if owner is None:
                default = await self.default_entity()
                owner = default.id if default is not None else None
            _raise_on_errors(check_site_entity(site_entity_id=branch.legal_entity_id, entity_id=owner))
        project.legal_entity_id = entity_id
        project.legal_entity_branch_id = branch_id
        await self.session.flush()
        entity, source = await self.project_entity(project_id)
        warnings: list[Issue] = []
        if before is not None and entity is not None and before.id != entity.id:
            if await self.issued_invoice_count(project_id):
                warnings = check_cross_entity([before.id, entity.id])
        return entity, source, warnings

    async def issued_invoice_count(self, project_id: uuid.UUID) -> int:
        """Outgoing invoices on the project that are past draft."""
        try:
            from app.modules.finance.models import Invoice
        except ImportError:
            return 0
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Invoice)
                .where(
                    Invoice.project_id == project_id,
                    Invoice.invoice_direction == "receivable",
                    Invoice.status.in_(_ISSUED_STATUSES),
                )
            )
            or 0
        )

    async def project_counts(self) -> dict[uuid.UUID, int]:
        """Live projects per entity; a project naming none counts for the default entity."""
        rows = (
            await self.session.execute(
                select(Project.legal_entity_id, func.count())
                .where(Project.status != "archived")
                .group_by(Project.legal_entity_id)
            )
        ).all()
        counts: dict[uuid.UUID, int] = {}
        unassigned = 0
        for entity_id, n in rows:
            if entity_id is None:
                unassigned += int(n)
            else:
                counts[entity_id] = counts.get(entity_id, 0) + int(n)
        if unassigned:
            default = await self.default_entity()
            if default is not None:
                counts[default.id] = counts.get(default.id, 0) + unassigned
        return counts

    async def member_counts(self) -> dict[uuid.UUID, int]:
        rows = (
            await self.session.execute(
                select(LegalEntityMember.legal_entity_id, func.count()).group_by(LegalEntityMember.legal_entity_id)
            )
        ).all()
        return {entity_id: int(n) for entity_id, n in rows}

    async def entities_with_own_settings(self) -> set[str]:
        """Ids (as text) of the entities that have their own e-invoice seller details."""
        try:
            from app.modules.finance.einvoice_settings_models import EInvoiceSettings
        except ImportError:
            return set()
        scopes = (
            await self.session.execute(select(EInvoiceSettings.scope).where(EInvoiceSettings.scope.like("entity:%")))
        ).scalars()
        return {scope.split(":", 1)[1] for scope in scopes}

    # ── Members ───────────────────────────────────────────────────────────

    async def list_members(self, entity_id: uuid.UUID) -> list[tuple[LegalEntityMember, Any]]:
        from app.modules.users.models import User

        await self.get_entity(entity_id)
        rows = (
            await self.session.execute(
                select(LegalEntityMember, User)
                .join(User, User.id == LegalEntityMember.user_id)
                .where(LegalEntityMember.legal_entity_id == entity_id)
                .order_by(User.full_name, User.email)
            )
        ).all()
        return [(m, u) for m, u in rows]

    async def any_members(self) -> bool:
        return (await self.session.scalar(select(func.count()).select_from(LegalEntityMember)) or 0) > 0

    async def add_member(self, entity_id: uuid.UUID, user_id: uuid.UUID, role: str) -> LegalEntityMember:
        from app.modules.users.models import User

        await self.get_entity(entity_id)
        if await self.session.get(User, user_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        existing = (
            await self.session.execute(
                select(LegalEntityMember).where(
                    LegalEntityMember.legal_entity_id == entity_id, LegalEntityMember.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.role = role
            await self.session.flush()
            return existing
        member = LegalEntityMember(legal_entity_id=entity_id, user_id=user_id, role=role)
        self.session.add(member)
        await self.session.flush()
        return member

    async def _member(self, entity_id: uuid.UUID, member_id: uuid.UUID) -> LegalEntityMember:
        member = await self.session.get(LegalEntityMember, member_id)
        if member is None or member.legal_entity_id != entity_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
        return member

    async def update_member(self, entity_id: uuid.UUID, member_id: uuid.UUID, role: str) -> LegalEntityMember:
        member = await self._member(entity_id, member_id)
        member.role = role
        await self.session.flush()
        return member

    async def remove_member(self, entity_id: uuid.UUID, member_id: uuid.UUID) -> None:
        await self.session.delete(await self._member(entity_id, member_id))
        await self.session.flush()

    async def my_entity_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.session.execute(
            select(LegalEntityMember.legal_entity_id).where(LegalEntityMember.user_id == user_id)
        )
        return list(rows.scalars().all())

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
            raise _duplicate(data["code"], site=True)
        branch = Branch(
            legal_entity_id=entity.id,
            code=data["code"],
            name=data["name"],
            country_code=country,
            subdivision_code=data.get("subdivision_code"),
            address=_address(data.get("address")),
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
                raise _duplicate(merged_code, site=True)
        for field in ("code", "name", "country_code", "is_active"):
            if data.get(field) is not None:
                setattr(branch, field, data[field])
        if "subdivision_code" in data:
            branch.subdivision_code = data["subdivision_code"]
        if "address" in data:
            branch.address = _address(data["address"])
        await self.session.flush()
        return branch, warnings

    async def delete_branch(self, entity_id: uuid.UUID, branch_id: uuid.UUID) -> None:
        entity = await self.get_entity(entity_id)
        await self.branches.delete(await self._get_branch(entity, branch_id))
        await self.session.refresh(entity, attribute_names=["branches"])
