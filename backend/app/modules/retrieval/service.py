# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Retrieval services: run a search, and keep the searches worth keeping.

Two services live here.

:class:`RetrievalService` is the search itself. The ranking + filtering logic is
the pure, IO-free :mod:`app.modules.retrieval.facet_query`; this service only
supplies the IO: it reads candidate records from the modules that hold the
dispute-relevant record (documents, correspondence and change orders), maps each
row to a :class:`~app.modules.retrieval.facet_query.RetrievableRecord`, then
hands the set to :func:`run_query`. Everything stays scoped to one project.

Reads are bounded per source so a huge project cannot pull an unbounded set
into memory; the cap is logged-friendly and intentionally generous for v1.

:class:`SavedSearchService` is the persistence behind the Find Records history
panel. It owns three decisions the router should not have to make: re-saving
facets that are already pinned updates that pin instead of adding a duplicate,
a full list evicts its least-used entry rather than refusing the save, and every
write runs the ``retrieval_saved_search`` rule set with the outcome persisted on
the row, so a list view can flag a broken pin without re-validating.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import Severity, validation_engine
from app.modules.changeorders.models import ChangeOrder
from app.modules.correspondence.models import Correspondence
from app.modules.documents.models import Document
from app.modules.retrieval.facet_query import FacetQuery, RankedResult, RetrievableRecord, run_query
from app.modules.retrieval.models import SavedSearch
from app.modules.retrieval.repository import SAVED_SEARCH_LIMIT, SavedSearchRepository
from app.modules.retrieval.saved_search_logic import (
    FACET_FIELDS,
    describe_facets,
    facet_signature,
    normalize_facets,
)
from app.modules.retrieval.validators import RETRIEVAL_SAVED_SEARCH_RULE_SET

logger = logging.getLogger(__name__)

#: Per-source row cap so a single source cannot dominate memory for v1.
SOURCE_LIMIT = 500

#: Every record starts from this neutral relevance; a production wiring can
#: layer a vector-adapter score in here, but the facet filter + rank stand
#: alone and deterministically without it.
BASE_SCORE = 0.5


def _iso(value: object) -> str:
    """Best-effort ISO string for a datetime / string / None."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _clean_refs(*values: object) -> tuple[str, ...]:
    """Keep only non-empty string refs, de-duplicated, order preserved."""
    out: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip() and value not in out:
            out.append(value.strip())
    return tuple(out)


class RetrievalService:
    """Gather project records from several modules and rank them by facets."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _documents(self, project_id: uuid.UUID) -> list[RetrievableRecord]:
        stmt = (
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
            .limit(SOURCE_LIMIT)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            RetrievableRecord(
                record_type="document",
                record_id=str(row.id),
                title=row.name or "",
                body=row.description or "",
                source_module="documents",
                party=row.uploaded_by or "",
                occurred_at=_iso(row.created_at),
                entity_refs=_clean_refs(row.category, getattr(row, "drawing_number", "")),
                base_score=BASE_SCORE,
            )
            for row in rows
        ]

    async def _correspondence(self, project_id: uuid.UUID) -> list[RetrievableRecord]:
        stmt = (
            select(Correspondence)
            .where(Correspondence.project_id == project_id)
            .order_by(Correspondence.created_at.desc())
            .limit(SOURCE_LIMIT)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            RetrievableRecord(
                record_type="correspondence",
                record_id=str(row.id),
                title=row.subject or "",
                body=row.notes or "",
                source_module="correspondence",
                party=row.from_contact_id or "",
                occurred_at=row.date_sent or row.date_received or _iso(row.created_at),
                entity_refs=_clean_refs(row.reference_number, row.linked_rfi_id),
                base_score=BASE_SCORE,
            )
            for row in rows
        ]

    async def _change_orders(self, project_id: uuid.UUID) -> list[RetrievableRecord]:
        stmt = (
            select(ChangeOrder)
            .where(ChangeOrder.project_id == project_id)
            .order_by(ChangeOrder.created_at.desc())
            .limit(SOURCE_LIMIT)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            RetrievableRecord(
                record_type="change_order",
                record_id=str(row.id),
                title=row.title or "",
                body=row.description or "",
                source_module="changeorders",
                party=row.ball_in_court or "",
                occurred_at=_iso(row.created_at),
                entity_refs=_clean_refs(row.code),
                base_score=BASE_SCORE,
            )
            for row in rows
        ]

    async def gather(self, project_id: uuid.UUID) -> list[RetrievableRecord]:
        """Collect candidate records from every wired source for a project."""
        records: list[RetrievableRecord] = []
        records.extend(await self._documents(project_id))
        records.extend(await self._correspondence(project_id))
        records.extend(await self._change_orders(project_id))
        return records

    async def search(
        self,
        project_id: uuid.UUID,
        query: FacetQuery,
        *,
        as_of: str = "",
    ) -> list[RankedResult]:
        """Gather the project's records and rank them against ``query``."""
        records = await self.gather(project_id)
        return list(run_query(records, query, as_of=as_of))


