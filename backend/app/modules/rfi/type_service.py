# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request type catalogue service: a project's types, presets, and the type a request resolves to.

A project's catalogue is its rows in ``oe_rfi_request_type`` plus, while it has
no RFI row of its own, the built-in RFI type, so a project that never opened
the catalogue keeps filing ``RFI-001`` exactly as before types existed.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rfi.models import RFIRequestType
from app.modules.rfi.repository import RequestTypeRepository
from app.modules.rfi.request_types import (
    DEFAULT_TYPE_CODE,
    RequestTypeSpec,
    builtin_default_type,
    catalogue_problems,
    get_preset,
)
from app.modules.rfi.schemas import RequestTypeCreate, RequestTypeUpdate

__all__ = ["BuiltinRequestTypes", "RequestTypeService", "spec_from_row"]


def spec_from_row(row: RFIRequestType) -> RequestTypeSpec:
    """The catalogue row as the pure spec every rule and the numbering read."""
    return RequestTypeSpec(
        id=row.id,
        code=row.code,
        number_prefix=row.number_prefix,
        number_digits=int(row.number_digits or 4),
        name_i18n=dict(row.name_i18n or {}),
        description_i18n=dict(row.description_i18n or {}),
        default_response_days=row.default_response_days,
        required_fields=tuple(row.required_fields or ()),
        default_route_id=row.default_route_id,
        is_active=bool(row.is_active),
        sort_order=int(row.sort_order or 0),
        preset_code=row.preset_code,
    )


def _unknown_type(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Request type '{code}' is not in this project's catalogue.",
    )


class BuiltinRequestTypes:
    """A catalogue that holds only the built-in RFI type.

    It is what an :class:`~app.modules.rfi.service.RFIService` resolves types
    against when it was built without a database session; the real service
    replaces it with :class:`RequestTypeService` in its constructor.
    """

    async def resolve(self, project_id: uuid.UUID, code: str, *, allow_inactive: bool = False) -> RequestTypeSpec:
        if code == DEFAULT_TYPE_CODE:
            return builtin_default_type()
        raise _unknown_type(code)

    async def catalogue(self, project_id: uuid.UUID) -> list[RequestTypeSpec]:
        return [builtin_default_type()]


