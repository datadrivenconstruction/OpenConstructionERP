# OpenConstructionERP - DataDrivenConstruction (DDC)
# CWICR Cost Database Engine · BOQ Module
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""‌⁠‍BOQ service - business logic for Bill of Quantities management.

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
import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from app.modules.boq.schemas import PositionLinksResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate

# ── CWICR variant snapshot helpers ───────────────────────────────────────
#
# When a BOQ position is applied from a CostItem that carries CWICR
# abstract-resource variants (e.g. concrete C25 / C30 / C35), the position
# stores either the picked variant under ``metadata.variant`` (with
# ``{label, price, index}``) or - when the user accepted the auto-suggested
# average - under ``metadata.variant_default = "mean" | "median"``.
#
# To make the relationship immutable from the position's side, we also write
# ``metadata.variant_snapshot`` with a frozen copy at the moment of choice:
#
#     {
#         "label": str,            # variant label or "average"/"median"
#         "rate": float,           # numeric unit rate captured at this point
#         "currency": str,         # ISO 4217 currency code
#         "captured_at": str,      # UTC ISO-8601 timestamp
#         "source": "user_pick" | "default_mean" | "default_median",
#     }
#
# The snapshot is computed deterministically from the incoming metadata
# (``variant`` / ``variant_default`` / ``variant_stats`` / ``unit_rate``
# / ``currency``) so any later import / cost-DB rate change cannot silently
# rewrite the BOQ position's price.  Callers re-stamp the snapshot only when
# ``variant`` or ``variant_default`` actually changes - a no-op patch leaves
# the existing snapshot intact.


def _stamp_variant_snapshot(
    metadata: dict[str, Any],
    *,
    unit_rate: float | str | Decimal | None,
    currency: str | None,
) -> dict[str, Any]:
    """‌⁠‍Add or refresh ``metadata.variant_snapshot`` when the metadata carries
    a ``variant`` (user pick) or ``variant_default`` (auto-average) marker.

    Idempotent: when ``variant_snapshot`` already exists and matches the
    current ``variant`` / ``variant_default``, the existing snapshot is
    preserved (we don't move ``captured_at`` forward on a no-op patch).

    Returns the same metadata dict (mutated in-place) so it can be fed back
    into the SQL UPDATE without an extra alloc.

    Args:
        metadata: BOQ position metadata dict.  Must be safe to mutate.
        unit_rate: The numeric unit rate the caller is about to persist.
            Accepts string / Decimal / float to mirror ``_quantize_money_str``.
        currency: ISO 4217 code captured alongside the rate.  ``None`` is
            allowed; falls back to ``"USD"`` to avoid losing the snapshot.
    """
    variant = metadata.get("variant")
    variant_default = metadata.get("variant_default")

    has_user_pick = (
        isinstance(variant, dict)
        and isinstance(variant.get("label"), str)
        and isinstance(variant.get("price"), int | float)
    )
    has_default = isinstance(variant_default, str) and variant_default in {
        "mean",
        "median",
    }

    if not (has_user_pick or has_default):
        return metadata

    # Numeric rate - quantise lightly so the snapshot never carries a
    # full-precision Decimal that won't survive JSON round-trip.
    try:
        rate_val = float(unit_rate) if unit_rate is not None else 0.0
    except (TypeError, ValueError):
        rate_val = 0.0
    rate_val = round(rate_val, 4)

    if has_user_pick:
        label = str(variant["label"])
        source = "user_pick"
    else:
        label = "average" if variant_default == "mean" else "median"
        source = f"default_{variant_default}"

    existing = metadata.get("variant_snapshot")
    if (
        isinstance(existing, dict)
        and existing.get("label") == label
        and existing.get("source") == source
        and abs(float(existing.get("rate", 0)) - rate_val) < 0.005
    ):
        # No-op patch - preserve the original captured_at timestamp so the
        # immutability marker doesn't drift on every unrelated metadata
        # update.
        return metadata

    metadata["variant_snapshot"] = {
        "label": label,
        "rate": rate_val,
        "currency": currency or "",
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source,
    }
    return metadata


def _stamp_resource_variant_snapshots(
    metadata: dict[str, Any],
    *,
    position_currency: str | None,
) -> dict[str, Any]:
    """‌⁠‍Walk ``metadata.resources`` and stamp ``variant_snapshot`` on every
    resource entry that carries a per-resource ``variant`` or
    ``variant_default`` marker.

    Mirrors the position-level helper but operates on each resource dict
    independently so a position composed of multiple variant-bearing CWICR
    items (e.g. concrete C30 + rebar 8mm) keeps an immutable record per
    resource. Currency falls back to the per-resource ``currency`` field
    first, then ``position_currency``, then ``"USD"``.

    Idempotent: a no-op patch leaves existing snapshots intact.
    """
    resources = metadata.get("resources")
    if not isinstance(resources, list):
        return metadata

    for resource in resources:
        if not isinstance(resource, dict):
            continue
        variant = resource.get("variant")
        variant_default = resource.get("variant_default")

        has_user_pick = (
            isinstance(variant, dict)
            and isinstance(variant.get("label"), str)
            and isinstance(variant.get("price"), int | float)
        )
        has_default = isinstance(variant_default, str) and variant_default in {
            "mean",
            "median",
        }

        if not (has_user_pick or has_default):
            continue

        try:
            rate_val = float(resource.get("unit_rate", 0) or 0)
        except (TypeError, ValueError):
            rate_val = 0.0
        rate_val = round(rate_val, 4)

        if has_user_pick:
            label = str(variant["label"])
            source = "user_pick"
        else:
            label = "average" if variant_default == "mean" else "median"
            source = f"default_{variant_default}"

        existing = resource.get("variant_snapshot")
        if (
            isinstance(existing, dict)
            and existing.get("label") == label
            and existing.get("source") == source
            and abs(float(existing.get("rate", 0)) - rate_val) < 0.005
        ):
            continue

        resource_currency = resource.get("currency")
        # Resource currency wins; fall back to position currency; finally
        # leave empty rather than stamping "USD" / "EUR" - both lie when
        # the project is in another currency. The variant_snapshot reader
        # tolerates empty currency and renders the rate as a bare number.
        currency = (
            resource_currency if isinstance(resource_currency, str) and resource_currency else (position_currency or "")
        )

        resource["variant_snapshot"] = {
            "label": label,
            "rate": rate_val,
            "currency": currency,
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": source,
        }

    return metadata


logger_events = logging.getLogger(__name__ + ".events")
_logger_audit = logging.getLogger(__name__ + ".audit")


async def _safe_publish(name: str, data: dict[str, Any], source_module: str = "oe_boq") -> None:
    """Publish event safely - ignores MissingGreenlet errors with SQLite async."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        logger_events.debug("Event publish skipped (SQLite async): %s", name)


async def _safe_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Best-effort audit log - never blocks the caller on failure."""
    try:
        from app.core.audit import audit_log

        await audit_log(
            session,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            details=details,
        )
    except Exception:
        _logger_audit.debug("Audit log write skipped for %s %s", action, entity_type)


from app.modules.boq.models import (
    BOQ,
    BOQActivityLog,
    BOQMarkup,
    BOQSnapshot,
    Position,
    QuantityLink,
)
from app.modules.boq.repository import (
    ActivityLogRepository,
    BOQRepository,
    MarkupRepository,
    PositionRepository,
    QuantityLinkRepository,
)
from app.modules.boq.schemas import (
    ActivityLogList,
    ActivityLogResponse,
    BOQCompareResponse,
    BOQCreate,
    BOQFromTemplateRequest,
    BOQStatisticsResponse,
    BOQUpdate,
    BOQWithPositions,
    BOQWithSections,
    BulkPositionUpdate,
    BulkUpdateResult,
    ComparePositionRow,
    CompareSummary,
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
    QuantityLinkApplyResponse,
    QuantityLinkApplyResultRow,
    QuantityLinkCreate,
    QuantityLinkRefreshResponse,
    QuantityLinkRefreshRow,
    QuantityLinkResponse,
    ResourceCodeLookupResponse,
    ResourceCodeMatch,
    SectionCreate,
    SectionResponse,
    TemplateInfo,
)
from app.modules.boq.templates import TEMPLATES
from app.modules.costs.repository import CostItemRepository

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


def _to_decimal(
    value: str | int | float | Decimal | None,
    default: Decimal = Decimal("0"),
) -> Decimal:
    """Safely coerce a numeric-ish value to Decimal (precision-preserving).

    - Strings are parsed verbatim (so "12.345" stays exact).
    - Floats go through ``repr`` to preserve their true representation
      rather than the display-truncated ``str(float)`` that drops digits.
    - NaN / ±Infinity are rejected - money never uses those - and the
      default is returned instead so downstream arithmetic stays well-defined.
    """
    if value is None:
        return default
    try:
        if isinstance(value, Decimal):
            d = value
        elif isinstance(value, bool):
            # bool is a subclass of int - reject so we don't quietly
            # accept True/False where a number is expected.
            return default
        elif isinstance(value, int):
            d = Decimal(value)
        elif isinstance(value, float):
            d = Decimal(repr(value))
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return default
            d = Decimal(stripped)
        else:
            return default
    except (InvalidOperation, ValueError, TypeError):
        return default
    if not d.is_finite():
        return default
    return d


# BUG-MATH01: enforce a fixed 4-decimal-place precision boundary at the
# storage layer.  the architecture guide specifies decimal arithmetic with explicit
# rounding; previously we wrote whatever Decimal multiplication produced
# (e.g. ``99.99 * 0.1 = 9.999``), which leaked binary-float drift in for
# any caller that fed floats in via ``repr``.  Quantising at write time
# turns the column into a NUMERIC(18,4) equivalent regardless of the
# underlying String-vs-Numeric storage choice.
_MONEY_QUANTUM = Decimal("0.0001")


def _quantize_money(value: Decimal) -> Decimal:
    """Round a Decimal to 4 fractional digits using banker's rounding.

    Returns the input unchanged when the value is non-finite - callers
    upstream already guarded those.  ROUND_HALF_EVEN ("banker's rounding")
    is the regulated default for monetary aggregations and avoids the
    upward bias of HALF_UP over millions of line items.
    """
    from decimal import ROUND_HALF_EVEN

    if not value.is_finite():
        return value
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def _quantize_money_str(value: str | int | float | Decimal | None) -> str:
    """Coerce → Decimal → quantize(4dp) → canonical string.

    Used at every write boundary for ``quantity``, ``unit_rate``, and
    ``total`` so the DB never holds more than 4 fractional digits.
    """
    return str(_quantize_money(_to_decimal(value)))


# BUG-B-001 / BUG-B-012: rollup figures (direct_cost, markup amounts,
# net_total, grand_total, section subtotals) must be returned quantised to
# the currency minor unit using *commercial* rounding (ROUND_HALF_UP), not
# the 4dp banker's rounding used for per-line storage and not raw
# full-precision Decimal. Storage stays at 4dp (q×r identity preserved
# per-line); only the aggregate read boundary is snapped to cents so the
# editor (structured), the list endpoint, statistics and cost-breakdown all
# return ONE canonical number for the same BOQ.
_CURRENCY_QUANTUM = Decimal("0.01")


def _round_currency(value: Decimal | float | int | str | None) -> Decimal:
    """Quantise an aggregate monetary value to 2dp, ROUND_HALF_UP.

    v3 §10 - returns a ``Decimal`` so downstream Pydantic schemas
    typed as ``Decimal`` don't round-trip through float and re-introduce
    precision drift. Non-finite / unparseable input collapses to
    ``Decimal('0.00')`` so a corrupt intermediate never serialises as
    ``NaN`` / ``Infinity``.
    """
    from decimal import ROUND_HALF_UP

    d = value if isinstance(value, Decimal) else _to_decimal(value)
    if not d.is_finite():
        return Decimal("0.00")
    return d.quantize(_CURRENCY_QUANTUM, rounding=ROUND_HALF_UP)


def _coerce_audit_value(value: Any) -> Any:
    """Convert a Position attribute to a JSON-safe primitive (BUG-AUDIT01).

    Activity-log ``changes`` is stored as a JSON column; raw UUID /
    datetime / Decimal instances trip the SQLite JSON serialiser and
    break the diff write entirely.  Stringify them; primitives, dicts
    and lists pass through unchanged.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce_audit_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce_audit_value(v) for k, v in value.items()}
    return str(value)


def _compute_total(
    quantity: str | int | float | Decimal | None,
    unit_rate: str | int | float | Decimal | None,
) -> str:
    """Compute ``quantity * unit_rate`` preserving exact decimal precision.

    Returns a canonical string representation safe for SQLite storage.
    The product is quantised to 4 decimal places (BUG-MATH01) so aggregate
    drift cannot compound across thousands of lines.
    """
    q = _to_decimal(quantity)
    r = _to_decimal(unit_rate)
    return str(_quantize_money(q * r))


def _str_to_float(value: str | None) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0.

    Used only in section-detection comparisons where exact precision is not
    required. For money arithmetic, use ``_to_decimal`` instead.
    """
    if value is None:
        return 0.0
    try:
        f = float(value)
    except (ValueError, TypeError):
        return 0.0
    # Reject NaN/Infinity - section detection compares against 0.0 and a
    # non-finite value there would make ``_is_section`` misbehave.
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f


def _is_section(position: Position) -> bool:
    """Determine whether a position is a section/sub-section header.

    A section is any position whose unit is empty or ``"section"``
    and whose quantity and unit_rate are both zero.
    Sections can exist at any depth (top-level or nested under another section).
    This enables multi-level BOQ hierarchies (3-4+ levels).
    """
    unit = (position.unit or "").strip().lower()
    qty = _str_to_float(position.quantity)
    rate = _str_to_float(position.unit_rate)
    return unit in ("", "section") and qty == 0.0 and rate == 0.0


def _stamp_resource_breakdown(metadata: dict[str, Any]) -> None:
    """Stamp ``metadata['resource_breakdown']`` from ``metadata['resources']``.

    Canonical server-side M/L/E rollup: ``{type: {"total": float, "pct": float}}``
    mirroring the shape written by the assembly apply path
    (``assemblies/service.py``) and the demo seeder's
    ``_resource_breakdown_rollup``. Each resource contributes its ``total``
    when present, else ``quantity * unit_rate`` (the per-unit norm convention).
    When resources are absent/empty or the rolled subtotal is not positive,
    any previously stamped ``resource_breakdown`` is removed so a stale split
    never survives a resources wipe (audit m5).
    ``float`` values in JSONB metadata follow the existing convention there.
    """
    resources = metadata.get("resources")
    if not isinstance(resources, list) or not resources:
        metadata.pop("resource_breakdown", None)
        return
    totals: dict[str, Decimal] = {}
    for res in resources:
        if not isinstance(res, dict):
            continue
        rtype = str(res.get("type") or "other")
        if res.get("total") is not None:
            try:
                ttl = Decimal(str(res.get("total")))
            except (ArithmeticError, ValueError):
                ttl = Decimal("0")
        else:
            try:
                ttl = Decimal(str(res.get("quantity") or 0)) * Decimal(str(res.get("unit_rate") or 0))
            except (ArithmeticError, ValueError):
                ttl = Decimal("0")
        if not ttl.is_finite():
            ttl = Decimal("0")
        totals[rtype] = totals.get(rtype, Decimal("0")) + ttl
    subtotal = sum(totals.values(), Decimal("0"))
    if subtotal <= 0:
        metadata.pop("resource_breakdown", None)
        return
    metadata["resource_breakdown"] = {
        rtype: {
            "total": float(ttl),
            "pct": float((ttl / subtotal) * Decimal("100")),
        }
        for rtype, ttl in totals.items()
    }


def _resource_total_in_base(
    resources: list[dict[str, Any]],
    fx_rates_map: dict[str, str] | None,
    base_currency: str,
) -> Decimal:
    """Sum resource subtotals in the project's BASE currency.

    Issue #88 - each resource dict may carry an optional ``currency``. When
    present and different from ``base_currency``, the row's contribution is
    converted via ``fx_rates_map[currency]`` (units of base per 1 unit of
    foreign). Missing currency → treated as base. Missing rate for a
    foreign currency → resource is summed in its own units anyway, but
    the caller is expected to surface a "missing FX rate" warning at UI
    time (this function silently skips the conversion to keep the rollup
    deterministic and never zero out a row).

    The rollup is accumulated with ``Decimal`` (qty, rate and fx are coerced
    via ``_to_decimal``) so summing many lines never drifts in binary float
    before the caller's ``_quantize_money_str`` snaps to 4dp. Returns a
    ``Decimal``; callers already wrap it via ``_quantize_money_str`` /
    ``_to_decimal(str(...))``.

    Pure function - no DB I/O - so it's cheap to call from update_position
    and reusable from snapshot/export paths.
    """
    if not resources:
        return Decimal("0")
    base = (base_currency or "").upper()
    total = Decimal("0")
    for r in resources:
        if not isinstance(r, dict):
            continue
        qty = _to_decimal(r.get("quantity"))
        rate = _to_decimal(r.get("unit_rate"))
        sub = qty * rate
        code = str(r.get("currency") or "").strip().upper()
        if code and code != base and fx_rates_map:
            fx = fx_rates_map.get(code)
            if fx:
                fx_dec = _to_decimal(fx)
                if fx_dec.is_finite() and fx_dec != 0:
                    sub = sub * fx_dec
        total += sub
    return total


def _detect_resource_fx_warnings(
    resources: list[dict[str, Any]] | None,
    fx_rates_map: dict[str, str] | None,
    base_currency: str,
) -> list[str]:
    """Issue #157 (skolodi): collect resource currency codes that have no FX
    rate in the project's ``fx_rates`` table.

    The rollup at ``_resource_total_in_base`` silently no-ops the conversion
    when a foreign-currency resource has no rate (preserves the value in its
    own units to keep the rollup deterministic and never zero a row). The
    side effect is the bug skolodi recorded on video: changing a resource's
    currency from EUR to USD with no USD rate produces an identical sum
    (`sub = qty * rate * 1` == `sub = qty * rate * <missing>` because the
    multiplication is skipped) - so the section total appears unchanged
    even though the user just touched the row. ARS has a rate in his
    project, hence "ARS updates but USD doesn't."

    Returning the list of missing codes lets the API surface a per-position
    warning so the UI can prompt "Add USD to Project Settings" instead of
    silently producing a math-correct-but-user-confusing no-op.

    Pure function - no DB I/O - safe to call from any write path.
    """
    if not isinstance(resources, list) or not resources:
        return []
    base = (base_currency or "").strip().upper()
    have = {k.upper() for k in (fx_rates_map or {}).keys()}
    missing: list[str] = []
    seen: set[str] = set()
    for r in resources:
        if not isinstance(r, dict):
            continue
        raw = r.get("currency")
        if not isinstance(raw, str):
            # Mirror ``_resource_total_in_base`` permissiveness elsewhere
            # but reject non-string currency fields here: they almost
            # always indicate malformed input (an int leaking in from a
            # bad parser) and rolling them up as warnings would surface
            # noise instead of actionable codes in the UI badge.
            continue
        code = raw.strip().upper()
        if not code or code == base:
            continue
        if code in have:
            continue
        if code in seen:
            continue
        seen.add(code)
        missing.append(code)
    return missing


def _project_fx_map(project: object | None) -> dict[str, str]:
    """Project the ``Project.fx_rates`` JSON list into ``{code: rate}``.

    Defensive against missing attribute / malformed entries - returns an
    empty dict in any error path so callers can pass it through
    ``_resource_total_in_base`` without further guards.
    """
    if project is None:
        return {}
    raw = getattr(project, "fx_rates", None)
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip().upper()
        rate = str(entry.get("rate") or "").strip()
        if code and rate:
            out[code] = rate
    return out


