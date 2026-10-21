# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assembly data access layer.

All database queries for assemblies and components live here.
No business logic - pure data access.
"""

import logging
import uuid

from sqlalchemy import String, Text, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.core.text_search import free_text_filter
from app.modules.assemblies.models import Assembly, AssemblyTemplate, Component

logger = logging.getLogger(__name__)


def _has_tag(tags_json: object, tag: str):
    """Exact, case-insensitive membership of ``tag`` in a JSON array of tags.

    Lowercasing the serialised array keeps rows written before tags were
    normalised matchable, and ``@>`` containment compares whole elements, so
    ``ab`` never matches ``abc``.
    """
    lowered = func.lower(cast(tags_json, Text))
    return cast(lowered, JSONB).contains([tag.strip().lower()])


class AssemblyRepository:
    """Data access for Assembly model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, assembly_id: uuid.UUID) -> Assembly | None:
        """Get assembly by ID without loading components (avoids MissingGreenlet)."""
        stmt = select(Assembly).where(Assembly.id == assembly_id).options(noload(Assembly.components))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_components(self, assembly_id: uuid.UUID) -> Assembly | None:
        """Get assembly by ID with components eagerly loaded."""
        stmt = select(Assembly).where(Assembly.id == assembly_id).options(selectinload(Assembly.components))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Assembly | None:
        """Get assembly by unique code."""
        stmt = select(Assembly).where(Assembly.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        q: str | None = None,
        category: str | None = None,
        unit: str | None = None,
        tag: str | None = None,
        project_id: uuid.UUID | None = None,
        is_template: bool | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> tuple[list[Assembly], int]:
        """List assemblies with pagination and optional filters.

        Args:
            offset: Number of items to skip.
            limit: Maximum number of items to return.
            q: Optional text search on code, name, and description.
            category: Filter by category (exact match).
            unit: Filter by unit (exact match).
            tag: Filter by tag (stored in metadata.tags JSON array).
            project_id: Filter by project_id (null = global templates).
            is_template: Filter by template flag.
            owner_id: When provided, restrict to the caller's own
                assemblies (per-tenant isolation). Pass ``None`` for an
                admin / unscoped listing. Legacy/global templates with no
                owner are excluded for scoped callers - they are readable
                only by admins, matching ``_verify_assembly_owner``.

        Returns:
            Tuple of (assemblies, total_count).
        """
        base = select(Assembly).where(Assembly.is_active.is_(True))

        if owner_id is not None:
            base = base.where(Assembly.owner_id == owner_id)

        if q:
            # Every typed term has to turn up somewhere in the row, accents
            # folded on both sides. A single ILIKE on the whole query missed
            # the entries an estimator is actually trying to tell apart, since
            # the words that distinguish them are separated in the stored text
            # by words nobody types. See app.core.text_search.
            clause = free_text_filter(q, [Assembly.code, Assembly.name, Assembly.description])
            if clause is not None:
                base = base.where(clause)

        if category:
            base = base.where(Assembly.category == category)

        if unit:
            base = base.where(Assembly.unit == unit)

        if tag:
            base = base.where(_has_tag(cast(Assembly.metadata_, JSONB)["tags"], tag))

        if project_id is not None:
            base = base.where(Assembly.project_id == project_id)

        if is_template is not None:
            base = base.where(Assembly.is_template.is_(is_template))

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch - skip eager loading of components for list queries
        stmt = base.options(noload(Assembly.components)).order_by(Assembly.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        assemblies = list(result.scalars().all())

        return assemblies, total

    async def count_components(self, assembly_ids: list[uuid.UUID]) -> dict[str, int]:
        """How many components each of ``assembly_ids`` has, keyed by id as a string.

        The list query above deliberately does not load components, so the number
        cannot come from the collection: an unloaded collection reads as empty and
        the card printed "0 components" beside a hover panel listing three. One
        grouped COUNT answers it for the whole page without pulling a single
        component row across.

        Assemblies with no components are absent from the result rather than
        present with a zero, which is what ``.get(id, 0)`` at the call site is
        for; a missing key and a real zero mean the same thing here.
        """
        if not assembly_ids:
            return {}
        stmt = (
            select(Component.assembly_id, func.count(Component.id))
            .where(Component.assembly_id.in_(assembly_ids))
            .group_by(Component.assembly_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(assembly_id): count for assembly_id, count in rows}

    async def create(self, assembly: Assembly) -> Assembly:
        """Insert a new assembly."""
        self.session.add(assembly)
        await self.session.flush()
        await self.session.refresh(assembly)
        return assembly

    async def update_fields(self, assembly_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an assembly."""
        stmt = update(Assembly).where(Assembly.id == assembly_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete(self, assembly_id: uuid.UUID) -> None:
        """Delete an assembly and all its components (via CASCADE)."""
        stmt = delete(Assembly).where(Assembly.id == assembly_id)
        await self.session.execute(stmt)

    async def count(self) -> int:
        """Total number of active assemblies."""
        stmt = select(func.count()).select_from(select(Assembly).where(Assembly.is_active.is_(True)).subquery())
        return (await self.session.execute(stmt)).scalar_one()


class ComponentRepository:
    """Data access for Component model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, component_id: uuid.UUID) -> Component | None:
        """Get component by ID."""
        stmt = select(Component).where(Component.id == component_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_assembly(
        self,
        assembly_id: uuid.UUID,
    ) -> list[Component]:
        """List components for an assembly ordered by sort_order.

        Args:
            assembly_id: Parent assembly identifier.

        Returns:
            List of components ordered by sort_order.
        """
        stmt = select(Component).where(Component.assembly_id == assembly_id).order_by(Component.sort_order)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, component: Component) -> Component:
        """Insert a new component."""
        self.session.add(component)
        await self.session.flush()
        await self.session.refresh(component)
        return component

    async def bulk_create(self, components: list[Component]) -> list[Component]:
        """Insert multiple components at once."""
        self.session.add_all(components)
        await self.session.flush()
        return components

    async def update_fields(self, component_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a component.

        ``synchronize_session="evaluate"`` makes SQLAlchemy reconcile
        the bulk UPDATE with *only* the matching ORM instance in this
        session's identity map (the WHERE is always the primary key, so
        the criteria evaluate purely in Python - no extra round-trip).
        This replaces the previous ``session.expire_all()``, which
        invalidated every loaded entity mid-request and was the root
        cause of the scattered MissingGreenlet defensive fallbacks.
        """
        stmt = (
            update(Component)
            .where(Component.id == component_id)
            .values(**fields)
            .execution_options(synchronize_session="evaluate")
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete(self, component_id: uuid.UUID) -> None:
        """Delete a single component."""
        stmt = delete(Component).where(Component.id == component_id)
        await self.session.execute(stmt)

    async def get_max_sort_order(self, assembly_id: uuid.UUID) -> int:
        """Get the highest sort_order for components in an assembly."""
        stmt = select(func.coalesce(func.max(Component.sort_order), -1)).where(Component.assembly_id == assembly_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)


# ── Assembly templates (platform-wide library) ───────────────────────────────


class AssemblyTemplateRepository:
    """Data access for the AssemblyTemplate model (platform library).

    Templates are read-only for end users - the only writer is the seed
    function ``seed_assembly_templates``. All getters return ORM rows
    without eager-loading anything else (the model has no relationships).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, template_id: uuid.UUID) -> AssemblyTemplate | None:
        stmt = select(AssemblyTemplate).where(AssemblyTemplate.id == template_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, name: str) -> AssemblyTemplate | None:
        stmt = select(AssemblyTemplate).where(AssemblyTemplate.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        q: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        classification_din276: str | None = None,
        classification_masterformat: str | None = None,
    ) -> tuple[list[AssemblyTemplate], int]:
        """List templates with pagination and optional filters.

        Free-text ``q`` matches the canonical English ``name``, the
        serialised JSON ``name_translations`` (so a German user typing
        "Stahlbeton" hits ``Stahlbetonwand C30/37``), and the
        serialised ``tags`` array - all via case-insensitive LIKE so the
        same code path works on SQLite and PostgreSQL without a JSON
        operator dance.
        """
        base = select(AssemblyTemplate)

        if q:
            clause = free_text_filter(
                q,
                [
                    AssemblyTemplate.name,
                    AssemblyTemplate.name_translations.cast(String),
                    AssemblyTemplate.tags.cast(String),
                ],
            )
            if clause is not None:
                base = base.where(clause)

        if category:
            base = base.where(AssemblyTemplate.category == category)

        if tag:
            base = base.where(_has_tag(AssemblyTemplate.tags, tag))

        # Classification filters: DIN 276 KG and MasterFormat division
        # are stored as values in the JSON `classification` blob. LIKE on
        # the serialised JSON is portable across SQLite and Postgres and
        # avoids dialect-specific JSON path operators.
        if classification_din276:
            din_pattern = f'%"din276": "{classification_din276}"%'
            base = base.where(AssemblyTemplate.classification.cast(String).ilike(din_pattern))
        if classification_masterformat:
            mf_pattern = f'%"masterformat": "{classification_masterformat}"%'
            base = base.where(AssemblyTemplate.classification.cast(String).ilike(mf_pattern))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(AssemblyTemplate.category, AssemblyTemplate.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total)

    async def count(self) -> int:
        try:
            stmt = select(func.count()).select_from(AssemblyTemplate)
            return int((await self.session.execute(stmt)).scalar_one())
        except (OperationalError, ProgrammingError):
            # Table not present yet (fresh DB, alembic head not at v40).
            return 0

    async def upsert_by_name(self, payload: dict) -> AssemblyTemplate:
        """Insert or update a template keyed by its canonical ``name``.

        Returns the persisted ORM row. The seeder uses this so re-running
        on an existing DB refreshes the recipe definition without
        creating duplicates and without disturbing any user data -
        templates carry no FK relationships.
        """
        name = str(payload["name"]).strip()
        existing = await self.get_by_name(name)
        if existing is None:
            tpl = AssemblyTemplate(
                name=name,
                name_translations=payload.get("name_translations", {}) or {},
                category=str(payload.get("category", "")),
                unit=str(payload.get("unit", "")),
                components=payload.get("components", []) or [],
                classification=payload.get("classification", {}) or {},
                tags=list(payload.get("tags", []) or []),
                is_builtin=bool(payload.get("is_builtin", True)),
            )
            self.session.add(tpl)
            await self.session.flush()
            return tpl

        existing.name_translations = payload.get("name_translations", {}) or existing.name_translations
        existing.category = str(payload.get("category", existing.category))
        existing.unit = str(payload.get("unit", existing.unit))
        existing.components = payload.get("components", []) or []
        existing.classification = payload.get("classification", {}) or {}
        existing.tags = list(payload.get("tags", []) or [])
        existing.is_builtin = bool(payload.get("is_builtin", existing.is_builtin))
        await self.session.flush()
        return existing


async def seed_assembly_templates(session: AsyncSession, *, force: bool = False) -> int:
    """Bulk-upsert the canonical assembly templates from ``templates_seed``.

    Args:
        session: An open async DB session.
        force: When False (default) the seeder short-circuits if any
            template row already exists - the common boot-time case
            doesn't need to re-write 25 rows on every restart. Set True
            in migrations / tests when you want a guaranteed refresh.

    Returns:
        Number of templates that were inserted or updated.

    The function is exception-tolerant: a missing table (a fresh DB
    where the v40 migration has not yet run) logs a warning and
    returns 0 - never raises into the startup hook. This mirrors the
    pattern other modules use for optional seed data.
    """
    from app.modules.assemblies.templates_seed import get_seed_templates

    repo = AssemblyTemplateRepository(session)
    try:
        existing_total = await repo.count()
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Assembly templates table not present; skipping seed (%s)", exc)
        return 0

    templates = get_seed_templates()
    if not force and existing_total >= len(templates):
        logger.debug(
            "Assembly templates seed skipped - %d already present (target %d)",
            existing_total,
            len(templates),
        )
        return 0

    written = 0
    for tpl in templates:
        try:
            await repo.upsert_by_name(tpl)
            written += 1
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Assembly template upsert failed for %r: %s", tpl.get("name"), exc)
            continue

    if written:
        try:
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
            logger.warning("Assembly templates seed commit failed", exc_info=True)
            return 0

    logger.info("Assembly templates seeded: %d rows", written)
    return written