class SavedSearchInvalid(Exception):
    """A saved search failed a rule the module treats as blocking.

    Carries the findings so the router can hand the caller the specific reasons
    rather than a bare 422. Only ERROR-severity findings block; warnings ride
    along on the persisted row instead.
    """

    def __init__(self, findings: list[dict[str, Any]]) -> None:
        super().__init__("The saved search did not pass validation")
        self.findings = findings


def _finding(result: Any) -> dict[str, Any]:
    """One failing rule result, in the shape persisted on the row."""
    return {
        "rule_id": result.rule_id,
        "severity": str(result.severity),
        "message": result.message,
        "suggestion": result.suggestion,
    }


class SavedSearchService:
    """Create, list, replay and delete the searches a user pinned."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SavedSearchRepository(session)

    async def _validate(self, label: str, facets: dict[str, str]) -> tuple[str, list[dict]]:
        """Run the saved-search rule set over a candidate pin.

        Returns the status to persist and the failing findings. A validation
        infrastructure failure degrades to ``pending`` with no findings rather
        than blocking the save: the rules exist to catch a broken pin, not to
        make pinning unavailable when the engine is unhappy.
        """
        try:
            report = await validation_engine.validate(
                data={"label": label, "query": facets},
                rule_sets=[RETRIEVAL_SAVED_SEARCH_RULE_SET],
                target_type="retrieval_saved_search",
                target_id="",
            )
        except Exception:  # noqa: BLE001 - a broken engine must not block a save
            logger.warning("Saved-search validation failed to run", exc_info=True)
            return "pending", []

        if report.unsupported_rule_sets and not report.supported_rule_sets:
            # The rule set resolved to nothing, so nothing was checked. Saying
            # "passed" here would be the exact lie the module exists to avoid:
            # an unregistered rule set and a clean pin look identical from the
            # outside. Persist "pending" instead, and say so in the log.
            logger.warning(
                "Rule set %s resolved to no rules; the saved search was not validated",
                RETRIEVAL_SAVED_SEARCH_RULE_SET,
            )
            return "pending", []

        findings = [_finding(result) for result in report.results if not result.passed and not result.is_engine_error]
        blocking = [
            result
            for result in report.results
            if not result.passed and not result.is_engine_error and result.severity == Severity.ERROR
        ]
        if blocking:
            raise SavedSearchInvalid([_finding(result) for result in blocking])
        return ("warnings" if findings else "passed"), findings

    async def list_saved(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> list[SavedSearch]:
        """Every pin the user holds on the project, most useful first."""
        return list(await self.repo.list_for_owner(user_id, project_id))

    async def save(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        *,
        label: str,
        raw_facets: dict[str, Any],
    ) -> SavedSearch:
        """Pin a search, or update the pin that already holds these facets.

        Raises:
            SavedSearchInvalid: when a blocking rule fails.
        """
        facets = normalize_facets(raw_facets)
        name = (label or "").strip() or describe_facets(facets)
        status, findings = await self._validate(name, facets)
        signature = facet_signature(facets)

        existing = await self.repo.get_by_signature(user_id, project_id, signature)
        if existing is not None:
            # Re-saving the same facets renames the pin rather than adding a
            # second identical row, matching what the browser used to do by
            # filtering its array on the query signature.
            existing.label = name
            existing.validation_status = status
            existing.validation_findings = findings
            await self.session.flush()
            return existing

        if await self.repo.count_for_owner(user_id, project_id) >= SAVED_SEARCH_LIMIT:
            # A full list evicts its least-used entry instead of refusing the
            # save. Refusing would strand the user with no way to pin anything
            # new short of pruning by hand, and the evicted row is the one that
            # already sits at the bottom of their list.
            evicted = await self.repo.oldest_unused(user_id, project_id)
            if evicted is not None:
                await self.repo.remove(evicted)

        saved = SavedSearch(
            user_id=user_id,
            project_id=project_id,
            label=name,
            signature=signature,
            validation_status=status,
            validation_findings=findings,
            **{field: facets[field] for field in FACET_FIELDS},
        )
        return await self.repo.add(saved)

    async def update(
        self,
        saved: SavedSearch,
        *,
        label: str | None,
        raw_facets: dict[str, Any] | None,
    ) -> SavedSearch:
        """Rename a pin and/or re-point it at different facets.

        Raises:
            SavedSearchInvalid: when a blocking rule fails.
        """
        facets = (
            normalize_facets(raw_facets)
            if raw_facets is not None
            else {field: getattr(saved, field) or "" for field in FACET_FIELDS}
        )
        name = (label if label is not None else saved.label).strip() or describe_facets(facets)
        status, findings = await self._validate(name, facets)

        saved.label = name
        if raw_facets is not None:
            for field in FACET_FIELDS:
                setattr(saved, field, facets[field])
            saved.signature = facet_signature(facets)
        saved.validation_status = status
        saved.validation_findings = findings
        await self.session.flush()
        return saved

    async def record_use(self, saved: SavedSearch) -> SavedSearch:
        """Note that the user replayed this pin, so it climbs their list."""
        return await self.repo.touch(saved)

    async def delete(self, saved: SavedSearch) -> None:
        """Unpin a search."""
        await self.repo.remove(saved)
