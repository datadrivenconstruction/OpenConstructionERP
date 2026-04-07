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
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

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

logger = logging.getLogger(__name__)


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
        """Delete a BIM model and all its elements."""
        await self.get_model(model_id)  # 404 check
        await self.model_repo.delete(model_id)
        logger.info("BIM model deleted: %s", model_id)

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
        """Create a link between a BOQ position and a BIM element."""
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
        logger.info(
            "BOQ-BIM link created: pos=%s elem=%s type=%s",
            data.boq_position_id,
            data.bim_element_id,
            data.link_type,
        )
        return link

    async def delete_link(self, link_id: uuid.UUID) -> None:
        """Delete a BOQ-BIM link."""
        link = await self.link_repo.get(link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ-BIM link not found",
            )
        await self.link_repo.delete(link_id)
        logger.info("BOQ-BIM link deleted: %s", link_id)

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

        For each element, checks which rules match (by element_type_filter
        and property_filter), then extracts the quantity from quantity_source,
        applies multiplier and waste factor.

        Returns a summary of matched elements and applied rules.
        """
        model = await self.get_model(request.model_id)

        # Get all elements for the model
        elements, _ = await self.element_repo.list_for_model(
            model.id, offset=0, limit=50000
        )

        # Get active rules (project-scoped first, then global)
        rules = await self.qmap_repo.list_active(project_id=model.project_id)

        results: list[dict[str, Any]] = []
        matched_elements = 0
        rules_applied = 0

        for element in elements:
            element_matched = False
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
                element_matched = True
                rules_applied += 1

            if element_matched:
                matched_elements += 1

        logger.info(
            "Quantity maps applied: %d elements matched, %d rules applied for model %s",
            matched_elements,
            rules_applied,
            model.name,
        )

        return QuantityMapApplyResult(
            matched_elements=matched_elements,
            rules_applied=rules_applied,
            results=results,
        )

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

            if old_e.geometry_hash != new_e.geometry_hash:
                changes: list[dict[str, Any]] = []
                # Detect what changed
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
