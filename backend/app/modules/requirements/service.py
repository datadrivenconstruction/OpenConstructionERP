"""Requirements & Quality Gates service​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — business logic.

Stateless service layer. Handles:
- RequirementSet and Requirement CRUD
- Quality gate execution (Completeness, Consistency, Coverage, Compliance)
- Linking requirements to BOQ positions
- Text import parsing
- Statistics aggregation
"""

import logging
import re
import uuid
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.requirements.models import GateResult, Requirement, RequirementSet
from app.modules.requirements.repository import (
    GateResultRepository,
    RequirementRepository,
    RequirementSetRepository,
)
from app.modules.requirements.schemas import (
    RequirementCreate,
    RequirementSetCreate,
    RequirementUpdate,
    TextImportRequest,
)

logger = logging.getLogger(__name__)


async def _safe_publish(name: str, data: dict[str, Any]) -> None:
    """Best-effort event publish — never raises into the calling path.

    The vector indexer in :mod:`app.modules.requirements.events` and any
    future cross-module subscriber consume the events emitted here.
    Failures are logged at debug level only because event publishing
    must never break a successful CRUD or link operation.
    """
    try:
        await event_bus.publish(name, data, source_module="oe_requirements")
    except Exception:
        logger.debug("Failed to publish requirements event '%s'", name, exc_info=True)

# Gate definitions
GATE_NAMES: dict[int, str] = {
    1: "Completeness",
    2: "Consistency",
    3: "Coverage",
    4: "Compliance",
}


