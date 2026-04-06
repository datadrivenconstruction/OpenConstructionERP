# OpenConstructionERP — DataDrivenConstruction (DDC)
# CWICR Cost Database Engine · BOQ Module
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""BOQ service — business logic for Bill of Quantities management.

Stateless service layer. Handles:
- BOQ CRUD with project scoping
- Position management with auto-calculated totals
- Section (header row) management
- Markup/overhead CRUD and calculation
- Structured BOQ retrieval with sections, subtotals, and markups
- Default markup template application per region
- Grand total computation
- Event publishing for inter-module communication
- BOQ creation from built-in templates
- Activity log queries
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

logger_events = logging.getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict[str, Any], source_module: str = "oe_boq") -> None:
    """Publish event safely — ignores MissingGreenlet errors with SQLite async."""
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        logger_events.debug("Event publish skipped (SQLite async): %s", name)
from app.modules.costs.repository import CostItemRepository
from app.modules.boq.models import BOQ, BOQActivityLog, BOQMarkup, BOQSnapshot, Position
from app.modules.boq.repository import (
    ActivityLogRepository,
    BOQRepository,
    MarkupRepository,
    PositionRepository,
)
from app.modules.boq.schemas import (
    ActivityLogList,
    ActivityLogResponse,
    BOQCreate,
    BOQFromTemplateRequest,
    BOQUpdate,
    BOQWithPositions,
    BOQWithSections,
    CostBreakdownCategory,
    CostBreakdownMarkup,
    CostBreakdownResource,
    CostBreakdownResponse,
    EstimateClassificationMetrics,
    EstimateClassificationResponse,
    MarkupCalculated,
    MarkupCreate,
    MarkupResponse,
    MarkupUpdate,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
    SectionCreate,
    SectionResponse,
    TemplateInfo,
)
from app.modules.boq.templates import TEMPLATES

logger = logging.getLogger(__name__)


# ── Regional markup templates ────────────────────────────────────────────────
#
# Based on industry standards for medium commercial building projects.
# Percentages applied to direct cost unless noted; tax items are cumulative.
# Sources: VOB/HOAI, NRM1/RICS, RSMeans/AIA, BATIPRIX, FIDIC, CPWD, AIQS,
# MLIT, TCU/SINAPI, Byggakademin, ГЭСН/МДС, 建标[2013]44号, 조달청.

