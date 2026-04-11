"""BIM Hub service — business logic for BIM data management.

Stateless service layer. Handles:
- BIM model CRUD
- Element bulk import (for CAD pipeline results)
- BOQ link management
- Quantity map rules application
- Model diff calculation (compare elements by stable_id + geometry_hash)
"""

import fnmatch
import logging
import shutil
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.bim_hub.models import (
    BIMElement,
    BIMModel,
    BIMModelDiff,
    BIMQuantityMap,
    BOQElementLink,
)
from app.modules.bim_hub.repository import (
    BIMElementRepository,
    BIMModelDiffRepository,
    BIMModelRepository,
    BIMQuantityMapRepository,
    BOQElementLinkRepository,
)
from app.modules.bim_hub.schemas import (
    BIMElementCreate,
    BIMModelCreate,
    BIMModelUpdate,
    BIMQuantityMapCreate,
    BIMQuantityMapUpdate,
    BOQElementLinkCreate,
    QuantityMapApplyRequest,
    QuantityMapApplyResult,
)
from app.modules.boq.models import BOQ, Position

logger = logging.getLogger(__name__)

# On-disk directory for BIM geometry files (original.{ext}, geometry.dae,
# dataframe.xlsx, …). Matches the layout used by ``bim_hub.router`` which
# writes to ``<repo>/data/bim/{project_id}/{model_id}/``.
#
# ``service.py`` → ``app/modules/bim_hub/service.py`` → parents[4] == repo root
_BIM_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "bim"


