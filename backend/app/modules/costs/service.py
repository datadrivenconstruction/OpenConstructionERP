"""Cost item service — business logic for cost database management.

Stateless service layer. Handles:
- Cost item CRUD
- Search with filters
- Bulk import
- BIM-element cost suggestions
- Event publishing for cost changes
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.costs.models import CostItem
from app.modules.costs.repository import CostItemRepository
from app.modules.costs.schemas import (
    CostItemCreate,
    CostItemUpdate,
    CostSearchQuery,
    CostSuggestion,
)

logger = logging.getLogger(__name__)


class CostItemService:
    """Business logic for cost item operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CostItemRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_cost_item(self, data: CostItemCreate) -> CostItem:
        """Create a new cost item.

        Raises HTTPException 409 if code already exists.
        """
        existing = await self.repo.get_by_code(data.code, region=data.region)
        if existing is not None:
            region_label = data.region or "global"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cost item with code '{data.code}' already exists for region '{region_label}'",
            )

        item = CostItem(
            code=data.code,
            description=data.description,
            descriptions=data.descriptions,
            unit=data.unit,
            rate=str(data.rate),
            currency=data.currency,
            source=data.source,
            classification=data.classification,
            components=data.components,
            tags=data.tags,
            region=data.region,
            metadata_=data.metadata,
        )
        item = await self.repo.create(item)

        await _safe_publish(
            "costs.item.created",
            {"item_id": str(item.id), "code": item.code},
            source_module="oe_costs",
        )

        logger.info("Cost item created: %s (%s)", item.code, item.unit)
        return item

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_cost_item(self, item_id: uuid.UUID) -> CostItem:
        """Get cost item by ID. Raises 404 if not found."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )
        return item

    async def get_by_codes(self, codes: list[str]) -> list[CostItem]:
        """Get multiple cost items by their codes."""
        return await self.repo.get_by_codes(codes)

    async def search_costs(self, query: CostSearchQuery) -> tuple[list[CostItem], int]:
        """Search cost items with filters and pagination."""
        return await self.repo.search(
            q=query.q,
            unit=query.unit,
            source=query.source,
            region=query.region,
            category=query.category,
            min_rate=query.min_rate,
            max_rate=query.max_rate,
            offset=query.offset,
            limit=query.limit,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_cost_item(self, item_id: uuid.UUID, data: CostItemUpdate) -> CostItem:
        """Update a cost item. Raises 404 if not found, 409 on code conflict."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert rate float → string for storage
        if "rate" in fields and fields["rate"] is not None:
            fields["rate"] = str(fields["rate"])

        # Rename metadata → metadata_ for the ORM column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Check code uniqueness if code or region is being changed
        new_code = fields.get("code", item.code)
        new_region = fields.get("region", item.region)
        if new_code != item.code or new_region != item.region:
            existing = await self.repo.get_by_code(new_code, region=new_region)
            if existing is not None and existing.id != item_id:
                region_label = new_region or "global"
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cost item with code '{new_code}' already exists for region '{region_label}'",
                )

        if fields:
            await self.repo.update_fields(item_id, **fields)

        updated = await self.repo.get_by_id(item_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        await _safe_publish(
            "costs.item.updated",
            {"item_id": str(item_id), "code": updated.code, "fields": list(fields.keys())},
            source_module="oe_costs",
        )

        logger.info("Cost item updated: %s", updated.code)
        return updated

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_cost_item(self, item_id: uuid.UUID) -> None:
        """Soft-delete a cost item (set is_active=False). Raises 404 if not found."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        # Save code before expire_all() invalidates the ORM object
        item_code = item.code

        await self.repo.update_fields(item_id, is_active=False)

        await _safe_publish(
            "costs.item.deleted",
            {"item_id": str(item_id), "code": item_code},
            source_module="oe_costs",
        )

        logger.info("Cost item deleted (soft): %s", item_code)

    # ── Bulk import ───────────────────────────────────────────────────────

    async def bulk_import(self, items_data: list[CostItemCreate]) -> list[CostItem]:
        """Bulk import cost items. Skips items with duplicate codes.

        Returns the list of successfully created items.
        """
        created: list[CostItem] = []
        skipped_codes: list[str] = []

        for data in items_data:
            existing = await self.repo.get_by_code(data.code, region=data.region)
            if existing is not None:
                skipped_codes.append(data.code)
                continue

            item = CostItem(
                code=data.code,
                description=data.description,
                descriptions=data.descriptions,
                unit=data.unit,
                rate=str(data.rate),
                currency=data.currency,
                source=data.source,
                classification=data.classification,
                components=data.components,
                tags=data.tags,
                region=data.region,
                metadata_=data.metadata,
            )
            created.append(item)

        if created:
            created = await self.repo.bulk_create(created)

        await _safe_publish(
            "costs.items.bulk_imported",
            {
                "created_count": len(created),
                "skipped_count": len(skipped_codes),
                "skipped_codes": skipped_codes[:20],  # Limit for event payload size
            },
            source_module="oe_costs",
        )

        logger.info(
            "Bulk import: %d created, %d skipped (duplicate codes)",
            len(created),
            len(skipped_codes),
        )
        return created

    # ── BIM-element suggestions ───────────────────────────────────────────

    async def suggest_for_bim_element(
        self,
        element_type: str | None,
        name: str | None,
        discipline: str | None,
        properties: dict[str, Any] | None,
        quantities: dict[str, float] | None,
        classification: dict[str, str] | None,
        *,
        limit: int = 5,
        region: str | None = None,
    ) -> list[CostSuggestion]:
        """Return ranked CWICR cost items that best match a BIM element.

        Ranking factors (in priority order):
          1. Classification overlap — same OmniClass / UniFormat / DIN-276 code
          2. Element type keyword match in description (e.g. element_type='Walls'
             matches 'wall', 'wall panel', 'concrete wall')
          3. Material match — ``properties['material']`` vs description
          4. Family/type match — ``name`` vs description
          5. Tag overlap with element discipline / category

        Returns at most ``limit`` results, sorted by score descending.  Each
        result has a ``score`` field 0..1 so the UI can show confidence.

        Implementation notes:
            The DB query uses plain SQLAlchemy ``ilike`` + ``JSON`` column
            access so the same code path works on PostgreSQL AND SQLite.
            We fetch a wider candidate window (``limit * 20`` capped at 200)
            via keyword OR-ILIKE and then rank in Python.  No pgvector / FTS
            required.
        """
        _ = quantities  # Currently unused in ranking; accepted for API symmetry.

        keywords = self._build_keywords(element_type, name, discipline, properties)
        material = self._extract_material(properties)

        # ── Build candidate query ────────────────────────────────────────
        #
        # Strategy: OR across keyword ILIKE on description + code, plus any
        # items whose classification dict contains any of the provided
        # classification codes (we do this in Python post-filter to stay
        # DB-agnostic).
        base = select(CostItem).where(CostItem.is_active.is_(True))
        if region:
            base = base.where(CostItem.region == region)

        conditions: list[Any] = []
        for kw in keywords:
            if len(kw) < 3:
                continue
            pattern = f"%{kw}%"
            conditions.append(CostItem.description.ilike(pattern))
            conditions.append(CostItem.code.ilike(pattern))

        candidate_cap = max(limit * 20, 50)
        if conditions:
            base = base.where(or_(*conditions))
        # If no keywords at all, we still allow classification-only matching
        # but we bound the candidate pool hard.
        stmt = base.limit(candidate_cap)

        result = await self.session.execute(stmt)
        candidates: list[CostItem] = list(result.scalars().all())

        # ── Rank candidates in Python ────────────────────────────────────
        scored: list[tuple[float, list[str], CostItem]] = []
        for item in candidates:
            score, reasons = self._score_candidate(
                item=item,
                element_type=element_type,
                name=name,
                discipline=discipline,
                material=material,
                classification=classification or {},
                keywords=keywords,
            )
            if score > 0:
                scored.append((score, reasons, item))

        # Sort by score descending, then by code for stable output.
        scored.sort(key=lambda t: (-t[0], t[2].code))

        suggestions: list[CostSuggestion] = []
        for score, reasons, item in scored[:limit]:
            try:
                rate_val: float | str = float(item.rate)
            except (ValueError, TypeError):
                rate_val = str(item.rate)
            suggestions.append(
                CostSuggestion(
                    cost_item_id=str(item.id),
                    code=item.code,
                    description=item.description,
                    unit=item.unit,
                    unit_rate=rate_val,
                    classification=dict(item.classification or {}),
                    score=round(min(score, 1.0), 4),
                    match_reasons=reasons,
                )
            )

        logger.debug(
            "suggest_for_bim_element: element_type=%s keywords=%s -> %d candidates, %d returned",
            element_type,
            keywords,
            len(candidates),
            len(suggestions),
        )
        return suggestions

    # ── Helpers for BIM-element suggestions ───────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lower-case word tokenizer, drops words shorter than 3 chars."""
        return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3]

    @classmethod
    def _build_keywords(
        cls,
        element_type: str | None,
        name: str | None,
        discipline: str | None,
        properties: dict[str, Any] | None,
    ) -> list[str]:
        """Collect unique keywords from BIM element attributes."""
        bag: list[str] = []
        for src in (element_type, name, discipline):
            if src:
                bag.extend(cls._tokenize(str(src)))
        if properties:
            material = cls._extract_material(properties)
            if material:
                bag.extend(cls._tokenize(material))
            # Pull other obvious string props that often describe the element.
            for key in ("family", "type", "category", "system"):
                val = properties.get(key) if isinstance(properties, dict) else None
                if isinstance(val, str) and val:
                    bag.extend(cls._tokenize(val))
        # Normalize common Revit plural forms ("walls" -> "wall", etc.).
        normalized: list[str] = []
        for token in bag:
            normalized.append(token)
            if token.endswith("s") and len(token) > 3:
                normalized.append(token[:-1])
        # Deduplicate preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for t in normalized:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    @staticmethod
    def _extract_material(properties: dict[str, Any] | None) -> str | None:
        """Try a handful of common keys where material may live."""
        if not isinstance(properties, dict):
            return None
        for key in ("material", "Material", "structural_material", "StructuralMaterial"):
            val = properties.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    @classmethod
    def _score_candidate(
        cls,
        *,
        item: CostItem,
        element_type: str | None,
        name: str | None,
        discipline: str | None,
        material: str | None,
        classification: dict[str, str],
        keywords: list[str],
    ) -> tuple[float, list[str]]:
        """Compute a relevance score + human-readable reasons for one item.

        Returns a tuple (score, reasons).  Score is an unbounded positive
        float that the caller clamps to [0, 1].  A rough budget:
            classification exact match  -> +0.45
            element_type token in desc  -> +0.25
            material token in desc      -> +0.15
            family/name token in desc   -> +0.10
            discipline/tag overlap      -> +0.05
        """
        reasons: list[str] = []
        score = 0.0

        desc_lower = (item.description or "").lower()
        code_lower = (item.code or "").lower()
        item_class = item.classification or {}
        item_tags = [str(t).lower() for t in (item.tags or [])]

        # 1. Classification overlap ---------------------------------------
        for key, val in classification.items():
            if not isinstance(val, str) or not val:
                continue
            other = item_class.get(key)
            if isinstance(other, str) and other and other == val:
                score += 0.45
                reasons.append(f"{key}={val} exact match")
                break
            # Prefix match (e.g. DIN 276 "330" vs "331") - weaker.
            if isinstance(other, str) and other and (
                other.startswith(val) or val.startswith(other)
            ):
                score += 0.2
                reasons.append(f"{key}={val} prefix match")
                break

        # 2. Element type keyword in description --------------------------
        if element_type:
            for token in cls._tokenize(str(element_type)):
                norm_tokens = {token}
                if token.endswith("s") and len(token) > 3:
                    norm_tokens.add(token[:-1])
                for t in norm_tokens:
                    if t in desc_lower or t in code_lower:
                        score += 0.25
                        reasons.append(f"element_type={t}")
                        break
                else:
                    continue
                break

        # 3. Material match -----------------------------------------------
        if material:
            for token in cls._tokenize(material):
                if token in desc_lower:
                    score += 0.15
                    reasons.append(f"material={token}")
                    break

        # 4. Family/name match --------------------------------------------
        if name:
            for token in cls._tokenize(str(name)):
                if token in desc_lower:
                    score += 0.1
                    reasons.append(f"name={token}")
                    break

        # 5. Discipline / tag overlap -------------------------------------
        if discipline:
            disc_lower = str(discipline).lower()
            if disc_lower in item_tags or disc_lower in desc_lower:
                score += 0.05
                reasons.append(f"discipline={disc_lower}")

        # Small bonus per extra keyword hit (bounded) ---------------------
        extra_hits = 0
        for kw in keywords:
            if kw in desc_lower:
                extra_hits += 1
        if extra_hits > 1:
            score += min(0.05 * (extra_hits - 1), 0.15)
            reasons.append(f"+{extra_hits - 1} keyword hits")

        return score, reasons