def _position_currency(pos: Position) -> str:
    """Resolve a position's home currency from its metadata.

    Mirrors the grid path (``groupPositionsIntoSections`` in the frontend
    ``api.ts``, the Issue #131 fix the user verified): the per-position
    ``metadata.currency`` is authoritative. ``project_currency`` /
    ``position_currency`` are accepted as legacy fallbacks so older
    imported rows keep converting. Empty → "" (caller treats as base).
    """
    meta = pos.metadata_ if isinstance(getattr(pos, "metadata_", None), dict) else {}
    for key in ("currency", "position_currency", "project_currency"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().upper()
    return ""


def _position_total_in_base(
    total: str | None,
    currency_code: str | None,
    fx_rates_map: dict[str, str] | None,
    base_currency: str,
) -> Decimal:
    """Convert one position's stored ``total`` into the project BASE currency.

    Issue #111 - sibling of #131, which fixed this exact defect in the grid
    path (``groupPositionsIntoSections``). ``get_boq_structured`` powers the
    CSV / Excel / PDF exports and was summing foreign-currency ``total``
    strings straight into the base-currency Direct Cost / Grand Total.

    Semantics match ``_resource_total_in_base``: a position priced in a
    non-base currency contributes ``total * fx_rates_map[currency]`` (units
    of base per 1 unit of foreign). Missing currency → treated as base.
    Missing rate for a foreign currency → summed in its own units anyway
    (never zeroed) so the rollup stays deterministic and a forgotten FX
    rate degrades visibly rather than silently dropping money.
    """
    amount = _to_decimal(total)
    base = (base_currency or "").strip().upper()
    code = (currency_code or "").strip().upper()
    if code and code != base and fx_rates_map:
        fx = fx_rates_map.get(code)
        if fx:
            converted = _to_decimal(fx, default=Decimal("1"))
            if converted > 0:
                amount = amount * converted
    return amount


def _leaf_total_base_with_resources(
    pos: object,
    fx_rates_map: dict[str, str] | None,
    base_currency: str,
) -> Decimal:
    """Convert a leaf position's total into the project BASE currency.

    Issue #111 (skolodi follow-up) - ``_position_total_in_base`` only ever
    converted a position whose ``metadata.currency`` was set.  The
    contributor's real data (``Prueba_2.csv``) is the shape that path can
    never catch: the position carries NO ``metadata.currency`` but its
    ``metadata.resources`` are priced in a foreign currency.  At write
    time ``update_position`` derives ``unit_rate = Σ(r.quantity ×
    r.unit_rate)`` with no FX conversion, so the stored position ``total``
    silently mixes foreign-resource money into the base-currency rollup -
    a USD 25 000 resource in an ARS project rolled up as 25 000 ARS.

    Resolution order:

    * If the position has ``metadata.resources``, the per-unit ``unit_rate``
      is the sum of each resource's ``quantity × unit_rate`` converted
      from its own currency (``_resource_total_in_base`` semantics).  The
      position total is then ``position.quantity × that converted
      per-unit rate`` - exactly mirroring how ``update_position`` builds
      ``total`` from ``unit_rate``, but now currency-correct.  This fixes
      BOTH places the contributor circled (the per-position resource
      subtotal AND the section subtotal that sums these leaves).

    * Otherwise fall back to the established position-level
      ``_position_total_in_base`` / ``_position_currency`` path so legacy
      ``metadata.currency`` positions keep their verified #131 behaviour.

    Pure function - no DB I/O.  Safe to call from the structured rollup,
    compare, and export paths.
    """
    meta = getattr(pos, "metadata_", None)
    if not isinstance(meta, dict):
        meta = getattr(pos, "metadata", None)
    resources = meta.get("resources") if isinstance(meta, dict) else None

    has_priced_resources = (
        isinstance(resources, list) and len(resources) > 0 and any(isinstance(r, dict) for r in resources)
    )
    if has_priced_resources:
        # If NONE of the resources carries a foreign currency the
        # position total is already wholly in base - keep the stored
        # decimal (preserves the exact 4 dp string the editor wrote and
        # avoids a float roundtrip through the resource sum).
        base = (base_currency or "").strip().upper()
        any_foreign = any(
            isinstance(r, dict) and str(r.get("currency") or "").strip().upper() not in ("", base) for r in resources
        )
        if not any_foreign:
            return _position_total_in_base(
                getattr(pos, "total", "0"),
                _position_currency(pos) if hasattr(pos, "metadata_") or hasattr(pos, "metadata") else "",
                fx_rates_map,
                base_currency,
            )
        # Per-unit rate, currency-converted across mixed resource
        # currencies, then scaled by the position quantity (resources
        # are per-unit norms - same convention update_position uses to
        # build unit_rate then total).
        per_unit_base = _to_decimal(str(_resource_total_in_base(resources, fx_rates_map, base_currency)))
        qty = _to_decimal(getattr(pos, "quantity", "0"))
        return per_unit_base * qty

    return _position_total_in_base(
        getattr(pos, "total", "0"),
        _position_currency(pos),
        fx_rates_map,
        base_currency,
    )


def _build_position_response(pos: Position) -> PositionResponse:
    """Build a PositionResponse from a Position ORM instance."""
    return PositionResponse(
        id=pos.id,
        boq_id=pos.boq_id,
        parent_id=pos.parent_id,
        ordinal=pos.ordinal,
        description=pos.description,
        unit=pos.unit,
        # BUG-B-011: pass the exact stored 4 dp decimal strings straight
        # through - PositionResponse now types these as Decimal and
        # serialises a plain string, so large totals round-trip exactly
        # instead of being truncated by a float coercion here.
        quantity=pos.quantity,
        unit_rate=pos.unit_rate,
        total=pos.total,
        classification=pos.classification,
        source=pos.source,
        confidence=(_str_to_float(pos.confidence) if pos.confidence is not None else None),
        cad_element_ids=pos.cad_element_ids,
        validation_status=pos.validation_status,
        metadata_=pos.metadata_,
        sort_order=pos.sort_order,
        created_at=pos.created_at,
        updated_at=pos.updated_at,
        # Issue #127: surface the reuse-group fields read-only.
        reference_code=getattr(pos, "reference_code", None),
        link_role=getattr(pos, "link_role", None),
        link_group_id=getattr(pos, "link_group_id", None),
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
            "Capacity-factored, parametric models, judgment, or analogy. Based on very limited project information."
        ),
    },
    4: {
        "label": "Feasibility / Study",
        "accuracy_low": "-30%",
        "accuracy_high": "+50%",
        "definition_low": 1,
        "definition_high": 15,
        "methodology": (
            "Equipment-factored or parametric models. Based on schematic or conceptual design information."
        ),
    },
    3: {
        "label": "Budget / Authorization",
        "accuracy_low": "-20%",
        "accuracy_high": "+30%",
        "definition_low": 10,
        "definition_high": 40,
        "methodology": (
            "Semi-detailed unit costs with assembly-level line items. Based on preliminary design or developed design."
        ),
    },
    2: {
        "label": "Control / Bid / Tender",
        "accuracy_low": "-15%",
        "accuracy_high": "+20%",
        "definition_low": 30,
        "definition_high": 75,
        "methodology": (
            "Detailed unit costs with forced detailed takeoff. Based on detailed design or tender documentation."
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
    resource_pct = (positions_with_resources / total_positions * 100) if total_positions > 0 else 0.0
    classification_pct = (positions_with_classification / total_positions * 100) if total_positions > 0 else 0.0

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


def _stamp_cost_item_compat(
    metadata: dict[str, Any],
    *,
    cost_item: Any,
    position_unit: str | None,
    project_currency: str | None = None,
) -> bool:
    """Record the linked CostItem's unit/currency and flag a mismatch.

    BUG-B-013: applying a matched cost-database rate previously stored no
    provenance and ran no compatibility check - a EUR / m³ catalogue rate
    could be silently applied to a GBP / m² position. We can't FX-convert
    here (rates live in the finance module - cross-module), and a hard
    block would over-restrict legitimate cross-unit assemblies. Instead we
    follow the architecture guide principle #7 (AI-augmented, human-confirmed): stamp
    ``cost_item_currency`` / ``cost_item_unit`` so the value is never lost
    and raise a non-blocking warning the traffic-light dashboard surfaces
    when the units disagree.

    Returns ``True`` when a compatibility warning was recorded so the
    caller can set ``validation_status='warnings'``.
    """
    ci_unit = (str(getattr(cost_item, "unit", "") or "")).strip()
    ci_currency = (str(getattr(cost_item, "currency", "") or "")).strip()
    if ci_unit:
        metadata["cost_item_unit"] = ci_unit
    if ci_currency:
        metadata["cost_item_currency"] = ci_currency

    warnings: list[str] = []
    pos_unit = (position_unit or "").strip()
    if ci_unit and pos_unit and ci_unit.lower() != pos_unit.lower():
        warnings.append(
            f"Cost item is priced per '{ci_unit}' but this position is "
            f"measured in '{pos_unit}' - verify the rate applies to the "
            f"position's quantity basis.",
        )
    # Currency mismatch. We never auto-convert (no FX in this module) -
    # we only flag. The position's home currency is resolved in priority
    # order: an explicit per-position/metadata currency first, then the
    # caller-supplied project currency (BUG-B-013 - neither PositionCreate
    # nor PositionUpdate populate metadata currency, so without the
    # project-currency fallback a EUR rate applied to a USD project was
    # never flagged). ``project_currency`` is NOT persisted into metadata
    # - it is only used for the comparison.
    pos_currency = ""
    for key in ("currency", "project_currency", "position_currency"):
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            pos_currency = val.strip()
            break
    if not pos_currency and isinstance(project_currency, str) and project_currency.strip():
        pos_currency = project_currency.strip()
    if ci_currency and pos_currency and ci_currency.upper() != pos_currency.upper():
        warnings.append(
            f"Cost item rate is in {ci_currency} but this position is in "
            f"{pos_currency} - no FX conversion was applied.",
        )

    if warnings:
        metadata["cost_apply_warnings"] = warnings
        return True
    # No mismatch - drop any stale warning marker from a prior bad link.
    metadata.pop("cost_apply_warnings", None)
    return False


def _content_fingerprint(
    description: str | None,
    unit: str | None,
    quantity: Any,
    unit_rate: Any,
) -> tuple[str, str, str, str]:
    """Normalised (description, unit, qty, rate) key for duplicate detection.

    BUG-B-014 / boq_quality: two positions that describe the same work at
    the same unit, quantity and rate under different ordinals are almost
    always a copy-paste mistake (double-counted scope). Description is
    case-folded and whitespace-collapsed; unit is case-folded; numerics
    are compared at the stored 4 dp precision so "100" and "100.0000"
    collide. This is a *warning* signal only - never a hard block.
    """
    desc = " ".join((description or "").split()).casefold()
    u = (unit or "").strip().casefold()
    q = _quantize_money_str(quantity)
    r = _quantize_money_str(unit_rate)
    return (desc, u, q, r)


_DUPLICATE_WARNING_PREFIX = "Duplicate content: "


def _apply_duplicate_warning(metadata: dict[str, Any], dup_ordinal: str) -> None:
    """Attach a non-blocking boq_quality duplicate warning to metadata.

    Mirrors the ``cost_apply_warnings`` convention so the traffic-light
    dashboard surfaces it. Idempotent - re-applying the same ordinal does
    not stack duplicate strings.
    """
    msg = (
        f"{_DUPLICATE_WARNING_PREFIX}description, unit, quantity and unit "
        f"rate are identical to position '{dup_ordinal}' in this BOQ - "
        f"verify this scope is not double-counted."
    )
    existing = metadata.get("boq_quality_warnings")
    warnings: list[str] = list(existing) if isinstance(existing, list) else []
    # Drop any previous duplicate marker (the matched ordinal may change)
    # before re-adding so we never accumulate stale entries.
    warnings = [w for w in warnings if not str(w).startswith(_DUPLICATE_WARNING_PREFIX)]
    warnings.append(msg)
    metadata["boq_quality_warnings"] = warnings


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

        # Determine the base for calculation.
        # BUG-B-005: ``subtotal`` must base the markup on
        # direct_cost + Σ(preceding markups) - same as ``cumulative``.
        # Treating it as ``direct_cost`` systematically under-states any
        # tax-on-subtotal line (VAT on contractor price incl. overhead &
        # profit), the exact use case the schema offers ``subtotal`` for.
        apply_to = (markup.apply_to or "direct_cost").lower()
        if apply_to in ("cumulative", "subtotal"):
            base = direct_cost + running_sum
        else:
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


# ── Issue #127: BOQ code reuse / linked positions ────────────────────────
#
# A ``reference_code`` is the user-facing reusable code (Sección/Partida/
# Recurso). It is DISTINCT from ``ordinal`` (the line number): ``ordinal``
# stays unique within a BOQ (GAEB X83 RNoPart/ID identity +
# ``boq_quality.no_duplicate_ordinals``) while the SAME ``reference_code``
# may be reused across many positions in the project. Positions sharing one
# master definition all carry the same ``link_group_id`` and have
# ``link_role='instance'``; the definition-owner is ``link_role='master'``.

# Definition fields a master propagates to every linked instance. NEVER
# includes quantity / ordinal / sort_order / link_* - those are per-instance
# (the architecture guide: AI-augmented, human-confirmed; quantities never propagate).
_LINK_DEFINITION_FIELDS: tuple[str, ...] = (
    "description",
    "unit",
    "unit_rate",
    "classification",
    "source",
    "cad_element_ids",
)
# A copy of the master's metadata (resources / assembly sub-structure) is
# propagated too, but quantity-derived / per-instance keys are stripped.
# ``_link_src`` (Issue #132) records the id of the MASTER node each linked
# instance node was cloned from - it is the per-node correspondence key that
# lets a master CHILD edit reach the matching instance children (the group
# id alone is too coarse: every node in a subtree shares it). It is
# per-instance and must never be carried by a master→instance metadata copy.
_LINK_INSTANCE_ONLY_META_KEYS: tuple[str, ...] = (
    "bim_qty_source",
    "pdf_measurement_source",
    "dwg_annotation_source",
    "_link_src",
)
# Fields whose direct edit on an INSTANCE means "diverge from the master"
# → unlink + warn. Quantity / ordinal / sort_order / version / validation
# are explicitly NOT here (a quantity edit must never unlink).
_LINK_UNLINK_TRIGGER_FIELDS: tuple[str, ...] = (
    "description",
    "unit",
    "unit_rate",
    "classification",
    "source",
    "cad_element_ids",
    "metadata_",
)

_AUTO_CODE_PREFIX = "R-"

# ── Issue #133 (full): resource code dedup + master→instance propagation ──
#
# Resources are JSON leaves on ``Position.metadata.resources`` - there is
# no resource row / link_role. The canonical (master) definition for a
# resource ``code`` is the OLDEST position carrying that code (same rule
# ``find_resource_by_code`` uses for the reuse prompt). When that master
# resource's DEFINITION fields change, the change propagates to every
# OTHER position whose resource carries the same code - EXCEPT a target
# resource the user explicitly diverged (``_code_overridden`` marker).
# Quantity is NEVER propagated (per-instance, mirrors #127). This extends
# the existing reuse plumbing - it does not introduce a parallel model.
_RESOURCE_DEFINITION_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "type",
    "unit",
    "unit_rate",
    "currency",
)

# ── Issue #136: multi-level section / partida hierarchy ──────────────────
#
# Historically a BOQ had exactly 3 fixed tiers: Section → Partida → Resource.
# Real estimating practice nests far deeper - the issue reports up to ~8
# tiers ("a veces se utilizan hasta 8 niveles"). We therefore allow
# generous deep nesting of Sections-within-Sections and Partidas-within-
# Partidas, capped by a SINGLE configurable constant so the limit is easy
# to tune and cycles / runaway recursion are still impossible.
#
# ``MAX_NESTING_DEPTH`` is the maximum number of *position* tiers (1-based:
# a top-level row is tier 1). Resources are JSON leaves on a position and
# are NOT counted here. The cap is enforced on BOTH create (add_position /
# bulk_add_positions / create_section) and the parent_id-move path of
# update_position so a deep tree can never be assembled by either route.
MAX_NESTING_DEPTH = 8


def _generate_internal_reference_code() -> str:
    """Generate a stable, collision-resistant internal reusable code.

    Resources/positions created WITHOUT a code still need to be
    referenceable (Issue #127), so we stamp ``R-XXXXXXXX`` derived from a
    fresh uuid4 base32 slice. Project-level uniqueness is verified by the
    caller (it retries on the astronomically unlikely collision).
    """
    import base64

    raw = base64.b32encode(uuid.uuid4().bytes).decode("ascii").rstrip("=")
    return f"{_AUTO_CODE_PREFIX}{raw[:8].upper()}"


def _copy_definition_metadata(master_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-ish copy a master's metadata for a linked instance.

    Carries the reusable sub-structure (resources / assembly / variant
    snapshots / cost_item_id / classification helpers) but strips the
    per-instance link artefacts (BIM/PDF/DWG quantity-source markers)
    which are quantity-bound and must never be shared.
    """
    if not isinstance(master_meta, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in master_meta.items():
        if k in _LINK_INSTANCE_ONLY_META_KEYS:
            continue
        if isinstance(v, dict):
            out[k] = dict(v)
        elif isinstance(v, list):
            out[k] = [dict(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


class BOQService:
    """Business logic for BOQ, Position, and Markup operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.boq_repo = BOQRepository(session)
        self.position_repo = PositionRepository(session)
        self.markup_repo = MarkupRepository(session)
        self.activity_repo = ActivityLogRepository(session)
        self.quantity_link_repo = QuantityLinkRepository(session)

    async def _ensure_not_locked(self, boq_id: uuid.UUID) -> BOQ:
        """Load a BOQ and raise 409 Conflict if it is locked.

        All mutation methods that modify positions or markups on a BOQ
        should call this before proceeding.  Read-only methods do not
        need the guard.

        Returns:
            The loaded BOQ (so callers can reuse it instead of fetching twice).

        Raises:
            HTTPException 404: BOQ not found.
            HTTPException 409: BOQ is locked and cannot be modified.
        """
        boq = await self.get_boq(boq_id)
        if boq.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="BOQ is locked and cannot be modified. Create a revision to make changes.",
            )
        return boq

    async def _validate_parent_id(
        self,
        *,
        boq_id: uuid.UUID,
        position_id: uuid.UUID | None,
        new_parent_id: uuid.UUID | None,
    ) -> None:
        """Validate a candidate ``parent_id`` for a position to prevent cycles.

        Guards three classes of corruption that would crash hierarchical
        traversal (total recompute, PDF/Excel/GAEB exports):

        1. **Self-cycle** - ``parent_id == position_id``.
        2. **Descendant cycle** - ``parent_id`` is a direct or transitive
           descendant of ``position_id``. Walks the descendant chain by
           repeatedly fetching children until the candidate is found or the
           tree is exhausted. A visited-set guard prevents an infinite loop
           on already-corrupt data; if the guard ever trips we log a warning
           - under normal operation it never should.
        3. **Cross-BOQ parent** - ``parent_id`` belongs to a different BOQ.

        Args:
            boq_id: BOQ that the (current or candidate) position lives in.
            position_id: ID of the position being updated, or ``None`` for
                creates where the row does not exist yet.
            new_parent_id: Candidate parent UUID, or ``None`` for a top-level
                position. ``None`` is always valid and short-circuits.

        Raises:
            HTTPException 400: Any of the three invariants is violated.
        """
        if new_parent_id is None:
            return

        # 1. Self-cycle. Cheap pre-check before any DB round-trip.
        # BUG-CYCLE02: validation errors return 422 (FastAPI convention),
        # not 400. Bogus parent_id used to surface as a generic 400 or
        # leak a 500 from FK violation; now consistent across all
        # parent-validation failures.
        if position_id is not None and new_parent_id == position_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Position cannot be its own parent (self-referencing parent_id).",
            )

        # 3. Cross-BOQ parent - validated up front so we don't follow
        #    descendant chains across BOQ boundaries.
        parent = await self.position_repo.get_by_id(new_parent_id)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Parent position {new_parent_id} does not exist.",
            )
        if parent.boq_id != boq_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Parent position belongs to a different BOQ ({parent.boq_id}); cross-BOQ parents are not allowed."
                ),
            )

        # 2. Descendant cycle. Only meaningful for updates (position_id
        #    is not None). For creates the row has no descendants yet.
        if position_id is None:
            return

        visited: set[uuid.UUID] = set()
        frontier: list[uuid.UUID] = [position_id]
        while frontier:
            current = frontier.pop()
            if current in visited:
                logger.warning(
                    "Cycle guard: revisited position %s while walking descendants of %s - data may already be corrupt.",
                    current,
                    position_id,
                )
                continue
            visited.add(current)

            children = await self.position_repo.list_children(current)
            for child in children:
                if child.id == new_parent_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Cannot set parent_id to a descendant of this position "
                            "- would create a cycle in the BOQ hierarchy."
                        ),
                    )
                frontier.append(child.id)

    async def _parent_chain_depth(self, parent_id: uuid.UUID | None) -> int:
        """Return the 1-based tier of the position identified by ``parent_id``.

        Issue #136. Walks ``parent_id`` → root counting hops, INCLUDING the
        node itself: a top-level position returns 1, its direct child's
        parent returns 1 (so the child is tier 2), and so on. ``None``
        returns 0 (a row with no parent is tier 1, computed by the caller).
        A ``visited`` guard makes a pre-existing corrupt cycle terminate
        instead of looping forever (defence-in-depth - ``_validate_parent_id``
        already blocks cycle *creation*).
        """
        if parent_id is None:
            return 0
        depth = 0
        visited: set[uuid.UUID] = set()
        current: uuid.UUID | None = parent_id
        while current is not None:
            if current in visited:
                logger.warning(
                    "Depth guard: cycle detected walking ancestors of %s",
                    parent_id,
                )
                break
            visited.add(current)
            node = await self.position_repo.get_by_id(current)
            if node is None:
                break
            depth += 1
            current = getattr(node, "parent_id", None)
            if depth > MAX_NESTING_DEPTH + 4:
                # Hard stop well past the cap - a chain this long is
                # already over-deep; the caller's cap check will reject it.
                break
        return depth

    async def _validate_nesting_depth(
        self,
        *,
        new_parent_id: uuid.UUID | None,
        moving_subtree_root: uuid.UUID | None = None,
    ) -> None:
        """Reject a placement that would exceed ``MAX_NESTING_DEPTH`` tiers.

        Issue #136. ``new_parent_id`` is the candidate parent.
        ``_parent_chain_depth`` returns the parent's OWN 1-based tier
        (it counts the parent itself plus all of its ancestors), so the
        created / moved node lands at tier ``parent_tier + 1``. When
        ``moving_subtree_root`` is given (the update / move path) the
        DEEPEST descendant of that subtree must also stay within the cap,
        so the whole branch is depth-checked, not just its root.

        Raises:
            HTTPException 422: the placement would create tier
                ``> MAX_NESTING_DEPTH``.
        """
        if new_parent_id is None:
            base_tier = 1  # top-level row
        else:
            parent_tier = await self._parent_chain_depth(new_parent_id)
            base_tier = parent_tier + 1

        # On a move, account for the moved subtree's own internal depth so
        # a deep branch can't be re-parented just below the cap and then
        # silently overflow at its leaves.
        extra = 0
        if moving_subtree_root is not None:
            extra = await self._subtree_height(moving_subtree_root)

        deepest_tier = base_tier + extra
        if deepest_tier > MAX_NESTING_DEPTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Maximum nesting depth of {MAX_NESTING_DEPTH} tiers "
                    f"reached - cannot place this item {deepest_tier} "
                    f"levels deep. Flatten the structure or use fewer "
                    f"sub-levels."
                ),
            )

    async def _subtree_height(self, root_id: uuid.UUID) -> int:
        """Return the height of the subtree rooted at ``root_id``.

        0 when ``root_id`` is a leaf, 1 when it has children but no
        grandchildren, etc. Breadth-first with a ``visited`` guard so a
        corrupt cycle terminates. Used by the move path so re-parenting a
        deep branch is rejected if ANY leaf would exceed the cap.

        v4.2.2 Round 2 Wave C: was O(nodes_in_subtree) DB roundtrips via
        ``list_children`` per node. Now one ``list_all_for_boq`` plus an
        in-memory parent→children index - every walk is single-query.
        The traversal cap (``MAX_NESTING_DEPTH + 4``) is preserved exactly
        so semantics are unchanged for a corrupt/over-deep branch.
        """
        # Resolve the BOQ owning ``root_id``. A missing root is treated as
        # a height of 0 (matches the prior behaviour where ``list_children``
        # on an unknown id returned an empty list).
        root_node = await self.position_repo.get_by_id(root_id)
        if root_node is None:
            return 0
        all_positions = await self.position_repo.list_all_for_boq(root_node.boq_id)
        # Build parent→children index honouring the same sort_order the
        # original ``list_children`` query used.
        children_by_parent: dict[uuid.UUID, list[Position]] = {}
        for pos in all_positions:
            pid = pos.parent_id
            if pid is None:
                continue
            children_by_parent.setdefault(pid, []).append(pos)
        # ``list_all_for_boq`` already orders by ``sort_order, ordinal`` so
        # each bucket inherits the same ordering ``list_children`` returned.

        height = 0
        visited: set[uuid.UUID] = set()
        frontier: list[tuple[uuid.UUID, int]] = [(root_id, 0)]
        while frontier:
            node_id, level = frontier.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            if level > height:
                height = level
            if level > MAX_NESTING_DEPTH + 4:
                break
            for child in children_by_parent.get(node_id, ()):
                frontier.append((child.id, level + 1))
        return height

    # ── Issue #127: linked-position helpers ───────────────────────────────

    async def _resolve_create_reference_code(
        self,
        project_id: uuid.UUID | None,
        supplied: str | None,
    ) -> str:
        """Return the reference_code to stamp on a new position.

        * A non-empty supplied code is used verbatim (collision with an
          existing code is the *intended* reuse trigger - handled by the
          caller, not rejected here).
        * Empty / None → generate a stable internal ``R-XXXXXXXX`` code
          that is unique within the project so the position is always
          referenceable.
        """
        code = (supplied or "").strip()
        if code:
            return code[:64]
        # Auto-generate; verify project-uniqueness with a tiny retry budget.
        for _ in range(8):
            candidate = _generate_internal_reference_code()
            if project_id is None:
                return candidate
            if not await self.position_repo.reference_code_exists_in_project(project_id, candidate):
                return candidate
        # Astronomically unlikely fallthrough - append more entropy.
        return f"{_generate_internal_reference_code()}{uuid.uuid4().hex[:4].upper()}"[:64]

    async def _next_free_ordinal(self, boq_id: uuid.UUID, base: str) -> str:
        """Derive a fresh, BOQ-unique ordinal from ``base``.

        Linked instances / duplicates must NOT collide on ``ordinal``
        (GAEB X83 RNoPart/ID + ``boq_quality.no_duplicate_ordinals``
        invariant). Tries ``base.1``, ``base.2`` … then falls back to a
        uuid-suffixed form so this can never raise or loop forever.
        """
        for i in range(1, 1000):
            candidate = f"{base}.{i}"
            if not await self.position_repo.ordinal_exists(boq_id, candidate):
                return candidate
        fallback = f"{base}.{uuid.uuid4().hex[:6]}"
        return fallback[:50]

    async def _clone_subtree(
        self,
        source: Position,
        *,
        boq_id: uuid.UUID,
        new_parent_id: uuid.UUID | None,
        ordinal: str,
        quantity: str | None,
        link_group_id: uuid.UUID | None,
        link_role: str | None,
        reference_code: str | None,
    ) -> Position:
        """Deep-copy ``source`` and its descendant positions.

        Shared by ``duplicate_position`` (one-time clone) and the
        reuse-by-code linked-instance path. Each cloned node gets a
        BOQ-unique ordinal so the ordinal-uniqueness invariant always
        holds; the root takes the caller-supplied ``ordinal`` /
        ``quantity`` / link fields, descendants keep the source's own
        quantities and inherit the same link_group_id but
        ``link_role='instance'`` (children of an instance are themselves
        instances of their source children - quantities are still
        per-instance and never back-propagate).

        Returns the newly created ROOT position.

        The caller MUST pass a live (non-expired) ``source`` - the async
        engine cannot lazy-refresh expired ORM attributes on access
        (``MissingGreenlet``). The reuse path re-fetches the master after
        promoting it; ``duplicate_position`` fetches the source fresh.
        """
        max_order = await self.position_repo.get_max_sort_order(boq_id)

        # Issue #132: when this clone joins a link group, stamp the master
        # node it mirrors so a later master-CHILD edit can find exactly the
        # matching instance children (group id alone can't - every node in
        # the subtree shares it). Standalone copies (no group) get no marker.
        _root_meta = _copy_definition_metadata(source.metadata_)
        if link_group_id is not None:
            _root_meta["_link_src"] = str(source.id)

        root = Position(
            boq_id=boq_id,
            parent_id=new_parent_id,
            ordinal=ordinal,
            description=source.description,
            unit=source.unit,
            quantity=(_quantize_money_str(quantity) if quantity is not None else source.quantity),
            unit_rate=source.unit_rate,
            total=_compute_total(
                quantity if quantity is not None else source.quantity,
                source.unit_rate,
            ),
            classification=dict(source.classification) if source.classification else {},
            source=source.source,
            confidence=source.confidence,
            cad_element_ids=list(source.cad_element_ids) if source.cad_element_ids else [],
            validation_status="pending",
            metadata_=_root_meta,
            sort_order=max_order + 1,
            reference_code=reference_code,
            link_group_id=link_group_id,
            link_role=link_role,
        )
        root = await self.position_repo.create(root)

        # Recursively clone descendants (breadth-first, parent before child
        # so FK is always satisfiable).
        queue: list[tuple[Position, uuid.UUID]] = [(source, root.id)]
        while queue:
            src_node, new_parent = queue.pop()
            children = await self.position_repo.list_children(src_node.id)
            for child in children:
                max_order += 1
                child_ordinal = await self._next_free_ordinal(boq_id, child.ordinal)
                # Issue #132: each cloned child records ITS OWN master child
                # as the correspondence key (not the root's) so master-child
                # edits fan out to the matching instance children only.
                _child_meta = _copy_definition_metadata(child.metadata_)
                if link_group_id is not None:
                    _child_meta["_link_src"] = str(child.id)
                cloned_child = Position(
                    boq_id=boq_id,
                    parent_id=new_parent,
                    ordinal=child_ordinal,
                    description=child.description,
                    unit=child.unit,
                    quantity=child.quantity,
                    unit_rate=child.unit_rate,
                    total=child.total,
                    classification=(dict(child.classification) if child.classification else {}),
                    source=child.source,
                    confidence=child.confidence,
                    cad_element_ids=(list(child.cad_element_ids) if child.cad_element_ids else []),
                    validation_status="pending",
                    metadata_=_child_meta,
                    sort_order=max_order,
                    # Children inherit the group when the root is linked so
                    # the whole sub-structure stays addressable; they keep
                    # their own (auto / source) reference code.
                    reference_code=(
                        child.reference_code
                        if child.reference_code
                        else await self._resolve_create_reference_code(
                            await self.position_repo.project_id_for_boq(boq_id),
                            None,
                        )
                    ),
                    link_group_id=link_group_id,
                    link_role=("instance" if link_group_id is not None else None),
                )
                cloned_child = await self.position_repo.create(cloned_child)
                queue.append((child, cloned_child.id))

        return root

    async def _recompute_position_total(self, position: Position) -> None:
        """Recompute one position's ``total`` from its stored qty × rate."""
        new_total = _compute_total(position.quantity, position.unit_rate)
        if new_total != position.total:
            await self.position_repo.update_fields(position.id, total=new_total)

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

        result = await self.session.execute(select(Project.id).where(Project.id == data.project_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail=translate("errors.project_not_found", locale=get_locale()))

        default_display_columns = ["ordinal", "description", "unit", "quantity", "unit_rate", "total"]
        boq = BOQ(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            status="draft",
            estimate_type=data.estimate_type,
            base_date=data.base_date,
            metadata_={"display_columns": default_display_columns},
        )
        boq = await self.boq_repo.create(boq)

        # BUG-B-009 (user decision: opt-out): a freshly created BOQ now
        # starts with ZERO markups. Auto-stamping regional BGK/AGK/Wagnis/
        # Gewinn/MwSt (or any other) defaults silently inflated every
        # estimate's grand total before the estimator had reviewed a single
        # line - a violation of the architecture guide principle #7 (AI-augmented,
        # human-confirmed) and the global-copy policy. The explicit path is
        # ``POST /boqs/{boq_id}/markups/apply-defaults`` which still calls
        # ``apply_default_markups`` on demand.

        await _safe_publish(
            "boq.boq.created",
            {"boq_id": str(boq.id), "project_id": str(data.project_id)},
            source_module="oe_boq",
        )

        await _safe_audit(
            self.session,
            action="create",
            entity_type="boq",
            entity_id=str(boq.id),
            details={"name": boq.name, "project_id": str(data.project_id)},
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

    async def _resolve_project_currency(self, boq_id: uuid.UUID) -> str:
        """Resolve the project currency for a BOQ (BUG-B-013).

        ``_stamp_cost_item_compat`` can only flag a EUR-rate-into-USD
        application when it knows the position's home currency. Neither
        ``PositionCreate`` nor ``PositionUpdate`` carry one, so without
        resolving it here a foreign-currency cost-database rate was
        applied silently. We join BOQ → Project to obtain the
        authoritative currency. Best-effort: any failure returns an empty
        string (no currency assumption - never stamp a wrong "EUR").
        """
        try:
            from app.modules.projects.models import Project

            row = (
                await self.session.execute(
                    select(Project.currency).join(BOQ, BOQ.project_id == Project.id).where(BOQ.id == boq_id),
                )
            ).first()
        except Exception:  # noqa: BLE001 - never break a write on this lookup
            logger.debug("Project currency lookup failed for BOQ %s", boq_id, exc_info=True)
            return ""
        if not row or not row[0]:
            return ""
        return str(row[0]).strip()[:3].upper()

    async def _resolve_project_fx(
        self,
        boq_id: uuid.UUID,
    ) -> tuple[str, dict[str, str]]:
        """Resolve ``(base_currency, {code: rate})`` for a BOQ's project.

        Issue #111 - the structured/export rollup needs the project's FX
        table, not just its base currency, to convert foreign-currency
        position totals before summing. Best-effort: any failure returns
        ``("", {})`` so the export never breaks and degrades to raw sums
        (the pre-#111 behaviour) rather than a 500.
        """
        try:
            from app.modules.projects.models import Project

            row = (
                await self.session.execute(
                    select(Project.currency, Project.fx_rates)
                    .join(BOQ, BOQ.project_id == Project.id)
                    .where(BOQ.id == boq_id),
                )
            ).first()
        except Exception:  # noqa: BLE001 - never break an export on this lookup
            logger.debug("Project FX lookup failed for BOQ %s", boq_id, exc_info=True)
            return "", {}
        if not row:
            return "", {}
        base = str(row[0]).strip()[:3].upper() if row[0] else ""
        raw = row[1] if isinstance(row[1], list) else []
        fx_map: dict[str, str] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("code") or "").strip().upper()
            rate = str(entry.get("rate") or "").strip()
            if code and rate:
                fx_map[code] = rate
        return base, fx_map

    async def _resolve_project_fx_by_project(
        self,
        project_id: uuid.UUID,
    ) -> tuple[str, dict[str, str]]:
        """Resolve ``(base_currency, {code: rate})`` keyed by ``project_id``.

        Sibling of :meth:`_resolve_project_fx` for the project-scoped rollups
        (Project Intelligence widgets) that already hold a project id rather
        than a BOQ id, so they can convert foreign-currency position totals to
        the project BASE before summing. Best-effort: any failure returns
        ``("", {})`` so the widget degrades to raw sums rather than a 500.
        """
        try:
            from app.modules.projects.models import Project

            row = (
                await self.session.execute(
                    select(Project.currency, Project.fx_rates).where(Project.id == project_id),
                )
            ).first()
        except Exception:  # noqa: BLE001 - never break a widget on this lookup
            logger.debug("Project FX lookup failed for project %s", project_id, exc_info=True)
            return "", {}
        if not row:
            return "", {}
        base = str(row[0]).strip()[:3].upper() if row[0] else ""
        raw = row[1] if isinstance(row[1], list) else []
        fx_map: dict[str, str] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("code") or "").strip().upper()
            rate = str(entry.get("rate") or "").strip()
            if code and rate:
                fx_map[code] = rate
        return base, fx_map

    async def _find_content_duplicate(
        self,
        boq_id: uuid.UUID,
        *,
        description: str | None,
        unit: str | None,
        quantity: Any,
        unit_rate: Any,
        exclude_id: uuid.UUID | None = None,
    ) -> str | None:
        """Return the ordinal of an existing position with identical content.

        BUG-B-014: ``boq_quality`` advertises duplicate detection but only
        ordinal collisions were checked. Two positions with the same
        description+unit+quantity+unit_rate under different ordinals are a
        likely double-count. We scan all positions in the BOQ (rollups
        already use ``list_all_for_boq`` so this is consistent) and return
        the first colliding ordinal, or ``None``. Never raises - duplicate
        detection is advisory and must not break a write.
        """
        # PERF: v4.2.2 Round 2 Wave C audit - already single-query
        # (one ``list_all_for_boq`` then in-memory fingerprint scan;
        # ``_content_fingerprint`` reads scalar columns only). Replacing
        # the python scan with a DB-side hash filter would need a
        # ``content_hash`` column + backfill - deferred (model refactor).
        try:
            target = _content_fingerprint(description, unit, quantity, unit_rate)
            for pos in await self.position_repo.list_all_for_boq(boq_id):
                if exclude_id is not None and pos.id == exclude_id:
                    continue
                if (
                    _content_fingerprint(
                        pos.description,
                        pos.unit,
                        pos.quantity,
                        pos.unit_rate,
                    )
                    == target
                ):
                    return pos.ordinal
        except Exception:  # noqa: BLE001 - advisory only, never break the write
            logger.debug("Duplicate-content scan failed for BOQ %s", boq_id, exc_info=True)
        return None

    async def list_boqs_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQ], int]:
        """List BOQs for a given project with pagination."""
        return await self.boq_repo.list_for_project(project_id, offset=offset, limit=limit)

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
            HTTPException 409 if the BOQ is locked.
            HTTPException 422 if ``cost_item_id`` was supplied but does not
                reference an active CostItem (Issue #79).
        """
        await self._ensure_not_locked(data.boq_id)

        # ── Issue #127: reuse-by-code (linked instance) ──────────────────
        # If a reusable code was supplied AND a master/owner of that code
        # already exists ANYWHERE in the project, do NOT dead-end with
        # "código ya existe": create a REUSED instance carrying the
        # master's definition + sub-structure. The instance gets its OWN
        # auto-assigned BOQ-unique ordinal and its own per-instance
        # quantity, so the ordinal-uniqueness invariant (GAEB X83 +
        # boq_quality.no_duplicate_ordinals) is never violated.
        supplied_code = (getattr(data, "reference_code", None) or "").strip()
        link_mode = getattr(data, "link_mode", None)
        project_id = await self.position_repo.project_id_for_boq(data.boq_id)
        if supplied_code and link_mode != "standalone":
            master = (
                await self.position_repo.find_master_by_reference_code(project_id, supplied_code)
                if project_id is not None
                else None
            )
            if master is not None and str(master.boq_id) and master.id is not None:
                return await self._create_reused_position(
                    data=data,
                    master=master,
                    project_id=project_id,
                    reference_code=supplied_code,
                    as_copy=(link_mode == "copy"),
                )

        # Check ordinal uniqueness within the BOQ
        if await self.position_repo.ordinal_exists(data.boq_id, data.ordinal):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Position with ordinal '{data.ordinal}' already exists in this BOQ",
            )

        # Cycle / cross-BOQ guard. The (rare) client-supplied id case where
        # parent_id == id would otherwise create an immediate self-loop.
        await self._validate_parent_id(
            boq_id=data.boq_id,
            position_id=None,
            new_parent_id=data.parent_id,
        )
        # Issue #136: enforce the configurable deep-nesting cap.
        await self._validate_nesting_depth(new_parent_id=data.parent_id)

        # Issue #79: validate and stamp ``metadata.cost_item_id`` so a position
        # created with ``source='cwicr'`` (or any source) can carry a typed
        # link back to the cost database.  No DB migration - we piggyback
        # on the existing JSON metadata column.
        merged_metadata: dict[str, Any] = dict(data.metadata) if isinstance(data.metadata, dict) else {}
        if data.cost_item_id is not None:
            try:
                cost_repo = CostItemRepository(self.session)
                cost_item = await cost_repo.get_by_id(data.cost_item_id)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 - surface any DB failure as 422
                logger.exception("add_position cost_item lookup failed for %s", data.cost_item_id)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(f"cost_item_id does not reference an active CostItem ({type(exc).__name__})"),
                ) from exc
            if cost_item is None or not getattr(cost_item, "is_active", False):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="cost_item_id does not reference an active CostItem",
                )
            merged_metadata["cost_item_id"] = str(data.cost_item_id)
            # BUG-B-013: stamp cost-item unit/currency provenance and flag
            # a non-blocking warning on unit / currency mismatch.
            _cost_compat_warned = _stamp_cost_item_compat(
                merged_metadata,
                cost_item=cost_item,
                position_unit=data.unit,
                project_currency=await self._resolve_project_currency(data.boq_id),
            )
        else:
            _cost_compat_warned = False

        # Stamp the CWICR variant snapshot so the position's unit_rate is
        # immutable from the cost-database side: a later re-import or rate
        # update on the source CostItem cannot rewrite it silently.  Only
        # active when the caller actually attached a ``variant`` or
        # ``variant_default`` marker (no-op for plain manual positions).
        currency_hint = merged_metadata.get("currency") if isinstance(merged_metadata, dict) else None
        _stamp_variant_snapshot(
            merged_metadata,
            unit_rate=data.unit_rate,
            currency=currency_hint if isinstance(currency_hint, str) else None,
        )
        _stamp_resource_variant_snapshots(
            merged_metadata,
            position_currency=currency_hint if isinstance(currency_hint, str) else None,
        )
        # Canonical M/L/E rollup: keep ``resource_breakdown`` in sync with the
        # resources list so the BOQ grid split columns / pill never go stale.
        _stamp_resource_breakdown(merged_metadata)

        total = _compute_total(data.quantity, data.unit_rate)
        max_order = await self.position_repo.get_max_sort_order(data.boq_id)

        # ── Issue #139: insert directly below the selected row ────────────
        # When the client passes ``after_position_id`` (the row the user had
        # selected when they hit "Add position"), slot the new partida
        # immediately after that sibling instead of at the end of the
        # section: open a one-slot gap by bumping every later position down
        # by one, then take ``target.sort_order + 1``. The target must live
        # in the SAME BOQ - a stale / cross-BOQ id silently falls back to
        # the append-at-end behaviour rather than scrambling order.
        new_sort_order = max_order + 1
        if data.after_position_id is not None:
            anchor = await self.position_repo.get_by_id(data.after_position_id)
            if anchor is not None and anchor.boq_id == data.boq_id:
                await self.position_repo.shift_sort_order_after(data.boq_id, int(anchor.sort_order))
                new_sort_order = int(anchor.sort_order) + 1
        elif data.parent_id is not None:
            # ── Issue #149: keep the partida INSIDE the clicked section ──────
            # A position added via a specific section's "Add position" button
            # (explicit ``parent_id``, no ``after_position_id``) must land
            # inside *that* section - grouped with the section's own line
            # items and ahead of any sub-sections. Without this it inherits
            # the global-max ``sort_order`` and the grid (which walks
            # ``parent_id`` then orders siblings by ``sort_order``) renders it
            # after the last sub-section's entire subtree, so it looks as if
            # it were filed under that sub-section. We slot it right after the
            # section's existing direct line items but strictly before its
            # first sub-section, which is unambiguous regardless of any
            # legacy interleaving created before this fix.
            parent_pos = await self.position_repo.get_by_id(data.parent_id)
            if parent_pos is not None and parent_pos.boq_id == data.boq_id:
                direct_children = await self.position_repo.list_children(data.parent_id)
                leaf_so = [int(c.sort_order) for c in direct_children if not _is_section(c)]
                sub_so = [int(c.sort_order) for c in direct_children if _is_section(c)]
                anchor_so = max(leaf_so) if leaf_so else int(parent_pos.sort_order)
                if sub_so:
                    anchor_so = min(anchor_so, min(sub_so) - 1)
                anchor_so = max(anchor_so, int(parent_pos.sort_order))
                await self.position_repo.shift_sort_order_after(data.boq_id, anchor_so)
                new_sort_order = anchor_so + 1

        # BUG-B-014: non-blocking boq_quality duplicate-content check.
        _dup_ordinal = await self._find_content_duplicate(
            data.boq_id,
            description=data.description,
            unit=data.unit,
            quantity=data.quantity,
            unit_rate=data.unit_rate,
        )
        if _dup_ordinal is not None:
            _apply_duplicate_warning(merged_metadata, _dup_ordinal)

        # Issue #127: every position carries a reusable ``reference_code``.
        # Supplied code used verbatim (no collision here - either none, or
        # link_mode='standalone' which intentionally re-uses the literal
        # code without linking); otherwise stamp a stable internal code so
        # the position is always referenceable.
        resolved_reference_code = await self._resolve_create_reference_code(project_id, supplied_code or None)

        position = Position(
            boq_id=data.boq_id,
            parent_id=data.parent_id,
            ordinal=data.ordinal,
            description=data.description,
            unit=data.unit,
            # BUG-MATH01: quantise inputs to 4 dp at the storage boundary.
            quantity=_quantize_money_str(data.quantity),
            unit_rate=_quantize_money_str(data.unit_rate),
            total=total,
            classification=data.classification,
            source=data.source,
            confidence=str(data.confidence) if data.confidence is not None else None,
            cad_element_ids=data.cad_element_ids,
            metadata_=merged_metadata,
            # BUG-B-013 (cost-item unit/currency) + BUG-B-014 (duplicate
            # content) both surface on the validation traffic-light.
            validation_status=("warnings" if (_cost_compat_warned or _dup_ordinal is not None) else "pending"),
            sort_order=new_sort_order,
            reference_code=resolved_reference_code,
            # Standalone: no link group yet. The first reuse promotes this
            # row to 'master' and assigns a group (see _create_reused_position).
            link_group_id=None,
            link_role=None,
        )
        position = await self.position_repo.create(position)

        # Record a usage-ledger entry so the Cost Database "used in N
        # estimates" indicator (and the certainty badge frequency) reflect
        # this add immediately. Append-only; gated on a real cost_item link
        # and a resolvable project. Wrapped so a ledger failure never blocks
        # the position create - the indicator is informational, not a gate.
        if data.cost_item_id is not None and project_id is not None:
            try:
                from app.modules.costs.intelligence import CostUsageRecorder

                await CostUsageRecorder(self.session).record(
                    data.cost_item_id,
                    project_id=project_id,
                    unit_rate_at_use=data.unit_rate,
                    context="boq",
                )
            except Exception:  # noqa: BLE001 - ledger is best-effort
                logger.warning(
                    "Failed to record cost-item usage for %s on BOQ %s",
                    data.cost_item_id,
                    data.boq_id,
                    exc_info=True,
                )

        await _safe_publish(
            "boq.position.created",
            {
                "position_id": str(position.id),
                "boq_id": str(data.boq_id),
                "ordinal": data.ordinal,
            },
            source_module="oe_boq",
        )

        await _safe_audit(
            self.session,
            action="create",
            entity_type="position",
            entity_id=str(position.id),
            details={
                "boq_id": str(data.boq_id),
                "ordinal": data.ordinal,
                "description": (data.description or "")[:100],
            },
        )

        logger.info("Position added: %s to BOQ %s", data.ordinal, data.boq_id)
        return position

    async def _create_reused_position(
        self,
        *,
        data: PositionCreate,
        master: Position,
        project_id: uuid.UUID | None,
        reference_code: str,
        as_copy: bool,
    ) -> Position:
        """Create a reused position from an existing code's master.

        Issue #127. Deep-copies the master's definition + child subtree
        (via the shared ``_clone_subtree`` helper), assigns a fresh
        BOQ-unique ordinal (NEVER reuses the master's - the
        ordinal-uniqueness invariant holds) and the client-supplied
        quantity (default 0). When ``as_copy`` is False (the default 'link'
        path) the new position joins the master's link group as an
        ``instance``; the master is promoted to ``master`` and assigned a
        group id if it was still standalone. ``as_copy=True`` is a one-time
        clone with link fields left NULL (no future propagation).
        """
        target_boq = data.boq_id

        # ``PositionRepository.update_fields`` ends with
        # ``session.expire_all()`` - that expires EVERY ORM instance in the
        # unit of work, including ``master``. The async engine cannot
        # lazy-refresh on attribute access (``MissingGreenlet``), so read
        # everything we need from ``master`` NOW, before the first promote,
        # and re-fetch a live copy afterwards for the deep-copy.
        master_id = master.id
        master_ordinal = master.ordinal
        master_link_group_id = master.link_group_id
        master_link_role = master.link_role

        # Resolve / create the link group (only for the linked path).
        link_group_id: uuid.UUID | None = None
        link_role: str | None = None
        if not as_copy:
            if master_link_group_id is not None:
                link_group_id = master_link_group_id
                # Master may currently be a bare 'master' (group existed) -
                # nothing to do. If it lost its role, restore it.
                if master_link_role != "master":
                    await self.position_repo.update_fields(master_id, link_role="master")
            else:
                # Promote the standalone owner to master + open a group.
                link_group_id = uuid.uuid4()
                await self.position_repo.update_fields(
                    master_id,
                    link_group_id=link_group_id,
                    link_role="master",
                    # Ensure the master carries the shared code (it should
                    # already, but a standalone owner found by code is
                    # authoritative).
                    reference_code=reference_code,
                )
            link_role = "instance"

        # Fresh unique ordinal derived from the client-supplied ordinal
        # (fallback to the master's). NEVER the master's own ordinal.
        base_ordinal = (data.ordinal or master_ordinal or "REUSE").strip() or "REUSE"
        if await self.position_repo.ordinal_exists(target_boq, base_ordinal):
            new_ordinal = await self._next_free_ordinal(target_boq, base_ordinal)
        else:
            new_ordinal = base_ordinal

        # Per-instance quantity (client-supplied, default 0). Quantities
        # are NEVER inherited from the master.
        qty = data.quantity if data.quantity is not None else 0

        # Re-fetch a LIVE master (the promote above expired it) so the
        # deep-copy reads real definition values, not expired attributes.
        live_master = await self.position_repo.get_by_id(master_id)
        new_position = await self._clone_subtree(
            live_master if live_master is not None else master,
            boq_id=target_boq,
            new_parent_id=data.parent_id,
            ordinal=new_ordinal,
            quantity=str(qty),
            link_group_id=link_group_id,
            link_role=link_role,
            reference_code=reference_code,
        )

        await _safe_publish(
            "boq.position.created",
            {
                "position_id": str(new_position.id),
                "boq_id": str(target_boq),
                "ordinal": new_ordinal,
                "reference_code": reference_code,
                "reused_from": str(master_id),
                "linked": not as_copy,
            },
            source_module="oe_boq",
        )
        await _safe_audit(
            self.session,
            action="reuse_code" if not as_copy else "copy_code",
            entity_type="position",
            entity_id=str(new_position.id),
            details={
                "boq_id": str(target_boq),
                "ordinal": new_ordinal,
                "reference_code": reference_code,
                "master_id": str(master_id),
                "linked": not as_copy,
            },
        )
        logger.info(
            "Position %s code '%s' from master %s → %s (BOQ %s)",
            "linked" if not as_copy else "copied",
            reference_code,
            master_id,
            new_position.id,
            target_boq,
        )
        return new_position

    async def bulk_add_positions(
        self,
        boq_id: uuid.UUID,
        items: list[PositionCreate],
    ) -> list[Position]:
        """Add many positions to a BOQ in a single flush (Probe-A perf).

        This is the high-throughput path used by Takeoff, Excel-import,
        and AI-Smart-Import. Compared to calling ``add_position`` in a
        loop:

        * one ``get_max_sort_order`` query (was N)
        * one ordinal-uniqueness DB check (was N)
        * one ``session.add_all`` + flush (was N flushes)
        * no per-row event publish - a single ``boq.positions.bulk_created``
          fires at the end with the count
        * audit log writes a single ``bulk_create`` entry; per-row audit
          would dominate insert time at 100+ rows

        Validation parity with ``add_position``:

        * BOQ lock check fires once
        * Ordinals must be unique inside the supplied batch AND against
          existing rows
        * cost_item_id linkage validated per row (one CostItem lookup
          each - could be batched further but rarely > 5/100 in practice)
        * Variant snapshots stamped per row

        Returns the inserted ``Position`` objects in input order.
        """
        if not items:
            return []
        await self._ensure_not_locked(boq_id)

        # Single DB hit for the next sort_order base.
        max_order = await self.position_repo.get_max_sort_order(boq_id)

        # Dedupe ordinals inside the batch first; reject the whole
        # batch on collision so the caller doesn't get partial inserts.
        seen_ordinals: set[str] = set()
        for it in items:
            if it.ordinal in seen_ordinals:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Duplicate ordinal '{it.ordinal}' inside the bulk "
                        f"payload - every position must have a unique ordinal."
                    ),
                )
            seen_ordinals.add(it.ordinal)

        # One DB check for collisions against existing rows.
        existing_stmt = select(Position.ordinal).where(
            Position.boq_id == boq_id,
            Position.ordinal.in_(seen_ordinals),
        )
        existing_ordinals = {row[0] for row in (await self.session.execute(existing_stmt)).all()}
        if existing_ordinals:
            sample = next(iter(existing_ordinals))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Position with ordinal '{sample}' already exists "
                    f"in this BOQ ({len(existing_ordinals)} collision"
                    f"{'s' if len(existing_ordinals) != 1 else ''} total)."
                ),
            )

        cost_repo: CostItemRepository | None = None
        new_positions: list[Position] = []
        # BUG-B-013: resolve the project currency once for the whole batch
        # so a foreign-currency cost-database rate is flagged on every line.
        _bulk_project_currency = await self._resolve_project_currency(boq_id)
        for offset, data in enumerate(items, start=1):
            await self._validate_parent_id(
                boq_id=boq_id,
                position_id=None,
                new_parent_id=data.parent_id,
            )
            # Issue #136: deep-nesting cap also guards the bulk path.
            await self._validate_nesting_depth(new_parent_id=data.parent_id)

            merged_metadata: dict[str, Any] = dict(data.metadata) if isinstance(data.metadata, dict) else {}
            if data.cost_item_id is not None:
                if cost_repo is None:
                    cost_repo = CostItemRepository(self.session)
                cost_item = await cost_repo.get_by_id(data.cost_item_id)
                if cost_item is None or not getattr(cost_item, "is_active", False):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(f"cost_item_id {data.cost_item_id} does not reference an active CostItem"),
                    )
                merged_metadata["cost_item_id"] = str(data.cost_item_id)
                _bulk_cost_warned = _stamp_cost_item_compat(
                    merged_metadata,
                    cost_item=cost_item,
                    position_unit=data.unit,
                    project_currency=_bulk_project_currency,
                )
            else:
                _bulk_cost_warned = False

            currency_hint = merged_metadata.get("currency") if isinstance(merged_metadata, dict) else None
            _stamp_variant_snapshot(
                merged_metadata,
                unit_rate=data.unit_rate,
                currency=currency_hint if isinstance(currency_hint, str) else None,
            )
            _stamp_resource_variant_snapshots(
                merged_metadata,
                position_currency=currency_hint if isinstance(currency_hint, str) else None,
            )

            new_positions.append(
                Position(
                    boq_id=boq_id,
                    parent_id=data.parent_id,
                    ordinal=data.ordinal,
                    description=data.description,
                    unit=data.unit,
                    quantity=_quantize_money_str(data.quantity),
                    unit_rate=_quantize_money_str(data.unit_rate),
                    total=_compute_total(data.quantity, data.unit_rate),
                    classification=data.classification,
                    source=data.source,
                    confidence=(str(data.confidence) if data.confidence is not None else None),
                    cad_element_ids=data.cad_element_ids,
                    metadata_=merged_metadata,
                    validation_status="warnings" if _bulk_cost_warned else "pending",
                    sort_order=max_order + offset,
                ),
            )

        # Single flush - the perf win lives here.
        inserted = await self.position_repo.bulk_create(new_positions)

        await _safe_publish(
            "boq.positions.bulk_created",
            {"boq_id": str(boq_id), "count": len(inserted)},
            source_module="oe_boq",
        )
        await _safe_audit(
            self.session,
            action="bulk_create",
            entity_type="position",
            entity_id=str(boq_id),
            details={"count": len(inserted)},
        )

        logger.info("Bulk-added %d positions to BOQ %s", len(inserted), boq_id)
        return inserted

    async def create_section(self, boq_id: uuid.UUID, data: SectionCreate) -> Position:
        """Create a section header row in a BOQ.

        A section is stored as a Position with unit="section", quantity=0,
        unit_rate=0.  This distinguishes it from regular items. Issue #136:
        a section may nest under another section via ``data.parent_id``,
        bounded by ``MAX_NESTING_DEPTH``.

        Args:
            boq_id: Target BOQ identifier.
            data: Section creation payload (ordinal, description, parent_id).

        Returns:
            The newly created section (Position).

        Raises:
            HTTPException 404 if the target BOQ doesn't exist.
            HTTPException 409 if the BOQ is locked.
            HTTPException 422 if ``parent_id`` is invalid or the placement
                would exceed ``MAX_NESTING_DEPTH`` (Issue #136).
        """
        await self._ensure_not_locked(boq_id)

        # Check ordinal uniqueness within the BOQ
        if await self.position_repo.ordinal_exists(boq_id, data.ordinal):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Section with ordinal '{data.ordinal}' already exists in this BOQ",
            )

        # Issue #136: validate the (optional) parent + enforce the cap.
        parent_id = getattr(data, "parent_id", None)
        await self._validate_parent_id(
            boq_id=boq_id,
            position_id=None,
            new_parent_id=parent_id,
        )
        await self._validate_nesting_depth(new_parent_id=parent_id)

        max_order = await self.position_repo.get_max_sort_order(boq_id)

        section = Position(
            boq_id=boq_id,
            parent_id=parent_id,
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
        self,
        position_id: uuid.UUID,
        data: PositionUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Position:
        """Update a position and recalculate total if quantity or unit_rate changed.

        Args:
            position_id: Target position identifier.
            data: Partial update payload.  May include ``version`` for
                optimistic-concurrency control (BUG-CONCURRENCY01).
            actor_id: Optional caller user-id to attribute the audit-log
                entry to.  When ``None`` the service falls back to the
                system zero-UUID; routers should always pass it explicitly
                so ``BOQActivityLog.user_id`` resolves to a real user
                (PG/SQLite both enforce the FK).

        Returns:
            Updated position.

        Raises:
            HTTPException 404 if position not found.
            HTTPException 409 if the owning BOQ is locked, the ordinal
                collides, OR the supplied ``version`` does not match the
                row's current value (lost-update protection).
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.position_not_found", locale=get_locale()),
            )
        await self._ensure_not_locked(position.boq_id)

        # ── Issue #127: capture pre-update link state ────────────────────
        # Needed AFTER the write to decide master-propagation vs
        # instance-unlink. A snapshot of which definition fields the
        # client touched drives both branches.
        _link_role_before = getattr(position, "link_role", None)
        _link_group_before = getattr(position, "link_group_id", None)
        _ref_code_before = getattr(position, "reference_code", None)

        fields = data.model_dump(exclude_unset=True)

        # ``link_mode`` is a create-time decision only - never persisted on
        # update (PositionUpdate documents it as ignored). Drop it before it
        # reaches the column writer.
        fields.pop("link_mode", None)
        # Which DEFINITION fields did the client explicitly set? (used for
        # propagate-from-master / unlink-instance). Snapshot the *requested*
        # keys now, before the metadata/cost-item merge logic mutates
        # ``fields`` and adds derived keys (total/version/validation_status).
        _requested_def_fields: set[str] = {k for k in fields if k in _LINK_UNLINK_TRIGGER_FIELDS}
        if "metadata" in fields:
            _requested_def_fields.add("metadata_")

        # ── Issue #79: cost_item_id linkage ─────────────────────────────
        # The client doesn't see ``metadata.cost_item_id`` directly - they
        # send a top-level ``cost_item_id`` field.  Pop it out, validate
        # the target exists, then merge into ``metadata`` so the existing
        # JSON-column write path persists it without a schema migration.
        client_cost_item_id = fields.pop("cost_item_id", None)
        if client_cost_item_id is not None:
            try:
                cost_repo = CostItemRepository(self.session)
                cost_item = await cost_repo.get_by_id(client_cost_item_id)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 - surface any DB failure as 422
                logger.exception(
                    "update_position cost_item lookup failed for %s",
                    client_cost_item_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(f"cost_item_id does not reference an active CostItem ({type(exc).__name__})"),
                ) from exc
            if cost_item is None or not getattr(cost_item, "is_active", False):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="cost_item_id does not reference an active CostItem",
                )
            # Merge into the metadata field that the rest of the function
            # already knows how to persist.  Preserve any other keys the
            # caller patched (or, when they didn't touch metadata, the
            # existing stored values).
            base_meta: dict[str, Any]
            if "metadata" in fields and isinstance(fields["metadata"], dict):
                base_meta = dict(fields["metadata"])
            else:
                existing_meta = position.metadata_ if isinstance(position.metadata_, dict) else {}
                base_meta = dict(existing_meta)
            base_meta["cost_item_id"] = str(client_cost_item_id)
            # BUG-B-013: stamp unit/currency provenance + flag mismatch.
            # ``data.unit`` (if the same patch changes the unit) takes
            # precedence over the stored unit.
            _new_unit = fields.get("unit", position.unit)
            if (
                _stamp_cost_item_compat(
                    base_meta,
                    cost_item=cost_item,
                    position_unit=_new_unit,
                    project_currency=await self._resolve_project_currency(position.boq_id),
                )
                and "validation_status" not in fields
            ):
                fields["validation_status"] = "warnings"
            fields["metadata"] = base_meta

        # ── BUG-CONCURRENCY01: optimistic concurrency check ──────────────
        # Pop the client-supplied ``version`` so it never reaches the SQL
        # UPDATE.  We bump it ourselves below.
        client_version = fields.pop("version", None)
        if client_version is not None and int(client_version) != int(position.version or 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Position was modified by another writer (server version "
                    f"{position.version}, client supplied {client_version}). "
                    "Reload and retry."
                ),
            )

        # ── BUG-AUDIT01: snapshot before-state for the audit-log diff ──
        # Capture *before* mutation so the audit row carries old/new pairs
        # for every column the patch touches.  We only snapshot fields the
        # client actually set, mirroring ``exclude_unset`` above.
        _audit_before: dict[str, Any] = {}
        for key in fields:
            attr = "metadata_" if key == "metadata" else key
            try:
                _audit_before[key] = getattr(position, attr)
            except AttributeError:
                _audit_before[key] = None

        # ── Issue #133: snapshot resources BEFORE the write so a master
        # resource definition edit can be diffed + propagated afterwards.
        _res_before: list[dict[str, Any]] | None = None
        if "metadata" in fields:
            _existing_meta = position.metadata_ if isinstance(position.metadata_, dict) else {}
            _rb = _existing_meta.get("resources")
            if isinstance(_rb, list):
                _res_before = [dict(r) if isinstance(r, dict) else {} for r in _rb]

        # If ordinal is being changed, check uniqueness within the BOQ
        if "ordinal" in fields and fields["ordinal"] != position.ordinal:
            if await self.position_repo.ordinal_exists(position.boq_id, fields["ordinal"], exclude_id=position_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Position with ordinal '{fields['ordinal']}' already exists in this BOQ",
                )

        # If parent_id is being changed, validate it doesn't create a cycle
        # or cross BOQ boundaries. Skip the walk when the value is unchanged
        # so untouched edits don't pay the descendant-traversal cost.
        if "parent_id" in fields and fields["parent_id"] != position.parent_id:
            await self._validate_parent_id(
                boq_id=position.boq_id,
                position_id=position_id,
                new_parent_id=fields["parent_id"],
            )
            # Issue #136: re-parenting must keep the WHOLE moved subtree
            # within the configurable depth cap, not just its root.
            await self._validate_nesting_depth(
                new_parent_id=fields["parent_id"],
                moving_subtree_root=position_id,
            )

        # Convert float values to strings for storage and quantise to 4dp
        # so storage drift cannot accumulate (BUG-MATH01).
        if "quantity" in fields:
            fields["quantity"] = _quantize_money_str(fields["quantity"])
        if "unit_rate" in fields:
            fields["unit_rate"] = _quantize_money_str(fields["unit_rate"])
        if "confidence" in fields:
            val = fields["confidence"]
            fields["confidence"] = str(val) if val is not None else None

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # If metadata contains resources, derive unit_rate from resource totals.
        #
        # IMPORTANT: only re-derive when this update was *triggered by* a change
        # to quantity or to the resources themselves. Otherwise - for example
        # when the user edits an unrelated custom column and the frontend
        # echoes back the existing metadata - we'd silently rewrite unit_rate
        # and total even though nothing meaningful changed.
        meta = fields.get("metadata_", None)
        if meta is None and "metadata" in fields:
            meta = fields.get("metadata")
        new_quantity = fields.get("quantity", position.quantity)
        new_unit_rate = fields.get("unit_rate", position.unit_rate)

        # Resource model: each resource entry is a PER-UNIT norm
        # (quantity per 1 unit of position) - same convention as
        # mainstream estimating and 5D takeoff tools. Therefore:
        #   unit_rate (of position) = Σ(r.quantity × r.unit_rate)   [no division by qty]
        #   total    (of position) = position.quantity × unit_rate
        #
        # That means a pure position-quantity edit must leave unit_rate
        # AND the per-unit resource norms untouched; only the total
        # scales. unit_rate is re-derived from resources only when the
        # resources list itself changed.
        triggered_by_qty = "quantity" in fields
        triggered_by_resources = False
        if meta and isinstance(meta, dict) and isinstance(meta.get("resources"), list):
            existing_meta = position.metadata_ if isinstance(position.metadata_, dict) else {}
            existing_resources = existing_meta.get("resources") if isinstance(existing_meta, dict) else None
            if existing_resources != meta["resources"]:
                triggered_by_resources = True

        # ── FX context (resolved once, reused below for warning detection) ──
        # Resolving the project FX table here lets the resource→unit_rate
        # derivation convert each foreign-currency resource into the project
        # BASE currency BEFORE summing, instead of blending currencies into a
        # single base-denominated figure. Best-effort: a lookup failure
        # returns ("", {}) so the derivation degrades to a raw sum rather
        # than a 500 (mirrors the read/rollup path's tolerance).
        _fx_base_ccy: str | None = None
        _fx_map: dict[str, str] | None = None

        if (
            triggered_by_resources
            and meta
            and isinstance(meta, dict)
            and isinstance(meta.get("resources"), list)
            and meta["resources"]
        ):
            resources = meta["resources"]
            _fx_base_ccy, _fx_map = await self._resolve_project_fx(position.boq_id)
            # Sum of per-unit subtotals == position unit_rate (NO division by
            # qty). Each resource is converted from its own ``currency`` to the
            # project base via the FX table before summing - never blend
            # currencies into the stored rate (Issue #88 / #157). Mirrors the
            # read-side ``_resource_total_in_base`` so the persisted value and
            # the FX-aware rollup agree.
            new_unit_rate = _quantize_money_str(_resource_total_in_base(resources, _fx_map, _fx_base_ccy or ""))
            fields["unit_rate"] = new_unit_rate

        # Recalculate total only when something pricing-related actually changed.
        # A pure metadata patch (e.g. setting a custom column value) leaves the
        # existing total intact.
        if "quantity" in fields or "unit_rate" in fields or triggered_by_resources:
            # Probe-A scenario 11: enforce the overflow cap on the
            # post-merge values - covers the partial-update path where
            # the schema validator only saw one side of (quantity,
            # unit_rate). Mirrors ``POSITION_TOTAL_CAP`` from
            # ``boq/schemas.py`` so the message is identical.
            try:
                _q = Decimal(str(new_quantity)) * Decimal(str(new_unit_rate))
            except (InvalidOperation, ValueError):
                _q = None
            if _q is not None and _q > Decimal("1e15"):
                raise ValueError(
                    "Position total exceeds reasonable limit. Check quantity and unit rate.",
                )
            # Pass raw string values straight through - ``_compute_total`` now
            # uses Decimal and handles strings directly, so we avoid the
            # str → float → str roundtrip that was losing precision.
            fields["total"] = _compute_total(new_quantity, new_unit_rate)

        # Manual quantity override: drop BIM/PDF/DWG link artifacts and reset
        # validation. When the user hand-edits the quantity, any previously-
        # linked source is no longer authoritative - unit-column badges
        # disappear and the red validation border clears until re-validation
        # runs.
        #
        # Exception: when the caller (BIM Quantity Picker, PDF takeoff "Use
        # as quantity", or DWG popover "Apply") explicitly includes the
        # relevant ``*_source`` key in the incoming metadata, that key is the
        # authoritative new link and must be preserved through the strip
        # pass. Without this carve-out the picker's own provenance was wiped
        # on the same request that set it.
        if triggered_by_qty:
            existing_meta = position.metadata_ if isinstance(position.metadata_, dict) else {}
            incoming_meta = fields.get("metadata_")
            base_meta = dict(incoming_meta) if isinstance(incoming_meta, dict) else dict(existing_meta)
            stripped = False
            for link_key in (
                "bim_qty_source",
                "pdf_measurement_source",
                "dwg_annotation_source",
            ):
                if isinstance(incoming_meta, dict) and link_key in incoming_meta:
                    continue
                if link_key in base_meta:
                    base_meta.pop(link_key)
                    stripped = True
            if stripped or isinstance(incoming_meta, dict):
                fields["metadata_"] = base_meta
            if "validation_status" not in fields:
                fields["validation_status"] = "pending"

        # ── CWICR variant snapshot ───────────────────────────────────────
        # When the incoming metadata sets ``variant`` or ``variant_default``,
        # stamp ``variant_snapshot`` so the position's unit_rate is frozen
        # against later cost-database changes.  We only mutate metadata when
        # the snapshot is actually missing or stale - the helper is a no-op
        # for plain manual positions.
        #
        # Idempotency: a no-op metadata patch (same variant payload, no
        # snapshot in the incoming dict) must not advance ``captured_at``.
        # We pre-seed the incoming metadata with the existing snapshot so
        # ``_stamp_variant_snapshot`` can short-circuit when nothing changed.
        if "metadata_" in fields and isinstance(fields["metadata_"], dict):
            # Resolve the rate that's about to be persisted; falls back to
            # the new_unit_rate computed above when the patch only touches
            # metadata.
            snapshot_rate = fields.get("unit_rate", new_unit_rate)
            existing_meta = position.metadata_ if isinstance(position.metadata_, dict) else {}
            currency = fields["metadata_"].get("currency") or (
                existing_meta.get("currency") if isinstance(existing_meta, dict) else None
            )
            existing_snapshot = existing_meta.get("variant_snapshot") if isinstance(existing_meta, dict) else None
            if isinstance(existing_snapshot, dict) and "variant_snapshot" not in fields["metadata_"]:
                # Carry the existing snapshot forward so the idempotency
                # check inside ``_stamp_variant_snapshot`` can compare
                # against it.  If the new variant choice still matches,
                # ``captured_at`` stays stable.  If it has changed, the
                # helper overwrites this seed with a fresh entry below.
                fields["metadata_"]["variant_snapshot"] = existing_snapshot
            _stamp_variant_snapshot(
                fields["metadata_"],
                unit_rate=snapshot_rate,
                currency=currency if isinstance(currency, str) else None,
            )
            # Per-resource snapshots - preserve any existing snapshots on
            # incoming resources that didn't include one, so the idempotency
            # check inside ``_stamp_resource_variant_snapshots`` can compare
            # against them. Without this seeding, every metadata patch would
            # bump ``captured_at`` on resources whose pick is unchanged.
            existing_resources = existing_meta.get("resources") if isinstance(existing_meta, dict) else None
            incoming_resources = fields["metadata_"].get("resources")
            if isinstance(existing_resources, list) and isinstance(incoming_resources, list):
                # Match by code+name pair to survive reorder; positional fall-
                # back for anonymous resources. Existing snapshots are seeded
                # only when the incoming entry lacks one.
                lookup: dict[tuple[str, str], dict[str, Any]] = {}
                for er in existing_resources:
                    if isinstance(er, dict) and isinstance(er.get("variant_snapshot"), dict):
                        key = (str(er.get("code", "")), str(er.get("name", "")))
                        lookup[key] = er["variant_snapshot"]
                for idx, ir in enumerate(incoming_resources):
                    if not isinstance(ir, dict) or "variant_snapshot" in ir:
                        continue
                    key = (str(ir.get("code", "")), str(ir.get("name", "")))
                    seeded = lookup.get(key)
                    if seeded is None and idx < len(existing_resources):
                        prev = existing_resources[idx]
                        if isinstance(prev, dict) and isinstance(prev.get("variant_snapshot"), dict):
                            seeded = prev["variant_snapshot"]
                    if seeded is not None:
                        ir["variant_snapshot"] = seeded
            _stamp_resource_variant_snapshots(
                fields["metadata_"],
                position_currency=currency if isinstance(currency, str) else None,
            )
            # Canonical M/L/E rollup: re-stamp ``resource_breakdown`` whenever
            # a metadata patch carries resources, so the grid split columns
            # and the pill read fresh per-type totals/percentages.
            _stamp_resource_breakdown(fields["metadata_"])

        # BUG-B-014: re-evaluate the boq_quality duplicate-content signal
        # whenever the patch touches description / unit / quantity /
        # unit_rate. We compare the post-merge effective values against
        # the other positions in the same BOQ (excluding this row). The
        # warning is non-blocking - it only flags the traffic-light.
        if any(k in fields for k in ("description", "unit", "quantity", "unit_rate")):
            eff_desc = fields.get("description", position.description)
            eff_unit = fields.get("unit", position.unit)
            eff_qty = fields.get("quantity", position.quantity)
            eff_rate = fields.get("unit_rate", position.unit_rate)
            dup_ordinal = await self._find_content_duplicate(
                position.boq_id,
                description=eff_desc,
                unit=eff_unit,
                quantity=eff_qty,
                unit_rate=eff_rate,
                exclude_id=position_id,
            )
            # Resolve the metadata dict that will actually be persisted so
            # the warning isn't lost: prefer an in-flight metadata patch,
            # else carry the existing stored metadata forward.
            if "metadata_" in fields and isinstance(fields["metadata_"], dict):
                _dup_meta = fields["metadata_"]
            else:
                _existing = position.metadata_ if isinstance(position.metadata_, dict) else {}
                _dup_meta = dict(_existing)
            _had_marker = any(
                str(w).startswith(_DUPLICATE_WARNING_PREFIX)
                for w in (
                    _dup_meta.get("boq_quality_warnings")
                    if isinstance(_dup_meta.get("boq_quality_warnings"), list)
                    else []
                )
            )
            if dup_ordinal is not None:
                _apply_duplicate_warning(_dup_meta, dup_ordinal)
                fields["metadata_"] = _dup_meta
                if "validation_status" not in fields:
                    fields["validation_status"] = "warnings"
            elif _had_marker:
                # The edit resolved a former duplicate - clear the stale
                # marker so the traffic-light stops flagging it.
                _remaining = [
                    w
                    for w in _dup_meta.get("boq_quality_warnings", [])
                    if not str(w).startswith(_DUPLICATE_WARNING_PREFIX)
                ]
                if _remaining:
                    _dup_meta["boq_quality_warnings"] = _remaining
                else:
                    _dup_meta.pop("boq_quality_warnings", None)
                fields["metadata_"] = _dup_meta

        # ── Issue #127: instance definition edit → unlink + warn ─────────
        # If THIS position is a linked instance and the caller directly
        # edited a DEFINITION field (description / unit / unit_rate /
        # classification / source / cad_element_ids / metadata sub-
        # structure), it must NOT back-propagate to the master. Instead it
        # diverges: clear its link fields and attach a clear warning
        # (mirrors the customer's "si no quisiera cambiarlo, alertar").
        # A pure quantity / ordinal / sort_order edit NEVER unlinks.
        _did_unlink_instance = False
        _unlink_siblings_remaining = 0
        if _link_role_before == "instance" and _link_group_before is not None:
            _changed_def = False
            for _df in _requested_def_fields:
                if _df == "metadata_":
                    _new_meta = fields.get("metadata_")
                    _old_meta = position.metadata_ if isinstance(position.metadata_, dict) else {}
                    if isinstance(_new_meta, dict) and _new_meta != _old_meta:
                        _changed_def = True
                else:
                    if _df in fields and fields[_df] != getattr(position, _df, None):
                        _changed_def = True
            if _changed_def:
                # Count the OTHER positions still sharing the code so the
                # warning is actionable.
                try:
                    _grp = await self.position_repo.list_link_group(_link_group_before)
                    _unlink_siblings_remaining = max(0, len([p for p in _grp if p.id != position_id]) - 0)
                except Exception:  # noqa: BLE001 - advisory count only
                    _unlink_siblings_remaining = 0
                fields["link_group_id"] = None
                fields["link_role"] = None
                # Keep the code so the position stays referenceable, but it
                # no longer follows the master.
                _warn_meta: dict[str, Any]
                if "metadata_" in fields and isinstance(fields["metadata_"], dict):
                    _warn_meta = fields["metadata_"]
                else:
                    _existing_wm = position.metadata_ if isinstance(position.metadata_, dict) else {}
                    _warn_meta = dict(_existing_wm)
                _code_label = _ref_code_before or "(internal)"
                _msg = (
                    f"Editing this position's definition unlinked it from "
                    f"code '{_code_label}'; {_unlink_siblings_remaining} "
                    f"other position(s) still share '{_code_label}'."
                )
                _w = _warn_meta.get("boq_quality_warnings")
                _wl: list[str] = list(_w) if isinstance(_w, list) else []
                _wl = [x for x in _wl if "unlinked it from code" not in str(x)]
                _wl.append(_msg)
                _warn_meta["boq_quality_warnings"] = _wl
                _warn_meta["link_unlinked_from"] = _code_label
                fields["metadata_"] = _warn_meta
                if "validation_status" not in fields:
                    fields["validation_status"] = "warnings"
                _did_unlink_instance = True

        if fields:
            # BUG-CONCURRENCY01: bump the version counter atomically with the
            # rest of the field set so any concurrent reader observing the
            # post-write state also sees the incremented token.
            fields["version"] = int(position.version or 0) + 1
            # Bug 1 (v2.5.4): wrap the DB write in a defensive try/except so
            # any unexpected SQLAlchemy/IntegrityError surfaces as a 422 with
            # a useful detail instead of a bare 500. Common trigger: undo
            # replay against a position whose parent_id, ordinal, or numeric
            # field is no longer valid relative to current DB state.
            try:
                await self.position_repo.update_fields(position_id, **fields)
                # Flush to DB, then refresh ORM state from DB (avoids MissingGreenlet on lazy load)
                await self.session.flush()
                await self.session.refresh(position)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 - surface any DB failure as 422
                logger.exception(
                    "update_position DB write failed for %s; fields=%s",
                    position_id,
                    {k: type(v).__name__ for k, v in fields.items()},
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Position update could not be applied. The row may have "
                        "been deleted or modified concurrently - reload and retry. "
                        f"({type(exc).__name__})"
                    ),
                ) from exc

        # ── Issue #127: master definition edit → propagate to instances ──
        # If THIS position is a master and a DEFINITION field actually
        # changed, propagate ONLY those definition fields to every linked
        # instance in the group across the WHOLE project, in this same
        # transaction. NEVER propagate quantity / ordinal / sort_order /
        # link fields - those stay per-instance (the architecture guide: quantities
        # never propagate). Each affected position + its BOQ totals are
        # recomputed, the position-changed event fires per instance, and
        # ONE audit entry records the fan-out.
        _propagated_count = 0
        if _link_role_before == "master" and _link_group_before is not None and not _did_unlink_instance and fields:
            # Resolve the definition fields whose persisted value changed.
            _changed_def_payload: dict[str, Any] = {}
            for _df in _LINK_DEFINITION_FIELDS:
                if _df not in _requested_def_fields:
                    continue
                _new = getattr(position, _df, None)
                _changed_def_payload[_df] = _new
            # Metadata sub-structure (resources / assembly) propagates too.
            _propagate_meta = "metadata_" in _requested_def_fields and isinstance(position.metadata_, dict)
            if _changed_def_payload or _propagate_meta:
                try:
                    # ``repo.update_fields`` ends in ``session.expire_all()``,
                    # which expires EVERY ORM instance - the master
                    # ``position`` AND every row in ``group``. The async
                    # engine can't lazy-refresh on attribute access
                    # (``MissingGreenlet``), so snapshot the master's
                    # metadata once here and each instance's fields at the
                    # top of its iteration, then only touch locals after the
                    # per-instance write.
                    _master_meta_snapshot = position.metadata_ if isinstance(position.metadata_, dict) else {}
                    group = await self.position_repo.list_link_group(_link_group_before)
                    # Snapshot EVERY group member into plain values BEFORE
                    # the first per-instance write. ``update_fields`` ends in
                    # ``session.expire_all()``, so reading another (not-yet-
                    # processed) group member's ORM attributes on a LATER
                    # loop iteration would lazy-load on the async engine →
                    # MissingGreenlet. The original per-iteration snapshot
                    # only happened to be safe when the group had ≤1
                    # propagation target; #132 subtree groups have several.
                    _grp_snap: list[dict[str, Any]] = [
                        {
                            "id": g.id,
                            "role": g.link_role,
                            "boq_id": g.boq_id,
                            "ordinal": g.ordinal,
                            "quantity": g.quantity,
                            "unit_rate": g.unit_rate,
                            "version": int(g.version or 0),
                            "meta": (dict(g.metadata_) if isinstance(g.metadata_, dict) else {}),
                        }
                        for g in group
                    ]
                    # Issue #132: groups created with the per-node
                    # correspondence key (``_link_src``) propagate a ROOT
                    # edit ONLY to instance ROOTS (those whose ``_link_src``
                    # points back at this master root) - never blanket-
                    # overwriting instance CHILDREN with the root's
                    # definition. Legacy groups predating #132 carry no
                    # ``_link_src`` anywhere; they keep the original
                    # group-flat behaviour so existing links never regress.
                    _group_has_src = any("_link_src" in s["meta"] for s in _grp_snap)
                    affected_boqs: set[uuid.UUID] = set()
                    for _snap in _grp_snap:
                        _inst_id = _snap["id"]
                        _inst_role = _snap["role"]
                        _inst_boq_id = _snap["boq_id"]
                        _inst_ordinal = _snap["ordinal"]
                        _inst_quantity = _snap["quantity"]
                        _inst_unit_rate = _snap["unit_rate"]
                        _inst_version = _snap["version"]
                        _inst_meta = _snap["meta"]
                        if _inst_id == position_id:
                            continue
                        if _inst_role != "instance":
                            continue
                        # Correspondence guard (Issue #132): on #132-era
                        # groups a ROOT edit only reaches the instance
                        # ROOTS that mirror THIS master root. Instance
                        # children (``_link_src`` = their own master child)
                        # are handled by the master-child pass below.
                        if _group_has_src and str(_inst_meta.get("_link_src")) != str(position_id):
                            continue
                        inst_fields: dict[str, Any] = {}
                        for k, v in _changed_def_payload.items():
                            if k == "classification":
                                inst_fields[k] = dict(v) if isinstance(v, dict) else v
                            elif k == "cad_element_ids":
                                inst_fields[k] = list(v) if isinstance(v, list) else v
                            else:
                                inst_fields[k] = v
                        if _propagate_meta:
                            # Carry the master's reusable sub-structure but
                            # preserve each instance's own per-instance
                            # quantity-bound markers (BIM/PDF/DWG sources).
                            inst_meta = _copy_definition_metadata(_master_meta_snapshot)
                            for _k in _LINK_INSTANCE_ONLY_META_KEYS:
                                if _k in _inst_meta:
                                    inst_meta[_k] = _inst_meta[_k]
                            inst_fields["metadata_"] = inst_meta
                        # Recompute the instance total against ITS OWN
                        # quantity and the (possibly new) unit_rate.
                        _eff_rate = inst_fields.get("unit_rate", _inst_unit_rate)
                        inst_fields["total"] = _compute_total(_inst_quantity, _eff_rate)
                        inst_fields["version"] = _inst_version + 1
                        await self.position_repo.update_fields(_inst_id, **inst_fields)
                        affected_boqs.add(_inst_boq_id)
                        _propagated_count += 1
                        await _safe_publish(
                            "boq.position.updated",
                            {
                                "position_id": str(_inst_id),
                                "boq_id": str(_inst_boq_id),
                                "ordinal": _inst_ordinal,
                                "changes": {"propagated_from": str(position_id)},
                                "kind": "linked_master_propagation",
                            },
                            source_module="oe_boq",
                        )
                    await self.session.flush()
                    # The per-instance update_fields() calls each ran
                    # session.expire_all(); re-hydrate the master so the
                    # activity-log here and the audit-diff / event / response
                    # reads below operate on live attributes, not expired
                    # ones (async engine can't lazy-refresh → MissingGreenlet).
                    if _propagated_count:
                        await self.session.refresh(position)
                    if _propagated_count and actor_id is not None:
                        try:
                            _proj_id: uuid.UUID | None = None
                            try:
                                _b = await self.get_boq(position.boq_id)
                                _proj_id = _b.project_id
                            except Exception:  # noqa: BLE001
                                _proj_id = None
                            await self.log_activity(
                                user_id=actor_id,
                                action="position.linked_propagation",
                                target_type="position",
                                description=(
                                    f"Propagated master definition of "
                                    f"'{_ref_code_before}' to "
                                    f"{_propagated_count} linked instance(s)"
                                ),
                                project_id=_proj_id,
                                boq_id=position.boq_id,
                                target_id=position.id,
                                changes={
                                    "fields": sorted(_changed_def_payload),
                                    "metadata_propagated": _propagate_meta,
                                    "instance_count": _propagated_count,
                                },
                                metadata_={
                                    "reference_code": _ref_code_before,
                                    "link_group_id": str(_link_group_before),
                                },
                            )
                        except Exception:  # noqa: BLE001 - best-effort
                            logger.debug(
                                "Activity-log for linked propagation failed",
                                exc_info=True,
                            )
                except Exception:  # noqa: BLE001 - never break the master PATCH
                    logger.exception(
                        "Linked-position propagation failed for master %s (group=%s)",
                        position_id,
                        _link_group_before,
                    )

        # ── Issue #132: master CHILD edit → propagate to instance children ─
        # The block above only fires when the edited row is the master
        # ROOT (``link_role='master'``). A master's CHILDREN carry no
        # link_role (they are originals, not instances), so editing one
        # used to propagate to nothing - the customer's "reuse a whole
        # partida, fix a sub-line on the master, instances stay stale"
        # bug. Here: if the edited row is a non-link node whose subtree
        # ROOT is a master, fan the changed DEFINITION fields out to the
        # instance nodes that were cloned from THIS exact node
        # (``metadata._link_src == position_id``). Quantities / ordinals
        # never propagate (the architecture guide). Instance-side direct edits still
        # diverge+unlink via the block far above - unchanged.
        if _link_role_before is None and not _did_unlink_instance and fields and _requested_def_fields:
            try:
                # Snapshot the edited node's post-write definition BEFORE any
                # per-instance update_fields() (each ends in expire_all();
                # the async engine cannot lazy-refresh → MissingGreenlet).
                _mc_changed: dict[str, Any] = {}
                for _df in _LINK_DEFINITION_FIELDS:
                    if _df in _requested_def_fields:
                        _mc_changed[_df] = getattr(position, _df, None)
                _mc_prop_meta = "metadata_" in _requested_def_fields and isinstance(position.metadata_, dict)
                _mc_meta_snapshot = position.metadata_ if isinstance(position.metadata_, dict) else {}
                if _mc_changed or _mc_prop_meta:
                    # Walk parent chain to the subtree root (depth-capped -
                    # a cycle would otherwise loop forever).
                    _walk_id = getattr(position, "parent_id", None)
                    _root_node: Position | None = None
                    _hops = 0
                    while _walk_id is not None and _hops < 256:
                        _node = await self.position_repo.get_by_id(_walk_id)
                        if _node is None:
                            break
                        _root_node = _node
                        _walk_id = getattr(_node, "parent_id", None)
                        _hops += 1
                    if (
                        _root_node is not None
                        and _root_node.link_role == "master"
                        and _root_node.link_group_id is not None
                        and _root_node.id != position_id
                    ):
                        # Snapshot the master root's link identity NOW -
                        # per-instance update_fields() runs expire_all()
                        # and the async engine can't lazy-refresh these
                        # later for the activity-log (MissingGreenlet).
                        _mc_root_group_id = _root_node.link_group_id
                        _mc_root_code = _root_node.reference_code
                        _mc_group = await self.position_repo.list_link_group(_mc_root_group_id)
                        # Pre-snapshot the whole group before any write -
                        # update_fields() → expire_all() would otherwise make
                        # a later iteration's ORM read lazy-load on the async
                        # engine (MissingGreenlet) once >1 child matches.
                        _mc_snap: list[dict[str, Any]] = [
                            {
                                "id": _c.id,
                                "role": _c.link_role,
                                "boq_id": _c.boq_id,
                                "ordinal": _c.ordinal,
                                "quantity": _c.quantity,
                                "unit_rate": _c.unit_rate,
                                "version": int(_c.version or 0),
                                "meta": (dict(_c.metadata_) if isinstance(_c.metadata_, dict) else {}),
                            }
                            for _c in _mc_group
                        ]
                        _mc_affected: set[uuid.UUID] = set()
                        for _cs in _mc_snap:
                            _ci_id = _cs["id"]
                            _ci_role = _cs["role"]
                            _ci_boq_id = _cs["boq_id"]
                            _ci_ordinal = _cs["ordinal"]
                            _ci_quantity = _cs["quantity"]
                            _ci_unit_rate = _cs["unit_rate"]
                            _ci_version = _cs["version"]
                            _ci_meta = _cs["meta"]
                            if _ci_id == position_id:
                                continue
                            if _ci_role != "instance":
                                continue
                            # Per-node correspondence: only the instance
                            # children cloned from THIS master child.
                            if str(_ci_meta.get("_link_src")) != str(position_id):
                                continue
                            _ci_fields: dict[str, Any] = {}
                            for k, v in _mc_changed.items():
                                if k == "classification":
                                    _ci_fields[k] = dict(v) if isinstance(v, dict) else v
                                elif k == "cad_element_ids":
                                    _ci_fields[k] = list(v) if isinstance(v, list) else v
                                else:
                                    _ci_fields[k] = v
                            if _mc_prop_meta:
                                _ci_new_meta = _copy_definition_metadata(_mc_meta_snapshot)
                                # Preserve the instance child's own
                                # per-instance keys - crucially ``_link_src``
                                # so the correspondence survives the copy.
                                for _k in _LINK_INSTANCE_ONLY_META_KEYS:
                                    if _k in _ci_meta:
                                        _ci_new_meta[_k] = _ci_meta[_k]
                                _ci_fields["metadata_"] = _ci_new_meta
                            _ci_rate = _ci_fields.get("unit_rate", _ci_unit_rate)
                            _ci_fields["total"] = _compute_total(_ci_quantity, _ci_rate)
                            _ci_fields["version"] = _ci_version + 1
                            await self.position_repo.update_fields(_ci_id, **_ci_fields)
                            _mc_affected.add(_ci_boq_id)
                            _propagated_count += 1
                            await _safe_publish(
                                "boq.position.updated",
                                {
                                    "position_id": str(_ci_id),
                                    "boq_id": str(_ci_boq_id),
                                    "ordinal": _ci_ordinal,
                                    "changes": {"propagated_from": str(position_id)},
                                    "kind": "linked_master_child_propagation",
                                },
                                source_module="oe_boq",
                            )
                        await self.session.flush()
                        if _mc_affected:
                            await self.session.refresh(position)
                        if _mc_affected and actor_id is not None:
                            try:
                                _mc_proj: uuid.UUID | None = None
                                try:
                                    _mb = await self.get_boq(position.boq_id)
                                    _mc_proj = _mb.project_id
                                except Exception:  # noqa: BLE001
                                    _mc_proj = None
                                await self.log_activity(
                                    user_id=actor_id,
                                    action="position.linked_propagation",
                                    target_type="position",
                                    description=(
                                        f"Propagated master sub-line "
                                        f"'{position.ordinal}' to "
                                        f"{len(_mc_affected)} linked "
                                        f"instance child(ren)"
                                    ),
                                    project_id=_mc_proj,
                                    boq_id=position.boq_id,
                                    target_id=position.id,
                                    changes={
                                        "fields": sorted(_mc_changed),
                                        "metadata_propagated": _mc_prop_meta,
                                        "kind": "master_child",
                                    },
                                    metadata_={
                                        "reference_code": _mc_root_code,
                                        "link_group_id": str(_mc_root_group_id),
                                    },
                                )
                            except Exception:  # noqa: BLE001 - best-effort
                                logger.debug(
                                    "Activity-log for master-child propagation failed",
                                    exc_info=True,
                                )
            except Exception:  # noqa: BLE001 - never break the child PATCH
                logger.exception(
                    "Master-child linked propagation failed for %s",
                    position_id,
                )

        # ── BUG-AUDIT01: build the field-level diff payload ──────────────
        # ``_audit_before`` snapshotted attributes BEFORE the UPDATE; we
        # snapshot again now to compose ``{"field": {"old": ..., "new": ...}}``
        # entries.  Stringify everything so the JSON column never receives
        # an opaque Decimal/UUID/datetime that would break dict equality
        # downstream.  ``version`` is embedded in metadata so consumers can
        # reconstruct the row history without joining back to ``Position``.
        changes_diff: dict[str, dict[str, Any]] = {}
        if fields:
            for key in _audit_before:
                attr = "metadata_" if key == "metadata" else key
                try:
                    new_val = getattr(position, attr)
                except AttributeError:
                    new_val = None
                old_val = _audit_before[key]
                if old_val != new_val:
                    changes_diff[key] = {
                        "old": _coerce_audit_value(old_val),
                        "new": _coerce_audit_value(new_val),
                    }

        await _safe_publish(
            "boq.position.updated",
            {
                "position_id": str(position.id),
                "boq_id": str(position.boq_id),
                "ordinal": position.ordinal,
                # Diff payload picked up by the activity-log wildcard
                # handler in ``boq.events`` (BUG-AUDIT01).
                "changes": changes_diff,
                "version": int(position.version or 0),
            },
            source_module="oe_boq",
        )

        # ── BUG-AUDIT01: direct activity-log write ──────────────────────
        # The wildcard event handler in ``boq.events`` is *not* registered
        # on SQLite (greenlet-bridge issue) so dev / test instances would
        # otherwise lose every position-update audit entry.  Writing
        # in-line here, in the same session as the update, guarantees
        # coverage on every dialect.  Skipped when the caller did not
        # supply a real user-id (FK-bound column).
        if changes_diff and actor_id is not None:
            try:
                project_id: uuid.UUID | None = None
                try:
                    boq = await self.get_boq(position.boq_id)
                    project_id = boq.project_id
                except Exception:  # noqa: BLE001 - best-effort
                    project_id = None
                await self.log_activity(
                    user_id=actor_id,
                    action="position.updated",
                    target_type="position",
                    description=f"Updated position {position.ordinal}",
                    project_id=project_id,
                    boq_id=position.boq_id,
                    target_id=position.id,
                    changes=changes_diff,
                    metadata_={"version": int(position.version or 0)},
                )
            except Exception:  # noqa: BLE001 - best-effort, never break PATCH
                logger.debug("Activity-log write for position.updated failed", exc_info=True)

        # ── Issue #133: master resource definition edit → propagate ──────
        # If the patch changed a coded resource the editor owns the master
        # definition for, fan the changed DEFINITION fields out to every
        # other position's resource sharing that code (never the quantity,
        # never a user-diverged instance). Mirrors the #127 contract.
        _resource_propagated = 0
        if (
            # ``metadata`` is renamed to ``metadata_`` earlier in this
            # method (the column writer expects the mapped attribute name),
            # so accept either spelling here.
            ("metadata" in fields or "metadata_" in fields)
            and not _did_unlink_instance
            and isinstance(position.metadata_, dict)
        ):
            _res_after_raw = position.metadata_.get("resources")
            if isinstance(_res_after_raw, list):
                # Snapshot the after-state into a plain list NOW - the
                # propagation helper runs per-instance ``update_fields``
                # (expire_all) and the async engine cannot lazy-refresh
                # ``position.metadata_`` afterwards (MissingGreenlet).
                _res_after = [dict(r) if isinstance(r, dict) else r for r in _res_after_raw]
                _res_delta = self._resource_def_changed(_res_before, _res_after)
                if _res_delta:
                    _resource_propagated = await self._propagate_resource_definitions(
                        editor_position=position,
                        changed_by_code=_res_delta,
                        actor_id=actor_id,
                    )
                    # Per-instance writes above expired ``position``;
                    # re-hydrate it so the response serialisation
                    # (``_position_to_response_with_links``) reads live
                    # attributes, not lazy-loads → MissingGreenlet.
                    if _resource_propagated:
                        try:
                            await self.session.refresh(position)
                        except Exception:  # noqa: BLE001 - best-effort
                            logger.debug(
                                "Refresh after resource propagation failed",
                                exc_info=True,
                            )

        # ── Issue #127/#133: surface the link outcome on the response ────
        # Stashed on a NON-mapped attribute so the request-session commit
        # in ``get_session`` never persists it (mutating the mapped
        # ``metadata_`` column here would flush the transient key into the
        # DB). The router merges it into the response metadata.
        if _propagated_count or _did_unlink_instance or _resource_propagated:
            try:
                position._link_propagation_info = {  # type: ignore[attr-defined]
                    "propagated_to": _propagated_count,
                    "unlinked": _did_unlink_instance,
                    "resource_propagated_to": _resource_propagated,
                }
            except Exception:  # noqa: BLE001 - purely cosmetic
                pass

        # ── Issue #157 (skolodi): surface missing-FX warnings ────────────
        # Detect resources priced in a currency the project has no rate
        # for. Silent no-op at ``_resource_total_in_base`` makes the bug
        # invisible (section sum unchanged → user reports "EUR→USD didn't
        # update"). Stash on a NON-mapped attribute; router merges into
        # response metadata as ``fx_warnings: list[str]``.
        try:
            meta_now = position.metadata_ if isinstance(position.metadata_, dict) else {}
            resources_now = meta_now.get("resources") if isinstance(meta_now, dict) else None
            # Reuse the FX table already resolved for the unit_rate derivation
            # when available, so a single update issues at most one FX lookup.
            if _fx_map is not None and _fx_base_ccy is not None:
                base_ccy, fx_map = _fx_base_ccy, _fx_map
            else:
                base_ccy, fx_map = await self._resolve_project_fx(position.boq_id)
            fx_warnings = _detect_resource_fx_warnings(
                resources_now if isinstance(resources_now, list) else None,
                fx_map,
                base_ccy,
            )
            if fx_warnings:
                position._fx_warnings = fx_warnings  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - warning is best-effort
            logger.debug("FX warning detection failed", exc_info=True)

        return position

    # ── v3.12.0 Stream A - bulk update & per-field restore ───────────────────

    async def bulk_update_positions(
        self,
        boq_id: uuid.UUID,
        payload: BulkPositionUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> BulkUpdateResult:
        """Apply one of three bulk mutations to many positions atomically.

        See :class:`BulkPositionUpdate` for the payload contract. Each
        referenced position is loaded, its membership in ``boq_id`` is
        verified, and the per-row :meth:`update_position` is invoked so
        every downstream invariant fires (total recompute, validation
        reset, optimistic concurrency bump, master-propagation, audit
        log). Failed rows are collected and returned in
        :class:`BulkUpdateResult.failed_ids`; the umbrella action is
        always logged so the bulk action shows in the activity feed
        even when some rows skipped.

        Args:
            boq_id: BOQ that every supplied position must belong to.
            payload: Validated bulk request.
            actor_id: User id to attribute the activity log to.

        Returns:
            :class:`BulkUpdateResult` with counts and the umbrella log id.

        Raises:
            HTTPException 409: BOQ is locked.
            HTTPException 404: Position id not found / not in BOQ.
        """
        boq = await self._ensure_not_locked(boq_id)

        updated = 0
        failed_ids: list[uuid.UUID] = []
        # Pre-load all positions in one pass to surface 404s early.
        # The membership check protects against cross-BOQ id smuggling.
        positions: dict[uuid.UUID, Position] = {}
        for pid in payload.ids:
            row = await self.position_repo.get_by_id(pid)
            if row is None or row.boq_id != boq_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Position {pid} not found in BOQ {boq_id}",
                )
            positions[pid] = row

        # Materialise the per-row PositionUpdate payload.
        for pid, row in positions.items():
            try:
                if payload.updates is not None:
                    update_data = PositionUpdate(**payload.updates)
                elif payload.rate_factor is not None:
                    current = _to_decimal(row.unit_rate, default=Decimal("0"))
                    new_rate = current * Decimal(str(payload.rate_factor))
                    # Pass Decimal directly - PositionUpdate.unit_rate is
                    # typed Decimal, so converting through float() would
                    # re-introduce binary-floating-point rounding on large
                    # rates (BUG-B-bulk-float).
                    update_data = PositionUpdate(unit_rate=_quantize_money(new_rate))
                else:
                    # quantity_factor branch (validator guarantees one is set)
                    current_q = _to_decimal(row.quantity, default=Decimal("0"))
                    new_q = current_q * Decimal(str(payload.quantity_factor))
                    # quantity field is typed float; use the string-encoded
                    # Decimal so the schema coercion path (_quantize_money_str)
                    # fires cleanly rather than going float → string → Decimal.
                    update_data = PositionUpdate(quantity=float(_quantize_money(new_q)))
                await self.update_position(pid, update_data, actor_id=actor_id)
                updated += 1
            except HTTPException:
                failed_ids.append(pid)
            except ValueError:
                # Cap overflow / validation - skip the row but keep going.
                failed_ids.append(pid)

        log_id: uuid.UUID | None = None
        if actor_id is not None:
            try:
                kind = (
                    "updates"
                    if payload.updates is not None
                    else "rate_factor"
                    if payload.rate_factor is not None
                    else "quantity_factor"
                )
                entry = await self.log_activity(
                    user_id=actor_id,
                    action=f"position.bulk_{kind}",
                    target_type="boq",
                    description=(f"Bulk {kind} on {updated} position(s) (skipped {len(failed_ids)})"),
                    project_id=boq.project_id,
                    boq_id=boq_id,
                    target_id=None,
                    changes={
                        "ids": [str(i) for i in payload.ids],
                        "failed_ids": [str(i) for i in failed_ids],
                        "kind": kind,
                        "updates": payload.updates,
                        "rate_factor": payload.rate_factor,
                        "quantity_factor": payload.quantity_factor,
                    },
                )
                log_id = entry.id
            except Exception:  # noqa: BLE001 - never break the bulk return
                logger.debug("Bulk-update umbrella log failed", exc_info=True)

        return BulkUpdateResult(
            updated=updated,
            skipped=len(failed_ids),
            failed_ids=failed_ids,
            log_id=log_id,
        )

    async def restore_position_field(
        self,
        position_id: uuid.UUID,
        *,
        field: str,
        value: Any,
        log_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> Position:
        """Restore a single field on a position from a prior log entry.

        Reads the source :class:`BOQActivityLog`, asserts the entry
        targets this position and recorded a change for ``field``, then
        delegates to :meth:`update_position` so every invariant fires.
        A fresh log entry is appended noting which source entry was
        replayed (so the restore chain is itself auditable).

        Args:
            position_id: Position to mutate.
            field: Position attribute to restore (must be a column the
                normal :class:`PositionUpdate` schema accepts).
            value: New value (typically the ``old`` side of the diff).
            log_id: The BOQActivityLog entry being replayed.
            actor_id: Caller id (required for the new audit row).

        Returns:
            Updated position.

        Raises:
            HTTPException 404: position or source log not found.
            HTTPException 422: field is not restorable / log mismatch.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.position_not_found", locale=get_locale()),
            )
        await self._ensure_not_locked(position.boq_id)

        source: BOQActivityLog | None = await self.session.get(BOQActivityLog, log_id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Activity log entry {log_id} not found",
            )
        if source.target_id != position_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"Log entry {log_id} targets a different position ({source.target_id})"),
            )
        changes = source.changes if isinstance(source.changes, dict) else {}
        if field not in changes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Field '{field}' has no recorded change in log entry "
                    f"{log_id}. Available fields: {sorted(changes.keys())}"
                ),
            )

        # Build a single-key PositionUpdate. Float fields need numeric
        # coercion so a stringified '12.5' still validates cleanly.
        payload_kwargs: dict[str, Any] = {}
        if field in {"quantity", "unit_rate", "confidence"}:
            try:
                payload_kwargs[field] = None if value is None or value == "" else float(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot coerce {field}={value!r} to float",
                ) from exc
        elif field in {"classification", "metadata", "cad_element_ids"}:
            payload_kwargs[field] = value
        else:
            payload_kwargs[field] = None if value is None else str(value)

        try:
            update_data = PositionUpdate(**payload_kwargs)
        except Exception as exc:  # noqa: BLE001 - schema rejections → 422
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"Cannot restore field '{field}': {exc!s}"),
            ) from exc

        updated = await self.update_position(position_id, update_data, actor_id=actor_id)

        # Standalone audit row so the restore itself is greppable in the
        # activity feed (``update_position`` already wrote a generic
        # ``position.updated`` row; this adds context).
        if actor_id is not None:
            try:
                boq = await self.get_boq(position.boq_id)
                await self.log_activity(
                    user_id=actor_id,
                    action="position.field_restored",
                    target_type="position",
                    description=(f"Restored field '{field}' on position {updated.ordinal} from log {log_id}"),
                    project_id=boq.project_id,
                    boq_id=position.boq_id,
                    target_id=position_id,
                    changes={
                        "field": field,
                        "restored_value": _coerce_audit_value(value),
                        "source_log_id": str(log_id),
                    },
                )
            except Exception:  # noqa: BLE001
                logger.debug("Field-restore audit row failed", exc_info=True)

        return updated

    async def repick_resource_variant(
        self,
        position_id: uuid.UUID,
        resource_idx: int,
        variant_code: str,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Position:
        """Swap the chosen variant on an already-added resource entry.

        Looks up ``metadata.resources[resource_idx].available_variants`` (cached
        at apply-time by the frontend), finds the entry whose ``label`` matches
        ``variant_code``, then patches that resource's ``unit_rate`` + ``variant``
        marker. The variant_snapshot is re-stamped via
        ``_stamp_resource_variant_snapshots`` so the immutability contract from
        v2.6.25 is preserved. Other resources on the same position are left
        untouched (their snapshots retain their original ``captured_at``).

        Args:
            position_id: Target position identifier.
            resource_idx: 0-based index into ``metadata.resources``.
            variant_code: Label string identifying the desired variant in the
                cached ``available_variants`` array.
            actor_id: Caller user-id for audit-log attribution.

        Returns:
            The updated Position with the new resource ``variant`` /
            ``variant_snapshot`` and recomputed ``unit_rate`` + ``total``.

        Raises:
            HTTPException 404: Position not found.
            HTTPException 409: BOQ is locked.
            HTTPException 422: ``resource_idx`` out of range, the resource
                has no cached ``available_variants``, or ``variant_code``
                does not exist in that array.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.position_not_found", locale=get_locale()),
            )
        await self._ensure_not_locked(position.boq_id)

        existing_meta = position.metadata_ if isinstance(position.metadata_, dict) else {}
        resources_raw = existing_meta.get("resources")
        if not isinstance(resources_raw, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Position has no resources to re-pick a variant for",
            )
        if resource_idx < 0 or resource_idx >= len(resources_raw):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"resource_idx {resource_idx} is out of range (position has {len(resources_raw)} resource(s))"),
            )

        # Deep-copy the resources so the in-memory ORM dict isn't mutated
        # before we explicitly persist it.
        resources: list[dict[str, Any]] = [dict(r) if isinstance(r, dict) else {} for r in resources_raw]
        target_resource = resources[resource_idx]
        if not isinstance(target_resource, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Resource at index {resource_idx} is malformed",
            )

        available = target_resource.get("available_variants")
        if not isinstance(available, list) or not available:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Resource has no cached variants to re-pick from. "
                    "Re-add the resource from the cost database to enable variant switching."
                ),
            )

        # Find the variant in the cached array by label (the human-readable
        # marker the frontend already uses as the variant identifier - see
        # ``CostVariant.label`` in ``frontend/src/features/costs/api.ts``).
        chosen: dict[str, Any] | None = None
        for v in available:
            if isinstance(v, dict) and str(v.get("label")) == variant_code:
                chosen = v
                break
        if chosen is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"variant_code '{variant_code}' not found in available_variants "
                    f"({len(available)} option(s) cached on this resource)"
                ),
            )

        try:
            new_price = float(chosen.get("price", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Selected variant has a malformed price",
            ) from exc

        try:
            chosen_index = int(chosen.get("index", 0) or 0)
        except (TypeError, ValueError):
            chosen_index = 0

        # Apply the new variant to the target resource. Drop any
        # ``variant_default`` marker - the user made an explicit pick.
        target_resource["variant"] = {
            "label": str(chosen.get("label", variant_code)),
            "price": new_price,
            "index": chosen_index,
        }
        target_resource.pop("variant_default", None)
        target_resource["unit_rate"] = new_price

        # Replace the resource's display name with the variant's full label
        # (``common_start + variable_part``) so the BOQ row + Resource Summary
        # reflect the concrete pick, not the abstract group description. Skip
        # the rewrite for pre-v2.6.30 cached variants that don't carry
        # ``full_label`` - preserves whatever name was stamped at apply-time.
        full_label = chosen.get("full_label")
        if isinstance(full_label, str) and full_label.strip():
            target_resource["name"] = full_label.strip()[:400]
        try:
            qty_val = float(target_resource.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            qty_val = 0.0
        target_resource["total"] = round(qty_val * new_price, 4)
        # Drop the old snapshot so ``_stamp_resource_variant_snapshots``
        # writes a fresh ``captured_at`` for the changed resource. Other
        # resources still carry their original snapshots and remain idempotent.
        target_resource.pop("variant_snapshot", None)

        # Build the merged metadata. We must preserve every other key on
        # the position's metadata (cost_item_id, currency, BIM links, ...)
        new_meta: dict[str, Any] = dict(existing_meta)
        new_meta["resources"] = resources

        currency_hint = new_meta.get("currency")
        position_currency = currency_hint if isinstance(currency_hint, str) else None

        # Re-stamp variant snapshots for every variant-bearing resource. The
        # idempotency guard inside the helper means resources whose pick is
        # unchanged keep their original ``captured_at``; only the row whose
        # ``variant_snapshot`` we just removed gets a fresh stamp.
        _stamp_resource_variant_snapshots(new_meta, position_currency=position_currency)

        # Recalculate the position-level unit_rate from per-unit resource
        # subtotals. Mirrors the convention in ``update_position``:
        #   unit_rate(position) = Σ(r.quantity × r.unit_rate)
        new_unit_rate = round(
            sum(
                (float(r.get("quantity", 0) or 0) * float(r.get("unit_rate", 0) or 0))
                for r in resources
                if isinstance(r, dict)
            ),
            4,
        )
        new_total = _compute_total(position.quantity, str(new_unit_rate))

        # Snapshot before for audit diff.
        before_meta = dict(position.metadata_) if isinstance(position.metadata_, dict) else {}
        before_unit_rate = position.unit_rate
        before_total = position.total

        try:
            await self.position_repo.update_fields(
                position_id,
                metadata_=new_meta,
                unit_rate=_quantize_money_str(str(new_unit_rate)),
                total=new_total,
                version=int(position.version or 0) + 1,
            )
            await self.session.flush()
            await self.session.refresh(position)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any DB failure as 422
            logger.exception(
                "repick_resource_variant DB write failed for %s[%s]",
                position_id,
                resource_idx,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Variant re-pick could not be applied. The position may have been "
                    f"modified concurrently - reload and retry. ({type(exc).__name__})"
                ),
            ) from exc

        await _safe_publish(
            "boq.position.updated",
            {
                "position_id": str(position.id),
                "boq_id": str(position.boq_id),
                "ordinal": position.ordinal,
                "changes": {
                    "metadata": {
                        "old": _coerce_audit_value(before_meta),
                        "new": _coerce_audit_value(new_meta),
                    },
                    "unit_rate": {
                        "old": _coerce_audit_value(before_unit_rate),
                        "new": _coerce_audit_value(position.unit_rate),
                    },
                    "total": {
                        "old": _coerce_audit_value(before_total),
                        "new": _coerce_audit_value(position.total),
                    },
                },
                "version": int(position.version or 0),
                "kind": "resource_variant_repick",
            },
            source_module="oe_boq",
        )

        if actor_id is not None:
            try:
                project_id: uuid.UUID | None = None
                try:
                    boq = await self.get_boq(position.boq_id)
                    project_id = boq.project_id
                except Exception:  # noqa: BLE001 - best-effort
                    project_id = None
                await self.log_activity(
                    user_id=actor_id,
                    action="position.resource_variant_repicked",
                    target_type="position",
                    description=(
                        f"Re-picked variant on resource[{resource_idx}] of "
                        f"position {position.ordinal} → '{variant_code}'"
                    ),
                    project_id=project_id,
                    boq_id=position.boq_id,
                    target_id=position.id,
                    metadata_={
                        "resource_idx": resource_idx,
                        "variant_code": variant_code,
                        "version": int(position.version or 0),
                    },
                )
            except Exception:  # noqa: BLE001 - best-effort, never break PATCH
                logger.debug("Activity-log write for resource_variant_repick failed", exc_info=True)

        return position

    async def delete_position(self, position_id: uuid.UUID, *, cascade: bool = False) -> None:
        """Delete a position.

        If the position is a section, children are orphaned via ``parent_id=NULL``
        by the database (``ondelete="SET NULL"``). Set ``cascade=True`` to also
        delete all descendant positions recursively - mirrors the UX contract
        users expect when deleting a section header.

        Raises:
            HTTPException 404: Position not found.
            HTTPException 409: BOQ is locked.
            HTTPException 409: Section has children and cascade=False.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.position_not_found", locale=get_locale()),
            )
        await self._ensure_not_locked(position.boq_id)

        boq_id = str(position.boq_id)
        deleted_position_ids: list[str] = [str(position_id)]

        # Section handling: collect and cascade-delete children so we don't
        # orphan positions with parent_id = NULL.
        if _is_section(position):
            children = await self.position_repo.list_children(position_id)
            if children and not cascade:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Section has {len(children)} child position(s). "
                        "Pass ?cascade=true to delete them together, or move them first."
                    ),
                )
            # Recursively collect descendant IDs for cascade delete
            to_visit = list(children)
            while to_visit:
                child = to_visit.pop()
                deleted_position_ids.append(str(child.id))
                grandchildren = await self.position_repo.list_children(child.id)
                to_visit.extend(grandchildren)

            # Delete in reverse (leaves first) to respect FK hierarchy
            for child_id_str in reversed(deleted_position_ids[1:]):
                await self.position_repo.delete(uuid.UUID(child_id_str))

        # ── Issue #127: deleting a master must not orphan its instances ──
        # Promote the oldest remaining instance to master; if it was the
        # last group member, dissolve the group (no dangling
        # link_group_id). Captured before the delete so the group query
        # still sees the soon-to-be-deleted row's group.
        _del_link_role = getattr(position, "link_role", None)
        _del_link_group = getattr(position, "link_group_id", None)
        # Capture the master's boq_id while ``position`` is still live - the
        # promotion below calls repo.update_fields() which runs
        # session.expire_all(); the async engine can't lazy-refresh expired
        # attributes (MissingGreenlet).
        _del_position_boq_id = position.boq_id
        _deleted_ids_set = set(deleted_position_ids)
        if _del_link_role == "master" and _del_link_group is not None:
            try:
                group = await self.position_repo.list_link_group(_del_link_group)
                # Survivors = group members not in the delete set (cascade
                # may have removed instances too).
                survivors = [p for p in group if str(p.id) not in _deleted_ids_set]
                if survivors:
                    # list_link_group is ordered oldest-first → promote head.
                    # Capture the id before the first update_fields()
                    # expires every ORM instance (incl. ``new_master``).
                    _promote_id = survivors[0].id
                    await self.position_repo.update_fields(_promote_id, link_role="master")
                    if len(survivors) == 1:
                        # Only one left - collapse to a standalone owner so
                        # we don't keep a one-member group around.
                        await self.position_repo.update_fields(
                            _promote_id,
                            link_role=None,
                            link_group_id=None,
                        )
                    logger.info(
                        "Promoted position %s to master of group %s (old master %s deleted)",
                        _promote_id,
                        _del_link_group,
                        position_id,
                    )
            except Exception:  # noqa: BLE001 - never block the delete
                logger.exception(
                    "Master-promotion failed for group %s on delete of %s",
                    _del_link_group,
                    position_id,
                )

        await self.position_repo.delete(position_id)

        # Clean up Activity references to deleted positions so the schedule
        # module doesn't retain dead IDs in Activity.boq_position_ids JSON arrays.
        if deleted_position_ids:
            await self._scrub_activity_position_refs(_del_position_boq_id, deleted_position_ids)

        for pid_str in deleted_position_ids:
            await _safe_publish(
                "boq.position.deleted",
                {"position_id": pid_str, "boq_id": boq_id},
                source_module="oe_boq",
            )

        logger.info(
            "Position deleted: %s from BOQ %s (cascade=%d descendants)",
            position_id,
            boq_id,
            len(deleted_position_ids) - 1,
        )

    async def _scrub_activity_position_refs(
        self,
        boq_id: uuid.UUID,
        deleted_position_ids: list[str],
    ) -> None:
        """Remove deleted position IDs from Activity.boq_position_ids JSON arrays.

        Schedule activities can link to BOQ positions via a JSON array of IDs;
        when those positions are deleted, the activity holds dangling references.
        This helper finds activities in the same project and scrubs the stale IDs.
        """
        try:
            from sqlalchemy import select, update

            from app.modules.boq.models import BOQ
            from app.modules.schedule.models import Activity, Schedule

            # Find all schedules in the same project as this BOQ
            boq_row = (await self.session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).first()
            if not boq_row:
                return
            project_id = boq_row[0]

            stmt = (
                select(Activity)
                .join(Schedule, Activity.schedule_id == Schedule.id)
                .where(Schedule.project_id == project_id)
            )
            activities = (await self.session.execute(stmt)).scalars().all()
            deleted_set = set(deleted_position_ids)
            updated_count = 0
            for act in activities:
                current = list(act.boq_position_ids or [])
                cleaned = [pid for pid in current if str(pid) not in deleted_set]
                if len(cleaned) != len(current):
                    await self.session.execute(
                        update(Activity).where(Activity.id == act.id).values(boq_position_ids=cleaned)
                    )
                    updated_count += 1
            if updated_count:
                logger.info(
                    "Scrubbed %d deleted position refs from %d activities (boq=%s)",
                    len(deleted_position_ids),
                    updated_count,
                    boq_id,
                )
        except Exception as exc:  # best-effort cleanup - never fail the parent delete
            logger.warning(
                "Failed to scrub activity position refs for boq=%s: %s",
                boq_id,
                exc,
            )

    async def reorder_positions(self, boq_id: uuid.UUID, position_ids: list[uuid.UUID]) -> None:
        """Reorder positions within a BOQ.

        Assigns sequential sort_order values based on the order of
        ``position_ids``.  The BOQ is verified to exist and not locked.

        Args:
            boq_id: The BOQ that owns the positions.
            position_ids: Ordered list of position UUIDs.

        Raises:
            HTTPException 404: If the BOQ does not exist.
            HTTPException 409: If the BOQ is locked.
        """
        await self._ensure_not_locked(boq_id)
        await self.position_repo.reorder(position_ids, boq_id)
        logger.info("Reordered %d positions in BOQ %s", len(position_ids), boq_id)

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
            HTTPException 409 if the BOQ is locked.
        """
        await self._ensure_not_locked(boq_id)

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

    async def update_markup(self, markup_id: uuid.UUID, data: MarkupUpdate) -> BOQMarkup:
        """Update a markup line.

        Args:
            markup_id: Target markup identifier.
            data: Partial update payload.

        Returns:
            Updated BOQMarkup.

        Raises:
            HTTPException 404 if markup not found.
            HTTPException 409 if the owning BOQ is locked.
        """
        markup = await self.markup_repo.get_by_id(markup_id)
        if markup is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found",
            )
        await self._ensure_not_locked(markup.boq_id)

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

        Raises HTTPException 404 if not found, 409 if BOQ is locked.
        """
        markup = await self.markup_repo.get_by_id(markup_id)
        if markup is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found",
            )
        await self._ensure_not_locked(markup.boq_id)

        boq_id = str(markup.boq_id)
        await self.markup_repo.delete(markup_id)

        await _safe_publish(
            "boq.markup.deleted",
            {"markup_id": str(markup_id), "boq_id": boq_id},
            source_module="oe_boq",
        )

        logger.info("Markup deleted: %s from BOQ %s", markup_id, boq_id)

    async def calculate_markups(self, boq_id: uuid.UUID) -> tuple[Decimal, list[tuple[BOQMarkup, Decimal]]]:
        """Compute markup amounts for a BOQ based on its direct cost.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            Tuple of (direct_cost, list of (markup, computed_amount)).
        """
        positions = await self.position_repo.list_all_for_boq(boq_id)
        markups = await self.markup_repo.list_for_boq(boq_id)

        # Direct cost: sum of totals for non-section items only, converted to
        # the project BASE currency so foreign-currency lines are not blended
        # into the base figure (FX-aware, consistent with get_boq_structured).
        # Best-effort FX: a lookup failure degrades to raw sums rather than a 500.
        base_ccy, fx_map = await self._resolve_project_fx(boq_id)
        direct_cost = Decimal("0")
        for pos in positions:
            if not _is_section(pos):
                direct_cost += _leaf_total_base_with_resources(pos, fx_map, base_ccy or "")

        calculated = _calculate_markup_amounts(direct_cost, markups)
        return direct_cost, calculated

    async def apply_default_markups(self, boq_id: uuid.UUID, region: str) -> list[BOQMarkup]:
        """Replace all markups on a BOQ with the default template for a region.

        Deletes existing markups and creates the standard set.

        Issue #89 - when the owning Project has ``default_vat_rate`` set,
        the seeded VAT/tax markup row uses that percentage instead of the
        regional template's default. Other markup rows (overhead, profit,
        contingency) keep their regional defaults.

        Args:
            boq_id: Target BOQ identifier.
            region: Region code - "DACH", "UK", "US", "RU", "GULF", or "DEFAULT".

        Returns:
            List of newly created BOQMarkup objects.

        Raises:
            HTTPException 404 if BOQ not found.
            HTTPException 409 if the BOQ is locked.
        """
        await self._ensure_not_locked(boq_id)

        # Look up template; fall back to DEFAULT
        region_key = region.upper()
        template = DEFAULT_MARKUP_TEMPLATES.get(region_key, DEFAULT_MARKUP_TEMPLATES["DEFAULT"])

        # Resolve the project's per-project VAT override, if any. Loaded
        # via the BOQ → Project chain so we don't need a project_id arg
        # (keeps backwards compat with the existing public signature).
        # ``default_vat_rate`` is a decimal-string percentage (e.g. ``"21"``).
        project_vat_override: str | None = None
        try:
            boq = await self.boq_repo.get_by_id(boq_id)
            if boq is not None and getattr(boq, "project_id", None):
                from app.modules.projects.repository import ProjectRepository

                project = await ProjectRepository(self.session).get_by_id(boq.project_id)
                if project is not None:
                    raw = getattr(project, "default_vat_rate", None)
                    if raw is not None and str(raw).strip() != "":
                        project_vat_override = str(raw).strip()
        except Exception:  # noqa: BLE001 - best-effort, never break seeding
            logger.debug("default_vat_rate lookup failed for boq %s", boq_id, exc_info=True)
            project_vat_override = None

        # Remove existing markups
        await self.markup_repo.delete_all_for_boq(boq_id)

        # Create new markups from template, swapping in the override on tax rows
        new_markups: list[BOQMarkup] = []
        for entry in template:
            percentage = str(entry["percentage"])
            is_tax_override = bool(project_vat_override) and entry.get("category") == "tax"
            if is_tax_override:
                percentage = project_vat_override  # type: ignore[assignment]
            markup = BOQMarkup(
                boq_id=boq_id,
                name=str(entry["name"]),
                markup_type=str(entry.get("markup_type", "percentage")),
                category=str(entry["category"]),
                percentage=percentage,
                fixed_amount=str(entry.get("fixed_amount", "0")),
                apply_to=str(entry.get("apply_to", "direct_cost")),
                sort_order=int(entry["sort_order"]),  # type: ignore[arg-type]
                is_active=True,
                metadata_={"vat_override": True} if is_tax_override else {},
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
        recomputed as Σ(resource.quantity × resource.unit_rate) - the
        per-unit norm convention shared with :meth:`update_position`. The
        position total is then ``position.quantity × unit_rate`` (BUG-B-004:
        the two paths previously disagreed by a factor of qty² - recalc used
        ``total = resource_sum × qty`` while ``unit_rate = resource_sum``, and
        also floored qty at 1.0).  Both now derive identical values for the
        same resources + quantity.

        Args:
            boq_id: The BOQ whose positions should be recalculated.

        Returns:
            Dict with ``updated``, ``skipped``, and ``total`` counts.
        """
        # Ensure the BOQ exists and is not locked
        await self._ensure_not_locked(boq_id)

        positions = await self.position_repo.list_all_for_boq(boq_id)

        # BUG-B-003: ``position_repo.update_fields`` calls
        # ``session.expire_all()`` on every invocation. If we read
        # ``pos.metadata_`` / ``pos.quantity`` lazily inside the loop, the
        # FIRST update expires every not-yet-processed ORM instance; the
        # next iteration's attribute access then triggers an implicit
        # async lazy-load outside the greenlet → MissingGreenlet → HTTP
        # 500 (only reproduced with ≥2 resource-loaded positions).
        # Snapshot every attribute we need BEFORE mutating anything so the
        # loop never touches an expired instance.
        snapshots: list[tuple[uuid.UUID, list[dict[str, Any]], str | None]] = []
        for pos in positions:
            meta = pos.metadata_ or {}
            resources = meta.get("resources") or []
            resources = [r for r in resources if isinstance(r, dict)]
            snapshots.append((pos.id, resources, pos.quantity))

        # Resolve the project FX table once so foreign-currency resources are
        # converted to the project BASE currency before summing, exactly as
        # ``update_position`` does. Best-effort: a lookup failure returns
        # ("", {}) so the derivation degrades to a raw sum rather than a 500.
        fx_base_ccy, fx_map = await self._resolve_project_fx(boq_id)

        updated = 0
        skipped = 0
        for pos_id, resources, pos_qty_raw in snapshots:
            if resources:
                # Per-unit norm: unit_rate = Σ(r.qty × r.rate in base), NO
                # division by position quantity (mirrors update_position).
                # Each resource is converted from its own currency to the
                # project base before summing so the stored rate never blends
                # currencies (Issue #88 / #157).
                new_unit_rate = _quantize_money_str(_resource_total_in_base(resources, fx_map, fx_base_ccy or ""))
                if _to_decimal(new_unit_rate) > 0:
                    new_total = _compute_total(pos_qty_raw, new_unit_rate)
                    await self.position_repo.update_fields(
                        pos_id,
                        unit_rate=new_unit_rate,
                        total=new_total,
                    )
                    updated += 1
                    continue
            skipped += 1

        await self.session.flush()
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

        # Copy positions - first pass: create all with old parent_id recorded
        positions = await self.position_repo.list_all_for_boq(boq_id)
        old_to_new: dict[uuid.UUID, uuid.UUID] = {}

        # Eagerly capture all attributes from source positions BEFORE any
        # flush/bulk_create that may expire the ORM objects (MissingGreenlet fix).
        captured_positions: list[dict] = []
        new_positions: list[Position] = []
        for pos in positions:
            pos_id = pos.id
            pos_parent_id = pos.parent_id
            pos_ordinal = pos.ordinal
            pos_description = pos.description
            pos_unit = pos.unit
            pos_quantity = pos.quantity
            pos_unit_rate = pos.unit_rate
            pos_total = pos.total
            pos_classification = dict(pos.classification) if pos.classification else {}
            pos_source = pos.source
            pos_confidence = pos.confidence
            pos_cad_element_ids = list(pos.cad_element_ids) if pos.cad_element_ids else []
            pos_metadata = dict(pos.metadata_) if pos.metadata_ else {}
            pos_sort_order = pos.sort_order
            # Preserve the reusable code (Issue #127) so a duplicated BOQ -
            # the canonical baseline→revision path via create-revision -
            # keeps a STABLE per-line identity. compare_boqs pairs lines by
            # ``reference_code`` first; without this every revision line
            # would look "added/removed" instead of "changed". The new BOQ
            # is its own scope, so copying the code can never collide. The
            # cross-position link group (link_group_id / link_role) is
            # DELIBERATELY NOT carried: a revision instance must not follow
            # the original BOQ's master definition.
            pos_reference_code = getattr(pos, "reference_code", None)

            captured_positions.append({"id": pos_id, "parent_id": pos_parent_id})

            new_pos = Position(
                boq_id=new_boq_id,
                parent_id=None,  # will be remapped after insert
                ordinal=pos_ordinal,
                description=pos_description,
                unit=pos_unit,
                quantity=pos_quantity,
                unit_rate=pos_unit_rate,
                total=pos_total,
                classification=pos_classification,
                source=pos_source,
                confidence=pos_confidence,
                cad_element_ids=pos_cad_element_ids,
                validation_status="pending",
                reference_code=pos_reference_code,
                metadata_=pos_metadata,
                sort_order=pos_sort_order,
            )
            new_positions.append(new_pos)

        created_positions = await self.position_repo.bulk_create(new_positions)

        # Build old→new ID mapping - eagerly capture new IDs before they expire
        new_ids: list[uuid.UUID] = [p.id for p in created_positions]
        for cap, new_id in zip(captured_positions, new_ids, strict=False):
            old_to_new[cap["id"]] = new_id

        # Second pass: remap parent_id references using captured data
        for cap, new_id in zip(captured_positions, new_ids, strict=False):
            if cap["parent_id"] is not None and cap["parent_id"] in old_to_new:
                await self.position_repo.update_fields(new_id, parent_id=old_to_new[cap["parent_id"]])

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
                detail=translate("errors.position_not_found", locale=get_locale()),
            )

        # Issue #127: a duplicate is a one-time clone - UNLINKED, with its
        # own fresh internal reference_code (no future propagation). It now
        # also deep-copies the source's child subtree via the shared
        # helper, and every cloned node gets a BOQ-unique ordinal so the
        # ordinal-uniqueness invariant (GAEB X83 + boq_quality) holds even
        # when the legacy ``<ordinal>.1`` collides.
        _base_ordinal = f"{source.ordinal}.1"
        if await self.position_repo.ordinal_exists(source.boq_id, _base_ordinal):
            _dup_ordinal = await self._next_free_ordinal(source.boq_id, source.ordinal)
        else:
            _dup_ordinal = _base_ordinal
        _project_id = await self.position_repo.project_id_for_boq(source.boq_id)
        _fresh_code = await self._resolve_create_reference_code(_project_id, None)
        new_position = await self._clone_subtree(
            source,
            boq_id=source.boq_id,
            new_parent_id=source.parent_id,
            ordinal=_dup_ordinal,
            quantity=source.quantity,
            link_group_id=None,
            link_role=None,
            reference_code=_fresh_code,
        )

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

    # ── Issue #127: explicit link management ──────────────────────────────

    async def unlink_position(
        self,
        position_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Position:
        """Detach a position from its reuse group without changing values.

        The position keeps its current definition + ``reference_code``
        (still referenceable) but stops following the master. If the
        position WAS the master, the oldest remaining instance is promoted
        (or the group dissolved when it was the last member) so no
        instance is ever orphaned.

        Raises:
            HTTPException 404: Position not found.
            HTTPException 409: BOQ is locked.
            HTTPException 422: Position is not part of a link group.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.position_not_found", locale=get_locale()),
            )
        await self._ensure_not_locked(position.boq_id)

        group_id = getattr(position, "link_group_id", None)
        role = getattr(position, "link_role", None)
        if group_id is None or role is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Position is not part of a linked-code group.",
            )

        # ``PositionRepository.update_fields`` ends with
        # ``session.expire_all()``, which expires EVERY ORM instance in this
        # unit of work - including ``position``. On the async engine a later
        # attribute read on the expired instance triggers an implicit lazy
        # refresh → MissingGreenlet → HTTP 500. Capture everything we need
        # BEFORE the first expiring write, then re-fetch a live instance
        # afterwards. (Same footgun already fixed in
        # _create_reused_position / update_position / delete_position; the
        # master-promotion path below is the one that 500'd on unlink.)
        _pos_version = int(getattr(position, "version", 0) or 0)
        _pos_boq_id = position.boq_id
        _pos_ordinal = position.ordinal
        _pos_ref_code = getattr(position, "reference_code", None)

        # If this is the master, promote a survivor first so instances
        # don't dangle.
        if role == "master":
            try:
                group = await self.position_repo.list_link_group(group_id)
                survivors = [p for p in group if p.id != position_id]
                if survivors:
                    new_master = survivors[0]
                    if len(survivors) == 1:
                        await self.position_repo.update_fields(new_master.id, link_role=None, link_group_id=None)
                    else:
                        await self.position_repo.update_fields(new_master.id, link_role="master")
            except Exception:  # noqa: BLE001 - never block the unlink
                logger.exception(
                    "Survivor-promotion failed unlinking master %s",
                    position_id,
                )

        await self.position_repo.update_fields(
            position_id,
            link_group_id=None,
            link_role=None,
            version=_pos_version + 1,
        )
        await self.session.flush()
        # ``position`` is expired/stale after the writes above - re-fetch a
        # live instance so the return value + router serialization
        # (``_position_to_response``) don't lazy-load on a dead instance.
        live_position = await self.position_repo.get_by_id(position_id)
        if live_position is not None:
            position = live_position

        await _safe_publish(
            "boq.position.updated",
            {
                "position_id": str(position_id),
                "boq_id": str(_pos_boq_id),
                "ordinal": _pos_ordinal,
                "changes": {"unlinked": True},
                "kind": "linked_position_unlinked",
            },
            source_module="oe_boq",
        )
        if actor_id is not None:
            try:
                _proj_id: uuid.UUID | None = None
                try:
                    _b = await self.get_boq(_pos_boq_id)
                    _proj_id = _b.project_id
                except Exception:  # noqa: BLE001
                    _proj_id = None
                await self.log_activity(
                    user_id=actor_id,
                    action="position.unlinked",
                    target_type="position",
                    description=(f"Unlinked position {_pos_ordinal} from code '{_pos_ref_code}'"),
                    project_id=_proj_id,
                    boq_id=_pos_boq_id,
                    target_id=position_id,
                    metadata_={"link_group_id": str(group_id)},
                )
            except Exception:  # noqa: BLE001 - best-effort
                logger.debug("Activity-log for unlink failed", exc_info=True)

        return position

    async def list_links(self, position_id: uuid.UUID) -> "PositionLinksResponse":
        """Return the reuse group for a position's ``reference_code``.

        Lists every position that shares the code across the WHOLE project
        (not just one BOQ), identifies the master, and reports counts. A
        standalone position (code used once) returns ``linked=False`` with
        itself as the only member.

        Raises:
            HTTPException 404: Position not found.
        """
        from app.modules.boq.schemas import (
            LinkedPositionInfo,
            PositionLinksResponse,
        )

        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.position_not_found", locale=get_locale()),
            )

        ref_code = getattr(position, "reference_code", None)
        group_id = getattr(position, "link_group_id", None)

        members_src: list[Position]
        master_id: uuid.UUID | None = None
        if group_id is not None:
            members_src = await self.position_repo.list_link_group(group_id)
            for m in members_src:
                if getattr(m, "link_role", None) == "master":
                    master_id = m.id
                    break
        else:
            # Standalone: the code may still be reused elsewhere in the
            # project under different (e.g. copy) rows - surface every row
            # in the project carrying the same code so the UI can show
            # "this code is used N times".
            project_id = await self.position_repo.project_id_for_boq(position.boq_id)
            if ref_code and project_id is not None:
                master = await self.position_repo.find_master_by_reference_code(project_id, ref_code)
                if master is not None and master.link_group_id is not None:
                    members_src = await self.position_repo.list_link_group(master.link_group_id)
                    group_id = master.link_group_id
                    for m in members_src:
                        if getattr(m, "link_role", None) == "master":
                            master_id = m.id
                            break
                else:
                    members_src = [position]
            else:
                members_src = [position]

        def _info(p: Position) -> LinkedPositionInfo:
            return LinkedPositionInfo(
                id=p.id,
                boq_id=p.boq_id,
                ordinal=p.ordinal,
                description=p.description,
                quantity=Decimal(str(_str_to_float(p.quantity))),
                total=Decimal(str(_str_to_float(p.total))),
                link_role=getattr(p, "link_role", None),
                is_master=(p.id == master_id),
            )

        members = [_info(p) for p in members_src]
        instance_count = sum(1 for p in members_src if getattr(p, "link_role", None) == "instance")
        return PositionLinksResponse(
            reference_code=ref_code,
            link_group_id=group_id,
            linked=len(members_src) > 1,
            master_id=master_id,
            total_count=len(members_src),
            instance_count=instance_count,
            members=members,
        )

    async def find_resource_by_code(
        self,
        project_id: uuid.UUID,
        code: str,
    ) -> ResourceCodeLookupResponse:
        """Find the first existing resource in a project that uses ``code``.

        Issue #133. Resource codes live in
        ``Position.metadata.resources[].code`` (JSON - no SQL column), so
        we scan every position of the project oldest-first and return the
        first match's reusable *definition* (name / type / unit /
        unit_rate / currency) plus where it was found. The quantity is
        deliberately excluded - it is always per-instance (same contract
        as #127 position reuse). Returns ``found=False`` when the code is
        unused anywhere in the project.
        """
        norm = (code or "").strip()
        if not norm:
            return ResourceCodeLookupResponse(found=False, code="")
        norm_cf = norm.casefold()

        positions = await self.position_repo.list_for_project(project_id)
        for pos in positions:
            meta = pos.metadata_ if isinstance(pos.metadata_, dict) else None
            if not meta:
                continue
            resources = meta.get("resources")
            if not isinstance(resources, list):
                continue
            for r in resources:
                if not isinstance(r, dict):
                    continue
                r_code = str(r.get("code") or "").strip()
                if not r_code or r_code.casefold() != norm_cf:
                    continue
                # Issue #133 - a coded resource imported from a catalogue /
                # variant / match flow often stores its human label under
                # ``description`` (or a composed variant name) with a blank
                # ``name``. Fall back through those, and finally to the code
                # itself, so the "insert existing" path always receives a
                # usable name and never silently drops the resource.
                _disp = (
                    str(r.get("name") or "").strip()
                    or str(r.get("description") or "").strip()
                    or str(r.get("resource_name") or "").strip()
                    or r_code
                )
                return ResourceCodeLookupResponse(
                    found=True,
                    code=r_code,
                    match=ResourceCodeMatch(
                        code=r_code,
                        name=_disp,
                        type=str(r.get("type") or ""),
                        unit=str(r.get("unit") or ""),
                        unit_rate=_str_to_float(r.get("unit_rate")),
                        currency=str(r.get("currency") or ""),
                        position_id=str(pos.id),
                        position_ordinal=str(pos.ordinal or ""),
                        position_description=str(pos.description or ""),
                    ),
                )
        return ResourceCodeLookupResponse(found=False, code=norm)

    @staticmethod
    def _resource_def_changed(
        before: list[dict[str, Any]] | None,
        after: list[dict[str, Any]] | None,
    ) -> dict[str, dict[str, Any]]:
        """Return ``{code: {field: new_value}}`` for resources whose
        DEFINITION fields changed between two ``metadata.resources`` lists.

        Issue #133. Only coded resources participate (a blank code is
        un-shareable). Quantity / total are intentionally excluded - they
        are per-instance and must never propagate. Matched positionally
        first (the common in-place edit), then by code so a re-order does
        not produce spurious diffs.
        """
        if not isinstance(after, list):
            return {}
        before_by_code: dict[str, dict[str, Any]] = {}
        for r in before or []:
            if isinstance(r, dict):
                c = str(r.get("code") or "").strip()
                if c:
                    before_by_code.setdefault(c, r)
        changed: dict[str, dict[str, Any]] = {}
        for idx, r in enumerate(after):
            if not isinstance(r, dict):
                continue
            code = str(r.get("code") or "").strip()
            if not code:
                continue
            prev: dict[str, Any] | None = None
            if (
                isinstance(before, list)
                and idx < len(before)
                and isinstance(before[idx], dict)
                and str(before[idx].get("code") or "").strip() == code
            ):
                prev = before[idx]
            else:
                prev = before_by_code.get(code)
            delta: dict[str, Any] = {}
            for f in _RESOURCE_DEFINITION_FIELDS:
                new_v = r.get(f)
                old_v = prev.get(f) if isinstance(prev, dict) else None
                if new_v != old_v:
                    delta[f] = new_v
            if delta:
                changed[code] = delta
        return changed

    async def _propagate_resource_definitions(
        self,
        *,
        editor_position: Position,
        changed_by_code: dict[str, dict[str, Any]],
        actor_id: uuid.UUID | None,
    ) -> int:
        """Issue #133 - fan a master resource's definition edit out to the
        linked resource instances across the project.

        ``editor_position`` is the just-saved position. For each changed
        resource ``code`` it only propagates when ``editor_position`` holds
        the MASTER definition (the OLDEST position carrying that code -
        same canonical rule as ``find_resource_by_code``). Other positions'
        resources with the same code receive the changed DEFINITION fields
        and have their ``total`` recomputed against THEIR OWN quantity
        (never the master's). A target resource the user explicitly
        diverged (``_code_overridden`` truthy) is left untouched and not
        re-linked silently (the architecture guide: AI-augmented, human-confirmed).

        Returns the number of resource instances updated. Best-effort -
        never raises (a propagation hiccup must not fail the user's PATCH).
        """
        if not changed_by_code:
            return 0
        try:
            project_id = await self.position_repo.project_id_for_boq(editor_position.boq_id)
            if project_id is None:
                return 0
            # Capture editor identity NOW - per-instance ``update_fields``
            # calls below run ``expire_all()`` and the async engine cannot
            # lazy-refresh ``editor_position`` afterwards (MissingGreenlet).
            editor_id = editor_position.id
            editor_boq_id = editor_position.boq_id
            # Resolve the project FX table once so each instance's derived
            # unit_rate converts foreign-currency resources into the project
            # BASE currency before summing, exactly as update_position and
            # recalculate_rates do (Issue #88 / #157). Best-effort: a lookup
            # failure returns ("", {}) so the rollup degrades to a raw sum
            # rather than blending currencies into the stored rate.
            fx_base_ccy, fx_map = await self._resolve_project_fx_by_project(project_id)
            # Oldest-first - the FIRST carrier of a code is its master.
            positions = await self.position_repo.list_for_project(project_id)

            # ── Snapshot EVERY position into plain values BEFORE any write.
            # ``position_repo.update_fields`` ends in ``session.expire_all()``
            # which expires every ORM instance in this unit of work; a later
            # attribute read on a not-yet-processed row would lazy-load on
            # the async engine → MissingGreenlet. (Same footgun + fix the
            # #127 propagation uses - see ``_grp_snap``.)
            snap: list[dict[str, Any]] = [
                {
                    "id": p.id,
                    "boq_id": p.boq_id,
                    "ordinal": p.ordinal,
                    "quantity": p.quantity,
                    "version": int(p.version or 0),
                    "meta": (dict(p.metadata_) if isinstance(p.metadata_, dict) else {}),
                }
                for p in positions
            ]

            def _has_code(meta: dict[str, Any], code: str) -> bool:
                res = meta.get("resources")
                if not isinstance(res, list):
                    return False
                return any(
                    isinstance(rr, dict) and str(rr.get("code") or "").strip().casefold() == code.casefold()
                    for rr in res
                )

            # Resolve which of the changed codes this editor actually owns
            # (it must be the OLDEST carrier - first in the snapshot order).
            owned_codes: set[str] = set()
            for code in changed_by_code:
                for s in snap:
                    if _has_code(s["meta"], code):
                        if s["id"] == editor_id:
                            owned_codes.add(code)
                        break  # first carrier decides ownership
            if not owned_codes:
                return 0
            owned_cf = {c.casefold() for c in owned_codes}

            updated = 0
            affected_boqs: set[uuid.UUID] = set()
            for s in snap:
                if s["id"] == editor_id:
                    continue
                meta = s["meta"]
                if not isinstance(meta, dict):
                    continue
                res_raw = meta.get("resources")
                if not isinstance(res_raw, list):
                    continue
                new_res: list[Any] = [dict(r) if isinstance(r, dict) else r for r in res_raw]
                touched = False
                for r in new_res:
                    if not isinstance(r, dict):
                        continue
                    rc = str(r.get("code") or "").strip()
                    if not rc or rc.casefold() not in owned_cf:
                        continue
                    # Honour an explicit user divergence - never silently
                    # overwrite an instance the user customised.
                    if r.get("_code_overridden"):
                        continue
                    delta = None
                    for c, d in changed_by_code.items():
                        if c.casefold() == rc.casefold():
                            delta = d
                            break
                    if not delta:
                        continue
                    for f, v in delta.items():
                        r[f] = v
                    # Recompute THIS resource's total against ITS OWN qty.
                    r_qty = _str_to_float(r.get("quantity"))
                    r_rate = _str_to_float(r.get("unit_rate"))
                    r["total"] = round(r_qty * r_rate, 2)
                    touched = True
                if not touched:
                    continue
                new_meta = dict(meta)
                new_meta["resources"] = new_res
                # Recompute the position's derived unit_rate from resources.
                # Each resource is converted from its own currency to the
                # project base via the FX table before summing, mirroring
                # update_position / recalculate_rates so this propagation path
                # never blends currencies into the stored rate (Issue #88 / #157).
                res_dicts = [r for r in new_res if isinstance(r, dict)]
                derived_rate = _quantize_money_str(_resource_total_in_base(res_dicts, fx_map, fx_base_ccy or ""))
                new_total = _compute_total(s["quantity"], derived_rate)
                await self.position_repo.update_fields(
                    s["id"],
                    metadata_=new_meta,
                    unit_rate=derived_rate,
                    total=new_total,
                    version=s["version"] + 1,
                )
                affected_boqs.add(s["boq_id"])
                updated += 1
                await _safe_publish(
                    "boq.position.updated",
                    {
                        "position_id": str(s["id"]),
                        "boq_id": str(s["boq_id"]),
                        "ordinal": s["ordinal"],
                        "changes": {"resource_code_propagation": sorted(owned_codes)},
                        "kind": "linked_resource_propagation",
                    },
                    source_module="oe_boq",
                )

            if updated:
                await self.session.flush()
                if actor_id is not None:
                    try:
                        await self.log_activity(
                            user_id=actor_id,
                            action="resource.linked_propagation",
                            target_type="position",
                            description=(
                                f"Propagated resource definition "
                                f"({', '.join(sorted(owned_codes))}) to "
                                f"{updated} linked instance(s)"
                            ),
                            project_id=project_id,
                            boq_id=editor_boq_id,
                            target_id=editor_id,
                            changes={
                                "codes": sorted(owned_codes),
                                "instance_count": updated,
                            },
                        )
                    except Exception:  # noqa: BLE001 - best-effort
                        logger.debug(
                            "Activity-log for resource propagation failed",
                            exc_info=True,
                        )
            return updated
        except Exception:  # noqa: BLE001 - never break the user's PATCH
            # ``editor_position`` may be expired here (a per-instance
            # ``update_fields`` ran ``expire_all()``); avoid touching it.
            logger.exception(
                "Resource-definition propagation failed (editor %s)",
                locals().get("editor_id", "?"),
            )
            return 0

    # ── Composite reads ───────────────────────────────────────────────────

    async def get_boq_with_positions(self, boq_id: uuid.UUID) -> BOQWithPositions:
        """Get a BOQ with all its positions and computed grand total.

        ``grand_total`` here matches the list-endpoint semantics: it includes
        active markups (BUG-008 - list returned 25830, detail returned 20500
        for the same BOQ; clients flipped between the two cosmically and lost
        trust).  ``direct_cost_total`` exposes the position-sum-only figure
        for clients that need the breakdown.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            BOQWithPositions including positions list and grand_total.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)
        positions = await self.position_repo.list_all_for_boq(boq_id)

        # Build position responses with float conversions
        position_responses = []
        direct_cost = Decimal("0")
        position_count = 0

        for pos in positions:
            position_responses.append(_build_position_response(pos))
            # Exclude section headers from totals + counts (sections have no unit)
            if not _is_section(pos):
                total_val = _str_to_float(pos.total)
                direct_cost += Decimal(str(total_val))
                position_count += 1

        # Apply active markups so detail matches the list endpoint
        # (``boq_repo.grand_totals_for_boqs`` does the same arithmetic
        #  for list-style responses; we share the result here).
        totals = await self.boq_repo.grand_totals_for_boqs([boq_id])
        grand_total_with_markups = Decimal(str(totals.get(boq_id, float(direct_cost))))
        markups_total = grand_total_with_markups - direct_cost

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
            # BUG-B-001 / BUG-B-012: cents-quantised (HALF_UP) so list and
            # detail return one canonical figure.
            direct_cost_total=_round_currency(direct_cost),
            markups_total=_round_currency(markups_total),
            grand_total=_round_currency(grand_total_with_markups),
            position_count=position_count,
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
        all_positions = await self.position_repo.list_all_for_boq(boq_id)

        # Issue #111 - resolve the project FX table once so foreign-currency
        # position totals convert into the base currency before they roll up
        # into section subtotals / Direct Cost / Grand Total. Without this the
        # export path (CSV/Excel/PDF all read get_boq_structured) summed
        # foreign totals as base - the exact defect #131 fixed in the grid.
        _fx_base, _fx_map = await self._resolve_project_fx(boq_id)

        def _leaf_total_base(pos: Position) -> Decimal:
            # Issue #111 (skolodi follow-up) - resource-currency-aware. A
            # position with USD-priced resources but no metadata.currency
            # must still convert into the base before it lands in the
            # section subtotal / direct cost / grand total.
            return _leaf_total_base_with_resources(pos, _fx_map, _fx_base)

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
                # Parent exists but is not a section - still group under parent
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

        # BUG-B-010: build a child-section adjacency map so a parent
        # section's subtotal rolls up nested sub-section costs (3-4+
        # levels). A section nested under another section lands in
        # ``section_map`` as its own entry but its parent never aggregated
        # it, so the parent reported subtotal 0 while the child held the
        # money - any UI summing top-level section subtotals understated
        # the BOQ.
        child_sections: dict[uuid.UUID, list[uuid.UUID]] = {}
        for sid, spos in section_map.items():
            parent = spos.parent_id
            if parent is not None and parent in section_map:
                child_sections.setdefault(parent, []).append(sid)

        # Own-leaf subtotal (direct, non-section children only).
        own_leaf_subtotal: dict[uuid.UUID, Decimal] = {}
        for sid in section_map:
            s = Decimal("0")
            for child in children_map.get(sid, []):
                if not _is_section(child):
                    s += _leaf_total_base(child)
            own_leaf_subtotal[sid] = s

        # Rolled subtotal = own leaves + every descendant section's leaves.
        # Iterative post-order with a visited guard so already-corrupt
        # parent cycles can't spin forever.
        _rolled_cache: dict[uuid.UUID, Decimal] = {}

        def _rolled(sid: uuid.UUID, _seen: set[uuid.UUID]) -> Decimal:
            if sid in _rolled_cache:
                return _rolled_cache[sid]
            if sid in _seen:
                return own_leaf_subtotal.get(sid, Decimal("0"))
            _seen.add(sid)
            total = own_leaf_subtotal.get(sid, Decimal("0"))
            for csid in child_sections.get(sid, []):
                total += _rolled(csid, _seen)
            _rolled_cache[sid] = total
            return total

        # Build section responses
        sections: list[SectionResponse] = []
        direct_cost = Decimal("0")

        for section_id, section_pos in section_map.items():
            child_responses: list[PositionResponse] = []
            for child in children_map.get(section_id, []):
                child_responses.append(_build_position_response(child))

            rolled = _rolled(section_id, set())
            sections.append(
                SectionResponse(
                    id=section_pos.id,
                    ordinal=section_pos.ordinal,
                    description=section_pos.description,
                    positions=child_responses,
                    subtotal=_round_currency(rolled),
                )
            )
            # direct_cost accumulates ONLY this section's own leaves so a
            # rolled parent subtotal does not double-count its children
            # (BUG-B-010 - grand total stays leaf-exact).
            direct_cost += own_leaf_subtotal[section_id]

        # Ungrouped items
        ungrouped_responses: list[PositionResponse] = []
        for pos in remaining_ungrouped:
            if not _is_section(pos):
                ungrouped_responses.append(_build_position_response(pos))
                direct_cost += _leaf_total_base(pos)

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
                    amount=_round_currency(amount),
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
            # BUG-B-001 / BUG-B-012: snap aggregates to cents (HALF_UP) so
            # the editor matches statistics / cost-breakdown / list.
            direct_cost=_round_currency(direct_cost),
            markups=markups_calculated,
            net_total=_round_currency(net_total),
            grand_total=_round_currency(net_total),
        )

    async def get_export_fx(
        self,
        boq_id: uuid.UUID,
    ) -> tuple[str, dict[str, str]]:
        """Public accessor for a BOQ project's ``(base_currency, fx_map)``.

        Issue #111 - the CSV / Excel exporters embed these frozen rates as
        an audit appendix so a downloaded BOQ records exactly which FX
        rates produced its base-currency totals (a later rate edit can't
        retroactively change a delivered tender).
        """
        return await self._resolve_project_fx(boq_id)

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
        all_positions = await self.position_repo.list_all_for_boq(boq_id)

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
                    # Derive the per-unit subtotal from quantity * unit_rate when
                    # both are present, so the breakdown self-heals after an
                    # inline resource edit that updated qty/rate but left a stale
                    # ``total`` behind. Fall back to the stored ``total`` only
                    # when the factors are missing.
                    res_qty = res.get("quantity")
                    res_rate = res.get("unit_rate")
                    if res_qty is not None and res_rate is not None:
                        res_total = (_str_to_float(res_qty)) * (_str_to_float(res_rate))
                    else:
                        res_total = float(res.get("total", 0) or 0)
                    if not math.isfinite(res_total):
                        res_total = 0.0

                    cat = self._normalize_resource_category(res_type)

                    # Scale the per-unit resource subtotal by the real
                    # position quantity. ``res.total`` is the PER-UNIT
                    # subtotal (r.quantity * r.unit_rate) and the position's
                    # authoritative total is pos.quantity * Σ(res.total), so
                    # scaling by ``pos_qty`` makes this branch sum to the same
                    # canonical direct cost as the stored ``pos.total`` summed
                    # everywhere else. Never substitute 1.0 for a legitimate
                    # fractional or zero quantity (that over-stated 0.5 m3 as
                    # 1.0 and reported a full subtotal for a 0-qty position).
                    scaled_cost = res_total * pos_qty

                    category_amounts[cat] = category_amounts.get(cat, 0.0) + scaled_cost
                    category_counts[cat] = category_counts.get(cat, 0) + 1

                    resource_totals[res_name] = resource_totals.get(res_name, 0.0) + scaled_cost
                    resource_types[res_name] = cat
                    resource_positions.setdefault(res_name, set()).add(pos.id)
            else:
                # Heuristic fallback - classify by description keywords (fast)
                cat = self._classify_position_category(pos.description)
                category_amounts[cat] = category_amounts.get(cat, 0.0) + pos_total
                category_counts[cat] = category_counts.get(cat, 0) + 1

                short_name = pos.description[:60] if pos.description else "Position"
                resource_totals[short_name] = resource_totals.get(short_name, 0.0) + pos_total
                resource_types[short_name] = cat
                resource_positions.setdefault(short_name, set()).add(pos.id)

        direct_cost_val = sum(category_amounts.values())

        # Build categories sorted by amount descending
        categories: list[CostBreakdownCategory] = []
        for cat, amount in sorted(category_amounts.items(), key=lambda x: x[1], reverse=True):
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
            markup_results = _calculate_markup_amounts(Decimal(str(direct_cost_val)), markups_orm)
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
        for name, total_cost in sorted(resource_totals.items(), key=lambda x: x[1], reverse=True)[:10]:
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
            # BUG-B-012: HALF_UP cents quantisation, consistent with the
            # other read endpoints' monetary rounding.
            grand_total=_round_currency(grand_total),
            direct_cost=_round_currency(direct_cost_val),
            categories=categories,
            markups=markup_lines,
            top_resources=top_resources,
        )

    # ── Statistics ─────────────────────────────────────────────────────

    async def get_statistics(self, boq_id: uuid.UUID) -> BOQStatisticsResponse:
        """Compute aggregated statistics for a BOQ.

        Returns position count, section count, direct cost, grand total,
        average unit rate, completion percentage, unit breakdown, source
        breakdown, and classification coverage.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            BOQStatisticsResponse with all computed metrics.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)
        all_positions = await self.position_repo.list_all_for_boq(boq_id)

        sections = [p for p in all_positions if _is_section(p)]
        items = [p for p in all_positions if not _is_section(p)]

        # Direct cost
        direct_cost = Decimal("0")
        unit_rates: list[float] = []
        unit_breakdown: dict[str, int] = {}
        source_breakdown: dict[str, int] = {}
        complete_count = 0
        classified_count = 0

        for pos in items:
            total_val = _str_to_float(pos.total)
            direct_cost += Decimal(str(total_val))

            rate = _str_to_float(pos.unit_rate)
            qty = _str_to_float(pos.quantity)
            if rate > 0:
                unit_rates.append(rate)
            if rate > 0 and qty > 0:
                complete_count += 1

            # Unit breakdown
            unit_key = (pos.unit or "").strip().lower() or "other"
            unit_breakdown[unit_key] = unit_breakdown.get(unit_key, 0) + 1

            # Source breakdown
            source_key = pos.source or "manual"
            source_breakdown[source_key] = source_breakdown.get(source_key, 0) + 1

            # Classification coverage
            if pos.classification and any(pos.classification.values()):
                classified_count += 1

        item_count = len(items)
        avg_rate = sum(unit_rates) / len(unit_rates) if unit_rates else 0.0
        completion_pct = (complete_count / item_count * 100.0) if item_count > 0 else 0.0
        classification_pct = (classified_count / item_count * 100.0) if item_count > 0 else 0.0

        # Grand total (direct cost + markups)
        markups_orm = await self.markup_repo.list_for_boq(boq_id)
        markup_results = _calculate_markup_amounts(direct_cost, markups_orm)
        markup_total = sum(amount for _, amount in markup_results)
        grand_total = float(direct_cost + markup_total)

        return BOQStatisticsResponse(
            boq_id=str(boq_id),
            boq_name=boq.name,
            status=boq.status,
            position_count=item_count,
            section_count=len(sections),
            # BUG-B-012: same HALF_UP cents quantisation as structured /
            # cost-breakdown / list so all read endpoints agree.
            direct_cost=_round_currency(direct_cost),
            grand_total=_round_currency(grand_total),
            avg_unit_rate=round(avg_rate, 2),
            completion_pct=round(completion_pct, 1),
            unit_breakdown=unit_breakdown,
            source_breakdown=source_breakdown,
            classification_coverage_pct=round(classification_pct, 1),
            created_at=boq.created_at,
            updated_at=boq.updated_at,
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
            "material",
            "materials",
            "mat",
            "baustoff",
            "baustoffe",
        ):
            return "material"
        if res_type in (
            "equipment",
            "plant",
            "machinery",
            "geraet",
            "maschine",
        ):
            return "equipment"
        if res_type in (
            "subcontractor",
            "sub",
            "nachunternehmer",
            "fremdleistung",
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
            "beton",
            "concrete",
            "stahl",
            "steel",
            "holz",
            "timber",
            "wood",
            "ziegel",
            "brick",
            "glas",
            "glass",
            "daemmung",
            "insulation",
            "fliesen",
            "tile",
            "putz",
            "plaster",
            "farbe",
            "paint",
            "rohr",
            "pipe",
            "kabel",
            "cable",
            "mortar",
            "kies",
            "gravel",
            "sand",
            "zement",
            "cement",
            "bitumen",
            "asphalt",
            "kupfer",
            "copper",
            "aluminium",
            "aluminum",
            "lieferung",
            "delivery",
            "material",
        )
        labor_keywords = (
            "montage",
            "installation",
            "verlegung",
            "laying",
            "einbau",
            "abbruch",
            "demolition",
            "aushub",
            "excavation",
            "erdarbeit",
            "earthwork",
            "schalung",
            "formwork",
            "bewehrung",
            "reinforcement",
            "anstrich",
            "painting",
            "labor",
            "labour",
            "arbeit",
            "work",
            "verlegen",
            "install",
            "mauern",
            "betonieren",
        )
        equipment_keywords = (
            "kran",
            "crane",
            "bagger",
            "excavator",
            "geruest",
            "scaffold",
            "equipment",
            "machine",
            "pump",
            "pumpe",
            "container",
            "transport",
            "miete",
            "rental",
            "hire",
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
    async def _lookup_cost_item_components(cost_repo: CostItemRepository, description: str) -> list[dict[str, Any]]:
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
            items, _, _ = await cost_repo.search(q=description, limit=1)
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
            position_count = sum(len(sec["positions"]) for sec in tpl["sections"])
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
                detail=f"Unknown template: {data.template_id}. Available: {', '.join(TEMPLATES.keys())}",
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

        entries, total = await self.activity_repo.list_for_boq(boq_id, offset=offset, limit=limit)
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
        entries, total = await self.activity_repo.list_for_project(project_id, offset=offset, limit=limit)
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

    async def get_estimate_classification(self, boq_id: uuid.UUID) -> EstimateClassificationResponse:
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
        all_positions = await self.position_repo.list_all_for_boq(boq_id)

        # Filter out section headers - only count real line items
        items = [p for p in all_positions if not _is_section(p)]
        total_positions = len(items)

        if total_positions == 0:
            return _build_classification(0, 0, 0, 0)

        # Count positions with non-zero unit rates
        positions_with_rates = sum(1 for p in items if _str_to_float(p.unit_rate) > 0)

        # "Resources" = has description AND quantity > 0 AND unit_rate > 0
        positions_with_resources = sum(
            1
            for p in items
            if (p.description or "").strip() and _str_to_float(p.quantity) > 0 and _str_to_float(p.unit_rate) > 0
        )

        # Positions with at least one classification code
        positions_with_classification = sum(1 for p in items if p.classification and any(p.classification.values()))

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

        stmt = select(BOQSnapshot).where(BOQSnapshot.boq_id == boq_id).order_by(BOQSnapshot.created_at.desc())
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
            positions_data.append(
                {
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
                }
            )

        # Serialize markups
        markups_data = []
        for m in boq.markups:
            markups_data.append(
                {
                    "name": m.name,
                    "markup_type": m.markup_type,
                    "category": m.category,
                    "percentage": m.percentage,
                    "fixed_amount": m.fixed_amount,
                    "apply_to": m.apply_to,
                    "sort_order": m.sort_order,
                    "is_active": m.is_active,
                }
            )

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

    async def restore_snapshot(self, boq_id: uuid.UUID, snapshot_id: uuid.UUID) -> BOQWithPositions:
        """Restore a BOQ to a previous snapshot state.

        Deletes all current positions and markups, then recreates them from
        the snapshot - including hierarchical parent_id relationships and
        markup lines.
        """
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select

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

        # Delete current positions AND markups
        await self.session.execute(sa_delete(Position).where(Position.boq_id == boq_id))
        await self.session.execute(sa_delete(BOQMarkup).where(BOQMarkup.boq_id == boq_id))
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

        # Note: snapshot parent_id values are the OLD UUIDs which we cannot
        # directly map to new positions. The section hierarchy is reconstructed
        # from ordinals by get_boq_structured, so explicit parent_id is not
        # strictly required for correct rendering.

        # Recreate markups from snapshot
        for mdata in data.get("markups", []):
            markup = BOQMarkup(
                boq_id=boq_id,
                name=mdata["name"],
                markup_type=mdata.get("markup_type", "percentage"),
                category=mdata.get("category", "overhead"),
                percentage=mdata.get("percentage", "0"),
                fixed_amount=mdata.get("fixed_amount", "0"),
                apply_to=mdata.get("apply_to", "direct_cost"),
                sort_order=mdata.get("sort_order", 0),
                is_active=mdata.get("is_active", True),
            )
            self.session.add(markup)

        await self.session.flush()
        return await self.get_boq_with_positions(boq_id)

    # ── Feature 1: live model→BOQ quantity links ──────────────────────────

    @staticmethod
    def _aggregate_quantities(
        values: list[Decimal],
        aggregation: str,
    ) -> Decimal:
        """Combine per-element quantities into one figure.

        Operates on the collected per-element ``Decimal`` values. ``count``
        is handled by the caller (it counts resolved elements, not parsed
        magnitudes) and never reaches this helper. An empty list always
        yields ``Decimal("0")`` so a link to vanished elements degrades to
        zero rather than raising.
        """
        if not values:
            return Decimal("0")
        if aggregation == "max":
            return max(values)
        if aggregation == "min":
            return min(values)
        if aggregation == "first":
            return values[0]
        # default + explicit "sum"
        return sum(values, Decimal("0"))

    async def _resolve_latest_model_id(self, model_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        """Walk the BIM model revision chain forward to its newest tip.

        When a model is re-imported the BIM Hub inserts a *new*
        :class:`BIMModel` row whose ``parent_model_id`` points at the
        prior version. To re-pull quantities we must compare against the
        latest version, so we follow ``parent_model_id`` links forward
        (child = row whose ``parent_model_id`` is the current node) until
        no successor exists. A visited guard prevents an infinite loop on
        a corrupt self-referential chain.

        Returns:
            ``(latest_model_id, latest_version)``. When the model has no
            successors this is the input model itself.
        """
        from app.modules.bim_hub.models import BIMModel

        current_id = model_id
        version = ""
        seen: set[uuid.UUID] = set()
        while current_id not in seen:
            seen.add(current_id)
            row = (await self.session.execute(select(BIMModel.version).where(BIMModel.id == current_id))).first()
            if row is not None and row[0]:
                version = str(row[0])
            successor = (
                await self.session.execute(
                    select(BIMModel.id)
                    .where(BIMModel.parent_model_id == current_id)
                    .order_by(BIMModel.created_at.desc())
                    .limit(1)
                )
            ).first()
            if successor is None:
                break
            current_id = successor[0]
        return current_id, version

    async def _compute_link_quantity(
        self,
        *,
        model_id: uuid.UUID,
        stable_ids: list[str],
        quantity_field: str,
        aggregation: str,
    ) -> tuple[Decimal, list[str], list[str]]:
        """Evaluate a link's extraction rule against current model elements.

        Reads the canonical ``quantities`` map off every bound element in
        the target model, projects ``quantity_field`` out of each, and
        aggregates. Elements that no longer exist (model revised away) or
        that lack the requested field are reported as ``missing`` so the
        caller can surface a precise review message.

        Takes plain primitives (NOT the ORM ``QuantityLink``) so callers
        can snapshot a link's scalar fields up front and stay correct
        across ``session.expire_all()`` boundaries - the same
        MissingGreenlet-avoidance pattern ``duplicate_boq`` uses.

        Args:
            model_id: The model to read elements from (callers pass the
                resolved *latest* version).
            stable_ids: Bound element ``stable_id``s, in order.
            quantity_field: Canonical quantity key to project per element.
            aggregation: One of sum / max / min / count / first.

        Returns:
            ``(aggregated_quantity, contributing_stable_ids, missing_ids)``.
        """
        from app.modules.bim_hub.repository import BIMElementRepository

        ids = list(stable_ids or [])
        elem_repo = BIMElementRepository(self.session)
        elements = await elem_repo.list_by_stable_ids(model_id, ids)
        by_sid = {e.stable_id: e for e in elements}

        values: list[Decimal] = []
        contributing: list[str] = []
        missing: list[str] = []
        for sid in ids:
            elem = by_sid.get(sid)
            if elem is None:
                missing.append(sid)
                continue
            quantities = elem.quantities if isinstance(elem.quantities, dict) else {}
            if aggregation == "count":
                # ``count`` does not need the field present - it counts
                # resolvable elements. Still record the contribution.
                contributing.append(sid)
                continue
            if quantity_field not in quantities:
                missing.append(sid)
                continue
            raw = quantities.get(quantity_field)
            values.append(_to_decimal(raw))
            contributing.append(sid)

        if aggregation == "count":
            # ``count`` is the number of RESOLVED elements (the classic
            # "number of doors" takeoff) - independent of any field value.
            aggregated = Decimal(len(contributing))
        else:
            aggregated = self._aggregate_quantities(values, aggregation)
        return aggregated, contributing, missing

    async def create_quantity_link(
        self,
        position_id: uuid.UUID,
        data: QuantityLinkCreate,
        *,
        created_by: uuid.UUID | None = None,
    ) -> QuantityLinkResponse:
        """Bind a position numeric field to a set of BIM model elements.

        Creating the link does NOT change the position quantity - it only
        records the extraction rule + provenance. Validates that the
        position and model exist and live in the same project so a link
        can never cross a tenancy boundary.

        Raises:
            HTTPException 404: position or model not found.
            HTTPException 400: model belongs to a different project.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.position_not_found", locale=get_locale()),
            )
        boq = await self.get_boq(position.boq_id)

        from app.modules.bim_hub.models import BIMModel

        model = (await self.session.execute(select(BIMModel).where(BIMModel.id == data.model_id))).scalar_one_or_none()
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BIM model not found")
        if model.project_id != boq.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Model belongs to a different project than the BOQ",
            )

        link = QuantityLink(
            position_id=position_id,
            boq_id=position.boq_id,
            model_id=data.model_id,
            element_stable_ids=list(data.element_stable_ids),
            quantity_field=data.quantity_field,
            target_field=data.target_field,
            aggregation=data.aggregation,
            status="active",
            source_model_version=str(model.version) if model.version else None,
            created_by=created_by,
            metadata_={},
        )
        link = await self.quantity_link_repo.create(link)
        await _safe_publish(
            "boq.quantity_link.created",
            {
                "link_id": str(link.id),
                "position_id": str(position_id),
                "model_id": str(data.model_id),
            },
        )
        return QuantityLinkResponse.model_validate(link)

    async def list_quantity_links(self, position_id: uuid.UUID) -> list[QuantityLinkResponse]:
        """List every quantity link bound to a single position."""
        links = await self.quantity_link_repo.list_for_position(position_id)
        return [QuantityLinkResponse.model_validate(link) for link in links]

    async def delete_quantity_link(self, link_id: uuid.UUID) -> None:
        """Delete a quantity link. Idempotent - 404s an unknown id.

        Deleting a link never touches the position quantity: the value
        the link last applied stays put, it just stops being tracked.
        """
        link = await self.quantity_link_repo.get_by_id(link_id)
        if link is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quantity link not found")
        await self.quantity_link_repo.delete(link_id)

    async def refresh_quantity_links(self, boq_id: uuid.UUID) -> QuantityLinkRefreshResponse:
        """Re-pull every link in a BOQ against the latest model version.

        For each link: resolve the model's newest revision, recompute the
        bound quantity via the extraction rule, and compare against the
        position's current stored value. Links whose computed value
        differs are flipped to ``stale`` (persisted) and surfaced in the
        review payload. NOTHING is written to the position here - applying
        the pull is an explicit, human-confirmed second step (the architecture guide
        §7).

        Returns:
            A review payload: per link the old/new/delta + the elements
            that contributed and any that went missing.
        """
        await self.get_boq(boq_id)  # 404 guard
        links = await self.quantity_link_repo.list_for_boq(boq_id)

        # Snapshot every link's scalar fields BEFORE the loop so the
        # subsequent ``update_fields`` (which calls ``session.expire_all``)
        # can never make a still-referenced ORM ``link`` lazy-load and
        # raise MissingGreenlet - the same pattern ``duplicate_boq`` uses.
        snapshots = [
            {
                "id": link.id,
                "position_id": link.position_id,
                "model_id": link.model_id,
                "element_stable_ids": list(link.element_stable_ids or []),
                "quantity_field": link.quantity_field,
                "target_field": link.target_field,
                "aggregation": link.aggregation,
                "source_model_version": link.source_model_version,
            }
            for link in links
        ]

        rows: list[QuantityLinkRefreshRow] = []
        stale_count = 0
        now_iso = datetime.now(UTC).isoformat()

        for snap in snapshots:
            position = await self.position_repo.get_by_id(snap["position_id"])
            if position is None:
                # Position deleted out from under the link - drop the link
                # so a refresh self-heals (CASCADE normally handles this;
                # belt-and-braces for any orphan).
                await self.quantity_link_repo.delete(snap["id"])
                continue

            latest_model_id, latest_version = await self._resolve_latest_model_id(snap["model_id"])
            new_qty, contributing, missing = await self._compute_link_quantity(
                model_id=latest_model_id,
                stable_ids=snap["element_stable_ids"],
                quantity_field=snap["quantity_field"],
                aggregation=snap["aggregation"],
            )
            old_qty = _to_decimal(position.quantity)
            new_qty_q = _to_decimal(_quantize_money_str(new_qty))
            delta = new_qty_q - old_qty
            changed = delta != 0

            if not contributing and missing:
                new_status = "broken"
                message = "No bound elements resolve in the latest model version"
            elif changed:
                new_status = "stale"
                message = "Source element quantities changed"
            else:
                new_status = "active"
                message = ""

            pos_ordinal = position.ordinal
            pos_description = position.description
            pos_unit = position.unit

            # Persist status + provenance of this probe (never the value).
            await self.quantity_link_repo.update_fields(
                snap["id"],
                status=new_status,
                last_pulled_at=now_iso,
                source_model_version=(latest_version or snap["source_model_version"]),
            )
            if new_status == "stale":
                stale_count += 1

            rows.append(
                QuantityLinkRefreshRow(
                    link_id=snap["id"],
                    position_id=snap["position_id"],
                    ordinal=pos_ordinal,
                    description=pos_description,
                    quantity_field=snap["quantity_field"],
                    target_field=snap["target_field"],
                    aggregation=snap["aggregation"],
                    unit=pos_unit,
                    old_quantity=_quantize_money_str(old_qty),
                    new_quantity=_quantize_money_str(new_qty_q),
                    delta=_quantize_money_str(delta),
                    changed=changed,
                    status=new_status,
                    contributing_elements=contributing,
                    missing_element_ids=missing,
                    message=message,
                )
            )

        return QuantityLinkRefreshResponse(
            boq_id=boq_id,
            checked=len(rows),
            stale=stale_count,
            rows=rows,
        )

    async def apply_quantity_links(
        self,
        boq_id: uuid.UUID,
        link_ids: list[uuid.UUID],
        *,
        applied_by: uuid.UUID | None = None,
    ) -> QuantityLinkApplyResponse:
        """Apply re-pulled quantities to the chosen positions (human gate).

        Only the links explicitly listed in ``link_ids`` are applied -
        this is the confirm step of the propose→review→apply contract.
        For each, the latest-model quantity is recomputed, written to the
        position's ``target_field`` (with ``total`` recomputed exactly via
        ``quantity * unit_rate``), and a provenance record is appended to
        ``position.metadata.model_quantity_pull`` so the figure's origin
        is auditable and never silently overwritten.

        Raises:
            HTTPException 404: BOQ not found.
            HTTPException 409: the BOQ is locked.
        """
        await self._ensure_not_locked(boq_id)
        # Snapshot link scalar fields up front so the per-iteration
        # ``update_fields`` (→ ``session.expire_all``) can never make a
        # still-referenced ORM ``link`` lazy-load and raise
        # MissingGreenlet (same pattern ``duplicate_boq`` uses).
        snap_by_id: dict[uuid.UUID, dict] = {
            link.id: {
                "id": link.id,
                "position_id": link.position_id,
                "model_id": link.model_id,
                "element_stable_ids": list(link.element_stable_ids or []),
                "quantity_field": link.quantity_field,
                "aggregation": link.aggregation,
                "source_model_version": link.source_model_version,
            }
            for link in await self.quantity_link_repo.list_for_boq(boq_id)
        }

        # v4.2.2 Round 2 Wave C: snapshot every bound position's scalar
        # state in ONE bulk query up front so the per-link loop doesn't
        # fan out into N ``get_by_id`` round-trips. We don't keep the ORM
        # instances live - the *first* ``update_fields`` call (either on
        # a position or its link) triggers ``session.expire_all()``,
        # which would render every cached instance lazy-load-prone. So
        # we copy the scalar fields the loop actually reads into plain
        # dicts (mirrors the link snapshot pattern above), then look up
        # by id without ever touching the ORM. The common case (each
        # link binds a distinct position, none mutated twice) costs ONE
        # bulk query total instead of N round-trips.
        position_ids_to_load: list[uuid.UUID] = []
        seen_position_ids: set[uuid.UUID] = set()
        for link_id in link_ids:
            snap = snap_by_id.get(link_id)
            if snap is None:
                continue
            pid = snap["position_id"]
            if pid in seen_position_ids:
                continue
            seen_position_ids.add(pid)
            position_ids_to_load.append(pid)
        pos_snap_by_id: dict[uuid.UUID, dict] = {
            p.id: {
                "id": p.id,
                "ordinal": p.ordinal,
                "quantity": p.quantity,
                "unit_rate": p.unit_rate,
                "metadata_": dict(p.metadata_ or {}),
            }
            for p in await self.position_repo.list_by_ids(position_ids_to_load)
        }
        # Tracks positions this batch already mutated - a later
        # iteration that touches the same position must re-read from DB
        # (the snapshot's ``quantity`` / ``metadata_`` are stale).
        mutated_position_ids: set[uuid.UUID] = set()

        results: list[QuantityLinkApplyResultRow] = []
        applied = 0
        skipped = 0
        now_iso = datetime.now(UTC).isoformat()

        for link_id in link_ids:
            snap = snap_by_id.get(link_id)
            if snap is None:
                skipped += 1
                results.append(
                    QuantityLinkApplyResultRow(
                        link_id=link_id,
                        position_id=link_id,  # placeholder; unknown link
                        ordinal="",
                        applied=False,
                        old_quantity="0",
                        new_quantity="0",
                        message="Link not found in this BOQ",
                    )
                )
                continue

            position_id = snap["position_id"]
            # Use the cached scalar snapshot unless this position was
            # already mutated in this batch (then its snapshot is stale)
            # or was never in the bulk fetch (concurrent delete race).
            position: Any
            if position_id in mutated_position_ids or position_id not in pos_snap_by_id:
                position = await self.position_repo.get_by_id(position_id)
            else:
                # SimpleNamespace gives ``position.ordinal`` / ``.quantity``
                # / ``.unit_rate`` / ``.metadata_`` attribute access that's
                # drop-in compatible with the ORM ``Position`` reads the
                # downstream code performs - no lazy loads possible.
                position = SimpleNamespace(**pos_snap_by_id[position_id])
            if position is None:
                skipped += 1
                results.append(
                    QuantityLinkApplyResultRow(
                        link_id=link_id,
                        position_id=snap["position_id"],
                        ordinal="",
                        applied=False,
                        old_quantity="0",
                        new_quantity="0",
                        message="Bound position no longer exists",
                    )
                )
                continue

            latest_model_id, latest_version = await self._resolve_latest_model_id(snap["model_id"])
            new_qty, contributing, missing = await self._compute_link_quantity(
                model_id=latest_model_id,
                stable_ids=snap["element_stable_ids"],
                quantity_field=snap["quantity_field"],
                aggregation=snap["aggregation"],
            )
            pos_ordinal = position.ordinal
            if not contributing and missing:
                skipped += 1
                results.append(
                    QuantityLinkApplyResultRow(
                        link_id=link_id,
                        position_id=snap["position_id"],
                        ordinal=pos_ordinal,
                        applied=False,
                        old_quantity=_quantize_money_str(position.quantity),
                        new_quantity=_quantize_money_str(new_qty),
                        message="No bound elements resolve - not applied",
                    )
                )
                continue

            old_qty_str = _quantize_money_str(position.quantity)
            new_qty_str = _quantize_money_str(new_qty)
            new_total = _compute_total(new_qty_str, position.unit_rate)

            # Append (never replace) a provenance record so the history of
            # model-driven pulls on this position is fully auditable.
            meta = dict(position.metadata_ or {})
            history = list(meta.get("model_quantity_pull_history") or [])
            provenance = {
                "link_id": str(snap["id"]),
                "model_id": str(snap["model_id"]),
                "resolved_model_id": str(latest_model_id),
                "model_version": latest_version,
                "quantity_field": snap["quantity_field"],
                "aggregation": snap["aggregation"],
                "element_stable_ids": list(snap["element_stable_ids"]),
                "contributing_elements": contributing,
                "missing_element_ids": missing,
                "old_quantity": old_qty_str,
                "new_quantity": new_qty_str,
                "applied_at": now_iso,
                "applied_by": str(applied_by) if applied_by else None,
            }
            history.append(provenance)
            meta["model_quantity_pull"] = provenance
            meta["model_quantity_pull_history"] = history

            await self.position_repo.update_fields(
                snap["position_id"],
                quantity=new_qty_str,
                total=new_total,
                metadata_=meta,
            )
            # update_fields → session.expire_all(); any later iteration
            # that touches this position must re-read from DB.
            mutated_position_ids.add(snap["position_id"])
            await self.quantity_link_repo.update_fields(
                snap["id"],
                status="active",
                last_applied_quantity=new_qty_str,
                last_applied_at=now_iso,
                applied_by=applied_by,
                source_model_version=(latest_version or snap["source_model_version"]),
            )
            applied += 1
            results.append(
                QuantityLinkApplyResultRow(
                    link_id=link_id,
                    position_id=snap["position_id"],
                    ordinal=pos_ordinal,
                    applied=True,
                    old_quantity=old_qty_str,
                    new_quantity=new_qty_str,
                    message="Applied",
                )
            )

        await _safe_publish(
            "boq.quantity_link.applied",
            {"boq_id": str(boq_id), "applied": applied, "skipped": skipped},
        )
        return QuantityLinkApplyResponse(
            boq_id=boq_id,
            applied=applied,
            skipped=skipped,
            results=results,
        )

    # ── Feature 2: estimate baseline / line-level comparison ──────────────

    async def compare_boqs(
        self,
        base_boq_id: uuid.UUID,
        other_boq_id: uuid.UUID,
    ) -> BOQCompareResponse:
        """Classify every line difference between two BOQs (pure read).

        Positions are paired by ``reference_code`` first (the stable reuse
        identity, Issue #127) then by ``ordinal``. Each pair is classified
        as ``qty_changed`` / ``rate_changed`` / ``changed`` / ``unchanged``;
        positions only in ``base`` are ``removed``, only in ``other`` are
        ``added``.

        Money is rebased into the project's base currency via the existing
        FX table (the same ``_resolve_project_fx`` /
        ``_position_total_in_base`` path the structured view + exports use)
        so a multi-currency estimate compares consistently. Section
        headers (no unit) are skipped - they carry no money.

        Raises:
            HTTPException 404: either BOQ not found.
        """
        base_boq = await self.get_boq(base_boq_id)
        other_boq = await self.get_boq(other_boq_id)

        base_positions = await self.position_repo.list_all_for_boq(base_boq_id)
        other_positions = await self.position_repo.list_all_for_boq(other_boq_id)

        # FX context for each side resolved independently - the two BOQs
        # may even sit in different projects (a baseline imported as a
        # standalone). Rebase each side with its own project's table.
        base_fx_ccy, base_fx_map = await self._resolve_project_fx(base_boq_id)
        other_fx_ccy, other_fx_map = await self._resolve_project_fx(other_boq_id)
        # The comparison currency is the BASE boq's project currency (the
        # baseline is the reference frame).
        compare_ccy = base_fx_ccy or other_fx_ccy

        def _match_key(pos: Position) -> str:
            rc = (getattr(pos, "reference_code", None) or "").strip()
            if rc:
                return f"rc:{rc}"
            return f"ord:{pos.ordinal.strip()}"

        def _index(positions: list[Position]) -> dict[str, Position]:
            out: dict[str, Position] = {}
            for p in positions:
                if _is_section(p):
                    continue
                key = _match_key(p)
                # First occurrence wins; a duplicate key is a data issue
                # (boq_quality flags it) - comparing the first is stable.
                out.setdefault(key, p)
            return out

        base_idx = _index(base_positions)
        other_idx = _index(other_positions)

        rows: list[ComparePositionRow] = []
        summary = CompareSummary(base_currency=compare_ccy)

        old_dc_base = Decimal("0")
        new_dc_base = Decimal("0")

        all_keys = list(dict.fromkeys([*base_idx.keys(), *other_idx.keys()]))
        for key in all_keys:
            b = base_idx.get(key)
            o = other_idx.get(key)

            if b is not None:
                # Issue #111 (skolodi) - resource-currency-aware so a
                # base-budget diff converts USD-resource positions too.
                b_total_base = _leaf_total_base_with_resources(b, base_fx_map, base_fx_ccy)
                old_dc_base += b_total_base
            else:
                b_total_base = Decimal("0")
            if o is not None:
                o_total_base = _leaf_total_base_with_resources(o, other_fx_map, other_fx_ccy)
                new_dc_base += o_total_base
            else:
                o_total_base = Decimal("0")

            if b is not None and o is None:
                summary.removed += 1
                rows.append(
                    ComparePositionRow(
                        change_type="removed",
                        match_key=key,
                        reference_code=getattr(b, "reference_code", None),
                        ordinal=b.ordinal,
                        description=b.description,
                        unit=b.unit,
                        old_quantity=_quantize_money_str(b.quantity),
                        old_unit_rate=_quantize_money_str(b.unit_rate),
                        old_total=_quantize_money_str(b.total),
                        old_total_base=_quantize_money_str(b_total_base),
                        currency=_position_currency(b),
                        total_delta_base=_quantize_money_str(-b_total_base),
                    )
                )
                continue

            if b is None and o is not None:
                summary.added += 1
                rows.append(
                    ComparePositionRow(
                        change_type="added",
                        match_key=key,
                        reference_code=getattr(o, "reference_code", None),
                        ordinal=o.ordinal,
                        description=o.description,
                        unit=o.unit,
                        new_quantity=_quantize_money_str(o.quantity),
                        new_unit_rate=_quantize_money_str(o.unit_rate),
                        new_total=_quantize_money_str(o.total),
                        new_total_base=_quantize_money_str(o_total_base),
                        currency=_position_currency(o),
                        total_delta_base=_quantize_money_str(o_total_base),
                    )
                )
                continue

            # Both present - classify what moved using exact Decimal.
            # (the add/remove branches above already ``continue``d, so
            # reaching here means both sides resolved a position).
            qty_changed = _to_decimal(b.quantity) != _to_decimal(o.quantity)
            rate_changed = _to_decimal(b.unit_rate) != _to_decimal(o.unit_rate)
            if qty_changed and rate_changed:
                change_type = "changed"
                summary.changed += 1
            elif qty_changed:
                change_type = "qty_changed"
                summary.qty_changed += 1
            elif rate_changed:
                change_type = "rate_changed"
                summary.rate_changed += 1
            else:
                change_type = "unchanged"
                summary.unchanged += 1

            rows.append(
                ComparePositionRow(
                    change_type=change_type,
                    match_key=key,
                    reference_code=getattr(o, "reference_code", None) or getattr(b, "reference_code", None),
                    ordinal=o.ordinal,
                    description=o.description,
                    unit=o.unit,
                    old_quantity=_quantize_money_str(b.quantity),
                    new_quantity=_quantize_money_str(o.quantity),
                    old_unit_rate=_quantize_money_str(b.unit_rate),
                    new_unit_rate=_quantize_money_str(o.unit_rate),
                    old_total=_quantize_money_str(b.total),
                    new_total=_quantize_money_str(o.total),
                    old_total_base=_quantize_money_str(b_total_base),
                    new_total_base=_quantize_money_str(o_total_base),
                    currency=_position_currency(o),
                    total_delta_base=_quantize_money_str(o_total_base - b_total_base),
                )
            )

        summary.old_direct_cost_base = _quantize_money_str(old_dc_base)
        summary.new_direct_cost_base = _quantize_money_str(new_dc_base)
        summary.direct_cost_delta_base = _quantize_money_str(new_dc_base - old_dc_base)

        return BOQCompareResponse(
            base_boq_id=base_boq_id,
            other_boq_id=other_boq_id,
            base_boq_name=base_boq.name,
            other_boq_name=other_boq.name,
            summary=summary,
            rows=rows,
        )

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
            project_standard: Target standard - "din276", "nrm", or "masterformat".

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
            suggestions.append(
                {
                    "standard": project_standard,
                    "code": code,
                    "label": code_labels.get(code, ""),
                    "confidence": confidence,
                }
            )

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
            unit_filtered = [m for m in matches if str(m.get("unit", "")).lower().strip() == unit_lower]
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

            rate_matches.append(
                {
                    "code": str(m.get("code", "")),
                    "description": str(m.get("description", "")),
                    "rate": round(rate, 2),
                    "region": str(m.get("region", "")),
                    "score": round(score, 4),
                }
            )

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

    async def check_anomalies(self, boq_id: uuid.UUID) -> dict[str, Any]:
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
                return await asyncio.to_thread(vector_search, all_vectors[idx], None, 10)
            except Exception:
                return []

        all_matches = await asyncio.gather(*[_search_one(i) for i in range(len(eligible))])

        def _percentile_val(data: list[float], pct: float) -> float:
            idx = pct / 100.0 * (len(data) - 1)
            lower = int(idx)
            upper = min(lower + 1, len(data) - 1)
            frac = idx - lower
            return data[lower] + frac * (data[upper] - data[lower])

        anomalies: list[dict[str, Any]] = []

        for pos, matches in zip(eligible, all_matches, strict=False):
            if not matches:
                continue

            # Filter by matching unit if possible
            if pos.unit:
                unit_lower = pos.unit.lower().strip()
                unit_filtered = [m for m in matches if str(m.get("unit", "")).lower().strip() == unit_lower]
                if unit_filtered:
                    matches = unit_filtered

            # Extract rates from matches
            rates = [float(m.get("rate", 0.0)) for m in matches if float(m.get("rate", 0.0)) > 0]

            if len(rates) < 2:
                continue

            sorted_rates = sorted(rates)

            p25 = round(_percentile_val(sorted_rates, 25), 2)
            median = round(_percentile_val(sorted_rates, 50), 2)
            p75 = round(_percentile_val(sorted_rates, 75), 2)

            if median <= 0:
                continue

            # BUG-B-011: ``pos.unit_rate`` is now an exact Decimal. This
            # anomaly heuristic mixes it with float market percentiles, so
            # cast to float locally - heuristic comparison does not need
            # sub-cent exactness (the exact value is preserved in storage
            # and in the JSON response).
            current_rate = float(pos.unit_rate)
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
                    f"Unit rate {current_rate:.2f} is more than 2x the market median {median:.2f}. Review recommended."
                )
            elif current_rate < 0.3 * median:
                severity = "warning"
                message = (
                    f"Unit rate {current_rate:.2f} is less than 30% of the "
                    f"market median {median:.2f}. Suspiciously low."
                )

            if severity:
                anomalies.append(
                    {
                        "position_id": str(pos.id),
                        "field": "unit_rate",
                        "current_value": round(current_rate, 2),
                        "market_range": market_range,
                        "severity": severity,
                        "message": message,
                        "suggestion": median,
                    }
                )

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
            raw_matches = await asyncio.to_thread(vector_search, vectors[0], region, min(limit * 2, 30))
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
            results.append(
                {
                    "id": str(m.get("id", "")),
                    "code": code,
                    "description": str(m.get("description", "")),
                    "unit": str(m.get("unit", "")),
                    "rate": round(float(m.get("rate", 0)), 2),
                    "region": str(m.get("region", "")),
                    "score": round(float(m.get("score", 0)), 4),
                    "classification": (db_item.classification or {}) if db_item else {},
                    "components": (db_item.components or []) if db_item else [],
                    "currency": (db_item.currency if db_item else "") or "",
                }
            )

        return {
            "results": results,
            "total_found": len(results),
            "query_embedding_ms": embed_ms,
            "search_ms": search_ms,
        }

    # ── LLM-powered AI features ──────────────────────────────────────────────

    async def _get_ai_client(self, user_id: str) -> tuple[str, str, str | None]:
        """Resolve AI provider, API key, and the user's model-id override.

        Returns:
            Tuple of (provider, api_key, model_override_or_none). The model
            override (Settings > AI) is honored so a provider like OpenRouter
            uses the model the user picked rather than a hardcoded default -
            issue #138.

        Raises:
            HTTPException 400: If no API key is configured.
        """
        import uuid as _uuid

        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository

        settings_repo = AISettingsRepository(self.session)
        uid = _uuid.UUID(user_id)
        settings = await settings_repo.get_by_user_id(uid)

        try:
            return resolve_provider_key_model(settings)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    async def _call_llm(self, user_id: str, system: str, prompt: str) -> tuple[str, str, int]:
        """Call LLM and return (raw_text, provider, tokens_used)."""
        from app.modules.ai.ai_client import call_ai

        provider, api_key, model_override = await self._get_ai_client(user_id)
        raw_text, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=system,
            prompt=prompt,
            max_tokens=2048,
            model=model_override,
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
            description=description,
            unit=unit,
            classification=cls_str,
        )

        raw_text, provider, tokens = await self._call_llm(
            user_id,
            with_locale(ENHANCE_DESCRIPTION_SYSTEM, locale),
            prompt,
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
        existing = "\n".join(f"  - {d}" for d in (existing_descriptions or [])[:30]) or "  (none)"

        prompt = SUGGEST_PREREQUISITES_PROMPT.format(
            description=description,
            unit=unit,
            classification=cls_str,
            existing_positions=existing,
        )

        raw_text, provider, tokens = await self._call_llm(
            user_id,
            with_locale(SUGGEST_PREREQUISITES_SYSTEM, locale),
            prompt,
        )
        parsed = extract_json(raw_text)

        if not isinstance(parsed, list):
            return {"suggestions": [], "model_used": provider, "tokens_used": tokens}

        suggestions = []
        for item in parsed[:8]:
            if not isinstance(item, dict):
                continue
            suggestions.append(
                {
                    "description": str(item.get("description", "")),
                    "unit": str(item.get("unit", "lsum")),
                    "typical_rate_eur": round(float(item.get("typical_rate_eur", 0)), 2),
                    "relationship": str(item.get("relationship", "companion")),
                    "reason": str(item.get("reason", "")),
                }
            )

        return {"suggestions": suggestions, "model_used": provider, "tokens_used": tokens}

    async def check_scope_completeness(
        self,
        user_id: str,
        boq_id: Any,
        project_type: str = "general",
        region: str = "",
        currency: str = "",
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
                "warnings": ["BOQ is empty - no positions to analyze."],
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
            user_id,
            with_locale(CHECK_SCOPE_SYSTEM, locale),
            prompt,
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
            missing.append(
                {
                    "description": str(item.get("description", "")),
                    "category": str(item.get("category", "")),
                    "priority": str(item.get("priority", "medium")),
                    "reason": str(item.get("reason", "")),
                    "estimated_rate": round(float(item.get("estimated_rate", 0)), 2),
                    "unit": str(item.get("unit", "lsum")),
                }
            )

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
        currency: str = "",
        base_year: int = 2023,
        target_year: int = 2026,
        region: str = "",
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
        from app.modules.boq.ai_prompts import (
            ESCALATE_RATE_PROMPT,
            ESCALATE_RATE_SYSTEM,
            with_locale,
        )

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
            user_id,
            with_locale(ESCALATE_RATE_SYSTEM, locale),
            prompt,
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

    # ── Project Intelligence (RFC 25) ──────────────────────────────────────

    # Project Intelligence widgets fire on every project page load and
    # iterate every position in Python. A 10K-position project is the
    # high end of realistic load; cap at 2× that so a runaway project
    # can't OOM the worker. Anything bigger is genuinely abusive and
    # the widgets degrade to "first 20K" which is still a useful Pareto.
    _PI_POSITION_CAP = 20_000

    async def _list_positions_for_project(self, project_id: uuid.UUID) -> list[Position]:
        """Return every non-section Position across all BOQs of a project.

        Capped at ``_PI_POSITION_CAP`` to bound memory use on the always-on
        Project Intelligence widgets.
        """
        from sqlalchemy import select as _select

        stmt = (
            _select(Position)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id)
            .where(Position.unit != "")
            .order_by(Position.sort_order, Position.ordinal)
            .limit(self._PI_POSITION_CAP)
        )
        rows = await self.session.execute(stmt)
        return list(rows.scalars().all())

    async def get_line_items(
        self,
        project_id: uuid.UUID,
        *,
        group: str = "cost",
        top_n: int = 20,
    ) -> list[dict[str, Any]]:
        """Top-N line items by cost for the Pareto widget (RFC 25)."""
        top_n = max(1, min(top_n, 200))
        positions = await self._list_positions_for_project(project_id)
        if not positions:
            return []

        aggregate = sum(_str_to_float(p.total) for p in positions) or 0.0
        sorted_positions = sorted(
            positions,
            key=lambda p: (-_str_to_float(p.total), p.ordinal or ""),
        )

        results: list[dict[str, Any]] = []
        for pos in sorted_positions[:top_n]:
            total = _str_to_float(pos.total)
            share = (total / aggregate) if aggregate > 0 else 0.0
            results.append(
                {
                    "position_id": str(pos.id),
                    "description": pos.description or "",
                    "unit": pos.unit,
                    "quantity": _str_to_float(pos.quantity),
                    "unit_rate": _str_to_float(pos.unit_rate),
                    "total_cost": round(total, 2),
                    "share_of_total": round(share, 6),
                }
            )
        return results

    async def get_cost_rollup(
        self,
        project_id: uuid.UUID,
        *,
        group_by: str = "din276",
    ) -> list[dict[str, Any]]:
        """Aggregate position totals by classification code (RFC 25)."""
        effective_key = "din276" if group_by == "cost_code" else group_by
        positions = await self._list_positions_for_project(project_id)
        if not positions:
            return []

        # Convert each position total to the project BASE currency before
        # bucketing so foreign-currency lines are not blended into the base
        # rollup (consistent with get_boq_structured). Best-effort FX: a
        # lookup failure degrades to raw sums rather than a 500.
        base_ccy, fx_map = await self._resolve_project_fx_by_project(project_id)

        buckets: dict[str, dict[str, Any]] = {}
        for pos in positions:
            classification = pos.classification or {}
            code = str(classification.get(effective_key) or "").strip()
            key = code or "(unclassified)"
            entry = buckets.setdefault(
                key,
                {"code": key, "label": key, "total": Decimal("0"), "position_count": 0},
            )
            entry["total"] += _leaf_total_base_with_resources(pos, fx_map, base_ccy or "")
            entry["position_count"] += 1

        rows = list(buckets.values())
        rows.sort(key=lambda r: (-r["total"], r["code"]))
        for row in rows:
            row["total"] = float(_round_currency(row["total"]))
        return rows

    async def get_anomalies(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Statistical anomaly detection for v1.9.1 (RFC 25)."""
        positions = await self._list_positions_for_project(project_id)
        if not positions:
            return []

        anomalies: list[dict[str, Any]] = []

        # format: missing / zero required fields
        for pos in positions:
            unit = pos.unit or ""
            qty = _str_to_float(pos.quantity)
            rate = _str_to_float(pos.unit_rate)
            missing: list[str] = []
            if not unit.strip():
                missing.append("unit")
            if qty <= 0:
                missing.append("quantity")
            if rate <= 0:
                missing.append("unit_rate")
            if missing:
                anomalies.append(
                    {
                        "position_id": str(pos.id),
                        "ordinal": pos.ordinal or "",
                        "description": pos.description or "",
                        "type": "format",
                        "severity": "error" if "unit_rate" in missing else "warning",
                        "detail": f"Missing or zero: {', '.join(missing)}",
                        "value": None,
                        "reference": None,
                    }
                )

        # outlier: z-score > 3 within classification group
        groups: dict[str, list[tuple[Position, float]]] = {}
        for pos in positions:
            rate = _str_to_float(pos.unit_rate)
            if rate <= 0:
                continue
            classification = pos.classification or {}
            group_key = (
                str(classification.get("din276") or "")
                or str(classification.get("masterformat") or "")
                or str(classification.get("nrm") or "")
                or "(unclassified)"
            )
            groups.setdefault(group_key, []).append((pos, rate))

        for _group_key, items in groups.items():
            if len(items) < 4:
                continue
            rates = [r for _, r in items]
            mean = sum(rates) / len(rates)
            variance = sum((r - mean) ** 2 for r in rates) / len(rates)
            stddev = variance**0.5
            if stddev <= 0:
                continue
            for pos, rate in items:
                z = (rate - mean) / stddev
                if abs(z) > 3.0:
                    anomalies.append(
                        {
                            "position_id": str(pos.id),
                            "ordinal": pos.ordinal or "",
                            "description": pos.description or "",
                            "type": "outlier",
                            "severity": "warning",
                            "detail": (f"Unit rate {rate:.2f} is {z:+.2f}\u03c3 from the group mean {mean:.2f}"),
                            "value": round(rate, 2),
                            "reference": round(mean, 2),
                        }
                    )

        # jump: > 2x median of immediate neighbours (within same BOQ)
        by_boq: dict[uuid.UUID, list[Position]] = {}
        for pos in positions:
            by_boq.setdefault(pos.boq_id, []).append(pos)

        for boq_positions in by_boq.values():
            ordered = sorted(boq_positions, key=lambda p: (p.sort_order, p.ordinal or ""))
            for idx, pos in enumerate(ordered):
                rate = _str_to_float(pos.unit_rate)
                if rate <= 0:
                    continue
                neighbours: list[float] = []
                for offset in (-2, -1, 1, 2):
                    n_idx = idx + offset
                    if 0 <= n_idx < len(ordered):
                        n_rate = _str_to_float(ordered[n_idx].unit_rate)
                        if n_rate > 0:
                            neighbours.append(n_rate)
                if len(neighbours) < 2:
                    continue
                neighbours.sort()
                mid = len(neighbours) // 2
                median = neighbours[mid] if len(neighbours) % 2 == 1 else (neighbours[mid - 1] + neighbours[mid]) / 2
                if median > 0 and rate > 2 * median:
                    anomalies.append(
                        {
                            "position_id": str(pos.id),
                            "ordinal": pos.ordinal or "",
                            "description": pos.description or "",
                            "type": "jump",
                            "severity": "warning",
                            "detail": (f"Unit rate {rate:.2f} exceeds 2x the neighbour median {median:.2f}"),
                            "value": round(rate, 2),
                            "reference": round(median, 2),
                        }
                    )

        return anomalies