DEFAULT_MARKUP_TEMPLATES: dict[str, list[dict[str, object]]] = {
    # ── Germany / Austria / Switzerland ─────────────────────────────────
    # VOB/B Zuschlagskalkulation, EFB Preisblatt 221
    "DACH": [
        {
            "name": "Baustellengemeinkosten (BGK)",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Allgemeine Geschäftskosten (AGK)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Wagnis (W)",
            "category": "contingency",
            "percentage": "2.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Gewinn (G)",
            "category": "profit",
            "percentage": "3.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "Mehrwertsteuer (MwSt.)",
            "category": "tax",
            "percentage": "19.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── United Kingdom ──────────────────────────────────────────────────
    # RICS NRM1/NRM2, BCIS Elemental Standard Form
    "UK": [
        {
            "name": "Main Contractor's Preliminaries",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Main Contractor's Overheads",
            "category": "overhead",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Main Contractor's Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Design Development Risk",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── United States ───────────────────────────────────────────────────
    # RSMeans / AIA / CSI MasterFormat Division 01
    "US": [
        {
            "name": "General Conditions (Div. 01)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "General Contractor Overhead",
            "category": "overhead",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "General Contractor Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "General Liability Insurance",
            "category": "insurance",
            "percentage": "1.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "Performance & Payment Bond",
            "category": "bond",
            "percentage": "1.5",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "Design Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 6,
        },
    ],
    # ── France ──────────────────────────────────────────────────────────
    # Méthode du Déboursé Sec, BATIPRIX, Code des marchés publics
    "FR": [
        {
            "name": "Frais de chantier (FC)",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Frais généraux (FG)",
            "category": "overhead",
            "percentage": "15.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Bénéfice et aléas (B&A)",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "TVA",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Gulf / UAE ──────────────────────────────────────────────────────
    # FIDIC Red Book, AECOM ME Handbook
    "GULF": [
        {
            "name": "Preliminaries & General (P&G)",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor Overhead",
            "category": "overhead",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contractor Profit",
            "category": "profit",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Insurance (CAR + TPL)",
            "category": "insurance",
            "percentage": "0.5",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Performance Bond",
            "category": "bond",
            "percentage": "0.5",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── India ───────────────────────────────────────────────────────────
    # CPWD Works Manual 2019, DSR, IS:7272
    "IN": [
        {
            "name": "Site Overhead / Establishment",
            "category": "overhead",
            "percentage": "7.5",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Head Office Overhead",
            "category": "overhead",
            "percentage": "7.5",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contractor's Profit",
            "category": "profit",
            "percentage": "7.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Labour Cess (BOCW)",
            "category": "other",
            "percentage": "1.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "GST",
            "category": "tax",
            "percentage": "18.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── Australia ───────────────────────────────────────────────────────
    # AIQS ACMM, AS 4000
    "AU": [
        {
            "name": "Contractor's Preliminaries",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Margin (OH&P)",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Design Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Escalation Allowance",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "GST",
            "category": "tax",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── Japan ───────────────────────────────────────────────────────────
    # 公共建築工事共通費積算基準 (MLIT)
    "JP": [
        {
            "name": "\u5171\u901a\u4eee\u8a2d\u8cbb (Common Temporary)",
            "category": "overhead",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u73fe\u5834\u7ba1\u7406\u8cbb (Site Management)",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "\u4e00\u822c\u7ba1\u7406\u8cbb\u7b49 (General Admin & Profit)",
            "category": "profit",
            "percentage": "7.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "\u6d88\u8cbb\u7a0e (Consumption Tax)",
            "category": "tax",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Brazil ──────────────────────────────────────────────────────────
    # BDI per TCU Acórdão 2.622/2013, SINAPI
    "BR": [
        {
            "name": "Administra\u00e7\u00e3o Central (AC)",
            "category": "overhead",
            "percentage": "5.5",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Despesas Financeiras (DF)",
            "category": "other",
            "percentage": "1.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Seguros (S)",
            "category": "insurance",
            "percentage": "0.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Garantias (G)",
            "category": "bond",
            "percentage": "0.5",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "Riscos e Imprevistos (R)",
            "category": "contingency",
            "percentage": "1.0",
            "apply_to": "direct_cost",
            "sort_order": 4,
        },
        {
            "name": "Lucro (L)",
            "category": "profit",
            "percentage": "7.5",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
        {
            "name": "PIS + COFINS",
            "category": "tax",
            "percentage": "3.65",
            "apply_to": "cumulative",
            "sort_order": 6,
        },
        {
            "name": "ISS",
            "category": "tax",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 7,
        },
    ],
    # ── Scandinavia / Nordic ────────────────────────────────────────────
    # Byggakademin (SE), AB 04, NS 3420 (NO)
    "NORDIC": [
        {
            "name": "Arbetsplatsomkostnader (APO)",
            "category": "overhead",
            "percentage": "15.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Centralomkostnader (CO)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Vinst (V)",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Risk (R)",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "MOMS",
            "category": "tax",
            "percentage": "25.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── Russia / CIS ────────────────────────────────────────────────────
    # МДС 81-35.2004, Приказ Минстроя 812/пр, 774/пр
    # НР/СП norms applied to ФОТ; effective % of direct costs shown here.
    "RU": [
        {
            "name": "\u041d\u0430\u043a\u043b\u0430\u0434\u043d\u044b\u0435 \u0440\u0430\u0441\u0445\u043e\u0434\u044b (\u041d\u0420)",
            "category": "overhead",
            "percentage": "16.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u0421\u043c\u0435\u0442\u043d\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c (\u0421\u041f)",
            "category": "profit",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "\u041d\u0435\u043f\u0440\u0435\u0434\u0432\u0438\u0434\u0435\u043d\u043d\u044b\u0435 \u0440\u0430\u0441\u0445\u043e\u0434\u044b",
            "category": "contingency",
            "percentage": "2.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "\u041d\u0414\u0421",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── China ───────────────────────────────────────────────────────────
    # 建标[2013]44号, regional 定额
    "CN": [
        {
            "name": "\u63aa\u65bd\u9879\u76ee\u8d39 (Temporary Works)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u4f01\u4e1a\u7ba1\u7406\u8d39 (Management Fee)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "\u5229\u6da6 (Profit)",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "\u89c4\u8d39 (Statutory Fees)",
            "category": "other",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "\u589e\u503c\u7a0e (VAT)",
            "category": "tax",
            "percentage": "9.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── South Korea ─────────────────────────────────────────────────────
    # 조달청 예정가격작성기준, 계약예규
    "KR": [
        {
            "name": "\uac04\uc811\ub178\ubb34\ube44 (Indirect Labor)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\uc0b0\uc5c5\uc548\uc804\ubcf4\uac74\uad00\ub9ac\ube44 (Safety & Health)",
            "category": "overhead",
            "percentage": "2.15",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "\uae30\ud0c0\uacbd\ube44 (Other Expenses)",
            "category": "overhead",
            "percentage": "6.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "\uc77c\ubc18\uad00\ub9ac\ube44 (General Admin)",
            "category": "overhead",
            "percentage": "6.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "\uc774\uc724 (Profit)",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "\ubd80\uac00\uac00\uce58\uc138 (VAT)",
            "category": "tax",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── Default (generic international) ─────────────────────────────────
    "DEFAULT": [
        {
            "name": "Site Overhead",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Head Office Overhead",
            "category": "overhead",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
}


def _compute_total(quantity: float, unit_rate: float) -> str:
    """Compute total as string from quantity and unit_rate.

    Uses Decimal for precision, returns string for SQLite-safe storage.
    """
    try:
        q = Decimal(str(quantity))
        r = Decimal(str(unit_rate))
        return str(q * r)
    except (InvalidOperation, ValueError):
        return "0"


def _str_to_float(value: str | None) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _is_section(position: Position) -> bool:
    """Determine whether a position is a section header.

    A section is a top-level position (parent_id is None) whose unit is empty
    or the sentinel value ``"section"`` and whose quantity and unit_rate are
    both zero.  This distinguishes section headers from real line items that
    happen to have no parent.
    """
    if position.parent_id is not None:
        return False
    unit = (position.unit or "").strip().lower()
    qty = _str_to_float(position.quantity)
    rate = _str_to_float(position.unit_rate)
    return unit in ("", "section") and qty == 0.0 and rate == 0.0


def _build_position_response(pos: Position) -> PositionResponse:
    """Build a PositionResponse from a Position ORM instance."""
    return PositionResponse(
        id=pos.id,
        boq_id=pos.boq_id,
        parent_id=pos.parent_id,
        ordinal=pos.ordinal,
        description=pos.description,
        unit=pos.unit,
        quantity=_str_to_float(pos.quantity),
        unit_rate=_str_to_float(pos.unit_rate),
        total=_str_to_float(pos.total),
        classification=pos.classification,
        source=pos.source,
        confidence=(
            _str_to_float(pos.confidence) if pos.confidence is not None else None
        ),
        cad_element_ids=pos.cad_element_ids,
        validation_status=pos.validation_status,
        metadata_=pos.metadata_,
        sort_order=pos.sort_order,
        created_at=pos.created_at,
        updated_at=pos.updated_at,
    )


def _build_markup_response(markup: BOQMarkup) -> MarkupResponse:
    """Build a MarkupResponse from a BOQMarkup ORM instance."""
    return MarkupResponse(
        id=markup.id,
        boq_id=markup.boq_id,
        name=markup.name,
        markup_type=markup.markup_type,
        category=markup.category,
        percentage=_str_to_float(markup.percentage),
        fixed_amount=_str_to_float(markup.fixed_amount),
        apply_to=markup.apply_to,
        sort_order=markup.sort_order,
        is_active=markup.is_active,
        metadata_=markup.metadata_,
        created_at=markup.created_at,
        updated_at=markup.updated_at,
    )


# ── AACE 18R-97 classification table ─────────────────────────────────────────

_AACE_CLASSES: dict[int, dict[str, str | int]] = {
    5: {
        "label": "Screening / Order of Magnitude",
        "accuracy_low": "-50%",
        "accuracy_high": "+100%",
        "definition_low": 0,
        "definition_high": 2,
        "methodology": (
            "Capacity-factored, parametric models, judgment, or analogy. "
            "Based on very limited project information."
        ),
    },
    4: {
        "label": "Feasibility / Study",
        "accuracy_low": "-30%",
        "accuracy_high": "+50%",
        "definition_low": 1,
        "definition_high": 15,
        "methodology": (
            "Equipment-factored or parametric models. "
            "Based on schematic or conceptual design information."
        ),
    },
    3: {
        "label": "Budget / Authorization",
        "accuracy_low": "-20%",
        "accuracy_high": "+30%",
        "definition_low": 10,
        "definition_high": 40,
        "methodology": (
            "Semi-detailed unit costs with assembly-level line items. "
            "Based on preliminary design or developed design."
        ),
    },
    2: {
        "label": "Control / Bid / Tender",
        "accuracy_low": "-15%",
        "accuracy_high": "+20%",
        "definition_low": 30,
        "definition_high": 75,
        "methodology": (
            "Detailed unit costs with forced detailed takeoff. "
            "Based on detailed design or tender documentation."
        ),
    },
    1: {
        "label": "Definitive / Check / Bid",
        "accuracy_low": "-10%",
        "accuracy_high": "+15%",
        "definition_low": 65,
        "definition_high": 100,
        "methodology": (
            "Detailed unit costs with detailed takeoff and resource-loaded schedule. "
            "Based on complete or near-complete design."
        ),
    },
}


def _determine_aace_class(
    total_positions: int,
    rate_pct: float,
    resource_pct: float,
) -> int:
    """Determine AACE class from position count and completeness percentages.

    Rules (evaluated top-to-bottom, first match wins):
    - Class 5: < 5 positions or < 20% have rates
    - Class 4: < 20 positions or < 50% complete
    - Class 3: < 50 positions or < 75% complete
    - Class 2: < 100 positions or < 90% complete with resources
    - Class 1: 100+ positions, 90%+ complete with resources
    """
    if total_positions < 5 or rate_pct < 20:
        return 5
    if total_positions < 20 or rate_pct < 50:
        return 4
    if total_positions < 50 or rate_pct < 75:
        return 3
    if total_positions < 100 or resource_pct < 90:
        return 2
    return 1


def _build_classification(
    total_positions: int,
    positions_with_rates: int,
    positions_with_resources: int,
    positions_with_classification: int,
) -> EstimateClassificationResponse:
    """Build an EstimateClassificationResponse from raw metric counts."""
    rate_pct = (positions_with_rates / total_positions * 100) if total_positions > 0 else 0.0
    resource_pct = (
        (positions_with_resources / total_positions * 100) if total_positions > 0 else 0.0
    )
    classification_pct = (
        (positions_with_classification / total_positions * 100) if total_positions > 0 else 0.0
    )

    est_class = _determine_aace_class(total_positions, rate_pct, resource_pct)
    class_info = _AACE_CLASSES[est_class]

    return EstimateClassificationResponse(
        estimate_class=est_class,
        class_label=str(class_info["label"]),
        accuracy_low=str(class_info["accuracy_low"]),
        accuracy_high=str(class_info["accuracy_high"]),
        definition_level_low=int(class_info["definition_low"]),
        definition_level_high=int(class_info["definition_high"]),
        methodology=str(class_info["methodology"]),
        metrics=EstimateClassificationMetrics(
            total_positions=total_positions,
            positions_with_rates=positions_with_rates,
            positions_with_resources=positions_with_resources,
            positions_with_classification=positions_with_classification,
            rate_completeness_pct=round(rate_pct, 1),
            resource_completeness_pct=round(resource_pct, 1),
            classification_completeness_pct=round(classification_pct, 1),
        ),
    )


def _calculate_markup_amounts(
    direct_cost: Decimal,
    markups: list[BOQMarkup],
) -> list[tuple[BOQMarkup, Decimal]]:
    """Compute the dollar amount for each active markup line.

    Args:
        direct_cost: Sum of all position totals.
        markups: Ordered list of BOQMarkup ORM objects.

    Returns:
        List of (markup, computed_amount) tuples preserving input order.
    """
    results: list[tuple[BOQMarkup, Decimal]] = []
    running_sum = Decimal("0")

    for markup in markups:
        if not markup.is_active:
            results.append((markup, Decimal("0")))
            continue

        # Determine the base for calculation
        apply_to = (markup.apply_to or "direct_cost").lower()
        if apply_to == "cumulative":
            base = direct_cost + running_sum
        else:
            # "direct_cost" and "subtotal" both use direct_cost as base
            base = direct_cost

        # Calculate amount based on type
        markup_type = (markup.markup_type or "percentage").lower()
        if markup_type == "percentage":
            pct = Decimal(str(markup.percentage or "0"))
            amount = base * pct / Decimal("100")
        elif markup_type == "fixed":
            amount = Decimal(str(markup.fixed_amount or "0"))
        else:
            # per_unit and unknown types default to zero
            amount = Decimal("0")

        running_sum += amount
        results.append((markup, amount))

    return results


class BOQService:
    """Business logic for BOQ, Position, and Markup operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.boq_repo = BOQRepository(session)
        self.position_repo = PositionRepository(session)
        self.markup_repo = MarkupRepository(session)
        self.activity_repo = ActivityLogRepository(session)

    # ── BOQ operations ────────────────────────────────────────────────────

    async def create_boq(self, data: BOQCreate) -> BOQ:
        """Create a new Bill of Quantities.

        Args:
            data: BOQ creation payload with project_id, name, description.

        Returns:
            The newly created BOQ.

        Raises:
            HTTPException: If the referenced project does not exist.
        """
        # Validate project exists
        from app.modules.projects.models import Project

        result = await self.session.execute(
            select(Project.id).where(Project.id == data.project_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        default_display_columns = ["ordinal", "description", "unit", "quantity", "unit_rate", "total"]
        boq = BOQ(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            status="draft",
            metadata_={"display_columns": default_display_columns},
        )
        boq = await self.boq_repo.create(boq)

        # Auto-apply default markups based on project region
        try:
            from app.modules.projects.models import Project

            result = await self.session.execute(
                select(Project.region).where(Project.id == data.project_id)
            )
            region = result.scalar_one_or_none() or "DEFAULT"
            await self.apply_default_markups(boq.id, region)
            logger.info("Auto-applied %s markups to new BOQ %s", region, boq.id)
        except Exception:
            logger.warning("Could not auto-apply markups for BOQ %s", boq.id, exc_info=True)

        await _safe_publish(
            "boq.boq.created",
            {"boq_id": str(boq.id), "project_id": str(data.project_id)},
            source_module="oe_boq",
        )

        logger.info("BOQ created: %s (project=%s)", boq.name, data.project_id)
        return boq

    async def get_boq(self, boq_id: uuid.UUID) -> BOQ:
        """Get BOQ by ID. Raises 404 if not found."""
        boq = await self.boq_repo.get_by_id(boq_id)
        if boq is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ not found",
            )
        return boq

    async def list_boqs_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQ], int]:
        """List BOQs for a given project with pagination."""
        return await self.boq_repo.list_for_project(
            project_id, offset=offset, limit=limit
        )

    async def update_boq(self, boq_id: uuid.UUID, data: BOQUpdate) -> BOQ:
        """Update BOQ metadata fields.

        Args:
            boq_id: Target BOQ identifier.
            data: Partial update payload.

        Returns:
            Updated BOQ.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)

        fields = data.model_dump(exclude_unset=True)
        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.boq_repo.update_fields(boq_id, **fields)

            await _safe_publish(
                "boq.boq.updated",
                {"boq_id": str(boq_id), "fields": list(fields.keys())},
            )

        # Re-fetch to return fresh data
        return await self.get_boq(boq_id)

    async def delete_boq(self, boq_id: uuid.UUID) -> None:
        """Delete a BOQ and all its positions.

        Raises HTTPException 404 if not found.
        """
        boq = await self.get_boq(boq_id)
        project_id = str(boq.project_id)

        await self.boq_repo.delete(boq_id)

        await _safe_publish(
            "boq.boq.deleted",
            {"boq_id": str(boq_id), "project_id": project_id},
            source_module="oe_boq",
        )

        logger.info("BOQ deleted: %s", boq_id)

    # ── Position operations ───────────────────────────────────────────────

    async def add_position(self, data: PositionCreate) -> Position:
        """Add a new position to a BOQ.

        Auto-calculates total = quantity * unit_rate.
        Assigns sort_order to place the position at the end.

        Args:
            data: Position creation payload.

        Returns:
            The newly created position.

        Raises:
            HTTPException 404 if the target BOQ doesn't exist.
        """
        # Verify BOQ exists
        await self.get_boq(data.boq_id)

        total = _compute_total(data.quantity, data.unit_rate)
        max_order = await self.position_repo.get_max_sort_order(data.boq_id)

        position = Position(
            boq_id=data.boq_id,
            parent_id=data.parent_id,
            ordinal=data.ordinal,
            description=data.description,
            unit=data.unit,
            quantity=str(data.quantity),
            unit_rate=str(data.unit_rate),
            total=total,
            classification=data.classification,
            source=data.source,
            confidence=str(data.confidence) if data.confidence is not None else None,
            cad_element_ids=data.cad_element_ids,
            metadata_=data.metadata,
            sort_order=max_order + 1,
        )
        position = await self.position_repo.create(position)

        await _safe_publish(
            "boq.position.created",
            {
                "position_id": str(position.id),
                "boq_id": str(data.boq_id),
                "ordinal": data.ordinal,
            },
            source_module="oe_boq",
        )

        logger.info("Position added: %s to BOQ %s", data.ordinal, data.boq_id)
        return position

    async def create_section(
        self, boq_id: uuid.UUID, data: SectionCreate
    ) -> Position:
        """Create a section header row in a BOQ.

        A section is stored as a Position with unit="section", quantity=0,
        unit_rate=0, and parent_id=None.  This distinguishes it from regular
        items.

        Args:
            boq_id: Target BOQ identifier.
            data: Section creation payload (ordinal, description).

        Returns:
            The newly created section (Position).

        Raises:
            HTTPException 404 if the target BOQ doesn't exist.
        """
        await self.get_boq(boq_id)

        max_order = await self.position_repo.get_max_sort_order(boq_id)

        section = Position(
            boq_id=boq_id,
            parent_id=None,
            ordinal=data.ordinal,
            description=data.description,
            unit="section",
            quantity="0",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            confidence=None,
            cad_element_ids=[],
            metadata_=data.metadata,
            sort_order=max_order + 1,
        )
        section = await self.position_repo.create(section)

        await _safe_publish(
            "boq.section.created",
            {
                "section_id": str(section.id),
                "boq_id": str(boq_id),
                "ordinal": data.ordinal,
            },
            source_module="oe_boq",
        )

        logger.info("Section created: %s in BOQ %s", data.ordinal, boq_id)
        return section

    async def update_position(
        self, position_id: uuid.UUID, data: PositionUpdate
    ) -> Position:
        """Update a position and recalculate total if quantity or unit_rate changed.

        Args:
            position_id: Target position identifier.
            data: Partial update payload.

        Returns:
            Updated position.

        Raises:
            HTTPException 404 if position not found.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "quantity" in fields:
            fields["quantity"] = str(fields["quantity"])
        if "unit_rate" in fields:
            fields["unit_rate"] = str(fields["unit_rate"])
        if "confidence" in fields:
            val = fields["confidence"]
            fields["confidence"] = str(val) if val is not None else None

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # If metadata contains resources, derive unit_rate from resource totals
        meta = fields.get("metadata_", None)
        if meta is None and "metadata" in fields:
            meta = fields.get("metadata")
        new_quantity = fields.get("quantity", position.quantity)
        new_unit_rate = fields.get("unit_rate", position.unit_rate)

        if meta and isinstance(meta, dict) and isinstance(meta.get("resources"), list):
            resources = meta["resources"]
            if resources:
                resource_total = sum(
                    float(r.get("quantity", 0)) * float(r.get("unit_rate", 0))
                    for r in resources
                    if isinstance(r, dict)
                )
                qty_float = _str_to_float(new_quantity)
                if qty_float > 0:
                    new_unit_rate = str(round(resource_total / qty_float, 4))
                    fields["unit_rate"] = new_unit_rate

        # Recalculate total
        fields["total"] = _compute_total(
            _str_to_float(new_quantity), _str_to_float(new_unit_rate)
        )

        if fields:
            await self.position_repo.update_fields(position_id, **fields)
            # Flush to DB, then refresh ORM state from DB (avoids MissingGreenlet on lazy load)
            await self.session.flush()
            await self.session.refresh(position)

        return position

    async def delete_position(self, position_id: uuid.UUID) -> None:
        """Delete a position.

        Raises HTTPException 404 if not found.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )

        boq_id = str(position.boq_id)
        await self.position_repo.delete(position_id)

        await _safe_publish(
            "boq.position.deleted",
            {"position_id": str(position_id), "boq_id": boq_id},
            source_module="oe_boq",
        )

        logger.info("Position deleted: %s from BOQ %s", position_id, boq_id)

    async def reorder_positions(
        self, boq_id: uuid.UUID, position_ids: list[uuid.UUID]
    ) -> None:
        """Reorder positions within a BOQ.

        Assigns sequential sort_order values based on the order of
        ``position_ids``.  The BOQ is verified to exist first.

        Args:
            boq_id: The BOQ that owns the positions.
            position_ids: Ordered list of position UUIDs.

        Raises:
            HTTPException 404: If the BOQ does not exist.
        """
        boq = await self.boq_repo.get_by_id(boq_id)
        if boq is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ not found",
            )
        await self.position_repo.reorder(position_ids)
        logger.info(
            "Reordered %d positions in BOQ %s", len(position_ids), boq_id
        )

    # ── Markup operations ─────────────────────────────────────────────────

    async def list_markups(self, boq_id: uuid.UUID) -> list[BOQMarkup]:
        """List all markups for a BOQ."""
        return await self.markup_repo.list_for_boq(boq_id)

    async def add_markup(self, boq_id: uuid.UUID, data: MarkupCreate) -> BOQMarkup:
        """Add a markup/overhead line to a BOQ.

        Args:
            boq_id: Target BOQ identifier.
            data: Markup creation payload.

        Returns:
            The newly created BOQMarkup.

        Raises:
            HTTPException 404 if the target BOQ doesn't exist.
        """
        await self.get_boq(boq_id)

        max_order = await self.markup_repo.get_max_sort_order(boq_id)

        markup = BOQMarkup(
            boq_id=boq_id,
            name=data.name,
            markup_type=data.markup_type,
            category=data.category,
            percentage=str(data.percentage),
            fixed_amount=str(data.fixed_amount),
            apply_to=data.apply_to,
            sort_order=data.sort_order if data.sort_order > 0 else max_order + 1,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        markup = await self.markup_repo.create(markup)

        await _safe_publish(
            "boq.markup.created",
            {
                "markup_id": str(markup.id),
                "boq_id": str(boq_id),
                "name": data.name,
            },
            source_module="oe_boq",
        )

        logger.info("Markup added: %s to BOQ %s", data.name, boq_id)
        return markup

    async def update_markup(
        self, markup_id: uuid.UUID, data: MarkupUpdate
    ) -> BOQMarkup:
        """Update a markup line.

        Args:
            markup_id: Target markup identifier.
            data: Partial update payload.

        Returns:
            Updated BOQMarkup.

        Raises:
            HTTPException 404 if markup not found.
        """
        markup = await self.markup_repo.get_by_id(markup_id)
        if markup is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "percentage" in fields:
            fields["percentage"] = str(fields["percentage"])
        if "fixed_amount" in fields:
            fields["fixed_amount"] = str(fields["fixed_amount"])

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            refreshed = await self.markup_repo.update_fields(markup_id, **fields)

            await _safe_publish(
                "boq.markup.updated",
                {
                    "markup_id": str(markup_id),
                    "boq_id": str(markup.boq_id),
                    "fields": list(fields.keys()),
                },
            )

            if refreshed is not None:
                return refreshed

        # Re-fetch to return fresh data
        updated = await self.markup_repo.get_by_id(markup_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found after update",
            )
        await self.markup_repo.session.refresh(updated)
        return updated

    async def delete_markup(self, markup_id: uuid.UUID) -> None:
        """Delete a markup line.

        Raises HTTPException 404 if not found.
        """
        markup = await self.markup_repo.get_by_id(markup_id)
        if markup is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found",
            )

        boq_id = str(markup.boq_id)
        await self.markup_repo.delete(markup_id)

        await _safe_publish(
            "boq.markup.deleted",
            {"markup_id": str(markup_id), "boq_id": boq_id},
            source_module="oe_boq",
        )

        logger.info("Markup deleted: %s from BOQ %s", markup_id, boq_id)

    async def calculate_markups(
        self, boq_id: uuid.UUID
    ) -> tuple[Decimal, list[tuple[BOQMarkup, Decimal]]]:
        """Compute markup amounts for a BOQ based on its direct cost.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            Tuple of (direct_cost, list of (markup, computed_amount)).
        """
        positions, _ = await self.position_repo.list_for_boq(boq_id)
        markups = await self.markup_repo.list_for_boq(boq_id)

        # Direct cost: sum of totals for non-section items only
        direct_cost = Decimal("0")
        for pos in positions:
            if not _is_section(pos):
                direct_cost += Decimal(str(_str_to_float(pos.total)))

        calculated = _calculate_markup_amounts(direct_cost, markups)
        return direct_cost, calculated

    async def apply_default_markups(
        self, boq_id: uuid.UUID, region: str
    ) -> list[BOQMarkup]:
        """Replace all markups on a BOQ with the default template for a region.

        Deletes existing markups and creates the standard set.

        Args:
            boq_id: Target BOQ identifier.
            region: Region code — "DACH", "UK", "US", "RU", "GULF", or "DEFAULT".

        Returns:
            List of newly created BOQMarkup objects.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        await self.get_boq(boq_id)

        # Look up template; fall back to DEFAULT
        region_key = region.upper()
        template = DEFAULT_MARKUP_TEMPLATES.get(
            region_key, DEFAULT_MARKUP_TEMPLATES["DEFAULT"]
        )

        # Remove existing markups
        await self.markup_repo.delete_all_for_boq(boq_id)

        # Create new markups from template
        new_markups: list[BOQMarkup] = []
        for entry in template:
            markup = BOQMarkup(
                boq_id=boq_id,
                name=str(entry["name"]),
                markup_type=str(entry.get("markup_type", "percentage")),
                category=str(entry["category"]),
                percentage=str(entry["percentage"]),
                fixed_amount=str(entry.get("fixed_amount", "0")),
                apply_to=str(entry.get("apply_to", "direct_cost")),
                sort_order=int(entry["sort_order"]),  # type: ignore[arg-type]
                is_active=True,
                metadata_={},
            )
            new_markups.append(markup)

        created = await self.markup_repo.bulk_create(new_markups)

        await _safe_publish(
            "boq.markups.defaults_applied",
            {"boq_id": str(boq_id), "region": region_key, "count": len(created)},
            source_module="oe_boq",
        )

        logger.info(
            "Applied %d default markups (%s) to BOQ %s",
            len(created),
            region_key,
            boq_id,
        )
        return created

    # ── Recalculate rates ─────────────────────────────────────────────────

    async def recalculate_rates(self, boq_id: uuid.UUID) -> dict[str, int]:
        """Recalculate unit_rates for all positions from their resource breakdowns.

        For each position that has ``metadata_.resources``, the unit_rate is
        recomputed as the sum of ``quantity * unit_rate`` for every resource entry.
        The position total is then ``unit_rate * position.quantity``.

        Args:
            boq_id: The BOQ whose positions should be recalculated.

        Returns:
            Dict with ``updated``, ``skipped``, and ``total`` counts.
        """
        # Ensure the BOQ exists (raises 404 otherwise)
        await self.get_boq(boq_id)

        positions, _ = await self.position_repo.list_for_boq(boq_id)
        updated = 0
        skipped = 0

        for pos in positions:
            meta = pos.metadata_ or {}
            resources = meta.get("resources", [])
            if resources:
                total_resource_cost = sum(
                    float(r.get("quantity", 0)) * float(r.get("unit_rate", 0))
                    for r in resources
                )
                if total_resource_cost > 0:
                    pos_qty = max(float(pos.quantity or 0), 1.0)
                    new_total = str(total_resource_cost * pos_qty)
                    await self.position_repo.update_fields(
                        pos.id,
                        unit_rate=str(total_resource_cost),
                        total=new_total,
                    )
                    updated += 1
                    continue
            skipped += 1

        await self.session.commit()
        return {"updated": updated, "skipped": skipped, "total": len(positions)}

    # ── Duplicate operations ─────────────────────────────────────────────

    async def duplicate_boq(self, boq_id: uuid.UUID) -> BOQ:
        """Deep-copy a BOQ with all positions and markups.

        Creates a new BOQ named ``<original> (Copy)`` under the same project.
        All positions and markups receive fresh UUIDs; parent_id references
        within positions are re-mapped to the corresponding new IDs.

        Args:
            boq_id: Source BOQ to duplicate.

        Returns:
            The newly created BOQ copy.

        Raises:
            HTTPException 404 if source BOQ not found.
        """
        source_boq = await self.get_boq(boq_id)
        # Eagerly capture all source attributes to avoid MissingGreenlet
        source_project_id = source_boq.project_id
        source_name = source_boq.name
        source_description = source_boq.description
        source_metadata = dict(source_boq.metadata_) if source_boq.metadata_ else {}

        # Create the new BOQ shell
        new_boq = BOQ(
            project_id=source_project_id,
            name=f"{source_name} (Copy)",
            description=source_description,
            status="draft",
            metadata_=source_metadata,
        )
        new_boq = await self.boq_repo.create(new_boq)
        # Eagerly capture ID to avoid MissingGreenlet if session expires attributes
        new_boq_id = new_boq.id

        # Copy positions — first pass: create all with old parent_id recorded
        positions, _ = await self.position_repo.list_for_boq(boq_id)
        old_to_new: dict[uuid.UUID, uuid.UUID] = {}

        new_positions: list[Position] = []
        for pos in positions:
            new_pos = Position(
                boq_id=new_boq_id,
                parent_id=None,  # will be remapped after insert
                ordinal=pos.ordinal,
                description=pos.description,
                unit=pos.unit,
                quantity=pos.quantity,
                unit_rate=pos.unit_rate,
                total=pos.total,
                classification=dict(pos.classification) if pos.classification else {},
                source=pos.source,
                confidence=pos.confidence,
                cad_element_ids=list(pos.cad_element_ids) if pos.cad_element_ids else [],
                validation_status="pending",
                metadata_=dict(pos.metadata_) if pos.metadata_ else {},
                sort_order=pos.sort_order,
            )
            new_positions.append(new_pos)

        created_positions = await self.position_repo.bulk_create(new_positions)

        # Build old→new ID mapping
        for old_pos, new_pos in zip(positions, created_positions):
            old_to_new[old_pos.id] = new_pos.id

        # Second pass: remap parent_id references
        for old_pos, new_pos in zip(positions, created_positions):
            if old_pos.parent_id is not None and old_pos.parent_id in old_to_new:
                await self.position_repo.update_fields(
                    new_pos.id, parent_id=old_to_new[old_pos.parent_id]
                )

        # Copy markups
        markups = await self.markup_repo.list_for_boq(boq_id)
        new_markups: list[BOQMarkup] = []
        for markup in markups:
            new_markup = BOQMarkup(
                boq_id=new_boq_id,
                name=markup.name,
                markup_type=markup.markup_type,
                category=markup.category,
                percentage=markup.percentage,
                fixed_amount=markup.fixed_amount,
                apply_to=markup.apply_to,
                sort_order=markup.sort_order,
                is_active=markup.is_active,
                metadata_=dict(markup.metadata_) if markup.metadata_ else {},
            )
            new_markups.append(new_markup)

        if new_markups:
            await self.markup_repo.bulk_create(new_markups)

        await _safe_publish(
            "boq.boq.duplicated",
            {
                "source_boq_id": str(boq_id),
                "new_boq_id": str(new_boq_id),
                "project_id": str(source_project_id),
            },
            source_module="oe_boq",
        )

        logger.info("BOQ duplicated: %s → %s", boq_id, new_boq_id)

        # Re-fetch to ensure all attributes are loaded for serialization
        return await self.get_boq(new_boq_id)

    async def duplicate_position(self, position_id: uuid.UUID) -> Position:
        """Duplicate a single position within the same BOQ.

        The copy is placed immediately after the original (same parent_id,
        ordinal appended with ``.1``).

        Args:
            position_id: Source position to duplicate.

        Returns:
            The newly created position copy.

        Raises:
            HTTPException 404 if source position not found.
        """
        source = await self.position_repo.get_by_id(position_id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )

        max_order = await self.position_repo.get_max_sort_order(source.boq_id)

        new_position = Position(
            boq_id=source.boq_id,
            parent_id=source.parent_id,
            ordinal=f"{source.ordinal}.1",
            description=source.description,
            unit=source.unit,
            quantity=source.quantity,
            unit_rate=source.unit_rate,
            total=source.total,
            classification=dict(source.classification) if source.classification else {},
            source=source.source,
            confidence=source.confidence,
            cad_element_ids=list(source.cad_element_ids) if source.cad_element_ids else [],
            validation_status="pending",
            metadata_=dict(source.metadata_) if source.metadata_ else {},
            sort_order=max_order + 1,
        )
        new_position = await self.position_repo.create(new_position)

        await _safe_publish(
            "boq.position.duplicated",
            {
                "source_position_id": str(position_id),
                "new_position_id": str(new_position.id),
                "boq_id": str(source.boq_id),
            },
            source_module="oe_boq",
        )

        logger.info(
            "Position duplicated: %s → %s in BOQ %s",
            position_id,
            new_position.id,
            source.boq_id,
        )
        return new_position

    # ── Composite reads ───────────────────────────────────────────────────

    async def get_boq_with_positions(self, boq_id: uuid.UUID) -> BOQWithPositions:
        """Get a BOQ with all its positions and computed grand total.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            BOQWithPositions including positions list and grand_total.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)
        positions, _ = await self.position_repo.list_for_boq(boq_id)

        # Build position responses with float conversions
        position_responses = []
        grand_total = Decimal("0")

        for pos in positions:
            position_responses.append(_build_position_response(pos))
            # Exclude section headers from grand total (sections have no unit)
            if not _is_section(pos):
                total_val = _str_to_float(pos.total)
                grand_total += Decimal(str(total_val))

        return BOQWithPositions(
            id=boq.id,
            project_id=boq.project_id,
            name=boq.name,
            description=boq.description,
            status=boq.status,
            metadata_=boq.metadata_,
            created_at=boq.created_at,
            updated_at=boq.updated_at,
            positions=position_responses,
            grand_total=float(grand_total),
        )

    async def get_boq_structured(self, boq_id: uuid.UUID) -> BOQWithSections:
        """Get a BOQ with sections, subtotals, markups, and computed totals.

        Positions are grouped into sections based on parent_id.  Positions
        without a parent that are not sections themselves appear in the
        top-level ``positions`` list.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            BOQWithSections with full hierarchical structure.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)
        all_positions, _ = await self.position_repo.list_for_boq(boq_id)

        # Separate sections from items
        section_map: dict[uuid.UUID, Position] = {}
        children_map: dict[uuid.UUID, list[Position]] = {}
        ungrouped_items: list[Position] = []

        for pos in all_positions:
            if _is_section(pos):
                section_map[pos.id] = pos
                children_map.setdefault(pos.id, [])
            elif pos.parent_id is not None and pos.parent_id in section_map:
                children_map.setdefault(pos.parent_id, []).append(pos)
            elif pos.parent_id is not None:
                # Parent exists but is not a section — still group under parent
                # if parent is in section_map after full scan, handled below
                ungrouped_items.append(pos)
            else:
                ungrouped_items.append(pos)

        # Second pass: items whose parent_id was scanned later
        remaining_ungrouped: list[Position] = []
        for pos in ungrouped_items:
            if pos.parent_id is not None and pos.parent_id in section_map:
                children_map.setdefault(pos.parent_id, []).append(pos)
            else:
                remaining_ungrouped.append(pos)

        # Build section responses
        sections: list[SectionResponse] = []
        direct_cost = Decimal("0")

        for section_id, section_pos in section_map.items():
            child_responses: list[PositionResponse] = []
            subtotal = Decimal("0")
            for child in children_map.get(section_id, []):
                child_responses.append(_build_position_response(child))
                subtotal += Decimal(str(_str_to_float(child.total)))

            sections.append(
                SectionResponse(
                    id=section_pos.id,
                    ordinal=section_pos.ordinal,
                    description=section_pos.description,
                    positions=child_responses,
                    subtotal=float(subtotal),
                )
            )
            direct_cost += subtotal

        # Ungrouped items
        ungrouped_responses: list[PositionResponse] = []
        for pos in remaining_ungrouped:
            if not _is_section(pos):
                ungrouped_responses.append(_build_position_response(pos))
                direct_cost += Decimal(str(_str_to_float(pos.total)))

        # Calculate markups
        markups_orm = await self.markup_repo.list_for_boq(boq_id)
        markup_results = _calculate_markup_amounts(direct_cost, markups_orm)

        markups_calculated: list[MarkupCalculated] = []
        markup_total = Decimal("0")
        for markup_obj, amount in markup_results:
            markups_calculated.append(
                MarkupCalculated(
                    id=markup_obj.id,
                    boq_id=markup_obj.boq_id,
                    name=markup_obj.name,
                    markup_type=markup_obj.markup_type,
                    category=markup_obj.category,
                    percentage=_str_to_float(markup_obj.percentage),
                    fixed_amount=_str_to_float(markup_obj.fixed_amount),
                    apply_to=markup_obj.apply_to,
                    sort_order=markup_obj.sort_order,
                    is_active=markup_obj.is_active,
                    metadata_=markup_obj.metadata_,
                    created_at=markup_obj.created_at,
                    updated_at=markup_obj.updated_at,
                    amount=float(amount),
                )
            )
            markup_total += amount

        net_total = direct_cost + markup_total

        return BOQWithSections(
            id=boq.id,
            project_id=boq.project_id,
            name=boq.name,
            description=boq.description,
            status=boq.status,
            metadata_=boq.metadata_,
            created_at=boq.created_at,
            updated_at=boq.updated_at,
            sections=sections,
            positions=ungrouped_responses,
            direct_cost=float(direct_cost),
            markups=markups_calculated,
            net_total=float(net_total),
            grand_total=float(net_total),
        )

    # ── Cost breakdown ─────────────────────────────────────────────────

    async def get_cost_breakdown(self, boq_id: uuid.UUID) -> CostBreakdownResponse:
        """Compute a cost breakdown for a BOQ by resource type.

        For each position, reads ``metadata_.resources`` (list of dicts with
        keys ``type``, ``total``, ``name``, ``unit``, ``quantity``, ``unit_rate``).
        Resource costs are scaled by the position quantity and aggregated into
        categories: labor, material, equipment, subcontractor, other.

        If no resource metadata is found on any position, the full position
        total is categorised based on description keyword heuristics.

        Overhead and profit are computed from the BOQ's markup lines or
        default to 15% overhead + 10% profit when no markups exist.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            CostBreakdownResponse with categories, markups, and top resources.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)
        all_positions, _ = await self.position_repo.list_for_boq(boq_id)

        # Accumulators
        category_amounts: dict[str, float] = {}
        category_counts: dict[str, int] = {}
        resource_totals: dict[str, float] = {}  # name -> total cost
        resource_types: dict[str, str] = {}  # name -> type
        resource_positions: dict[str, set[uuid.UUID]] = {}  # name -> position ids
        for pos in all_positions:
            if _is_section(pos):
                continue

            pos_qty = _str_to_float(pos.quantity)
            pos_total = _str_to_float(pos.total)
            meta = pos.metadata_ or {}
            resources = meta.get("resources")

            if isinstance(resources, list) and len(resources) > 0:
                for res in resources:
                    if not isinstance(res, dict):
                        continue
                    res_type = str(res.get("type", "other")).lower()
                    res_name = str(res.get("name", "Unknown"))
                    res_total = float(res.get("total", 0))

                    cat = self._normalize_resource_category(res_type)

                    # Scale resource cost by position quantity
                    scaled_cost = res_total * max(pos_qty, 1.0)

                    category_amounts[cat] = category_amounts.get(cat, 0.0) + scaled_cost
                    category_counts[cat] = category_counts.get(cat, 0) + 1

                    resource_totals[res_name] = (
                        resource_totals.get(res_name, 0.0) + scaled_cost
                    )
                    resource_types[res_name] = cat
                    resource_positions.setdefault(res_name, set()).add(pos.id)
            else:
                # Heuristic fallback — classify by description keywords (fast)
                cat = self._classify_position_category(pos.description)
                category_amounts[cat] = category_amounts.get(cat, 0.0) + pos_total
                category_counts[cat] = category_counts.get(cat, 0) + 1

                short_name = (
                    pos.description[:60] if pos.description else "Position"
                )
                resource_totals[short_name] = (
                    resource_totals.get(short_name, 0.0) + pos_total
                )
                resource_types[short_name] = cat
                resource_positions.setdefault(short_name, set()).add(pos.id)

        direct_cost_val = sum(category_amounts.values())

        # Build categories sorted by amount descending
        categories: list[CostBreakdownCategory] = []
        for cat, amount in sorted(
            category_amounts.items(), key=lambda x: x[1], reverse=True
        ):
            pct = (amount / direct_cost_val * 100.0) if direct_cost_val > 0 else 0.0
            categories.append(
                CostBreakdownCategory(
                    type=cat,
                    amount=round(amount, 2),
                    percentage=round(pct, 1),
                    item_count=category_counts.get(cat, 0),
                )
            )

        # Calculate markups from BOQ markup lines (or defaults)
        markups_orm = await self.markup_repo.list_for_boq(boq_id)
        markup_lines: list[CostBreakdownMarkup] = []
        markup_total = Decimal("0")

        if markups_orm:
            markup_results = _calculate_markup_amounts(
                Decimal(str(direct_cost_val)), markups_orm
            )
            for markup_obj, amount in markup_results:
                if markup_obj.is_active:
                    markup_lines.append(
                        CostBreakdownMarkup(
                            name=markup_obj.name,
                            percentage=_str_to_float(markup_obj.percentage),
                            amount=round(float(amount), 2),
                        )
                    )
                    markup_total += amount
        else:
            overhead_amount = Decimal(str(direct_cost_val)) * Decimal("0.15")
            profit_amount = Decimal(str(direct_cost_val)) * Decimal("0.10")
            markup_lines = [
                CostBreakdownMarkup(
                    name="Overhead",
                    percentage=15.0,
                    amount=round(float(overhead_amount), 2),
                ),
                CostBreakdownMarkup(
                    name="Profit",
                    percentage=10.0,
                    amount=round(float(profit_amount), 2),
                ),
            ]
            markup_total = overhead_amount + profit_amount

        grand_total = float(Decimal(str(direct_cost_val)) + markup_total)

        # Top 10 resources by cost
        top_resources: list[CostBreakdownResource] = []
        for name, total_cost in sorted(
            resource_totals.items(), key=lambda x: x[1], reverse=True
        )[:10]:
            top_resources.append(
                CostBreakdownResource(
                    name=name,
                    type=resource_types.get(name, "other"),
                    total_cost=round(total_cost, 2),
                    positions_count=len(resource_positions.get(name, set())),
                )
            )

        await _safe_publish(
            "boq.cost_breakdown.computed",
            {"boq_id": str(boq_id), "direct_cost": round(direct_cost_val, 2)},
        )

        return CostBreakdownResponse(
            boq_id=str(boq_id),
            grand_total=round(grand_total, 2),
            direct_cost=round(direct_cost_val, 2),
            categories=categories,
            markups=markup_lines,
            top_resources=top_resources,
        )

    @staticmethod
    def _normalize_resource_category(res_type: str) -> str:
        """Normalize a resource type string into a standard category.

        Args:
            res_type: Raw resource type from position metadata.

        Returns:
            One of: labor, material, equipment, subcontractor, other.
        """
        res_type = res_type.lower().strip()
        if res_type in ("labor", "labour", "work", "lohn", "arbeit"):
            return "labor"
        if res_type in (
            "material", "materials", "mat", "baustoff", "baustoffe",
        ):
            return "material"
        if res_type in (
            "equipment", "plant", "machinery", "geraet", "maschine",
        ):
            return "equipment"
        if res_type in (
            "subcontractor", "sub", "nachunternehmer", "fremdleistung",
        ):
            return "subcontractor"
        return "other"

    @staticmethod
    def _classify_position_category(description: str) -> str:
        """Classify a position into a cost category based on description keywords.

        Used as a fallback when no resource metadata is available.

        Args:
            description: BOQ position description text.

        Returns:
            One of: labor, material, equipment, other.
        """
        desc_lower = (description or "").lower()

        material_keywords = (
            "beton", "concrete", "stahl", "steel", "holz", "timber", "wood",
            "ziegel", "brick", "glas", "glass", "daemmung", "insulation",
            "fliesen", "tile", "putz", "plaster", "farbe", "paint",
            "rohr", "pipe", "kabel", "cable", "mortar",
            "kies", "gravel", "sand", "zement", "cement", "bitumen",
            "asphalt", "kupfer", "copper", "aluminium", "aluminum",
            "lieferung", "delivery", "material",
        )
        labor_keywords = (
            "montage", "installation", "verlegung", "laying", "einbau",
            "abbruch", "demolition", "aushub", "excavation", "erdarbeit",
            "earthwork", "schalung", "formwork", "bewehrung", "reinforcement",
            "anstrich", "painting", "labor", "labour", "arbeit", "work",
            "verlegen", "install", "mauern", "betonieren",
        )
        equipment_keywords = (
            "kran", "crane", "bagger", "excavator", "geruest", "scaffold",
            "equipment", "machine", "pump", "pumpe", "container",
            "transport", "miete", "rental", "hire",
        )

        for kw in material_keywords:
            if kw in desc_lower:
                return "material"
        for kw in labor_keywords:
            if kw in desc_lower:
                return "labor"
        for kw in equipment_keywords:
            if kw in desc_lower:
                return "equipment"
        return "other"

    @staticmethod
    async def _lookup_cost_item_components(
        cost_repo: CostItemRepository, description: str
    ) -> list[dict[str, Any]]:
        """Look up cost item components matching a position description.

        Searches the cost database for an item whose description matches the
        position description.  If found and the cost item has a non-empty
        ``components`` list, returns it so callers can use the component-level
        resource data for breakdown and resource summary.

        Args:
            cost_repo: CostItemRepository instance (uses the same session).
            description: Position description to search for.

        Returns:
            A list of component dicts (may be empty).
        """
        if not description:
            return []

        try:
            items, _ = await cost_repo.search(q=description, limit=1)
            if not items:
                return []
            item = items[0]
            components = item.components or []
            if isinstance(components, str):
                import json as _json
                components = _json.loads(components)
            if isinstance(components, list) and len(components) > 0:
                return components
        except Exception:
            logger.debug("Cost item lookup failed for: %s", description[:60])
        return []

    # ── Template operations ────────────────────────────────────────────────

    def list_templates(self) -> list[TemplateInfo]:
        """Return summary information for all available built-in templates."""
        result: list[TemplateInfo] = []
        for template_id, tpl in TEMPLATES.items():
            section_count = len(tpl["sections"])
            position_count = sum(
                len(sec["positions"]) for sec in tpl["sections"]
            )
            result.append(
                TemplateInfo(
                    id=template_id,
                    name=tpl["name"],
                    description=tpl["description"],
                    icon=tpl["icon"],
                    section_count=section_count,
                    position_count=position_count,
                )
            )
        return result

    async def create_boq_from_template(self, data: BOQFromTemplateRequest) -> BOQ:
        """Create a complete BOQ from a built-in template.

        Creates the BOQ, section headers, and all positions with quantities
        derived from ``area_m2 * qty_factor``.

        Args:
            data: Template request with project_id, template_id, area_m2, and
                  optional boq_name.

        Returns:
            The newly created BOQ.

        Raises:
            HTTPException 400 if template_id is unknown.
        """
        template = TEMPLATES.get(data.template_id)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown template: {data.template_id}. "
                f"Available: {', '.join(TEMPLATES.keys())}",
            )

        boq_name = data.boq_name or template["name"]

        # Create the BOQ shell
        boq = BOQ(
            project_id=data.project_id,
            name=boq_name,
            description=template["description"],
            status="draft",
            metadata_={"template_id": data.template_id, "area_m2": data.area_m2},
        )
        boq = await self.boq_repo.create(boq)

        sort_order = 0

        for section_def in template["sections"]:
            # Create section header
            section = Position(
                boq_id=boq.id,
                parent_id=None,
                ordinal=section_def["ordinal"],
                description=section_def["description"],
                unit="section",
                quantity="0",
                unit_rate="0",
                total="0",
                classification={},
                source="template",
                confidence=None,
                cad_element_ids=[],
                metadata_={},
                sort_order=sort_order,
            )
            section = await self.position_repo.create(section)
            sort_order += 1

            # Create positions under this section
            for pos_def in section_def["positions"]:
                quantity = Decimal(str(data.area_m2)) * Decimal(str(pos_def["qty_factor"]))
                unit_rate = Decimal(str(pos_def["rate"]))
                total = quantity * unit_rate

                position = Position(
                    boq_id=boq.id,
                    parent_id=section.id,
                    ordinal=pos_def["ordinal"],
                    description=pos_def["description"],
                    unit=pos_def["unit"],
                    quantity=str(quantity),
                    unit_rate=str(unit_rate),
                    total=str(total),
                    classification={},
                    source="template",
                    confidence=None,
                    cad_element_ids=[],
                    metadata_={"qty_factor": pos_def["qty_factor"]},
                    sort_order=sort_order,
                )
                await self.position_repo.create(position)
                sort_order += 1

        await _safe_publish(
            "boq.boq.created_from_template",
            {
                "boq_id": str(boq.id),
                "project_id": str(data.project_id),
                "template_id": data.template_id,
                "area_m2": data.area_m2,
            },
            source_module="oe_boq",
        )

        logger.info(
            "BOQ created from template '%s': %s (project=%s, area=%.1f m2)",
            data.template_id,
            boq.name,
            data.project_id,
            data.area_m2,
        )
        return boq

    # ── Activity log operations ────────────────────────────────────────────

    async def log_activity(
        self,
        *,
        user_id: uuid.UUID,
        action: str,
        target_type: str,
        description: str,
        project_id: uuid.UUID | None = None,
        boq_id: uuid.UUID | None = None,
        target_id: uuid.UUID | None = None,
        changes: dict | None = None,
        metadata_: dict | None = None,
    ) -> BOQActivityLog:
        """Create an activity log entry.

        Args:
            user_id: Who performed the action.
            action: Dot-notation action, e.g. "position.created".
            target_type: Entity kind, e.g. "position", "boq", "markup".
            description: Human-readable summary.
            project_id: Optional project scope.
            boq_id: Optional BOQ scope.
            target_id: Optional UUID of the affected entity.
            changes: Optional field-level diff dict.
            metadata_: Optional additional context.

        Returns:
            The created BOQActivityLog entry.
        """
        entry = BOQActivityLog(
            project_id=project_id,
            boq_id=boq_id,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            description=description,
            changes=changes or {},
            metadata_=metadata_ or {},
        )
        return await self.activity_repo.create(entry)

    async def get_activity_for_boq(
        self,
        boq_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> ActivityLogList:
        """Retrieve paginated activity log for a BOQ.

        Args:
            boq_id: Target BOQ.
            offset: Pagination offset.
            limit: Max entries to return.

        Returns:
            ActivityLogList with items, total, offset, limit.
        """
        # Verify BOQ exists
        await self.get_boq(boq_id)

        entries, total = await self.activity_repo.list_for_boq(
            boq_id, offset=offset, limit=limit
        )
        items = [
            ActivityLogResponse(
                id=e.id,
                project_id=e.project_id,
                boq_id=e.boq_id,
                user_id=e.user_id,
                action=e.action,
                target_type=e.target_type,
                target_id=e.target_id,
                description=e.description,
                changes=e.changes,
                metadata_=e.metadata_,
                created_at=e.created_at,
            )
            for e in entries
        ]
        return ActivityLogList(items=items, total=total, offset=offset, limit=limit)

    async def get_activity_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> ActivityLogList:
        """Retrieve paginated activity log for a project.

        Args:
            project_id: Target project.
            offset: Pagination offset.
            limit: Max entries to return.

        Returns:
            ActivityLogList with items, total, offset, limit.
        """
        entries, total = await self.activity_repo.list_for_project(
            project_id, offset=offset, limit=limit
        )
        items = [
            ActivityLogResponse(
                id=e.id,
                project_id=e.project_id,
                boq_id=e.boq_id,
                user_id=e.user_id,
                action=e.action,
                target_type=e.target_type,
                target_id=e.target_id,
                description=e.description,
                changes=e.changes,
                metadata_=e.metadata_,
                created_at=e.created_at,
            )
            for e in entries
        ]
        return ActivityLogList(items=items, total=total, offset=offset, limit=limit)

    # ── AACE Estimate Classification ─────────────────────────────────────

    async def get_estimate_classification(
        self, boq_id: uuid.UUID
    ) -> EstimateClassificationResponse:
        """Determine AACE 18R-97 estimate class for a BOQ.

        Auto-detects class based on:
        - Number of line-item positions (excluding section headers)
        - Percentage of positions with unit rates filled
        - Percentage of positions with resources (description + quantity + rate)
        - Percentage of positions with classification codes

        Returns:
            EstimateClassificationResponse with class, accuracy range, and metrics.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        await self.get_boq(boq_id)
        all_positions, _ = await self.position_repo.list_for_boq(boq_id)

        # Filter out section headers — only count real line items
        items = [p for p in all_positions if not _is_section(p)]
        total_positions = len(items)

        if total_positions == 0:
            return _build_classification(0, 0, 0, 0)

        # Count positions with non-zero unit rates
        positions_with_rates = sum(
            1 for p in items if _str_to_float(p.unit_rate) > 0
        )

        # "Resources" = has description AND quantity > 0 AND unit_rate > 0
        positions_with_resources = sum(
            1
            for p in items
            if (p.description or "").strip()
            and _str_to_float(p.quantity) > 0
            and _str_to_float(p.unit_rate) > 0
        )

        # Positions with at least one classification code
        positions_with_classification = sum(
            1
            for p in items
            if p.classification and any(p.classification.values())
        )

        return _build_classification(
            total_positions,
            positions_with_rates,
            positions_with_resources,
            positions_with_classification,
        )

    # ── Snapshot operations ────────────────────────────────────────────────

    async def list_snapshots(self, boq_id: uuid.UUID) -> list[BOQSnapshot]:
        """List all snapshots for a BOQ, newest first."""
        from sqlalchemy import select

        stmt = (
            select(BOQSnapshot)
            .where(BOQSnapshot.boq_id == boq_id)
            .order_by(BOQSnapshot.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_snapshot(
        self, boq_id: uuid.UUID, *, name: str = "", user_id: uuid.UUID | None = None
    ) -> BOQSnapshot:
        """Create a point-in-time snapshot of the current BOQ state."""
        boq = await self.get_boq(boq_id)

        # Serialize positions
        positions_data = []
        for p in boq.positions:
            positions_data.append({
                "ordinal": p.ordinal,
                "description": p.description,
                "unit": p.unit,
                "quantity": p.quantity,
                "unit_rate": p.unit_rate,
                "total": p.total,
                "parent_id": str(p.parent_id) if p.parent_id else None,
                "classification": p.classification,
                "source": p.source,
                "metadata": p.metadata_,
                "sort_order": p.sort_order,
            })

        # Serialize markups
        markups_data = []
        for m in boq.markups:
            markups_data.append({
                "name": m.name,
                "markup_type": m.markup_type,
                "category": m.category,
                "percentage": m.percentage,
                "fixed_amount": m.fixed_amount,
                "apply_to": m.apply_to,
                "sort_order": m.sort_order,
                "is_active": m.is_active,
            })

        snapshot_data = {
            "boq_name": boq.name,
            "boq_status": boq.status,
            "positions": positions_data,
            "markups": markups_data,
            "position_count": len(positions_data),
        }

        auto_name = name or f"Snapshot ({len(positions_data)} positions)"
        snap = BOQSnapshot(
            boq_id=boq_id,
            name=auto_name,
            snapshot_data=snapshot_data,
            created_by=user_id,
        )
        self.session.add(snap)
        await self.session.flush()
        await self.session.refresh(snap)
        return snap

    async def restore_snapshot(
        self, boq_id: uuid.UUID, snapshot_id: uuid.UUID
    ) -> BOQWithPositions:
        """Restore a BOQ to a previous snapshot state.

        Deletes all current positions and recreates them from the snapshot.
        """
        from sqlalchemy import select, delete as sa_delete

        # Load snapshot
        stmt = select(BOQSnapshot).where(
            BOQSnapshot.id == snapshot_id,
            BOQSnapshot.boq_id == boq_id,
        )
        result = await self.session.execute(stmt)
        snap = result.scalar_one_or_none()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        data = snap.snapshot_data

        # Delete current positions
        await self.session.execute(
            sa_delete(Position).where(Position.boq_id == boq_id)
        )
        await self.session.flush()

        # Recreate positions from snapshot
        for pdata in data.get("positions", []):
            pos = Position(
                boq_id=boq_id,
                ordinal=pdata["ordinal"],
                description=pdata["description"],
                unit=pdata.get("unit", "pcs"),
                quantity=pdata.get("quantity", "0"),
                unit_rate=pdata.get("unit_rate", "0"),
                total=pdata.get("total", "0"),
                classification=pdata.get("classification", {}),
                source=pdata.get("source", "manual"),
                metadata_=pdata.get("metadata", {}),
                sort_order=pdata.get("sort_order", 0),
            )
            self.session.add(pos)

        await self.session.flush()
        return await self.get_boq_with_positions(boq_id)

    # ── AI-powered classification ─────────────────────────────────────────

    async def classify_position(
        self,
        description: str,
        unit: str,
        project_standard: str,
    ) -> list[dict[str, Any]]:
        """Suggest classification codes for a position using vector similarity.

        Encodes the description as a vector, searches the cost database for
        similar items, extracts their classification codes, and ranks by
        frequency weighted by similarity score.

        Args:
            description: Position description text.
            unit: Unit of measurement (used to build a richer query).
            project_standard: Target standard — "din276", "nrm", or "masterformat".

        Returns:
            List of suggestion dicts with keys: standard, code, label, confidence.
            Returns empty list if vector DB is unavailable.
        """
        try:
            from app.core.vector import encode_texts_async, vector_search
        except Exception:
            logger.debug("Vector module not available for classify_position")
            return []

        # Build a richer query text for embedding
        query_text = description
        if unit:
            query_text = f"{description} [{unit}]"

        try:
            vectors = await encode_texts_async([query_text])
        except Exception:
            logger.debug("Embedding failed for classify_position")
            return []

        query_vec = vectors[0]

        try:
            import asyncio
            matches = await asyncio.to_thread(vector_search, query_vec, None, 10)
        except Exception:
            logger.debug("Vector search failed for classify_position")
            return []

        if not matches:
            return []

        # Aggregate classification codes by frequency x similarity
        code_scores: dict[str, float] = {}
        code_labels: dict[str, str] = {}

        for match in matches:
            score = max(float(match.get("score", 0.0)), 0.0)  # clamp negative distances
            code = str(match.get("code", "")).strip()
            desc = str(match.get("description", "")).strip()

            if not code or score <= 0:
                continue

            if code not in code_scores:
                code_scores[code] = 0.0
                code_labels[code] = desc
            code_scores[code] += score

        if not code_scores:
            return []

        # Rank by aggregated score, take top 5
        ranked = sorted(code_scores.items(), key=lambda x: x[1], reverse=True)[:5]

        # Normalize confidence to 0..1 range
        max_score = ranked[0][1] if ranked else 1.0
        max_score = max(max_score, 0.001)

        suggestions: list[dict[str, Any]] = []
        for code, score in ranked:
            confidence = round(max(0.0, min(score / max_score, 1.0)), 3)
            suggestions.append({
                "standard": project_standard,
                "code": code,
                "label": code_labels.get(code, ""),
                "confidence": confidence,
            })

        return suggestions

    # ── AI-powered rate suggestion ────────────────────────────────────────

    async def suggest_rate(
        self,
        description: str,
        unit: str,
        classification: dict[str, Any],
        region: str | None,
    ) -> dict[str, Any]:
        """Suggest a market rate for a position using vector similarity search.

        Encodes the description, searches the cost database for similar items,
        filters by unit if provided, and computes a weighted average rate.

        Args:
            description: Position description text.
            unit: Unit of measurement for filtering.
            classification: Classification dict (unused currently, reserved).
            region: Optional region filter for vector search.

        Returns:
            Dict with keys: suggested_rate, confidence, source, matches.
            Returns zero rate with empty matches if vector DB is unavailable.
        """
        empty_result: dict[str, Any] = {
            "suggested_rate": 0.0,
            "confidence": 0.0,
            "source": "vector_search",
            "matches": [],
        }

        try:
            from app.core.vector import encode_texts_async, vector_search
        except Exception:
            logger.debug("Vector module not available for suggest_rate")
            return empty_result

        query_text = description
        if unit:
            query_text = f"{description} [{unit}]"

        try:
            vectors = await encode_texts_async([query_text])
        except Exception:
            logger.debug("Embedding failed for suggest_rate")
            return empty_result

        query_vec = vectors[0]

        try:
            import asyncio
            matches = await asyncio.to_thread(vector_search, query_vec, region, 10)
        except Exception:
            logger.debug("Vector search failed for suggest_rate")
            return empty_result

        if not matches:
            return empty_result

        # Filter by matching unit if provided
        if unit:
            unit_lower = unit.lower().strip()
            unit_filtered = [
                m for m in matches
                if str(m.get("unit", "")).lower().strip() == unit_lower
            ]
            # If filtering removes everything, keep all matches
            if unit_filtered:
                matches = unit_filtered

        # Calculate weighted average rate (weighted by similarity score)
        total_weight = 0.0
        weighted_sum = 0.0
        rate_matches: list[dict[str, Any]] = []

        for m in matches:
            rate = float(m.get("rate", 0.0))
            score = float(m.get("score", 0.0))

            if rate <= 0:
                continue

            weighted_sum += rate * score
            total_weight += score

            rate_matches.append({
                "code": str(m.get("code", "")),
                "description": str(m.get("description", "")),
                "rate": round(rate, 2),
                "region": str(m.get("region", "")),
                "score": round(score, 4),
            })

        if total_weight == 0:
            return empty_result

        suggested_rate = round(weighted_sum / total_weight, 2)

        # Confidence based on average similarity score and match count
        avg_score = total_weight / len(rate_matches) if rate_matches else 0.0
        match_factor = min(len(rate_matches) / 5.0, 1.0)
        confidence = round(avg_score * match_factor, 3)

        return {
            "suggested_rate": suggested_rate,
            "confidence": min(confidence, 1.0),
            "source": "vector_search",
            "matches": rate_matches,
        }

    # ── Anomaly detection ─────────────────────────────────────────────────

    async def check_anomalies(
        self, boq_id: uuid.UUID
    ) -> dict[str, Any]:
        """Check all positions in a BOQ for pricing anomalies.

        For each position with a description and unit_rate > 0, uses vector
        search to find 5-10 similar items. Computes p25, median, p75 of
        matched rates. Flags positions whose rate deviates significantly from
        the market range.

        Thresholds:
        - rate > 3x median  -> severity "error"
        - rate > 2x median  -> severity "warning"
        - rate < 0.3x median -> severity "warning" (suspiciously low)

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            Dict with keys: anomalies (list), positions_checked (int).

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq_data = await self.get_boq_with_positions(boq_id)

        try:
            from app.core.vector import encode_texts_async, vector_search
        except Exception:
            logger.debug("Vector module not available for check_anomalies")
            return {"anomalies": [], "positions_checked": 0}

        import asyncio

        MAX_POSITIONS = 80  # Limit to prevent timeout

        # Collect eligible positions
        eligible: list[Any] = []
        for pos in boq_data.positions:
            if not pos.description or pos.unit_rate <= 0:
                continue
            if pos.unit and pos.unit.strip().lower() == "section":
                continue
            eligible.append(pos)
            if len(eligible) >= MAX_POSITIONS:
                break

        if not eligible:
            return {"anomalies": [], "positions_checked": 0}

        # Batch encode all descriptions in a single call
        query_texts = []
        for pos in eligible:
            qt = pos.description
            if pos.unit:
                qt = f"{pos.description} [{pos.unit}]"
            query_texts.append(qt)

        try:
            all_vectors = await encode_texts_async(query_texts)
        except Exception:
            logger.debug("Batch embedding failed for check_anomalies")
            return {"anomalies": [], "positions_checked": 0}

        # Search for each position in parallel
        async def _search_one(idx: int) -> list[dict]:
            try:
                return await asyncio.to_thread(
                    vector_search, all_vectors[idx], None, 10
                )
            except Exception:
                return []

        all_matches = await asyncio.gather(
            *[_search_one(i) for i in range(len(eligible))]
        )

        def _percentile_val(data: list[float], pct: float) -> float:
            idx = pct / 100.0 * (len(data) - 1)
            lower = int(idx)
            upper = min(lower + 1, len(data) - 1)
            frac = idx - lower
            return data[lower] + frac * (data[upper] - data[lower])

        anomalies: list[dict[str, Any]] = []

        for pos, matches in zip(eligible, all_matches):
            if not matches:
                continue

            # Filter by matching unit if possible
            if pos.unit:
                unit_lower = pos.unit.lower().strip()
                unit_filtered = [
                    m for m in matches
                    if str(m.get("unit", "")).lower().strip() == unit_lower
                ]
                if unit_filtered:
                    matches = unit_filtered

            # Extract rates from matches
            rates = [
                float(m.get("rate", 0.0))
                for m in matches
                if float(m.get("rate", 0.0)) > 0
            ]

            if len(rates) < 2:
                continue

            sorted_rates = sorted(rates)

            p25 = round(_percentile_val(sorted_rates, 25), 2)
            median = round(_percentile_val(sorted_rates, 50), 2)
            p75 = round(_percentile_val(sorted_rates, 75), 2)

            if median <= 0:
                continue

            current_rate = pos.unit_rate
            market_range = {"p25": p25, "median": median, "p75": p75}

            severity: str | None = None
            message = ""

            if current_rate > 3.0 * median:
                severity = "error"
                message = (
                    f"Unit rate {current_rate:.2f} is more than 3x the "
                    f"market median {median:.2f}. Likely a pricing error."
                )
            elif current_rate > 2.0 * median:
                severity = "warning"
                message = (
                    f"Unit rate {current_rate:.2f} is more than 2x the "
                    f"market median {median:.2f}. Review recommended."
                )
            elif current_rate < 0.3 * median:
                severity = "warning"
                message = (
                    f"Unit rate {current_rate:.2f} is less than 30% of the "
                    f"market median {median:.2f}. Suspiciously low."
                )

            if severity:
                anomalies.append({
                    "position_id": str(pos.id),
                    "field": "unit_rate",
                    "current_value": round(current_rate, 2),
                    "market_range": market_range,
                    "severity": severity,
                    "message": message,
                    "suggestion": median,
                })

        return {
            "anomalies": anomalies,
            "positions_checked": len(eligible),
        }

    # ── AI Cost Finder (vector search) ──────────────────────────────────

    async def search_cost_items(
        self,
        query: str,
        unit: str | None = None,
        region: str | None = None,
        limit: int = 15,
        min_score: float = 0.3,
    ) -> dict[str, Any]:
        """Search cost items using vector similarity.

        Encodes query text, searches the vector DB, filters by min_score and
        optionally by unit, then enriches results with full DB records
        (components, classification) from the SQL cost_items table.

        Args:
            query: Natural-language description to search for.
            unit: Optional unit filter (exact match, case-insensitive).
            region: Optional region filter passed to vector search.
            limit: Max results to return (1-30).
            min_score: Minimum similarity score threshold (0.0-1.0).

        Returns:
            Dict with keys: results, total_found, query_embedding_ms, search_ms.
        """
        import asyncio
        import time

        empty: dict[str, Any] = {
            "results": [],
            "total_found": 0,
            "query_embedding_ms": 0,
            "search_ms": 0,
        }

        try:
            from app.core.vector import encode_texts_async, vector_search
        except Exception:
            logger.debug("Vector module not available for search_cost_items")
            return empty

        # Build richer query text
        query_text = query
        if unit:
            query_text = f"{query} [{unit}]"

        # Encode
        t0 = time.monotonic()
        try:
            vectors = await encode_texts_async([query_text])
        except Exception:
            logger.debug("Embedding failed for search_cost_items")
            return empty
        embed_ms = round((time.monotonic() - t0) * 1000, 1)

        # Search (request more than limit to allow filtering)
        t1 = time.monotonic()
        try:
            raw_matches = await asyncio.to_thread(
                vector_search, vectors[0], region, min(limit * 2, 30)
            )
        except Exception:
            logger.debug("Vector search failed for search_cost_items")
            return empty
        search_ms = round((time.monotonic() - t1) * 1000, 1)

        # Filter by min_score and unit
        filtered = []
        for m in raw_matches:
            score = float(m.get("score", 0))
            if score < min_score:
                continue
            if unit:
                m_unit = str(m.get("unit", "")).lower().strip()
                if m_unit and m_unit != unit.lower().strip():
                    continue
            filtered.append(m)

        filtered = filtered[:limit]

        if not filtered:
            return {**empty, "query_embedding_ms": embed_ms, "search_ms": search_ms}

        # Enrich from SQL DB (components, classification)
        from app.modules.costs.repository import CostItemRepository

        cost_repo = CostItemRepository(self.session)
        codes = [str(m.get("code", "")) for m in filtered]
        db_items = await cost_repo.get_by_codes(codes)
        db_map = {item.code: item for item in db_items}

        results = []
        for m in filtered:
            code = str(m.get("code", ""))
            db_item = db_map.get(code)
            results.append({
                "id": str(m.get("id", "")),
                "code": code,
                "description": str(m.get("description", "")),
                "unit": str(m.get("unit", "")),
                "rate": round(float(m.get("rate", 0)), 2),
                "region": str(m.get("region", "")),
                "score": round(float(m.get("score", 0)), 4),
                "classification": (db_item.classification or {}) if db_item else {},
                "components": (db_item.components or []) if db_item else [],
                "currency": (db_item.currency if db_item else "EUR") or "EUR",
            })

        return {
            "results": results,
            "total_found": len(results),
            "query_embedding_ms": embed_ms,
            "search_ms": search_ms,
        }

    # ── LLM-powered AI features ──────────────────────────────────────────────

    async def _get_ai_client(self, user_id: str) -> tuple[str, str]:
        """Resolve AI provider and API key for the current user.

        Returns:
            Tuple of (provider, api_key).

        Raises:
            HTTPException 400: If no API key is configured.
        """
        from app.modules.ai.ai_client import resolve_provider_and_key
        from app.modules.ai.repository import AISettingsRepository
        import uuid as _uuid

        settings_repo = AISettingsRepository(self.session)
        uid = _uuid.UUID(user_id)
        settings = await settings_repo.get_by_user_id(uid)

        try:
            return resolve_provider_and_key(settings)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    async def _call_llm(
        self, user_id: str, system: str, prompt: str
    ) -> tuple[str, str, int]:
        """Call LLM and return (raw_text, provider, tokens_used)."""
        from app.modules.ai.ai_client import call_ai

        provider, api_key = await self._get_ai_client(user_id)
        raw_text, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=system,
            prompt=prompt,
            max_tokens=2048,
        )
        return raw_text, provider, tokens

    async def enhance_description(
        self,
        user_id: str,
        description: str,
        unit: str = "m2",
        classification: dict[str, str] | None = None,
        locale: str = "en",
    ) -> dict[str, Any]:
        """Enhance a BOQ position description using LLM.

        Args:
            user_id: Current user's ID (for API key resolution).
            description: Short position description to enhance.
            unit: Unit of measurement.
            classification: Optional classification codes.
            locale: User's language for AI response text.

        Returns:
            Dict with enhanced_description, specifications, standards, confidence.
        """
        from app.modules.ai.ai_client import extract_json
        from app.modules.boq.ai_prompts import (
            ENHANCE_DESCRIPTION_PROMPT,
            ENHANCE_DESCRIPTION_SYSTEM,
            with_locale,
        )

        cls_str = ", ".join(f"{k}: {v}" for k, v in (classification or {}).items()) or "none"
        prompt = ENHANCE_DESCRIPTION_PROMPT.format(
            description=description, unit=unit, classification=cls_str,
        )

        raw_text, provider, tokens = await self._call_llm(
            user_id, with_locale(ENHANCE_DESCRIPTION_SYSTEM, locale), prompt,
        )
        parsed = extract_json(raw_text)

        if not isinstance(parsed, dict):
            return {
                "enhanced_description": description,
                "specifications": [],
                "standards": [],
                "confidence": 0.0,
                "model_used": provider,
                "tokens_used": tokens,
            }

        return {
            "enhanced_description": str(parsed.get("enhanced_description", description)),
            "specifications": parsed.get("specifications", []),
            "standards": parsed.get("standards", []),
            "confidence": max(0.0, min(float(parsed.get("confidence", 0.5)), 1.0)),
            "model_used": provider,
            "tokens_used": tokens,
        }

    async def suggest_prerequisites(
        self,
        user_id: str,
        description: str,
        unit: str = "m2",
        classification: dict[str, str] | None = None,
        existing_descriptions: list[str] | None = None,
        locale: str = "en",
    ) -> dict[str, Any]:
        """Suggest prerequisite/related positions for a BOQ item.

        Args:
            user_id: Current user's ID.
            description: Target position description.
            unit: Unit of measurement.
            classification: Optional classification codes.
            existing_descriptions: Descriptions already in the BOQ (to avoid duplicates).
            locale: User's language for AI response text.

        Returns:
            Dict with suggestions list, model_used, tokens_used.
        """
        from app.modules.ai.ai_client import extract_json
        from app.modules.boq.ai_prompts import (
            SUGGEST_PREREQUISITES_PROMPT,
            SUGGEST_PREREQUISITES_SYSTEM,
            with_locale,
        )

        cls_str = ", ".join(f"{k}: {v}" for k, v in (classification or {}).items()) or "none"
        existing = "\n".join(
            f"  - {d}" for d in (existing_descriptions or [])[:30]
        ) or "  (none)"

        prompt = SUGGEST_PREREQUISITES_PROMPT.format(
            description=description,
            unit=unit,
            classification=cls_str,
            existing_positions=existing,
        )

        raw_text, provider, tokens = await self._call_llm(
            user_id, with_locale(SUGGEST_PREREQUISITES_SYSTEM, locale), prompt,
        )
        parsed = extract_json(raw_text)

        if not isinstance(parsed, list):
            return {"suggestions": [], "model_used": provider, "tokens_used": tokens}

        suggestions = []
        for item in parsed[:8]:
            if not isinstance(item, dict):
                continue
            suggestions.append({
                "description": str(item.get("description", "")),
                "unit": str(item.get("unit", "lsum")),
                "typical_rate_eur": round(float(item.get("typical_rate_eur", 0)), 2),
                "relationship": str(item.get("relationship", "companion")),
                "reason": str(item.get("reason", "")),
            })

        return {"suggestions": suggestions, "model_used": provider, "tokens_used": tokens}

    async def check_scope_completeness(
        self,
        user_id: str,
        boq_id: Any,
        project_type: str = "general",
        region: str = "DACH",
        currency: str = "EUR",
        locale: str = "en",
    ) -> dict[str, Any]:
        """Check BOQ scope completeness using LLM analysis.

        Sends a summary of all BOQ positions to the LLM and asks it to
        identify missing trades, work packages, and critical items.

        Args:
            user_id: Current user's ID.
            boq_id: Target BOQ identifier.
            project_type: Type of construction project.
            region: Project region.
            currency: Currency code.

        Returns:
            Dict with completeness_score, missing_items, warnings, summary.
        """
        from app.modules.ai.ai_client import extract_json
        from app.modules.boq.ai_prompts import CHECK_SCOPE_PROMPT, CHECK_SCOPE_SYSTEM, with_locale

        # Fetch BOQ positions
        boq = await self.boq_repo.get_by_id(boq_id)
        if not boq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")

        positions = await self.position_repo.list_by_boq(boq_id)
        if not positions:
            return {
                "completeness_score": 0.0,
                "missing_items": [],
                "warnings": ["BOQ is empty — no positions to analyze."],
                "summary": "Empty BOQ.",
                "model_used": "",
                "tokens_used": 0,
            }

        # Build summary (truncate to avoid token overflow)
        grand_total = 0.0
        summary_lines = []
        for p in positions[:80]:
            desc = (p.description or "")[:80]
            qty = float(p.quantity or 0)
            rate = float(p.unit_rate or 0)
            total = qty * rate
            grand_total += total
            unit = p.unit or ""
            line = f"  - {p.ordinal or ''} | {desc} | {unit} | qty={qty:.1f} | rate={rate:.2f}"
            summary_lines.append(line)

        prompt = CHECK_SCOPE_PROMPT.format(
            project_type=project_type,
            region=region,
            total_positions=len(positions),
            currency=currency,
            grand_total=f"{grand_total:,.2f}",
            positions_summary="\n".join(summary_lines),
        )

        raw_text, provider, tokens = await self._call_llm(
            user_id, with_locale(CHECK_SCOPE_SYSTEM, locale), prompt,
        )
        parsed = extract_json(raw_text)

        if not isinstance(parsed, dict):
            return {
                "completeness_score": 0.0,
                "missing_items": [],
                "warnings": ["AI analysis failed to produce structured results."],
                "summary": "",
                "model_used": provider,
                "tokens_used": tokens,
            }

        missing = []
        for item in parsed.get("missing_items", [])[:10]:
            if not isinstance(item, dict):
                continue
            missing.append({
                "description": str(item.get("description", "")),
                "category": str(item.get("category", "")),
                "priority": str(item.get("priority", "medium")),
                "reason": str(item.get("reason", "")),
                "estimated_rate": round(float(item.get("estimated_rate", 0)), 2),
                "unit": str(item.get("unit", "lsum")),
            })

        return {
            "completeness_score": max(0.0, min(float(parsed.get("completeness_score", 0)), 1.0)),
            "missing_items": missing,
            "warnings": [str(w) for w in parsed.get("warnings", [])],
            "summary": str(parsed.get("summary", "")),
            "model_used": provider,
            "tokens_used": tokens,
        }

    async def escalate_rate(
        self,
        user_id: str,
        description: str,
        unit: str,
        rate: float,
        currency: str = "EUR",
        base_year: int = 2023,
        target_year: int = 2026,
        region: str = "DACH",
        locale: str = "en",
    ) -> dict[str, Any]:
        """Escalate a unit rate to current prices using LLM analysis.

        Args:
            user_id: Current user's ID.
            description: Position description.
            unit: Unit of measurement.
            rate: Current unit rate.
            currency: Currency code.
            base_year: Year the rate was established.
            target_year: Target year for escalation.
            region: Project region.

        Returns:
            Dict with escalated_rate, escalation_percent, factors, reasoning.
        """
        from app.modules.ai.ai_client import extract_json
        from app.modules.boq.ai_prompts import ESCALATE_RATE_PROMPT, ESCALATE_RATE_SYSTEM, with_locale

        prompt = ESCALATE_RATE_PROMPT.format(
            description=description,
            unit=unit,
            rate=rate,
            currency=currency,
            base_year=base_year,
            target_year=target_year,
            region=region,
        )

        raw_text, provider, tokens = await self._call_llm(
            user_id, with_locale(ESCALATE_RATE_SYSTEM, locale), prompt,
        )
        parsed = extract_json(raw_text)

        if not isinstance(parsed, dict):
            return {
                "original_rate": rate,
                "escalated_rate": rate,
                "escalation_percent": 0.0,
                "factors": {},
                "confidence": "low",
                "reasoning": "AI analysis failed.",
                "model_used": provider,
                "tokens_used": tokens,
            }

        factors = parsed.get("factors", {})
        if not isinstance(factors, dict):
            factors = {}

        return {
            "original_rate": rate,
            "escalated_rate": round(float(parsed.get("escalated_rate", rate)), 2),
            "escalation_percent": round(float(parsed.get("escalation_percent", 0)), 1),
            "factors": {
                "material_inflation": round(float(factors.get("material_inflation", 0)), 1),
                "labor_cost_change": round(float(factors.get("labor_cost_change", 0)), 1),
                "regional_adjustment": round(float(factors.get("regional_adjustment", 0)), 1),
            },
            "confidence": str(parsed.get("confidence", "medium")),
            "reasoning": str(parsed.get("reasoning", "")),
            "model_used": provider,
            "tokens_used": tokens,
        }
