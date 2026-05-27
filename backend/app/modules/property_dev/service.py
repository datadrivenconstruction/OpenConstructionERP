"""‌⁠‍Property Development service — business logic + state machines.

Pure helpers (no DB / I/O) live at module top so tests can exercise them
directly. The :class:`PropertyDevService` orchestrates them against the
session + repositories.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.property_dev.models import (
    Block,
    Broker,
    Buyer,
    BuyerOption,
    BuyerOptionGroup,
    BuyerSelection,
    BuyerSelectionItem,
    CommissionAccrual,
    CommissionAgreement,
    ContractParty,
    Development,
    EscrowAccount,
    EscrowTransaction,
    Handover,
    HandoverDoc,
    HouseType,
    HouseTypeVariant,
    Instalment,
    Lead,
    PaymentSchedule,
    Phase,
    Plot,
    PriceMatrix,
    PropertyDevHouseType,
    Reservation,
    SalesContract,
    Snag,
    WarrantyClaim,
)
from app.modules.property_dev.repository import (
    BlockRepository,
    BrokerRepository,
    BuyerOptionGroupRepository,
    BuyerOptionRepository,
    BuyerPipelineQueries,
    BuyerRepository,
    BuyerSelectionItemRepository,
    BuyerSelectionRepository,
    CommissionAccrualRepository,
    CommissionAgreementRepository,
    ContractPartyRepository,
    DevelopmentRepository,
    EscrowAccountRepository,
    EscrowTransactionRepository,
    HandoverDocRepository,
    HandoverRepository,
    HouseTypeRepository,
    HouseTypeVariantRepository,
    InstalmentRepository,
    LeadRepository,
    PaymentScheduleRepository,
    PhaseRepository,
    PlotRepository,
    PriceListEntryRepository,
    PriceListRepository,
    PriceMatrixRepository,
    PricingRuleRepository,
    ReservationRepository,
    SalesContractRepository,
    SalesContractRevisionRepository,
    SnagRepository,
    WarrantyClaimRepository,
)
from app.modules.property_dev.schemas import (
    BuyerCancelRequest,
    BuyerContractRequest,
    BuyerCreate,
    BuyerOptionCreate,
    BuyerOptionGroupCreate,
    BuyerOptionGroupUpdate,
    BuyerOptionUpdate,
    BuyerSelectionCreate,
    BuyerSelectionItemCreate,
    BuyerSelectionUpdate,
    BuyerUpdate,
    ContractPartyCreate,
    ContractPartyUpdate,
    DevelopmentCreate,
    DevelopmentUpdate,
    HandoverCompleteRequest,
    HandoverCreate,
    HandoverDocCreate,
    HandoverDocUpdate,
    HandoverUpdate,
    HouseTypeCreate,
    HouseTypeUpdate,
    HouseTypeVariantCreate,
    HouseTypeVariantUpdate,
    InstalmentCreate,
    InstalmentMarkPaidRequest,
    InstalmentUpdate,
    InstalmentWaiveRequest,
    LeadConvertToReservationRequest,
    LeadCreate,
    LeadUpdate,
    PaymentScheduleCreate,
    PaymentScheduleUpdate,
    PlotCreate,
    PlotReserveRequest,
    PlotUpdate,
    PropertyDevHouseTypeCreate,
    PropertyDevHouseTypeUpdate,
    ReservationConvertToSpaRequest,
    ReservationCreate,
    ReservationUpdate,
    SalesContractCreate,
    SalesContractSendForSignatureRequest,
    SalesContractSignRequest,
    SalesContractUpdate,
    SnagCreate,
    SnagUpdate,
    WarrantyClaimCreate,
    WarrantyClaimUpdate,
)

logger = logging.getLogger(__name__)

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# ── State machines ──────────────────────────────────────────────────────


_PLOT_TRANSITIONS: dict[str, set[str]] = {
    # ``held`` + ``blocked`` (task #142 — Inventory Map) are short-lived sales
    # statuses used by the bulk hold/release workflow. They can only be
    # entered from an "available" plot (``planned`` / ``ready``) and they
    # always release back to ``planned``. ``blocked`` is reserved for
    # admin-flagged plots (legal / structural defect) and cannot be moved
    # by the bulk-release endpoint — only an explicit PATCH lifts it.
    "planned": {"reserved", "under_construction", "ready", "held", "blocked"},
    "reserved": {"planned", "under_construction", "ready", "sold"},
    "under_construction": {"ready", "reserved"},
    "ready": {"reserved", "sold", "under_construction", "held", "blocked"},
    "sold": {"handed_over"},
    "handed_over": set(),
    "held": {"planned"},
    "blocked": {"planned"},
}

_BUYER_TRANSITIONS: dict[str, set[str]] = {
    "lead": {"reserved", "cancelled"},
    "reserved": {"contracted", "cancelled", "lead"},
    "contracted": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

_SELECTION_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"locked", "draft", "cancelled"},
    "locked": {"cancelled"},
    "cancelled": set(),
}

_HANDOVER_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "scheduled", "cancelled"},
    "completed": set(),
    "cancelled": {"scheduled"},
}

_WARRANTY_TRANSITIONS: dict[str, set[str]] = {
    # ``raised`` may be triaged into ``under_review`` or accepted /
    # rejected straight away — the UI's Accept / Reject buttons on a
    # raised claim shortcut the triage step (v3113 — was blocking the
    # WarrantyTab Accept button).
    "raised": {"under_review", "accepted", "rejected", "closed"},
    "under_review": {"accepted", "rejected", "closed"},
    "accepted": {"closed"},
    "rejected": {"closed"},
    "closed": set(),
}


# ── R6 FSMs ─────────────────────────────────────────────────────────────


_LEAD_TRANSITIONS: dict[str, set[str]] = {
    "new": {"qualified", "lost", "disqualified"},
    "qualified": {
        "viewing_scheduled",
        "quotation_sent",
        "negotiating",
        "lost",
        "disqualified",
    },
    "viewing_scheduled": {"visited", "lost", "disqualified"},
    "visited": {
        "quotation_sent",
        "negotiating",
        "converted",
        "lost",
        "disqualified",
    },
    "quotation_sent": {"negotiating", "converted", "lost"},
    "negotiating": {"quotation_sent", "converted", "lost"},
    "converted": set(),
    "lost": set(),
    "disqualified": set(),
}


_RESERVATION_TRANSITIONS: dict[str, set[str]] = {
    "active": {"converted", "expired", "cancelled", "refunded"},
    "converted": set(),
    "expired": {"refunded"},
    "cancelled": {"refunded"},
    "refunded": set(),
}


_SPA_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"sent_for_signature", "cancelled"},
    "sent_for_signature": {"partially_signed", "signed", "cancelled"},
    "partially_signed": {"signed", "cancelled"},
    "signed": {"countersigned", "cancelled"},
    "countersigned": {"registered", "cancelled"},
    "registered": set(),
    "cancelled": set(),
}


_PAYMENT_SCHEDULE_TRANSITIONS: dict[str, set[str]] = {
    "active": {"suspended", "completed", "cancelled"},
    "suspended": {"active", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


_INSTALMENT_TRANSITIONS: dict[str, set[str]] = {
    # Allow ``pending → paid`` directly so an early payment from the
    # buyer (before the demand-letter / "due" transition has fired)
    # doesn't 409. Real-world UX: the user marks paid the moment they
    # see funds — they shouldn't have to flip the row to ``due`` first.
    "pending": {"due", "paid", "waived", "cancelled"},
    "due": {"overdue", "paid", "waived", "cancelled"},
    "overdue": {"paid", "waived", "cancelled"},
    "paid": set(),
    "waived": set(),
    "cancelled": set(),
}


def allowed_lead_transitions(current: str) -> set[str]:
    """Return the set of next valid Lead statuses."""
    return set(_LEAD_TRANSITIONS.get(current, set()))


def allowed_reservation_transitions(current: str) -> set[str]:
    """Return the set of next valid Reservation statuses."""
    return set(_RESERVATION_TRANSITIONS.get(current, set()))


def allowed_spa_transitions(current: str) -> set[str]:
    """Return the set of next valid SalesContract statuses."""
    return set(_SPA_TRANSITIONS.get(current, set()))


def allowed_payment_schedule_transitions(current: str) -> set[str]:
    """Return the set of next valid PaymentSchedule statuses."""
    return set(_PAYMENT_SCHEDULE_TRANSITIONS.get(current, set()))


def allowed_instalment_transitions(current: str) -> set[str]:
    """Return the set of next valid Instalment statuses."""
    return set(_INSTALMENT_TRANSITIONS.get(current, set()))


def allowed_plot_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of next valid plot statuses."""
    return set(_PLOT_TRANSITIONS.get(current, set()))


def allowed_buyer_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of next valid buyer statuses."""
    return set(_BUYER_TRANSITIONS.get(current, set()))


def allowed_selection_transitions(current: str) -> set[str]:
    """Return the set of next valid buyer-selection statuses."""
    return set(_SELECTION_TRANSITIONS.get(current, set()))


def allowed_handover_transitions(current: str) -> set[str]:
    """Return the set of next valid handover progress states."""
    return set(_HANDOVER_TRANSITIONS.get(current, set()))


def allowed_warranty_transitions(current: str) -> set[str]:
    """Return the set of next valid warranty-claim statuses."""
    return set(_WARRANTY_TRANSITIONS.get(current, set()))


def _ensure_transition(
    name: str,
    current: str,
    target: str,
    allowed_fn,
) -> None:
    if target == current:
        return
    if target not in allowed_fn(current):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid {name} transition: {current} -> {target}",
        )


# ── Pure helpers ────────────────────────────────────────────────────────


def compute_freeze_deadline(handover_date: date, freeze_offset_days: int) -> date:
    """Return the date by which the buyer must lock their selection.

    Pure: no I/O. ``freeze_offset_days`` is subtracted from ``handover_date``.
    Negative offsets are clamped to 0.
    """
    if freeze_offset_days < 0:
        freeze_offset_days = 0
    return handover_date - timedelta(days=freeze_offset_days)


def compute_buyer_selection_total(items: Iterable[Any]) -> Decimal:
    """Sum ``quantity * unit_price_snapshot`` across items.

    Accepts ORM objects, dataclasses or dicts with the same attribute names.
    Pure: no DB.
    """
    total = Decimal("0")
    for item in items:
        qty = _attr(item, "quantity", 1)
        unit_price = _attr(item, "unit_price_snapshot", Decimal("0"))
        total += Decimal(str(qty)) * Decimal(str(unit_price))
    return total


def _attr(obj: Any, name: str, default: Any) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def validate_option_compatibility(
    selected_option_ids: Iterable[Any],
    all_options: Iterable[Any],
    rules: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Validate the buyer's selection against compatibility_rules.

    The rules live on each ``BuyerOption.compatibility_rules`` JSON column
    in the form::

        {"must_have": ["opt_code", ...], "must_not_have": ["opt_code", ...]}

    Args:
        selected_option_ids: Iterable of option ids the buyer picked.
        all_options: Iterable of option-like objects (must expose ``id``,
            ``code``, ``compatibility_rules``).
        rules: Optional explicit rules dict (overrides per-option rules
            when provided — handy for tests).

    Returns:
        ``(ok, violations)``: ``ok`` is False when any rule fails;
        ``violations`` is a human-readable message list.
    """
    by_id: dict[Any, Any] = {_attr(o, "id", None): o for o in all_options}
    selected_set = {oid for oid in selected_option_ids if oid in by_id}
    selected_codes = {_attr(by_id[oid], "code", "") for oid in selected_set}

    violations: list[str] = []

    if rules is not None:
        violations.extend(_check_rules(rules, selected_codes))
    else:
        for oid in selected_set:
            opt = by_id[oid]
            opt_rules = _attr(opt, "compatibility_rules", {}) or {}
            code = _attr(opt, "code", "")
            for msg in _check_rules(opt_rules, selected_codes, requester_code=code):
                violations.append(msg)

    return (not violations, violations)


def _check_rules(
    rules: dict[str, Any],
    selected_codes: set[str],
    requester_code: str | None = None,
) -> list[str]:
    out: list[str] = []
    must_have = rules.get("must_have") or []
    must_not_have = rules.get("must_not_have") or []
    prefix = f"{requester_code}: " if requester_code else ""
    for code in must_have:
        if code not in selected_codes:
            out.append(f"{prefix}requires '{code}'")
    for code in must_not_have:
        if code in selected_codes:
            out.append(f"{prefix}incompatible with '{code}'")
    return out


def compute_plot_final_price(
    plot: Any,
    variant: Any | None,
    selections: Iterable[Any],
) -> Decimal:
    """Return the buyer's all-in price for the plot.

    Formula:
        base + (base * modifier_pct / 100) + sum(selection.total_price)

    Pure: no DB.
    """
    base = Decimal(str(_attr(plot, "price_base", 0)))
    modifier_value = Decimal("0")
    if variant is not None:
        pct = Decimal(str(_attr(variant, "modifier_pct", 0)))
        modifier_value = base * pct / Decimal("100")
    selections_total = Decimal("0")
    for sel_item in selections:
        selections_total += Decimal(str(_attr(sel_item, "total_price", 0)))
    return base + modifier_value + selections_total


def can_modify_selection(buyer: Any, today: date) -> bool:
    """Return True if the buyer can still edit their option selection.

    Rules:
        - Buyer status must not be ``locked``/``cancelled``/``completed``.
        - Today must be strictly before ``buyer.freeze_deadline`` (if set).
    """
    buyer_status = _attr(buyer, "status", "lead")
    if buyer_status in {"cancelled", "completed"}:
        return False
    deadline = _attr(buyer, "freeze_deadline", None)
    if deadline is None:
        return True
    if isinstance(deadline, str):
        try:
            deadline = date.fromisoformat(deadline[:10])
        except (TypeError, ValueError):
            return True
    return today < deadline


def derive_plot_construction_progress(plot_id: uuid.UUID, work_packages: Iterable[dict[str, Any]]) -> Decimal:
    """Return overall construction % for a plot from a work-package list.

    Each work package is expected to be a dict with ``plot_id``, ``weight``
    (relative importance, default 1) and ``percent_complete`` (0-100).
    Pure: external schedulers feed in the packages.
    """
    weight_total = Decimal("0")
    weighted_progress = Decimal("0")
    for pkg in work_packages:
        if str(pkg.get("plot_id")) != str(plot_id):
            continue
        weight = Decimal(str(pkg.get("weight", 1)))
        pct = Decimal(str(pkg.get("percent_complete", 0)))
        weight_total += weight
        weighted_progress += weight * pct
    if weight_total == 0:
        return Decimal("0")
    return (weighted_progress / weight_total).quantize(Decimal("0.01"))


# ── Deposit forfeiture ──────────────────────────────────────────────────


# Each rule: (forfeit_fraction, citation, summary)
# fraction = Decimal between 0 and 1 representing the SHARE OF THE DEPOSIT
# kept by the developer. Fractions > 1 mean the developer must pay the
# buyer 2x deposit penalty (Spain LOE retraction at developer fault — but
# we model only buyer-initiated cancellations here; developer-side
# defaults are handled separately in the cancellation reason chain).
_DEPOSIT_FORFEITURE_RULES: dict[str, tuple[Decimal, str, str]] = {
    "GB": (
        Decimal("1.00"),
        "PRA CP21/22 + UK SRA Property Standards",
        "Buyer forfeits full deposit after exchange of contracts; "
        "before exchange — full refund (cooling-off period applies).",
    ),
    "IE": (
        Decimal("1.00"),
        "Law Society of Ireland — Standard Conditions of Sale 2023",
        "Buyer forfeits 10% deposit on rescission after binding contract.",
    ),
    "ES": (
        Decimal("1.00"),
        "Código Civil Art. 1454 — Arras Penitenciales",
        "Buyer loses full deposit on retraction; seller-default is "
        "2x deposit but is handled in seller-cancellation flow.",
    ),
    "PT": (
        Decimal("1.00"),
        "Código Civil Português Art. 442 — Sinal",
        "Buyer forfeits sinal (deposit) on contract rescission.",
    ),
    "AE": (
        Decimal("1.00"),
        "RERA Dubai Law No. (8) of 2007 — Article 11",
        "RERA escrow holds deposit; buyer forfeits full deposit on "
        "default after 30-day notice period if developer is not at fault.",
    ),
    "SA": (
        Decimal("1.00"),
        "Saudi Real Estate General Authority — Escrow Account Regs",
        "Buyer forfeits full deposit on default; seller delivers refund "
        "only when default is attributable to developer.",
    ),
    "US": (
        Decimal("1.00"),
        "Uniform Land Transactions Act (state-by-state)",
        "Earnest money typically forfeited on buyer default; state-specific overrides may reduce amount.",
    ),
    "DE": (
        Decimal("0.00"),
        "BGB §§ 311b, 313 — notarized purchase contract",
        "No standard deposit forfeiture under German civil code; "
        "developer may claim damages but no automatic deposit penalty.",
    ),
    "FR": (
        Decimal("1.00"),
        "Code civil Art. 1590 — arrhes",
        "Buyer forfeits arrhes on rescission; seller delivers 2x arrhes if seller withdraws.",
    ),
    "AU": (
        Decimal("1.00"),
        "Conveyancing Act (state-by-state) — typically 10% deposit",
        "Buyer forfeits deposit on default after cooling-off (typically 5 business days).",
    ),
}

_DEFAULT_FORFEITURE_RULE: tuple[Decimal, str, str] = (
    Decimal("1.00"),
    "Generic common-law forfeiture",
    "No jurisdiction-specific rule loaded; full deposit forfeited on buyer-initiated cancellation (generic default).",
)


def compute_deposit_forfeiture(
    deposit_amount: Decimal | float | int | str,
    jurisdiction: str | None,
    cancelled_before_contract: bool = False,
) -> dict[str, Any]:
    """Return forfeiture amount + jurisdiction-cited rule.

    When ``cancelled_before_contract`` is True, the buyer is still in
    cooling-off / pre-exchange window — full refund regardless of
    jurisdiction.

    Pure: no DB. Always uses a real, citable rule (no random defaults).
    """
    amount = Decimal(str(deposit_amount or 0))
    code = (jurisdiction or "").strip().upper()

    if cancelled_before_contract:
        return {
            "jurisdiction": code or "—",
            "deposit_amount": amount,
            "forfeited_amount": Decimal("0"),
            "refundable_amount": amount,
            "rule_citation": "Pre-contract / cooling-off period",
            "rule_summary": ("Cancellation before contract exchange — full refund regardless of jurisdiction."),
        }

    rule = _DEPOSIT_FORFEITURE_RULES.get(code, _DEFAULT_FORFEITURE_RULE)
    fraction, citation, summary = rule
    forfeited = (amount * fraction).quantize(Decimal("0.01"))
    refundable = (amount - forfeited).quantize(Decimal("0.01"))
    return {
        "jurisdiction": code or "—",
        "deposit_amount": amount,
        "forfeited_amount": forfeited,
        "refundable_amount": refundable,
        "rule_citation": citation,
        "rule_summary": summary,
    }


def supported_jurisdictions() -> list[str]:
    """Return the list of ISO-3166 alpha-2 codes with a real rule loaded."""
    return sorted(_DEPOSIT_FORFEITURE_RULES.keys())


# ── Residual development appraisal (RICS Red Book) ──────────────────────


def compute_residual_appraisal(
    gross_development_value: Decimal | float | int | str,
    construction_cost: Decimal | float | int | str,
    professional_fees_pct: Decimal | float | int | str = Decimal("10"),
    finance_cost: Decimal | float | int | str = Decimal("0"),
    sales_costs_pct: Decimal | float | int | str = Decimal("3"),
    developer_profit_target_pct: Decimal | float | int | str = Decimal("20"),
    contingency_pct: Decimal | float | int | str = Decimal("5"),
) -> dict[str, Any]:
    """Run the residual-valuation method (RICS Red Book — Global, 2025).

    Residual Land Value = GDV − (construction + fees + contingency +
    finance + sales costs + developer profit).

    Profit on Cost = developer_profit / total development cost, where
    "total development cost" is construction + fees + contingency +
    finance + sales costs (i.e. excluding the residual land value and
    excluding the profit line itself — the standard RICS denominator).
    Profit on GDV  = developer_profit / GDV.

    All inputs are coerced through ``Decimal`` so callers may pass floats
    or strings safely.  All percentages are in points (10 = 10%).

    Returns a dict with land value, profit metrics, and the cost breakdown
    so callers can render an itemised appraisal sheet.

    Pure: no DB / I/O.
    """
    gdv = Decimal(str(gross_development_value or 0))
    cc = Decimal(str(construction_cost or 0))
    pf_pct = Decimal(str(professional_fees_pct or 0))
    fin = Decimal(str(finance_cost or 0))
    sc_pct = Decimal(str(sales_costs_pct or 0))
    prof_pct = Decimal(str(developer_profit_target_pct or 0))
    cont_pct = Decimal(str(contingency_pct or 0))

    professional_fees = cc * pf_pct / Decimal("100")
    contingency = cc * cont_pct / Decimal("100")
    sales_costs = gdv * sc_pct / Decimal("100")
    developer_profit = gdv * prof_pct / Decimal("100")

    total_costs_excl_land = cc + professional_fees + contingency + fin + sales_costs + developer_profit
    residual_land_value = gdv - total_costs_excl_land

    q = Decimal("0.01")
    pct_q = Decimal("0.0001")
    total_dev_cost = cc + professional_fees + contingency + fin + sales_costs
    # Profit metrics use the developer-profit line as the numerator.
    profit_on_cost = (developer_profit / total_dev_cost) if total_dev_cost > 0 else Decimal("0")
    profit_on_gdv = (developer_profit / gdv) if gdv > 0 else Decimal("0")

    viable = residual_land_value >= 0

    return {
        "gdv": gdv.quantize(q),
        "construction_cost": cc.quantize(q),
        "professional_fees": professional_fees.quantize(q),
        "contingency": contingency.quantize(q),
        "finance_cost": fin.quantize(q),
        "sales_costs": sales_costs.quantize(q),
        "developer_profit": developer_profit.quantize(q),
        "total_costs_excl_land": total_costs_excl_land.quantize(q),
        "residual_land_value": residual_land_value.quantize(q),
        "profit_on_cost": profit_on_cost.quantize(pct_q),
        "profit_on_gdv": profit_on_gdv.quantize(pct_q),
        "viable": viable,
        "method": "RICS Red Book Global 2025 — Residual Valuation",
    }


def compute_sales_velocity(
    sold_units: int,
    total_units: int,
    months_on_market: Decimal | float | int | str,
) -> dict[str, Any]:
    """Return absorption / velocity metrics for a development.

    Velocity = sold_units / months_on_market  (units / month)
    Absorption_pct = sold_units / total_units * 100
    Months_to_sellout = (total_units − sold_units) / velocity

    Pure: no DB.
    """
    months = Decimal(str(months_on_market or 0))
    if total_units <= 0 or months <= 0:
        return {
            "velocity_units_per_month": Decimal("0"),
            "absorption_pct": Decimal("0"),
            "months_to_sellout": None,
            "sold_units": sold_units,
            "total_units": total_units,
        }
    velocity = Decimal(sold_units) / months
    absorption = (Decimal(sold_units) / Decimal(total_units)) * Decimal("100")
    remaining = total_units - sold_units
    months_to_sellout = (
        (Decimal(remaining) / velocity).quantize(Decimal("0.1"))
        if velocity > 0 and remaining > 0
        else (Decimal("0") if remaining == 0 else None)
    )
    return {
        "velocity_units_per_month": velocity.quantize(Decimal("0.01")),
        "absorption_pct": absorption.quantize(Decimal("0.01")),
        "months_to_sellout": months_to_sellout,
        "sold_units": sold_units,
        "total_units": total_units,
    }


# ── Service ─────────────────────────────────────────────────────────────


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


# ── Payment-schedule milestone templates ────────────────────────────────
#
# Pure data — no DB, no I/O. Each template is a sequence of milestone
# entries summing to 100 % of contract value. ``offset_days`` is added to
# the chosen start date to derive ``due_date``. ``milestone_event`` is
# carried through to ``Instalment.milestone_event`` so downstream
# automations (handover trigger, fit-out trigger, etc.) can fire the
# right line. The catalogue is intentionally short; tenants needing
# more variations should compose them via :class:`PaymentScheduleCreate`
# + :class:`InstalmentCreate`.

PAYMENT_SCHEDULE_TEMPLATES: dict[str, dict[str, Any]] = {
    "single_balance": {
        "label": "Single balance on SPA signing",
        "description": "One instalment for 100 % at SPA signing.",
        "milestones": [
            {
                "sequence": 1,
                "pct": Decimal("100"),
                "label": "Full balance @ SPA signature",
                "milestone_event": "spa_signed",
                "offset_days": 0,
            },
        ],
    },
    "10_40_50": {
        "label": "10 % / 40 % / 50 %",
        "description": "10 % deposit, 40 % at top-out, 50 % at handover.",
        "milestones": [
            {
                "sequence": 1,
                "pct": Decimal("10"),
                "label": "Deposit",
                "milestone_event": "spa_signed",
                "offset_days": 0,
            },
            {
                "sequence": 2,
                "pct": Decimal("40"),
                "label": "Top-out",
                "milestone_event": "construction_top_out",
                "offset_days": 180,
            },
            {
                "sequence": 3,
                "pct": Decimal("50"),
                "label": "Handover",
                "milestone_event": "handover_complete",
                "offset_days": 360,
            },
        ],
    },
    "30_30_40": {
        "label": "30 % / 30 % / 40 %",
        "description": "30 % at signing, 30 % at top-out, 40 % at handover.",
        "milestones": [
            {
                "sequence": 1,
                "pct": Decimal("30"),
                "label": "Down payment",
                "milestone_event": "spa_signed",
                "offset_days": 0,
            },
            {
                "sequence": 2,
                "pct": Decimal("30"),
                "label": "Top-out",
                "milestone_event": "construction_top_out",
                "offset_days": 180,
            },
            {
                "sequence": 3,
                "pct": Decimal("40"),
                "label": "Handover",
                "milestone_event": "handover_complete",
                "offset_days": 360,
            },
        ],
    },
    "20_30_30_20": {
        "label": "20 % / 30 % / 30 % / 20 %",
        "description": ("20 % at signing, 30 % at slab, 30 % at top-out, 20 % at handover."),
        "milestones": [
            {
                "sequence": 1,
                "pct": Decimal("20"),
                "label": "Down payment",
                "milestone_event": "spa_signed",
                "offset_days": 0,
            },
            {
                "sequence": 2,
                "pct": Decimal("30"),
                "label": "Foundation slab",
                "milestone_event": "construction_slab_poured",
                "offset_days": 90,
            },
            {
                "sequence": 3,
                "pct": Decimal("30"),
                "label": "Top-out",
                "milestone_event": "construction_top_out",
                "offset_days": 240,
            },
            {
                "sequence": 4,
                "pct": Decimal("20"),
                "label": "Handover",
                "milestone_event": "handover_complete",
                "offset_days": 365,
            },
        ],
    },
    "quarterly_12": {
        "label": "Equal quarterly over 12 quarters",
        "description": "12 equal instalments at quarterly intervals.",
        "milestones": [
            {
                "sequence": i + 1,
                "pct": Decimal("100") / Decimal("12"),
                "label": f"Quarter {i + 1}",
                "milestone_event": "scheduled",
                "offset_days": i * 90,
            }
            for i in range(12)
        ],
    },
}


def _add_days_iso(start_iso: str, days: int) -> str:
    """Return ``start_iso`` + ``days`` as a YYYY-MM-DD string."""
    d = date.fromisoformat(start_iso[:10])
    return (d + timedelta(days=days)).isoformat()