class RequestTypeService:
    """Business logic for a project's request type catalogue."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RequestTypeRepository(session)

    # ── Reading ───────────────────────────────────────────────────────────

    async def catalogue(self, project_id: uuid.UUID) -> list[RequestTypeSpec]:
        """Every type of the project, the built-in RFI first when the project has no RFI row."""
        specs = [spec_from_row(row) for row in await self.repo.list_for_project(project_id)]
        if not any(spec.code == DEFAULT_TYPE_CODE for spec in specs):
            specs.insert(0, builtin_default_type())
        return specs

    async def resolve(self, project_id: uuid.UUID, code: str, *, allow_inactive: bool = False) -> RequestTypeSpec:
        """The type ``code`` names in this project; 422 when it is unknown or retired.

        ``allow_inactive`` is for requests that already exist: a retired type
        stops new requests, never the ones filed while it was active.
        """
        for spec in await self.catalogue(project_id):
            if spec.code == code:
                if not spec.is_active and not allow_inactive:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Request type '{code}' is retired; new requests cannot use it.",
                    )
                return spec
        raise _unknown_type(code)

    async def request_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        return await self.repo.request_counts(project_id)

    async def get_row(self, type_id: uuid.UUID) -> RFIRequestType:
        row = await self.repo.get(type_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request type not found")
        return row

    # ── Writing ───────────────────────────────────────────────────────────

    async def _check_route(self, project_id: uuid.UUID, route_id: uuid.UUID | None) -> None:
        """A default route must exist, sign off RFIs, and belong to this project or to none."""
        if route_id is None:
            return
        from app.modules.approval_routes.models import Route

        route = await self.session.get(Route, route_id)
        if route is None or route.target_kind != "rfi" or route.project_id not in (None, project_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The default approval route must be an RFI route of this project.",
            )

    def _refuse_problems(self, existing: list[RequestTypeSpec], candidate: RequestTypeSpec) -> None:
        """Run the catalogue rules over the catalogue with ``candidate`` in it; refuse what it breaks."""
        problems = [p for p in catalogue_problems([*existing, candidate]) if p.type_code == candidate.code]
        if not problems:
            return
        conflict = {"duplicate_code", "duplicate_prefix"}
        code = (
            status.HTTP_409_CONFLICT
            if any(p.code in conflict for p in problems)
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail="; ".join(p.detail for p in problems))

    async def create_type(self, data: RequestTypeCreate) -> RFIRequestType:
        """Add a type. A project's own RFI row replaces the built-in RFI type."""
        await self._check_route(data.project_id, data.default_route_id)
        existing = await self.catalogue(data.project_id)
        if data.code == DEFAULT_TYPE_CODE:
            # The built-in RFI is the slot this row takes over, not a rival.
            existing = [s for s in existing if not s.is_builtin]
        candidate = RequestTypeSpec(
            code=data.code,
            number_prefix=data.number_prefix,
            number_digits=data.number_digits,
            name_i18n=data.name_i18n,
            description_i18n=data.description_i18n,
            default_response_days=data.default_response_days,
            required_fields=tuple(data.required_fields),
            default_route_id=data.default_route_id,
            is_active=data.is_active,
            sort_order=data.sort_order,
        )
        self._refuse_problems(existing, candidate)
        row = RFIRequestType(
            project_id=data.project_id,
            code=data.code,
            name_i18n=data.name_i18n,
            description_i18n=data.description_i18n,
            number_prefix=data.number_prefix,
            number_digits=data.number_digits,
            default_response_days=data.default_response_days,
            required_fields=list(data.required_fields),
            default_route_id=data.default_route_id,
            is_active=data.is_active,
            sort_order=data.sort_order,
        )
        return await self.repo.add(row)

    async def update_type(self, row: RFIRequestType, data: RequestTypeUpdate) -> RFIRequestType:
        """Patch a type. Code and prefix stay: requests carry them already."""
        fields = data.model_dump(exclude_unset=True)
        if "default_route_id" in fields:
            await self._check_route(row.project_id, fields["default_route_id"])
        # ``None`` clears the nullable fields (SLA, default route) and is ignored
        # for the NOT NULL ones, so a client echoing a whole form never blanks a name.
        not_null = {"name_i18n", "description_i18n", "number_digits", "required_fields", "is_active", "sort_order"}
        for name, value in fields.items():
            if name in not_null and value is None:
                continue
            setattr(row, name, list(value) if name == "required_fields" else value)
        await self.session.flush()
        return row

    async def delete_type(self, row: RFIRequestType) -> None:
        """Remove a type no request uses; 409 for one in use (retire it instead)."""
        counts = await self.repo.request_counts(row.project_id)
        if counts.get(row.code):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Request type '{row.code}' is used by {counts[row.code]} request(s); "
                    "retire it (is_active = false) instead of deleting it."
                ),
            )
        await self.repo.delete(row)

    async def load_preset(self, project_id: uuid.UUID, preset_code: str) -> tuple[list[str], list[str]]:
        """Copy a shipped preset into the project; returns ``(created, skipped)`` type codes.

        A type whose code or prefix the project already has is skipped, so the
        project's own edits survive a second load and two presets that both
        carry RFI or Site Query load side by side.
        """
        try:
            preset = get_preset(preset_code)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found") from None
        rows = await self.repo.list_for_project(project_id)
        codes = {r.code for r in rows}
        prefixes = {r.number_prefix for r in rows}
        created: list[str] = []
        skipped: list[str] = []
        for spec in preset.types:
            if spec.code in codes or spec.number_prefix in prefixes:
                skipped.append(spec.code)
                continue
            await self.repo.add(
                RFIRequestType(
                    project_id=project_id,
                    code=spec.code,
                    name_i18n=dict(spec.name_i18n),
                    description_i18n=dict(spec.description_i18n),
                    number_prefix=spec.number_prefix,
                    number_digits=spec.number_digits,
                    default_response_days=spec.default_response_days,
                    required_fields=list(spec.required_fields),
                    is_active=True,
                    sort_order=spec.sort_order,
                    preset_code=preset.code,
                )
            )
            codes.add(spec.code)
            prefixes.add(spec.number_prefix)
            created.append(spec.code)
        return created, skipped
