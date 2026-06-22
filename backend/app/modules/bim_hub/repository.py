"""‌⁠‍BIM Hub data access layer.

All database queries for BIM models, elements, BOQ links, quantity maps,
and model diffs live here. No business logic - pure data access.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.sql_json import json_path_text
from app.modules.bim_hub.models import (
    NON_3D_MODEL_FORMATS,
    BIMElement,
    BIMFederation,
    BIMFederationModel,
    BIMModel,
    BIMModelDiff,
    BIMQuantityMap,
    BOQElementLink,
)


class BIMModelRepository:
    """‌⁠‍Data access for BIMModel."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, model_id: uuid.UUID) -> BIMModel | None:
        """‌⁠‍Get BIM model by ID."""
        return await self.session.get(BIMModel, model_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        include_non_3d: bool = False,
    ) -> tuple[list[BIMModel], int]:
        """List BIM models for a project with pagination.

        Elements are NOT loaded in list queries - use get() for a single model
        with elements when needed.

        By default 2D drawing formats (DWG/DXF/DGN) are excluded: they carry no
        3D mesh and belong to the dedicated DWG Takeoff module, never the BIM 3D
        Takeoff surface. Pass ``include_non_3d=True`` only for maintenance views
        that intentionally want every row (e.g. orphan cleanup).
        """
        base = select(BIMModel).where(BIMModel.project_id == project_id)

        if not include_non_3d:
            # Drop rows whose normalised format CONTAINS a 2D drawing token
            # (dwg/dxf/dgn). Substring matching (not exact) mirrors the Python
            # ``is_non_3d_format`` helper so values like "autocad_dwg" or
            # ".dwg" are excluded consistently across both layers. NULL / empty
            # formats are kept (legacy rows + generic uploads stay visible in
            # the 3D list).
            norm_fmt = func.lower(func.coalesce(BIMModel.model_format, ""))
            for token in NON_3D_MODEL_FORMATS:
                base = base.where(norm_fmt.notlike(f"%{token}%"))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.options(noload(BIMModel.elements)).order_by(BIMModel.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        models = list(result.scalars().all())
        return models, total

    async def create(self, model: BIMModel) -> BIMModel:
        """Insert a new BIM model."""
        self.session.add(model)
        await self.session.flush()
        return model

    async def update_fields(self, model_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a BIM model."""
        stmt = update(BIMModel).where(BIMModel.id == model_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, model_id: uuid.UUID) -> None:
        """Delete a BIM model and all its elements (via CASCADE)."""
        stmt = delete(BIMModel).where(BIMModel.id == model_id)
        await self.session.execute(stmt)

    async def cleanup_stale_processing(
        self,
        project_id: uuid.UUID,
        max_age_hours: int = 1,
    ) -> int:
        """Delete models stuck in 'processing' with 0 elements for longer than max_age_hours.

        Returns the number of models deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        # Find stale models
        find_stmt = select(BIMModel.id).where(
            BIMModel.project_id == project_id,
            BIMModel.status == "processing",
            BIMModel.element_count == 0,
            BIMModel.created_at < cutoff,
        )
        result = await self.session.execute(find_stmt)
        stale_ids = [row[0] for row in result.all()]
        if not stale_ids:
            return 0
        # Delete them
        del_stmt = delete(BIMModel).where(BIMModel.id.in_(stale_ids))
        await self.session.execute(del_stmt)
        return len(stale_ids)


class BIMElementRepository:
    """Data access for BIMElement."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, element_id: uuid.UUID) -> BIMElement | None:
        """Get BIM element by ID."""
        return await self.session.get(BIMElement, element_id)

    async def list_for_model(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BIMElement], int]:
        """List elements for a model with optional filters and pagination.

        BOQ links are NOT loaded in list queries to avoid N+1.
        """
        base = select(BIMElement).where(BIMElement.model_id == model_id)

        if element_type is not None:
            base = base.where(BIMElement.element_type == element_type)
        if storey is not None:
            base = base.where(BIMElement.storey == storey)
        if discipline is not None:
            base = base.where(BIMElement.discipline == discipline)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.options(noload(BIMElement.boq_links)).order_by(BIMElement.created_at).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        elements = list(result.scalars().all())
        return elements, total

    async def list_by_stable_ids(
        self,
        model_id: uuid.UUID,
        stable_ids: list[str],
    ) -> list[BIMElement]:
        """Get elements by their stable IDs within a model."""
        if not stable_ids:
            return []
        stmt = select(BIMElement).where(BIMElement.model_id == model_id, BIMElement.stable_id.in_(stable_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, element: BIMElement) -> BIMElement:
        """Insert a new BIM element."""
        self.session.add(element)
        await self.session.flush()
        return element

    async def bulk_create(self, elements: list[BIMElement]) -> list[BIMElement]:
        """Insert multiple elements in batches.

        Batching avoids SQLite's 999 bind-variable limit and keeps memory
        pressure manageable for large models (17 k+ elements).
        """
        BATCH_SIZE = 500
        created: list[BIMElement] = []
        for i in range(0, len(elements), BATCH_SIZE):
            batch = elements[i : i + BATCH_SIZE]
            self.session.add_all(batch)
            await self.session.flush()
            created.extend(batch)
        return created

    async def delete_all_for_model(self, model_id: uuid.UUID) -> int:
        """Delete all elements for a model. Returns count deleted."""
        count_stmt = select(func.count()).where(BIMElement.model_id == model_id)
        count = (await self.session.execute(count_stmt)).scalar_one()
        stmt = delete(BIMElement).where(BIMElement.model_id == model_id)
        await self.session.execute(stmt)
        return count

    # ── Asset Register (v2.3.0) ──────────────────────────────────────────

    async def list_tracked_assets_for_project(
        self,
        project_id: uuid.UUID,
        *,
        element_type: str | None = None,
        operational_status: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[BIMElement, BIMModel]], int]:
        """List tracked assets across every model in a project.

        Joins BIMElement → BIMModel so the API response can expose
        ``model_name`` and ``project_id`` without a second round-trip.
        Returns (element, model) tuples.

        Filters:
        - ``element_type``: exact match against BIMElement.element_type.
        - ``operational_status``: matches ``asset_info.operational_status``
          (JSON lookup, SQL-portable via ``JSON_EXTRACT``).
        - ``search``: case-insensitive LIKE across stable_id/name/
          serial_number/asset_tag/manufacturer. Tiny projects stay fast
          because the ``is_tracked_asset`` index narrows first.
        """
        base = (
            select(BIMElement, BIMModel)
            .join(BIMModel, BIMElement.model_id == BIMModel.id)
            .where(
                BIMModel.project_id == project_id,
                BIMElement.is_tracked_asset.is_(True),
            )
        )
        if element_type is not None:
            base = base.where(BIMElement.element_type == element_type)
        if operational_status is not None:
            # Portable JSON extraction - works on SQLite + Postgres.
            base = base.where(json_path_text(BIMElement.asset_info, "$.operational_status") == operational_status)
        if search is not None and search.strip():
            q = f"%{search.strip().lower()}%"
            base = base.where(
                func.lower(BIMElement.stable_id).like(q)
                | func.lower(func.coalesce(BIMElement.name, "")).like(q)
                | func.lower(
                    func.coalesce(
                        json_path_text(BIMElement.asset_info, "$.serial_number"),
                        "",
                    )
                ).like(q)
                | func.lower(
                    func.coalesce(
                        json_path_text(BIMElement.asset_info, "$.asset_tag"),
                        "",
                    )
                ).like(q)
                | func.lower(
                    func.coalesce(
                        json_path_text(BIMElement.asset_info, "$.manufacturer"),
                        "",
                    )
                ).like(q)
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.options(noload(BIMElement.boq_links))
            .order_by(BIMModel.name, BIMElement.stable_id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows: list[tuple[BIMElement, BIMModel]] = []
        for row in result.all():
            element, model = row
            rows.append((element, model))
        return rows, total

    async def update_asset_info(
        self,
        element_id: uuid.UUID,
        *,
        asset_info: dict,
        is_tracked_asset: bool | None = None,
    ) -> BIMElement | None:
        """Merge-update asset_info on an element.

        Behaviour:
        - ``asset_info`` is shallow-merged into the existing JSON (pass
          the new keys/values; pre-existing unrelated keys survive).
        - ``is_tracked_asset`` is flipped to ``True`` automatically when
          the merged ``asset_info`` ends up non-empty AND the caller did
          not pass an explicit override.
        - Returns the refreshed element, or ``None`` if not found.
        """
        element = await self.session.get(BIMElement, element_id)
        if element is None:
            return None

        merged = dict(element.asset_info or {})
        for key, value in (asset_info or {}).items():
            # Treat empty-string / None as "clear this field" - keeps
            # the JSON clean so AssetSummary columns don't show "" for
            # cleared keys.
            if value is None or (isinstance(value, str) and value == ""):
                merged.pop(key, None)
            else:
                merged[key] = value
        element.asset_info = merged

        if is_tracked_asset is not None:
            element.is_tracked_asset = is_tracked_asset
        elif merged:
            element.is_tracked_asset = True

        await self.session.flush()
        await self.session.refresh(element)
        return element


class BOQElementLinkRepository:
    """Data access for BOQElementLink."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, link_id: uuid.UUID) -> BOQElementLink | None:
        """Get a link by ID."""
        return await self.session.get(BOQElementLink, link_id)

    async def list_by_boq_position(
        self,
        boq_position_id: uuid.UUID,
    ) -> list[BOQElementLink]:
        """List all links for a BOQ position."""
        stmt = (
            select(BOQElementLink)
            .where(BOQElementLink.boq_position_id == boq_position_id)
            .order_by(BOQElementLink.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_bim_element(
        self,
        bim_element_id: uuid.UUID,
    ) -> list[BOQElementLink]:
        """List all links for a BIM element."""
        stmt = (
            select(BOQElementLink)
            .where(BOQElementLink.bim_element_id == bim_element_id)
            .order_by(BOQElementLink.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, link: BOQElementLink) -> BOQElementLink:
        """Insert a new BOQ-BIM link."""
        self.session.add(link)
        await self.session.flush()
        return link

    async def delete(self, link_id: uuid.UUID) -> None:
        """Delete a single link."""
        stmt = delete(BOQElementLink).where(BOQElementLink.id == link_id)
        await self.session.execute(stmt)


class BIMQuantityMapRepository:
    """Data access for BIMQuantityMap."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, map_id: uuid.UUID) -> BIMQuantityMap | None:
        """Get a quantity map rule by ID."""
        return await self.session.get(BIMQuantityMap, map_id)

    async def list_active(
        self,
        *,
        project_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
    ) -> list[BIMQuantityMap]:
        """List active quantity map rules, optionally filtered by project/org."""
        base = select(BIMQuantityMap).where(BIMQuantityMap.is_active.is_(True))

        if project_id is not None:
            base = base.where((BIMQuantityMap.project_id == project_id) | (BIMQuantityMap.project_id.is_(None)))
        if org_id is not None:
            base = base.where((BIMQuantityMap.org_id == org_id) | (BIMQuantityMap.org_id.is_(None)))

        stmt = base.order_by(BIMQuantityMap.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_scoped(
        self,
        *,
        project_ids: set[uuid.UUID] | None,
        include_global: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[BIMQuantityMap], int]:
        """List quantity map rules visible to the caller, paginated.

        Scoping rule (mirrors ``accessible_project_ids`` semantics):

        * ``project_ids is None`` -> no project filter (admin / unrestricted),
          every row is returned.
        * ``project_ids`` is a (possibly empty) set -> only rows whose
          ``project_id`` is in that set are returned, plus rows with
          ``project_id IS NULL`` when ``include_global`` is True (those are
          the intended global/org templates, not another tenant's data).

        This replaces the old ``list_all`` (no WHERE clause) which leaked
        every tenant's project-scoped mapping rules through the list endpoint.
        """
        base = select(BIMQuantityMap)

        if project_ids is not None:
            scoped = BIMQuantityMap.project_id.in_(project_ids)
            if include_global:
                base = base.where(scoped | BIMQuantityMap.project_id.is_(None))
            else:
                base = base.where(scoped)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BIMQuantityMap.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        maps = list(result.scalars().all())
        return maps, total

    async def create(self, qmap: BIMQuantityMap) -> BIMQuantityMap:
        """Insert a new quantity map rule."""
        self.session.add(qmap)
        await self.session.flush()
        return qmap

    async def update_fields(self, map_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a quantity map rule."""
        stmt = update(BIMQuantityMap).where(BIMQuantityMap.id == map_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, map_id: uuid.UUID) -> None:
        """Delete a quantity map rule."""
        stmt = delete(BIMQuantityMap).where(BIMQuantityMap.id == map_id)
        await self.session.execute(stmt)


class BIMModelDiffRepository:
    """Data access for BIMModelDiff."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, diff_id: uuid.UUID) -> BIMModelDiff | None:
        """Get a model diff by ID."""
        return await self.session.get(BIMModelDiff, diff_id)

    async def get_by_pair(
        self,
        old_model_id: uuid.UUID,
        new_model_id: uuid.UUID,
    ) -> BIMModelDiff | None:
        """Get diff by model pair."""
        stmt = select(BIMModelDiff).where(
            BIMModelDiff.old_model_id == old_model_id,
            BIMModelDiff.new_model_id == new_model_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, diff: BIMModelDiff) -> BIMModelDiff:
        """Insert a new model diff."""
        self.session.add(diff)
        await self.session.flush()
        return diff

    async def delete(self, diff_id: uuid.UUID) -> None:
        """Delete a model diff."""
        stmt = delete(BIMModelDiff).where(BIMModelDiff.id == diff_id)
        await self.session.execute(stmt)


# ── BIM Federation repository (v4.0 / Slice 1) ───────────────────────────────


class BIMFederationRepository:
    """‌⁠‍Data access for BIMFederation + BIMFederationModel."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, federation_id: uuid.UUID) -> BIMFederation | None:
        """Fetch a federation header (members loaded lazily via selectin)."""
        from sqlalchemy.orm import selectinload

        stmt = (
            select(BIMFederation).options(selectinload(BIMFederation.members)).where(BIMFederation.id == federation_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[BIMFederation], int]:
        """Paginated list of federations for a project (newest first)."""
        from sqlalchemy.orm import selectinload

        base = select(BIMFederation).where(BIMFederation.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = (
            base.options(selectinload(BIMFederation.members))
            .order_by(BIMFederation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, federation: BIMFederation) -> BIMFederation:
        """Insert a new federation."""
        self.session.add(federation)
        await self.session.flush()
        return federation

    async def update_fields(
        self,
        federation_id: uuid.UUID,
        **fields: object,
    ) -> None:
        """Update specific fields on a federation."""
        if not fields:
            return
        stmt = update(BIMFederation).where(BIMFederation.id == federation_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, federation_id: uuid.UUID) -> None:
        """Delete a federation (members cascade via FK)."""
        stmt = delete(BIMFederation).where(BIMFederation.id == federation_id)
        await self.session.execute(stmt)

    async def add_member(
        self,
        member: BIMFederationModel,
    ) -> BIMFederationModel:
        """Insert a new federation-model link row."""
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_member(
        self,
        member_id: uuid.UUID,
    ) -> BIMFederationModel | None:
        return await self.session.get(BIMFederationModel, member_id)

    async def remove_member(self, member_id: uuid.UUID) -> None:
        stmt = delete(BIMFederationModel).where(BIMFederationModel.id == member_id)
        await self.session.execute(stmt)

    async def find_member(
        self,
        federation_id: uuid.UUID,
        bim_model_id: uuid.UUID,
    ) -> BIMFederationModel | None:
        """Lookup the link row for a given (federation, bim_model) pair."""
        stmt = select(BIMFederationModel).where(
            BIMFederationModel.federation_id == federation_id,
            BIMFederationModel.bim_model_id == bim_model_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