class PropertyDevService:
    """Business logic + workflow orchestration."""

    # Keep the templates discoverable on the class so the router can list
    # them without importing the module-level constant directly.
    PAYMENT_SCHEDULE_TEMPLATES = PAYMENT_SCHEDULE_TEMPLATES

    @staticmethod
    def payment_schedule_template_catalogue() -> list[dict[str, Any]]:
        """Return a stable, serialisable catalogue of milestone templates."""
        out: list[dict[str, Any]] = []
        for key, tmpl in PAYMENT_SCHEDULE_TEMPLATES.items():
            out.append(
                {
                    "key": key,
                    "label": tmpl["label"],
                    "description": tmpl["description"],
                    "milestone_count": len(tmpl["milestones"]),
                    "splits": [str(m["pct"]) for m in tmpl["milestones"]],
                }
            )
        return out

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.developments = DevelopmentRepository(session)
        self.house_types = HouseTypeRepository(session)
        self.variants = HouseTypeVariantRepository(session)
        self.plots = PlotRepository(session)
        self.option_groups = BuyerOptionGroupRepository(session)
        self.options = BuyerOptionRepository(session)
        self.buyers = BuyerRepository(session)
        self.selections = BuyerSelectionRepository(session)
        self.selection_items = BuyerSelectionItemRepository(session)
        self.handovers = HandoverRepository(session)
        self.handover_docs = HandoverDocRepository(session)
        self.snags = SnagRepository(session)
        self.warranty = WarrantyClaimRepository(session)
        self.pipeline = BuyerPipelineQueries(session)
        # ── R6 (task #137) ─────────────────────────────────────────
        self.leads = LeadRepository(session)
        self.reservations = ReservationRepository(session)
        self.sales_contracts = SalesContractRepository(session)
        self.sales_contract_revisions = SalesContractRevisionRepository(session)
        self.payment_schedules = PaymentScheduleRepository(session)
        self.instalments = InstalmentRepository(session)
        self.contract_parties = ContractPartyRepository(session)
        # ── Task #138 — new repositories.
        self.phases = PhaseRepository(session)
        self.blocks = BlockRepository(session)
        self.brokers = BrokerRepository(session)
        self.commission_agreements = CommissionAgreementRepository(session)
        self.commission_accruals = CommissionAccrualRepository(session)
        self.escrow_accounts = EscrowAccountRepository(session)
        self.escrow_transactions = EscrowTransactionRepository(session)
        self.price_matrices = PriceMatrixRepository(session)
        # ── Pricing engine (v3124) ─────────────────────────────────
        self.price_lists = PriceListRepository(session)
        self.price_list_entries = PriceListEntryRepository(session)
        self.pricing_rules = PricingRuleRepository(session)

    # ── Development ─────────────────────────────────────────────────────

    async def create_development(self, data: DevelopmentCreate) -> Development:
        obj = Development(
            project_id=data.project_id,
            code=data.code,
            name=data.name,
            description=data.description,
            dev_type=data.dev_type,
            location_address=data.location_address,
            country_code=data.country_code,
            latitude=data.latitude,
            longitude=data.longitude,
            total_plots=data.total_plots,
            total_area_m2=data.total_area_m2,
            total_floors=data.total_floors,
            sales_phase=data.sales_phase,
            start_date=data.start_date,
            launch_date=data.launch_date,
            completion_date=data.completion_date,
            marketing_brief=data.marketing_brief,
            status=data.status,
            units=data.units,
            sales_target_amount=data.sales_target_amount,
            currency=data.currency,
            developer_name=data.developer_name,
            architect_name=data.architect_name,
            general_contractor_name=data.general_contractor_name,
            cover_image_url=data.cover_image_url,
            brochure_url=data.brochure_url,
            website_url=data.website_url,
            metadata_=data.metadata,
        )
        return await self.developments.create(obj)

    async def get_development(self, dev_id: uuid.UUID) -> Development:
        obj = await self.developments.get_by_id(dev_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Development not found")
        return obj

    async def update_development(self, dev_id: uuid.UUID, data: DevelopmentUpdate) -> Development:
        await self.get_development(dev_id)
        fields = _dump(data)
        await self.developments.update_fields(dev_id, **fields)
        return await self.get_development(dev_id)

    async def delete_development(self, dev_id: uuid.UUID) -> None:
        await self.get_development(dev_id)
        await self.developments.delete(dev_id)

    # ── House Type ──────────────────────────────────────────────────────

    async def create_house_type(self, data: HouseTypeCreate) -> HouseType:
        obj = HouseType(
            development_id=data.development_id,
            code=data.code,
            name=data.name,
            bedrooms=data.bedrooms,
            bathrooms=data.bathrooms,
            total_area_m2=data.total_area_m2,
            footprint_m2=data.footprint_m2,
            levels=data.levels,
            base_price=data.base_price,
            currency=data.currency,
            bim_model_ref=data.bim_model_ref,
            thumbnail_url=data.thumbnail_url,
            description=data.description,
            metadata_=data.metadata,
        )
        return await self.house_types.create(obj)

    async def get_house_type(self, ht_id: uuid.UUID) -> HouseType:
        obj = await self.house_types.get_by_id(ht_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="HouseType not found")
        return obj

    async def update_house_type(self, ht_id: uuid.UUID, data: HouseTypeUpdate) -> HouseType:
        await self.get_house_type(ht_id)
        await self.house_types.update_fields(ht_id, **_dump(data))
        return await self.get_house_type(ht_id)

    async def delete_house_type(self, ht_id: uuid.UUID) -> None:
        await self.get_house_type(ht_id)
        await self.house_types.delete(ht_id)

    # ── House Type Catalogue (preset + user-created) ────────────────────
    #
    # Distinct from the per-Development HouseType above: these are the
    # lightweight classification entries shown in the Plot create dialog
    # so the user can pick e.g. "Reihenhaus" / "Townhouse" without
    # modelling a full floor plan. Project_id NULL + is_preset=True means
    # "global preset" (migration-seeded); project_id set + is_preset=False
    # means "this tenant's custom entry, scoped to one project".

    async def _verify_project_owner_for_house_type_catalogue(
        self,
        project_id: uuid.UUID,
        user_payload: dict[str, object] | None,
    ) -> None:
        """Confirm the caller owns the project — collapse "not yours" to 404.

        Mirrors the cross-tenant IDOR guard used elsewhere in property_dev
        (see :func:`router._verify_buyer_owner`). Admins bypass.
        """
        if user_payload is None:
            # Service-layer caller without payload (tests / migrations).
            return
        if user_payload.get("role") == "admin":
            return
        user_id = user_payload.get("sub") or user_payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.project_not_found", locale=get_locale()),
            )
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None or str(project.owner_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.project_not_found", locale=get_locale()),
            )

    async def list_house_type_catalogue(
        self,
        *,
        country_code: str | None = None,
        project_id: uuid.UUID | None = None,
        user_payload: dict[str, object] | None = None,
    ) -> list[PropertyDevHouseType]:
        """Return presets + tenant-created entries.

        - Presets (``project_id IS NULL``, ``is_preset=True``) are visible
          to every caller. Filtering by ``country_code`` keeps the result
          tight when the caller knows the project's country.
        - ``project_id``-scoped entries are returned only when the caller
          owns the project (admins see everything).
        - Tenant-created entries with the same ``code`` as a preset
          override the preset in the response (this lets the user replace
          "REIHENHAUS" with their own labelled / sized version without
          losing the preset for other projects).
        """
        from sqlalchemy import or_, select

        # Optional project-ownership gate; if user_payload is None
        # (e.g. internal service call) we skip and return the union.
        if project_id is not None and user_payload is not None:
            await self._verify_project_owner_for_house_type_catalogue(project_id, user_payload)

        clauses = []
        # Always include presets.
        preset_clause = (PropertyDevHouseType.project_id.is_(None)) & (PropertyDevHouseType.is_preset.is_(True))
        clauses.append(preset_clause)
        if project_id is not None:
            clauses.append(PropertyDevHouseType.project_id == project_id)

        stmt = select(PropertyDevHouseType).where(or_(*clauses))
        if country_code:
            # Match exact country OR region-agnostic (NULL) entries.
            stmt = stmt.where(
                or_(
                    PropertyDevHouseType.country_code == country_code.upper(),
                    PropertyDevHouseType.country_code.is_(None),
                )
            )

        rows = (await self.session.execute(stmt)).scalars().all()

        # Override presets with same-code tenant rows. Key by
        # (country_code, code) so a "REIHENHAUS"/DE override only beats
        # the DE preset, never the FR one.
        by_key: dict[tuple[str | None, str], PropertyDevHouseType] = {}
        # First pass: presets (will be overwritten by tenant rows).
        for row in rows:
            if row.project_id is None:
                by_key[(row.country_code, row.code)] = row
        # Second pass: tenant rows override.
        for row in rows:
            if row.project_id is not None:
                by_key[(row.country_code, row.code)] = row

        # Stable sort: country_code (None first), then code.
        return sorted(
            by_key.values(),
            key=lambda r: (r.country_code or "", r.code),
        )

    async def get_house_type_catalogue_entry(
        self,
        entry_id: uuid.UUID,
        user_payload: dict[str, object] | None = None,
    ) -> PropertyDevHouseType:
        obj = await self.session.get(PropertyDevHouseType, entry_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="House type catalogue entry not found")
        # Tenant-scoped entries are only visible to their owner.
        if obj.project_id is not None and user_payload is not None:
            await self._verify_project_owner_for_house_type_catalogue(obj.project_id, user_payload)
        return obj

    async def create_house_type_catalogue_entry(
        self,
        data: PropertyDevHouseTypeCreate,
        user_payload: dict[str, object] | None = None,
    ) -> PropertyDevHouseType:
        """Create a user-scoped catalogue entry. Presets stay migration-only."""
        await self._verify_project_owner_for_house_type_catalogue(data.project_id, user_payload)
        user_id_raw = (user_payload or {}).get("sub") or (user_payload or {}).get("user_id")
        try:
            created_by = uuid.UUID(str(user_id_raw)) if user_id_raw else None
        except (ValueError, TypeError):
            created_by = None

        # Pricing sanity: if both ends supplied, max must be ≥ min.
        if (
            data.typical_price_min is not None
            and data.typical_price_max is not None
            and data.typical_price_max < data.typical_price_min
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="typical_price_max must be ≥ typical_price_min",
            )
        currency = data.currency.upper() if data.currency else None
        construction_type = data.construction_type.strip().lower() or None if data.construction_type else None
        energy_class = data.energy_class.strip() or None if data.energy_class else None
        sales_channel = data.sales_channel.strip().lower() or None if data.sales_channel else None
        # Tags: dedupe + strip + drop empties, preserve order.
        tags_clean: list[str] = []
        for raw in data.tags or []:
            t = (raw or "").strip()
            if t and t not in tags_clean:
                tags_clean.append(t)

        obj = PropertyDevHouseType(
            project_id=data.project_id,
            country_code=(data.country_code.upper() if data.country_code else None),
            region_label=(data.region_label.strip() or None) if data.region_label else None,
            code=data.code.upper(),
            name=data.name,
            description=data.description,
            area_typical_m2=data.area_typical_m2,
            floors_typical=data.floors_typical,
            typical_bedrooms=data.typical_bedrooms,
            typical_bathrooms=data.typical_bathrooms,
            parking_spots=data.parking_spots,
            typical_price_min=data.typical_price_min,
            typical_price_max=data.typical_price_max,
            currency=currency,
            construction_type=construction_type,
            energy_class=energy_class,
            sales_channel=sales_channel,
            image_url=data.image_url,
            tags=tags_clean,
            is_preset=False,
            created_by=created_by,
        )
        self.session.add(obj)
        try:
            await self.session.flush()
        except Exception as exc:  # noqa: BLE001 — surface as 409 conflict
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("A catalogue entry with this code already exists for this project / country"),
            ) from exc
        return obj

    async def update_house_type_catalogue_entry(
        self,
        entry_id: uuid.UUID,
        data: PropertyDevHouseTypeUpdate,
        user_payload: dict[str, object] | None = None,
    ) -> PropertyDevHouseType:
        obj = await self.get_house_type_catalogue_entry(entry_id, user_payload)
        if obj.is_preset:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=("Cannot edit a preset catalogue entry; create a project-scoped override instead"),
            )
        payload = data.model_dump(exclude_unset=True)
        if "country_code" in payload and payload["country_code"]:
            payload["country_code"] = payload["country_code"].upper()
        if "region_label" in payload and payload["region_label"]:
            payload["region_label"] = payload["region_label"].strip() or None
        if "currency" in payload and payload["currency"]:
            payload["currency"] = payload["currency"].upper()
        if "construction_type" in payload and payload["construction_type"]:
            payload["construction_type"] = payload["construction_type"].strip().lower() or None
        if "sales_channel" in payload and payload["sales_channel"]:
            payload["sales_channel"] = payload["sales_channel"].strip().lower() or None
        if "energy_class" in payload and payload["energy_class"]:
            payload["energy_class"] = payload["energy_class"].strip() or None
        # Pricing sanity (against the merged effective values).
        new_min = payload.get("typical_price_min") if "typical_price_min" in payload else obj.typical_price_min
        new_max = payload.get("typical_price_max") if "typical_price_max" in payload else obj.typical_price_max
        if new_min is not None and new_max is not None and new_max < new_min:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="typical_price_max must be ≥ typical_price_min",
            )
        if "tags" in payload and payload["tags"] is not None:
            tags_clean: list[str] = []
            for raw in payload["tags"]:
                t = (raw or "").strip()
                if t and t not in tags_clean:
                    tags_clean.append(t)
            payload["tags"] = tags_clean
        for key, value in payload.items():
            setattr(obj, key, value)
        await self.session.flush()
        self.session.expire(obj)
        return await self.get_house_type_catalogue_entry(entry_id, user_payload)

    async def delete_house_type_catalogue_entry(
        self,
        entry_id: uuid.UUID,
        user_payload: dict[str, object] | None = None,
    ) -> None:
        obj = await self.get_house_type_catalogue_entry(entry_id, user_payload)
        if obj.is_preset:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete a preset catalogue entry",
            )
        await self.session.delete(obj)
        await self.session.flush()

    # ── Variant ─────────────────────────────────────────────────────────

    async def create_variant(self, data: HouseTypeVariantCreate) -> HouseTypeVariant:
        obj = HouseTypeVariant(
            house_type_id=data.house_type_id,
            code=data.code,
            name=data.name,
            modifier_pct=data.modifier_pct,
            description=data.description,
            metadata_=data.metadata,
        )
        return await self.variants.create(obj)

    async def get_variant(self, v_id: uuid.UUID) -> HouseTypeVariant:
        obj = await self.variants.get_by_id(v_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Variant not found")
        return obj

    async def update_variant(self, v_id: uuid.UUID, data: HouseTypeVariantUpdate) -> HouseTypeVariant:
        await self.get_variant(v_id)
        await self.variants.update_fields(v_id, **_dump(data))
        return await self.get_variant(v_id)

    async def delete_variant(self, v_id: uuid.UUID) -> None:
        await self.get_variant(v_id)
        await self.variants.delete(v_id)

    # ── Plot ────────────────────────────────────────────────────────────

    async def create_plot(self, data: PlotCreate) -> Plot:
        obj = Plot(
            development_id=data.development_id,
            plot_number=data.plot_number,
            house_type_id=data.house_type_id,
            house_type_variant_id=data.house_type_variant_id,
            house_type_label=data.house_type_label,
            # Task #138 — Phase/Block hierarchy fields.
            block_id=data.block_id,
            level_in_block=data.level_in_block,
            position_on_floor=data.position_on_floor,
            orientation=data.orientation,
            view_type=data.view_type,
            area_m2=data.area_m2,
            garden_area_m2=data.garden_area_m2,
            balcony_area_m2=data.balcony_area_m2,
            storage_area_m2=data.storage_area_m2,
            bedrooms=data.bedrooms,
            bathrooms=data.bathrooms,
            parking_spaces=data.parking_spaces,
            sun_exposure_hours=data.sun_exposure_hours,
            price_base=data.price_base,
            currency=data.currency,
            status=data.status,
            reservation_deadline=data.reservation_deadline,
            construction_status_percent=data.construction_status_percent,
            metadata_=data.metadata,
        )
        return await self.plots.create(obj)

    async def get_plot(self, plot_id: uuid.UUID) -> Plot:
        obj = await self.plots.get_by_id(plot_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=translate("errors.plot_not_found", locale=get_locale()))
        return obj

    async def update_plot(self, plot_id: uuid.UUID, data: PlotUpdate) -> Plot:
        plot = await self.get_plot(plot_id)
        fields = _dump(data)
        new_status = fields.get("status")
        if new_status:
            _ensure_transition("plot", plot.status, new_status, allowed_plot_transitions)
        await self.plots.update_fields(plot_id, **fields)
        return await self.get_plot(plot_id)

    async def delete_plot(self, plot_id: uuid.UUID) -> None:
        await self.get_plot(plot_id)
        await self.plots.delete(plot_id)

    async def reserve_plot(self, plot_id: uuid.UUID, data: PlotReserveRequest) -> tuple[Plot, Buyer]:
        """Reserve a plot for a buyer.

        Raises:
            HTTPException(409) if the plot is already reserved/sold.
        """
        plot = await self.get_plot(plot_id)
        if plot.status not in {"planned", "ready", "under_construction"}:
            raise HTTPException(
                status_code=409,
                detail=f"Plot in status '{plot.status}' cannot be reserved",
            )

        # The plot must not already be bound to a *different* buyer — the
        # ``Buyer.plot_id`` UNIQUE constraint would otherwise raise an
        # opaque IntegrityError at flush. Surface a clean 409 instead.
        existing_buyer = await self.buyers.get_for_plot(plot_id)
        if (existing_buyer is not None and data.buyer_id is not None and existing_buyer.id != data.buyer_id) or (
            existing_buyer is not None and data.buyer_id is None
        ):
            raise HTTPException(
                status_code=409,
                detail="Plot is already assigned to a buyer",
            )

        # Bind / create buyer.
        if data.buyer_id is not None:
            buyer = await self.buyers.get_by_id(data.buyer_id)
            if buyer is None:
                raise HTTPException(status_code=404, detail="Buyer not found")
            # No cross-development binding: a buyer can only be placed on a
            # plot inside their own development (IDOR / data-integrity).
            if buyer.development_id != plot.development_id:
                raise HTTPException(
                    status_code=409,
                    detail="Buyer belongs to a different development",
                )
            # Terminal/contracted buyers must not be silently re-pointed at
            # a new plot — only leads/reserved buyers may be (re)reserved.
            if buyer.status not in {"lead", "reserved"}:
                raise HTTPException(
                    status_code=409,
                    detail=(f"Buyer in status '{buyer.status}' cannot reserve a plot"),
                )
            # If the buyer was reserved against another plot, release that
            # plot back to ``planned`` so it does not stay orphaned in
            # ``reserved`` with no buyer attached.
            if buyer.plot_id is not None and buyer.plot_id != plot_id:
                old_plot = await self.plots.get_by_id(buyer.plot_id)
                if old_plot is not None and old_plot.status == "reserved":
                    await self.plots.update_fields(buyer.plot_id, status="planned", reservation_deadline=None)
            await self.buyers.update_fields(buyer.id, plot_id=plot_id, status="reserved")
            buyer = await self.buyers.get_by_id(buyer.id)
        else:
            buyer = Buyer(
                development_id=plot.development_id,
                plot_id=plot_id,
                full_name=data.full_name,
                email=data.email,
                phone=data.phone,
                language=data.language,
                status="reserved",
                metadata_=data.metadata,
            )
            buyer = await self.buyers.create(buyer)

        # Flip plot.
        await self.plots.update_fields(
            plot_id,
            status="reserved",
            reservation_deadline=data.reservation_deadline,
        )
        plot = await self.get_plot(plot_id)

        return plot, buyer

    # ── Option Group / Option ───────────────────────────────────────────

    async def create_option_group(self, data: BuyerOptionGroupCreate) -> BuyerOptionGroup:
        obj = BuyerOptionGroup(
            development_id=data.development_id,
            code=data.code,
            name=data.name,
            group_type=data.group_type,
            display_order=data.display_order,
            allow_multiple=data.allow_multiple,
            max_count=data.max_count,
            freeze_offset_days_before_handover=data.freeze_offset_days_before_handover,
            metadata_=data.metadata,
        )
        return await self.option_groups.create(obj)

    async def get_option_group(self, g_id: uuid.UUID) -> BuyerOptionGroup:
        obj = await self.option_groups.get_by_id(g_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="OptionGroup not found")
        return obj

    async def update_option_group(self, g_id: uuid.UUID, data: BuyerOptionGroupUpdate) -> BuyerOptionGroup:
        await self.get_option_group(g_id)
        await self.option_groups.update_fields(g_id, **_dump(data))
        return await self.get_option_group(g_id)

    async def delete_option_group(self, g_id: uuid.UUID) -> None:
        await self.get_option_group(g_id)
        await self.option_groups.delete(g_id)

    async def create_option(self, data: BuyerOptionCreate) -> BuyerOption:
        obj = BuyerOption(
            group_id=data.group_id,
            code=data.code,
            name=data.name,
            sku=data.sku,
            price_delta=data.price_delta,
            currency=data.currency,
            lead_time_days=data.lead_time_days,
            supplier_name=data.supplier_name,
            thumbnail_url=data.thumbnail_url,
            is_active=data.is_active,
            compatibility_rules=data.compatibility_rules,
            metadata_=data.metadata,
        )
        return await self.options.create(obj)

    async def get_option(self, o_id: uuid.UUID) -> BuyerOption:
        obj = await self.options.get_by_id(o_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Option not found")
        return obj

    async def update_option(self, o_id: uuid.UUID, data: BuyerOptionUpdate) -> BuyerOption:
        await self.get_option(o_id)
        await self.options.update_fields(o_id, **_dump(data))
        return await self.get_option(o_id)

    async def delete_option(self, o_id: uuid.UUID) -> None:
        await self.get_option(o_id)
        await self.options.delete(o_id)

    # ── Buyer ───────────────────────────────────────────────────────────

    async def create_buyer(
        self,
        data: BuyerCreate,
        *,
        sync_to_contacts: bool = True,
        tenant_id: str | None = None,
    ) -> Buyer:
        """Create a Buyer row and (by default) sync it to the Contacts directory.

        ``sync_to_contacts``:
            When True (default for UI-driven flows) the bridge finds-or-
            creates a Contact for the buyer's email and links it via
            ``buyer.contact_id``. The contact's ``module_tags`` array
            picks up ``'property_dev_buyer'``.

            Set to False for portal-driven flows where the buyer signs
            up anonymously and we don't yet want a directory entry.

        ``tenant_id``:
            The caller's user id — used to scope the contact lookup.
            Falls back to None (admin / system context) when omitted.
        """
        obj = Buyer(
            development_id=data.development_id,
            plot_id=data.plot_id,
            portal_user_id=data.portal_user_id,
            full_name=data.full_name,
            email=data.email,
            phone=data.phone,
            language=data.language,
            status=data.status,
            contract_value=data.contract_value,
            currency=data.currency,
            metadata_=data.metadata,
        )
        created = await self.buyers.create(obj)
        if sync_to_contacts and (created.email or created.full_name):
            try:
                from app.modules.contacts import bridge as _contacts_bridge

                await _contacts_bridge.ensure_contact_for_buyer(self.session, created, tenant_id=tenant_id)
            except Exception:  # noqa: BLE001 — bridge is best-effort
                logger.exception(
                    "Contacts bridge failed for buyer %s; continuing without link",
                    created.id,
                )
        return created

    async def get_buyer(self, b_id: uuid.UUID) -> Buyer:
        obj = await self.buyers.get_by_id(b_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Buyer not found")
        return obj

    async def update_buyer(self, b_id: uuid.UUID, data: BuyerUpdate) -> Buyer:
        buyer = await self.get_buyer(b_id)
        fields = _dump(data)
        new_status = fields.get("status")
        if new_status:
            _ensure_transition("buyer", buyer.status, new_status, allowed_buyer_transitions)
        # plot_id consistency: if the caller sets plot_id, it must belong
        # to the same development. Closes a cross-development link bug
        # caught by task #134's plot-collision test. ``None`` is allowed
        # (un-assign the plot).
        plot_field_provided = "plot_id" in fields
        if plot_field_provided and fields["plot_id"] is not None:
            target_plot = await self.plots.get_by_id(fields["plot_id"])
            if target_plot is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Plot {fields['plot_id']} not found",
                )
            if target_plot.development_id != buyer.development_id:
                raise HTTPException(
                    status_code=422,
                    detail=(f"Plot belongs to a different development ({target_plot.development_id})"),
                )
        # Normalise jurisdiction (ISO-3166 alpha-2) to upper-case so the
        # deposit-forfeiture rule lookup stays case-insensitive.
        if "jurisdiction" in fields and isinstance(fields["jurisdiction"], str):
            fields["jurisdiction"] = fields["jurisdiction"].upper()
        # Currency: enforce 3-letter ISO format when supplied (the schema
        # only caps length at 8 to allow stablecoin tickers like USDT —
        # for the edit flow we want a real currency, not a tag).
        currency = fields.get("currency")
        if currency is not None and currency != "" and len(currency) != 3:
            raise HTTPException(
                status_code=422,
                detail="Currency must be a 3-letter ISO code",
            )
        await self.buyers.update_fields(b_id, **fields)
        updated = await self.get_buyer(b_id)
        # Mirror canonical fields back to the linked Contact if any of
        # name/email/phone were touched. Best-effort: a missing/broken
        # contact never breaks the buyer update flow.
        if updated.contact_id is not None and any(k in fields for k in ("full_name", "email", "phone")):
            try:
                from app.modules.contacts import bridge as _contacts_bridge

                await _contacts_bridge.mirror_buyer_fields_to_contact(self.session, updated)
            except Exception:  # noqa: BLE001
                logger.exception("Contacts mirror failed for buyer %s; continuing", updated.id)
        return updated

    async def delete_buyer(self, b_id: uuid.UUID) -> None:
        await self.get_buyer(b_id)
        await self.buyers.delete(b_id)

    async def convert_buyer_to_contracted(self, buyer_id: uuid.UUID, data: BuyerContractRequest) -> Buyer:
        """Walk a buyer up the lead → reserved → contracted path."""
        buyer = await self.get_buyer(buyer_id)
        if buyer.status == "lead":
            _ensure_transition("buyer", buyer.status, "reserved", allowed_buyer_transitions)
            await self.buyers.update_fields(buyer_id, status="reserved")
            buyer.status = "reserved"
        _ensure_transition("buyer", buyer.status, "contracted", allowed_buyer_transitions)

        fields: dict[str, Any] = {
            "status": "contracted",
            "contract_value": data.contract_value,
            "currency": data.currency,
            "contract_signed_at": data.contract_signed_at,
            "deposit_paid_at": data.deposit_paid_at,
            "freeze_deadline": data.freeze_deadline,
        }
        if data.deposit_amount is not None:
            fields["deposit_amount"] = data.deposit_amount
        if data.jurisdiction:
            fields["jurisdiction"] = data.jurisdiction.upper()
        await self.buyers.update_fields(buyer_id, **fields)
        contracted = await self.get_buyer(buyer_id)

        event_bus.publish_detached(
            "property_dev.buyer.contracted",
            data={
                "buyer_id": str(buyer_id),
                "development_id": str(contracted.development_id),
                "plot_id": str(contracted.plot_id) if contracted.plot_id else None,
                "contract_value": str(contracted.contract_value),
                "currency": contracted.currency,
                "contract_signed_at": contracted.contract_signed_at,
                "deposit_amount": str(getattr(contracted, "deposit_amount", 0) or 0),
                "jurisdiction": getattr(contracted, "jurisdiction", "") or "",
            },
            source_module="property_dev",
        )

        return contracted

    async def cancel_buyer(self, buyer_id: uuid.UUID, data: BuyerCancelRequest) -> tuple[Buyer, dict[str, Any]]:
        """Cancel a buyer and compute deposit forfeiture per jurisdiction.

        Returns ``(buyer, forfeiture_breakdown)``. Updates the buyer's
        ``status='cancelled'`` + ``cancelled_at`` + ``cancelled_reason``
        and persists ``deposit_forfeited`` / ``deposit_refunded`` columns.
        Publishes ``property_dev.buyer.cancelled`` event.

        Raises:
            HTTPException(409) if the buyer is already cancelled or
            already completed (terminal states).
        """
        buyer = await self.get_buyer(buyer_id)
        if buyer.status in {"cancelled", "completed"}:
            raise HTTPException(
                status_code=409,
                detail=f"Buyer in status '{buyer.status}' cannot be cancelled",
            )

        # Pre-contract cancellations get full refund regardless of jurisdiction.
        cancelled_pre_contract = buyer.status in {"lead", "reserved"}
        jurisdiction = data.jurisdiction_override.upper() if data.jurisdiction_override else (buyer.jurisdiction or "")
        forfeiture = compute_deposit_forfeiture(
            buyer.deposit_amount or Decimal("0"),
            jurisdiction,
            cancelled_before_contract=cancelled_pre_contract,
        )

        await self.buyers.update_fields(
            buyer_id,
            status="cancelled",
            cancelled_at=data.cancelled_at,
            cancelled_reason=data.reason,
            deposit_forfeited=forfeiture["forfeited_amount"],
            deposit_refunded=forfeiture["refundable_amount"],
        )
        # Free up the plot if it was held by this buyer. A merely
        # ``reserved`` plot goes back to ``planned`` (re-marketable, no
        # construction state to preserve). A ``sold`` plot has typically
        # been (part-)built, so it is released to ``ready`` rather than
        # regressed all the way to ``planned`` — that keeps the legal
        # plot state machine intact (``sold`` -> ``planned`` is NOT an
        # allowed transition) and does not throw away build progress.
        if buyer.plot_id:
            plot = await self.plots.get_by_id(buyer.plot_id)
            if plot is not None and plot.status == "reserved":
                await self.plots.update_fields(buyer.plot_id, status="planned", reservation_deadline=None)
            elif plot is not None and plot.status == "sold":
                await self.plots.update_fields(buyer.plot_id, status="ready")

        cancelled = await self.get_buyer(buyer_id)
        event_bus.publish_detached(
            "property_dev.buyer.cancelled",
            data={
                "buyer_id": str(buyer_id),
                "development_id": str(cancelled.development_id),
                "plot_id": str(cancelled.plot_id) if cancelled.plot_id else None,
                "deposit_forfeited": str(forfeiture["forfeited_amount"]),
                "deposit_refunded": str(forfeiture["refundable_amount"]),
                "rule_citation": forfeiture["rule_citation"],
            },
            source_module="property_dev",
        )
        forfeiture["buyer_id"] = buyer_id  # type: ignore[index]
        return cancelled, forfeiture

    # ── Selection ───────────────────────────────────────────────────────

    async def create_selection(self, data: BuyerSelectionCreate) -> BuyerSelection:
        obj = BuyerSelection(
            buyer_id=data.buyer_id,
            status=data.status,
            notes=data.notes,
            metadata_=data.metadata,
        )
        return await self.selections.create(obj)

    async def get_selection(self, s_id: uuid.UUID) -> BuyerSelection:
        obj = await self.selections.get_by_id(s_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Selection not found")
        return obj

    async def update_selection(self, s_id: uuid.UUID, data: BuyerSelectionUpdate) -> BuyerSelection:
        sel = await self.get_selection(s_id)
        fields = _dump(data)
        new_status = fields.get("status")
        if new_status:
            _ensure_transition("selection", sel.status, new_status, allowed_selection_transitions)
        await self.selections.update_fields(s_id, **fields)
        return await self.get_selection(s_id)

    async def delete_selection(self, s_id: uuid.UUID) -> None:
        await self.get_selection(s_id)
        await self.selections.delete(s_id)

    async def add_selection_item(self, selection_id: uuid.UUID, data: BuyerSelectionItemCreate) -> BuyerSelectionItem:
        sel = await self.get_selection(selection_id)
        if sel.status in {"locked", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail=f"Selection is {sel.status}",
            )
        option = await self.get_option(data.option_id)
        if not option.is_active:
            raise HTTPException(
                status_code=409,
                detail="Option is no longer available",
            )
        unit_price = data.unit_price_snapshot if data.unit_price_snapshot is not None else option.price_delta
        item = BuyerSelectionItem(
            selection_id=selection_id,
            option_id=data.option_id,
            quantity=data.quantity,
            unit_price_snapshot=unit_price,
            total_price=Decimal(str(unit_price)) * Decimal(str(data.quantity)),
            included_in_production=False,
            metadata_=data.metadata,
        )
        item = await self.selection_items.create(item)
        item_id = item.id
        # ``_recompute_selection_total`` calls ``update_fields`` which runs
        # ``session.expire_all()`` — that expires the freshly-created ``item``
        # too, so returning it would force a lazy-load outside the async
        # session (MissingGreenlet 500). Re-fetch after recompute so the
        # router serialises a live, attribute-populated instance.
        await self._recompute_selection_total(selection_id)
        refreshed = await self.selection_items.get_by_id(item_id)
        return refreshed if refreshed is not None else item

    async def remove_selection_item(self, item_id: uuid.UUID) -> None:
        item = await self.selection_items.get_by_id(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Selection item not found")
        sel = await self.get_selection(item.selection_id)
        if sel.status in {"locked", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail=f"Selection is {sel.status}",
            )
        await self.selection_items.delete(item_id)
        await self._recompute_selection_total(item.selection_id)

    async def _recompute_selection_total(self, selection_id: uuid.UUID) -> Decimal:
        items = await self.selection_items.list_for_selection(selection_id)
        total = compute_buyer_selection_total(items)
        await self.selections.update_fields(selection_id, total_options_value=total)
        return total

    async def submit_selection(self, selection_id: uuid.UUID) -> BuyerSelection:
        sel = await self.get_selection(selection_id)
        _ensure_transition("selection", sel.status, "submitted", allowed_selection_transitions)
        await self.selections.update_fields(selection_id, status="submitted", submitted_at=_today_iso())
        return await self.get_selection(selection_id)

    async def lock_selection(self, selection_id: uuid.UUID) -> BuyerSelection:
        """Lock a selection (typically after deposit + design freeze)."""
        sel = await self.get_selection(selection_id)
        # Allow lock from draft or submitted.
        if sel.status == "locked":
            return sel
        if sel.status not in {"draft", "submitted"}:
            _ensure_transition("selection", sel.status, "locked", allowed_selection_transitions)
        await self.selections.update_fields(selection_id, status="locked", locked_at=_today_iso())
        locked = await self.get_selection(selection_id)
        event_bus.publish_detached(
            "property_dev.selection.locked",
            data={
                "selection_id": str(selection_id),
                "buyer_id": str(locked.buyer_id),
                "total_options_value": str(locked.total_options_value),
                "locked_at": locked.locked_at,
            },
            source_module="property_dev",
        )
        return locked

    async def submit_for_production(self, buyer_id: uuid.UUID) -> BuyerSelection:
        """Flag every line in the buyer's locked selection as
        ``included_in_production`` so downstream procurement can pick it up.
        """
        buyer = await self.get_buyer(buyer_id)
        sel = await self.selections.current_selection_for_buyer(buyer_id)
        if sel is None:
            raise HTTPException(status_code=404, detail="No selection for buyer")
        if sel.status != "locked":
            raise HTTPException(
                status_code=409,
                detail="Selection must be locked before production handoff",
            )
        items = await self.selection_items.list_for_selection(sel.id)
        for item in items:
            await self.selection_items.update_fields(item.id, included_in_production=True)

        event_bus.publish_detached(
            "property_dev.selection.submitted_for_production",
            data={
                "selection_id": str(sel.id),
                "buyer_id": str(buyer_id),
                "development_id": str(buyer.development_id),
                "plot_id": str(buyer.plot_id) if buyer.plot_id else None,
                "total_options_value": str(sel.total_options_value),
                "item_count": len(items),
            },
            source_module="property_dev",
        )
        return sel

    # ── Handover ────────────────────────────────────────────────────────

    async def create_handover(self, data: HandoverCreate) -> Handover:
        obj = Handover(
            plot_id=data.plot_id,
            scheduled_at=data.scheduled_at,
            notes=data.notes,
            metadata_=data.metadata,
        )
        return await self.handovers.create(obj)

    async def get_handover(self, h_id: uuid.UUID) -> Handover:
        obj = await self.handovers.get_by_id(h_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Handover not found")
        return obj

    async def update_handover(self, h_id: uuid.UUID, data: HandoverUpdate) -> Handover:
        await self.get_handover(h_id)
        await self.handovers.update_fields(h_id, **_dump(data))
        return await self.get_handover(h_id)

    async def delete_handover(self, h_id: uuid.UUID) -> None:
        await self.get_handover(h_id)
        await self.handovers.delete(h_id)

    async def complete_handover(self, h_id: uuid.UUID, data: HandoverCompleteRequest) -> Handover:
        handover = await self.get_handover(h_id)
        if handover.completed_at:
            return handover
        await self.handovers.update_fields(
            h_id,
            completed_at=data.completed_at,
            customer_signature_ref=data.customer_signature_ref,
            keys_handed_over_at=data.keys_handed_over_at or data.completed_at,
            final_check_passed=data.final_check_passed,
            snag_count_at_handover=data.snag_count_at_handover,
            notes=data.notes if data.notes is not None else handover.notes,
        )

        # Flip plot to handed_over.
        await self.plots.update_fields(handover.plot_id, status="handed_over")

        # Advance the linked buyer to ``completed``. Without this the buyer
        # is stuck at ``contracted`` forever even after the keys are handed
        # over, so ``buyers_by_status`` / ``revenue_completed`` and the
        # buyer-stage UI never reflect a finished sale. The transition is
        # only legal from ``contracted`` (per ``_BUYER_TRANSITIONS``); any
        # other state (lead/reserved/cancelled) is left untouched.
        buyer_completed = False
        buyer = await self.buyers.get_for_plot(handover.plot_id)
        if buyer is not None and buyer.status == "contracted":
            await self.buyers.update_fields(buyer.id, status="completed")
            buyer_completed = True

        completed = await self.get_handover(h_id)
        event_bus.publish_detached(
            "property_dev.handover.completed",
            data={
                "handover_id": str(h_id),
                "plot_id": str(completed.plot_id),
                "completed_at": completed.completed_at,
                "snag_count": completed.snag_count_at_handover,
                "final_check_passed": completed.final_check_passed,
                "buyer_id": str(buyer.id) if buyer is not None else None,
                "buyer_completed": buyer_completed,
            },
            source_module="property_dev",
        )
        return completed

    # ── Snag ────────────────────────────────────────────────────────────

    async def create_snag(self, data: SnagCreate) -> Snag:
        obj = Snag(
            handover_id=data.handover_id,
            buyer_id=data.buyer_id,
            category=data.category,
            location_in_plot=data.location_in_plot,
            severity=data.severity,
            description=data.description,
            status=data.status,
            reported_at=data.reported_at or _today_iso(),
            cost_impact=data.cost_impact,
            metadata_=data.metadata,
        )
        snag = await self.snags.create(obj)
        # Surface the snag on the cross-module event bus. Subscribers
        # (punchlist auto-bridge, BI dashboards, ...) listen on
        # ``property_dev.snag.created``. Best-effort: never blocks.
        event_bus.publish_detached(
            "property_dev.snag.created",
            data={
                "snag_id": str(snag.id),
                "handover_id": str(snag.handover_id),
                "buyer_id": str(snag.buyer_id) if snag.buyer_id else None,
                "category": snag.category,
                "severity": snag.severity,
                "description": snag.description[:200],
                "cost_impact": str(snag.cost_impact),
            },
            source_module="property_dev",
        )
        return snag

    async def get_snag(self, s_id: uuid.UUID) -> Snag:
        obj = await self.snags.get_by_id(s_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Snag not found")
        return obj

    async def update_snag(self, s_id: uuid.UUID, data: SnagUpdate) -> Snag:
        await self.get_snag(s_id)
        await self.snags.update_fields(s_id, **_dump(data))
        return await self.get_snag(s_id)

    async def delete_snag(self, s_id: uuid.UUID) -> None:
        await self.get_snag(s_id)
        await self.snags.delete(s_id)

    async def mark_snag_fixed(self, s_id: uuid.UUID, *, fix_notes: str | None = None) -> Snag:
        snag = await self.get_snag(s_id)
        if snag.status == "fixed":
            return snag
        await self.snags.update_fields(s_id, status="fixed", fixed_at=_today_iso(), fix_notes=fix_notes)
        return await self.get_snag(s_id)

    async def mark_snag_wont_fix(self, s_id: uuid.UUID, *, fix_notes: str | None = None) -> Snag:
        await self.get_snag(s_id)
        await self.snags.update_fields(s_id, status="wont_fix", fix_notes=fix_notes)
        return await self.get_snag(s_id)

    async def add_snag_photo(self, s_id: uuid.UUID, photo_path: str) -> Snag:
        """Append a relative photo path to ``snag.photos``.

        The router validates the magic bytes + writes the file to disk
        before calling this; the service just stores the path so the
        photos array stays in sync with what's on the filesystem.
        """
        snag = await self.get_snag(s_id)
        existing = list(snag.photos or [])
        if photo_path not in existing:
            existing.append(photo_path)
            await self.snags.update_fields(s_id, photos=existing)
        return await self.get_snag(s_id)

    # ── Warranty ────────────────────────────────────────────────────────

    # Default warranty windows (years) used when computing
    # ``is_in_warranty``. Structural defects: 10 years from handover.
    # Cosmetic/finishing defects: 1 year. Matches the document_templates
    # warranty-certificate defaults.
    _STRUCTURAL_WARRANTY_YEARS_DEFAULT = 10
    _FINISHING_WARRANTY_YEARS_DEFAULT = 1

    async def raise_warranty_claim(
        self, plot_id: uuid.UUID, buyer_id: uuid.UUID, data: WarrantyClaimCreate
    ) -> WarrantyClaim:
        # Best-effort handover auto-link: if the caller didn't pass one
        # but there's exactly one Handover on this plot, attach it so
        # ``is_in_warranty`` can be computed without further round-trips.
        handover_id = data.handover_id
        if handover_id is None:
            try:
                from sqlalchemy import select as _select

                from app.modules.property_dev.models import (
                    Handover as _Handover,
                )

                row = (
                    await self.session.execute(_select(_Handover).where(_Handover.plot_id == plot_id))
                ).scalar_one_or_none()
                if row is not None:
                    handover_id = row.id
            except Exception:  # noqa: BLE001 — non-fatal best-effort
                handover_id = None

        obj = WarrantyClaim(
            plot_id=plot_id,
            buyer_id=buyer_id,
            handover_id=handover_id,
            source_snag_id=data.source_snag_id,
            assigned_to_user_id=data.assigned_to_user_id,
            raised_at=data.raised_at or _today_iso(),
            category=data.category,
            severity=data.severity,
            description=data.description,
            photos=list(data.photos or []),
            status="raised",
            sla_deadline=data.sla_deadline,
            linked_service_ticket_id=data.linked_service_ticket_id,
            metadata_=data.metadata,
        )
        claim = await self.warranty.create(obj)
        event_bus.publish_detached(
            "property_dev.warranty.raised",
            data={
                "claim_id": str(claim.id),
                "plot_id": str(plot_id),
                "buyer_id": str(buyer_id),
                "handover_id": (str(handover_id) if handover_id else None),
                "source_snag_id": (str(data.source_snag_id) if data.source_snag_id else None),
                "category": data.category,
                "severity": data.severity,
                "description": data.description[:200],
            },
            source_module="property_dev",
        )
        return claim

    async def assign_warranty(self, w_id: uuid.UUID, assignee_id: uuid.UUID | None) -> WarrantyClaim:
        """Assign or unassign a warranty claim's contractor / PM owner."""
        await self.get_warranty(w_id)
        await self.warranty.update_fields(w_id, assigned_to_user_id=assignee_id)
        claim = await self.get_warranty(w_id)
        event_bus.publish_detached(
            "property_dev.warranty.assigned",
            data={
                "claim_id": str(claim.id),
                "assigned_to_user_id": (str(assignee_id) if assignee_id else None),
            },
            source_module="property_dev",
        )
        return claim

    async def add_warranty_photo(self, w_id: uuid.UUID, photo_path: str) -> WarrantyClaim:
        """Append a relative photo path to ``warranty_claim.photos``.

        Mirrors :meth:`add_snag_photo` — the router validates magic
        bytes + writes the file before calling this.
        """
        claim = await self.get_warranty(w_id)
        existing = list(claim.photos or [])
        if photo_path not in existing:
            existing.append(photo_path)
            await self.warranty.update_fields(w_id, photos=existing)
        return await self.get_warranty(w_id)

    async def _is_in_warranty(self, claim: WarrantyClaim) -> bool:
        """True when the claim was raised within the configured warranty
        window from the linked Handover's completion date.

        Categories ``structural`` and ``mep`` use the structural window
        (default 10y). Everything else uses the finishing window (1y).
        Returns False if the link, completion-date, or dates are
        unparseable.
        """
        if not claim.handover_id or not claim.raised_at:
            return False
        try:
            handover = await self.handovers.get_by_id(claim.handover_id)
        except Exception:  # noqa: BLE001
            return False
        if handover is None or not handover.completed_at:
            return False
        from datetime import date as _date

        try:
            completed = _date.fromisoformat(handover.completed_at[:10])
            raised = _date.fromisoformat(claim.raised_at[:10])
        except ValueError:
            return False
        years = (
            self._STRUCTURAL_WARRANTY_YEARS_DEFAULT
            if claim.category in ("structural", "mep")
            else self._FINISHING_WARRANTY_YEARS_DEFAULT
        )
        try:
            cutoff = completed.replace(year=completed.year + years)
        except ValueError:
            # Feb-29 + N years on a non-leap year → fall back to Feb-28.
            cutoff = completed.replace(year=completed.year + years, day=28)
        return raised <= cutoff

    async def warranty_response(self, claim: WarrantyClaim):
        """Validate + decorate a WarrantyClaim into its API response shape."""
        from app.modules.property_dev.schemas import WarrantyClaimResponse

        in_warranty = await self._is_in_warranty(claim)
        payload = WarrantyClaimResponse.model_validate(claim)
        payload.is_in_warranty = in_warranty
        return payload

    async def get_warranty(self, w_id: uuid.UUID) -> WarrantyClaim:
        obj = await self.warranty.get_by_id(w_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="WarrantyClaim not found")
        return obj

    async def update_warranty(self, w_id: uuid.UUID, data: WarrantyClaimUpdate) -> WarrantyClaim:
        claim = await self.get_warranty(w_id)
        fields = _dump(data)
        new_status = fields.get("status")
        if new_status:
            _ensure_transition("warranty", claim.status, new_status, allowed_warranty_transitions)
        await self.warranty.update_fields(w_id, **fields)
        return await self.get_warranty(w_id)

    async def delete_warranty(self, w_id: uuid.UUID) -> None:
        await self.get_warranty(w_id)
        await self.warranty.delete(w_id)

    async def warranty_accept(self, w_id: uuid.UUID) -> WarrantyClaim:
        claim = await self.get_warranty(w_id)
        _ensure_transition("warranty", claim.status, "accepted", allowed_warranty_transitions)
        await self.warranty.update_fields(w_id, status="accepted", accepted_at=_today_iso())
        return await self.get_warranty(w_id)

    async def warranty_reject(self, w_id: uuid.UUID) -> WarrantyClaim:
        claim = await self.get_warranty(w_id)
        _ensure_transition("warranty", claim.status, "rejected", allowed_warranty_transitions)
        await self.warranty.update_fields(w_id, status="rejected")
        return await self.get_warranty(w_id)

    async def warranty_close(self, w_id: uuid.UUID) -> WarrantyClaim:
        claim = await self.get_warranty(w_id)
        _ensure_transition("warranty", claim.status, "closed", allowed_warranty_transitions)
        await self.warranty.update_fields(w_id, status="closed", closed_at=_today_iso())
        return await self.get_warranty(w_id)

    # ── Dashboards ──────────────────────────────────────────────────────

    async def development_sales_dashboard(self, dev_id: uuid.UUID) -> dict[str, Any]:
        dev = await self.get_development(dev_id)
        plots_by_status = await self.plots.count_for_development_by_status(dev_id)
        buyers_by_status = await self.buyers.count_for_development_by_status(dev_id)
        contracted_value = await self.buyers.sum_contract_value(dev_id, status_in=["contracted", "completed"])
        open_snags = await self.snags.count_open_for_development(dev_id)
        open_warranty = await self.warranty.count_open_for_development(dev_id)
        completed_handovers, scheduled_handovers = await self.handovers.count_progress_for_development(dev_id)
        total_plots = sum(plots_by_status.values()) or 0
        sold = plots_by_status.get("sold", 0) + plots_by_status.get("handed_over", 0)
        sell_through = Decimal(sold) / Decimal(total_plots) * Decimal("100") if total_plots else Decimal("0")
        return {
            "development_id": dev.id,
            "total_plots": total_plots,
            "plots_by_status": plots_by_status,
            "buyers_by_status": buyers_by_status,
            "contracted_value": Decimal(str(contracted_value or 0)),
            "open_snags": open_snags,
            "open_warranty_claims": open_warranty,
            "completed_handovers": completed_handovers,
            "scheduled_handovers": scheduled_handovers,
            "sell_through_percent": sell_through.quantize(Decimal("0.01")),
        }

    # ── Handover docs ───────────────────────────────────────────────────

    async def create_handover_doc(self, data: HandoverDocCreate) -> HandoverDoc:
        await self.get_handover(data.handover_id)
        obj = HandoverDoc(
            handover_id=data.handover_id,
            doc_type=data.doc_type,
            title=data.title,
            file_url=data.file_url,
            is_required=data.is_required,
            is_delivered=data.is_delivered,
            delivered_at=_today_iso() if data.is_delivered else None,
            metadata_=data.metadata,
        )
        return await self.handover_docs.create(obj)

    async def get_handover_doc(self, doc_id: uuid.UUID) -> HandoverDoc:
        obj = await self.handover_docs.get_by_id(doc_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="HandoverDoc not found")
        return obj

    async def update_handover_doc(self, doc_id: uuid.UUID, data: HandoverDocUpdate) -> HandoverDoc:
        doc = await self.get_handover_doc(doc_id)
        fields = _dump(data)
        # Stamp delivered_at when flipping is_delivered → True.
        if fields.get("is_delivered") is True and not doc.is_delivered:
            fields["delivered_at"] = _today_iso()
        if fields.get("is_delivered") is False:
            fields["delivered_at"] = None
        await self.handover_docs.update_fields(doc_id, **fields)
        return await self.get_handover_doc(doc_id)

    async def delete_handover_doc(self, doc_id: uuid.UUID) -> None:
        await self.get_handover_doc(doc_id)
        await self.handover_docs.delete(doc_id)

    async def handover_bundle(self, handover_id: uuid.UUID) -> dict[str, Any]:
        """Return all handover docs + required-doc compliance status."""
        await self.get_handover(handover_id)
        docs = await self.handover_docs.list_for_handover(handover_id)
        required = [d for d in docs if d.is_required]
        missing = [d.doc_type for d in required if not d.is_delivered]
        return {
            "handover_id": handover_id,
            "docs": docs,
            "delivered_count": sum(1 for d in docs if d.is_delivered),
            "required_count": len(required),
            "missing_required": missing,
            "ready_for_handover": not missing,
        }

    # ── Sales pipeline kanban + reservation calendar ────────────────────

    async def sales_kanban(self, dev_id: uuid.UUID) -> dict[str, Any]:
        """Group buyers into kanban columns by status."""
        await self.get_development(dev_id)
        rows = await self.pipeline.kanban_for_development(dev_id)
        # Stable column order for the UI.
        column_order = ("lead", "reserved", "contracted", "completed", "cancelled")
        columns: dict[str, dict[str, Any]] = {
            s: {"status": s, "buyers": [], "count": 0, "total_value": Decimal("0")} for s in column_order
        }
        for buyer, plot in rows:
            col = columns.setdefault(
                buyer.status,
                {"status": buyer.status, "buyers": [], "count": 0, "total_value": Decimal("0")},
            )
            col["buyers"].append(
                {
                    "buyer_id": buyer.id,
                    "full_name": buyer.full_name,
                    "email": buyer.email,
                    "plot_id": buyer.plot_id,
                    "plot_number": plot.plot_number if plot is not None else None,
                    "status": buyer.status,
                    "contract_value": Decimal(str(buyer.contract_value or 0)),
                    "currency": buyer.currency,
                    "contract_signed_at": buyer.contract_signed_at,
                    "freeze_deadline": buyer.freeze_deadline,
                }
            )
            col["count"] += 1
            col["total_value"] += Decimal(str(buyer.contract_value or 0))
        return {
            "development_id": dev_id,
            "columns": list(columns.values()),
        }

    async def reservation_calendar(
        self,
        dev_id: uuid.UUID,
        period_start: str,
        period_end: str,
    ) -> dict[str, Any]:
        """Upcoming reservation + freeze + contract deadlines."""
        await self.get_development(dev_id)
        rows = await self.pipeline.reservation_calendar(
            dev_id,
            period_start,
            period_end,
        )
        entries: list[dict[str, Any]] = []
        for plot, buyer in rows:
            entries.append(
                {
                    "plot_id": plot.id,
                    "plot_number": plot.plot_number,
                    "buyer_id": buyer.id if buyer else None,
                    "buyer_name": buyer.full_name if buyer else "",
                    "reservation_deadline": plot.reservation_deadline,
                    "freeze_deadline": buyer.freeze_deadline if buyer else None,
                    "status": plot.status,
                }
            )
        return {
            "development_id": dev_id,
            "period_start": period_start,
            "period_end": period_end,
            "entries": entries,
        }

    async def development_pnl(self, dev_id: uuid.UUID) -> dict[str, Any]:
        """Aggregate revenue + deposit + warranty for a development.

        Cost data comes from finance via cross-module events; here we
        report the developer-visible revenue + deposit + after-care
        metrics.

        Currency: a development is single-currency by convention. We pick
        the currency of the first buyer that has one and only aggregate
        buyers in that currency — silently summing mixed-currency contract
        values into one number is meaningless. ``mixed_currency`` flags
        when at least one buyer used a different currency so the UI can
        warn instead of showing a wrong total.
        """
        dev = await self.get_development(dev_id)
        rows = await self.pipeline.kanban_for_development(dev_id)
        currency = ""
        for buyer, _plot in rows:
            if buyer.currency:
                currency = buyer.currency
                break
        mixed_currency = False
        revenue_contracted = Decimal("0")
        revenue_completed = Decimal("0")
        deposits_held = Decimal("0")
        deposits_forfeited = Decimal("0")
        plot_count_sold = 0
        plot_count_handed_over = 0
        contract_revenue_total = Decimal("0")
        contract_buyer_count = 0
        for buyer, plot in rows:
            b_ccy = buyer.currency or ""
            # Only aggregate money for buyers in the development currency.
            # A buyer with no currency set carries no monetary signal so
            # it is treated as in-currency (its value is 0 anyway).
            in_currency = (not b_ccy) or (not currency) or (b_ccy == currency)
            if b_ccy and currency and b_ccy != currency:
                mixed_currency = True
            value = Decimal(str(buyer.contract_value or 0))
            if in_currency:
                if buyer.status == "contracted":
                    revenue_contracted += value
                if buyer.status == "completed":
                    revenue_completed += value
                if buyer.status in {"contracted", "completed"} and value > 0:
                    contract_revenue_total += value
                    contract_buyer_count += 1
                if buyer.status in {"reserved", "contracted"}:
                    deposits_held += Decimal(str(buyer.deposit_amount or 0))
                deposits_forfeited += Decimal(str(buyer.deposit_forfeited or 0))
            if plot is not None and plot.status == "sold":
                plot_count_sold += 1
            if plot is not None and plot.status == "handed_over":
                plot_count_handed_over += 1
        # Average sale price = mean contract value across buyers that
        # actually hold a contract — NOT contracted revenue divided by
        # the count of *sold plots* (mismatched populations: a contracted
        # buyer's plot is usually still under construction, not "sold").
        avg_sale = (
            (contract_revenue_total / Decimal(contract_buyer_count)).quantize(Decimal("0.01"))
            if contract_buyer_count
            else Decimal("0")
        )
        open_warranty = await self.warranty.count_open_for_development(dev_id)
        open_snags = await self.snags.count_open_for_development(dev_id)
        return {
            "development_id": dev.id,
            "currency": currency,
            "mixed_currency": mixed_currency,
            "revenue_contracted": revenue_contracted.quantize(Decimal("0.01")),
            "revenue_completed": revenue_completed.quantize(Decimal("0.01")),
            "deposits_held": deposits_held.quantize(Decimal("0.01")),
            "deposits_forfeited": deposits_forfeited.quantize(Decimal("0.01")),
            "plot_count_sold": plot_count_sold,
            "plot_count_handed_over": plot_count_handed_over,
            "avg_sale_price": avg_sale,
            "open_warranty_count": open_warranty,
            "open_snag_count": open_snags,
        }

    # ════════════════════════════════════════════════════════════════════
    # R6 — Lead / Reservation / SPA / PaymentSchedule / ContractParty
    # ════════════════════════════════════════════════════════════════════

    # ── Lead ────────────────────────────────────────────────────────────

    async def create_lead(
        self,
        data: LeadCreate,
        *,
        sync_to_contacts: bool = True,
        tenant_id: str | None = None,
    ) -> Lead:
        """Create a new lead at the top of the funnel.

        ``sync_to_contacts`` (default True): find-or-create a Contact
        for the lead's email and link it. The contact picks up the
        ``'property_dev_lead'`` module tag. See
        :mod:`app.modules.contacts.bridge` for the full rationale.

        ``tenant_id``: caller's user id — scopes the contact lookup.
        Falls back to ``data.tenant_id`` when None.
        """
        if data.preferred_house_type_id is not None:
            ht = await self.house_types.get_by_id(data.preferred_house_type_id)
            if ht is None:
                raise HTTPException(status_code=422, detail="preferred_house_type not found")
        if data.development_id is not None:
            dev = await self.developments.get_by_id(data.development_id)
            if dev is None:
                raise HTTPException(status_code=422, detail="development not found")
        obj = Lead(
            development_id=data.development_id,
            tenant_id=data.tenant_id,
            source=data.source,
            lead_score=data.lead_score,
            assigned_agent_user_id=data.assigned_agent_user_id,
            status=data.status,
            nurture_stage=data.nurture_stage,
            full_name=data.full_name,
            email=data.email,
            phone=data.phone,
            language=data.language,
            budget_min=data.budget_min,
            budget_max=data.budget_max,
            currency=data.currency or "",
            preferred_house_type_id=data.preferred_house_type_id,
            notes=data.notes,
            metadata_=data.metadata,
        )
        lead = await self.leads.create(obj)
        if sync_to_contacts and (lead.email or lead.full_name):
            # Resolve the tenant: an explicit caller-supplied id wins;
            # otherwise fall back to data.tenant_id (legacy payload
            # form). The bridge writes the FK back onto ``lead`` and
            # flushes so the next read sees the link.
            resolved_tenant = tenant_id if tenant_id is not None else (str(data.tenant_id) if data.tenant_id else None)
            try:
                from app.modules.contacts import bridge as _contacts_bridge

                await _contacts_bridge.ensure_contact_for_lead(self.session, lead, tenant_id=resolved_tenant)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Contacts bridge failed for lead %s; continuing without link",
                    lead.id,
                )
        event_bus.publish_detached(
            "property_dev.lead.created",
            data={
                "lead_id": str(lead.id),
                "development_id": (str(lead.development_id) if lead.development_id else None),
                "source": lead.source,
                "status": lead.status,
                "email": lead.email,
            },
            source_module="property_dev",
        )
        return lead

    async def get_lead(self, lead_id: uuid.UUID) -> Lead:
        obj = await self.leads.get_by_id(lead_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        return obj

    async def update_lead(self, lead_id: uuid.UUID, data: LeadUpdate) -> Lead:
        lead = await self.get_lead(lead_id)
        fields = _dump(data)
        new_status = fields.get("status")
        if new_status:
            _ensure_transition("lead", lead.status, new_status, allowed_lead_transitions)
        await self.leads.update_fields(lead_id, **fields)
        updated = await self.get_lead(lead_id)
        # Mirror canonical fields back to the linked Contact (best-effort).
        if updated.contact_id is not None and any(k in fields for k in ("full_name", "email", "phone")):
            try:
                from app.modules.contacts import bridge as _contacts_bridge

                await _contacts_bridge.mirror_lead_fields_to_contact(self.session, updated)
            except Exception:  # noqa: BLE001
                logger.exception("Contacts mirror failed for lead %s; continuing", updated.id)
        return updated

    async def delete_lead(self, lead_id: uuid.UUID) -> None:
        await self.get_lead(lead_id)
        await self.leads.delete(lead_id)

    async def convert_lead_to_reservation(
        self,
        lead_id: uuid.UUID,
        data: LeadConvertToReservationRequest,
    ) -> Reservation:
        """Convert a Lead → Reservation (+ optionally a Buyer shadow).

        Publishes ``property_dev.lead.converted``.

        Raises:
            HTTPException(409) if the lead is in a terminal state.
            HTTPException(422) if plot is missing or doesn't accept new
                reservations (status='sold' or 'handed_over').
        """
        lead = await self.get_lead(lead_id)
        if lead.status in {"converted", "lost", "disqualified"}:
            raise HTTPException(
                status_code=409,
                detail=f"Lead in status '{lead.status}' cannot convert",
            )
        plot = await self.plots.get_by_id(data.plot_id)
        if plot is None:
            raise HTTPException(status_code=422, detail="plot not found")
        # Snapshot every plot attribute the rest of this function reads —
        # later update_fields() calls expire the ORM object and any deferred
        # column access trips MissingGreenlet under aiosqlite (caught by R6
        # dashboards + document-templates work).
        plot_id_snap = plot.id
        plot_status_before = plot.status
        plot_development_id_snap = plot.development_id
        plot_number_snap = plot.plot_number
        if plot_status_before in {"sold", "handed_over"}:
            raise HTTPException(
                status_code=409,
                detail=f"Plot {plot_number_snap} not available for reservation",
            )

        # Optionally materialise a Buyer shadow.
        buyer: Buyer | None = None
        if data.create_buyer:
            dev_id = lead.development_id or plot_development_id_snap
            buyer_obj = Buyer(
                development_id=dev_id,
                plot_id=plot_id_snap,
                full_name=lead.full_name,
                email=lead.email,
                phone=lead.phone,
                language=lead.language or "en",
                status="reserved",
                currency=data.currency,
                deposit_amount=data.deposit_amount,
                deposit_paid_at=_today_iso(),
                metadata_=dict(lead.metadata_ or {}),
            )
            buyer = await self.buyers.create(buyer_obj)

        reservation = await self._create_reservation_internal(
            plot=plot,
            lead_id=lead.id,
            buyer_id=buyer.id if buyer is not None else None,
            tenant_id=lead.tenant_id,
            deposit_amount=data.deposit_amount,
            currency=data.currency,
            cooling_off_days=data.cooling_off_days,
            expires_at=data.expires_at,
            metadata={"converted_from_lead": str(lead_id)},
        )

        # Mark lead converted.
        await self.leads.update_fields(
            lead_id,
            status="converted",
            converted_to_buyer_id=buyer.id if buyer is not None else None,
        )
        # Flip plot to reserved unless already past reservation gate.
        if plot_status_before in {"planned", "under_construction", "ready"}:
            await self.plots.update_fields(plot_id_snap, status="reserved")

        event_bus.publish_detached(
            "property_dev.lead.converted",
            data={
                "lead_id": str(lead_id),
                "reservation_id": str(reservation.id),
                "buyer_id": str(buyer.id) if buyer is not None else None,
                "plot_id": str(plot_id_snap),
                "deposit_amount": str(reservation.deposit_amount),
                "currency": reservation.currency,
            },
            source_module="property_dev",
        )
        return reservation

    # ── Reservation ─────────────────────────────────────────────────────

    async def _next_reservation_number(self, plot: Plot) -> str:
        """Compute the next per-development reservation number.

        Numbering format: ``RES-{development_code}-{seq:05d}`` where
        ``seq`` is the count of reservations on this plot + 1.
        """
        dev = await self.developments.get_by_id(plot.development_id)
        dev_code = (dev.code if dev else "DEV").upper()
        seq = await self.reservations.next_sequence_for_plot(plot.id)
        return f"RES-{dev_code}-{seq:05d}"

    async def _create_reservation_internal(
        self,
        *,
        plot: Plot,
        lead_id: uuid.UUID | None,
        buyer_id: uuid.UUID | None,
        tenant_id: uuid.UUID | None,
        deposit_amount: Decimal,
        currency: str,
        cooling_off_days: int,
        expires_at: str | None,
        reservation_number: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Reservation:
        if reservation_number is None:
            reservation_number = await self._next_reservation_number(plot)
        today = datetime.now(UTC).date()
        cooling_off_until = (today + timedelta(days=cooling_off_days)).isoformat()
        # Capture pricing snapshot from the active PriceList (if any).
        # This is the audit-trail entry surfaced in the Quote History tab.
        # Falls back to a base-only quote when no active price list exists
        # so legacy flows continue to work unchanged.
        snapshot: dict[str, Any] = {}
        try:
            active_lists = await self.price_lists.list_active_for_development(
                plot.development_id,
            )
            if active_lists:
                pl = active_lists[0]
                quote = await self.compute_price_quote(  # type: ignore[attr-defined]
                    pl.id,
                    plot_id=plot.id,
                    buyer_id=buyer_id,
                    promo_code=(metadata or {}).get("promo_code"),
                )
                snapshot = quote.model_dump(mode="json")
            else:
                snapshot = {
                    "base_price": str(Decimal(str(plot.price_base or 0))),
                    "lines": [],
                    "total": str(Decimal(str(plot.price_base or 0))),
                    "currency": currency,
                    "price_list_id": None,
                }
        except Exception:  # noqa: BLE001 — never block a reservation on snapshot
            snapshot = {
                "base_price": str(Decimal(str(plot.price_base or 0))),
                "lines": [],
                "total": str(Decimal(str(plot.price_base or 0))),
                "currency": currency,
                "price_list_id": None,
            }

        obj = Reservation(
            plot_id=plot.id,
            lead_id=lead_id,
            buyer_id=buyer_id,
            tenant_id=tenant_id,
            reservation_number=reservation_number,
            deposit_amount=deposit_amount,
            currency=currency,
            deposit_paid_at=datetime.now(UTC),
            cooling_off_days=cooling_off_days,
            cooling_off_until=cooling_off_until,
            expires_at=expires_at,
            status="active",
            price_breakdown_snapshot=snapshot,
            metadata_=metadata or {},
        )
        reservation = await self.reservations.create(obj)
        event_bus.publish_detached(
            "property_dev.reservation.created",
            data={
                "reservation_id": str(reservation.id),
                "plot_id": str(plot.id),
                "lead_id": str(lead_id) if lead_id else None,
                "buyer_id": str(buyer_id) if buyer_id else None,
                "deposit_amount": str(deposit_amount),
                "currency": currency,
            },
            source_module="property_dev",
        )
        return reservation

    async def create_reservation(self, data: ReservationCreate) -> Reservation:
        plot = await self.plots.get_by_id(data.plot_id)
        if plot is None:
            raise HTTPException(status_code=422, detail="plot not found")
        # "reserved" is intentionally included: a plot that is already
        # reserved must not accept a second reservation (double-booking race).
        # Callers that legitimately need to re-reserve a plot must first
        # cancel the existing reservation so the plot status returns to
        # "planned" before creating a new one.
        if plot.status in {"reserved", "sold", "handed_over"}:
            raise HTTPException(
                status_code=409,
                detail=f"Plot {plot.plot_number} not available for reservation",
            )
        # Validate lead/buyer ids if provided.
        if data.lead_id is not None and await self.leads.get_by_id(data.lead_id) is None:
            raise HTTPException(status_code=422, detail="lead not found")
        if data.buyer_id is not None and await self.buyers.get_by_id(data.buyer_id) is None:
            raise HTTPException(status_code=422, detail="buyer not found")
        return await self._create_reservation_internal(
            plot=plot,
            lead_id=data.lead_id,
            buyer_id=data.buyer_id,
            tenant_id=data.tenant_id,
            deposit_amount=data.deposit_amount,
            currency=data.currency,
            cooling_off_days=data.cooling_off_days,
            expires_at=data.expires_at,
            reservation_number=data.reservation_number,
            metadata=data.metadata,
        )

    async def get_reservation(self, r_id: uuid.UUID) -> Reservation:
        obj = await self.reservations.get_by_id(r_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Reservation not found")
        return obj

    async def update_reservation(self, r_id: uuid.UUID, data: ReservationUpdate) -> Reservation:
        res = await self.get_reservation(r_id)
        if res.status != "active":
            raise HTTPException(
                status_code=409,
                detail=f"Reservation in status '{res.status}' is read-only",
            )
        fields = _dump(data)
        if fields:
            await self.reservations.update_fields(r_id, **fields)
        return await self.get_reservation(r_id)

    async def cancel_reservation(self, r_id: uuid.UUID) -> Reservation:
        res = await self.get_reservation(r_id)
        _ensure_transition(
            "reservation",
            res.status,
            "cancelled",
            allowed_reservation_transitions,
        )
        await self.reservations.update_fields(r_id, status="cancelled")
        cancelled = await self.get_reservation(r_id)
        # Free plot if it was held for this reservation.
        plot = await self.plots.get_by_id(cancelled.plot_id)
        if plot is not None and plot.status == "reserved":
            await self.plots.update_fields(plot.id, status="planned")
        event_bus.publish_detached(
            "property_dev.reservation.cancelled",
            data={
                "reservation_id": str(r_id),
                "plot_id": str(cancelled.plot_id),
            },
            source_module="property_dev",
        )
        return cancelled

    async def expire_reservation(self, r_id: uuid.UUID) -> Reservation:
        res = await self.get_reservation(r_id)
        _ensure_transition(
            "reservation",
            res.status,
            "expired",
            allowed_reservation_transitions,
        )
        await self.reservations.update_fields(r_id, status="expired")
        expired = await self.get_reservation(r_id)
        # Free plot if it was held.
        plot = await self.plots.get_by_id(expired.plot_id)
        if plot is not None and plot.status == "reserved":
            await self.plots.update_fields(plot.id, status="planned")
        event_bus.publish_detached(
            "property_dev.reservation.expired",
            data={
                "reservation_id": str(r_id),
                "plot_id": str(expired.plot_id),
            },
            source_module="property_dev",
        )
        return expired

    async def expire_overdue_reservations(self) -> list[uuid.UUID]:
        """Expire every active reservation whose ``expires_at`` is past.

        Returns the list of expired reservation IDs. Safe to call from a
        cron-driven endpoint or from a daily job; idempotent.
        """
        today = datetime.now(UTC).date().isoformat()
        expired = await self.reservations.find_expired(today_iso=today)
        out: list[uuid.UUID] = []
        for res in expired:
            try:
                await self.expire_reservation(res.id)
                out.append(res.id)
            except HTTPException:
                # Transition conflict (already mutated by another path) —
                # skip, do not abort the batch.
                continue
        return out

    async def convert_reservation_to_spa(
        self,
        r_id: uuid.UUID,
        data: ReservationConvertToSpaRequest,
    ) -> SalesContract:
        res = await self.get_reservation(r_id)
        if res.status != "active":
            raise HTTPException(
                status_code=409,
                detail=f"Reservation in status '{res.status}' cannot convert",
            )
        plot = await self.plots.get_by_id(res.plot_id)
        if plot is None:
            raise HTTPException(status_code=409, detail="Plot for reservation has gone away")
        # Snapshot every attribute the rest of this function touches; any
        # later update_fields() expires its row's ORM identity-map entry and
        # would force a lazy-load on subsequent attribute access (trips
        # MissingGreenlet under aiosqlite).
        plot_id_snap = plot.id
        plot_status_before = plot.status
        res_tenant_id_snap = res.tenant_id
        res_buyer_id_snap = res.buyer_id

        contract_number = data.contract_number or await self._next_contract_number(plot)
        obj = SalesContract(
            contract_number=contract_number,
            plot_id=plot_id_snap,
            reservation_id=r_id,
            tenant_id=res_tenant_id_snap,
            signing_date=data.signing_date,
            governing_law=data.governing_law or "",
            language=data.language or "en",
            total_price_breakdown=data.total_price_breakdown,
            total_value=data.total_value,
            currency=data.currency,
            status="draft",
            terms_version=data.terms_version,
            metadata_=data.metadata,
        )
        spa = await self.sales_contracts.create(obj)

        # Mark reservation converted + buyer/plot transition.
        await self.reservations.update_fields(r_id, status="converted")
        if res_buyer_id_snap is not None:
            buyer = await self.buyers.get_by_id(res_buyer_id_snap)
            if buyer is not None and buyer.status == "reserved":
                await self.buyers.update_fields(
                    res_buyer_id_snap,
                    status="contracted",
                    contract_value=data.total_value,
                    currency=data.currency,
                    contract_signed_at=data.signing_date,
                )
            # Auto-create the primary ContractParty so the SPA can move
            # straight into the "send for signature" step. Without this
            # the user was stuck on a draft SPA that the FSM rejected with
            # "SalesContract has no primary party — cannot send" and had
            # no UI affordance to add a party (root cause of "Sales
            # Contracts не работает": the only convert-from-reservation
            # path produced a dead-end SPA).
            try:
                await self.contract_parties.create(
                    ContractParty(
                        sales_contract_id=spa.id,
                        buyer_id=res_buyer_id_snap,
                        ownership_pct=Decimal("100"),
                        party_role="primary",
                        signing_order=0,
                    )
                )
            except Exception:  # noqa: BLE001
                # Auto-party creation must NEVER block SPA creation —
                # if it fails (e.g. on a future race) the SPA still
                # exists and the user can add the party manually via
                # the contract-parties endpoint.
                pass
        if plot_status_before == "reserved":
            await self.plots.update_fields(plot_id_snap, status="sold")

        # Default payment schedule (single milestone @ spa_signed).
        await self._create_default_payment_schedule(spa)

        event_bus.publish_detached(
            "property_dev.spa.created",
            data={
                "spa_id": str(spa.id),
                "plot_id": str(plot_id_snap),
                "reservation_id": str(r_id),
                "total_value": str(spa.total_value),
                "currency": spa.currency,
            },
            source_module="property_dev",
        )
        return spa

    # ── SalesContract ──────────────────────────────────────────────────

    async def _next_contract_number(self, plot: Plot) -> str:
        dev = await self.developments.get_by_id(plot.development_id)
        dev_code = (dev.code if dev else "DEV").upper()
        seq = await self.sales_contracts.next_sequence_for_plot(plot.id)
        return f"SPA-{dev_code}-{seq:05d}"

    async def _create_default_payment_schedule(self, spa: SalesContract) -> PaymentSchedule:
        """Create a single-line ``spa_signed`` schedule by default."""
        schedule_obj = PaymentSchedule(
            sales_contract_id=spa.id,
            tenant_id=spa.tenant_id,
            currency=spa.currency,
            total_amount=spa.total_value,
            status="active",
            metadata_={"auto_created": True},
        )
        schedule = await self.payment_schedules.create(schedule_obj)
        await self.instalments.create(
            Instalment(
                schedule_id=schedule.id,
                sequence=1,
                milestone_label="Full balance @ SPA signature",
                milestone_event="spa_signed",
                due_date=spa.signing_date,
                amount=spa.total_value,
                status="pending",
            )
        )
        return schedule

    async def create_spa(self, data: SalesContractCreate) -> SalesContract:
        plot = await self.plots.get_by_id(data.plot_id)
        if plot is None:
            raise HTTPException(status_code=422, detail="plot not found")
        contract_number = data.contract_number or await self._next_contract_number(plot)
        obj = SalesContract(
            contract_number=contract_number,
            plot_id=plot.id,
            reservation_id=data.reservation_id,
            tenant_id=data.tenant_id,
            signing_date=data.signing_date,
            governing_law=data.governing_law or "",
            language=data.language or "en",
            total_price_breakdown=data.total_price_breakdown,
            total_value=data.total_value,
            currency=data.currency or "",
            e_sign_envelope_id=data.e_sign_envelope_id,
            status="draft",
            parent_contract_id=data.parent_contract_id,
            revision_number=data.revision_number,
            terms_version=data.terms_version,
            metadata_=data.metadata,
        )
        spa = await self.sales_contracts.create(obj)
        event_bus.publish_detached(
            "property_dev.spa.draft_created",
            data={
                "spa_id": str(spa.id),
                "plot_id": str(plot.id),
                "total_value": str(spa.total_value),
                "currency": spa.currency,
            },
            source_module="property_dev",
        )
        return spa

    async def get_spa(self, spa_id: uuid.UUID) -> SalesContract:
        obj = await self.sales_contracts.get_by_id(spa_id)
        if obj is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.salescontract_not_found", locale=get_locale())
            )
        return obj

    async def update_spa(self, spa_id: uuid.UUID, data: SalesContractUpdate) -> SalesContract:
        spa = await self.get_spa(spa_id)
        if spa.status not in {"draft", "sent_for_signature"}:
            raise HTTPException(
                status_code=409,
                detail=f"SalesContract in status '{spa.status}' is read-only",
            )
        fields = _dump(data)
        if fields:
            await self.sales_contracts.update_fields(spa_id, **fields)
        return await self.get_spa(spa_id)

    async def delete_spa(self, spa_id: uuid.UUID) -> None:
        spa = await self.get_spa(spa_id)
        if spa.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Only draft SalesContracts can be deleted",
            )
        await self.sales_contracts.delete(spa_id)

    async def send_spa_for_signature(
        self,
        spa_id: uuid.UUID,
        data: SalesContractSendForSignatureRequest,
    ) -> SalesContract:
        spa = await self.get_spa(spa_id)
        _ensure_transition(
            "spa",
            spa.status,
            "sent_for_signature",
            allowed_spa_transitions,
        )
        # Require at least one party with role=primary.
        parties = await self.contract_parties.list_for_contract(spa_id)
        if not any(p.party_role == "primary" for p in parties):
            raise HTTPException(
                status_code=409,
                detail="SalesContract has no primary party — cannot send",
            )
        fields: dict[str, Any] = {"status": "sent_for_signature"}
        if data.e_sign_envelope_id is not None:
            fields["e_sign_envelope_id"] = data.e_sign_envelope_id
        await self.sales_contracts.update_fields(spa_id, **fields)
        sent = await self.get_spa(spa_id)
        event_bus.publish_detached(
            "property_dev.spa.sent_for_signature",
            data={
                "spa_id": str(spa_id),
                "envelope_id": sent.e_sign_envelope_id,
                "party_count": len(parties),
            },
            source_module="property_dev",
        )
        return sent

    async def sign_spa(self, spa_id: uuid.UUID, data: SalesContractSignRequest) -> SalesContract:
        """Counter-sign the SPA on the developer side."""
        spa = await self.get_spa(spa_id)
        # Allow counter-sign from signed → countersigned (typical path)
        # or from sent_for_signature when buyer + developer co-sign at once.
        if spa.status == "signed":
            target = "countersigned"
        elif spa.status in {"sent_for_signature", "partially_signed"}:
            target = "signed"
        else:
            raise HTTPException(
                status_code=409,
                detail=f"SalesContract in status '{spa.status}' cannot be signed",
            )
        _ensure_transition("spa", spa.status, target, allowed_spa_transitions)
        fields: dict[str, Any] = {"status": target}
        if data.signing_date and not spa.signing_date:
            fields["signing_date"] = data.signing_date
        await self.sales_contracts.update_fields(spa_id, **fields)
        signed = await self.get_spa(spa_id)

        # Auto-activate the linked payment schedule on countersign.
        if target == "countersigned":
            schedule = await self.payment_schedules.get_for_contract(spa_id)
            if schedule is not None and schedule.status == "active":
                # Schedule already active → fire spa_signed milestone.
                await self._fire_milestone(spa_id, "spa_signed")

        event_bus.publish_detached(
            "property_dev.spa.signed",
            data={
                "spa_id": str(spa_id),
                "plot_id": str(signed.plot_id),
                "status": signed.status,
                "signing_date": signed.signing_date,
            },
            source_module="property_dev",
        )
        return signed

    async def cancel_spa(self, spa_id: uuid.UUID) -> SalesContract:
        spa = await self.get_spa(spa_id)
        _ensure_transition("spa", spa.status, "cancelled", allowed_spa_transitions)
        await self.sales_contracts.update_fields(spa_id, status="cancelled")
        # Suspend the schedule.
        schedule = await self.payment_schedules.get_for_contract(spa_id)
        if schedule is not None and schedule.status == "active":
            await self.payment_schedules.update_fields(schedule.id, status="cancelled")
        event_bus.publish_detached(
            "property_dev.spa.cancelled",
            data={"spa_id": str(spa_id)},
            source_module="property_dev",
        )
        return await self.get_spa(spa_id)

    # ── Tax / VAT / Stamp-duty quote ───────────────────────────────────

    async def quote_contract_taxes(
        self,
        contract_id: uuid.UUID,
        *,
        jurisdiction: str | None = None,
        region_subcode: str | None = None,
        is_first_home: bool = False,
        is_additional_property: bool = False,
        vat_rate_class: str = "standard",
        absd_buyer_profile: str | None = None,
        emirate: str | None = None,
        include_overdue: bool = True,
    ) -> dict[str, Any]:
        """Compute jurisdiction-aware taxes for a SalesContract.

        Thin async wrapper over :mod:`app.modules.property_dev.tax_engine`.
        Resolves the contract → development → project chain, derives a
        sensible default jurisdiction (when not supplied by the caller),
        gathers overdue instalments and returns a fully itemised quote.

        Args:
            contract_id: SalesContract.id.
            jurisdiction: Override jurisdiction ISO-3166 alpha-2. When
                None, taken from ``SalesContract.governing_law`` (ISO
                3166-2 form, e.g. ``"DE-BE"``) or the development
                metadata ``country_code`` key.
            region_subcode: e.g. ``"BE"`` for Berlin, ``"MH"`` for
                Maharashtra. When None and governing_law has a hyphen,
                the suffix is used.
            is_first_home: UK first-time-buyer relief flag.
            is_additional_property: UK 3 % surcharge / second-home flag.
            vat_rate_class: VAT/GST class key.
            absd_buyer_profile: SG ABSD buyer profile.
            emirate: UAE emirate when jurisdiction is AE.
            include_overdue: when True, include late-interest accrual
                for every instalment whose ``due_date`` is in the past
                and ``status`` is overdue/due. Default True.

        Returns:
            The full ``compute_total_taxes_for_contract`` payload.

        Raises:
            HTTPException 404: contract not found.
            tax_engine.UnsupportedJurisdictionError: jurisdiction not in table.
            tax_engine.MissingRegionSubcodeError: subcode needed but not given.
        """
        # Local import avoids module-load cost when the endpoint isn't used.
        from app.modules.property_dev.tax_engine import (
            compute_total_taxes_for_contract,
        )

        spa = await self.get_spa(contract_id)

        # ── 1. Resolve jurisdiction + region_subcode if not provided ──
        resolved_jurisdiction = jurisdiction
        resolved_subcode = region_subcode
        if resolved_jurisdiction is None:
            gov = (spa.governing_law or "").strip().upper()
            if gov:
                parts = gov.split("-", 1)
                resolved_jurisdiction = parts[0]
                if resolved_subcode is None and len(parts) == 2:
                    resolved_subcode = parts[1]
        if resolved_jurisdiction is None:
            # Fall back to development metadata.
            plot = await self.get_plot(spa.plot_id)
            dev = await self.get_development(plot.development_id)
            md = dev.metadata_ or {}
            resolved_jurisdiction = (md.get("country_code") or md.get("jurisdiction") or "").strip().upper() or None
            if resolved_subcode is None:
                resolved_subcode = md.get("region_subcode") or md.get("state") or None
                if isinstance(resolved_subcode, str):
                    resolved_subcode = resolved_subcode.strip().upper()

        # Effective-on = contract signing date (defaults to today).
        effective_on: date | None = None
        if spa.signing_date:
            try:
                effective_on = date.fromisoformat(spa.signing_date[:10])
            except (TypeError, ValueError):
                effective_on = None

        # ── 2. Collect overdue instalments for late-interest accrual ──
        overdue_lines: list[dict[str, Any]] = []
        if include_overdue:
            schedule = await self.payment_schedules.get_for_contract(contract_id)
            if schedule is not None:
                rows = await self.instalments.list_for_schedule(schedule.id)
                today = date.today()
                for row in rows:
                    if row.status not in {"overdue", "due"}:
                        continue
                    due_dt: date | None = None
                    if row.due_date:
                        try:
                            due_dt = date.fromisoformat(row.due_date[:10])
                        except (TypeError, ValueError):
                            due_dt = None
                    if due_dt is None or due_dt >= today:
                        continue
                    overdue_lines.append(
                        {
                            "sequence": row.sequence,
                            "amount": str(row.amount - row.amount_paid),
                            "due_date": row.due_date,
                            "paid_date": None,
                        }
                    )

        # ── 3. Build the engine input ─────────────────────────────────
        contract_input: dict[str, Any] = {
            "net": spa.total_value,
            "currency": spa.currency,
        }
        # If the SPA's price breakdown carries an explicit ``net`` line,
        # prefer that — it captures discounts/options the engine can't see.
        breakdown = spa.total_price_breakdown or {}
        if isinstance(breakdown, dict) and breakdown.get("net"):
            contract_input["net"] = breakdown["net"]

        return compute_total_taxes_for_contract(
            contract_input,
            resolved_jurisdiction or "",
            region_subcode=resolved_subcode,
            is_first_home=is_first_home,
            is_additional_property=is_additional_property,
            vat_rate_class=vat_rate_class,
            effective_on=effective_on,
            absd_buyer_profile=absd_buyer_profile,
            emirate=emirate,
            overdue_instalments=overdue_lines if overdue_lines else None,
        )

    # ── PaymentSchedule ────────────────────────────────────────────────

    async def generate_payment_schedule_from_template(
        self,
        contract_id: uuid.UUID,
        *,
        template_key: str,
        start_date: str | None = None,
        late_fee_pct: Any = None,
        grace_period_days: Any = None,
    ) -> PaymentSchedule:
        """Create (or rebuild) a payment schedule from a milestone template.

        Used by the "Generate Schedule" CTA on the SPA detail tab. If a
        schedule already exists for this SPA and is in ``active`` or
        ``completed`` state, the request fails 409 to avoid clobbering
        paid lines. A ``suspended``/``cancelled`` schedule is rebuilt in
        place (its instalments are removed and re-created).
        """
        if template_key not in PAYMENT_SCHEDULE_TEMPLATES:
            raise HTTPException(
                status_code=422,
                detail=(f"Unknown template_key '{template_key}'. Known: {sorted(PAYMENT_SCHEDULE_TEMPLATES.keys())}"),
            )
        spa = await self.get_spa(contract_id)
        existing = await self.payment_schedules.get_for_contract(spa.id)
        if existing is not None and existing.status in {"active", "completed"}:
            # The convert-reservation-to-spa flow always creates a default
            # ``active`` 1-line schedule (so finance has *something* to
            # post against immediately). Allow a from-template rebuild
            # over that default IFF nothing has been paid yet — otherwise
            # the user is stuck (UX dead-end the user reported as
            # "Payment Schedules не работает"). The strict 409 still
            # applies to schedules with any paid/waived/cancelled rows.
            existing_md = dict(existing.metadata_ or {})
            ins_rows = await self.instalments.list_for_schedule(existing.id)
            has_real_activity = any(
                r.status in {"paid", "waived", "overdue", "due"} or (r.amount_paid and Decimal(str(r.amount_paid)) > 0)
                for r in ins_rows
            )
            if not (existing_md.get("auto_created") and not has_real_activity):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"PaymentSchedule in status '{existing.status}' is "
                        "live with paid instalments — suspend it first or "
                        "create a new SPA revision."
                    ),
                )

        tmpl = PAYMENT_SCHEDULE_TEMPLATES[template_key]
        total_value = Decimal(str(spa.total_value or 0))
        # Compute per-line amounts. Last line absorbs rounding so the
        # sum is identical to ``total_value`` to the cent.
        per_line: list[Decimal] = []
        running = Decimal("0")
        for i, m in enumerate(tmpl["milestones"]):
            pct: Decimal = m["pct"]
            if i == len(tmpl["milestones"]) - 1:
                amt = (total_value - running).quantize(Decimal("0.01"))
            else:
                amt = (total_value * pct / Decimal("100")).quantize(Decimal("0.01"))
                running += amt
            per_line.append(amt)

        # Resolve start anchor: explicit start_date > spa.signing_date > today.
        if start_date is None:
            start_anchor = spa.signing_date or datetime.now(UTC).date().isoformat()
        else:
            start_anchor = start_date

        lfp = Decimal(str(late_fee_pct)) if late_fee_pct is not None else Decimal("0")
        gpd = int(grace_period_days) if grace_period_days is not None else 0

        # Replace-in-place when a non-live schedule exists; else create.
        if existing is None:
            schedule_obj = PaymentSchedule(
                sales_contract_id=spa.id,
                tenant_id=spa.tenant_id,
                currency=spa.currency,
                total_amount=total_value,
                late_fee_pct=lfp,
                grace_period_days=gpd,
                status="active",
                metadata_={
                    "auto_created": True,
                    "template_key": template_key,
                    "start_date": start_anchor,
                },
            )
            schedule = await self.payment_schedules.create(schedule_obj)
        else:
            # Snapshot every attribute the rest of this block touches BEFORE
            # any mutation — once update_fields() expires the row, lazy
            # column reloads under aiosqlite trip MissingGreenlet (same
            # pattern as convert_reservation_to_spa above).
            existing_id = existing.id
            existing_md = dict(existing.metadata_ or {})
            # Drop every existing instalment row first.
            rows = await self.instalments.list_for_schedule(existing_id)
            for r in rows:
                await self.instalments.delete(r.id)
            existing_md.update(
                {
                    "auto_created": True,
                    "template_key": template_key,
                    "start_date": start_anchor,
                }
            )
            await self.payment_schedules.update_fields(
                existing_id,
                status="active",
                total_amount=total_value,
                currency=spa.currency,
                late_fee_pct=lfp,
                grace_period_days=gpd,
                metadata_=existing_md,
            )
            schedule = await self.get_payment_schedule(existing_id)

        for m, amt in zip(tmpl["milestones"], per_line, strict=False):
            due_iso: str | None = None
            try:
                due_iso = _add_days_iso(start_anchor, int(m["offset_days"]))
            except (TypeError, ValueError):
                due_iso = None
            await self.instalments.create(
                Instalment(
                    schedule_id=schedule.id,
                    sequence=int(m["sequence"]),
                    milestone_label=str(m["label"]),
                    milestone_event=str(m["milestone_event"]),
                    due_date=due_iso,
                    amount=amt,
                    status="pending",
                )
            )

        # Mark the first pending instalment due so it shows on the
        # cashflow widgets immediately.
        await self._mark_first_pending_due(schedule.id)
        event_bus.publish_detached(
            "property_dev.payment_schedule.generated",
            data={
                "schedule_id": str(schedule.id),
                "sales_contract_id": str(spa.id),
                "template_key": template_key,
                "milestone_count": len(tmpl["milestones"]),
            },
            source_module="property_dev",
        )
        return schedule

    async def create_payment_schedule(self, data: PaymentScheduleCreate) -> PaymentSchedule:
        spa = await self.get_spa(data.sales_contract_id)
        existing = await self.payment_schedules.get_for_contract(spa.id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="PaymentSchedule already exists for this SPA",
            )
        obj = PaymentSchedule(
            sales_contract_id=spa.id,
            tenant_id=data.tenant_id,
            currency=data.currency,
            total_amount=data.total_amount,
            late_fee_pct=data.late_fee_pct,
            grace_period_days=data.grace_period_days,
            status="active",
            metadata_=data.metadata,
        )
        return await self.payment_schedules.create(obj)

    async def get_payment_schedule(self, schedule_id: uuid.UUID) -> PaymentSchedule:
        obj = await self.payment_schedules.get_by_id(schedule_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="PaymentSchedule not found")
        return obj

    async def update_payment_schedule(self, schedule_id: uuid.UUID, data: PaymentScheduleUpdate) -> PaymentSchedule:
        await self.get_payment_schedule(schedule_id)
        fields = _dump(data)
        if fields:
            await self.payment_schedules.update_fields(schedule_id, **fields)
        return await self.get_payment_schedule(schedule_id)

    async def activate_payment_schedule(self, schedule_id: uuid.UUID) -> PaymentSchedule:
        """Activate a suspended schedule and mark the first pending line due."""
        schedule = await self.get_payment_schedule(schedule_id)
        if schedule.status == "active":
            # Idempotent — but still mark first pending instalment due.
            await self._mark_first_pending_due(schedule_id)
            return schedule
        _ensure_transition(
            "payment_schedule",
            schedule.status,
            "active",
            allowed_payment_schedule_transitions,
        )
        await self.payment_schedules.update_fields(schedule_id, status="active")
        await self._mark_first_pending_due(schedule_id)
        activated = await self.get_payment_schedule(schedule_id)
        event_bus.publish_detached(
            "property_dev.payment_schedule.activated",
            data={
                "schedule_id": str(schedule_id),
                "sales_contract_id": str(activated.sales_contract_id),
            },
            source_module="property_dev",
        )
        return activated

    async def suspend_payment_schedule(self, schedule_id: uuid.UUID) -> PaymentSchedule:
        schedule = await self.get_payment_schedule(schedule_id)
        _ensure_transition(
            "payment_schedule",
            schedule.status,
            "suspended",
            allowed_payment_schedule_transitions,
        )
        await self.payment_schedules.update_fields(schedule_id, status="suspended")
        return await self.get_payment_schedule(schedule_id)

    async def _mark_first_pending_due(self, schedule_id: uuid.UUID) -> None:
        instalments = await self.instalments.list_for_schedule(schedule_id)
        for ins in instalments:
            if ins.status == "pending":
                await self.instalments.update_fields(ins.id, status="due")
                break

    # ── Instalment ─────────────────────────────────────────────────────

    async def create_instalment(self, data: InstalmentCreate) -> Instalment:
        schedule = await self.get_payment_schedule(data.schedule_id)
        if schedule.status not in {"active", "suspended"}:
            raise HTTPException(
                status_code=409,
                detail=f"Schedule in status '{schedule.status}' is read-only",
            )
        obj = Instalment(
            schedule_id=schedule.id,
            sequence=data.sequence,
            milestone_label=data.milestone_label,
            milestone_event=data.milestone_event,
            due_date=data.due_date,
            amount=data.amount,
            status="pending",
            invoice_ref=data.invoice_ref,
            metadata_=data.metadata,
        )
        return await self.instalments.create(obj)

    async def get_instalment(self, ins_id: uuid.UUID) -> Instalment:
        obj = await self.instalments.get_by_id(ins_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Instalment not found")
        return obj

    async def update_instalment(self, ins_id: uuid.UUID, data: InstalmentUpdate) -> Instalment:
        ins = await self.get_instalment(ins_id)
        if ins.status in {"paid", "waived", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail=f"Instalment in status '{ins.status}' is read-only",
            )
        fields = _dump(data)
        if fields:
            await self.instalments.update_fields(ins_id, **fields)
        return await self.get_instalment(ins_id)

    async def mark_instalment_paid(
        self,
        ins_id: uuid.UUID,
        data: InstalmentMarkPaidRequest,
    ) -> Instalment:
        ins = await self.get_instalment(ins_id)
        if ins.status in {"paid", "waived", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail=f"Instalment in status '{ins.status}' is read-only",
            )
        amount = Decimal(str(data.amount))
        if amount <= 0:
            raise HTTPException(status_code=422, detail="amount must be > 0")
        current_paid = Decimal(str(ins.amount_paid or 0))
        new_paid = current_paid + amount
        owed = Decimal(str(ins.amount or 0))
        # Allow over-pay tolerance of 0.01 (rounding); else 422.
        if new_paid > owed + Decimal("0.01"):
            raise HTTPException(
                status_code=422,
                detail=(f"payment {amount} exceeds outstanding {owed - current_paid}"),
            )
        new_status = "paid" if new_paid >= owed - Decimal("0.01") else ins.status
        if new_status == "paid":
            _ensure_transition(
                "instalment",
                ins.status,
                "paid",
                allowed_instalment_transitions,
            )
        fields: dict[str, Any] = {
            "amount_paid": new_paid.quantize(Decimal("0.01")),
        }
        if new_status == "paid":
            fields["status"] = "paid"
            fields["paid_at"] = data.paid_at or datetime.now(UTC)
        if data.invoice_ref:
            fields["invoice_ref"] = data.invoice_ref
        await self.instalments.update_fields(ins_id, **fields)
        updated = await self.get_instalment(ins_id)

        # Schedule completion check.
        if new_status == "paid":
            await self._maybe_complete_schedule(updated.schedule_id)

        event_bus.publish_detached(
            "property_dev.instalment.paid",
            data={
                "instalment_id": str(ins_id),
                "schedule_id": str(updated.schedule_id),
                "amount_paid": str(amount),
                "amount_total_paid": str(new_paid),
                "status": updated.status,
            },
            source_module="property_dev",
        )
        # Cashflow signal for finance.
        event_bus.publish_detached(
            "finance.cashflow.actual_received",
            data={
                "source_module": "property_dev",
                "source_id": str(ins_id),
                "schedule_id": str(updated.schedule_id),
                "amount": str(amount),
            },
            source_module="property_dev",
        )
        return updated

    async def issue_instalment_demand(self, ins_id: uuid.UUID) -> Instalment:
        """Emit a demand-letter event for the correspondence module.

        The correspondence module subscribes to
        ``correspondence.outbound.requested`` and is responsible for
        templating, signing and sending. This method only stages the
        intent + records it on the instalment metadata.
        """
        ins = await self.get_instalment(ins_id)
        if ins.status in {"paid", "waived", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail=f"Instalment in status '{ins.status}' — no demand",
            )
        # Mark overdue if past due_date.
        today = datetime.now(UTC).date().isoformat()
        if ins.due_date and ins.due_date < today and ins.status in {"pending", "due"}:
            _ensure_transition(
                "instalment",
                ins.status,
                "overdue",
                allowed_instalment_transitions,
            )
            await self.instalments.update_fields(ins_id, status="overdue")

        event_bus.publish_detached(
            "correspondence.outbound.requested",
            data={
                "template": "INSTALMENT_DEMAND",
                "instalment_id": str(ins_id),
                "schedule_id": str(ins.schedule_id),
                "amount_outstanding": str(Decimal(str(ins.amount or 0)) - Decimal(str(ins.amount_paid or 0))),
                "due_date": ins.due_date,
                "milestone_label": ins.milestone_label,
            },
            source_module="property_dev",
        )
        return await self.get_instalment(ins_id)

    async def waive_instalment(self, ins_id: uuid.UUID, data: InstalmentWaiveRequest) -> Instalment:
        ins = await self.get_instalment(ins_id)
        _ensure_transition(
            "instalment",
            ins.status,
            "waived",
            allowed_instalment_transitions,
        )
        md = dict(ins.metadata_ or {})
        md["waiver_reason"] = data.reason
        md["waived_at"] = datetime.now(UTC).isoformat()
        await self.instalments.update_fields(ins_id, status="waived", metadata_=md)
        await self._maybe_complete_schedule(ins.schedule_id)
        event_bus.publish_detached(
            "property_dev.instalment.waived",
            data={
                "instalment_id": str(ins_id),
                "schedule_id": str(ins.schedule_id),
                "reason": data.reason,
            },
            source_module="property_dev",
        )
        return await self.get_instalment(ins_id)

    async def accrue_late_fees_daily(self) -> dict[str, Any]:
        """Accrue one day of late fees on every overdue instalment.

        Late fee delta = ``schedule.late_fee_pct / 100 * outstanding``.
        Pure no-op when no schedules have a non-zero fee.
        """
        today = datetime.now(UTC).date().isoformat()
        overdue = await self.instalments.list_overdue(today_iso=today)
        touched = 0
        total_accrued = Decimal("0")
        for ins in overdue:
            schedule = await self.payment_schedules.get_by_id(ins.schedule_id)
            if schedule is None or schedule.status != "active":
                continue
            pct = Decimal(str(schedule.late_fee_pct or 0))
            if pct <= 0:
                continue
            grace = schedule.grace_period_days or 0
            try:
                due = date.fromisoformat(ins.due_date)
            except (TypeError, ValueError):
                continue
            today_d = date.fromisoformat(today)
            if (today_d - due).days <= grace:
                continue
            outstanding = Decimal(str(ins.amount or 0)) - Decimal(str(ins.amount_paid or 0))
            if outstanding <= 0:
                continue
            delta = outstanding * pct / Decimal("100") / Decimal("365")
            delta = delta.quantize(Decimal("0.01"))
            if delta <= 0:
                continue
            new_accrued = (Decimal(str(ins.late_fee_accrued or 0)) + delta).quantize(Decimal("0.01"))
            # Move pending → overdue if not already.
            new_status = "overdue" if ins.status != "overdue" else ins.status
            await self.instalments.update_fields(
                ins.id,
                late_fee_accrued=new_accrued,
                status=new_status,
            )
            touched += 1
            total_accrued += delta
        return {
            "touched_count": touched,
            "total_accrued": total_accrued,
        }

    async def _maybe_complete_schedule(self, schedule_id: uuid.UUID) -> None:
        """If all instalments are paid/waived → mark schedule completed."""
        items = await self.instalments.list_for_schedule(schedule_id)
        if not items:
            return
        if all(i.status in {"paid", "waived", "cancelled"} for i in items):
            await self.payment_schedules.update_fields(schedule_id, status="completed")
            event_bus.publish_detached(
                "property_dev.payment_schedule.completed",
                data={"schedule_id": str(schedule_id)},
                source_module="property_dev",
            )

    async def _fire_milestone(self, spa_id: uuid.UUID, milestone_event: str) -> int:
        """Mark every pending instalment matching ``milestone_event`` as due.

        Returns the number of instalments touched.
        """
        # All instalments on this SPA whose milestone matches.
        ins_rows = await self.instalments.list_for_contract(spa_id)
        touched = 0
        for ins in ins_rows:
            if ins.milestone_event == milestone_event and ins.status == "pending":
                await self.instalments.update_fields(ins.id, status="due")
                touched += 1
        return touched

    # ── ContractParty ──────────────────────────────────────────────────

    async def add_contract_party(self, data: ContractPartyCreate) -> ContractParty:
        spa = await self.get_spa(data.sales_contract_id)
        if spa.status not in {"draft", "sent_for_signature"}:
            raise HTTPException(
                status_code=409,
                detail=(f"SalesContract in status '{spa.status}' is locked — no party changes"),
            )
        buyer = await self.buyers.get_by_id(data.buyer_id)
        if buyer is None:
            raise HTTPException(status_code=422, detail="buyer not found")
        existing = await self.contract_parties.find_existing(spa.id, data.buyer_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Buyer is already a party")
        # Validate sum of ownership_pct including the new row.
        parties = await self.contract_parties.list_for_contract(spa.id)
        current_total = sum(
            (Decimal(str(p.ownership_pct or 0)) for p in parties),
            Decimal("0"),
        )
        new_total = current_total + Decimal(str(data.ownership_pct))
        if new_total > Decimal("100"):
            raise HTTPException(
                status_code=422,
                detail=(f"ownership_pct sum would be {new_total} > 100"),
            )
        obj = ContractParty(
            sales_contract_id=spa.id,
            buyer_id=data.buyer_id,
            ownership_pct=data.ownership_pct,
            party_role=data.party_role,
            signing_order=data.signing_order,
            signature_ref=data.signature_ref,
            metadata_=data.metadata,
        )
        party = await self.contract_parties.create(obj)
        event_bus.publish_detached(
            "property_dev.contract_party.added",
            data={
                "spa_id": str(spa.id),
                "buyer_id": str(data.buyer_id),
                "party_id": str(party.id),
                "ownership_pct": str(party.ownership_pct),
                "party_role": party.party_role,
                "ownership_total": str(new_total),
            },
            source_module="property_dev",
        )
        return party

    async def get_contract_party(self, party_id: uuid.UUID) -> ContractParty:
        obj = await self.contract_parties.get_by_id(party_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="ContractParty not found")
        return obj

    async def update_contract_party(self, party_id: uuid.UUID, data: ContractPartyUpdate) -> ContractParty:
        party = await self.get_contract_party(party_id)
        fields = _dump(data)
        # Validate ownership-sum if pct is changing.
        if "ownership_pct" in fields and fields["ownership_pct"] is not None:
            spa = await self.get_spa(party.sales_contract_id)
            if spa.status not in {"draft", "sent_for_signature"}:
                raise HTTPException(
                    status_code=409,
                    detail=(f"SPA in status '{spa.status}' — ownership is locked"),
                )
            parties = await self.contract_parties.list_for_contract(party.sales_contract_id)
            new_total = Decimal("0")
            for p in parties:
                if p.id == party_id:
                    new_total += Decimal(str(fields["ownership_pct"]))
                else:
                    new_total += Decimal(str(p.ownership_pct or 0))
            if new_total > Decimal("100"):
                raise HTTPException(
                    status_code=422,
                    detail=(f"ownership_pct sum would be {new_total} > 100"),
                )
        await self.contract_parties.update_fields(party_id, **fields)
        return await self.get_contract_party(party_id)

    async def remove_contract_party(self, party_id: uuid.UUID) -> None:
        party = await self.get_contract_party(party_id)
        spa = await self.get_spa(party.sales_contract_id)
        if spa.status not in {"draft", "sent_for_signature"}:
            raise HTTPException(
                status_code=409,
                detail=(f"SPA in status '{spa.status}' — parties are locked"),
            )
        await self.contract_parties.delete(party_id)
        event_bus.publish_detached(
            "property_dev.contract_party.removed",
            data={
                "spa_id": str(party.sales_contract_id),
                "buyer_id": str(party.buyer_id),
                "party_id": str(party_id),
            },
            source_module="property_dev",
        )

    # ── Dashboards (task #140) ──────────────────────────────────────────
    #
    # All six endpoints below read from the *full* R6 schema:
    #   Phase / Block / Lead / Reservation / SalesContract / PaymentSchedule
    #   / Instalment / EscrowAccount / EscrowTransaction.
    # Legacy Buyer-only data is supported as a fallback so existing
    # rows render even before they are wired to the new entities.

    async def dashboard_inventory_heatmap(
        self,
        dev_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Plot grid grouped by Phase -> Block (heat-map data source).

        Each cell is one Plot, coloured by ``status``. Layout follows
        ``Phase.sequence`` then ``Block.code``. Plots without ``block_id``
        fall back to a synthetic "Unassigned" block under the synthetic
        "—" phase so legacy data still renders.
        """
        from sqlalchemy import select as _select

        dev = await self.get_development(dev_id)

        phases = await self.phases.list_for_dev_ordered(dev_id)
        blocks = await self.blocks.list_for_development(dev_id)
        plots, _ = await self.plots.list_for_development(
            dev_id,
            offset=0,
            limit=10_000,
        )
        # House-type names (legacy fallback display).
        house_types = await self.house_types.list_for_development(dev_id)
        ht_by_id = {ht.id: ht for ht in house_types}

        blocks_by_id: dict[Any, Any] = {b.id: b for b in blocks}
        phases_by_id: dict[Any, Any] = {p.id: p for p in phases}
        # Phase id -> list[Block].
        phase_to_blocks: dict[Any, list[Any]] = {p.id: [] for p in phases}
        for b in blocks:
            phase_to_blocks.setdefault(b.phase_id, []).append(b)
        # Sort blocks inside each phase by code.
        for blist in phase_to_blocks.values():
            blist.sort(key=lambda b: b.code or "")

        # Bucket plots: (phase_id, block_id) -> [plot]
        plot_buckets: dict[tuple[Any, Any], list[Plot]] = {}
        legacy_by_ht: dict[Any, list[Plot]] = {}
        for plot in plots:
            block = blocks_by_id.get(plot.block_id) if plot.block_id else None
            if block is None:
                # Legacy: group by house_type as a fallback.
                legacy_by_ht.setdefault(plot.house_type_id, []).append(plot)
                continue
            key = (block.phase_id, block.id)
            plot_buckets.setdefault(key, []).append(plot)

        def _cell(plot: Plot) -> dict[str, Any]:
            return {
                "plot_id": str(plot.id),
                "plot_number": plot.plot_number,
                "status": plot.status,
                "area_m2": Decimal(str(plot.area_m2 or 0)),
                "price_base": Decimal(str(plot.price_base or 0)),
                "currency": plot.currency or "",
                "level_in_block": plot.level_in_block,
                "position_on_floor": plot.position_on_floor,
                "house_type_id": (str(plot.house_type_id) if plot.house_type_id else None),
            }

        phase_rows: list[dict[str, Any]] = []
        for phase in phases:
            ph_blocks = phase_to_blocks.get(phase.id, [])
            block_rows: list[dict[str, Any]] = []
            for block in ph_blocks:
                cells = plot_buckets.get((phase.id, block.id), [])
                cells.sort(
                    key=lambda p: (
                        (p.level_in_block or 0),
                        (p.position_on_floor or ""),
                        p.plot_number,
                    )
                )
                block_rows.append(
                    {
                        "block_id": str(block.id),
                        "code": block.code,
                        "name": block.name,
                        "levels_count": int(block.levels_count or 1),
                        "units_per_level": int(block.units_per_level or 1),
                        "orientation": block.orientation,
                        "units": [_cell(p) for p in cells],
                    }
                )
            phase_rows.append(
                {
                    "phase_id": str(phase.id),
                    "code": phase.code,
                    "name": phase.name,
                    "sequence": int(phase.sequence or 0),
                    "status": phase.status,
                    "blocks": block_rows,
                }
            )

        # Legacy fallback groups (no Block linkage).
        legacy_blocks: list[dict[str, Any]] = []
        for ht_id, lp in legacy_by_ht.items():
            ht = ht_by_id.get(ht_id) if ht_id is not None else None
            lp.sort(key=lambda p: p.plot_number)
            legacy_blocks.append(
                {
                    "block_id": None,
                    "code": (ht.code if ht else "—"),
                    "name": (ht.name if ht else "Unassigned"),
                    "levels_count": 1,
                    "units_per_level": len(lp),
                    "orientation": None,
                    "units": [_cell(p) for p in lp],
                }
            )
        if legacy_blocks:
            phase_rows.append(
                {
                    "phase_id": None,
                    "code": "—",
                    "name": "Legacy (no phase)",
                    "sequence": 9999,
                    "status": "planned",
                    "blocks": legacy_blocks,
                }
            )

        # Status colour legend (matches the order plots advance through).
        status_counts: dict[str, int] = {}
        for plot in plots:
            status_counts[plot.status] = status_counts.get(plot.status, 0) + 1

        _ = _select  # ruff: prevent unused-import bombs (helper kept handy)
        return {
            "development_id": dev.id,
            "currency": dev.metadata_.get("currency", "") if dev.metadata_ else "",
            "phases": phase_rows,
            "total_units": len(plots),
            "status_counts": status_counts,
        }

    async def dashboard_sales_velocity(
        self,
        dev_id: uuid.UUID,
        granularity: str = "month",
    ) -> dict[str, Any]:
        """Time-series of signed SPAs (primary source) per period.

        Primary source = ``SalesContract.signing_date`` for status in
        {signed, countersigned}. Falls back to ``Buyer.contract_signed_at``
        for legacy buyer rows that predate the SalesContract table.

        Currency is per-bucket: a list of ``{currency, revenue}`` entries
        so mixed-currency portfolios stay correct (no FX cross-conversion
        at the dashboard layer).
        """
        from sqlalchemy import select as _select

        await self.get_development(dev_id)

        # Pull SPAs (signed + countersigned) for this dev's plots.
        stmt = (
            _select(SalesContract, Plot)
            .join(Plot, Plot.id == SalesContract.plot_id)
            .where(Plot.development_id == dev_id)
            .where(SalesContract.status.in_(("signed", "countersigned")))
        )
        rows = (await self.session.execute(stmt)).all()
        spa_keys: set[uuid.UUID] = set()  # plot_ids already counted via SPA

        def _bucket(date_iso: str) -> str:
            d = date_iso[:10]
            if granularity == "quarter":
                try:
                    y, m, _ = d.split("-")
                    q = (int(m) - 1) // 3 + 1
                    return f"{y}-Q{q}"
                except Exception:  # noqa: BLE001
                    return d[:7]
            if granularity == "week":
                try:
                    dt = date.fromisoformat(d)
                    y, w, _ = dt.isocalendar()
                    return f"{y:04d}-W{w:02d}"
                except Exception:  # noqa: BLE001
                    return d
            return d[:7]  # month

        buckets: dict[str, dict[str, Any]] = {}
        currencies_seen: set[str] = set()

        for spa, plot in rows:
            signed = spa.signing_date
            if not signed:
                continue
            spa_keys.add(plot.id)
            key = _bucket(signed)
            currency = spa.currency or ""
            currencies_seen.add(currency)
            bucket = buckets.setdefault(
                key,
                {
                    "period": key,
                    "units": 0,
                    "area_m2": Decimal("0"),
                    "revenue_by_currency": {},
                },
            )
            bucket["units"] += 1
            bucket["area_m2"] += Decimal(str(plot.area_m2 or 0))
            cur_revenue = bucket["revenue_by_currency"].setdefault(
                currency,
                Decimal("0"),
            )
            bucket["revenue_by_currency"][currency] = cur_revenue + Decimal(str(spa.total_value or 0))

        # Legacy Buyer fallback — skip any buyer whose plot already has a
        # signed SPA above.
        legacy_rows = await self.pipeline.kanban_for_development(dev_id)
        for buyer, plot in legacy_rows:
            if not buyer.contract_signed_at:
                continue
            if plot is not None and plot.id in spa_keys:
                continue
            key = _bucket(buyer.contract_signed_at)
            currency = buyer.currency or ""
            currencies_seen.add(currency)
            bucket = buckets.setdefault(
                key,
                {
                    "period": key,
                    "units": 0,
                    "area_m2": Decimal("0"),
                    "revenue_by_currency": {},
                },
            )
            bucket["units"] += 1
            if plot is not None:
                bucket["area_m2"] += Decimal(str(plot.area_m2 or 0))
            cur_revenue = bucket["revenue_by_currency"].setdefault(
                currency,
                Decimal("0"),
            )
            bucket["revenue_by_currency"][currency] = cur_revenue + Decimal(str(buyer.contract_value or 0))

        series = sorted(buckets.values(), key=lambda b: b["period"])
        # Project revenue dict -> list for JSON friendliness.
        for s in series:
            s["revenue"] = [
                {
                    "currency": cur,
                    "amount": amt.quantize(Decimal("0.01")),
                }
                for cur, amt in sorted(s["revenue_by_currency"].items())
            ]
            s["area_m2"] = s["area_m2"].quantize(Decimal("0.01"))
            del s["revenue_by_currency"]

        total_units = sum(int(s["units"]) for s in series)
        total_area = sum(
            (Decimal(s["area_m2"]) for s in series),
            start=Decimal("0"),
        )
        total_by_currency: dict[str, Decimal] = {}
        for s in series:
            for entry in s["revenue"]:
                total_by_currency[entry["currency"]] = total_by_currency.get(entry["currency"], Decimal("0")) + Decimal(
                    str(entry["amount"])
                )

        _ = _select  # keep the import alias alive across method scope
        return {
            "development_id": dev_id,
            "granularity": granularity,
            "series": series,
            "currencies": sorted(currencies_seen),
            "totals": {
                "units": int(total_units),
                "area_m2": total_area.quantize(Decimal("0.01")),
                "revenue": [
                    {
                        "currency": cur,
                        "amount": amt.quantize(Decimal("0.01")),
                    }
                    for cur, amt in sorted(total_by_currency.items())
                ],
            },
        }

    async def dashboard_cashflow_waterfall(
        self,
        dev_id: uuid.UUID,
        start_month: str | None = None,
        months: int = 12,
    ) -> dict[str, Any]:
        """Monthly cash-flow projection from Instalments + Escrow.

        Three series per month bucket:
          * ``scheduled``       — sum of Instalment.amount due in month
          * ``actual_collected``— sum of EscrowTransaction direction=credit
          * ``actual_disbursed``— sum of EscrowTransaction direction=debit
        """
        from sqlalchemy import select as _select

        await self.get_development(dev_id)

        # Resolve window — default = current month + N-1 forward months.
        if not start_month or not _MONTH_RE.match(start_month):
            today = datetime.now(UTC).date()
            start_month = f"{today.year:04d}-{today.month:02d}"
        if months < 1:
            months = 1
        if months > 60:
            months = 60

        sy, sm = (int(x) for x in start_month.split("-"))
        month_keys: list[str] = []
        for i in range(months):
            mm = sm - 1 + i
            yy = sy + mm // 12
            mo = mm % 12 + 1
            month_keys.append(f"{yy:04d}-{mo:02d}")
        first_key = month_keys[0]
        last_key = month_keys[-1]

        # Fetch all relevant Instalments via PaymentSchedule -> SPA -> Plot.
        ins_stmt = (
            _select(Instalment, SalesContract, Plot)
            .join(
                PaymentSchedule,
                PaymentSchedule.id == Instalment.schedule_id,
            )
            .join(
                SalesContract,
                SalesContract.id == PaymentSchedule.sales_contract_id,
            )
            .join(Plot, Plot.id == SalesContract.plot_id)
            .where(Plot.development_id == dev_id)
        )
        ins_rows = (await self.session.execute(ins_stmt)).all()

        # Build empty buckets.
        buckets: dict[str, dict[str, Any]] = {
            k: {
                "month": k,
                "scheduled_by_currency": {},
                "collected_by_currency": {},
                "disbursed_by_currency": {},
            }
            for k in month_keys
        }
        currencies_seen: set[str] = set()

        for ins, spa, _plot in ins_rows:
            due = ins.due_date
            if not due or len(due) < 7:
                continue
            key = due[:7]
            if not (first_key <= key <= last_key):
                continue
            currency = spa.currency or ""
            currencies_seen.add(currency)
            sched = buckets[key]["scheduled_by_currency"]
            sched[currency] = sched.get(currency, Decimal("0")) + Decimal(str(ins.amount or 0))

        # Fetch all escrow transactions for this development.
        esc_stmt = (
            _select(EscrowTransaction, EscrowAccount)
            .join(
                EscrowAccount,
                EscrowAccount.id == EscrowTransaction.escrow_account_id,
            )
            .where(EscrowAccount.development_id == dev_id)
        )
        esc_rows = (await self.session.execute(esc_stmt)).all()

        for tx, acct in esc_rows:
            td = tx.transaction_date
            if not td or len(td) < 7:
                continue
            key = td[:7]
            if not (first_key <= key <= last_key):
                continue
            currency = tx.currency or acct.currency or ""
            currencies_seen.add(currency)
            target = (
                buckets[key]["collected_by_currency"]
                if tx.direction == "credit"
                else buckets[key]["disbursed_by_currency"]
            )
            target[currency] = target.get(currency, Decimal("0")) + Decimal(str(tx.amount or 0))

        def _flatten(by_cur: dict[str, Decimal]) -> list[dict[str, Any]]:
            return [
                {
                    "currency": cur,
                    "amount": amt.quantize(Decimal("0.01")),
                }
                for cur, amt in sorted(by_cur.items())
            ]

        series = []
        totals_scheduled: dict[str, Decimal] = {}
        totals_collected: dict[str, Decimal] = {}
        totals_disbursed: dict[str, Decimal] = {}
        for k in month_keys:
            b = buckets[k]
            for cur, amt in b["scheduled_by_currency"].items():
                totals_scheduled[cur] = totals_scheduled.get(cur, Decimal("0")) + amt
            for cur, amt in b["collected_by_currency"].items():
                totals_collected[cur] = totals_collected.get(cur, Decimal("0")) + amt
            for cur, amt in b["disbursed_by_currency"].items():
                totals_disbursed[cur] = totals_disbursed.get(cur, Decimal("0")) + amt
            series.append(
                {
                    "month": k,
                    "scheduled": _flatten(b["scheduled_by_currency"]),
                    "actual_collected": _flatten(b["collected_by_currency"]),
                    "actual_disbursed": _flatten(b["disbursed_by_currency"]),
                }
            )

        _ = _select  # keep alias referenced
        return {
            "development_id": dev_id,
            "start_month": first_key,
            "months": months,
            "currencies": sorted(currencies_seen),
            "series": series,
            "totals": {
                "scheduled": _flatten(totals_scheduled),
                "actual_collected": _flatten(totals_collected),
                "actual_disbursed": _flatten(totals_disbursed),
            },
        }

    async def dashboard_inventory_ageing(
        self,
        dev_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Days-on-market histogram for unsold inventory.

        Source of the start-date: Plot doesn't have a ``listed_at``
        column today, so we fall back to ``created_at``. (Migrate to
        ``listed_at`` once #138.2 lands — code is already prepared.)
        Adds a new bucket ``reserved_no_contract`` for Plots that have
        an active Reservation but no SalesContract yet.
        """
        from sqlalchemy import select as _select

        await self.get_development(dev_id)
        plots, _ = await self.plots.list_for_development(
            dev_id,
            offset=0,
            limit=10_000,
        )
        today = datetime.now(UTC).date()
        today_iso = today.isoformat()

        # Plots with active Reservation but no signed SPA.
        # Build set via subqueries.
        active_res_stmt = (
            _select(Reservation.plot_id)
            .join(Plot, Plot.id == Reservation.plot_id)
            .where(Plot.development_id == dev_id)
            .where(Reservation.status == "active")
            .where((Reservation.expires_at.is_(None)) | (Reservation.expires_at >= today_iso))
        )
        active_res_plot_ids: set[Any] = set(
            (await self.session.execute(active_res_stmt)).scalars().all(),
        )
        signed_spa_stmt = (
            _select(SalesContract.plot_id)
            .join(Plot, Plot.id == SalesContract.plot_id)
            .where(Plot.development_id == dev_id)
            .where(
                SalesContract.status.in_(("signed", "countersigned", "draft", "sent_for_signature", "partially_signed"))
            )
        )
        with_spa_plot_ids: set[Any] = set(
            (await self.session.execute(signed_spa_stmt)).scalars().all(),
        )

        buckets: dict[str, dict[str, Any]] = {
            "0-30": {"label": "0–30", "count": 0, "plots": []},
            "30-60": {"label": "30–60", "count": 0, "plots": []},
            "60-90": {"label": "60–90", "count": 0, "plots": []},
            "90+": {"label": "90+", "count": 0, "plots": []},
            "reserved_no_contract": {
                "label": "Reserved, no contract",
                "count": 0,
                "plots": [],
            },
        }

        for plot in plots:
            # Exclude already-sold inventory.
            if plot.status in {"sold", "handed_over"}:
                continue
            # Reserved-but-no-contract takes priority over ageing buckets.
            if plot.id in active_res_plot_ids and plot.id not in with_spa_plot_ids:
                key = "reserved_no_contract"
            else:
                listed_attr = getattr(plot, "listed_at", None) or plot.created_at
                try:
                    listed_date = listed_attr.date() if hasattr(listed_attr, "date") else today
                except Exception:  # noqa: BLE001
                    listed_date = today
                days = (today - listed_date).days
                if days < 30:
                    key = "0-30"
                elif days < 60:
                    key = "30-60"
                elif days < 90:
                    key = "60-90"
                else:
                    key = "90+"
            buckets[key]["count"] += 1
            listed_attr = getattr(plot, "listed_at", None) or plot.created_at
            try:
                listed_date = listed_attr.date() if hasattr(listed_attr, "date") else today
            except Exception:  # noqa: BLE001
                listed_date = today
            days_on_market = (today - listed_date).days
            buckets[key]["plots"].append(
                {
                    "plot_id": str(plot.id),
                    "plot_number": plot.plot_number,
                    "status": plot.status,
                    "days_on_market": int(days_on_market),
                    "block_id": (str(plot.block_id) if plot.block_id else None),
                    "house_type_id": (str(plot.house_type_id) if plot.house_type_id else None),
                    "price_base": Decimal(str(plot.price_base or 0)),
                    "currency": plot.currency or "",
                }
            )

        _ = _select
        return {
            "development_id": dev_id,
            "as_of": today_iso,
            "buckets": list(buckets.values()),
            "total_unsold": sum(int(b["count"]) for b in buckets.values()),
        }

    async def dashboard_funnel_conversion(
        self,
        dev_id: uuid.UUID,
        period_days: int = 90,
    ) -> dict[str, Any]:
        """5-stage funnel: Lead -> Reservation -> SPA draft -> SPA signed -> Handover.

        Counts respect ``period_days``: only entities created within the
        last N days count. Drop-off ratios drive colour quartiles on the
        frontend.
        """
        from sqlalchemy import func as _func
        from sqlalchemy import select as _select

        await self.get_development(dev_id)
        if period_days < 1:
            period_days = 1
        cutoff = datetime.now(UTC) - timedelta(days=int(period_days))
        cutoff_iso = cutoff.date().isoformat()

        # Stage 1 — Lead (any source, this development, created within window).
        lead_count = (
            await self.session.execute(
                _select(_func.count())
                .select_from(Lead)
                .where(Lead.development_id == dev_id)
                .where(Lead.created_at >= cutoff)
            )
        ).scalar_one() or 0

        # Stage 2 — Reservation (plots in this dev, created within window).
        res_count = (
            await self.session.execute(
                _select(_func.count())
                .select_from(Reservation)
                .join(Plot, Plot.id == Reservation.plot_id)
                .where(Plot.development_id == dev_id)
                .where(Reservation.created_at >= cutoff)
            )
        ).scalar_one() or 0

        # Stage 3 — SPA in draft/sent/partially_signed within window.
        spa_draft_count = (
            await self.session.execute(
                _select(_func.count())
                .select_from(SalesContract)
                .join(Plot, Plot.id == SalesContract.plot_id)
                .where(Plot.development_id == dev_id)
                .where(SalesContract.created_at >= cutoff)
            )
        ).scalar_one() or 0

        # Stage 4 — SPA signed (signing_date within window).
        spa_signed_count = (
            await self.session.execute(
                _select(_func.count())
                .select_from(SalesContract)
                .join(Plot, Plot.id == SalesContract.plot_id)
                .where(Plot.development_id == dev_id)
                .where(SalesContract.status.in_(("signed", "countersigned")))
                .where((SalesContract.signing_date.is_not(None)) & (SalesContract.signing_date >= cutoff_iso))
            )
        ).scalar_one() or 0

        # Stage 5 — Handover completed within window.
        handover_count = (
            await self.session.execute(
                _select(_func.count())
                .select_from(Handover)
                .join(Plot, Plot.id == Handover.plot_id)
                .where(Plot.development_id == dev_id)
                .where(Handover.completed_at.is_not(None))
                .where(Handover.completed_at >= cutoff_iso)
            )
        ).scalar_one() or 0

        def _drop(prev: int, cur: int) -> Decimal:
            if prev <= 0:
                return Decimal("0")
            return (Decimal(prev - cur) / Decimal(prev) * Decimal("100")).quantize(Decimal("0.1"))

        stages = [
            {
                "code": "lead",
                "label": "Lead",
                "count": int(lead_count),
                "drop_pct": Decimal("0"),
            },
            {
                "code": "reservation",
                "label": "Reservation",
                "count": int(res_count),
                "drop_pct": _drop(int(lead_count), int(res_count)),
            },
            {
                "code": "spa_draft",
                "label": "SPA draft",
                "count": int(spa_draft_count),
                "drop_pct": _drop(int(res_count), int(spa_draft_count)),
            },
            {
                "code": "spa_signed",
                "label": "SPA signed",
                "count": int(spa_signed_count),
                "drop_pct": _drop(int(spa_draft_count), int(spa_signed_count)),
            },
            {
                "code": "handover",
                "label": "Handover",
                "count": int(handover_count),
                "drop_pct": _drop(int(spa_signed_count), int(handover_count)),
            },
        ]

        # Final conversion = handover / lead.
        conv = (
            (Decimal(int(handover_count)) / Decimal(int(lead_count)) * Decimal("100")).quantize(Decimal("0.1"))
            if lead_count > 0
            else Decimal("0")
        )

        return {
            "development_id": dev_id,
            "period_days": int(period_days),
            "stages": stages,
            "totals": {
                "leads": int(lead_count),
                "conversion_pct": conv,
            },
        }

    async def dashboard_buyer_journey(
        self,
        buyer_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Cross-entity chronological timeline for one buyer.

        Walks Lead -> Reservation -> SalesContract (+ revisions) ->
        PaymentSchedule + Instalments (clustered) -> Handover -> Snags ->
        Warranty. Each event carries an ``entity`` / ``entity_id`` so the
        UI can deep-link.
        """
        from sqlalchemy import select as _select

        buyer = await self.buyers.get_by_id(buyer_id)
        if buyer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer not found",
            )

        events: list[dict[str, Any]] = []

        def _push(
            code: str,
            label: str,
            ts: str | None,
            state: str,
            *,
            entity: str | None = None,
            entity_id: str | None = None,
            detail: dict[str, Any] | None = None,
        ) -> None:
            events.append(
                {
                    "code": code,
                    "label": label,
                    "timestamp": ts,
                    "state": state,
                    "entity": entity,
                    "entity_id": entity_id,
                    "detail": detail or {},
                }
            )

        # 1) Lead — match by email, dev scope (if dev is known).
        lead_row = None
        if buyer.email:
            lead_stmt = (
                _select(Lead)
                .where(Lead.development_id == buyer.development_id)
                .where(Lead.email == buyer.email)
                .order_by(Lead.created_at)
                .limit(1)
            )
            lead_row = (await self.session.execute(lead_stmt)).scalar_one_or_none()
        if lead_row is not None:
            ts = lead_row.created_at.isoformat() if hasattr(lead_row.created_at, "isoformat") else None
            _push(
                "lead_created",
                "Lead created",
                ts,
                "completed",
                entity="lead",
                entity_id=str(lead_row.id),
                detail={"source": lead_row.source, "status": lead_row.status},
            )
        else:
            ts = buyer.created_at.isoformat() if hasattr(buyer.created_at, "isoformat") else None
            _push(
                "lead_created",
                "Lead created",
                ts,
                "completed",
                entity="buyer",
                entity_id=str(buyer.id),
            )

        # 2) Reservation — via ContractParty? simpler: by buyer_id on Reservation.
        res_stmt = _select(Reservation).where(Reservation.buyer_id == buyer_id).order_by(Reservation.created_at)
        reservations = list((await self.session.execute(res_stmt)).scalars().all())
        for res in reservations:
            ts = (
                res.deposit_paid_at.isoformat()
                if res.deposit_paid_at is not None
                else (res.created_at.isoformat() if hasattr(res.created_at, "isoformat") else None)
            )
            res_state = "completed" if res.status != "active" else "in_progress"
            _push(
                "reservation",
                "Reservation " + res.reservation_number,
                ts,
                res_state,
                entity="reservation",
                entity_id=str(res.id),
                detail={
                    "status": res.status,
                    "deposit_amount": str(res.deposit_amount),
                    "currency": res.currency,
                },
            )

        # 3) SalesContract via ContractParty (multi-buyer support).
        spa_stmt = (
            _select(SalesContract, ContractParty)
            .join(
                ContractParty,
                ContractParty.sales_contract_id == SalesContract.id,
            )
            .where(ContractParty.buyer_id == buyer_id)
            .order_by(SalesContract.created_at)
        )
        spa_rows = (await self.session.execute(spa_stmt)).all()
        spa_ids: list[uuid.UUID] = []
        for spa, party in spa_rows:
            spa_ids.append(spa.id)
            sig_state = (
                "completed"
                if spa.status in {"signed", "countersigned"}
                else ("in_progress" if spa.status in {"sent_for_signature", "partially_signed"} else "upcoming")
            )
            _push(
                "spa_signed" if spa.status in {"signed", "countersigned"} else "spa_draft",
                f"SPA {spa.contract_number}",
                spa.signing_date or None,
                sig_state,
                entity="sales_contract",
                entity_id=str(spa.id),
                detail={
                    "status": spa.status,
                    "total_value": str(spa.total_value),
                    "currency": spa.currency,
                    "ownership_pct": str(party.ownership_pct),
                    "party_role": party.party_role,
                },
            )

        # 4) PaymentSchedule + Instalments (clustered, not one-per-line).
        if spa_ids:
            sched_stmt = _select(PaymentSchedule).where(PaymentSchedule.sales_contract_id.in_(spa_ids))
            schedules = list((await self.session.execute(sched_stmt)).scalars().all())
            for sched in schedules:
                instalments = await self.instalments.list_for_schedule(sched.id)
                paid = sum(
                    (1 for ins in instalments if ins.status == "paid"),
                    start=0,
                )
                total = len(instalments)
                state = "completed" if paid == total and total > 0 else "in_progress" if paid > 0 else "upcoming"
                # Anchor timestamp = earliest pending due_date else last paid_at.
                upcoming_dates = [ins.due_date for ins in instalments if ins.due_date]
                anchor_ts = min(upcoming_dates) if upcoming_dates else None
                _push(
                    "payment_schedule",
                    f"Payment schedule ({paid}/{total} paid)",
                    anchor_ts,
                    state,
                    entity="payment_schedule",
                    entity_id=str(sched.id),
                    detail={
                        "paid": int(paid),
                        "total_lines": int(total),
                        "currency": sched.currency,
                        "status": sched.status,
                    },
                )

        # 5) Handover — by plot.
        if buyer.plot_id:
            handovers = await self.handovers.list_for_plot(buyer.plot_id)
            for h in handovers:
                if h.scheduled_at:
                    _push(
                        "handover_scheduled",
                        "Handover scheduled",
                        h.scheduled_at,
                        "in_progress" if not h.completed_at else "completed",
                        entity="handover",
                        entity_id=str(h.id),
                    )
                if h.completed_at:
                    _push(
                        "handover_completed",
                        "Handover completed",
                        h.completed_at,
                        "completed",
                        entity="handover",
                        entity_id=str(h.id),
                    )
                # 6) Snags raised at this handover.
                snags = await self.snags.list_for_handover(h.id)
                for s in snags:
                    if s.reported_at:
                        s_state = "completed" if s.status in {"fixed", "wont_fix"} else "in_progress"
                        _push(
                            "snag_raised",
                            f"Snag ({s.severity})",
                            s.reported_at,
                            s_state,
                            entity="snag",
                            entity_id=str(s.id),
                            detail={"status": s.status},
                        )

        # 7) Warranty claims.
        warranties = await self.warranty.list_for_buyer(buyer_id)
        for w in warranties:
            if w.raised_at:
                _push(
                    "warranty_raised",
                    f"Warranty: {w.category}",
                    w.raised_at,
                    "completed" if w.closed_at else "in_progress",
                    entity="warranty",
                    entity_id=str(w.id),
                )
            if w.closed_at:
                _push(
                    "warranty_closed",
                    "Warranty closed",
                    w.closed_at,
                    "completed",
                    entity="warranty",
                    entity_id=str(w.id),
                )

        # Chronological sort — missing timestamps go last.
        events.sort(key=lambda e: e["timestamp"] or "9999-99-99")
        return {
            "buyer_id": buyer.id,
            "development_id": buyer.development_id,
            "full_name": buyer.full_name,
            "status": buyer.status,
            "events": events,
            "event_count": len(events),
        }


# ════════════════════════════════════════════════════════════════════════
# Task #138 — Broker / Commission / Escrow / PriceMatrix / Phase / Block
# ════════════════════════════════════════════════════════════════════════


# ── State machines (commissions + escrow) ──────────────────────────────


_COMMISSION_TRANSITIONS: dict[str, set[str]] = {
    "accrued": {"approved", "cancelled"},
    "approved": {"paid", "cancelled"},
    "paid": set(),
    "cancelled": set(),
}


_ESCROW_RECONCILIATION_TRANSITIONS: dict[str, set[str]] = {
    "unreconciled": {"matched", "disputed"},
    "matched": {"disputed"},
    "disputed": {"matched"},
}


def allowed_commission_transitions(current: str) -> set[str]:
    """Return the valid next states for a CommissionAccrual."""
    return set(_COMMISSION_TRANSITIONS.get(current, set()))


def allowed_escrow_reconciliation_transitions(current: str) -> set[str]:
    """Return the valid next reconciliation states for an EscrowTransaction."""
    return set(_ESCROW_RECONCILIATION_TRANSITIONS.get(current, set()))


# ── Pure commission math ───────────────────────────────────────────────


def compute_commission_amount(
    base_amount: Decimal | int | float | str,
    structure_type: str,
    structure: dict[str, Any],
) -> Decimal:
    """Compute the commission for a deal of size ``base_amount``.

    All inputs are coerced through Decimal so callers may pass floats or
    strings safely. Ladder logic picks the tier whose threshold is the
    largest value <= base_amount.

    Pure: no DB / I/O. Used both by the event-driven accrual flow and the
    unit tests in ``test_property_dev_broker_escrow_pricematrix.py``.
    """
    base = Decimal(str(base_amount or 0))
    if structure_type == "flat":
        return Decimal(str(structure.get("amount", 0) or 0))
    if structure_type == "percent":
        pct = Decimal(str(structure.get("pct", 0) or 0))
        return (base * pct / Decimal("100")).quantize(Decimal("0.01"))
    if structure_type == "ladder":
        tiers = structure.get("tiers") or []
        # Sort ascending by threshold; the largest threshold ≤ base wins.
        sorted_tiers = sorted(tiers, key=lambda t: Decimal(str(t.get("threshold", 0) or 0)))
        applicable_pct = Decimal("0")
        for tier in sorted_tiers:
            threshold = Decimal(str(tier.get("threshold", 0) or 0))
            if base >= threshold:
                applicable_pct = Decimal(str(tier.get("pct", 0) or 0))
        return (base * applicable_pct / Decimal("100")).quantize(Decimal("0.01"))
    return Decimal("0")


def compute_withholding(
    commission: Decimal | int | float | str,
    withholding_pct: Decimal | int | float | str,
) -> tuple[Decimal, Decimal]:
    """Return ``(withholding_amount, net_payable)`` from gross commission.

    Pure: no DB.
    """
    gross = Decimal(str(commission or 0))
    pct = Decimal(str(withholding_pct or 0))
    withholding = (gross * pct / Decimal("100")).quantize(Decimal("0.01"))
    net = (gross - withholding).quantize(Decimal("0.01"))
    return withholding, net


# ── Pure PriceMatrix evaluation ────────────────────────────────────────


def _rule_matches(
    factor_type: str,
    condition: dict[str, Any],
    plot: Any,
    *,
    on_date: str,
) -> bool:
    """Return True if a single PriceMatrix rule applies to ``plot``."""
    md = _attr(plot, "metadata_", {}) or _attr(plot, "metadata", {}) or {}
    if factor_type == "floor":
        level = _attr(plot, "level_in_block", None)
        if level is None:
            return False
        minimum = condition.get("min")
        maximum = condition.get("max")
        if minimum is not None and level < int(minimum):
            return False
        if maximum is not None and level > int(maximum):
            return False
        return True
    if factor_type == "view":
        target = condition.get("value")
        return bool(target) and (md.get("view") == target)
    if factor_type == "orientation":
        target = condition.get("value")
        return bool(target) and (_attr(plot, "orientation", None) == target)
    if factor_type == "corner":
        target = condition.get("value", True)
        is_corner = bool(md.get("is_corner") or md.get("corner"))
        return is_corner == bool(target)
    if factor_type == "launch_discount":
        before = condition.get("before")
        if not before:
            return False
        # Discount applies when ``on_date`` is strictly before the cutoff.
        return on_date < before
    if factor_type == "phase_escalator":
        phase_code = condition.get("phase_code")
        return bool(phase_code) and md.get("phase_code") == phase_code
    return False


def compute_plot_price_breakdown(
    plot: Any,
    matrix: Any,
    *,
    on_date: str,
) -> dict[str, Any]:
    """Apply a PriceMatrix to a Plot and return the full breakdown.

    Result keys: ``base_price``, ``applied_rules``, ``combined_multiplier``,
    ``final_price``. Floats are forbidden — every monetary computation
    runs in Decimal space to avoid drift on % math.

    Pure: no DB / I/O.
    """
    area = Decimal(str(_attr(plot, "area_m2", 0) or 0))
    base_per_m2 = Decimal(str(_attr(matrix, "base_price_per_m2", 0) or 0))
    base_price = (area * base_per_m2).quantize(Decimal("0.01"))

    rules = _attr(matrix, "rules", []) or []
    applied: list[dict[str, Any]] = []
    combined = Decimal("1")
    for rule in rules:
        factor_type = rule.get("factor_type") if isinstance(rule, dict) else None
        if factor_type is None:
            continue
        condition = rule.get("condition") or {}
        multiplier = Decimal(str(rule.get("multiplier", 1) or 1))
        if _rule_matches(factor_type, condition, plot, on_date=on_date):
            combined = combined * multiplier
            applied.append(
                {
                    "factor_type": factor_type,
                    "condition": condition,
                    "multiplier": str(multiplier),
                }
            )

    combined = combined.quantize(Decimal("0.0001"))
    final = (base_price * combined).quantize(Decimal("0.01"))
    return {
        "base_price": base_price,
        "applied_rules": applied,
        "combined_multiplier": combined,
        "final_price": final,
    }


# ── PropertyDevService — extension methods ─────────────────────────────


# We attach commission/escrow/etc methods to PropertyDevService below.
# Done as a monkey-patch via ``setattr`` after the class body would also
# work but a subclass-style extension is harder to test — instead we
# define standalone helpers that take a ``svc`` and add bound-method
# shims at the bottom of this file.


async def _svc_create_broker(svc: PropertyDevService, data: Any) -> Broker:
    obj = Broker(
        tenant_id=data.tenant_id,
        name=data.name,
        license_number=data.license_number,
        jurisdiction=data.jurisdiction.upper() if data.jurisdiction else "",
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        default_commission_pct=data.default_commission_pct,
        kyc_status=data.kyc_status,
        active=data.active,
        metadata_=data.metadata,
    )
    return await svc.brokers.create(obj)


async def _svc_get_broker(svc: PropertyDevService, broker_id: uuid.UUID) -> Broker:
    obj = await svc.brokers.get_by_id(broker_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Broker not found")
    return obj


async def _svc_update_broker(
    svc: PropertyDevService,
    broker_id: uuid.UUID,
    data: Any,
) -> Broker:
    await _svc_get_broker(svc, broker_id)
    fields = _dump(data)
    # ISO 3166-2 stays case-normalised.
    if "jurisdiction" in fields and isinstance(fields["jurisdiction"], str):
        fields["jurisdiction"] = fields["jurisdiction"].upper()
    await svc.brokers.update_fields(broker_id, **fields)
    return await _svc_get_broker(svc, broker_id)


async def _svc_verify_broker_kyc(
    svc: PropertyDevService,
    broker_id: uuid.UUID,
) -> Broker:
    broker = await _svc_get_broker(svc, broker_id)
    if broker.kyc_status == "verified":
        return broker
    now = datetime.now(UTC)
    await svc.brokers.update_fields(broker_id, kyc_status="verified", kyc_verified_at=now)
    return await _svc_get_broker(svc, broker_id)


async def _svc_create_agreement(
    svc: PropertyDevService,
    data: Any,
) -> CommissionAgreement:
    await _svc_get_broker(svc, data.broker_id)
    if data.development_id is not None:
        await svc.get_development(data.development_id)
    obj = CommissionAgreement(
        broker_id=data.broker_id,
        development_id=data.development_id,
        specific_plot_ids=[str(p) for p in (data.specific_plot_ids or [])] or None,
        structure_type=data.structure_type,
        structure=data.structure,
        accrual_trigger=data.accrual_trigger,
        payout_terms=data.payout_terms,
        withholding_tax_pct=data.withholding_tax_pct,
        currency=data.currency.upper(),
        effective_from=data.effective_from,
        effective_to=data.effective_to,
        status=data.status,
        metadata_=data.metadata,
    )
    return await svc.commission_agreements.create(obj)


async def _svc_get_agreement(
    svc: PropertyDevService,
    agreement_id: uuid.UUID,
) -> CommissionAgreement:
    obj = await svc.commission_agreements.get_by_id(agreement_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="CommissionAgreement not found")
    return obj


async def _svc_update_agreement(
    svc: PropertyDevService,
    agreement_id: uuid.UUID,
    data: Any,
) -> CommissionAgreement:
    await _svc_get_agreement(svc, agreement_id)
    fields = _dump(data)
    if "currency" in fields and isinstance(fields["currency"], str):
        fields["currency"] = fields["currency"].upper()
    if "specific_plot_ids" in fields and fields["specific_plot_ids"] is not None:
        fields["specific_plot_ids"] = [str(p) for p in fields["specific_plot_ids"]]
    await svc.commission_agreements.update_fields(agreement_id, **fields)
    return await _svc_get_agreement(svc, agreement_id)


async def _svc_compute_commission_on_event(
    svc: PropertyDevService,
    *,
    event_type: str,
    development_id: uuid.UUID,
    base_amount: Decimal,
    currency: str,
    trigger_entity_type: str,
    trigger_entity_id: uuid.UUID,
    plot_id: uuid.UUID | None = None,
    on_date: str | None = None,
) -> list[CommissionAccrual]:
    """For each matching active agreement, create + persist a CommissionAccrual.

    Publishes ``property_dev.commission.accrued`` per accrual.
    """
    on_date_str = on_date or _today_iso()
    agreements = await svc.commission_agreements.list_matching(
        development_id=development_id,
        on_date=on_date_str,
        accrual_trigger=event_type,
    )
    accruals: list[CommissionAccrual] = []
    for agreement in agreements:
        # Specific-plot restriction (when set, the accrual only fires for
        # listed plots).
        if agreement.specific_plot_ids:
            allowed = {str(x) for x in agreement.specific_plot_ids}
            if plot_id is None or str(plot_id) not in allowed:
                continue
        commission_amount = compute_commission_amount(
            base_amount,
            agreement.structure_type,
            agreement.structure or {},
        )
        withholding, net = compute_withholding(
            commission_amount,
            agreement.withholding_tax_pct or 0,
        )
        now = datetime.now(UTC)
        accrual = CommissionAccrual(
            agreement_id=agreement.id,
            broker_id=agreement.broker_id,
            trigger_event=event_type,
            trigger_entity_type=trigger_entity_type,
            trigger_entity_id=trigger_entity_id,
            base_amount=Decimal(str(base_amount)),
            commission_amount=commission_amount,
            currency=(currency or agreement.currency or "").upper(),
            state="accrued",
            accrued_at=now,
            withholding_amount=withholding,
            net_payable=net,
            metadata_={"source": "auto_event"},
        )
        accrual = await svc.commission_accruals.create(accrual)
        accruals.append(accrual)
        event_bus.publish_detached(
            "property_dev.commission.accrued",
            data={
                "accrual_id": str(accrual.id),
                "agreement_id": str(accrual.agreement_id),
                "broker_id": str(accrual.broker_id),
                "trigger_event": event_type,
                "base_amount": str(accrual.base_amount),
                "commission_amount": str(accrual.commission_amount),
                "currency": accrual.currency,
            },
            source_module="property_dev",
        )
    return accruals


async def _svc_approve_commission(
    svc: PropertyDevService,
    accrual_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> CommissionAccrual:
    accrual = await svc.commission_accruals.get_by_id(accrual_id)
    if accrual is None:
        raise HTTPException(
            status_code=404, detail=translate("errors.commission_accrual_not_found", locale=get_locale())
        )
    target = "approved"
    if target == accrual.state:
        return accrual
    if target not in allowed_commission_transitions(accrual.state):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid commission transition: {accrual.state} -> {target}",
        )
    md = dict(accrual.metadata_ or {})
    if user_id is not None:
        md["approved_by"] = str(user_id)
    await svc.commission_accruals.update_fields(
        accrual_id,
        state="approved",
        approved_at=datetime.now(UTC),
        metadata_=md,
    )
    updated = await svc.commission_accruals.get_by_id(accrual_id)
    event_bus.publish_detached(
        "property_dev.commission.approved",
        data={
            "accrual_id": str(accrual_id),
            "broker_id": str(updated.broker_id) if updated else None,
            "approved_by": str(user_id) if user_id else None,
        },
        source_module="property_dev",
    )
    return updated  # type: ignore[return-value]


async def _svc_pay_commission(
    svc: PropertyDevService,
    accrual_id: uuid.UUID,
    payment_ref: str,
    user_id: uuid.UUID | None = None,
) -> CommissionAccrual:
    accrual = await svc.commission_accruals.get_by_id(accrual_id)
    if accrual is None:
        raise HTTPException(
            status_code=404, detail=translate("errors.commission_accrual_not_found", locale=get_locale())
        )
    target = "paid"
    if target not in allowed_commission_transitions(accrual.state):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid commission transition: {accrual.state} -> {target}",
        )
    md = dict(accrual.metadata_ or {})
    if user_id is not None:
        md["paid_by"] = str(user_id)
    await svc.commission_accruals.update_fields(
        accrual_id,
        state="paid",
        paid_at=datetime.now(UTC),
        payment_ref=payment_ref,
        metadata_=md,
    )
    updated = await svc.commission_accruals.get_by_id(accrual_id)
    event_bus.publish_detached(
        "property_dev.commission.paid",
        data={
            "accrual_id": str(accrual_id),
            "broker_id": str(updated.broker_id) if updated else None,
            "amount": str(updated.commission_amount) if updated else "0",
            "currency": updated.currency if updated else "",
            "payment_ref": payment_ref,
        },
        source_module="property_dev",
    )
    return updated  # type: ignore[return-value]


# ── Escrow ─────────────────────────────────────────────────────────────


async def _svc_create_escrow_account(
    svc: PropertyDevService,
    data: Any,
) -> EscrowAccount:
    await svc.get_development(data.development_id)
    obj = EscrowAccount(
        development_id=data.development_id,
        regulator_ref=data.regulator_ref,
        regulator_account_number=data.regulator_account_number,
        bank_name=data.bank_name,
        iban=data.iban,
        swift_bic=data.swift_bic,
        currency=data.currency.upper(),
        opened_at=data.opened_at,
        is_active=data.is_active,
        metadata_=data.metadata,
    )
    return await svc.escrow_accounts.create(obj)


async def _svc_get_escrow_account(
    svc: PropertyDevService,
    account_id: uuid.UUID,
) -> EscrowAccount:
    obj = await svc.escrow_accounts.get_by_id(account_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EscrowAccount not found")
    return obj


async def _svc_update_escrow_account(
    svc: PropertyDevService,
    account_id: uuid.UUID,
    data: Any,
) -> EscrowAccount:
    await _svc_get_escrow_account(svc, account_id)
    await svc.escrow_accounts.update_fields(account_id, **_dump(data))
    return await _svc_get_escrow_account(svc, account_id)


async def _svc_create_escrow_transaction(
    svc: PropertyDevService,
    data: Any,
) -> EscrowTransaction:
    account = await _svc_get_escrow_account(svc, data.escrow_account_id)
    if account.currency and data.currency.upper() != account.currency.upper():
        raise HTTPException(
            status_code=422,
            detail=(f"Transaction currency {data.currency} does not match escrow account currency {account.currency}"),
        )
    obj = EscrowTransaction(
        escrow_account_id=data.escrow_account_id,
        direction=data.direction,
        amount=data.amount,
        currency=data.currency.upper(),
        source_type=data.source_type,
        source_instalment_id=data.source_instalment_id,
        source_reference=data.source_reference,
        bank_reference=data.bank_reference,
        transaction_date=data.transaction_date,
        reconciliation_state="unreconciled",
        metadata_=data.metadata,
    )
    created = await svc.escrow_transactions.create(obj)
    event_bus.publish_detached(
        "property_dev.escrow.transaction.created",
        data={
            "transaction_id": str(created.id),
            "escrow_account_id": str(created.escrow_account_id),
            "direction": created.direction,
            "amount": str(created.amount),
            "currency": created.currency,
            "source_type": created.source_type,
        },
        source_module="property_dev",
    )
    return created


async def _svc_reconcile_escrow_transaction(
    svc: PropertyDevService,
    tx_id: uuid.UUID,
    bank_ref: str,
    user_id: uuid.UUID | None = None,
) -> EscrowTransaction:
    tx = await svc.escrow_transactions.get_by_id(tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=translate("errors.escrow_not_found", locale=get_locale()))
    target = "matched"
    if target == tx.reconciliation_state:
        return tx
    if target not in allowed_escrow_reconciliation_transitions(tx.reconciliation_state):
        raise HTTPException(
            status_code=409,
            detail=(f"Invalid reconciliation transition: {tx.reconciliation_state} -> {target}"),
        )
    await svc.escrow_transactions.update_fields(
        tx_id,
        reconciliation_state="matched",
        bank_reference=bank_ref,
        reconciled_at=datetime.now(UTC),
        reconciled_by_user_id=user_id,
    )
    updated = await svc.escrow_transactions.get_by_id(tx_id)
    event_bus.publish_detached(
        "property_dev.escrow.transaction.reconciled",
        data={
            "transaction_id": str(tx_id),
            "bank_reference": bank_ref,
            "reconciled_by_user_id": str(user_id) if user_id else None,
        },
        source_module="property_dev",
    )
    return updated  # type: ignore[return-value]


async def _svc_compute_escrow_balance(
    svc: PropertyDevService,
    account_id: uuid.UUID,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    account = await _svc_get_escrow_account(svc, account_id)
    breakdown = await svc.escrow_transactions.compute_balance(
        account_id,
        as_of_date=as_of_date,
    )
    breakdown["escrow_account_id"] = account.id
    breakdown["currency"] = account.currency
    breakdown["as_of_date"] = as_of_date
    return breakdown


# ── PriceMatrix ────────────────────────────────────────────────────────


async def _svc_create_price_matrix(
    svc: PropertyDevService,
    data: Any,
) -> PriceMatrix:
    await svc.get_development(data.development_id)
    rules_dump: list[dict[str, Any]] = []
    for rule in data.rules:
        rules_dump.append(
            {
                "factor_type": rule.factor_type,
                "condition": rule.condition,
                "multiplier": str(rule.multiplier),
            }
        )
    obj = PriceMatrix(
        development_id=data.development_id,
        name=data.name,
        base_price_per_m2=data.base_price_per_m2,
        currency=data.currency.upper(),
        effective_from=data.effective_from,
        effective_to=data.effective_to,
        rules=rules_dump,
        status=data.status,
        version=data.version,
        metadata_=data.metadata,
    )
    return await svc.price_matrices.create(obj)


async def _svc_get_price_matrix(
    svc: PropertyDevService,
    matrix_id: uuid.UUID,
) -> PriceMatrix:
    obj = await svc.price_matrices.get_by_id(matrix_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="PriceMatrix not found")
    return obj


async def _svc_update_price_matrix(
    svc: PropertyDevService,
    matrix_id: uuid.UUID,
    data: Any,
) -> PriceMatrix:
    await _svc_get_price_matrix(svc, matrix_id)
    fields = _dump(data)
    if fields.get("rules") is not None:
        coerced: list[dict[str, Any]] = []
        for rule in fields["rules"]:
            if isinstance(rule, dict):
                coerced.append(
                    {
                        "factor_type": rule.get("factor_type"),
                        "condition": rule.get("condition", {}),
                        "multiplier": str(rule.get("multiplier", 1)),
                    }
                )
            else:
                coerced.append(
                    {
                        "factor_type": rule.factor_type,
                        "condition": rule.condition,
                        "multiplier": str(rule.multiplier),
                    }
                )
        fields["rules"] = coerced
    await svc.price_matrices.update_fields(matrix_id, **fields)
    return await _svc_get_price_matrix(svc, matrix_id)


async def _svc_activate_price_matrix(
    svc: PropertyDevService,
    matrix_id: uuid.UUID,
) -> PriceMatrix:
    matrix = await _svc_get_price_matrix(svc, matrix_id)
    if matrix.status == "active":
        return matrix
    await svc.price_matrices.update_fields(matrix_id, status="active")
    activated = await _svc_get_price_matrix(svc, matrix_id)
    event_bus.publish_detached(
        "property_dev.price_matrix.activated",
        data={
            "matrix_id": str(matrix_id),
            "development_id": str(activated.development_id),
            "version": activated.version,
            "effective_from": activated.effective_from,
        },
        source_module="property_dev",
    )
    return activated


async def _svc_compute_plot_price(
    svc: PropertyDevService,
    plot_id: uuid.UUID,
    *,
    on_date: str | None = None,
    matrix_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    plot = await svc.get_plot(plot_id)
    target_date = on_date or _today_iso()
    if matrix_id is not None:
        matrix = await _svc_get_price_matrix(svc, matrix_id)
    else:
        matrix = await svc.price_matrices.find_active_for_dev_on_date(
            plot.development_id,
            target_date,
        )
    if matrix is None:
        # No active matrix → return zero-rule breakdown with the explicit
        # price_base override (priority 1) so callers always get a number.
        explicit = Decimal(str(plot.price_base or 0))
        return {
            "plot_id": plot.id,
            "matrix_id": None,
            "currency": plot.currency,
            "base_price_per_m2": Decimal("0"),
            "area_m2": Decimal(str(plot.area_m2 or 0)),
            "base_price": explicit,
            "applied_rules": [],
            "combined_multiplier": Decimal("1"),
            "final_price": explicit,
        }
    breakdown = compute_plot_price_breakdown(plot, matrix, on_date=target_date)
    breakdown["plot_id"] = plot.id
    breakdown["matrix_id"] = matrix.id
    breakdown["currency"] = matrix.currency
    breakdown["base_price_per_m2"] = Decimal(str(matrix.base_price_per_m2))
    breakdown["area_m2"] = Decimal(str(plot.area_m2 or 0))
    return breakdown


async def _svc_bulk_recompute_dev_prices(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
) -> dict[str, Any]:
    dev = await svc.get_development(dev_id)
    dev_id_value = dev.id
    today = _today_iso()
    matrix = await svc.price_matrices.find_active_for_dev_on_date(dev_id, today)
    if matrix is None:
        raise HTTPException(
            status_code=409,
            detail="No active PriceMatrix found for the development",
        )
    matrix_id_value = matrix.id
    rows, _ = await svc.plots.list_for_development(
        dev_id,
        offset=0,
        limit=10_000,
    )
    # Snapshot all needed attributes BEFORE the first update_fields call —
    # ``_BaseRepo.update_fields`` runs ``session.expire_all`` after every
    # write, which would otherwise force a lazy load on ``plot.id`` /
    # ``plot.computed_price`` from inside a non-greenlet context and
    # raise MissingGreenlet.
    snapshots: list[tuple[uuid.UUID, Decimal | None, dict[str, Any]]] = []
    for plot in rows:
        snapshots.append(
            (
                plot.id,
                (Decimal(str(plot.computed_price)) if plot.computed_price is not None else None),
                compute_plot_price_breakdown(plot, matrix, on_date=today),
            )
        )
    plots_updated = 0
    plots_unchanged = 0
    for plot_id, prev_price, breakdown in snapshots:
        new_price = breakdown["final_price"]
        if prev_price is None or prev_price != new_price:
            await svc.plots.update_fields(plot_id, computed_price=new_price)
            plots_updated += 1
        else:
            plots_unchanged += 1
    return {
        "matrix_id": matrix_id_value,
        "development_id": dev_id_value,
        "plots_updated": plots_updated,
        "plots_unchanged": plots_unchanged,
    }


# ── Phase / Block ──────────────────────────────────────────────────────


async def _svc_create_phase(svc: PropertyDevService, data: Any) -> Phase:
    await svc.get_development(data.development_id)
    obj = Phase(
        development_id=data.development_id,
        code=data.code,
        name=data.name,
        sequence=data.sequence,
        planned_start=data.planned_start,
        planned_end=data.planned_end,
        status=data.status,
        metadata_=data.metadata,
    )
    return await svc.phases.create(obj)


async def _svc_get_phase(svc: PropertyDevService, phase_id: uuid.UUID) -> Phase:
    obj = await svc.phases.get_by_id(phase_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Phase not found")
    return obj


async def _svc_update_phase(
    svc: PropertyDevService,
    phase_id: uuid.UUID,
    data: Any,
) -> Phase:
    await _svc_get_phase(svc, phase_id)
    await svc.phases.update_fields(phase_id, **_dump(data))
    return await _svc_get_phase(svc, phase_id)


async def _svc_create_block(svc: PropertyDevService, data: Any) -> Block:
    await _svc_get_phase(svc, data.phase_id)
    obj = Block(
        phase_id=data.phase_id,
        code=data.code,
        name=data.name,
        levels_count=data.levels_count,
        units_per_level=data.units_per_level,
        orientation=data.orientation,
        geo_coordinates=data.geo_coordinates,
        status=data.status,
        metadata_=data.metadata,
    )
    return await svc.blocks.create(obj)


async def _svc_get_block(svc: PropertyDevService, block_id: uuid.UUID) -> Block:
    obj = await svc.blocks.get_by_id(block_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return obj


async def _svc_update_block(
    svc: PropertyDevService,
    block_id: uuid.UUID,
    data: Any,
) -> Block:
    await _svc_get_block(svc, block_id)
    await svc.blocks.update_fields(block_id, **_dump(data))
    return await _svc_get_block(svc, block_id)


# ── Regulator reports (RERA / MAHARERA / 214-ФЗ) ──────────────────────


def _render_regulator_pdf(
    *,
    regulator: str,
    development_name: str,
    development_code: str,
    quarter: str,
    summary: dict[str, Any],
) -> bytes:
    """Render a real PDF for a regulator quarterly disclosure.

    Uses reportlab (already a hard dep). Layout is minimal but real —
    header + project block + key metrics table — so the file is a valid,
    rendered PDF that opens in any reader, not an empty stub.
    """
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"{regulator} Quarterly Disclosure",
        author="OpenConstructionERP / DataDrivenConstruction",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            f"<b>{regulator} — Quarterly Disclosure ({quarter})</b>",
            styles["Title"],
        ),
        Spacer(1, 0.6 * cm),
        Paragraph(
            f"<b>Development:</b> {development_name} (<font face='Courier'>{development_code}</font>)",
            styles["Normal"],
        ),
        Paragraph(
            f"<b>Reporting period:</b> {quarter}",
            styles["Normal"],
        ),
        Paragraph(
            f"<b>Currency:</b> {summary.get('currency', '—')}",
            styles["Normal"],
        ),
        Spacer(1, 0.4 * cm),
    ]
    rows = [["Metric", "Value"]]
    for key, value in summary.items():
        rows.append([str(key), str(value)])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f3f4f6"), colors.white]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.8 * cm))
    story.append(
        Paragraph(
            "<i>This disclosure is generated by OpenConstructionERP "
            "(DataDrivenConstruction). All figures are derived from the "
            "live property_dev module ledger as of the report timestamp.</i>",
            styles["Italic"],
        )
    )
    doc.build(story)
    return buf.getvalue()


async def _svc_collect_regulator_summary(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
    quarter: str,
) -> tuple[Development, dict[str, Any]]:
    """Aggregate the disclosure metrics for one development + quarter."""
    dev = await svc.get_development(dev_id)
    plots_by_status = await svc.plots.count_for_development_by_status(dev_id)
    buyers_by_status = await svc.buyers.count_for_development_by_status(dev_id)
    contracted_value = await svc.buyers.sum_contract_value(
        dev_id,
        status_in=["contracted", "completed"],
    )
    accounts = await svc.escrow_accounts.list_for_development(dev_id)
    escrow_summary: dict[str, dict[str, Any]] = {}
    for acc in accounts:
        balance = await svc.escrow_transactions.compute_balance(acc.id)
        escrow_summary[f"escrow_{acc.currency}_{acc.regulator_ref}"] = {
            "credit": str(balance["credit_total"]),
            "debit": str(balance["debit_total"]),
            "balance": str(balance["balance"]),
            "unreconciled": balance["unreconciled_count"],
        }
    sold = plots_by_status.get("sold", 0) + plots_by_status.get("handed_over", 0)
    total_plots = sum(plots_by_status.values())
    currency = ""
    rows, _ = await svc.buyers.list_for_development(dev_id, offset=0, limit=1)
    if rows and rows[0].currency:
        currency = rows[0].currency
    summary: dict[str, Any] = {
        "currency": currency,
        "quarter": quarter,
        "total_plots": total_plots,
        "plots_sold": sold,
        "plots_reserved": plots_by_status.get("reserved", 0),
        "plots_handed_over": plots_by_status.get("handed_over", 0),
        "buyers_contracted": buyers_by_status.get("contracted", 0),
        "buyers_completed": buyers_by_status.get("completed", 0),
        "buyers_cancelled": buyers_by_status.get("cancelled", 0),
        "contracted_value": str(contracted_value or 0),
    }
    summary.update(escrow_summary)
    return dev, summary


async def _svc_generate_regulator_report(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
    quarter: str,
    regulator: str,
) -> dict[str, Any]:
    """Generic per-regulator report generator. RERA / MAHARERA / 214-ФЗ
    differ in title + label set but the data extraction logic is shared.
    """
    if not _QUARTER_RE.match(quarter):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid quarter format {quarter!r}: expected e.g. 2026-Q1",
        )
    dev, summary = await _svc_collect_regulator_summary(svc, dev_id, quarter)
    if regulator == "RERA":
        title = "RERA Dubai (DLD) Quarterly Disclosure"
        summary["regulator_law"] = "Law No. (8) of 2007 — RERA Dubai"
    elif regulator == "MAHARERA":
        title = "MahaRERA Form 5 — Quarterly Project Update"
        summary["regulator_law"] = "RERA Act 2016 — MahaRERA Rule 5"
    elif regulator == "214_FZ":
        title = "ФЗ-214 Ежеквартальный отчёт застройщика"
        summary["regulator_law"] = "ФЗ № 214 от 30.12.2004"
    else:
        title = f"{regulator} Disclosure"
    pdf_bytes = _render_regulator_pdf(
        regulator=title,
        development_name=dev.name or dev.code,
        development_code=dev.code,
        quarter=quarter,
        summary=summary,
    )
    import base64

    payload = {
        "development_id": dev.id,
        "regulator": regulator,
        "quarter": quarter,
        "generated_at": datetime.now(UTC),
        "currency": summary.get("currency", ""),
        "summary": summary,
        "pdf_size_bytes": len(pdf_bytes),
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
    }
    event_bus.publish_detached(
        "property_dev.regulator_report.generated",
        data={
            "development_id": str(dev.id),
            "regulator": regulator,
            "quarter": quarter,
            "pdf_size_bytes": payload["pdf_size_bytes"],
        },
        source_module="property_dev",
    )
    return payload


_QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")


# ── Bind extension methods to PropertyDevService ───────────────────────


PropertyDevService.create_broker = _svc_create_broker  # type: ignore[attr-defined]
PropertyDevService.get_broker = _svc_get_broker  # type: ignore[attr-defined]
PropertyDevService.update_broker = _svc_update_broker  # type: ignore[attr-defined]
PropertyDevService.verify_broker_kyc = _svc_verify_broker_kyc  # type: ignore[attr-defined]
PropertyDevService.create_agreement = _svc_create_agreement  # type: ignore[attr-defined]
PropertyDevService.get_agreement = _svc_get_agreement  # type: ignore[attr-defined]
PropertyDevService.update_agreement = _svc_update_agreement  # type: ignore[attr-defined]
PropertyDevService.compute_commission_on_event = (  # type: ignore[attr-defined]
    _svc_compute_commission_on_event
)
PropertyDevService.approve_commission = _svc_approve_commission  # type: ignore[attr-defined]
PropertyDevService.pay_commission = _svc_pay_commission  # type: ignore[attr-defined]
PropertyDevService.create_escrow_account = _svc_create_escrow_account  # type: ignore[attr-defined]
PropertyDevService.get_escrow_account = _svc_get_escrow_account  # type: ignore[attr-defined]
PropertyDevService.update_escrow_account = _svc_update_escrow_account  # type: ignore[attr-defined]
PropertyDevService.create_escrow_transaction = (  # type: ignore[attr-defined]
    _svc_create_escrow_transaction
)
PropertyDevService.reconcile_escrow_transaction = (  # type: ignore[attr-defined]
    _svc_reconcile_escrow_transaction
)
PropertyDevService.compute_escrow_balance = _svc_compute_escrow_balance  # type: ignore[attr-defined]
PropertyDevService.create_price_matrix = _svc_create_price_matrix  # type: ignore[attr-defined]
PropertyDevService.get_price_matrix = _svc_get_price_matrix  # type: ignore[attr-defined]
PropertyDevService.update_price_matrix = _svc_update_price_matrix  # type: ignore[attr-defined]
PropertyDevService.activate_price_matrix = _svc_activate_price_matrix  # type: ignore[attr-defined]
PropertyDevService.compute_plot_price = _svc_compute_plot_price  # type: ignore[attr-defined]
PropertyDevService.bulk_recompute_dev_prices = (  # type: ignore[attr-defined]
    _svc_bulk_recompute_dev_prices
)
PropertyDevService.create_phase = _svc_create_phase  # type: ignore[attr-defined]
PropertyDevService.get_phase = _svc_get_phase  # type: ignore[attr-defined]
PropertyDevService.update_phase = _svc_update_phase  # type: ignore[attr-defined]
PropertyDevService.create_block = _svc_create_block  # type: ignore[attr-defined]
PropertyDevService.get_block = _svc_get_block  # type: ignore[attr-defined]
PropertyDevService.update_block = _svc_update_block  # type: ignore[attr-defined]
PropertyDevService.generate_regulator_report = (  # type: ignore[attr-defined]
    _svc_generate_regulator_report
)


async def _svc_generate_regulator_report_RERA(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
    quarter: str,
) -> dict[str, Any]:
    return await _svc_generate_regulator_report(svc, dev_id, quarter, "RERA")


async def _svc_generate_regulator_report_MAHARERA(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
    quarter: str,
) -> dict[str, Any]:
    return await _svc_generate_regulator_report(svc, dev_id, quarter, "MAHARERA")


async def _svc_generate_regulator_report_214FZ(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
    quarter: str,
) -> dict[str, Any]:
    return await _svc_generate_regulator_report(svc, dev_id, quarter, "214_FZ")


PropertyDevService.generate_regulator_report_RERA = (  # type: ignore[attr-defined]
    _svc_generate_regulator_report_RERA
)
PropertyDevService.generate_regulator_report_MAHARERA = (  # type: ignore[attr-defined]
    _svc_generate_regulator_report_MAHARERA
)
PropertyDevService.generate_regulator_report_214FZ = (  # type: ignore[attr-defined]
    _svc_generate_regulator_report_214FZ
)


# ── PDF document generation (#138 follow-up) ───────────────────────────


_VALID_DOC_TYPES: frozenset[str] = frozenset(
    {
        "reservation_receipt",
        "sales_contract",
        "payment_receipt",
        "handover_certificate",
        "warranty_certificate",
        "noc",
    }
)


async def _svc_generate_document(
    svc: PropertyDevService,
    *,
    doc_type: str,
    contract_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    handover_id: uuid.UUID | None = None,
    instalment_id: uuid.UUID | None = None,
    locale: str = "en",
    payment_method: str = "",
    payment_ref: str | None = None,
    requested_by: str = "",
    structural_warranty_years: int = 10,
    finishing_warranty_years: int = 1,
    noc_validity_days: int = 30,
) -> bytes:
    """Render one of the six sales-pipeline PDFs.

    Returns raw PDF bytes (starting with ``%PDF``). The caller wraps
    these into a streaming or base64 response.

    Loads the right entity graph for the requested ``doc_type`` and
    invokes the corresponding pure ``render_*`` from
    :mod:`document_templates`. Cross-tenant IDOR closure is the
    responsibility of the router (it owns the user payload); this helper
    raises :class:`HTTPException` 404 on missing entities.
    """
    from app.modules.property_dev.document_templates import (
        render_handover_certificate_pdf,
        render_no_objection_certificate_pdf,
        render_payment_receipt_pdf,
        render_reservation_receipt_pdf,
        render_sales_contract_pdf,
        render_warranty_certificate_pdf,
    )

    if doc_type not in _VALID_DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown doc_type: {doc_type}",
        )

    if doc_type == "reservation_receipt":
        if reservation_id is None:
            raise HTTPException(status_code=400, detail="reservation_id required")
        reservation = await svc.reservations.get_by_id(reservation_id)
        if reservation is None:
            raise HTTPException(status_code=404, detail="Reservation not found")
        plot = await svc.plots.get_by_id(reservation.plot_id)
        if plot is None:
            raise HTTPException(status_code=404, detail=translate("errors.plot_not_found", locale=get_locale()))
        development = await svc.developments.get_by_id(plot.development_id)
        if development is None:
            raise HTTPException(status_code=404, detail="Development not found")
        buyers: list[Buyer] = []
        if reservation.buyer_id is not None:
            buyer = await svc.buyers.get_by_id(reservation.buyer_id)
            if buyer is not None:
                buyers.append(buyer)
        return render_reservation_receipt_pdf(
            reservation,
            plot,
            development,
            buyers,
            locale=locale,
        )

    if doc_type == "sales_contract":
        if contract_id is None:
            raise HTTPException(status_code=400, detail="contract_id required")
        contract = await svc.sales_contracts.get_by_id(contract_id)
        if contract is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.salescontract_not_found", locale=get_locale())
            )
        plot = await svc.plots.get_by_id(contract.plot_id)
        if plot is None:
            raise HTTPException(status_code=404, detail=translate("errors.plot_not_found", locale=get_locale()))
        development = await svc.developments.get_by_id(plot.development_id)
        if development is None:
            raise HTTPException(status_code=404, detail="Development not found")
        payment_schedule = await svc.payment_schedules.get_for_contract(contract_id)
        instalments = await svc.instalments.list_for_contract(contract_id) if payment_schedule is not None else []
        parties = await svc.contract_parties.list_for_contract(contract_id)
        # Resolve buyer rows for parties (single per-contract resolution —
        # no N+1 because we only fetch unique buyer_ids).
        buyer_lookup: dict[uuid.UUID, Buyer] = {}
        for p in parties:
            if p.buyer_id and p.buyer_id not in buyer_lookup:
                b = await svc.buyers.get_by_id(p.buyer_id)
                if b is not None:
                    buyer_lookup[p.buyer_id] = b
        return render_sales_contract_pdf(
            contract,
            payment_schedule,
            instalments,
            parties,
            plot,
            development,
            locale=locale,
            buyer_lookup=buyer_lookup,
        )

    if doc_type == "payment_receipt":
        if instalment_id is None:
            raise HTTPException(status_code=400, detail="instalment_id required")
        instalment = await svc.instalments.get_by_id(instalment_id)
        if instalment is None:
            raise HTTPException(status_code=404, detail="Instalment not found")
        schedule = await svc.payment_schedules.get_by_id(instalment.schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail="PaymentSchedule not found")
        contract = await svc.sales_contracts.get_by_id(schedule.sales_contract_id)
        if contract is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.salescontract_not_found", locale=get_locale())
            )
        plot = await svc.plots.get_by_id(contract.plot_id)
        development = await svc.developments.get_by_id(plot.development_id) if plot is not None else None
        return render_payment_receipt_pdf(
            instalment,
            contract,
            payment_method or "",
            payment_ref,
            locale=locale,
            plot=plot,
            development=development,
        )

    if doc_type == "handover_certificate":
        if handover_id is None:
            raise HTTPException(status_code=400, detail="handover_id required")
        handover = await svc.handovers.get_by_id(handover_id)
        if handover is None:
            raise HTTPException(status_code=404, detail="Handover not found")
        plot = await svc.plots.get_by_id(handover.plot_id)
        if plot is None:
            raise HTTPException(status_code=404, detail=translate("errors.plot_not_found", locale=get_locale()))
        development = await svc.developments.get_by_id(plot.development_id)
        # The handover certificate quotes the SPA — find the most recent
        # signed contract on the plot. Falls back to draft if no signed one.
        from sqlalchemy import select as _select

        from app.modules.property_dev.models import SalesContract as _SC

        stmt = _select(_SC).where(_SC.plot_id == plot.id).order_by(_SC.revision_number.desc())
        rows = (await svc.session.execute(stmt)).scalars().all()
        contract = next(
            (r for r in rows if r.status in {"signed", "completed", "executed"}),
            next(iter(rows), None),
        )
        # Open-snag count from snag repo (status != 'fixed' and not closed).
        open_snags = 0
        try:
            from sqlalchemy import func as _func

            from app.modules.property_dev.models import Snag as _Snag

            cnt_stmt = (
                _select(_func.count(_Snag.id))
                .where(_Snag.handover_id == handover.id)
                .where(_Snag.status.in_(("open", "in_progress")))
            )
            open_snags = int((await svc.session.execute(cnt_stmt)).scalar() or 0)
        except Exception:  # noqa: BLE001 — best-effort snag count
            open_snags = int(_attr(handover, "snag_count_at_handover", 0) or 0)
        return render_handover_certificate_pdf(
            handover,
            contract,
            open_snags,
            plot,
            development,
            locale=locale,
        )

    if doc_type == "warranty_certificate":
        if handover_id is None:
            raise HTTPException(status_code=400, detail="handover_id required")
        handover = await svc.handovers.get_by_id(handover_id)
        if handover is None:
            raise HTTPException(status_code=404, detail="Handover not found")
        plot = await svc.plots.get_by_id(handover.plot_id)
        development = await svc.developments.get_by_id(plot.development_id) if plot is not None else None
        from sqlalchemy import select as _select

        from app.modules.property_dev.models import SalesContract as _SC

        stmt = _select(_SC).where(_SC.plot_id == handover.plot_id).order_by(_SC.revision_number.desc())
        rows = (await svc.session.execute(stmt)).scalars().all()
        contract = next(iter(rows), None)
        return render_warranty_certificate_pdf(
            contract,
            handover,
            int(structural_warranty_years),
            int(finishing_warranty_years),
            locale=locale,
            plot=plot,
            development=development,
        )

    if doc_type == "noc":
        if contract_id is None:
            raise HTTPException(status_code=400, detail="contract_id required")
        contract = await svc.sales_contracts.get_by_id(contract_id)
        if contract is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.salescontract_not_found", locale=get_locale())
            )
        plot = await svc.plots.get_by_id(contract.plot_id)
        if plot is None:
            raise HTTPException(status_code=404, detail=translate("errors.plot_not_found", locale=get_locale()))
        development = await svc.developments.get_by_id(plot.development_id)
        return render_no_objection_certificate_pdf(
            contract,
            plot,
            development,
            requested_by or "",
            locale=locale,
            validity_days=int(noc_validity_days),
        )

    # Unreachable — _VALID_DOC_TYPES is exhaustive.
    raise HTTPException(status_code=400, detail="Unhandled doc_type")  # pragma: no cover


PropertyDevService.generate_document = _svc_generate_document  # type: ignore[attr-defined]


# ════════════════════════════════════════════════════════════════════════
# Inventory Map (task #142) — sales-floor block / floor / unit grid.
# ════════════════════════════════════════════════════════════════════════
#
# The Inventory Map is the read-side fan-out of the BOQ for a residential
# Development. The sales desk uses it as their daily index: "show me every
# Plot, grouped by Block, grouped by floor, coloured by status, with a
# KPI ribbon and bulk hold / release". This is intentionally a *separate*
# endpoint from /developments/{dev_id}/dashboard-inventory-heatmap
# (task #140) — that one is the analytics phase->block view, this one is
# the sales-desk floor-by-floor view.


# Statuses that count as "available" for the bulk-hold workflow + the
# KPI ribbon. ``planned`` is the default fresh-import status; ``ready``
# means construction is finished but it's still on the market.
_INVENTORY_AVAILABLE_STATUSES: frozenset[str] = frozenset({"planned", "ready"})


def _inventory_summary(plots: Iterable[Plot]) -> dict[str, int]:
    """Bucket plots into the ribbon counters for the Inventory Map."""
    out = {
        "total": 0,
        "available": 0,
        "reserved": 0,
        "sold": 0,
        "handed_over": 0,
        "held": 0,
        "blocked": 0,
        "under_construction": 0,
        "ready": 0,
    }
    for plot in plots:
        out["total"] += 1
        st = plot.status or ""
        # "available" is the union of planned + ready — these are the
        # statuses the bulk-hold endpoint will accept; we surface a
        # dedicated counter so the UI's primary KPI matches the action.
        if st in _INVENTORY_AVAILABLE_STATUSES:
            out["available"] += 1
        if st in out and st != "total":
            out[st] += 1
    return out


def _derive_unit_code(plot: Plot, block_code: str | None) -> str:
    """Build a stable ``B2-04-12`` style unit code for the UI.

    Falls back to ``Plot.plot_number`` when the hierarchy is incomplete
    (legacy plots without ``block_id`` / ``level_in_block``). Keeps the
    sales-floor display deterministic — never returns an empty string.
    """
    if block_code and plot.level_in_block is not None and (plot.position_on_floor or plot.plot_number):
        floor_part = f"{int(plot.level_in_block):02d}"
        pos_part = (plot.position_on_floor or plot.plot_number).strip() or "00"
        return f"{block_code}-{floor_part}-{pos_part}"
    return plot.plot_number or "—"


async def _svc_inventory_map(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
) -> dict[str, Any]:
    """Render the Inventory Map payload for one Development.

    Single read fan-out: one SELECT for plots, one for blocks, one for
    the parent dev. Plots without ``block_id`` are surfaced under a
    synthetic "Unassigned" block so legacy data still appears. Sort
    order: ``block_code`` asc → floor desc (high floors first, matching
    every real-estate floor plan) → ``unit_code`` asc.
    """
    dev = await svc.get_development(dev_id)
    plots, _ = await svc.plots.list_for_development(
        dev_id,
        offset=0,
        limit=10_000,
    )
    blocks = await svc.blocks.list_for_development(dev_id)
    blocks_by_id: dict[Any, Any] = {b.id: b for b in blocks}

    # Bucket: block_code → floor → list[Plot].
    # ``block_code`` is None for unassigned plots; we render them last
    # under a synthetic "—" block code.
    buckets: dict[tuple[str, str | None], dict[int, list[Plot]]] = {}
    block_meta: dict[tuple[str, str | None], dict[str, Any]] = {}

    for plot in plots:
        block = blocks_by_id.get(plot.block_id) if plot.block_id else None
        block_code = (block.code if block else None) or "—"
        block_id_key = str(block.id) if block else None
        key = (block_code, block_id_key)
        if key not in block_meta:
            block_meta[key] = {
                "block_code": block_code,
                "block_id": (block.id if block else None),
                "name": (block.name if block else "Unassigned"),
            }
        floor = int(plot.level_in_block) if plot.level_in_block is not None else 0
        buckets.setdefault(key, {}).setdefault(floor, []).append(plot)

    # Stable sort: block_code asc, but the synthetic "—" goes last.
    def _block_key(item: tuple[str, str | None]) -> tuple[int, str]:
        code = item[0]
        return (1 if code == "—" else 0, code)

    block_rows: list[dict[str, Any]] = []
    for key in sorted(buckets.keys(), key=_block_key):
        meta = block_meta[key]
        floor_map = buckets[key]
        floor_rows: list[dict[str, Any]] = []
        # Floors descending — penthouse on top of the card, matches
        # how every real-estate brochure prints floor plans.
        for floor in sorted(floor_map.keys(), reverse=True):
            plots_on_floor = floor_map[floor]
            plots_on_floor.sort(
                key=lambda p: (
                    (p.position_on_floor or ""),
                    p.plot_number,
                ),
            )
            floor_rows.append(
                {
                    "floor": floor,
                    "plots": [
                        {
                            "id": p.id,
                            "unit_code": _derive_unit_code(p, meta["block_code"]),
                            "status": p.status,
                            "plot_type": p.house_type_label,
                            "block_code": meta["block_code"],
                            "floor": floor,
                            "base_price": Decimal(str(p.price_base or 0)),
                            "area_m2": Decimal(str(p.area_m2 or 0)),
                            "currency": (p.currency or dev.currency or ""),
                            "bedrooms": int(p.bedrooms or 0),
                            "bathrooms": int(p.bathrooms or 0),
                        }
                        for p in plots_on_floor
                    ],
                }
            )
        block_rows.append(
            {
                "block_code": meta["block_code"],
                "block_id": meta["block_id"],
                "name": meta["name"],
                "floors": floor_rows,
            }
        )

    summary = _inventory_summary(plots)
    return {
        "development_id": dev.id,
        "currency": dev.currency or "",
        "blocks": block_rows,
        "summary": summary,
    }


async def _svc_inventory_bulk_hold(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
    plot_ids: list[uuid.UUID],
    hold_reason: str,
    hold_until: str | None,
    actor_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Atomically move ``plot_ids`` from available → held.

    Atomicity contract (mirrors procurement.create_invoice_from_po):
        The whole batch runs under a single ``begin_nested`` SAVEPOINT.
        If ANY plot fails the precondition checks (not in this dev, not
        available, FK violation) the SAVEPOINT rolls back and NO plot
        flips status. Rationale: a half-applied hold is worse than a
        rejected one — the sales desk would otherwise have to manually
        reconcile "which 6 of 11 went through".

    Skipped (already-held or wrong tenant) plots are silently dropped
    from the success list and surfaced via ``skipped`` so the UI can
    show a "5 of 7 held, 2 already held" toast.
    """
    # We must verify every requested plot belongs to this dev BEFORE
    # we mutate anything — otherwise a SAVEPOINT abort can't reverse the
    # initial check (the check itself doesn't write).
    await svc.get_development(dev_id)  # 404 if dev doesn't exist

    if not plot_ids:
        return {
            "updated_count": 0,
            "skipped_count": 0,
            "updated_plot_ids": [],
            "skipped": [],
        }

    # Dedup while preserving order.
    seen: set[uuid.UUID] = set()
    dedup_ids: list[uuid.UUID] = []
    for pid in plot_ids:
        if pid in seen:
            continue
        seen.add(pid)
        dedup_ids.append(pid)

    updated_ids: list[uuid.UUID] = []
    skipped: list[dict[str, str]] = []
    iso_now = datetime.now(UTC).isoformat()

    try:
        async with svc.session.begin_nested():
            for pid in dedup_ids:
                plot = await svc.plots.get_by_id(pid)
                if plot is None or plot.development_id != dev_id:
                    # Cross-tenant / unknown plot — soft-skip; we
                    # intentionally do NOT 404 here, because the bulk
                    # endpoint should not become a UUID-existence
                    # oracle for other tenants' inventory.
                    skipped.append(
                        {
                            "plot_id": str(pid),
                            "reason": "not_in_development",
                        }
                    )
                    continue
                if plot.status == "held":
                    # Idempotent — already in the requested state.
                    skipped.append({"plot_id": str(pid), "reason": "already_held"})
                    continue
                if plot.status not in _INVENTORY_AVAILABLE_STATUSES:
                    # Hard reject — a reserved / sold / handed-over plot
                    # must NOT be held; that would corrupt the sales
                    # pipeline. Raise 409 so the *whole* batch rolls back
                    # — better to fail loud than half-apply.
                    raise HTTPException(
                        status_code=409,
                        detail=(f"Plot {plot.plot_number} is in status '{plot.status}' and cannot be held"),
                    )
                # Stash hold metadata on Plot.metadata — no schema migration
                # needed because metadata is JSON. Audit trail is also
                # written below.
                new_metadata = dict(plot.metadata_ or {})
                new_metadata["hold"] = {
                    "reason": hold_reason,
                    "until": hold_until,
                    "held_by": str(actor_id) if actor_id else None,
                    "held_at": iso_now,
                }
                await svc.plots.update_fields(
                    pid,
                    status="held",
                    metadata_=new_metadata,
                )
                updated_ids.append(pid)

            # Audit trail inside the SAVEPOINT so an audit failure
            # cancels the whole batch (matches procurement pattern).
            if updated_ids:
                try:
                    from app.core.audit_log import log_activity

                    await log_activity(
                        svc.session,
                        actor_id=str(actor_id) if actor_id else None,
                        entity_type="property_dev_development",
                        entity_id=str(dev_id),
                        action="inventory_map.bulk_hold",
                        reason=hold_reason or "bulk_hold",
                        metadata={
                            "plot_count": len(updated_ids),
                            "plot_ids": [str(p) for p in updated_ids],
                            "hold_until": hold_until or "",
                        },
                    )
                except Exception:  # pragma: no cover — audit best-effort
                    logger.exception("audit log failed for inventory bulk_hold")
                    raise
    except HTTPException:
        # The SAVEPOINT auto-rolls back; surface the original 409 unchanged.
        raise

    return {
        "updated_count": len(updated_ids),
        "skipped_count": len(skipped),
        "updated_plot_ids": updated_ids,
        "skipped": skipped,
    }


async def _svc_inventory_bulk_release(
    svc: PropertyDevService,
    dev_id: uuid.UUID,
    plot_ids: list[uuid.UUID],
    actor_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Atomically move ``plot_ids`` from held → planned.

    Idempotent: non-held plots are silently skipped (no 409). Rationale:
    the sales desk routinely shift-selects a range that may include a
    plot they already released; a noisy 409 would force them to redo
    the selection one plot at a time.

    ``blocked`` plots are NEVER released by this endpoint — only an
    explicit ``PATCH /plots/{id} {"status": "planned"}`` (MANAGER) lifts
    a block. The bulk path treats them like ``reserved`` / ``sold`` —
    silently skipped.
    """
    await svc.get_development(dev_id)

    if not plot_ids:
        return {
            "updated_count": 0,
            "skipped_count": 0,
            "updated_plot_ids": [],
            "skipped": [],
        }

    seen: set[uuid.UUID] = set()
    dedup_ids: list[uuid.UUID] = []
    for pid in plot_ids:
        if pid in seen:
            continue
        seen.add(pid)
        dedup_ids.append(pid)

    updated_ids: list[uuid.UUID] = []
    skipped: list[dict[str, str]] = []

    try:
        async with svc.session.begin_nested():
            for pid in dedup_ids:
                plot = await svc.plots.get_by_id(pid)
                if plot is None or plot.development_id != dev_id:
                    skipped.append({"plot_id": str(pid), "reason": "not_in_development"})
                    continue
                if plot.status != "held":
                    # Idempotent — anything that isn't currently held
                    # (including ``blocked``) is a soft skip.
                    skipped.append({"plot_id": str(pid), "reason": "not_held"})
                    continue
                new_metadata = dict(plot.metadata_ or {})
                new_metadata.pop("hold", None)
                await svc.plots.update_fields(
                    pid,
                    status="planned",
                    metadata_=new_metadata,
                )
                updated_ids.append(pid)

            if updated_ids:
                try:
                    from app.core.audit_log import log_activity

                    await log_activity(
                        svc.session,
                        actor_id=str(actor_id) if actor_id else None,
                        entity_type="property_dev_development",
                        entity_id=str(dev_id),
                        action="inventory_map.bulk_release",
                        reason="bulk_release",
                        metadata={
                            "plot_count": len(updated_ids),
                            "plot_ids": [str(p) for p in updated_ids],
                        },
                    )
                except Exception:  # pragma: no cover
                    logger.exception("audit log failed for inventory bulk_release")
                    raise
    except HTTPException:
        raise

    return {
        "updated_count": len(updated_ids),
        "skipped_count": len(skipped),
        "updated_plot_ids": updated_ids,
        "skipped": skipped,
    }


PropertyDevService.inventory_map = _svc_inventory_map  # type: ignore[attr-defined]
PropertyDevService.inventory_bulk_hold = (  # type: ignore[attr-defined]
    _svc_inventory_bulk_hold
)
PropertyDevService.inventory_bulk_release = (  # type: ignore[attr-defined]
    _svc_inventory_bulk_release
)


async def _svc_resolve_development_owner(
    svc: PropertyDevService,
    *,
    contract_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    handover_id: uuid.UUID | None = None,
    instalment_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Resolve the owning ``Project.owner_id`` for the entity referenced.

    Used by the router for cross-tenant IDOR closure. Returns ``None``
    when any link in the chain is missing — the router collapses that
    into a 404 so we never leak existence of other tenants' entities.
    """
    plot_id: uuid.UUID | None = None
    if contract_id is not None:
        contract = await svc.sales_contracts.get_by_id(contract_id)
        if contract is None:
            return None
        plot_id = contract.plot_id
    elif reservation_id is not None:
        reservation = await svc.reservations.get_by_id(reservation_id)
        if reservation is None:
            return None
        plot_id = reservation.plot_id
    elif handover_id is not None:
        handover = await svc.handovers.get_by_id(handover_id)
        if handover is None:
            return None
        plot_id = handover.plot_id
    elif instalment_id is not None:
        instalment = await svc.instalments.get_by_id(instalment_id)
        if instalment is None:
            return None
        sched = await svc.payment_schedules.get_by_id(instalment.schedule_id)
        if sched is None:
            return None
        contract = await svc.sales_contracts.get_by_id(sched.sales_contract_id)
        if contract is None:
            return None
        plot_id = contract.plot_id

    if plot_id is None:
        return None
    plot = await svc.plots.get_by_id(plot_id)
    if plot is None:
        return None
    development = await svc.developments.get_by_id(plot.development_id)
    if development is None:
        return None

    from app.modules.projects.repository import ProjectRepository

    project = await ProjectRepository(svc.session).get_by_id(development.project_id)
    if project is None:
        return None
    return getattr(project, "owner_id", None)


PropertyDevService.resolve_development_owner = (  # type: ignore[attr-defined]
    _svc_resolve_development_owner
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _dump(data: Any) -> dict[str, Any]:
    """Pydantic v2 ``model_dump`` that maps ``metadata`` → ``metadata_``."""
    fields = data.model_dump(exclude_unset=True)
    if "metadata" in fields:
        fields["metadata_"] = fields.pop("metadata")
    return fields


# ── Pricing engine service methods (v3124) ──────────────────────────────


async def _svc_create_price_list(
    svc: PropertyDevService,
    development_id: uuid.UUID,
    data: Any,
    *,
    created_by: uuid.UUID | None = None,
) -> Any:
    """Create a draft PriceList with optional entries + rules."""
    from app.modules.property_dev.models import (
        SalesPriceList as _PL,
    )
    from app.modules.property_dev.models import (
        SalesPriceListEntry as _PLE,
    )
    from app.modules.property_dev.models import (
        SalesPricingRule as _PR,
    )

    dev = await svc.developments.get_by_id(development_id)
    if dev is None:
        raise HTTPException(status_code=404, detail="Development not found")

    pl = _PL(
        development_id=development_id,
        name=data.name,
        effective_from=data.effective_from,
        effective_to=data.effective_to,
        currency=data.currency,
        status="draft",
        created_by=created_by,
        notes=data.notes,
    )
    pl = await svc.price_lists.create(pl)

    for entry in data.entries or []:
        # Verify plot belongs to this development (cross-tenant safety).
        plot = await svc.plots.get_by_id(entry.plot_id)
        if plot is None or plot.development_id != development_id:
            raise HTTPException(
                status_code=422,
                detail=f"Plot {entry.plot_id} does not belong to this development",
            )
        await svc.price_list_entries.create(
            _PLE(
                price_list_id=pl.id,
                plot_id=entry.plot_id,
                base_price=Decimal(str(entry.base_price)),
            )
        )

    for r in data.rules or []:
        await svc.pricing_rules.create(
            _PR(
                price_list_id=pl.id,
                name=r.name,
                rule_type=r.rule_type,
                condition_json=r.condition_json,
                adjustment_pct=Decimal(str(r.adjustment_pct)),
                adjustment_fixed=(Decimal(str(r.adjustment_fixed)) if r.adjustment_fixed is not None else None),
                priority=r.priority,
                active=r.active,
                effective_from=r.effective_from or "",
                effective_to=r.effective_to,
                max_uses=r.max_uses,
                times_used=0,
            )
        )

    return pl


async def _svc_activate_price_list(
    svc: PropertyDevService,
    price_list_id: uuid.UUID,
) -> Any:
    """Atomically activate a price list, superseding the previously
    active one for the same development.

    Wraps the two writes (supersede-others + flip-this-to-active) in
    a SAVEPOINT when one is open, falling back to back-to-back flushes
    on the outer request-scope transaction otherwise. Either way the
    pair commits together — concurrent activations against the same
    development serialise on the row lock the UPDATE acquires.
    """
    pl = await svc.price_lists.get_by_id(price_list_id)
    if pl is None:
        raise HTTPException(status_code=404, detail="PriceList not found")
    if pl.status == "active":
        return pl
    if pl.status == "superseded":
        raise HTTPException(
            status_code=409,
            detail="A superseded price list cannot be re-activated; clone it.",
        )

    # Cache the primary keys NOW. After ``update_fields`` flushes the
    # write the ORM expires the loaded attributes; accessing
    # ``pl.id`` / ``pl.development_id`` later would trigger an
    # implicit lazy refresh that crashes under aiosqlite
    # (MissingGreenlet — async I/O inside a sync attribute getter).
    pl_id = pl.id
    pl_development_id = pl.development_id

    # Atomicity model:
    # * On Postgres we wrap the supersede+activate pair in a SAVEPOINT
    #   (``begin_nested``) so a concurrent activation against the same
    #   development serialises on the row lock the UPDATE acquires.
    # * On SQLite (local dev + tests only) we skip SAVEPOINT — aiosqlite's
    #   savepoint path loses the greenlet context and trips MissingGreenlet.
    #   SQLite has no concurrent-write story anyway (one writer at a time
    #   serialised by the database lock), so the pair is naturally atomic
    #   at the flush boundary.
    dialect = svc.session.bind.dialect.name if svc.session.bind else ""
    if dialect == "postgresql" and svc.session.in_transaction():
        async with svc.session.begin_nested():
            await svc.price_lists.supersede_other_active(
                pl_development_id,
                keep_id=pl_id,
            )
            await svc.price_lists.update_fields(pl_id, status="active")
    else:
        await svc.price_lists.supersede_other_active(
            pl_development_id,
            keep_id=pl_id,
        )
        await svc.price_lists.update_fields(pl_id, status="active")

    event_bus.publish_detached(
        "property_dev.price_list.activated",
        data={
            "price_list_id": str(pl_id),
            "development_id": str(pl_development_id),
        },
        source_module="property_dev",
    )
    return await svc.price_lists.get_by_id(pl_id)


async def _svc_compute_price_quote(
    svc: PropertyDevService,
    price_list_id: uuid.UUID,
    *,
    plot_id: uuid.UUID,
    promo_code: str | None = None,
    buyer_id: uuid.UUID | None = None,
    quote_date: str | None = None,
    basket_plot_ids: list[uuid.UUID] | None = None,
) -> Any:
    """Compute a :class:`PriceQuote` against a price list."""
    from app.modules.property_dev.pricing_engine import compute_final_price

    pl = await svc.price_lists.get_by_id(price_list_id)
    if pl is None:
        raise HTTPException(status_code=404, detail="PriceList not found")
    plot = await svc.plots.get_by_id(plot_id)
    if plot is None or plot.development_id != pl.development_id:
        raise HTTPException(status_code=404, detail="Plot not found")

    buyer = None
    prior_purchases = 0
    if buyer_id is not None:
        buyer = await svc.buyers.get_by_id(buyer_id)
        if buyer is not None:
            prior_purchases = (
                await svc.reservations.count_for_buyer(buyer_id) if hasattr(svc.reservations, "count_for_buyer") else 0
            )

    rules = await svc.pricing_rules.list_active_for_price_list(pl.id)

    # Resolve base_price: prefer per-plot entry; fallback to Plot.price_base.
    entry = await svc.price_list_entries.find_for_plot(pl.id, plot_id)
    if entry is not None:
        base_price = Decimal(str(entry.base_price))
    else:
        base_price = Decimal(str(plot.price_base or 0))

    qd = date.fromisoformat(quote_date) if quote_date else datetime.now(UTC).date()

    basket = None
    if basket_plot_ids:
        basket = []
        for pid in basket_plot_ids:
            p = await svc.plots.get_by_id(pid)
            if p is not None and p.development_id == pl.development_id:
                basket.append(p)

    return await compute_final_price(
        plot=plot,
        price_list=pl,
        buyer=buyer,
        promo_code=promo_code,
        quote_date=qd,
        bulk_basket=basket,
        rules=rules,
        base_price=base_price,
        prior_purchases=prior_purchases,
    )


async def _svc_effective_rules_on_date(
    svc: PropertyDevService,
    price_list_id: uuid.UUID,
    *,
    on_date: str | None = None,
) -> list[Any]:
    """Return the rules effective on ``on_date`` (with times_used baked in)."""
    pl = await svc.price_lists.get_by_id(price_list_id)
    if pl is None:
        raise HTTPException(status_code=404, detail="PriceList not found")
    target = date.fromisoformat(on_date) if on_date else datetime.now(UTC).date()
    rules = await svc.pricing_rules.list_for_price_list(pl.id)
    out: list[Any] = []
    for r in rules:
        if not r.active:
            continue
        if r.effective_from:
            try:
                if date.fromisoformat(r.effective_from[:10]) > target:
                    continue
            except ValueError:
                pass
        if r.effective_to:
            try:
                if date.fromisoformat(r.effective_to[:10]) < target:
                    continue
            except ValueError:
                pass
        if r.max_uses is not None and (r.times_used or 0) >= r.max_uses:
            continue
        out.append(r)
    return out


PropertyDevService.create_price_list = _svc_create_price_list  # type: ignore[attr-defined]
PropertyDevService.activate_price_list = _svc_activate_price_list  # type: ignore[attr-defined]
PropertyDevService.compute_price_quote = _svc_compute_price_quote  # type: ignore[attr-defined]
PropertyDevService.effective_rules_on_date = (  # type: ignore[attr-defined]
    _svc_effective_rules_on_date
)


__all__ = [
    "PropertyDevService",
    "allowed_buyer_transitions",
    "allowed_commission_transitions",
    "allowed_escrow_reconciliation_transitions",
    "allowed_handover_transitions",
    "allowed_instalment_transitions",
    "allowed_lead_transitions",
    "allowed_payment_schedule_transitions",
    "allowed_plot_transitions",
    "allowed_reservation_transitions",
    "allowed_selection_transitions",
    "allowed_spa_transitions",
    "allowed_warranty_transitions",
    "can_modify_selection",
    "compute_buyer_selection_total",
    "compute_commission_amount",
    "compute_deposit_forfeiture",
    "compute_freeze_deadline",
    "compute_plot_final_price",
    "compute_plot_price_breakdown",
    "compute_withholding",
    "derive_plot_construction_progress",
    "supported_jurisdictions",
    "validate_option_compatibility",
]
