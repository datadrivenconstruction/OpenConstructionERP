"""‌⁠‍Contacts data access layer.

All database queries for contacts live here.
No business logic — pure data access.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact


def _tenant_scope(owner_id: str):  # type: ignore[no-untyped-def]
    """‌⁠‍Produce the WHERE clause that scopes contacts to ``owner_id``.

    Prefers the ``tenant_id`` column (populated from v2.3.1 onwards) and
    falls back to ``created_by`` so rows inserted before the migration
    backfill still resolve correctly. Both branches are indexed.
    """
    owner = str(owner_id)
    return or_(Contact.tenant_id == owner, Contact.created_by == owner)


class ContactRepository:
    """‌⁠‍Data access for Contact model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, contact_id: uuid.UUID) -> Contact | None:
        """Get contact by ID."""
        return await self.session.get(Contact, contact_id)

    async def get_by_email(self, email: str) -> Contact | None:
        """Get first active contact by primary email.

        Returns the first match (preferring active contacts) so duplicate
        emails in legacy data do not raise MultipleResultsFound.
        """
        stmt = (
            select(Contact)
            .where(Contact.primary_email == email.lower())
            .order_by(Contact.is_active.desc(), Contact.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        contact_type: str | None = None,
        country_code: str | None = None,
        search: str | None = None,
        is_active: bool = True,
        owner_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[Contact], int]:
        """List contacts with filters and pagination.

        ``owner_id`` scopes the result to contacts in the caller's
        tenant (``tenant_id`` column, with a fallback to ``created_by``
        for rows inserted before the v2.3.1 migration).  Pass ``None``
        to skip the scope filter — only admins should ever do that.

        Returns (contacts, total_count).
        """
        base = select(Contact).where(Contact.is_active == is_active)

        if contact_type is not None:
            base = base.where(Contact.contact_type == contact_type)
        if country_code is not None:
            base = base.where(Contact.country_code == country_code)
        if owner_id is not None:
            base = base.where(_tenant_scope(owner_id))
        if search is not None:
            term = f"%{search}%"
            base = base.where(
                or_(
                    Contact.first_name.ilike(term),
                    Contact.last_name.ilike(term),
                    Contact.company_name.ilike(term),
                    Contact.primary_email.ilike(term),
                )
            )
        if tags:
            # Tags live in metadata.tags as a JSON array of strings. We
            # filter by casting metadata to text and substring-matching
            # the quoted tag — portable across SQLite and Postgres without
            # dialect-specific JSON operators. AND-combined: a contact
            # must carry every requested tag.
            metadata_text = func.cast(Contact.metadata_, String)
            tag_clauses = [metadata_text.ilike(f'%"{t}"%') for t in tags if t]
            if tag_clauses:
                base = base.where(and_(*tag_clauses))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Sorting
        order_clause = None
        if sort_by:
            col = getattr(Contact, sort_by, None)
            if col is not None:
                order_clause = col.desc() if sort_order == "desc" else col.asc()
        if order_clause is None:
            order_clause = Contact.created_at.desc()

        stmt = base.order_by(order_clause).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        contacts = list(result.scalars().all())

        return contacts, total

    async def create(self, contact: Contact) -> Contact:
        """Insert a new contact."""
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def update(self, contact_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a contact."""
        stmt = update(Contact).where(Contact.id == contact_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def count(self, contact_type: str | None = None) -> int:
        """Count contacts, optionally filtered by type."""
        base = select(func.count()).select_from(Contact)
        if contact_type is not None:
            base = select(func.count()).select_from(
                select(Contact).where(Contact.contact_type == contact_type).subquery()
            )
        return (await self.session.execute(base)).scalar_one()

    async def stats(self, *, owner_id: str | None = None) -> dict:
        """Compute aggregate contact statistics.

        ``owner_id`` scopes the aggregates to a single tenant via the
        ``tenant_id`` column (``created_by`` fallback for legacy rows).
        Pass ``None`` for the global view — admins only.

        Returns dict with keys: total, by_type, by_country_top10,
        with_expiring_prequalification.
        """
        # Reused base predicate for all 4 sub-queries below.
        owner_filter = _tenant_scope(owner_id) if owner_id is not None else None

        def _scope(stmt):  # type: ignore[no-untyped-def]
            return stmt.where(owner_filter) if owner_filter is not None else stmt

        # Total active contacts
        total_stmt = _scope(select(func.count()).select_from(Contact).where(Contact.is_active.is_(True)))
        total = (await self.session.execute(total_stmt)).scalar_one()

        # Count by type
        type_stmt = _scope(
            select(Contact.contact_type, func.count()).where(Contact.is_active.is_(True)).group_by(Contact.contact_type)
        )
        type_rows = (await self.session.execute(type_stmt)).all()
        by_type = {row[0]: row[1] for row in type_rows}

        # Top 10 countries
        country_stmt = _scope(
            select(Contact.country_code, func.count())
            .where(Contact.is_active.is_(True))
            .where(Contact.country_code.isnot(None))
            .group_by(Contact.country_code)
            .order_by(func.count().desc())
            .limit(10)
        )
        country_rows = (await self.session.execute(country_stmt)).all()
        by_country_top10 = {row[0]: row[1] for row in country_rows}

        # Contacts with expiring prequalification (approved + qualified_until set)
        expiring_stmt = _scope(
            select(func.count())
            .select_from(Contact)
            .where(Contact.is_active.is_(True))
            .where(Contact.prequalification_status == "approved")
            .where(Contact.qualified_until.isnot(None))
        )
        with_expiring = (await self.session.execute(expiring_stmt)).scalar_one()

        return {
            "total": total,
            "by_type": by_type,
            "by_country_top10": by_country_top10,
            "with_expiring_prequalification": with_expiring,
        }

    async def tag_facets(
        self,
        *,
        owner_id: str | None = None,
        limit: int = 60,
    ) -> list[tuple[str, int]]:
        """Aggregate tag counts from active contacts.

        Returns the top ``limit`` tags as ``(tag, count)`` tuples, sorted
        by count desc. Walks the metadata.tags arrays in Python — at
        contact-list scale (a few thousand rows) this is cheaper than
        dialect-specific JSON unnest queries.
        """
        base = select(Contact.metadata_).where(Contact.is_active.is_(True))
        if owner_id is not None:
            base = base.where(_tenant_scope(owner_id))

        rows = (await self.session.execute(base)).scalars().all()
        counts: dict[str, int] = {}
        for meta in rows:
            if not isinstance(meta, dict):
                continue
            tags = meta.get("tags")
            if not isinstance(tags, list):
                continue
            for t in tags:
                if isinstance(t, str) and t:
                    counts[t] = counts.get(t, 0) + 1

        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    async def list_by_company(
        self,
        company_name: str,
        *,
        owner_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Contact], int]:
        """List all contacts at the same company.

        Uses case-insensitive matching on company_name.  ``owner_id``
        scopes the result by ``tenant_id`` (with ``created_by`` fallback).
        """
        base = (
            select(Contact)
            .where(Contact.is_active.is_(True))
            .where(func.lower(Contact.company_name) == company_name.lower())
        )
        if owner_id is not None:
            base = base.where(_tenant_scope(owner_id))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Contact.last_name.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        contacts = list(result.scalars().all())

        return contacts, total
