# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue business logic.

A project rate is a copy. Copying reads the source once; every later read
compares the copy with the source as it is now, so a moved database price is
seen without anything being pushed into the project. The master data is only
ever read here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status

from app.modules.project_catalogue.catalogue_math import (
    ItemStatus,
    deviation_percent,
    item_status,
    resolve_sync,
)
from app.modules.project_catalogue.models import ProjectCatalogueItem
from app.modules.project_catalogue.repository import LINK_KEY, ProjectCatalogueRepository, link_of
from app.modules.project_catalogue.schemas import (
    ApplyResult,
    CandidateListResponse,
    CatalogueSummary,
    Finding,
    ImportResult,
    ItemCreate,
    ItemListResponse,
    ItemResponse,
    ItemUpdate,
    PositionCandidate,
    SourceHit,
    SourceSearchResponse,
    SyncResult,
    ValidationReportOut,
)
from app.modules.project_catalogue.validators import PROJECT_CATALOGUE_RULE_SET


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


@dataclass(frozen=True)
class SourceRow:
    """A source row read now, reduced to what the catalogue compares."""

    source_type: str
    source_id: str
    code: str
    description: str
    unit: str
    rate: Decimal
    currency: str
    label: str
    item_type: str
    active: bool


def _cost_item_row(row: Any, catalog_names: dict[str, str]) -> SourceRow:
    label = catalog_names.get(str(row.catalog_id)) if row.catalog_id else None
    if not label:
        label = " ".join(p for p in (str(row.source or ""), str(row.region or "")) if p).strip()
    return SourceRow(
        source_type="cost_item",
        source_id=str(row.id),
        code=row.code,
        description=row.description,
        unit=row.unit or "",
        rate=_dec(row.rate) or Decimal(0),
        currency=row.currency or "",
        label=label,
        item_type="work",
        active=bool(row.is_active),
    )


_RESOURCE_TYPES = {"labor": "labor", "labour": "labor", "material": "material", "equipment": "equipment"}


def _resource_row(row: Any) -> SourceRow:
    return SourceRow(
        source_type="catalog_resource",
        source_id=str(row.id),
        code=row.resource_code,
        description=row.name,
        unit=row.unit or "",
        rate=_dec(row.base_price) or Decimal(0),
        currency=row.currency or "",
        label=" ".join(p for p in (str(row.source or ""), str(row.region or "")) if p).strip(),
        item_type=_RESOURCE_TYPES.get(str(row.resource_type or "").lower(), "other"),
        active=bool(row.is_active),
    )


