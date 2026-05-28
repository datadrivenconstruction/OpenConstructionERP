"""‌⁠‍Project data access layer.

All database queries for projects live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import Integer, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.modules.projects.models import Project


class ProjectRepository:
    """‌⁠‍Data access for Project model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        """‌⁠‍Get project by ID."""
        return await self.session.get(Project, project_id)

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        exclude_archived: bool = True,
        is_admin: bool = False,
    ) -> tuple[list[Project], int]:
        """List projects for a user with pagination. Returns (projects, total_count).

        Admins see all projects; regular users see projects they own OR
        where they are a team member (added via add_project_member).
        Archived (soft-deleted) projects are excluded by default; pass an
        explicit `status` to override.
        """
        from app.modules.teams.access import member_project_ids_subquery

        base = select(Project)
        if not is_admin:
            base = base.where(
                (Project.owner_id == owner_id)
                | (Project.id.in_(member_project_ids_subquery(owner_id)))
            )
        if status is not None:
            base = base.where(Project.status == status)
        elif exclude_archived:
            base = base.where(Project.status != "archived")

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch — skip eager loading of relationships for list queries
        stmt = (
            base.options(
                noload(Project.wbs_nodes),
                noload(Project.milestones),
                noload(Project.children),
            )
            .order_by(Project.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        projects = list(result.scalars().all())

        return projects, total

    async def create(self, project: Project) -> Project:
        """Insert a new project."""
        self.session.add(project)
        await self.session.flush()
        return project

    async def update_fields(self, project_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a project."""
        stmt = update(Project).where(Project.id == project_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, project_id: uuid.UUID) -> None:
        """Hard delete a project."""
        project = await self.get_by_id(project_id)
        if project is not None:
            await self.session.delete(project)
            await self.session.flush()

    async def count_for_user(self, owner_id: uuid.UUID) -> int:
        """Total number of projects for a user."""
        stmt = select(func.count()).select_from(select(Project).where(Project.owner_id == owner_id).subquery())
        return (await self.session.execute(stmt)).scalar_one()

    async def project_code_exists(self, code: str) -> bool:
        """Return True if any row already carries this ``project_code``.

        Used by ``ProjectService._generate_project_code`` to detect the
        rare race where two concurrent creates compute the same next
        sequence number before either inserts. Cheap — single indexed
        scalar query.
        """
        stmt = select(func.count()).select_from(select(Project.id).where(Project.project_code == code).subquery())
        count = (await self.session.execute(stmt)).scalar_one()
        return bool(count)

    async def existing_project_codes(self, codes: list[str]) -> set[str]:
        """Bulk variant of :meth:`project_code_exists`.

        Returns the subset of ``codes`` that are already committed in
        ``Project.project_code``. Issues a single ``WHERE IN (...)``
        query instead of N point queries — used by the stale-reservation
        prune in ``ProjectService._generate_project_code`` which can
        otherwise spend O(N) round-trips checking reservations on every
        ``create_project`` call when the in-process reservation set has
        grown (long-running uvicorn workers, batch importer scenarios).

        Empty input → empty set (no query issued).

        Hard cap on input size — refuses to issue an unbounded ``IN``
        clause that could trip Postgres' parameter-limit (max 32k bind
        params on the wire). The caller (generator) keeps the
        reservation set small in practice, but guarding here protects
        against pathological batch flows.
        """
        if not codes:
            return set()
        # Postgres caps at ~32k bind parameters per statement; chunk
        # defensively. 1000 covers any sane in-process reservation set
        # while staying well below the limit even on the worst engine.
        BATCH = 1000
        found: set[str] = set()
        for start in range(0, len(codes), BATCH):
            chunk = codes[start : start + BATCH]
            stmt = select(Project.project_code).where(
                Project.project_code.in_(chunk),
            )
            result = await self.session.execute(stmt)
            for row in result.all():
                if row[0] is not None:
                    found.add(row[0])
        return found

    async def max_project_code_seq(self, prefix: str) -> int | None:
        """Find the maximum sequence number for project codes with the given prefix.

        Scans codes like ``PRJ-2026-0001`` and extracts the numeric suffix.
        Returns ``None`` if no matching codes exist.

        Performance: pushes the scan into the database as a single
        ``SELECT MAX(CAST(SUBSTR(project_code, N) AS INTEGER))`` aggregate
        scoped by ``LIKE prefix || '%'``. Previously this method loaded
        every matching row into the application and iterated in Python —
        an O(n) pull that became measurable past a few hundred projects.
        The aggregate runs in O(1) wall time on the indexed column with
        a single round-trip and zero rows transferred.

        ``GLOB`` (SQLite) / ``SIMILAR TO`` (Postgres) would be the
        absolutely safest filter for the cast, but neither is portable.
        Instead we feed the cast a substring that's already been
        prefix-matched, then defensively coalesce a ``NULL`` MAX (no
        rows) to ``None``. Rows whose suffix isn't a pure integer don't
        produce a meaningful ``int(...)`` in the old code path either —
        on SQLite the cast yields ``0`` for them (harmless: 0 < any real
        sequence), on Postgres the cast raises and we fall through to the
        Python scan as a safety net (preserves existing semantics for
        any pre-existing malformed codes).
        """
        prefix_len = len(prefix)
        if prefix_len <= 0:
            return None

        # SUBSTR is 1-indexed in SQL — pass prefix_len + 1 to start past
        # the prefix.
        suffix_expr = func.substr(Project.project_code, prefix_len + 1)
        max_expr = func.max(func.cast(suffix_expr, Integer))
        stmt = select(max_expr).where(
            Project.project_code.isnot(None),
            Project.project_code.startswith(prefix),
        )
        try:
            result = await self.session.execute(stmt)
            max_seq = result.scalar()
        except DBAPIError:
            # Postgres raises on a non-numeric cast; fall back to the
            # original Python-side scan so a single malformed historical
            # row doesn't break code generation.
            return await self._max_project_code_seq_python_fallback(prefix)

        if max_seq is None or max_seq <= 0:
            return None
        return int(max_seq)

    async def _max_project_code_seq_python_fallback(self, prefix: str) -> int | None:
        """Python-side scan fallback for ``max_project_code_seq``.

        Used only when the SQL CAST raises (e.g. Postgres encountering a
        non-numeric suffix on a malformed legacy row). Preserves the
        pre-aggregate behaviour: ignore unparseable codes, return the
        max integer suffix observed.
        """
        stmt = select(Project.project_code).where(
            Project.project_code.isnot(None),
            Project.project_code.startswith(prefix),
        )
        result = await self.session.execute(stmt)
        codes = [row[0] for row in result.all()]

        if not codes:
            return None

        max_seq = 0
        prefix_len = len(prefix)
        for code in codes:
            try:
                seq = int(code[prefix_len:])
            except (ValueError, IndexError):
                continue
            if seq > max_seq:
                max_seq = seq

        return max_seq if max_seq > 0 else None
