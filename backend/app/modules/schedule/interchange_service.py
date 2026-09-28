# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ORM-facing export / import for lossless schedule interchange (T1.1).

Wraps :class:`ScheduleService` (reusing its repos and the canonical
dependency-mirror rebuild) and delegates all format / repair logic to the pure
``schedule_interchange`` and ``schedule_clean`` modules. Access is checked the
same way as the rest of the schedule module: export verifies the source
schedule's project, import verifies the target project, both via
``verify_project_access`` (404 on a cross-tenant id).

Import always mints fresh ids. It runs in three passes so the activity graph
re-links correctly even though every id changes:

1. create every activity, recording ``document ref -> new id``;
2. set ``parent_id`` from the ref map (second pass, parents may appear after
   children in the document);
3. create the relationship rows from the ref map, then rebuild each touched
   activity's derived ``dependencies`` JSON from the canonical edges.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import verify_project_access
from app.modules.schedule.models import Activity, Schedule, ScheduleRelationship
from app.modules.schedule.schedule_clean import CleanAction, CleanResult, clean_document
from app.modules.schedule.schedule_interchange import (
    VALID_RELATIONSHIP_TYPES,
    InterchangeError,
    ParsedDocument,
    build_export_document,
    parse_document,
    validate_document,
)
from app.modules.schedule.service import ScheduleService


