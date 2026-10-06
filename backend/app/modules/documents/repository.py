# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document Management data access layer.

All database queries for documents live here.
No business logic - pure data access.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, cast, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.documents.folder_permissions_models import FOLDER_SCOPED_CATEGORIES
from app.modules.documents.models import Document, ProjectPhoto, Sheet
from app.modules.documents.sheet_fields import sheet_chain_key

# Columns a client is allowed to sort the document list by. Everything
# else (dunder attributes like ``__class__`` that ``getattr`` happily
# returns, relationship/hybrid attributes, and the internal server-side
# ``file_path`` column) is rejected so an attacker can neither crash the
# query (``__class__.desc()`` → 500, A-DOC-07) nor use ``file_path`` as
# an ordering oracle on the storage layout (A-DOC-08).
SORTABLE_DOCUMENT_COLUMNS: frozenset[str] = frozenset(
    {"name", "created_at", "updated_at", "category", "file_size", "version"}
)


class DocumentRepository:
    """Data access for Document models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        """Get document by ID."""
        return await self.session.get(Document, document_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
        visible_categories: frozenset[str | None] | None = None,
    ) -> tuple[list[Document], int]:
        """List documents for a project with pagination and filters.

        Search matches against (case-insensitive ILIKE):
            * ``Document.name`` / ``Document.description``
            * ``Document.metadata_["ocr_text"]`` - text extracted from PDFs by
              the takeoff / sheet-split pipelines and stored in the JSON
              ``metadata`` column under the ``ocr_text`` key.
            * ``Sheet.sheet_title`` / ``Sheet.sheet_number`` for any sheet
              that references this document (outer join on the
              ``Sheet.document_id`` string column - Sheet stores the parent
              document id as a string, not a FK, so we cast Document.id to
              string for the join predicate).

        ``DISTINCT`` is applied so a document with multiple matching sheets
        appears once in the result set.

        ``visible_categories`` narrows the COUNT only, never the page. The
        route hands folder permissions to the page as a row-by-row filter it
        applies after this query, and that filter is left exactly where it is:
        it is the access control, and a rewrite of it into SQL that got one
        wildcard branch wrong would leak documents rather than miscount them.
        The count has no such stake, so it takes the same decision expressed
        as a set of readable categories - which is what makes ``total``
        describe the register the caller can actually see. ``None`` inside the
        set stands for documents whose category is not folder-scoped.
        """
        base = select(Document).where(Document.project_id == project_id)
        if category is not None:
            base = base.where(Document.category == category)
        if search is not None:
            pattern = f"%{search}%"
            # ``metadata_`` is mapped as ``sqlalchemy.JSON`` (NOT JSONB), so
            # both SQLite (development) and PostgreSQL (production) return
            # the raw text via the dialect-portable ``[key].as_string()``
            # accessor. Wrap in ``coalesce`` so a missing key surfaces as
            # ``''`` rather than NULL - ILIKE-against-NULL is always false.
            ocr_expr = func.coalesce(
                cast(Document.metadata_["ocr_text"].as_string(), String),
                "",
            )
            # Sheet.document_id is String(255); Document.id is UUID/String.
            # Cast Document.id to String so the comparison works on both
            # SQLite (TEXT) and PostgreSQL (UUID/TEXT) backends.
            base = base.outerjoin(
                Sheet,
                Sheet.document_id == cast(Document.id, String),
            )
            base = base.where(
                or_(
                    Document.name.ilike(pattern),
                    Document.description.ilike(pattern),
                    ocr_expr.ilike(pattern),
                    Sheet.sheet_title.ilike(pattern),
                    Sheet.sheet_number.ilike(pattern),
                )
            ).distinct()

        counted = base
        if visible_categories is not None:
            readable = [c for c in visible_categories if c is not None]
            clauses: list[ClauseElement] = []
            if readable:
                clauses.append(Document.category.in_(sorted(readable)))
            if None in visible_categories:
                # The unscoped folder: NULL, or a category outside the set the
                # permission model knows about. ``notin_`` alone would drop the
                # NULL rows - a NULL comparison is NULL, not true - so the
                # ``is_(None)`` arm has to be spelled out.
                clauses.append(
                    or_(
                        Document.category.is_(None),
                        Document.category.notin_(sorted(FOLDER_SCOPED_CATEGORIES)),
                    )
                )
            counted = counted.where(or_(*clauses)) if clauses else counted.where(false())

        count_stmt = select(func.count()).select_from(counted.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Sorting - only a documented whitelist of columns is honoured.
        # An unknown / dunder / sensitive ``sort_by`` falls back to
        # ``created_at desc`` instead of 500-ing (A-DOC-07) or leaking
        # the internal ``file_path`` column ordering (A-DOC-08).
        order_clause = None
        if sort_by and sort_by in SORTABLE_DOCUMENT_COLUMNS:
            col = getattr(Document, sort_by, None)
            if col is not None:
                order_clause = col.desc() if sort_order == "desc" else col.asc()
        if order_clause is None:
            order_clause = Document.created_at.desc()

        stmt = base.order_by(order_clause).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, document: Document) -> Document:
        """Insert a new document."""
        self.session.add(document)
        await self.session.flush()
        return document

    async def update_fields(self, document_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a document."""
        stmt = update(Document).where(Document.id == document_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(Document, document_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, document_id: uuid.UUID) -> None:
        """Hard delete a document."""
        item = await self.get_by_id(document_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def all_for_project(self, project_id: uuid.UUID) -> list[Document]:
        """Return all documents for a project (used for summary)."""
        stmt = select(Document).where(Document.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def summary_for_project(self, project_id: uuid.UUID) -> tuple[int, int, list[tuple[str, int]]]:
        """Return aggregated stats using SQL: (total_count, total_size, [(category, count)])."""
        # Total count and size
        totals_stmt = select(
            func.count(Document.id),
            func.coalesce(func.sum(Document.file_size), 0),
        ).where(Document.project_id == project_id)
        totals_row = (await self.session.execute(totals_stmt)).one()
        total_count: int = totals_row[0]
        total_size: int = totals_row[1]

        # Count by category
        cat_stmt = (
            select(Document.category, func.count(Document.id))
            .where(Document.project_id == project_id)
            .group_by(Document.category)
        )
        cat_rows = (await self.session.execute(cat_stmt)).all()

        return total_count, total_size, list(cat_rows)

    async def recent_uploads(self, project_id: uuid.UUID, limit: int = 5) -> list[Document]:
        """Return the most recently uploaded documents for a project."""
        stmt = (
            select(Document).where(Document.project_id == project_id).order_by(Document.created_at.desc()).limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class PhotoRepository:
    """Data access for ProjectPhoto models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, photo_id: uuid.UUID) -> ProjectPhoto | None:
        """Get photo by ID."""
        return await self.session.get(ProjectPhoto, photo_id)

    async def create(self, photo: ProjectPhoto) -> ProjectPhoto:
        """Insert a new photo."""
        self.session.add(photo)
        await self.session.flush()
        return photo

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        category: str | None = None,
        tag: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[list[ProjectPhoto], int]:
        """List photos for a project with filters."""
        base = select(ProjectPhoto).where(ProjectPhoto.project_id == project_id)

        if category is not None:
            base = base.where(ProjectPhoto.category == category)
        if search is not None:
            pattern = f"%{search}%"
            base = base.where(
                or_(
                    ProjectPhoto.caption.ilike(pattern),
                    ProjectPhoto.filename.ilike(pattern),
                )
            )
        if date_from is not None:
            base = base.where(ProjectPhoto.created_at >= date_from)
        if date_to is not None:
            base = base.where(ProjectPhoto.created_at <= date_to)
        # Tag filtering handled in service layer for JSON compatibility

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ProjectPhoto.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def recent_across_projects(
        self,
        project_ids: list[uuid.UUID],
        *,
        limit: int = 12,
    ) -> list[tuple[ProjectPhoto, str]]:
        """Return the most recent photos across ``project_ids``, newest first.

        Joins each photo to its project so the caller gets the project
        name in one round trip. Ordering prefers ``taken_at`` (when the
        shutter fired) and falls back to ``created_at`` for photos with no
        EXIF capture date, so a freshly uploaded photo without EXIF still
        sorts sensibly. Returns ``(photo, project_name)`` pairs.

        An empty ``project_ids`` list short-circuits to ``[]`` so we never
        emit a ``WHERE project_id IN ()`` that some backends choke on.
        """
        if not project_ids:
            return []

        from app.modules.projects.models import Project

        # coalesce(taken_at, created_at) gives a single sortable instant so
        # null capture dates fall back to upload time instead of sinking to
        # the bottom of the list.
        sort_instant = func.coalesce(ProjectPhoto.taken_at, ProjectPhoto.created_at)
        stmt = (
            select(ProjectPhoto, Project.name)
            .join(Project, Project.id == ProjectPhoto.project_id)
            # A deleted project is archived, not removed; its photos are not
            # "recent across projects" and would open onto "Project not found".
            .where(ProjectPhoto.project_id.in_(project_ids), Project.status != "archived")
            .order_by(sort_instant.desc(), ProjectPhoto.created_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]

    async def update_fields(self, photo_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a photo."""
        stmt = update(ProjectPhoto).where(ProjectPhoto.id == photo_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(ProjectPhoto, photo_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, photo_id: uuid.UUID) -> None:
        """Hard delete a photo."""
        item = await self.get_by_id(photo_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()


class SheetRepository:
    """Data access for Sheet models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, sheet_id: uuid.UUID) -> Sheet | None:
        """Get sheet by ID."""
        return await self.session.get(Sheet, sheet_id)

    async def create(self, sheet: Sheet) -> Sheet:
        """Insert a new sheet."""
        self.session.add(sheet)
        await self.session.flush()
        return sheet

    async def create_many(self, sheets: list[Sheet]) -> list[Sheet]:
        """Insert multiple sheets at once."""
        self.session.add_all(sheets)
        await self.session.flush()
        return sheets

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        discipline: str | None = None,
        revision: str | None = None,
        document_id: str | None = None,
        current_only: bool = False,
    ) -> tuple[list[Sheet], int]:
        """List sheets for a project with pagination and filters."""
        base = select(Sheet).where(Sheet.project_id == project_id)

        if discipline is not None:
            base = base.where(Sheet.discipline == discipline)
        if revision is not None:
            base = base.where(Sheet.revision == revision)
        if document_id is not None:
            base = base.where(Sheet.document_id == document_id)
        if current_only:
            base = base.where(Sheet.is_current.is_(True))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # A page number is not unique: a set uploaded again starts at page 1
        # again, and one import can register two revisions in a single instant.
        # Ordering on the page number alone leaves those ties to the storage,
        # which is not an order the same query has to repeat, and the route
        # pages this with offset and limit - two pages that resolve one tie
        # differently show a row twice and skip the one it displaced. The
        # instant puts the older revision first and the id, being unique, is
        # what makes the order total.
        ordered = base.order_by(Sheet.page_number.asc(), Sheet.created_at.asc(), Sheet.id.asc())
        stmt = ordered.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def update_fields(self, sheet_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a sheet."""
        stmt = update(Sheet).where(Sheet.id == sheet_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(Sheet, sheet_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, sheet_id: uuid.UUID) -> None:
        """Hard delete a sheet."""
        item = await self.get_by_id(sheet_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def distinct_disciplines(self, project_id: uuid.UUID) -> list[str]:
        """Return distinct discipline values for a project."""
        stmt = (
            select(Sheet.discipline)
            .where(Sheet.project_id == project_id)
            .where(Sheet.discipline.isnot(None))
            .distinct()
            .order_by(Sheet.discipline)
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_version_chain(self, sheet_id: uuid.UUID) -> list[Sheet]:
        """Get all versions of a sheet by following previous_version_id links.

        Returns sheets ordered from oldest to newest.
        """
        current = await self.get_by_id(sheet_id)
        if current is None:
            return []

        chain = [current]

        # Walk backwards through previous versions
        visited: set[uuid.UUID] = {current.id}
        node = current
        while node.previous_version_id is not None:
            if node.previous_version_id in visited:
                break  # Prevent infinite loops
            prev = await self.get_by_id(node.previous_version_id)
            if prev is None:
                break
            visited.add(prev.id)
            chain.append(prev)
            node = prev

        # Walk forwards: find sheets that reference the current sheet
        # (or any sheet in the chain) as their previous_version_id
        forward_ids = {s.id for s in chain}
        while True:
            stmt = select(Sheet).where(Sheet.previous_version_id.in_(forward_ids)).where(Sheet.id.notin_(forward_ids))
            result = await self.session.execute(stmt)
            newer = list(result.scalars().all())
            if not newer:
                break
            for s in newer:
                forward_ids.add(s.id)
                chain.append(s)

        # Oldest first, in the order the links say. That is not always upload
        # order: an older revision uploaded after a newer one is linked in
        # beneath it, so its place is its depth below the root, not its
        # timestamp. Rows at one depth (two pages of one upload claiming the
        # same predecessor) fall back to the instant and then the id. The id
        # tiebreak matters: rows written by one ``create_many`` share a flush
        # and therefore a ``created_at``; the id is not chronological, but it is
        # stable, which is what a caller reading a version history needs.
        by_id = {s.id: s for s in chain}
        depth: dict[uuid.UUID, int] = {}
        for sheet in chain:
            walk: list[uuid.UUID] = []
            node: Sheet | None = sheet
            while node is not None and node.id not in depth and node.id not in walk:
                walk.append(node.id)
                node = by_id.get(node.previous_version_id) if node.previous_version_id else None
            base = depth.get(node.id, -1) if node is not None else -1
            for offset, sheet_id in enumerate(reversed(walk), start=1):
                depth[sheet_id] = base + offset
        chain.sort(key=lambda s: (depth[s.id], s.created_at, str(s.id)))
        return chain

    async def all_for_project(self, project_id: uuid.UUID) -> list[Sheet]:
        """Every sheet of a project, current and retired, oldest upload first."""
        stmt = select(Sheet).where(Sheet.project_id == project_id).order_by(Sheet.created_at, Sheet.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def successors_of(self, sheet_id: uuid.UUID) -> list[Sheet]:
        """Rows that name ``sheet_id`` as the revision they replaced."""
        stmt = select(Sheet).where(Sheet.previous_version_id == sheet_id).order_by(Sheet.created_at, Sheet.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def current_by_chain_key(self, project_id: uuid.UUID) -> dict[str, list[Sheet]]:
        """Return the project's current numbered sheets grouped by stack key.

        The stack key is :func:`sheet_chain_key` of the number, and not the
        parent document, because a revised drawing set arrives as a new PDF and
        the whole point is to recognise that its A-201 supersedes the previous
        A-201, or A201, or A-0201. That is deliberately a different key from the
        one ``canonical_name_for`` builds for the ``FileVersion`` index, which
        composes the document id in so that two unrelated PDFs do not merge into
        one history. The two answer different questions: this one answers what
        the project's current drawing set is.

        The key is computed in Python, so every current numbered row of the
        project is read. A register is hundreds of rows, not millions, and the
        alternative is a normalised column every writer would have to keep in
        step.

        Args:
            project_id: Project to look in.

        Returns:
            Mapping of stack key to its current rows, oldest first. More than
            one row per key is normal for a bare number ("TAVOLA 1" of two
            disciplines), and is also what a register already carrying
            duplicates looks like; the caller picks among them. The order is
            total, so the same rows always resolve the same way.
        """
        stmt = (
            select(Sheet)
            .where(Sheet.project_id == project_id)
            .where(Sheet.is_current.is_(True))
            .where(Sheet.sheet_number.isnot(None))
            # The id is not decoration. ``created_at`` is written per row by a
            # Python default, so it is only as fine as the clock underneath it,
            # and on a coarse one an entire import batch carries a single value.
            # Duplicates in this register come from exactly that, one import
            # writing the same number twice, which is the case where the
            # timestamp has nothing left to order by. Which row is the later one
            # decides what an incoming revision records as the one it replaces,
            # so leaving that to the plan would let one upload link to a
            # different predecessor than the same upload against the same rows
            # elsewhere. Same tiebreak and same direction as
            # ``get_version_chain`` above, so the two cannot disagree.
            .order_by(Sheet.created_at.asc(), Sheet.id.asc())
        )
        result = await self.session.execute(stmt)
        grouped: dict[str, list[Sheet]] = {}
        for sheet in result.scalars().all():
            key = sheet_chain_key(sheet.sheet_number)
            if key:
                grouped.setdefault(key, []).append(sheet)
        return grouped