class BIMHubService:
    """Business logic for BIM Hub operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.model_repo = BIMModelRepository(session)
        self.element_repo = BIMElementRepository(session)
        self.link_repo = BOQElementLinkRepository(session)
        self.qmap_repo = BIMQuantityMapRepository(session)
        self.diff_repo = BIMModelDiffRepository(session)

    # ── BIM Model CRUD ───────────────────────────────────────────────────────

    async def create_model(
        self,
        data: BIMModelCreate,
        user_id: str | None = None,
    ) -> BIMModel:
        """Create a new BIM model record."""
        model = BIMModel(
            project_id=data.project_id,
            name=data.name,
            discipline=data.discipline,
            model_format=data.model_format,
            version=data.version,
            import_date=data.import_date,
            status=data.status,
            bounding_box=data.bounding_box,
            original_file_id=data.original_file_id,
            canonical_file_path=data.canonical_file_path,
            parent_model_id=data.parent_model_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        model = await self.model_repo.create(model)
        logger.info("BIM model created: %s (project=%s)", data.name, data.project_id)
        return model

    async def get_model(self, model_id: uuid.UUID) -> BIMModel:
        """Get a BIM model by ID. Raises 404 if not found."""
        model = await self.model_repo.get(model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )
        return model

    async def list_models(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BIMModel], int]:
        """List BIM models for a project."""
        return await self.model_repo.list_for_project(project_id, offset=offset, limit=limit)

    async def update_model(
        self,
        model_id: uuid.UUID,
        data: BIMModelUpdate,
    ) -> BIMModel:
        """Update a BIM model's fields."""
        await self.get_model(model_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return await self.get_model(model_id)

        await self.model_repo.update_fields(model_id, **fields)
        updated = await self.model_repo.get(model_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found after update",
            )
        logger.info("BIM model updated: %s (fields=%s)", model_id, list(fields.keys()))
        return updated

    async def delete_model(self, model_id: uuid.UUID) -> None:
        """Delete a BIM model, all its elements, and on-disk geometry files.

        Disk cleanup is best-effort — a failure to remove the directory MUST
        NOT fail the delete operation (the DB row is already gone and the
        orphan sweeper can pick up any stragglers later).
        """
        model = await self.get_model(model_id)  # 404 check
        project_id = model.project_id
        await self.model_repo.delete(model_id)
        logger.info("BIM model deleted: %s", model_id)

        # Best-effort disk cleanup (after DB delete so we never strand files
        # belonging to a still-live DB row).
        geo_dir = _BIM_DATA_DIR / str(project_id) / str(model_id)
        try:
            if geo_dir.is_dir():
                shutil.rmtree(geo_dir, ignore_errors=True)
                logger.info("BIM geometry dir removed: %s", geo_dir)
        except Exception as exc:  # noqa: BLE001 — disk I/O must never block delete
            logger.warning(
                "Failed to remove BIM geometry dir %s: %s", geo_dir, exc
            )

    async def cleanup_orphan_bim_files(self) -> dict[str, Any]:
        """Scan ``data/bim/`` and remove directories with no matching DB row.

        Walks ``data/bim/{project_id}/{model_id}/`` and deletes any model
        directory whose ``model_id`` is not present in the ``oe_bim_models``
        table. Also removes empty ``project_id`` directories.

        Returns a summary with the count of removed model dirs and bytes
        reclaimed. Called from the admin-only
        ``POST /api/v1/bim_hub/cleanup-orphans/`` endpoint.
        """
        if not _BIM_DATA_DIR.is_dir():
            return {"scanned": 0, "removed_models": 0, "removed_projects": 0, "bytes_freed": 0}

        # Load all known model ids from the DB in a single query.
        from app.modules.bim_hub.models import BIMModel

        result = await self.session.execute(select(BIMModel.id))
        known_ids = {str(row[0]) for row in result.all()}

        scanned = 0
        removed_models = 0
        removed_projects = 0
        bytes_freed = 0
        removed_details: list[str] = []

        for project_dir in _BIM_DATA_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            for model_dir in project_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                scanned += 1
                if model_dir.name in known_ids:
                    continue
                # Orphan — compute size then remove.
                try:
                    size = sum(
                        f.stat().st_size
                        for f in model_dir.rglob("*")
                        if f.is_file()
                    )
                except OSError:
                    size = 0
                try:
                    shutil.rmtree(model_dir, ignore_errors=True)
                    removed_models += 1
                    bytes_freed += size
                    removed_details.append(str(model_dir))
                    logger.info(
                        "Orphan BIM dir removed: %s (%d bytes)", model_dir, size
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to remove orphan %s: %s", model_dir, exc)
            # Drop now-empty project directories.
            try:
                if not any(project_dir.iterdir()):
                    project_dir.rmdir()
                    removed_projects += 1
            except OSError:
                pass

        return {
            "scanned": scanned,
            "removed_models": removed_models,
            "removed_projects": removed_projects,
            "bytes_freed": bytes_freed,
            "removed": removed_details,
        }

    async def cleanup_stale_processing(
        self,
        project_id: uuid.UUID,
        max_age_hours: int = 1,
    ) -> int:
        """Remove models stuck in 'processing' with 0 elements older than max_age_hours."""
        count = await self.model_repo.cleanup_stale_processing(
            project_id, max_age_hours=max_age_hours
        )
        if count:
            logger.info(
                "Cleaned up %d stale processing model(s) for project %s",
                count,
                project_id,
            )
        return count

    # ── BIM Elements ─────────────────────────────────────────────────────────

    async def list_elements(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BIMElement], int]:
        """List elements for a model with optional filters."""
        await self.get_model(model_id)  # 404 check
        return await self.element_repo.list_for_model(
            model_id,
            element_type=element_type,
            storey=storey,
            discipline=discipline,
            offset=offset,
            limit=limit,
        )

    async def list_elements_with_links(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BIMElement], int, dict[uuid.UUID, list[dict[str, Any]]]]:
        """List elements AND their BOQElementLink briefs in two SQL round trips.

        Returns ``(elements, total, links_by_element_id)`` where each brief
        is a plain dict with the fields expected by ``BOQElementLinkBrief``
        (id, boq_position_id, boq_position_ordinal, boq_position_description,
        link_type, confidence).

        This avoids an N+1 (one query per element for links + one for each
        linked position) by issuing:
            1. A single SELECT on BIMElement with ``selectinload(boq_links)``.
            2. A single SELECT on Position for all distinct linked position ids.
        """
        await self.get_model(model_id)  # 404 check

        # ── Step 1: load elements with links eagerly ────────────────────
        base = select(BIMElement).where(BIMElement.model_id == model_id)
        if element_type is not None:
            base = base.where(BIMElement.element_type == element_type)
        if storey is not None:
            base = base.where(BIMElement.storey == storey)
        if discipline is not None:
            base = base.where(BIMElement.discipline == discipline)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.options(selectinload(BIMElement.boq_links))
            .order_by(BIMElement.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        elements = list(result.scalars().all())

        # ── Step 2: fetch ordinals/descriptions for every linked position
        pos_ids: set[uuid.UUID] = set()
        for elem in elements:
            for lnk in elem.boq_links or []:
                pos_ids.add(lnk.boq_position_id)

        pos_info: dict[uuid.UUID, tuple[str | None, str | None]] = {}
        if pos_ids:
            pos_stmt = select(
                Position.id, Position.ordinal, Position.description
            ).where(Position.id.in_(pos_ids))
            pos_result = await self.session.execute(pos_stmt)
            for pid, ordinal, desc in pos_result.all():
                pos_info[pid] = (ordinal, desc)

        # ── Step 3: build brief dicts per element ───────────────────────
        links_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for elem in elements:
            briefs: list[dict[str, Any]] = []
            for lnk in elem.boq_links or []:
                ordinal, desc = pos_info.get(lnk.boq_position_id, (None, None))
                briefs.append(
                    {
                        "id": lnk.id,
                        "boq_position_id": lnk.boq_position_id,
                        "boq_position_ordinal": ordinal,
                        "boq_position_description": desc,
                        "link_type": lnk.link_type,
                        "confidence": lnk.confidence,
                    }
                )
            links_by_element_id[elem.id] = briefs

        return elements, total, links_by_element_id

    async def get_element(self, element_id: uuid.UUID) -> BIMElement:
        """Get a single element by ID. Raises 404 if not found."""
        element = await self.element_repo.get(element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )
        return element

    async def bulk_import_elements(
        self,
        model_id: uuid.UUID,
        elements_data: list[BIMElementCreate],
    ) -> list[BIMElement]:
        """Bulk import elements for a model (from CAD pipeline results).

        Replaces all existing elements for the model and updates
        element_count on the model record.
        """
        model = await self.get_model(model_id)

        # Delete existing elements
        deleted = await self.element_repo.delete_all_for_model(model_id)
        if deleted:
            logger.info("Deleted %d existing elements for model %s", deleted, model_id)

        # Create new elements
        elements = [
            BIMElement(
                model_id=model_id,
                stable_id=e.stable_id,
                element_type=e.element_type,
                name=e.name,
                storey=e.storey,
                discipline=e.discipline,
                properties=e.properties,
                quantities=e.quantities,
                geometry_hash=e.geometry_hash,
                bounding_box=e.bounding_box,
                mesh_ref=e.mesh_ref,
                lod_variants=e.lod_variants,
                metadata_=e.metadata,
            )
            for e in elements_data
        ]
        created = await self.element_repo.bulk_create(elements)

        # Compute unique storeys
        storeys = {e.storey for e in created if e.storey}

        # Update model counts
        await self.model_repo.update_fields(
            model_id,
            element_count=len(created),
            storey_count=len(storeys),
            status="active",
        )

        logger.info(
            "Bulk imported %d elements for model %s (%d storeys)",
            len(created),
            model.name,
            len(storeys),
        )
        return created

    # ── BOQ Links ────────────────────────────────────────────────────────────

    async def list_links_for_position(
        self,
        boq_position_id: uuid.UUID,
    ) -> list[BOQElementLink]:
        """List all BIM element links for a BOQ position."""
        return await self.link_repo.list_by_boq_position(boq_position_id)

    async def create_link(
        self,
        data: BOQElementLinkCreate,
        user_id: str | None = None,
    ) -> BOQElementLink:
        """Create a link between a BOQ position and a BIM element.

        Also mirrors the BIM element id into ``Position.cad_element_ids``
        so legacy consumers that read that JSON array stay in sync with
        the canonical ``oe_bim_boq_link`` table.
        """
        # Verify element exists
        element = await self.element_repo.get(data.bim_element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )

        link = BOQElementLink(
            boq_position_id=data.boq_position_id,
            bim_element_id=data.bim_element_id,
            link_type=data.link_type,
            confidence=data.confidence,
            rule_id=data.rule_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        link = await self.link_repo.create(link)

        # Keep Position.cad_element_ids in sync (legacy JSON mirror).
        await self._append_cad_element_id(
            data.boq_position_id, data.bim_element_id
        )

        logger.info(
            "BOQ-BIM link created: pos=%s elem=%s type=%s",
            data.boq_position_id,
            data.bim_element_id,
            data.link_type,
        )
        return link

    async def delete_link(self, link_id: uuid.UUID) -> None:
        """Delete a BOQ-BIM link and drop the mirrored id from the position."""
        link = await self.link_repo.get(link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ-BIM link not found",
            )
        position_id = link.boq_position_id
        element_id = link.bim_element_id
        await self.link_repo.delete(link_id)

        # Remove the mirrored id from Position.cad_element_ids.
        await self._remove_cad_element_id(position_id, element_id)

        logger.info("BOQ-BIM link deleted: %s", link_id)

    # ── cad_element_ids sync helpers ─────────────────────────────────────

    async def _append_cad_element_id(
        self,
        position_id: uuid.UUID,
        element_id: uuid.UUID,
    ) -> None:
        """Append ``element_id`` to ``Position.cad_element_ids`` if missing.

        Initialises the array when the column is NULL (legacy rows) and
        skips duplicates. No-op when the position no longer exists — the
        caller is responsible for verifying position existence beforehand.
        """
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return
        current = list(pos.cad_element_ids or [])
        elem_str = str(element_id)
        if elem_str not in current:
            current.append(elem_str)
            pos.cad_element_ids = current
            # Re-assign to force SQLAlchemy to notice the mutation on JSON.
            await self.session.flush()

    async def _remove_cad_element_id(
        self,
        position_id: uuid.UUID,
        element_id: uuid.UUID,
    ) -> None:
        """Remove ``element_id`` from ``Position.cad_element_ids`` if present."""
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return
        current = list(pos.cad_element_ids or [])
        elem_str = str(element_id)
        if elem_str in current:
            current.remove(elem_str)
            pos.cad_element_ids = current
            await self.session.flush()

    # ── Quantity Maps ────────────────────────────────────────────────────────

    async def list_quantity_maps(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[BIMQuantityMap], int]:
        """List all quantity mapping rules."""
        return await self.qmap_repo.list_all(offset=offset, limit=limit)

    async def create_quantity_map(
        self,
        data: BIMQuantityMapCreate,
    ) -> BIMQuantityMap:
        """Create a new quantity mapping rule."""
        qmap = BIMQuantityMap(
            org_id=data.org_id,
            project_id=data.project_id,
            name=data.name,
            name_translations=data.name_translations,
            element_type_filter=data.element_type_filter,
            property_filter=data.property_filter,
            quantity_source=data.quantity_source,
            multiplier=data.multiplier,
            unit=data.unit,
            waste_factor_pct=data.waste_factor_pct,
            boq_target=data.boq_target,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        qmap = await self.qmap_repo.create(qmap)
        logger.info("Quantity map created: %s (source=%s)", data.name, data.quantity_source)
        return qmap

    async def update_quantity_map(
        self,
        map_id: uuid.UUID,
        data: BIMQuantityMapUpdate,
    ) -> BIMQuantityMap:
        """Update a quantity mapping rule."""
        existing = await self.qmap_repo.get(map_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quantity map rule not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return existing

        await self.qmap_repo.update_fields(map_id, **fields)
        updated = await self.qmap_repo.get(map_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quantity map rule not found after update",
            )
        return updated

    async def apply_quantity_maps(
        self,
        request: QuantityMapApplyRequest,
    ) -> QuantityMapApplyResult:
        """Apply quantity mapping rules to all elements in a model.

        Two modes, selected by ``request.dry_run``:

        **dry_run=True (default)** — compute and return a preview only.
            No ``BOQElementLink`` rows and no ``Position`` rows are created.
            ``links_created`` and ``positions_created`` stay at 0.

        **dry_run=False** — actually persist the result:
            * For every rule with a resolvable ``boq_target``, create a
              ``BOQElementLink`` (link_type="rule_based", confidence="high",
              rule_id=rule.id) for each matched element, skipping any
              (position_id, element_id) pair that already exists.
            * If a rule's ``boq_target`` does not resolve to an existing
              position **and** the target dict has ``auto_create: True``,
              a new ``Position`` is inserted into the project's first BOQ
              with quantity = Σ(adjusted quantity across matched elements)
              and then the links are created against the new position.
            * Each rule's writes run inside a single savepoint
              (``session.begin_nested``) — a failure while processing one
              rule rolls that rule back cleanly without aborting the
              others or the outer request transaction.
            * Also keeps ``Position.cad_element_ids`` in sync via
              ``_append_cad_element_id``.
        """
        model = await self.get_model(request.model_id)

        # Get all elements for the model
        elements, _ = await self.element_repo.list_for_model(
            model.id, offset=0, limit=50000
        )

        # Get active rules (project-scoped first, then global)
        rules = await self.qmap_repo.list_active(project_id=model.project_id)

        # ── Step 1: compute matches per rule (same math regardless of
        # dry_run so the preview stays identical across modes). ───────────
        per_rule_matches: dict[uuid.UUID, list[tuple[BIMElement, Decimal, Decimal]]] = {}
        results: list[dict[str, Any]] = []
        matched_element_ids: set[uuid.UUID] = set()

        for element in elements:
            for rule in rules:
                if not self._rule_matches_element(rule, element):
                    continue

                qty = self._extract_quantity(element, rule.quantity_source)
                if qty is None:
                    continue

                try:
                    multiplier = Decimal(rule.multiplier or "1")
                    waste_pct = Decimal(rule.waste_factor_pct or "0")
                    adjusted = qty * multiplier * (Decimal("1") + waste_pct / Decimal("100"))
                except (InvalidOperation, ValueError):
                    continue

                per_rule_matches.setdefault(rule.id, []).append(
                    (element, qty, adjusted)
                )
                matched_element_ids.add(element.id)

                results.append({
                    "element_id": str(element.id),
                    "stable_id": element.stable_id,
                    "element_type": element.element_type,
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "quantity_source": rule.quantity_source,
                    "raw_quantity": float(qty),
                    "adjusted_quantity": float(adjusted),
                    "unit": rule.unit,
                    "boq_target": rule.boq_target,
                })

        matched_elements = len(matched_element_ids)
        rules_applied = sum(1 for matches in per_rule_matches.values() if matches)
        links_created = 0
        positions_created = 0

        # ── Step 2: persist (only when dry_run is False) ───────────────
        if not request.dry_run and per_rule_matches:
            rules_by_id = {rule.id: rule for rule in rules}
            for rule_id, matches in per_rule_matches.items():
                rule = rules_by_id.get(rule_id)
                if rule is None or not matches:
                    continue

                try:
                    async with self.session.begin_nested():
                        created_links, created_positions = (
                            await self._persist_rule_matches(
                                rule=rule,
                                model=model,
                                matches=matches,
                            )
                        )
                        links_created += created_links
                        positions_created += created_positions
                except Exception:  # noqa: BLE001 — per-rule isolation
                    logger.exception(
                        "Failed to persist quantity map rule %s on model %s",
                        rule_id,
                        model.id,
                    )
                    # Savepoint already rolled back; continue with next rule.

        logger.info(
            "Quantity maps applied: %d elements matched, %d rules applied, "
            "%d links created, %d positions created for model %s (dry_run=%s)",
            matched_elements,
            rules_applied,
            links_created,
            positions_created,
            model.name,
            request.dry_run,
        )

        return QuantityMapApplyResult(
            matched_elements=matched_elements,
            rules_applied=rules_applied,
            links_created=links_created,
            positions_created=positions_created,
            results=results,
        )

    async def _persist_rule_matches(
        self,
        *,
        rule: BIMQuantityMap,
        model: BIMModel,
        matches: list[tuple[BIMElement, Decimal, Decimal]],
    ) -> tuple[int, int]:
        """Create BOQElementLink (and optionally a Position) for one rule.

        Called from ``apply_quantity_maps`` inside a savepoint. Returns
        ``(links_created, positions_created)``.
        """
        if not matches:
            return 0, 0

        target = rule.boq_target or {}
        if not isinstance(target, dict):
            logger.warning(
                "Rule %s has non-dict boq_target; skipping persistence", rule.id
            )
            return 0, 0

        # ── Resolve the target Position ───────────────────────────────
        position = await self._resolve_boq_target_position(
            target=target,
            project_id=model.project_id,
        )
        positions_created = 0

        if position is None:
            if not target.get("auto_create"):
                logger.info(
                    "Rule %s: boq_target unresolved and auto_create is false; skipping",
                    rule.id,
                )
                return 0, 0

            position = await self._auto_create_position_for_rule(
                rule=rule,
                project_id=model.project_id,
                matches=matches,
            )
            if position is None:
                return 0, 0
            positions_created = 1

        # ── Create links for every matched element ────────────────────
        links_created = 0
        existing_elem_ids = await self._existing_link_element_ids(position.id)

        for element, _raw, _adjusted in matches:
            if element.id in existing_elem_ids:
                continue  # idempotent — dup UNIQUE would 500 us otherwise

            link = BOQElementLink(
                boq_position_id=position.id,
                bim_element_id=element.id,
                link_type="rule_based",
                confidence="high",
                rule_id=str(rule.id),
                metadata_={},
            )
            try:
                await self.link_repo.create(link)
            except IntegrityError:
                # Race with a concurrent writer — treat as already linked.
                logger.debug(
                    "IntegrityError creating link pos=%s elem=%s (treated as duplicate)",
                    position.id,
                    element.id,
                )
                continue

            await self._append_cad_element_id(position.id, element.id)
            existing_elem_ids.add(element.id)
            links_created += 1

        return links_created, positions_created

    async def _resolve_boq_target_position(
        self,
        *,
        target: dict[str, Any],
        project_id: uuid.UUID,
    ) -> Position | None:
        """Look up a Position from a rule's ``boq_target`` dict.

        Supports two lookup keys:
            - ``position_id``: direct UUID lookup (scoped to project).
            - ``position_ordinal``: match by ordinal within any BOQ of the
              given project (returns the first match).
        """
        raw_pid = target.get("position_id")
        if raw_pid:
            try:
                pid = uuid.UUID(str(raw_pid))
            except (ValueError, TypeError):
                return None
            pos = await self.session.get(Position, pid)
            if pos is None:
                return None
            # Make sure the position belongs to the same project.
            boq = await self.session.get(BOQ, pos.boq_id)
            if boq is None or boq.project_id != project_id:
                return None
            return pos

        ordinal = target.get("position_ordinal")
        if ordinal:
            stmt = (
                select(Position)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id, Position.ordinal == str(ordinal))
                .limit(1)
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()

        return None

    async def _auto_create_position_for_rule(
        self,
        *,
        rule: BIMQuantityMap,
        project_id: uuid.UUID,
        matches: list[tuple[BIMElement, Decimal, Decimal]],
    ) -> Position | None:
        """Insert a new Position in the project's first/default BOQ.

        Quantity = sum of adjusted quantities across all matches for this
        rule. Unit = rule.unit (fallback "pcs"). Classification is lifted
        from ``rule.metadata_["classification"]`` when present.
        Returns ``None`` if the project has no BOQ to attach to.
        """
        # Find the project's first BOQ (oldest created_at, same as
        # ``BOQRepository.list_for_project`` order inverted).
        stmt = (
            select(BOQ)
            .where(BOQ.project_id == project_id)
            .order_by(BOQ.created_at.asc())
            .limit(1)
        )
        boq = (await self.session.execute(stmt)).scalar_one_or_none()
        if boq is None:
            logger.warning(
                "Auto-create requested for rule %s but project %s has no BOQ",
                rule.id,
                project_id,
            )
            return None

        # Aggregate the adjusted quantity across all matched elements.
        total_qty = sum((adjusted for _, _, adjusted in matches), Decimal("0"))

        # Pull classification out of the rule's metadata if present.
        rule_meta = rule.metadata_ or {}
        classification = rule_meta.get("classification") or {}
        if not isinstance(classification, dict):
            classification = {}

        # Pick a free ordinal — "BIM-<short rule id>" — unlikely to clash.
        ordinal = f"BIM-{str(rule.id)[:8]}"

        # Determine sort_order: after everything else.
        max_order_stmt = select(func.coalesce(func.max(Position.sort_order), 0)).where(
            Position.boq_id == boq.id
        )
        max_order = (await self.session.execute(max_order_stmt)).scalar_one() or 0

        position = Position(
            boq_id=boq.id,
            parent_id=None,
            ordinal=ordinal,
            description=rule.name,
            unit=rule.unit or "pcs",
            quantity=str(total_qty),
            unit_rate="0",
            total="0",
            classification=classification,
            source="cad_import",
            confidence=None,
            cad_element_ids=[],
            validation_status="pending",
            metadata_={"auto_created_by_rule": str(rule.id)},
            sort_order=max_order + 1,
        )
        self.session.add(position)
        await self.session.flush()
        logger.info(
            "Auto-created Position %s (ordinal=%s) for rule %s in BOQ %s",
            position.id,
            ordinal,
            rule.id,
            boq.id,
        )
        return position

    async def _existing_link_element_ids(
        self,
        position_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        """Return the set of bim_element_ids already linked to a position."""
        stmt = select(BOQElementLink.bim_element_id).where(
            BOQElementLink.boq_position_id == position_id
        )
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}

    async def sync_cad_element_ids(
        self,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Rewrite ``Position.cad_element_ids`` from ``oe_bim_boq_link``.

        Idempotent back-fill helper. Walks every ``BOQElementLink`` in the
        database (optionally scoped to a single project) and overwrites
        the JSON array on the linked ``Position`` with the sorted list of
        bim_element_id strings. Use this when:

            * the app shipped before the link↔position mirror existed and
              legacy rows have out-of-date or empty ``cad_element_ids``;
            * a bulk DB import bypassed the service layer;
            * a migration has added/removed links in bulk.

        Returns a small summary ``{"links_scanned", "positions_updated"}``.
        """
        # ── Load links (optionally scoped to project) ─────────────────
        if project_id is not None:
            stmt = (
                select(BOQElementLink.boq_position_id, BOQElementLink.bim_element_id)
                .join(Position, Position.id == BOQElementLink.boq_position_id)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id)
            )
        else:
            stmt = select(
                BOQElementLink.boq_position_id, BOQElementLink.bim_element_id
            )

        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, set[str]] = {}
        links_scanned = 0
        for pos_id, elem_id in result.all():
            links_scanned += 1
            grouped.setdefault(pos_id, set()).add(str(elem_id))

        # Also make sure positions that exist in the project but have NO
        # links get their cad_element_ids reset to [] (so stale ids from a
        # previous state are cleared).
        if project_id is not None:
            all_pos_stmt = (
                select(Position.id)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id)
            )
            all_pos = (await self.session.execute(all_pos_stmt)).scalars().all()
            for pid in all_pos:
                grouped.setdefault(pid, set())

        positions_updated = 0
        for pos_id, elem_ids in grouped.items():
            pos = await self.session.get(Position, pos_id)
            if pos is None:
                continue
            desired = sorted(elem_ids)
            current = list(pos.cad_element_ids or [])
            if sorted(current) != desired:
                pos.cad_element_ids = desired
                positions_updated += 1

        await self.session.flush()
        logger.info(
            "sync_cad_element_ids: scanned %d links, updated %d positions (project=%s)",
            links_scanned,
            positions_updated,
            project_id,
        )
        return {
            "links_scanned": links_scanned,
            "positions_updated": positions_updated,
        }

    @staticmethod
    def _rule_matches_element(rule: BIMQuantityMap, element: BIMElement) -> bool:
        """Check if a quantity map rule matches an element."""
        # Check element_type_filter
        if rule.element_type_filter:
            if rule.element_type_filter != "*":
                if not element.element_type:
                    return False
                if not fnmatch.fnmatch(element.element_type.lower(), rule.element_type_filter.lower()):
                    return False

        # Check property_filter
        if rule.property_filter:
            props = element.properties or {}
            for key, pattern in rule.property_filter.items():
                value = props.get(key)
                if value is None:
                    return False
                if not fnmatch.fnmatch(str(value).lower(), str(pattern).lower()):
                    return False

        return True

    @staticmethod
    def _extract_quantity(element: BIMElement, source: str) -> Decimal | None:
        """Extract a quantity from an element based on the source specification.

        Supports:
        - Direct quantity keys: area_m2, volume_m3, length_m, weight_kg, count
        - Property references: property:xxx (e.g., property:fire_rating)
        """
        quantities = element.quantities or {}

        if source.startswith("property:"):
            prop_name = source[len("property:"):]
            value = (element.properties or {}).get(prop_name)
        elif source == "count":
            return Decimal("1")
        else:
            value = quantities.get(source)

        if value is None:
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    # ── Model Diff ───────────────────────────────────────────────────────────

    async def compute_diff(
        self,
        new_model_id: uuid.UUID,
        old_model_id: uuid.UUID,
    ) -> BIMModelDiff:
        """Compute diff between two model versions by comparing elements.

        Elements are matched by stable_id. Changes detected via geometry_hash.
        Returns a BIMModelDiff with summary counts and detailed changes.
        """
        new_model = await self.get_model(new_model_id)
        old_model = await self.get_model(old_model_id)

        # Check if diff already exists
        existing = await self.diff_repo.get_by_pair(old_model_id, new_model_id)
        if existing is not None:
            return existing

        # Load all elements for both models
        old_elements, _ = await self.element_repo.list_for_model(
            old_model.id, offset=0, limit=50000
        )
        new_elements, _ = await self.element_repo.list_for_model(
            new_model.id, offset=0, limit=50000
        )

        old_by_sid = {e.stable_id: e for e in old_elements}
        new_by_sid = {e.stable_id: e for e in new_elements}

        old_ids = set(old_by_sid.keys())
        new_ids = set(new_by_sid.keys())

        added_ids = new_ids - old_ids
        deleted_ids = old_ids - new_ids
        common_ids = old_ids & new_ids

        modified: list[dict[str, Any]] = []
        unchanged = 0

        for sid in common_ids:
            old_e = old_by_sid[sid]
            new_e = new_by_sid[sid]

            changes: list[dict[str, Any]] = []
            # Detect what changed across all tracked fields
            if old_e.geometry_hash != new_e.geometry_hash:
                changes.append({
                    "field": "geometry_hash",
                    "old": old_e.geometry_hash,
                    "new": new_e.geometry_hash,
                })
            if old_e.element_type != new_e.element_type:
                changes.append({
                    "field": "element_type",
                    "old": old_e.element_type,
                    "new": new_e.element_type,
                })
            if old_e.quantities != new_e.quantities:
                changes.append({
                    "field": "quantities",
                    "old": old_e.quantities,
                    "new": new_e.quantities,
                })
            if old_e.properties != new_e.properties:
                changes.append({
                    "field": "properties",
                    "old": old_e.properties,
                    "new": new_e.properties,
                })

            if changes:
                modified.append({
                    "stable_id": sid,
                    "element_type": new_e.element_type,
                    "changes": changes,
                })
            else:
                unchanged += 1

        diff_summary = {
            "unchanged": unchanged,
            "modified": len(modified),
            "added": len(added_ids),
            "deleted": len(deleted_ids),
        }

        diff_details = {
            "modified": modified,
            "added": [
                {
                    "stable_id": sid,
                    "element_type": new_by_sid[sid].element_type,
                    "name": new_by_sid[sid].name,
                }
                for sid in added_ids
            ],
            "deleted": [
                {
                    "stable_id": sid,
                    "element_type": old_by_sid[sid].element_type,
                    "name": old_by_sid[sid].name,
                }
                for sid in deleted_ids
            ],
        }

        diff = BIMModelDiff(
            old_model_id=old_model_id,
            new_model_id=new_model_id,
            diff_summary=diff_summary,
            diff_details=diff_details,
        )
        diff = await self.diff_repo.create(diff)

        logger.info(
            "Model diff computed: %s -> %s (added=%d, deleted=%d, modified=%d, unchanged=%d)",
            old_model.name,
            new_model.name,
            len(added_ids),
            len(deleted_ids),
            len(modified),
            unchanged,
        )
        return diff

    async def get_diff(self, diff_id: uuid.UUID) -> BIMModelDiff:
        """Get a model diff by ID. Raises 404 if not found."""
        diff = await self.diff_repo.get(diff_id)
        if diff is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Model diff not found",
            )
        return diff