class ProjectCatalogueService:
    """Copy, edit, reconcile and apply a project's own rates."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.repo = ProjectCatalogueRepository(session)

    # ── Reading sources ─────────────────────────────────────────────────────

    async def _sources(self, items: list[ProjectCatalogueItem]) -> dict[tuple[str, str], SourceRow]:
        by_type: dict[str, list[str]] = {}
        for item in items:
            if item.source_type != "manual" and item.source_id:
                by_type.setdefault(item.source_type, []).append(item.source_id)
        out: dict[tuple[str, str], SourceRow] = {}
        if by_type.get("cost_item"):
            rows = await self.repo.cost_items(by_type["cost_item"])
            names = await self.repo.catalog_names(r.catalog_id for r in rows.values())
            for key, row in rows.items():
                out[("cost_item", key)] = _cost_item_row(row, names)
        if by_type.get("catalog_resource"):
            for key, row in (await self.repo.catalog_resources(by_type["catalog_resource"])).items():
                out[("catalog_resource", key)] = _resource_row(row)
        return out

    @staticmethod
    def _current(item: ProjectCatalogueItem, sources: dict[tuple[str, str], SourceRow]) -> SourceRow | None:
        row = sources.get((item.source_type, item.source_id or ""))
        return row if row is not None and row.active else None

    # ── Read model ──────────────────────────────────────────────────────────

    async def _links(self, project_id: uuid.UUID) -> dict[str, list[Any]]:
        links: dict[str, list[Any]] = {}
        for position, _ in await self.repo.project_positions(project_id):
            linked = link_of(position.metadata_)
            if linked:
                links.setdefault(linked, []).append(position)
        return links

    def _response(
        self,
        item: ProjectCatalogueItem,
        sources: dict[tuple[str, str], SourceRow],
        links: dict[str, list[Any]],
    ) -> ItemResponse:
        current = self._current(item, sources)
        rate = Decimal(item.rate)
        st = item_status(
            source_type=item.source_type,
            rate=rate,
            source_rate=item.source_rate,
            current_source_rate=current.rate if current else None,
            source_found=current is not None,
        )
        linked = links.get(str(item.id), [])
        stale = sum(1 for p in linked if (_dec(p.unit_rate) or Decimal(0)).compare(rate) != 0)
        out = ItemResponse.model_validate(item)
        out.current_source_rate = current.rate if current else None
        out.status = st.value
        out.deviation_percent = deviation_percent(rate, item.source_rate)
        out.linked_positions = len(linked)
        out.stale_positions = stale
        return out

    async def list_items(
        self,
        project_id: uuid.UUID,
        *,
        status_filter: str = "",
        q: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> ItemListResponse:
        items = await self.repo.list_for_project(project_id)
        sources = await self._sources(items)
        links = await self._links(project_id)
        rows = [self._response(i, sources, links) for i in items]
        summary = CatalogueSummary(total=len(rows))
        for r in rows:
            setattr(summary, r.status, getattr(summary, r.status) + 1)
            summary.linked_positions += r.linked_positions
            summary.stale_positions += r.stale_positions
        if status_filter:
            rows = [r for r in rows if r.status == status_filter]
        if q:
            needle = q.casefold()
            rows = [r for r in rows if needle in r.code.casefold() or needle in r.description.casefold()]
        return ItemListResponse(
            items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit, summary=summary
        )

    async def item_response(self, item: ProjectCatalogueItem, warnings: list[dict] | None = None) -> ItemResponse:
        sources = await self._sources([item])
        links = await self._links(item.project_id)
        out = self._response(item, sources, links)
        out.warnings = warnings or []
        return out

    async def get_item(self, item_id: uuid.UUID) -> ProjectCatalogueItem | None:
        return await self.repo.get(item_id)

    # ── Validation ──────────────────────────────────────────────────────────

    @staticmethod
    def _payload(item: ProjectCatalogueItem | dict, current: SourceRow | None = None) -> dict[str, Any]:
        get = item.get if isinstance(item, dict) else lambda k, d=None: getattr(item, k, d)
        return {
            "id": str(get("id") or ""),
            "code": get("code") or "",
            "unit": get("unit") or "",
            "rate": None if get("rate") is None else str(get("rate")),
            "currency": get("currency") or "",
            "source_type": get("source_type") or "manual",
            "source_rate": None if get("source_rate") is None else str(get("source_rate")),
            "current_source_rate": None if current is None else str(current.rate),
            "source_found": current is not None,
        }

    async def _context(self, project_id: uuid.UUID, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "project": {"id": str(project_id), "currency": await self.repo.project_currency(project_id)},
            "items": items,
        }

    async def _enforce(
        self, project_id: uuid.UUID, before: list[dict[str, Any]], after: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        from app.core.validation.money_rules import enforce_money_rules  # noqa: PLC0415

        return await enforce_money_rules(
            PROJECT_CATALOGUE_RULE_SET,
            await self._context(project_id, after),
            target_type="project_catalogue",
            target_id=str(project_id),
            project_id=str(project_id),
            before=await self._context(project_id, before),
        )

    async def _snapshot(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        return [self._payload(i) for i in await self.repo.list_for_project(project_id)]

    async def validate(self, project_id: uuid.UUID, locale: str = "en") -> ValidationReportOut:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        items = await self.repo.list_for_project(project_id)
        sources = await self._sources(items)
        payload = await self._context(project_id, [self._payload(i, self._current(i, sources)) for i in items])
        report = await validation_engine.validate(
            data=payload,
            rule_sets=[PROJECT_CATALOGUE_RULE_SET],
            target_type="project_catalogue",
            target_id=str(project_id),
            project_id=str(project_id),
            metadata={"locale": locale},
        )
        failed = [r for r in report.results if not r.passed]
        return ValidationReportOut(
            status=str(report.status.value if hasattr(report.status, "value") else report.status),
            error_count=len(report.errors),
            warning_count=len(report.warnings),
            info_count=len(report.infos),
            findings=[
                Finding(
                    rule_id=r.rule_id,
                    severity=str(r.severity.value if hasattr(r.severity, "value") else r.severity),
                    message=r.message,
                    suggestion=r.suggestion,
                    element_ref=r.element_ref,
                )
                for r in failed
            ],
        )

    # ── Writes ──────────────────────────────────────────────────────────────

    async def create_manual(
        self, project_id: uuid.UUID, data: ItemCreate, actor: uuid.UUID | None
    ) -> tuple[ProjectCatalogueItem, list[dict]]:
        before = await self._snapshot(project_id)
        item = ProjectCatalogueItem(
            project_id=project_id,
            code=data.code.strip(),
            description=data.description.strip(),
            unit=data.unit.strip(),
            item_type=data.item_type,
            rate=data.rate,
            currency=data.currency.strip().upper(),
            note=data.note,
            source_type="manual",
            created_by=actor,
        )
        warnings = await self._enforce(project_id, before, [*before, self._payload(item)])
        return await self.repo.add(item), warnings

    async def import_from_source(
        self, project_id: uuid.UUID, source_type: str, source_ids: list[uuid.UUID], actor: uuid.UUID | None
    ) -> ImportResult:
        existing = {(i.source_type, i.source_id) for i in await self.repo.list_for_project(project_id)}
        if source_type == "cost_item":
            raw = await self.repo.cost_items(str(s) for s in source_ids)
            names = await self.repo.catalog_names(r.catalog_id for r in raw.values())
            rows = [_cost_item_row(r, names) for r in raw.values()]
        else:
            rows = [_resource_row(r) for r in (await self.repo.catalog_resources(str(s) for s in source_ids)).values()]
        now = datetime.now(UTC)
        added: list[ProjectCatalogueItem] = []
        for row in rows:
            if not row.active or (source_type, row.source_id) in existing:
                continue
            item = ProjectCatalogueItem(
                project_id=project_id,
                code=row.code,
                description=row.description,
                unit=row.unit,
                item_type=row.item_type,
                rate=row.rate,
                currency=row.currency,
                source_type=source_type,
                source_id=row.source_id,
                source_label=row.label[:255],
                source_code=row.code,
                source_rate=row.rate,
                source_currency=row.currency,
                source_synced_at=now,
                created_by=actor,
            )
            added.append(await self.repo.add(item))
            existing.add((source_type, row.source_id))
        responses = [await self.item_response(i) for i in added]
        return ImportResult(added=len(added), skipped=len(source_ids) - len(added), items=responses)

    async def update_item(self, item: ProjectCatalogueItem, data: ItemUpdate) -> list[dict]:
        before = await self._snapshot(item.project_id)
        fields = data.model_dump(exclude_unset=True)
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if key == "currency":
                    value = value.upper()
            setattr(item, key, value)
        after = [self._payload(item) if row["id"] == str(item.id) else row for row in before]
        warnings = await self._enforce(item.project_id, before, after)
        await self.repo.flush(item)
        return warnings

    async def delete_item(self, item: ProjectCatalogueItem) -> None:
        await self.repo.delete(item)

    async def sync(self, project_id: uuid.UUID, action: str, item_ids: list[uuid.UUID] | None) -> SyncResult:
        items = await self.repo.list_for_project(project_id)
        if item_ids is not None:
            wanted = {str(i) for i in item_ids}
            items = [i for i in items if str(i.id) in wanted]
        sources = await self._sources(items)
        now = datetime.now(UTC)
        updated = skipped = 0
        for item in items:
            current = self._current(item, sources)
            if current is None:
                skipped += 1
                continue
            st = item_status(
                source_type=item.source_type,
                rate=Decimal(item.rate),
                source_rate=item.source_rate,
                current_source_rate=current.rate,
                source_found=True,
            )
            # "Take source" also resets an override the source never moved under.
            if st is ItemStatus.IN_SYNC or (st is ItemStatus.OVERRIDDEN and action == "keep_local"):
                skipped += 1
                continue
            item.rate, item.source_rate = resolve_sync(
                action, rate=Decimal(item.rate), current_source_rate=current.rate
            )
            if action == "take_source":
                item.currency = current.currency
            item.source_currency = current.currency
            item.source_synced_at = now
            updated += 1
        await self.session.flush()
        return SyncResult(updated=updated, skipped=skipped)

    # ── Sources search ──────────────────────────────────────────────────────

    async def search_sources(
        self, project_id: uuid.UUID, source_type: str, q: str, region: str, offset: int, limit: int
    ) -> SourceSearchResponse:
        if source_type == "cost_item":
            raw, total = await self.repo.search_cost_items(q, region, offset, limit)
            names = await self.repo.catalog_names(r.catalog_id for r in raw)
            rows = [_cost_item_row(r, names) for r in raw]
        else:
            raw, total = await self.repo.search_catalog_resources(q, region, offset, limit)
            rows = [_resource_row(r) for r in raw]
        have = {(i.source_type, i.source_id) for i in await self.repo.list_for_project(project_id)}
        hits = [
            SourceHit(
                source_type=r.source_type,
                source_id=r.source_id,
                code=r.code,
                description=r.description,
                unit=r.unit,
                rate=r.rate,
                currency=r.currency,
                label=r.label,
                already_added=(r.source_type, r.source_id) in have,
            )
            for r in rows
        ]
        return SourceSearchResponse(items=hits, total=total, offset=offset, limit=limit)

    # ── Bill lines ──────────────────────────────────────────────────────────

    async def position_candidates(
        self, item: ProjectCatalogueItem, q: str, same_unit: bool, offset: int, limit: int
    ) -> CandidateListResponse:
        rows = []
        needle = q.casefold()
        unit = (item.unit or "").strip().casefold()
        for position, boq_name in await self.repo.project_positions(item.project_id):
            if not (position.unit or "").strip():
                continue
            if same_unit and unit and (position.unit or "").strip().casefold() != unit:
                continue
            if needle and needle not in (position.description or "").casefold() and needle not in position.ordinal:
                continue
            rows.append(
                PositionCandidate(
                    id=str(position.id),
                    boq_id=str(position.boq_id),
                    boq_name=boq_name,
                    ordinal=position.ordinal,
                    description=position.description or "",
                    unit=position.unit or "",
                    quantity=str(position.quantity or "0"),
                    unit_rate=str(position.unit_rate or "0"),
                    linked_item_id=link_of(position.metadata_),
                )
            )
        return CandidateListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)

    async def _price_position(self, position: Any, item: ProjectCatalogueItem, actor: uuid.UUID | None) -> None:
        from app.modules.boq.schemas import PositionUpdate  # noqa: PLC0415
        from app.modules.boq.service import BOQService  # noqa: PLC0415

        meta = dict(position.metadata_) if isinstance(position.metadata_, dict) else {}
        meta[LINK_KEY] = str(item.id)
        await BOQService(self.session).update_position(
            position.id, PositionUpdate(unit_rate=Decimal(item.rate), metadata=meta), actor_id=actor
        )

    async def apply_to_positions(
        self, item: ProjectCatalogueItem, position_ids: list[uuid.UUID], actor: uuid.UUID | None
    ) -> ApplyResult:
        applied: list[str] = []
        skipped = 0
        for pid in dict.fromkeys(position_ids):
            found = await self.repo.position_project(pid)
            if found is None or found[1] != item.project_id:
                skipped += 1
                continue
            await self._price_position(found[0], item, actor)
            applied.append(str(pid))
        return ApplyResult(applied=len(applied), skipped=skipped, position_ids=applied)

    async def push_to_linked(self, item: ProjectCatalogueItem, actor: uuid.UUID | None) -> ApplyResult:
        """Re-price every bill line this rate priced whose rate no longer matches."""
        applied: list[str] = []
        skipped = 0
        rate = Decimal(item.rate)
        for position in (await self._links(item.project_id)).get(str(item.id), []):
            if (_dec(position.unit_rate) or Decimal(0)).compare(rate) == 0:
                skipped += 1
                continue
            await self._price_position(position, item, actor)
            applied.append(str(position.id))
        return ApplyResult(applied=len(applied), skipped=skipped, position_ids=applied)


def not_found() -> HTTPException:
    """The single 404 the module answers for a missing or foreign id."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project catalogue item not found")