def _to_decimal(value: Any) -> Decimal | None:
    """Parse a money / quantity string back to Decimal (never raises)."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_uuid(value: Any) -> uuid.UUID | None:
    """Parse an id-ish value to UUID, tolerating junk (returns ``None``)."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class ScheduleInterchangeService:
    """Lossless export / import of a schedule via the neutral interchange format."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base = ScheduleService(session)

    # ── Export ──────────────────────────────────────────────────────────────

    async def export_schedule(self, schedule_id: uuid.UUID, user_id: str) -> dict[str, Any]:
        """Build the canonical interchange document for one schedule (404-guarded)."""
        schedule = await self.base.get_schedule(schedule_id)
        await verify_project_access(schedule.project_id, user_id, self.session)
        activities = await self._all_activities(schedule_id)
        relationships = await self.base.relationship_repo.list_for_schedule(schedule_id)
        return build_export_document(schedule, activities, relationships)

    async def _all_activities(self, schedule_id: uuid.UUID) -> list[Activity]:
        """Page through every activity of a schedule, preserving sort order."""
        out: list[Activity] = []
        offset, page = 0, 1000
        while True:
            rows, total = await self.base.activity_repo.list_for_schedule(schedule_id, offset=offset, limit=page)
            out.extend(rows)
            offset += page
            if not rows or offset >= total:
                break
        return out

    # ── Clean preview (dry run) ───────────────────────────────────────────────

    async def clean_preview(self, schedule_id: uuid.UUID, user_id: str) -> CleanResult:
        """Report what normalise-on-import would change for a live schedule."""
        document = await self.export_schedule(schedule_id, user_id)
        return clean_document(parse_document(document))

    # ── Import ────────────────────────────────────────────────────────────────

    async def import_schedule(
        self,
        project_id: uuid.UUID,
        raw_document: Any,
        user_id: str,
        *,
        clean: bool = True,
        name_override: str | None = None,
    ) -> tuple[Schedule, dict[str, uuid.UUID], int, list[CleanAction], dict[str, int]]:
        """Create a new schedule from an interchange document (target-project guarded).

        Returns ``(schedule, ref_map, relationship_count, clean_actions, stats)``.
        """
        await verify_project_access(project_id, user_id, self.session)

        try:
            parsed = parse_document(raw_document)
        except InterchangeError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

        actions: list[CleanAction] = []
        stats: dict[str, int] = {}
        if clean:
            result = clean_document(parsed)
            parsed = result.document
            actions = result.actions
            stats = result.stats
        else:
            issues = validate_document(parsed)
            if issues:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="document has unresolved problems; import with clean=true or fix: " + "; ".join(issues[:10]),
                )

        schedule = await self._create_schedule(project_id, parsed, user_id, name_override)
        ref_map, objs = await self._create_activities(schedule.id, parsed)
        rel_count = await self._create_relationships(schedule.id, parsed, ref_map, objs)
        return schedule, ref_map, rel_count, actions, stats

    async def _create_schedule(
        self,
        project_id: uuid.UUID,
        parsed: ParsedDocument,
        user_id: str,
        name_override: str | None,
    ) -> Schedule:
        sd = parsed.schedule
        schedule = Schedule(
            project_id=project_id,
            name=(name_override or sd.get("name") or "Imported schedule"),
            schedule_type=sd.get("schedule_type") or "master",
            description=sd.get("description") or "",
            start_date=sd.get("start_date"),
            end_date=sd.get("end_date"),
            status=sd.get("status") or "draft",
            data_date=sd.get("data_date"),
            created_by=_to_uuid(user_id),
            metadata_=dict(sd.get("metadata") or {}),
        )
        return await self.base.schedule_repo.create(schedule)

    async def _create_activities(
        self,
        schedule_id: uuid.UUID,
        parsed: ParsedDocument,
    ) -> tuple[dict[str, uuid.UUID], dict[str, Activity]]:
        ref_map: dict[str, uuid.UUID] = {}
        objs: dict[str, Activity] = {}

        for ad in parsed.activities:
            ref = ad.get("ref")
            activity = Activity(
                schedule_id=schedule_id,
                name=ad.get("name") or "",
                description=ad.get("description") or "",
                wbs_code=ad.get("wbs_code") or "",
                start_date=ad.get("start_date") or "",
                end_date=ad.get("end_date") or "",
                duration_days=max(0, _int_or_none(ad.get("duration_days")) or 0),
                progress_pct=str(ad.get("progress_pct")) if ad.get("progress_pct") is not None else "0",
                status=ad.get("status") or "not_started",
                activity_type=ad.get("activity_type") or "task",
                dependencies=[],
                resources=list(ad.get("resources") or []),
                boq_position_ids=[str(b) for b in (ad.get("boq_position_ids") or [])],
                color=ad.get("color") or "#0071e3",
                sort_order=_int_or_none(ad.get("sort_order")) or 0,
                early_start=ad.get("early_start"),
                early_finish=ad.get("early_finish"),
                late_start=ad.get("late_start"),
                late_finish=ad.get("late_finish"),
                total_float=_int_or_none(ad.get("total_float")),
                free_float=_int_or_none(ad.get("free_float")),
                is_critical=bool(ad.get("is_critical")),
                constraint_type=ad.get("constraint_type"),
                constraint_date=ad.get("constraint_date"),
                activity_code=ad.get("activity_code"),
                bim_element_ids=(
                    list(ad.get("bim_element_ids")) if isinstance(ad.get("bim_element_ids"), list) else None
                ),
                metadata_=dict(ad.get("metadata") or {}),
                cost_planned=_to_decimal(ad.get("cost_planned")),
                cost_actual=_to_decimal(ad.get("cost_actual")),
                percent_complete_type=ad.get("percent_complete_type") or "physical",
                remaining_duration=_int_or_none(ad.get("remaining_duration")),
                budgeted_units=_to_decimal(ad.get("budgeted_units")),
                installed_units=_to_decimal(ad.get("installed_units")),
                calendar_id=_to_uuid(ad.get("calendar_id")),
                suspended_at=ad.get("suspended_at"),
                resumed_at=ad.get("resumed_at"),
                suspend_reason=ad.get("suspend_reason"),
            )
            created = await self.base.activity_repo.create(activity)
            if isinstance(ref, str) and ref:
                ref_map[ref] = created.id
                objs[ref] = created

        # Pass 2: re-link parents now that every ref has an id.
        for ad in parsed.activities:
            ref = ad.get("ref")
            parent_ref = ad.get("parent_ref")
            if parent_ref and isinstance(ref, str) and ref in objs and parent_ref in ref_map:
                objs[ref].parent_id = ref_map[parent_ref]
        await self.session.flush()

        return ref_map, objs

    async def _create_relationships(
        self,
        schedule_id: uuid.UUID,
        parsed: ParsedDocument,
        ref_map: dict[str, uuid.UUID],
        objs: dict[str, Activity],
    ) -> int:
        objs_by_id = {ref_map[ref]: obj for ref, obj in objs.items() if ref in ref_map}
        successors_with_edges: set[uuid.UUID] = set()
        seen_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
        count = 0

        for rd in parsed.relationships:
            pred = ref_map.get(rd.get("predecessor_ref"))
            succ = ref_map.get(rd.get("successor_ref"))
            if pred is None or succ is None or pred == succ:
                continue
            pair = (pred, succ)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            rtype = str(rd.get("relationship_type") or "FS").upper()
            if rtype not in VALID_RELATIONSHIP_TYPES:
                rtype = "FS"
            await self.base.relationship_repo.create(
                ScheduleRelationship(
                    schedule_id=schedule_id,
                    predecessor_id=pred,
                    successor_id=succ,
                    relationship_type=rtype,
                    lag_days=_int_or_none(rd.get("lag_days")) or 0,
                    metadata_=dict(rd.get("metadata") or {}),
                )
            )
            successors_with_edges.add(succ)
            count += 1

        await self.session.flush()

        # Rebuild the derived dependency mirror so Activity.dependencies agrees
        # with the canonical relationship rows (matches create_activity).
        for succ_id in successors_with_edges:
            derived = await self.base._derive_dependencies_json(succ_id)
            obj = objs_by_id.get(succ_id)
            if obj is not None:
                obj.dependencies = derived
        await self.session.flush()

        return count