class RequirementsService:
    """Business logic for requirements and quality gates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.set_repo = RequirementSetRepository(session)
        self.req_repo = RequirementRepository(session)
        self.gate_repo = GateResultRepository(session)

    # ── RequirementSet CRUD ──────────────────────────────────────────────

    async def create_set(
        self,
        data: RequirementSetCreate,
        user_id: str = "",
    ) -> RequirementSet:
        """Create a new requirement set."""
        item = RequirementSet(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            source_type=data.source_type,
            source_filename=data.source_filename,
            created_by=user_id,
            metadata_=data.metadata,
        )
        item = await self.set_repo.create(item)
        logger.info("RequirementSet created: %s for project %s", item.name, data.project_id)
        return item

    async def get_set(self, set_id: uuid.UUID) -> RequirementSet:
        """Get requirement set by ID. Raises 404 if not found."""
        item = await self.set_repo.get_by_id(set_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Requirement set not found",
            )
        return item

    async def list_sets(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[RequirementSet], int]:
        """List requirement sets for a project."""
        return await self.set_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def update_set(
        self,
        set_id: uuid.UUID,
        fields: dict[str, Any],
    ) -> RequirementSet:
        """Patch fields on an existing requirement set.

        Only known/whitelisted fields are accepted; the caller already
        validated them via the ``RequirementSetUpdate`` Pydantic schema.
        Returns the refreshed ORM row so the router can build a fresh
        response without an extra round-trip.
        """
        item = await self.get_set(set_id)  # 404 if missing

        if not fields:
            return item

        # Whitelist of safely-patchable columns + remap ``metadata`` →
        # ``metadata_`` (the SQLAlchemy attribute) so the schema can
        # use the friendlier public name.
        safe_fields: dict[str, Any] = {}
        for key in (
            "name",
            "description",
            "source_type",
            "source_filename",
            "status",
        ):
            if key in fields and fields[key] is not None:
                safe_fields[key] = fields[key]
        if "metadata" in fields and fields["metadata"] is not None:
            safe_fields["metadata_"] = fields["metadata"]

        if not safe_fields:
            return item

        await self.set_repo.update_fields(set_id, **safe_fields)
        await self.session.refresh(item)
        logger.info(
            "RequirementSet updated: %s (fields=%s)",
            set_id,
            list(safe_fields.keys()),
        )
        return item

    async def delete_set(self, set_id: uuid.UUID) -> None:
        """Delete a requirement set and all its requirements/gate results."""
        await self.get_set(set_id)  # Raises 404 if not found
        await self.set_repo.delete(set_id)
        logger.info("RequirementSet deleted: %s", set_id)

    async def bulk_delete_requirements(
        self,
        set_id: uuid.UUID,
        requirement_ids: list[uuid.UUID],
    ) -> tuple[int, int]:
        """Delete every requirement whose id is in the list.

        Ids that do not exist or belong to a different set are
        silently skipped — but the count is reported so callers can
        flag a "you asked for 100, we deleted 87" mismatch in the UI.

        Runs as a single transaction so a partial delete never leaks
        half the rows on a mid-flight failure.  Each successful delete
        publishes ``requirements.requirement.deleted`` so the vector
        store stays in sync.
        """
        await self.get_set(set_id)  # 404 if set missing

        deleted = 0
        skipped = 0
        for req_id in requirement_ids:
            item = await self.req_repo.get_by_id(req_id)
            if item is None or item.requirement_set_id != set_id:
                skipped += 1
                continue
            await self.req_repo.delete(req_id)
            deleted += 1
            await _safe_publish(
                "requirements.requirement.deleted",
                {
                    "requirement_id": str(req_id),
                    "requirement_set_id": str(set_id),
                },
            )

        logger.info(
            "RequirementSet %s: bulk-deleted %d requirement(s), skipped %d",
            set_id,
            deleted,
            skipped,
        )
        return deleted, skipped

    # ── Requirement CRUD ─────────────────────────────────────────────────

    async def add_requirement(
        self,
        set_id: uuid.UUID,
        data: RequirementCreate,
        user_id: str = "",
    ) -> Requirement:
        """Add a requirement to a set."""
        await self.get_set(set_id)  # Verify set exists

        item = Requirement(
            requirement_set_id=set_id,
            entity=data.entity,
            attribute=data.attribute,
            constraint_type=data.constraint_type,
            constraint_value=data.constraint_value,
            unit=data.unit,
            category=data.category,
            priority=data.priority,
            confidence=str(data.confidence) if data.confidence is not None else None,
            source_ref=data.source_ref,
            notes=data.notes,
            created_by=user_id,
            metadata_=data.metadata,
        )
        item = await self.req_repo.create(item)
        logger.info(
            "Requirement added: %s.%s to set %s",
            data.entity,
            data.attribute,
            set_id,
        )
        await _safe_publish(
            "requirements.requirement.created",
            {
                "requirement_id": str(item.id),
                "requirement_set_id": str(set_id),
            },
        )
        return item

    async def update_requirement(
        self,
        req_id: uuid.UUID,
        data: RequirementUpdate,
    ) -> Requirement:
        """Update a requirement's fields."""
        item = await self.req_repo.get_by_id(req_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Requirement not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return item

        # Convert confidence float to string for storage
        if "confidence" in fields and fields["confidence"] is not None:
            fields["confidence"] = str(fields["confidence"])

        await self.req_repo.update_fields(req_id, **fields)
        await self.session.refresh(item)

        logger.info("Requirement updated: %s (fields=%s)", req_id, list(fields.keys()))
        await _safe_publish(
            "requirements.requirement.updated",
            {
                "requirement_id": str(req_id),
                "requirement_set_id": str(item.requirement_set_id),
            },
        )
        return item

    async def delete_requirement(self, set_id: uuid.UUID, req_id: uuid.UUID) -> None:
        """Delete a requirement from a set."""
        item = await self.req_repo.get_by_id(req_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Requirement not found",
            )
        if item.requirement_set_id != set_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Requirement does not belong to the specified set",
            )
        await self.req_repo.delete(req_id)
        logger.info("Requirement deleted: %s from set %s", req_id, set_id)
        await _safe_publish(
            "requirements.requirement.deleted",
            {
                "requirement_id": str(req_id),
                "requirement_set_id": str(set_id),
            },
        )

    async def bulk_add_requirements(
        self,
        set_id: uuid.UUID,
        items_data: list[RequirementCreate],
        user_id: str = "",
    ) -> list[Requirement]:
        """Bulk add requirements to a set."""
        await self.get_set(set_id)  # Verify set exists

        items = [
            Requirement(
                requirement_set_id=set_id,
                entity=data.entity,
                attribute=data.attribute,
                constraint_type=data.constraint_type,
                constraint_value=data.constraint_value,
                unit=data.unit,
                category=data.category,
                priority=data.priority,
                confidence=(str(data.confidence) if data.confidence is not None else None),
                source_ref=data.source_ref,
                notes=data.notes,
                created_by=user_id,
                metadata_=data.metadata,
            )
            for data in items_data
        ]
        created = await self.req_repo.bulk_create(items)
        logger.info("Bulk added %d requirements to set %s", len(created), set_id)
        return created

    # ── Link to BOQ position ─────────────────────────────────────────────

    async def link_to_position(
        self,
        req_id: uuid.UUID,
        position_id: uuid.UUID,
    ) -> Requirement:
        """Link a requirement to a BOQ position."""
        item = await self.req_repo.get_by_id(req_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Requirement not found",
            )

        # Verify position exists
        from app.modules.boq.models import Position

        position = await self.session.get(Position, position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ position not found",
            )

        await self.req_repo.update_fields(
            req_id,
            linked_position_id=position_id,
            status="linked",
        )
        await self.session.refresh(item)

        logger.info("Requirement %s linked to position %s", req_id, position_id)
        await _safe_publish(
            "requirements.requirement.updated",
            {
                "requirement_id": str(req_id),
                "requirement_set_id": str(item.requirement_set_id),
                "link_type": "boq_position",
                "linked_position_id": str(position_id),
            },
        )
        return item

    # ── Link to BIM elements (cross-module spatial linkage) ──────────────

    async def link_to_bim_elements(
        self,
        req_id: uuid.UUID,
        bim_element_ids: list[str],
        *,
        replace: bool = False,
    ) -> Requirement:
        """Pin a requirement to one or more BIM elements.

        Stores the array under ``metadata_["bim_element_ids"]`` so we
        don't need a schema migration just for this link type.  By
        default the new ids are **merged** with whatever was there
        previously (additive linking — no accidental data loss).  Pass
        ``replace=True`` to overwrite the array entirely.

        After mutation we publish ``requirements.requirement.linked_bim``
        which the events module subscribes to in order to refresh the
        vector embedding (so semantic search reflects the new link).

        Returns the updated row with a refreshed ``metadata_`` snapshot.
        """
        item = await self.req_repo.get_by_id(req_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Requirement not found",
            )

        # Normalise + deduplicate the incoming ids — accept anything that
        # round-trips through str(uuid) so the caller doesn't have to
        # pre-coerce.
        clean_ids: list[str] = []
        seen: set[str] = set()
        for raw in bim_element_ids:
            if raw is None:
                continue
            try:
                cleaned = str(uuid.UUID(str(raw)))
            except (ValueError, AttributeError, TypeError):
                continue
            if cleaned not in seen:
                seen.add(cleaned)
                clean_ids.append(cleaned)

        existing_meta = dict(item.metadata_ or {})
        if replace:
            merged = clean_ids
        else:
            previous = existing_meta.get("bim_element_ids") or []
            previous_clean: list[str] = []
            previous_set: set[str] = set()
            for raw in previous:
                if isinstance(raw, str) and raw and raw not in previous_set:
                    previous_set.add(raw)
                    previous_clean.append(raw)
            # Append-only union, preserving order: existing first, then new.
            merged = previous_clean + [c for c in clean_ids if c not in previous_set]

        existing_meta["bim_element_ids"] = merged
        await self.req_repo.update_fields(
            req_id,
            metadata_=existing_meta,
        )
        await self.session.refresh(item)

        logger.info(
            "Requirement %s linked to %d BIM element(s) (replace=%s)",
            req_id,
            len(merged),
            replace,
        )
        await _safe_publish(
            "requirements.requirement.linked_bim",
            {
                "requirement_id": str(req_id),
                "requirement_set_id": str(item.requirement_set_id),
                "bim_element_ids": merged,
                "replace": replace,
            },
        )
        return item

    async def list_by_bim_element(
        self,
        bim_element_id: str,
        project_id: uuid.UUID | None = None,
    ) -> list[Requirement]:
        """Reverse query: every requirement that pins ``bim_element_id``.

        Used by the BIM viewer's element details panel to render the
        "Linked requirements" section without N+1 queries.  Loads the
        candidate requirements via the project filter (if supplied) so
        we don't scan the whole tenant on every selection click.

        Dialect-aware:

        * **PostgreSQL** — uses the JSONB ``@>`` containment operator
          at the SQL level so the database does the filtering and we
          only ship matching rows over the wire.  This is O(matching)
          instead of O(all-in-project), with a btree-style speedup
          when ``metadata_`` has a GIN index (which the v1.4.7
          migration adds).
        * **SQLite (and any other dialect without JSONB)** — falls
          back to the previous Python-side scan since SQLite has no
          portable JSON-array-contains operator we can rely on across
          versions.

        Dialect detection mirrors the pattern in
        ``tasks/service.py::get_tasks_for_bim_element``.
        """
        target = str(bim_element_id)
        bind = self.session.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "") or ""

        if dialect_name == "postgresql":
            # JSONB ``@>`` containment: rows where metadata_["bim_element_ids"]
            # is a superset of ``[target]``.  Cast metadata_ to JSONB
            # because the column is declared as JSON for cross-dialect
            # parity, but PostgreSQL accepts the cast and applies the
            # JSONB operator afterwards.
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import JSONB

            stmt = select(Requirement).where(
                cast(Requirement.metadata_, JSONB).contains(
                    {"bim_element_ids": [target]}
                )
            )
            if project_id is not None:
                from app.modules.requirements.models import RequirementSet

                stmt = stmt.join(
                    RequirementSet,
                    Requirement.requirement_set_id == RequirementSet.id,
                ).where(RequirementSet.project_id == project_id)
            return list((await self.session.execute(stmt)).scalars().all())

        # SQLite / other: load candidates and filter in Python
        if project_id is not None:
            candidates = await self.req_repo.all_for_project(project_id)
        else:
            stmt = select(Requirement)
            candidates = list((await self.session.execute(stmt)).scalars().all())

        out: list[Requirement] = []
        for req in candidates:
            ids = (req.metadata_ or {}).get("bim_element_ids") or []
            if isinstance(ids, list) and target in {str(x) for x in ids}:
                out.append(req)
        return out

    # ── Quality Gates ────────────────────────────────────────────────────

    async def run_gate(
        self,
        set_id: uuid.UUID,
        gate_number: int,
        user_id: str = "",
    ) -> GateResult:
        """Run a quality gate on a requirement set.

        Gates:
            1 — Completeness: all requirements have entity+attribute+constraint
            2 — Consistency: no conflicting constraints for same entity+attribute
            3 — Coverage: requirements cover BOQ positions (linked_position_id)
            4 — Compliance: requirements align with project standard
        """
        if gate_number not in GATE_NAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid gate number: {gate_number}. Valid: 1-4",
            )

        req_set = await self.get_set(set_id)
        requirements = await self.req_repo.all_for_set(set_id)

        gate_name = GATE_NAMES[gate_number]

        if gate_number == 1:
            gate_status, score, findings = self._run_gate_completeness(requirements)
        elif gate_number == 2:
            gate_status, score, findings = self._run_gate_consistency(requirements)
        elif gate_number == 3:
            gate_status, score, findings = await self._run_gate_coverage(req_set, requirements)
        elif gate_number == 4:
            gate_status, score, findings = self._run_gate_compliance(req_set, requirements)
        else:
            gate_status, score, findings = "skipped", 0.0, []

        # Eagerly capture gate_status before any DB writes expire the ORM object
        current_gate_status = dict(req_set.gate_status or {})

        result = GateResult(
            requirement_set_id=set_id,
            gate_number=gate_number,
            gate_name=gate_name,
            status=gate_status,
            score=float(score),
            findings=findings,
            executed_by=user_id,
        )
        await self.gate_repo.create(result)
        result_id = result.id  # Capture before session expires attributes

        # Update gate_status on the set
        current_gate_status[f"gate{gate_number}"] = gate_status
        await self.set_repo.update_fields(set_id, gate_status=current_gate_status)

        # Commit and re-fetch fresh object for serialization
        await self.session.commit()
        result = await self.gate_repo.get_by_id(result_id)

        logger.info(
            "Gate %d (%s) executed for set %s: %s (score=%.1f)",
            gate_number,
            gate_name,
            set_id,
            gate_status,
            score,
        )
        return result

    def _run_gate_completeness(
        self,
        requirements: list[Requirement],
    ) -> tuple[str, float, list[dict[str, Any]]]:
        """Gate 1: Check all requirements have entity+attribute+constraint filled."""
        findings: list[dict[str, Any]] = []

        if not requirements:
            return "warning", 0.0, [{"type": "empty", "message": "No requirements found"}]

        incomplete_count = 0
        for req in requirements:
            issues: list[str] = []
            if not req.entity or not req.entity.strip():
                issues.append("missing entity")
            if not req.attribute or not req.attribute.strip():
                issues.append("missing attribute")
            if not req.constraint_value or not req.constraint_value.strip():
                issues.append("missing constraint_value")

            if issues:
                incomplete_count += 1
                findings.append(
                    {
                        "type": "incomplete",
                        "requirement_id": str(req.id),
                        "entity": req.entity,
                        "attribute": req.attribute,
                        "issues": issues,
                        "message": f"Requirement '{req.entity}.{req.attribute}' is incomplete: " + ", ".join(issues),
                    }
                )

        total = len(requirements)
        complete_count = total - incomplete_count
        score = round((complete_count / total) * 100, 1) if total > 0 else 0.0

        if incomplete_count == 0:
            gate_status = "pass"
        elif incomplete_count <= total * 0.1:
            gate_status = "warning"
        else:
            gate_status = "fail"

        return gate_status, score, findings

    def _run_gate_consistency(
        self,
        requirements: list[Requirement],
    ) -> tuple[str, float, list[dict[str, Any]]]:
        """Gate 2: Check for conflicting constraints on same entity+attribute."""
        findings: list[dict[str, Any]] = []

        if not requirements:
            return "pass", 100.0, []

        # Group by (entity, attribute)
        groups: dict[tuple[str, str], list[Requirement]] = defaultdict(list)
        for req in requirements:
            key = (req.entity.lower().strip(), req.attribute.lower().strip())
            groups[key].append(req)

        conflict_count = 0
        for (entity, attribute), group in groups.items():
            if len(group) <= 1:
                continue

            # Check for actual conflicts: same constraint_type but different values
            by_type: dict[str, list[Requirement]] = defaultdict(list)
            for req in group:
                by_type[req.constraint_type].append(req)

            for ctype, reqs in by_type.items():
                if len(reqs) <= 1:
                    continue
                values = {r.constraint_value for r in reqs}
                if len(values) > 1:
                    conflict_count += 1
                    findings.append(
                        {
                            "type": "conflict",
                            "entity": entity,
                            "attribute": attribute,
                            "constraint_type": ctype,
                            "conflicting_values": list(values),
                            "requirement_ids": [str(r.id) for r in reqs],
                            "message": (f"Conflict on {entity}.{attribute} ({ctype}): values {values}"),
                        }
                    )

        total_groups = len(groups)
        consistent_groups = total_groups - conflict_count
        score = round((consistent_groups / total_groups) * 100, 1) if total_groups > 0 else 100.0

        if conflict_count == 0:
            gate_status = "pass"
        elif conflict_count <= 2:
            gate_status = "warning"
        else:
            gate_status = "fail"

        return gate_status, score, findings

    async def _run_gate_coverage(
        self,
        req_set: RequirementSet,
        requirements: list[Requirement],
    ) -> tuple[str, float, list[dict[str, Any]]]:
        """Gate 3: Check if requirements cover BOQ positions (linked_position_id)."""
        findings: list[dict[str, Any]] = []

        if not requirements:
            return "warning", 0.0, [{"type": "empty", "message": "No requirements to check coverage"}]

        linked = [r for r in requirements if r.linked_position_id is not None]
        unlinked = [r for r in requirements if r.linked_position_id is None]

        total = len(requirements)
        linked_count = len(linked)
        score = round((linked_count / total) * 100, 1) if total > 0 else 0.0

        if unlinked:
            findings.append(
                {
                    "type": "unlinked_requirements",
                    "count": len(unlinked),
                    "requirement_ids": [str(r.id) for r in unlinked],
                    "message": f"{len(unlinked)} of {total} requirements are not linked to BOQ positions",
                }
            )

        # Check for BOQ positions without any requirements
        from app.modules.boq.models import BOQ, Position

        boq_stmt = select(Position.id).join(BOQ).where(BOQ.project_id == req_set.project_id)
        result = await self.session.execute(boq_stmt)
        all_position_ids = {row[0] for row in result.all()}

        covered_position_ids = {r.linked_position_id for r in linked}
        uncovered = all_position_ids - covered_position_ids

        if uncovered:
            findings.append(
                {
                    "type": "uncovered_positions",
                    "count": len(uncovered),
                    "position_ids": [str(pid) for pid in list(uncovered)[:50]],
                    "message": (f"{len(uncovered)} BOQ positions have no linked requirements"),
                }
            )

        if linked_count == 0:
            gate_status = "fail"
        elif score >= 80.0 and not uncovered:
            gate_status = "pass"
        elif score >= 50.0:
            gate_status = "warning"
        else:
            gate_status = "fail"

        return gate_status, score, findings

    def _run_gate_compliance(
        self,
        req_set: RequirementSet,
        requirements: list[Requirement],
    ) -> tuple[str, float, list[dict[str, Any]]]:
        """Gate 4: Check requirements against project standard (DIN 276, NRM, etc.).

        This is a placeholder that checks basic structural compliance.
        Full standard-specific checks should be added per standard.
        """
        findings: list[dict[str, Any]] = []

        if not requirements:
            return "warning", 0.0, [{"type": "empty", "message": "No requirements to check compliance"}]

        issues_count = 0
        total = len(requirements)

        for req in requirements:
            # Check: must-priority requirements should have a unit
            if req.priority == "must" and not req.unit.strip():
                issues_count += 1
                findings.append(
                    {
                        "type": "missing_unit",
                        "requirement_id": str(req.id),
                        "entity": req.entity,
                        "attribute": req.attribute,
                        "message": (
                            f"Must-priority requirement '{req.entity}.{req.attribute}' lacks a unit of measurement"
                        ),
                    }
                )

            # Check: constraint_type 'range' should have a parseable range value
            if req.constraint_type == "range":
                if not re.match(r"^[\d.]+\s*[-–]\s*[\d.]+$", req.constraint_value):
                    issues_count += 1
                    findings.append(
                        {
                            "type": "invalid_range",
                            "requirement_id": str(req.id),
                            "entity": req.entity,
                            "attribute": req.attribute,
                            "constraint_value": req.constraint_value,
                            "message": (
                                f"Range constraint '{req.constraint_value}' for "
                                f"'{req.entity}.{req.attribute}' is not in 'min-max' format"
                            ),
                        }
                    )

            # Check: numeric constraints (min/max) should have numeric values
            if req.constraint_type in ("min", "max"):
                try:
                    float(req.constraint_value)
                except ValueError:
                    issues_count += 1
                    findings.append(
                        {
                            "type": "non_numeric_constraint",
                            "requirement_id": str(req.id),
                            "entity": req.entity,
                            "attribute": req.attribute,
                            "constraint_value": req.constraint_value,
                            "message": (
                                f"Constraint type '{req.constraint_type}' for "
                                f"'{req.entity}.{req.attribute}' has non-numeric "
                                f"value '{req.constraint_value}'"
                            ),
                        }
                    )

        compliant_count = total - issues_count
        score = round((compliant_count / total) * 100, 1) if total > 0 else 0.0

        if issues_count == 0:
            gate_status = "pass"
        elif issues_count <= total * 0.1:
            gate_status = "warning"
        else:
            gate_status = "fail"

        return gate_status, score, findings

    async def list_gate_results(self, set_id: uuid.UUID) -> list[GateResult]:
        """List all gate results for a requirement set."""
        await self.get_set(set_id)  # Verify set exists
        return await self.gate_repo.list_for_set(set_id)

    # ── Text Import ──────────────────────────────────────────────────────

    async def import_from_text(
        self,
        set_id: uuid.UUID,
        data: TextImportRequest,
        user_id: str = "",
    ) -> RequirementSet:
        """Parse structured text and add requirements to an EXISTING set.

        Expected text format (one requirement per line):
            entity | attribute | constraint_type | constraint_value | unit
        OR simple format:
            entity | attribute | constraint_value

        Lines starting with '#' are comments. Empty lines are skipped.
        """
        req_set = await self.get_set(set_id)
        set_id_val = req_set.id

        # Parse text
        items: list[Requirement] = []
        lines = data.text.strip().split("\n")
        parse_errors: list[str] = []

        for line_num, line in enumerate(lines, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split("|")]

            if len(parts) >= 5:
                # Full format: entity | attribute | constraint_type | value | unit
                entity, attribute, constraint_type, constraint_value, unit = (
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                    parts[4],
                )
            elif len(parts) >= 3:
                # Simple format: entity | attribute | value
                entity, attribute, constraint_value = parts[0], parts[1], parts[2]
                constraint_type = "equals"
                unit = ""
            else:
                parse_errors.append(f"Line {line_num}: not enough fields (need 3+)")
                continue

            if not entity or not attribute or not constraint_value:
                parse_errors.append(f"Line {line_num}: empty required field")
                continue

            items.append(
                Requirement(
                    requirement_set_id=set_id_val,
                    entity=entity,
                    attribute=attribute,
                    constraint_type=constraint_type,
                    constraint_value=constraint_value,
                    unit=unit,
                    category=data.default_category,
                    priority=data.default_priority,
                    source_ref=f"text_import:line_{line_num}",
                    created_by=user_id,
                )
            )

        if items:
            await self.req_repo.bulk_create(items)

        # Store parse errors in metadata
        if parse_errors:
            await self.set_repo.update_fields(
                req_set.id,
                metadata_={"parse_errors": parse_errors, "lines_total": len(lines)},
            )

        logger.info(
            "Imported %d requirements from text into set %s (errors: %d)",
            len(items),
            req_set.id,
            len(parse_errors),
        )

        # Commit and re-fetch to load all relationships cleanly
        await self.session.commit()
        return await self.get_set(set_id_val)

    # ── Statistics ───────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's requirements."""
        requirements = await self.req_repo.all_for_project(project_id)
        set_count = await self.set_repo.count_for_project(project_id)

        by_status: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        linked_count = 0
        unlinked_count = 0

        for req in requirements:
            by_status[req.status] = by_status.get(req.status, 0) + 1
            by_category[req.category] = by_category.get(req.category, 0) + 1
            by_priority[req.priority] = by_priority.get(req.priority, 0) + 1

            if req.linked_position_id is not None:
                linked_count += 1
            else:
                unlinked_count += 1

        return {
            "total_requirements": len(requirements),
            "total_sets": set_count,
            "by_status": by_status,
            "by_category": by_category,
            "by_priority": by_priority,
            "linked_count": linked_count,
            "unlinked_count": unlinked_count,
        }
