# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts service - business logic for the Contract Types Engine.

The service centralises:
    * Type-specific term validation (validate_contract_terms)
    * Pure cost / claim computation helpers (compute_*)
    * Per-type progress-claim generators (generate_*_claim)
    * GMP gainshare math (compute_gmp_gainshare)
    * Liquidated damages calculation (compute_ld_amount)
    * Change-order propagation to contract value (apply_change_order_to_contract)
    * State machines (Contract, ProgressClaim, FinalAccount)
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.validation.engine import ValidationReport, validation_engine
from app.core.validation.messages import translate
from app.core.validation.project_context import with_project_context
from app.modules.contracts import signing_bridge
from app.modules.contracts.compliance_packs import (
    DEFAULT_PACK_ID,
    WORKFLOW_CONTRACT_SIGNATURE,
    resolve_rule_sets,
)
from app.modules.contracts.events import CLAIM_POPULATED, EOT_DECIDED, EOT_SUBMITTED
from app.modules.contracts.final_account import (
    ClosureFacts,
    evaluate_final_account_readiness,
)
from app.modules.contracts.models import (
    CLAUSE_RISK_LEVELS,
    TEMPLATE_STATUSES,
    Contract,
    ContractDocument,
    ContractLine,
    ContractMilestone,
    ContractParty,
    ContractSecurity,
    ContractTemplate,
    ContractTemplateClause,
    EOTClaim,
    FeeStructure,
    FinalAccount,
    GainshareConfiguration,
    LDClause,
    ProgressClaim,
    ProgressClaimLine,
    RetentionSchedule,
)
from app.modules.contracts.repository import (
    ContractDocumentRepository,
    ContractLineRepository,
    ContractMilestoneRepository,
    ContractPartyRepository,
    ContractRepository,
    ContractSecurityRepository,
    ContractTemplateClauseRepository,
    ContractTemplateRepository,
    ContractTypeConfigurationRepository,
    EOTClaimRepository,
    FeeStructureRepository,
    FinalAccountRepository,
    GainshareConfigurationRepository,
    LDClauseRepository,
    ProgressClaimLineRepository,
    ProgressClaimRepository,
    RetentionScheduleRepository,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

DEC_ZERO = Decimal("0")
DEC_HUNDRED = Decimal("100")

CONTRACT_TYPES = (
    "lump_sum",
    "gmp",
    "cost_plus",
    "tm",
    "unit_price",
    "design_build",
    "combination",
    "remeasurement",
)

# Type-specific required-keys map. Empty list = no extra required keys.
# "remeasurement" mirrors "unit_price" semantics (re-measured quantities at
# agreed unit rates), so it carries no extra required terms.
_REQUIRED_TERM_FIELDS: dict[str, tuple[str, ...]] = {
    "lump_sum": (),
    "gmp": ("gmp_cap", "target_cost"),
    "cost_plus": ("fee_percent",),
    "tm": ("tm_nte_cap",),
    "unit_price": (),
    "design_build": (),
    "combination": (),
    "remeasurement": (),
}


# ── Custom errors ─────────────────────────────────────────────────────────


class NTECapExceededError(Exception):
    """Raised when a T&M claim would exceed the not-to-exceed (NTE) cap."""


class InvalidTransitionError(Exception):
    """Raised when an attempted state transition is not allowed."""


# ── State machines ────────────────────────────────────────────────────────


_CONTRACT_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "terminated"}),
    "active": frozenset({"suspended", "completed", "terminated"}),
    "suspended": frozenset({"active", "terminated"}),
    "completed": frozenset(),
    "terminated": frozenset(),
}

_CLAIM_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted", "rejected"}),
    "submitted": frozenset({"approved", "rejected"}),
    "approved": frozenset({"certified", "rejected"}),
    "certified": frozenset({"paid", "rejected"}),
    "paid": frozenset(),
    "rejected": frozenset({"draft"}),
}

_FINAL_ACCOUNT_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"agreed", "disputed"}),
    "agreed": frozenset({"closed", "disputed"}),
    "disputed": frozenset({"agreed", "closed"}),
    "closed": frozenset(),
}

# Extension-of-time claim FSM. A claim is raised (draft), submitted, optionally
# moved under review, then decided (granted / partially_granted / rejected) or
# withdrawn. Decisions and withdrawals are terminal.
_EOT_CLAIM_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted", "withdrawn"}),
    "submitted": frozenset(
        {"under_review", "granted", "partially_granted", "rejected", "withdrawn"},
    ),
    "under_review": frozenset({"granted", "partially_granted", "rejected", "withdrawn"}),
    "granted": frozenset(),
    "partially_granted": frozenset(),
    "rejected": frozenset(),
    "withdrawn": frozenset(),
}

# The subset of EOT statuses that represent a final decision on the claim.
_EOT_DECISION_STATUSES: frozenset[str] = frozenset(
    {"granted", "partially_granted", "rejected"},
)


def allowed_contract_transitions(current: str) -> frozenset[str]:
    """Return the set of statuses a contract may transition to from ``current``."""
    return _CONTRACT_TRANSITIONS.get(current, frozenset())


def allowed_claim_transitions(current: str) -> frozenset[str]:
    """Return the set of statuses a progress-claim may transition to."""
    return _CLAIM_TRANSITIONS.get(current, frozenset())


def allowed_final_account_transitions(current: str) -> frozenset[str]:
    """Return the set of statuses a final account may transition to."""
    return _FINAL_ACCOUNT_TRANSITIONS.get(current, frozenset())


def assert_contract_transition(current: str, target: str) -> None:
    """Raise ``InvalidTransitionError`` if (current → target) is not allowed."""
    if target not in allowed_contract_transitions(current):
        raise InvalidTransitionError(
            f"Cannot transition contract from {current!r} to {target!r}",
        )


def assert_claim_transition(current: str, target: str) -> None:
    if target not in allowed_claim_transitions(current):
        raise InvalidTransitionError(
            f"Cannot transition claim from {current!r} to {target!r}",
        )


def assert_final_account_transition(current: str, target: str) -> None:
    if target not in allowed_final_account_transitions(current):
        raise InvalidTransitionError(
            f"Cannot transition final account from {current!r} to {target!r}",
        )


def allowed_eot_transitions(current: str) -> frozenset[str]:
    """Return the set of statuses an EOT claim may transition to from ``current``."""
    return _EOT_CLAIM_TRANSITIONS.get(current, frozenset())


def assert_eot_transition(current: str, target: str) -> None:
    if target not in allowed_eot_transitions(current):
        raise InvalidTransitionError(
            f"Cannot transition EOT claim from {current!r} to {target!r}",
        )


def clamp_eot_days_granted(days_claimed: int, days_granted: int, decision: str) -> int:
    """Pure: constrain granted days to ``[0, days_claimed]`` for a decision.

    A rejected claim always grants zero days; otherwise the granted figure is
    clamped so a decision can never award more time than was claimed.
    """
    if decision == "rejected":
        return 0
    claimed = max(0, int(days_claimed or 0))
    granted = max(0, int(days_granted or 0))
    return min(granted, claimed)


# ── Pure validators / calculators ─────────────────────────────────────────


def validate_contract_terms(
    contract_type: str,
    terms: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Check that ``terms`` contains the keys required for ``contract_type``.

    Returns:
        (ok, errors) where ``ok`` is True iff the terms dict is well-formed.
    """
    errors: list[str] = []
    if contract_type not in CONTRACT_TYPES:
        errors.append(f"unknown contract_type: {contract_type}")
        return False, errors

    required = _REQUIRED_TERM_FIELDS.get(contract_type, ())
    terms = terms or {}
    for key in required:
        value = terms.get(key)
        if value in (None, ""):
            errors.append(f"missing required term: {key}")
        else:
            try:
                if Decimal(str(value)) < 0:
                    errors.append(f"term {key} must be non-negative")
            except (ValueError, ArithmeticError):
                errors.append(f"term {key} must be numeric")
    return len(errors) == 0, errors


def compute_line_total(line: ContractLine | Any) -> Decimal:
    """Pure: line.quantity × line.unit_rate. Treats missing values as zero."""
    qty = Decimal(str(getattr(line, "quantity", 0) or 0))
    rate = Decimal(str(getattr(line, "unit_rate", 0) or 0))
    return qty * rate


def compute_contract_total(lines: list[ContractLine | Any]) -> Decimal:
    """Sum of leaf-line totals (skip lines that are parents to avoid double-counting).

    A line is considered a "parent" if at least one other line has
    ``parent_line_id`` equal to its id.
    """
    if not lines:
        return DEC_ZERO

    parent_ids: set[uuid.UUID] = set()
    for ln in lines:
        parent = getattr(ln, "parent_line_id", None)
        if parent is not None:
            parent_ids.add(parent)

    total = DEC_ZERO
    for ln in lines:
        if getattr(ln, "id", None) in parent_ids:
            # This line has children - skip to avoid double-counting.
            continue
        total += compute_line_total(ln)
    return total


def compute_progress_claim_total(
    claim_lines: list[ProgressClaimLine | Any],
    retention_percent: Decimal,
    prior_claims_paid: Decimal,
) -> dict[str, Decimal]:
    """Pure: roll up claim-line values into gross/retention/net.

    Returns a dict with keys ``gross``, ``retention``, ``net``.

    Net is ``gross - retention - prior_claims_paid`` (clamped to zero floor).
    """
    gross = sum(
        (Decimal(str(getattr(ln, "period_completed_value", 0) or 0)) for ln in claim_lines),
        DEC_ZERO,
    )
    pct = Decimal(str(retention_percent or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    prior = Decimal(str(prior_claims_paid or 0))
    net = gross - retention - prior
    if net < DEC_ZERO:
        net = DEC_ZERO
    return {"gross": gross, "retention": retention, "net": net}


#: Key under which a SoV ``ContractLine.metadata_`` stores the id of the BOQ
#: position it bills against. The progress bridge reads the latest observation
#: for this position; lines without it are skipped (additive, no DDL needed).
BOQ_POSITION_META_KEY = "boq_position_id"


def boq_position_id_for_line(line: ContractLine | Any) -> uuid.UUID | None:
    """Return the BOQ position a SoV line bills against, or ``None``.

    The link lives in ``ContractLine.metadata_["boq_position_id"]`` (a string
    UUID). Returns ``None`` when the line is unlinked or the stored value is not
    a parseable UUID, so a malformed metadata entry degrades to "skip this
    line" rather than raising.
    """
    meta = getattr(line, "metadata_", None) or {}
    if not isinstance(meta, dict):
        return None
    raw = meta.get(BOQ_POSITION_META_KEY)
    if raw in (None, ""):
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def compute_progress_claim_line(
    line: ContractLine | Any,
    observed_pct: Decimal | float | int,
    *,
    value_override: Decimal | float | int | None = None,
) -> dict[str, Decimal]:
    """Pure: derive one claim line's figures from a SoV line + observed pct.

    The percent is clamped to [0, 100]. ``period_completed_value`` defaults to
    ``contract_line_value × pct / 100`` (rounded to 0.0001). When
    ``value_override`` is supplied (the user tweaked the value in the preview),
    it is used instead but clamped to the contract line value so a claim line
    can never bill more than the SoV line it sits against. Quantity progress is
    ``contract_quantity × pct / 100``.

    Returns ``{period_completed_qty, period_completed_value,
    period_completed_pct, cumulative_completed_value}`` (all Decimal).
    """
    pct = Decimal(str(observed_pct or 0))
    if pct < DEC_ZERO:
        pct = DEC_ZERO
    if pct > DEC_HUNDRED:
        pct = DEC_HUNDRED
    line_value = Decimal(str(getattr(line, "total_value", 0) or 0))
    qty = Decimal(str(getattr(line, "quantity", 0) or 0))
    if value_override is not None:
        value = Decimal(str(value_override or 0))
        if value < DEC_ZERO:
            value = DEC_ZERO
        if value > line_value:
            value = line_value
    else:
        value = (line_value * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    qty_progress = (qty * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    return {
        "period_completed_qty": qty_progress,
        "period_completed_value": value,
        "period_completed_pct": pct.quantize(Decimal("0.0001")),
        "cumulative_completed_value": value,
    }


def compute_gmp_gainshare(
    actual_cost: Decimal,
    target_cost: Decimal,
    gmp_cap: Decimal,
    split_owner_pct: Decimal,
    split_contractor_pct: Decimal,
) -> dict[str, Decimal]:
    """Pure: compute savings split or overrun for a GMP contract.

    * If actual < target → savings = target - actual, split per percentages.
    * If actual > gmp_cap → overrun = actual - gmp_cap (cap > target by design).
    * Otherwise (target <= actual <= gmp_cap) → no savings, no overrun.

    Returns dict with keys: ``savings``, ``owner_share``, ``contractor_share``,
    ``overrun``.
    """
    actual = Decimal(str(actual_cost or 0))
    target = Decimal(str(target_cost or 0))
    cap = Decimal(str(gmp_cap or 0))
    owner_pct = Decimal(str(split_owner_pct or 0))
    contractor_pct = Decimal(str(split_contractor_pct or 0))

    savings = DEC_ZERO
    owner_share = DEC_ZERO
    contractor_share = DEC_ZERO
    overrun = DEC_ZERO

    if actual < target:
        savings = target - actual
        owner_share = (savings * owner_pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
        contractor_share = (savings * contractor_pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    elif actual > cap and cap > DEC_ZERO:
        overrun = actual - cap

    return {
        "savings": savings,
        "owner_share": owner_share,
        "contractor_share": contractor_share,
        "overrun": overrun,
    }


def compute_ld_amount(
    per_day: Decimal,
    days_late: int,
    max_amount: Decimal | None,
) -> Decimal:
    """Pure: liquidated-damages amount, capped at ``max_amount`` if provided."""
    if days_late <= 0:
        return DEC_ZERO
    rate = Decimal(str(per_day or 0))
    raw = rate * Decimal(days_late)
    if max_amount is not None:
        cap = Decimal(str(max_amount))
        if raw > cap:
            return cap
    return raw


def compute_milestone_value(
    value: Decimal | float | int | None,
    percent_of_contract: Decimal | float | int | None,
    contract_value: Decimal | float | int,
) -> Decimal:
    """Pure: resolve a milestone's monetary value.

    Uses the explicit ``value`` when set, otherwise derives it from
    ``percent_of_contract`` of the contract value (rounded to 0.0001). Returns
    zero when neither is provided.
    """
    if value is not None:
        return Decimal(str(value or 0))
    if percent_of_contract is not None:
        base = Decimal(str(contract_value or 0))
        pct = Decimal(str(percent_of_contract or 0))
        return (base * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    return DEC_ZERO


# ── Per-type claim generators (pure) ──────────────────────────────────────


def generate_lump_sum_claim(
    contract: Contract | Any,
    lines: list[ContractLine | Any],
    completion: dict[uuid.UUID | str, Decimal | float | int],
    prior_paid: Decimal = DEC_ZERO,
) -> dict[str, Any]:
    """Compute a lump-sum claim payload from per-line completion %.

    ``completion`` maps contract_line_id (UUID or its string form) to completion
    percent (0-100). Lines absent from the dict are treated as 0%.

    Returns a dict with ``claim_lines`` (list of ProgressClaimLine-shaped dicts),
    plus ``gross``, ``retention``, ``net`` totals.
    """
    norm: dict[str, Decimal] = {str(k): Decimal(str(v)) for k, v in (completion or {}).items()}
    parent_ids: set[uuid.UUID] = {ln.parent_line_id for ln in lines if getattr(ln, "parent_line_id", None) is not None}

    claim_lines: list[dict[str, Any]] = []
    for ln in lines:
        if getattr(ln, "id", None) in parent_ids:
            continue  # skip parent / roll-up rows
        pct = norm.get(str(getattr(ln, "id", "")), DEC_ZERO)
        if pct < DEC_ZERO:
            pct = DEC_ZERO
        if pct > DEC_HUNDRED:
            pct = DEC_HUNDRED
        line_total = compute_line_total(ln)
        value = (line_total * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
        qty_progress = ((Decimal(str(getattr(ln, "quantity", 0) or 0)) * pct) / DEC_HUNDRED).quantize(Decimal("0.0001"))
        claim_lines.append(
            {
                "contract_line_id": getattr(ln, "id", None),
                "period_completed_qty": qty_progress,
                "period_completed_value": value,
                "period_completed_pct": pct,
                "cumulative_completed_value": value,
            }
        )

    totals = compute_progress_claim_total(
        [type("L", (), c)() for c in claim_lines],
        Decimal(str(getattr(contract, "retention_percent", 0) or 0)),
        prior_paid,
    )
    # The synthesised objects above lose attribute access - recompute gross
    # directly off the dicts to be safe.
    gross = sum(
        (c["period_completed_value"] for c in claim_lines),
        DEC_ZERO,
    )
    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    net = gross - retention - Decimal(str(prior_paid or 0))
    if net < DEC_ZERO:
        net = DEC_ZERO
    totals = {"gross": gross, "retention": retention, "net": net}

    return {
        "claim_lines": claim_lines,
        "gross": totals["gross"],
        "retention": totals["retention"],
        "net": totals["net"],
    }


def _fee_amount_from_structure(
    fee: FeeStructure | dict[str, Any] | None,
    base_cost: Decimal,
) -> Decimal:
    """Compute the fee dollars for a given cost-base and fee structure."""
    if fee is None:
        return DEC_ZERO

    def _get(name: str) -> Any:
        if isinstance(fee, dict):
            return fee.get(name)
        return getattr(fee, name, None)

    fee_type = _get("fee_type") or "percent_of_cost"
    if fee_type == "fixed":
        fixed = _get("fee_fixed_amount")
        return Decimal(str(fixed or 0))

    if fee_type == "sliding_scale":
        scale = _get("sliding_scale") or []
        applicable = DEC_ZERO
        for step in scale:
            try:
                threshold = Decimal(str(step.get("threshold", 0)))
                step_pct = Decimal(str(step.get("percent", 0)))
            except (ValueError, AttributeError, ArithmeticError):
                continue
            if base_cost >= threshold:
                applicable = step_pct
        return (base_cost * applicable / DEC_HUNDRED).quantize(Decimal("0.0001"))

    # percent_of_cost (default)
    pct = Decimal(str(_get("fee_percent") or 0))
    raw_fee = (base_cost * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    max_fee = _get("max_fee")
    if max_fee is not None:
        cap = Decimal(str(max_fee))
        if raw_fee > cap:
            return cap
    return raw_fee


def generate_cost_plus_claim(
    contract: Contract | Any,
    fee_structure: FeeStructure | dict[str, Any] | None,
    actual_costs_total: Decimal,
    prior_paid: Decimal = DEC_ZERO,
) -> dict[str, Any]:
    """Compute a cost-plus claim payload.

    Gross = actual_costs + fee, retention applied per contract.retention_percent.
    """
    base = Decimal(str(actual_costs_total or 0))
    fee = _fee_amount_from_structure(fee_structure, base)
    gross = base + fee
    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    prior = Decimal(str(prior_paid or 0))
    net = gross - retention - prior
    if net < DEC_ZERO:
        net = DEC_ZERO
    return {
        "actual_costs": base,
        "fee": fee,
        "gross": gross,
        "retention": retention,
        "prior_paid": prior,
        "net": net,
    }


def generate_tm_claim(
    contract: Contract | Any,
    time_entries_total: Decimal,
    material_entries_total: Decimal,
    fee_structure: FeeStructure | dict[str, Any] | None,
    prior_paid: Decimal = DEC_ZERO,
) -> dict[str, Any]:
    """Compute a T&M claim payload.

    Respects ``contract.terms.tm_nte_cap``. Raises ``NTECapExceededError``
    if (prior_paid + this gross) would exceed the cap.
    """
    labor = Decimal(str(time_entries_total or 0))
    materials = Decimal(str(material_entries_total or 0))
    base = labor + materials
    fee = _fee_amount_from_structure(fee_structure, base)
    gross = base + fee

    nte_cap_raw = (getattr(contract, "terms", None) or {}).get("tm_nte_cap")
    if nte_cap_raw not in (None, ""):
        try:
            cap = Decimal(str(nte_cap_raw))
        except (ValueError, ArithmeticError):
            cap = None
        if cap is not None and (Decimal(str(prior_paid or 0)) + gross) > cap:
            raise NTECapExceededError(
                f"T&M claim would exceed NTE cap: prior={prior_paid}, this={gross}, cap={cap}",
            )

    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    prior = Decimal(str(prior_paid or 0))
    net = gross - retention - prior
    if net < DEC_ZERO:
        net = DEC_ZERO
    return {
        "labor": labor,
        "materials": materials,
        "fee": fee,
        "gross": gross,
        "retention": retention,
        "net": net,
    }


def generate_unit_price_claim(
    contract: Contract | Any,
    lines: list[ContractLine | Any],
    measurements: dict[uuid.UUID | str, Decimal | float | int],
    prior_paid: Decimal = DEC_ZERO,
) -> dict[str, Any]:
    """Compute a unit-price claim from per-line measured quantities."""
    norm: dict[str, Decimal] = {str(k): Decimal(str(v)) for k, v in (measurements or {}).items()}
    parent_ids: set[uuid.UUID] = {ln.parent_line_id for ln in lines if getattr(ln, "parent_line_id", None) is not None}
    claim_lines: list[dict[str, Any]] = []
    for ln in lines:
        if getattr(ln, "id", None) in parent_ids:
            continue
        measured = norm.get(str(getattr(ln, "id", "")), DEC_ZERO)
        rate = Decimal(str(getattr(ln, "unit_rate", 0) or 0))
        value = (measured * rate).quantize(Decimal("0.0001"))
        qty_contract = Decimal(str(getattr(ln, "quantity", 0) or 0))
        pct = (
            DEC_ZERO
            if qty_contract == DEC_ZERO
            else ((measured / qty_contract * DEC_HUNDRED).quantize(Decimal("0.0001")))
        )
        claim_lines.append(
            {
                "contract_line_id": getattr(ln, "id", None),
                "period_completed_qty": measured,
                "period_completed_value": value,
                "period_completed_pct": pct,
                "cumulative_completed_value": value,
            }
        )

    gross = sum((c["period_completed_value"] for c in claim_lines), DEC_ZERO)
    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    prior = Decimal(str(prior_paid or 0))
    net = gross - retention - prior
    if net < DEC_ZERO:
        net = DEC_ZERO
    return {
        "claim_lines": claim_lines,
        "gross": gross,
        "retention": retention,
        "net": net,
    }


# ── Service class (DB-aware operations + event emission) ─────────────────


class ContractsService:
    """Business logic for the contracts module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.contract_repo = ContractRepository(session)
        self.line_repo = ContractLineRepository(session)
        self.type_repo = ContractTypeConfigurationRepository(session)
        self.retention_repo = RetentionScheduleRepository(session)
        self.fee_repo = FeeStructureRepository(session)
        self.gainshare_repo = GainshareConfigurationRepository(session)
        self.ld_repo = LDClauseRepository(session)
        self.claim_repo = ProgressClaimRepository(session)
        self.claim_line_repo = ProgressClaimLineRepository(session)
        self.final_account_repo = FinalAccountRepository(session)
        self.party_repo = ContractPartyRepository(session)
        self.security_repo = ContractSecurityRepository(session)
        self.eot_repo = EOTClaimRepository(session)
        self.document_repo = ContractDocumentRepository(session)
        self.milestone_repo = ContractMilestoneRepository(session)
        self.template_repo = ContractTemplateRepository(session)
        self.template_clause_repo = ContractTemplateClauseRepository(session)

    # ── Contracts ────────────────────────────────────────────────────────

    async def create_contract(
        self,
        data: Any,
        user_id: str | None = None,
    ) -> Contract:
        """Create a new contract; validates type-specific terms."""
        ok, errors = validate_contract_terms(data.contract_type, data.terms)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_contract_terms",
                    "details": errors,
                },
            )

        # Resolve the clause template now, not at read time. Storing the code
        # alone would mean "whatever version is current whenever someone looks",
        # so publishing version 3 would quietly restate what an already-signed
        # contract was drawn from. Resolving here pins the version the author
        # actually saw. A built-in resolves to version 0, which reads as "not a
        # versioned template" and keeps the pair populated either way.
        template_code, template_version = await self.resolve_template_for_contract(getattr(data, "template_code", None))

        # Contracts always start in 'draft'. The FSM (draft → active →
        # suspended / completed / terminated) is enforced by dedicated
        # transition endpoints that stamp signed_at and emit
        # contracts.contract.signed. Letting the caller pre-set status
        # would bypass both, producing a commercially-live contract
        # with no signed-audit-trail and no event reaching finance.
        contract = Contract(
            code=data.code,
            title=data.title,
            contract_type=data.contract_type,
            counterparty_type=data.counterparty_type,
            counterparty_id=data.counterparty_id,
            project_id=data.project_id,
            parent_contract_id=data.parent_contract_id,
            start_date=data.start_date,
            end_date=data.end_date,
            total_value=Decimal(str(data.total_value or 0)),
            currency=data.currency,
            retention_percent=Decimal(str(data.retention_percent or 0)),
            retention_release_event=data.retention_release_event,
            status="draft",
            signed_at=None,
            terms=data.terms,
            template_code=template_code,
            template_version=template_version,
            created_by=user_id,
            metadata_=data.metadata,
        )
        # ``code`` carries a unique constraint. Without this the duplicate
        # surfaced as an unhandled IntegrityError, which the caller sees as a
        # 500: an error the user cannot act on, for a mistake that is entirely
        # theirs to fix and takes one word to describe.
        try:
            contract = await self.contract_repo.create(contract)
        except IntegrityError as exc:
            await self.session.rollback()
            if "uq_oe_contracts_contract_code" not in str(exc.orig):
                raise
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A contract with code '{data.code}' already exists.",
            ) from exc

        logger.info(
            "Contract created: %s (%s) project=%s",
            contract.code,
            contract.contract_type,
            data.project_id,
        )
        return contract

    async def get_contract(self, contract_id: uuid.UUID) -> Contract:
        contract = await self.contract_repo.get_by_id(contract_id)
        if contract is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contract not found",
            )
        return contract

    #: Commercial terms that must not change once a contract is no longer a
    #: draft. Mutating contract value / retention / currency / type on a
    #: signed contract silently rewrites the agreed deal and breaks the
    #: audit trail - value changes must go through change orders, status
    #: through the transition endpoints.
    _LOCKED_FINANCIAL_FIELDS = (
        "total_value",
        "retention_percent",
        "currency",
        "contract_type",
        "retention_release_event",
        # Type-specific terms (gmp_cap, target_cost, tm_nte_cap, ld_per_day…)
        # are commercial terms too - freezing total_value but letting the
        # GMP cap be rewritten on a live contract would defeat the lock.
        "terms",
    )

    async def update_contract(self, contract_id: uuid.UUID, data: Any) -> Contract:
        contract = await self.get_contract(contract_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(contract, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )
        # Status changes must go through the lifecycle transition endpoints
        # (state-machine validation + signed_at stamping + event emission).
        # A raw PATCH would skip all of that and corrupt the lifecycle.
        if "status" in fields and fields["status"] != contract.status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "status_not_directly_editable",
                    "message": ("Use the sign / suspend / resume / terminate endpoints to change contract status"),
                },
            )
        fields.pop("status", None)
        # original_contract_value is set internally when the contract
        # leaves draft and must never be edited through the API.
        fields.pop("original_contract_value", None)
        # Once the contract leaves `draft`, its financial terms are frozen.
        if contract.status != "draft":
            locked = sorted(f for f in self._LOCKED_FINANCIAL_FIELDS if f in fields)
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "financial_terms_locked",
                        "message": (
                            "Financial terms cannot be edited on a contract "
                            f"in status {contract.status!r}; use a change "
                            "order to adjust the contract value"
                        ),
                        "locked_fields": locked,
                    },
                )
        # re-validate terms if changed
        if "terms" in fields or "contract_type" in fields:
            contract_type = fields.get("contract_type", contract.contract_type)
            terms = fields.get("terms", contract.terms)
            ok, errors = validate_contract_terms(contract_type, terms)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "invalid_contract_terms",
                        "details": errors,
                    },
                )
        if not fields:
            return contract
        await self.contract_repo.update_fields(contract_id, **fields)
        await self.session.refresh(contract)
        # The paper moved, so any signature already collected against the old
        # wording is stale. Pushing the new hash onto the outstanding sessions is
        # what lets signing.delta_by_hash say so; without this call the staleness
        # check can never fire for a contract. Best-effort, and it returns 0 on a
        # deployment without the signing module.
        await self.refresh_signing_content_hash(contract_id)
        return contract

    async def delete_contract(self, contract_id: uuid.UUID) -> None:
        """Delete a contract. Only a draft may be deleted.

        The delete cascades to every child row: variations, progress claims,
        payment certificates, retention, the lot. On a draft that is what you
        want. On a contract that has been signed and is running, it is the
        commercial record of the job, and one call used to take it and its
        entire claim history away with no confirmation of any kind. A contract
        that has left draft is closed or terminated through its status, not
        deleted. This mirrors the guard change orders already applies.
        """
        contract = await self.get_contract(contract_id)

        if contract.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Only draft contracts can be deleted. This contract is "
                    f"'{contract.status}'; terminate or complete it instead."
                ),
            )

        await self.contract_repo.delete(contract_id)
        logger.info("Contract deleted: %s", contract_id)

    async def clone_contract(
        self,
        source_contract_id: uuid.UUID,
        new_code: str,
        *,
        target_project_id: uuid.UUID | None = None,
        new_title: str | None = None,
        include_lines: bool = True,
        copy_subconfigs: bool = True,
        user_id: str | None = None,
    ) -> Contract:
        """Deep-clone a contract into the same or a different project.

        Security model (R7 IDOR-closure):
            * Read access on the **source** contract is verified by the
              router via :func:`_verify_contract_access` before this
              method is called.
            * Write access on the **destination** project is verified by
              the router via :func:`verify_project_access` before this
              method is called - so a manager on project A cannot
              ``clone --target_project_id=<project_B_id>`` and copy
              project A's commercial terms into project B.
            * Manager-or-higher RBAC is enforced at the route level
              via ``RequirePermission("contracts.clone")``.

        Lifecycle invariants:
            * Clone is always materialised in ``draft`` status with
              ``signed_at=None`` regardless of the source's lifecycle
              stage - a cloned contract is a brand-new instrument that
              must be re-signed.
            * Payment history (progress claims, claim lines, final
              accounts, lien-waiver attachments, retention-release
              audit entries) is **never** copied - that ledger belongs
              to the original contract.
        """
        source = await self.get_contract(source_contract_id)
        dest_project_id = target_project_id or source.project_id

        # Bare-minimum guard against accidental code collision (the DB
        # has a UNIQUE constraint, but a friendly 400 beats a 500).
        existing = await self.contract_repo.get_by_code(new_code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "contract_code_in_use",
                    "message": f"Contract code {new_code!r} is already in use",
                },
            )

        # Copy the terms dict by value so a later mutation on the clone
        # cannot bleed back into the source contract's terms.
        cloned_terms = dict(source.terms or {})
        cloned_meta = dict(getattr(source, "metadata_", {}) or {})
        # Strip volatile audit-trail fields so the clone starts with a
        # clean retention-release / lifecycle metadata block.
        for k in ("retention_releases", "lien_waivers"):
            cloned_meta.pop(k, None)
        cloned_meta["cloned_from_contract_id"] = str(source.id)

        clone = Contract(
            code=new_code,
            title=new_title or f"{source.title} (clone)",
            contract_type=source.contract_type,
            counterparty_type=source.counterparty_type,
            counterparty_id=source.counterparty_id,
            project_id=dest_project_id,
            parent_contract_id=None,  # do NOT inherit the source's parent
            start_date=source.start_date,
            end_date=source.end_date,
            total_value=Decimal(str(source.total_value or 0)),
            currency=source.currency,
            retention_percent=Decimal(str(source.retention_percent or 0)),
            retention_release_event=source.retention_release_event,
            status="draft",  # cloned instrument starts as draft
            signed_at=None,  # must be re-signed
            terms=cloned_terms,
            # The clone is the same paper as the source, so it carries the same
            # template version rather than re-resolving to whatever is current.
            # Re-resolving would silently upgrade a clone of a 2024 contract to
            # this year's clauses, which is not what "clone" means to anyone.
            template_code=getattr(source, "template_code", None),
            template_version=getattr(source, "template_version", None),
            created_by=user_id,
            metadata_=cloned_meta,
        )
        clone = await self.contract_repo.create(clone)

        # ── Schedule-of-Values lines (preserve hierarchy) ────────────
        if include_lines:
            src_lines = await self.line_repo.list_for_contract(source.id)
            # Map old line id → new line id so child parent_line_id
            # references resolve correctly in the clone.
            id_map: dict[uuid.UUID, uuid.UUID] = {}
            # Two-pass to handle parent_line_id ordering.
            for ln in src_lines:
                new_line = ContractLine(
                    contract_id=clone.id,
                    parent_line_id=None,  # rewritten in pass 2
                    code=ln.code,
                    description=ln.description,
                    scope_section=ln.scope_section,
                    line_type=ln.line_type,
                    unit=ln.unit,
                    quantity=Decimal(str(ln.quantity or 0)),
                    unit_rate=Decimal(str(ln.unit_rate or 0)),
                    total_value=Decimal(str(ln.total_value or 0)),
                    order_index=ln.order_index,
                    metadata_=dict(getattr(ln, "metadata_", {}) or {}),
                )
                new_line = await self.line_repo.create(new_line)
                id_map[ln.id] = new_line.id
            # Pass 2 - wire up parent_line_id translations.
            for ln in src_lines:
                if ln.parent_line_id is None:
                    continue
                new_parent = id_map.get(ln.parent_line_id)
                if new_parent is None:
                    continue
                await self.line_repo.update_fields(
                    id_map[ln.id],
                    parent_line_id=new_parent,
                )

        # ── Sub-configurations ──────────────────────────────────────
        if copy_subconfigs:
            src_retention = await self.retention_repo.list_for_contract(source.id)
            for r in src_retention:
                self.session.add(
                    RetentionSchedule(
                        contract_id=clone.id,
                        accrual_rule=dict(r.accrual_rule or {}),
                        release_rule=dict(r.release_rule or {}),
                        notes=r.notes,
                    )
                )
            src_fee = await self.fee_repo.get_for_contract(source.id)
            if src_fee is not None:
                self.session.add(
                    FeeStructure(
                        contract_id=clone.id,
                        fee_type=src_fee.fee_type,
                        fee_percent=Decimal(str(src_fee.fee_percent or 0)),
                        fee_fixed_amount=(
                            None if src_fee.fee_fixed_amount is None else Decimal(str(src_fee.fee_fixed_amount))
                        ),
                        sliding_scale=list(src_fee.sliding_scale or []),
                        max_fee=(None if src_fee.max_fee is None else Decimal(str(src_fee.max_fee))),
                    )
                )
            src_gain = await self.gainshare_repo.get_for_contract(source.id)
            if src_gain is not None:
                self.session.add(
                    GainshareConfiguration(
                        contract_id=clone.id,
                        target_cost=Decimal(str(src_gain.target_cost or 0)),
                        gmp_cap=Decimal(str(src_gain.gmp_cap or 0)),
                        savings_split_owner_pct=Decimal(
                            str(src_gain.savings_split_owner_pct or 0),
                        ),
                        savings_split_contractor_pct=Decimal(
                            str(src_gain.savings_split_contractor_pct or 0),
                        ),
                        overrun_responsibility=src_gain.overrun_responsibility,
                    )
                )
            src_lds = await self.ld_repo.list_for_contract(source.id)
            for ld in src_lds:
                self.session.add(
                    LDClause(
                        contract_id=clone.id,
                        per_day_amount=Decimal(str(ld.per_day_amount or 0)),
                        currency=ld.currency,
                        max_amount=(None if ld.max_amount is None else Decimal(str(ld.max_amount))),
                        milestone_id=ld.milestone_id,
                        enforcement_status=ld.enforcement_status,
                    )
                )
            await self.session.flush()

        event_bus.publish_detached(
            "contracts.contract.cloned",
            data={
                "source_contract_id": str(source.id),
                "clone_contract_id": str(clone.id),
                "source_project_id": str(source.project_id),
                "dest_project_id": str(dest_project_id),
                "actor": user_id,
            },
            source_module="contracts",
        )
        logger.info(
            "Contract cloned: %s → %s (project %s → %s)",
            source.code,
            clone.code,
            source.project_id,
            dest_project_id,
        )
        return clone

    # ── Compliance gate (draft → active) ─────────────────────────────────

    async def _resolve_compliance_rule_packs(
        self,
        project_id: uuid.UUID,
    ) -> list[str]:
        """Resolve the compliance rule-pack ids enforced for a project.

        Reads ``Project.compliance_rule_packs`` (a JSON list). Falls back to
        the single default pack when the project row, the column, or the
        value is missing - so the gate always has at least one pack to run
        and never silently no-ops. Best-effort: a lookup failure degrades to
        the default pack rather than blocking the transition on infra error.
        """
        try:
            from app.modules.projects.models import Project  # noqa: PLC0415

            project = await self.session.get(Project, project_id)
        except Exception:
            logger.debug("Compliance gate: project lookup failed for %s", project_id)
            project = None
        packs = list(getattr(project, "compliance_rule_packs", None) or [])
        # Keep only string ids; guard against a malformed JSON payload.
        packs = [p for p in packs if isinstance(p, str) and p]
        return packs or [DEFAULT_PACK_ID]

    def _contract_lines_as_positions(
        self,
        lines: list[ContractLine],
    ) -> list[dict[str, Any]]:
        """Map SoV ``ContractLine`` rows onto the BOQ-position shape the
        validation engine's ``boq_quality`` / classification rules consume.

        The engine reads ``{"positions": [{id, ordinal, description, unit,
        quantity, unit_rate, total, classification, parent_id, type}]}``.
        Schedule-of-values lines carry exactly that data, so the contract's
        commercial breakdown is validated with the same battle-tested rules
        the BOQ uses - no parallel rule implementation. Parent (roll-up)
        rows are tagged ``type="section"`` via the parent graph so the
        leaf-only rules don't false-positive on header rows.
        """
        parent_ids = {ln.parent_line_id for ln in lines if ln.parent_line_id is not None}
        positions: list[dict[str, Any]] = []
        for ln in lines:
            classification = {}
            meta = getattr(ln, "metadata_", None) or {}
            if isinstance(meta, dict) and isinstance(meta.get("classification"), dict):
                classification = meta["classification"]
            positions.append(
                {
                    "id": str(ln.id),
                    "ordinal": ln.code or "",
                    "description": ln.description or "",
                    "unit": ln.unit,
                    "quantity": str(ln.quantity if ln.quantity is not None else 0),
                    "unit_rate": str(ln.unit_rate if ln.unit_rate is not None else 0),
                    "total": str(ln.total_value if ln.total_value is not None else 0),
                    "classification": classification,
                    "parent_id": str(ln.parent_line_id) if ln.parent_line_id else None,
                    "type": "section" if ln.id in parent_ids else "position",
                }
            )
        return positions

    async def run_compliance_gate(
        self,
        contract: Contract,
        *,
        workflow: str = WORKFLOW_CONTRACT_SIGNATURE,
    ) -> tuple[ValidationReport, list[str]]:
        """Run the compliance validation gate for a contract.

        Resolves the project's rule packs → the union of their validation
        rule sets → runs the :class:`ValidationEngine` against the contract's
        schedule of values. Returns ``(report, pack_ids)``. Deterministic and
        side-effect free: callers decide whether to block or persist based on
        ``report.has_errors``.
        """
        pack_ids = await self._resolve_compliance_rule_packs(contract.project_id)
        rule_sets = resolve_rule_sets(pack_ids, workflow=workflow)
        lines = await self.line_repo.list_for_contract(contract.id)
        positions = self._contract_lines_as_positions(lines)
        report = await validation_engine.validate(
            data=await with_project_context(self.session, contract.project_id, {"positions": positions}),
            rule_sets=rule_sets,
            target_type="contract",
            target_id=str(contract.id),
            project_id=str(contract.project_id),
            metadata={"locale": get_locale(), "workflow": workflow},
        )
        return report, pack_ids

    @staticmethod
    def _compliance_audit_entry(
        report: ValidationReport,
        pack_ids: list[str],
        *,
        actor_id: str | None,
        blocked: bool,
    ) -> dict[str, Any]:
        """Build the audit-trail block stored on ``contract.metadata_``."""
        from datetime import UTC
        from datetime import datetime as _dt

        def _serialise(r: Any) -> dict[str, Any]:
            return {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }

        return {
            "checked_at": _dt.now(UTC).isoformat(),
            "checked_by": actor_id,
            "workflow": WORKFLOW_CONTRACT_SIGNATURE,
            "rule_packs": pack_ids,
            "rule_sets": report.rule_sets_applied,
            "status": report.status.value,
            "score": report.score,
            "blocked": blocked,
            "counts": {
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "passed": len(report.passed_rules),
            },
            "errors": [_serialise(r) for r in report.errors],
            "warnings": [_serialise(r) for r in report.warnings],
        }

    def _compliance_http_detail(
        self,
        report: ValidationReport,
        pack_ids: list[str],
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Structured 422 body the ComplianceGate UI renders verbatim.

        ``message`` is the one line a caller that only gets a toast will see,
        so a gate whose findings are not rendered anywhere near the button it
        guards passes one that names them.
        """

        def _serialise(r: Any) -> dict[str, Any]:
            return {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }

        return {
            "error": "compliance_gate_failed",
            "message": (
                message or "Compliance gate failed: resolve the blocking issues below before signing this contract."
            ),
            "rule_packs": pack_ids,
            "rule_sets": report.rule_sets_applied,
            "status": report.status.value,
            "score": report.score,
            "counts": {
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "passed": len(report.passed_rules),
            },
            "errors": [_serialise(r) for r in report.errors],
            "warnings": [_serialise(r) for r in report.warnings],
        }

    async def enforce_compliance_gate(
        self,
        contract: Contract,
        *,
        actor_id: str | None = None,
    ) -> tuple[dict[str, Any], ValidationReport, list[str]]:
        """Run the compliance gate and raise 422 if it blocks.

        Returns ``(audit_entry, report, pack_ids)`` when the gate passes. The
        caller decides what to do with the audit entry; this method never writes
        it on the happy path, because the write belongs in whatever transaction
        the caller is already building.

        Two callers, and the second is the reason this is a method rather than
        an inline block. ``transition_contract`` runs it at ``draft → active``,
        which is the terminal moment. ``open_signing_session`` runs it *before*
        anyone is asked to sign, because a gate that only fires at the end tells
        a room full of people who have already signed that the contract was
        never eligible. Keeping both means the direct ``POST /sign`` path, which
        does not open a session, is still gated.
        """
        report, pack_ids = await self.run_compliance_gate(contract)
        blocked = report.has_errors
        audit_entry = self._compliance_audit_entry(
            report,
            pack_ids,
            actor_id=actor_id,
            blocked=blocked,
        )
        if not blocked:
            return audit_entry, report, pack_ids

        # Persist the blocking outcome so the failed attempt is auditable, then
        # raise a structured 422 the ComplianceGate UI renders verbatim.
        #
        # The audit is written in a SEPARATE, independent session that commits
        # on its own. Committing the *request* session here and then raising
        # used to corrupt the request lifecycle: the ``get_session`` dependency
        # rolls back on the raised HTTPException, and rolling back a request
        # session whose transaction was already explicitly committed left the
        # connection in a state where the unwind raised a *second* exception.
        # That secondary error hit the catch-all handler and the client saw a
        # misleading ``500 Internal server error`` instead of the 422 violation
        # list (even though the sign was, correctly, blocked). Using an isolated
        # session keeps the request transaction untouched so the HTTPException
        # reaches the client cleanly.
        meta = dict(contract.metadata_ or {})
        meta["compliance_validation"] = audit_entry
        try:
            from app.database import async_session_factory

            async with async_session_factory() as audit_session:
                await ContractRepository(audit_session).update_fields(
                    contract.id,
                    metadata_=meta,
                )
                await audit_session.commit()
        except Exception:
            # The audit trail is best-effort: never let a failure to record the
            # blocked attempt mask the real reason (the 422).
            logger.warning(
                "Failed to persist compliance-gate audit for contract %s",
                contract.code,
                exc_info=True,
            )
        logger.info(
            "Compliance gate BLOCKED contract %s (%d errors, packs=%s)",
            contract.code,
            len(report.errors),
            pack_ids,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=self._compliance_http_detail(report, pack_ids),
        )

    # ── The contract's own rule set (parties, securities, EOT, templates) ─

    async def _party_signing_name(self, party: Any) -> str:
        """The name this party would appear under on a signature block.

        The stored ``display_name`` when there is one, and the live name of
        whatever row the party links to otherwise. A party entered as a link
        rather than as typed text carries no stored name at all, so reading
        only the stored field would call a register empty while the screen
        shows the employer by name.
        """
        stored = (getattr(party, "display_name", "") or "").strip()
        if stored:
            return stored
        return (await self.resolve_party_name(party) or "").strip()

    async def run_contract_rules(self, contract: Contract) -> ValidationReport:
        """Run the ``contracts`` rule set against one contract.

        One builder and one run for both callers: the completeness endpoint the
        screen polls, and the gate that runs when the contract is put up for
        signature. Two copies of the context would let the report the user is
        shown drift away from the check that blocks them, which is the exact
        failure the hardcoded party refusal used to be.
        """
        from app.modules.contracts.validators import CONTRACTS_RULE_SET  # noqa: PLC0415

        parties = await self.party_repo.list_for_contract(contract.id)
        securities = await self.security_repo.list_for_contract(contract.id)
        eot_claims = await self.eot_repo.list_for_contract(contract.id)
        party_rows: list[dict[str, Any]] = []
        for p in parties:
            party_rows.append(
                {
                    "party_role": p.party_role,
                    "party_type": p.party_type,
                    "display_name": await self._party_signing_name(p),
                }
            )
        context = {
            "contract": {
                "id": str(contract.id),
                "status": contract.status,
                "contract_type": contract.contract_type,
                "terms": contract.terms or {},
                # Both of these, not just the code: the rule that reads them
                # asks whether the pair is complete, and a rule handed half a
                # pair can only ever pass.
                "template_code": contract.template_code,
                "template_version": contract.template_version,
            },
            "parties": party_rows,
            "securities": [{"security_type": s.security_type, "status": s.status} for s in securities],
            "eot_claims": [
                {
                    "id": str(e.id),
                    "eot_number": e.eot_number,
                    "days_claimed": e.days_claimed,
                    "days_granted": e.days_granted,
                    "status": e.status,
                }
                for e in eot_claims
            ],
        }
        return await validation_engine.validate(
            data=context,
            rule_sets=[CONTRACTS_RULE_SET],
            target_type="contract",
            target_id=str(contract.id),
            project_id=str(contract.project_id),
            metadata={"locale": get_locale(), "workflow": WORKFLOW_CONTRACT_SIGNATURE},
        )

    async def enforce_contract_rules(self, contract: Contract) -> ValidationReport:
        """Refuse to put a contract up for signature while its own rules block.

        This is what "the contract has nobody who signs" is now: a blocking
        finding from ``contracts.parties_complete``, carried in the same
        structured body the compliance gate returns and visible on the
        completeness panel long before anyone presses anything. The refusal it
        replaces was prose written at the call site, so it named no rule, made
        no suggestion the screen could render, and could not be seen coming.

        Every ERROR the rule set produces blocks, not just the party one.
        Naming a single rule id here would put the special case straight back
        where it was; the rule set *is* this module's statement of what a
        contract must be before it is executed.
        """
        from app.modules.contracts.validators import CONTRACTS_RULE_SET  # noqa: PLC0415

        report = await self.run_contract_rules(contract)
        if CONTRACTS_RULE_SET in report.unsupported_rule_sets:
            # The rules register from the module package's import, so a build
            # that reached this line without them would sail through a gate
            # that checked nothing and open a session nobody can sign. Say the
            # check could not run rather than let its silence read as a pass.
            logger.error("contracts: rule set %s is not registered; signing gate cannot run", CONTRACTS_RULE_SET)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "The contract validation rules are not loaded on this deployment, "
                    "so this contract cannot be checked before signature."
                ),
            )
        if not report.has_errors:
            return report

        # The caller here is the signing panel, whose error path is a toast, so
        # the findings have to survive being flattened to one line.
        heads = "; ".join(r.message for r in report.errors[:3])
        more = len(report.errors) - 3
        if more > 0:
            heads = f"{heads} (and {more} more)"
        logger.info(
            "Contract rules BLOCKED signature for %s (%d errors)",
            contract.code,
            len(report.errors),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=self._compliance_http_detail(
                report,
                [],
                message=f"This contract is not complete enough to put up for signature: {heads}",
            ),
        )

    async def transition_contract(
        self,
        contract_id: uuid.UUID,
        target_status: str,
        actor_id: str | None = None,
    ) -> Contract:
        """Apply a status transition with state-machine + compliance validation.

        Signing a contract (``draft → active``) first runs the compliance
        gate: the project's rule packs are resolved to validation rule sets
        and the engine evaluates the contract's schedule of values. Any
        blocking ERROR raises HTTP 422 with a structured violation list and
        the transition does not happen. The validation outcome (pass or
        block) is always recorded on ``contract.metadata_["compliance_validation"]``
        so the gate decision is auditable.
        """
        contract = await self.get_contract(contract_id)
        try:
            assert_contract_transition(contract.status, target_status)
        except InvalidTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        fields: dict[str, Any] = {"status": target_status}
        if target_status == "active" and contract.status == "draft":
            from datetime import UTC, datetime

            # ── Compliance gate ──────────────────────────────────────
            audit_entry, report, pack_ids = await self.enforce_compliance_gate(
                contract,
                actor_id=actor_id,
            )

            # Freeze the original contract value so it survives later
            # amendments via change orders and variations.  The current
            # value lives in total_value; this column is immutable after
            # being set and is the figure auditors compare against.
            fields["original_contract_value"] = contract.total_value

            # Gate passed - stamp the audit trail onto the contract metadata.
            meta = dict(contract.metadata_ or {})
            meta["compliance_validation"] = audit_entry
            fields["metadata_"] = meta
            fields["signed_at"] = datetime.now(UTC).isoformat()
            event_bus.publish_detached(
                "contracts.contract.signed",
                data={
                    "contract_id": str(contract.id),
                    "code": contract.code,
                    "project_id": str(contract.project_id),
                    "signed_by": actor_id,
                    "compliance_score": report.score,
                    "compliance_rule_packs": pack_ids,
                },
                source_module="contracts",
            )
        await self.contract_repo.update_fields(contract_id, **fields)
        await self.session.refresh(contract)
        return contract

    # ── E-signature bridge ───────────────────────────────────────────────
    #
    # The signing module is subject-neutral: it knows a document reference and a
    # content hash. Everything that makes a contract into those two strings is
    # in ``contracts.signing_bridge``; everything that needs a session is here.
    # The import is deferred in each method because modules are plugins and an
    # installation may not carry ``oe_signing``: a missing module has to answer
    # 503 on the three endpoints that need it, not break contracts at import.

    #: Session statuses that no longer hold the contract open. Anything else is
    #: an outstanding attempt to execute this paper.
    _SIGNING_CLOSED_STATUSES: frozenset[str] = frozenset({"declined", "expired"})

    def _signing_service(self) -> Any:
        try:
            from app.modules.signing.service import SigningService  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The e-signature module is not installed on this deployment.",
            ) from exc
        return SigningService(self.session)

    def _signing_repository(self) -> Any:
        try:
            from app.modules.signing.repository import SigningRepository  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The e-signature module is not installed on this deployment.",
            ) from exc
        return SigningRepository(self.session)

    async def contract_content_hash(self, contract: Contract) -> str:
        """Hash of the contract body a signatory would be signing right now."""
        parties = await self.party_repo.list_for_contract(contract.id)
        return signing_bridge.contract_content_hash(contract, list(parties))

    async def list_signing_sessions(self, contract_id: uuid.UUID) -> list[Any]:
        """Signing sessions opened against this contract, newest first."""
        await self.get_contract(contract_id)
        ref = signing_bridge.contract_document_ref(contract_id)
        return await self._signing_repository().list_sessions_for_document(ref)

    async def open_signing_session(
        self,
        contract_id: uuid.UUID,
        *,
        provider_capability: str = "simple_electronic",
        expires_at: Any = None,
        signatories: list[dict[str, Any]] | None = None,
        actor_id: str | None = None,
    ) -> Any:
        """Put a draft contract up for signature.

        Runs the compliance gate first and refuses to open the session at all if
        the gate blocks. That ordering is the whole point of this method: the
        gate also guards ``draft → active``, but by then every signatory has
        already signed, and telling them afterwards that the contract was never
        eligible is not a workflow anyone can act on.

        Only a draft is signable, and only one attempt may be outstanding: a
        second open session would give two content hashes for one contract and
        no answer to which one the signatures belong to.

        A contract whose party register names nobody who signs is refused, and
        the refusal is the module's own rule set answering rather than a check
        written here. That matters because the same rules run behind the
        completeness panel, so the state that stops the press is on screen
        before the press. The signatories are the point of the session, and one
        built from no parties would collect an attestation against a name that
        belongs to no company.
        """
        contract = await self.get_contract(contract_id)
        if contract.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Only a draft contract can be put up for signature (this one is {contract.status})."),
            )

        ref = signing_bridge.contract_document_ref(contract_id)
        existing = await self._signing_repository().list_sessions_for_document(ref)
        open_now = [s for s in existing if s.status not in self._SIGNING_CLOSED_STATUSES]
        if open_now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This contract already has a signing session in progress ({open_now[0].status}). "
                    "Close it before opening another."
                ),
            )

        await self.enforce_compliance_gate(contract, actor_id=actor_id)
        await self.enforce_contract_rules(contract)

        parties = list(await self.party_repo.list_for_contract(contract_id))
        # The gate above passes only when both required roles are on the
        # register under a name, and the map is derived from the same resolved
        # names, so it cannot come back empty here.
        signatory_map = signatories or signing_bridge.signatory_map_from_parties(
            [
                signing_bridge.SigningParty(
                    party_role=p.party_role or "",
                    display_name=await self._party_signing_name(p),
                )
                for p in parties
            ]
        )

        from pydantic import ValidationError  # noqa: PLC0415

        from app.modules.signing.schemas import SigningSessionCreate  # noqa: PLC0415

        try:
            payload = SigningSessionCreate(
                project_id=contract.project_id,
                document_ref=ref,
                # The stored rows, not the name-resolved view above. The hash
                # is a function of what the contract records; feeding it a name
                # looked up elsewhere would move the hash of every contract
                # whose parties are links, and moving a hash is what marks a
                # signature stale.
                document_content_hash=signing_bridge.contract_content_hash(contract, parties),
                provider_capability=provider_capability,
                signatory_map=signatory_map,
                expires_at=expires_at,
                metadata={"contract_code": contract.code, "contract_title": contract.title},
            )
        except ValidationError as exc:
            # The capability vocabulary and the unique-role rule are owned by the
            # signing module, so this is where its verdict becomes an HTTP answer
            # rather than a 500. Restating either rule in the contracts schema
            # would give the platform two lists that drift apart.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "invalid_signing_session",
                    "message": "The signing register refused this session.",
                    "details": exc.errors(include_url=False),
                },
            ) from exc

        session_row = await self._signing_service().create_session(payload, user_id=actor_id)
        logger.info(
            "Signing session %s opened for contract %s (%d signatories)",
            session_row.id,
            contract.code,
            len(signatory_map),
        )
        return session_row

    async def signing_session_view(self, contract: Contract, session_row: Any) -> dict[str, Any]:
        """Serialise one session with the two derived fields the screen needs.

        ``content_hash_current`` compares the session's hash against what the
        contract hashes to right now, and ``stale_signatories`` names whoever
        signed a hash the session has since moved off. Both are computed rather
        than stored, so they cannot go out of date the way a cached flag would.
        """
        from app.modules.signing.service import delta_by_hash  # noqa: PLC0415

        signatures = await self._signing_repository().list_signatures_for_session(session_row.id)
        current = await self.contract_content_hash(contract)
        return {
            "id": session_row.id,
            "document_ref": session_row.document_ref,
            "document_content_hash": session_row.document_content_hash,
            "provider_capability": session_row.provider_capability,
            "delivered_capability": session_row.delivered_capability,
            "status": session_row.status,
            "signatory_map": list(session_row.signatory_map or []),
            "expires_at": session_row.expires_at,
            "created_at": getattr(session_row, "created_at", None),
            "content_hash_current": session_row.document_content_hash == current,
            "stale_signatories": sorted(n for n in delta_by_hash(signatures, session_row.document_content_hash) if n),
            "signed_roles": sorted({s.signatory_role for s in signatures if s.status == "signed" and s.signatory_role}),
        }

    async def refresh_signing_content_hash(self, contract_id: uuid.UUID) -> int:
        """Push the contract's current hash onto its outstanding sessions.

        This is what makes ``signing.delta_by_hash`` able to fire at all. That
        function compares each attestation's hash against the session's current
        one, so a signature can only ever be reported stale if somebody updates
        the session when the paper changes. The signing module cannot: it has no
        way to look at a contract. So the duty is here, on the write path that
        changes the contract.

        Returns the number of sessions moved. Best-effort by design: a contract
        edit must not fail because the signing register could not be updated,
        and a deployment without ``oe_signing`` reports zero rather than 503.
        """
        try:
            repo = self._signing_repository()
        except HTTPException:
            return 0
        contract = await self.get_contract(contract_id)
        ref = signing_bridge.contract_document_ref(contract_id)
        current = await self.contract_content_hash(contract)

        moved = 0
        for row in await repo.list_sessions_for_document(ref):
            if row.status in self._SIGNING_CLOSED_STATUSES:
                continue
            if row.document_content_hash == current:
                continue
            row.document_content_hash = current
            moved += 1
        if moved:
            await self.session.flush()
            logger.info(
                "Contract %s changed: %d signing session(s) re-hashed, earlier signatures now stale",
                contract.code,
                moved,
            )
        return moved

    async def sync_contract_from_signing(
        self,
        contract_id: uuid.UUID,
        actor_id: str | None = None,
    ) -> Contract:
        """Bring the contract status into line with its signing session.

        A fully signed session moves a draft contract to active through the
        normal transition, which re-runs the compliance gate. Running the gate
        twice is deliberate: the paper can change between opening the session
        and the last signature, and the transition is the only place that stamps
        the audit entry the contract carries afterwards.

        Anything short of fully signed leaves the contract alone and returns it
        unchanged, so this is safe to call on every read of the signing panel.
        """
        contract = await self.get_contract(contract_id)
        if contract.status != "draft":
            return contract

        ref = signing_bridge.contract_document_ref(contract_id)
        sessions = await self._signing_repository().list_sessions_for_document(ref)
        if not any(s.status == "fully_signed" for s in sessions):
            return contract
        return await self.transition_contract(contract_id, "active", actor_id)

    # ── ContractLines ────────────────────────────────────────────────────

    async def create_line(self, data: Any) -> ContractLine:
        qty = Decimal(str(data.quantity or 0))
        rate = Decimal(str(data.unit_rate or 0))
        total = qty * rate
        line = ContractLine(
            contract_id=data.contract_id,
            parent_line_id=data.parent_line_id,
            code=data.code,
            description=data.description,
            scope_section=data.scope_section,
            line_type=data.line_type,
            unit=data.unit,
            quantity=qty,
            unit_rate=rate,
            total_value=total,
            order_index=data.order_index,
            metadata_=data.metadata,
        )
        line = await self.line_repo.create(line)
        return line

    async def bulk_create_lines(
        self,
        contract_id: uuid.UUID,
        items: list[Any],
    ) -> list[ContractLine]:
        await self.get_contract(contract_id)
        lines: list[ContractLine] = []
        for it in items:
            qty = Decimal(str(it.quantity or 0))
            rate = Decimal(str(it.unit_rate or 0))
            lines.append(
                ContractLine(
                    contract_id=contract_id,
                    parent_line_id=it.parent_line_id,
                    code=it.code,
                    description=it.description,
                    scope_section=it.scope_section,
                    line_type=it.line_type,
                    unit=it.unit,
                    quantity=qty,
                    unit_rate=rate,
                    total_value=qty * rate,
                    order_index=it.order_index,
                    metadata_=it.metadata,
                )
            )
        return await self.line_repo.bulk_create(lines)

    async def update_line(
        self,
        line_id: uuid.UUID,
        data: Any,
    ) -> ContractLine:
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Contract line not found")
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(line, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )
        # Recompute total if quantity / unit_rate changed.
        qty = Decimal(str(fields.get("quantity", line.quantity) or 0))
        rate = Decimal(str(fields.get("unit_rate", line.unit_rate) or 0))
        fields["total_value"] = qty * rate
        await self.line_repo.update_fields(line_id, **fields)
        await self.session.refresh(line)
        return line

    async def delete_line(self, line_id: uuid.UUID) -> None:
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            return
        await self.line_repo.delete(line_id)

    # ── Progress claims ──────────────────────────────────────────────────

    async def create_progress_claim(self, data: Any) -> ProgressClaim:
        contract = await self.get_contract(data.contract_id)
        claim_number = data.claim_number or await self.claim_repo.next_claim_number(
            contract.id,
        )
        claim = ProgressClaim(
            contract_id=contract.id,
            claim_number=claim_number,
            period_start=data.period_start,
            period_end=data.period_end,
            claim_date=data.claim_date,
            currency=data.currency or contract.currency,
            milestone_id=getattr(data, "milestone_id", None),
            metadata_=data.metadata,
            status="draft",
        )
        return await self.claim_repo.create(claim)

    async def transition_claim(
        self,
        claim_id: uuid.UUID,
        target_status: str,
        actor_id: str | None = None,
    ) -> ProgressClaim:
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        try:
            assert_claim_transition(claim.status, target_status)
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        from datetime import UTC, datetime

        fields: dict[str, Any] = {"status": target_status}
        now = datetime.now(UTC).isoformat()
        if target_status == "submitted":
            fields["submitted_at"] = now
            event_bus.publish_detached(
                "contracts.claim.submitted",
                data={
                    "claim_id": str(claim.id),
                    "contract_id": str(claim.contract_id),
                    "claim_number": claim.claim_number,
                    "net_due": str(claim.net_due),
                    "actor": actor_id,
                },
                source_module="contracts",
            )
        elif target_status == "approved":
            fields["approved_at"] = now
            event_bus.publish_detached(
                "contracts.claim.approved",
                data={
                    "claim_id": str(claim.id),
                    "contract_id": str(claim.contract_id),
                    "net_due": str(claim.net_due),
                    "actor": actor_id,
                },
                source_module="contracts",
            )
        elif target_status == "certified":
            # Stamp certifier identity + timestamp onto metadata (no dedicated
            # column on the model) so the certification is auditable, then
            # emit the event finance / BI dashboards subscribe to. Without
            # this event a certified claim never spawns its AR invoice and
            # never reaches the dashboards (real cross-module money defect).
            cert_meta = dict(claim.metadata_ or {})
            cert_meta["certified_at"] = now
            cert_meta["certified_by"] = actor_id
            fields["metadata_"] = cert_meta
            event_bus.publish_detached(
                "contracts.claim.certified",
                data={
                    "claim_id": str(claim.id),
                    "contract_id": str(claim.contract_id),
                    "claim_number": claim.claim_number,
                    "net_due": str(claim.net_due),
                    "actor": actor_id,
                },
                source_module="contracts",
            )
        elif target_status == "paid":
            fields["paid_at"] = now
            event_bus.publish_detached(
                "contracts.claim.paid",
                data={
                    "claim_id": str(claim.id),
                    "contract_id": str(claim.contract_id),
                    "net_due": str(claim.net_due),
                    "actor": actor_id,
                },
                source_module="contracts",
            )
        await self.claim_repo.update_fields(claim_id, **fields)
        await self.session.refresh(claim)
        return claim

    async def auto_generate_claim_lines(
        self,
        claim_id: uuid.UUID,
        payload: Any,
    ) -> ProgressClaim:
        """Auto-generate claim lines + roll up totals based on contract type.

        Refuses non-``draft`` claims: a submitted / approved / certified /
        paid / rejected claim is part of the immutable audit trail, and
        silently rewriting its line breakdown and gross / retention /
        net totals would corrupt reconciliation against AR and the lien
        waiver chain. Changes after submission must go through the
        proper transition + new-claim workflow.
        """
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        if claim.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "claim_not_draft",
                    "message": (
                        "Auto-generate is only valid for draft claims; the "
                        f"claim is currently in status {claim.status!r}. "
                        "Create a new draft claim or reset this one via the "
                        "rejected → draft transition."
                    ),
                    "claim_status": claim.status,
                },
            )
        contract = await self.get_contract(claim.contract_id)
        lines = await self.line_repo.list_for_contract(contract.id)
        prior_paid = await self.claim_repo.paid_total(contract.id)
        fee_structure = await self.fee_repo.get_for_contract(contract.id)

        result: dict[str, Any]
        if contract.contract_type == "lump_sum":
            result = generate_lump_sum_claim(
                contract,
                lines,
                payload.completion or {},
                prior_paid,
            )
        elif contract.contract_type in ("unit_price", "remeasurement"):
            # Remeasurement contracts bill re-measured quantities at agreed
            # unit rates, exactly like unit-price, so they share the generator.
            result = generate_unit_price_claim(
                contract,
                lines,
                payload.measurements or {},
                prior_paid,
            )
        elif contract.contract_type == "cost_plus":
            result = generate_cost_plus_claim(
                contract,
                fee_structure,
                Decimal(str(payload.actual_costs_total or 0)),
                prior_paid,
            )
            result["claim_lines"] = []
        elif contract.contract_type == "tm":
            try:
                result = generate_tm_claim(
                    contract,
                    Decimal(str(payload.time_entries_total or 0)),
                    Decimal(str(payload.material_entries_total or 0)),
                    fee_structure,
                    prior_paid,
                )
            except NTECapExceededError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "nte_cap_exceeded", "message": str(exc)},
                ) from exc
            result["claim_lines"] = []
        else:
            # GMP / design_build / combination - default to lump-sum semantics
            result = generate_lump_sum_claim(
                contract,
                lines,
                payload.completion or {},
                prior_paid,
            )

        # Persist new claim lines (replacing any existing draft ones).
        existing = await self.claim_line_repo.list_for_claim(claim_id)
        for ex in existing:
            await self.claim_line_repo.delete(ex.id)
        # Running total: per SoV line, cumulative = sum of period values already
        # billed on prior (non-rejected) claims + this period. Downstream
        # consumers (costmodel claimed-to-date) read cumulative_completed_value
        # as the running total, so it must net prior claims, not just this one.
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(
            contract.id,
            exclude_claim_id=claim_id,
        )
        new_lines: list[ProgressClaimLine] = []
        for cl in result.get("claim_lines", []) or []:
            period_value = Decimal(str(cl["period_completed_value"]))
            prior_value = prior_by_line.get(cl["contract_line_id"], DEC_ZERO)
            new_lines.append(
                ProgressClaimLine(
                    progress_claim_id=claim_id,
                    contract_line_id=cl["contract_line_id"],
                    period_completed_qty=Decimal(str(cl["period_completed_qty"])),
                    period_completed_value=period_value,
                    period_completed_pct=Decimal(str(cl["period_completed_pct"])),
                    cumulative_completed_value=(prior_value + period_value).quantize(
                        Decimal("0.0001"),
                    ),
                )
            )
        if new_lines:
            await self.claim_line_repo.bulk_create(new_lines)

        # Roll up totals on the claim row.
        await self.claim_repo.update_fields(
            claim_id,
            gross_amount=Decimal(str(result["gross"])),
            retention_amount=Decimal(str(result["retention"])),
            prior_claims_total=Decimal(str(prior_paid)),
            net_due=Decimal(str(result["net"])),
        )
        await self.session.refresh(claim)
        return claim

    # ── Progress bridge (Gap I) ──────────────────────────────────────────

    #: Claim statuses whose line breakdown may still be edited. A submitted
    #: claim is still owner-editable before approval (a re-measure is common
    #: mid-review); once approved / certified / paid / rejected the breakdown
    #: is part of the immutable audit trail.
    _CLAIM_EDITABLE_STATUSES = frozenset({"draft", "submitted"})

    def _assert_claim_editable(self, claim: ProgressClaim) -> None:
        """Raise HTTP 422 unless the claim is in a line-editable status."""
        if claim.status not in self._CLAIM_EDITABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "claim_not_editable",
                    "message": (
                        "Progress lines can only be populated / committed on a "
                        f"draft or submitted claim; this claim is {claim.status!r}."
                    ),
                    "claim_status": claim.status,
                },
            )

    async def populate_claim_from_progress(
        self,
        claim_id: uuid.UUID,
        *,
        boq_position_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        """Preview claim lines derived from the latest progress observations.

        Read-only: builds the line breakdown the claim WOULD get if committed,
        without persisting anything, so the UI can let the user deselect / tweak
        first. For every SoV line that links to a BOQ position
        (``ContractLine.metadata_["boq_position_id"]``) the latest
        ``ProgressEntry`` for that position is read and its percent-complete is
        applied to the line value (same currency as the claim - currencies are
        never blended; a SoV line in a different currency than the claim is
        skipped and counted).

        Args:
            claim_id: target progress claim.
            boq_position_ids: optional filter - only preview lines whose linked
                BOQ position is in this set.

        Raises:
            HTTPException 404 if the claim is missing; 422 if it is not in a
            line-editable status.
        """
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        self._assert_claim_editable(claim)
        contract = await self.get_contract(claim.contract_id)
        claim_currency = claim.currency or contract.currency or ""

        position_filter: set[uuid.UUID] | None = set(boq_position_ids) if boq_position_ids else None

        from app.modules.progress.repository import ProgressRepository  # noqa: PLC0415

        progress_repo = ProgressRepository(self.session)

        lines = await self.line_repo.list_for_contract(contract.id)
        # Roll-up / parent rows are summed from children - never bill them
        # directly, exactly as the auto-generate path does.
        parent_ids = {ln.parent_line_id for ln in lines if getattr(ln, "parent_line_id", None) is not None}

        items: list[dict[str, Any]] = []
        skipped_unlinked = 0
        skipped_no_progress = 0
        skipped_foreign_currency = 0

        for ln in lines:
            if getattr(ln, "id", None) in parent_ids:
                continue
            pos_id = boq_position_id_for_line(ln)
            if pos_id is None:
                skipped_unlinked += 1
                continue
            if position_filter is not None and pos_id not in position_filter:
                continue
            # Never blend currencies: a SoV line whose own currency differs
            # from the claim currency cannot be summed into this claim's gross.
            ln_meta = getattr(ln, "metadata_", None)
            line_currency = ln_meta.get("currency") if isinstance(ln_meta, dict) else None
            if line_currency and claim_currency and str(line_currency).upper() != claim_currency.upper():
                skipped_foreign_currency += 1
                continue
            entry = await progress_repo.get_latest_for_position(contract.project_id, pos_id)
            if entry is None:
                skipped_no_progress += 1
                continue
            observed_pct = Decimal(str(entry.percent_complete or 0))
            derived = compute_progress_claim_line(ln, observed_pct)
            items.append(
                {
                    "contract_line_id": ln.id,
                    "contract_line_code": ln.code or "",
                    "contract_line_description": ln.description or "",
                    "boq_position_id": pos_id,
                    "unit": ln.unit,
                    "contract_quantity": Decimal(str(ln.quantity or 0)),
                    "contract_line_value": Decimal(str(ln.total_value or 0)),
                    "observed_pct": derived["period_completed_pct"],
                    "period_label": entry.period_label,
                    "recorded_at": entry.recorded_at,
                    "period_completed_qty": derived["period_completed_qty"],
                    "period_completed_value": derived["period_completed_value"],
                    "cumulative_completed_value": derived["cumulative_completed_value"],
                }
            )

        prior_paid = await self.claim_repo.paid_total(contract.id)
        gross = sum((it["period_completed_value"] for it in items), DEC_ZERO)
        pct = Decimal(str(contract.retention_percent or 0))
        retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
        net = gross - retention - prior_paid
        if net < DEC_ZERO:
            net = DEC_ZERO
        return {
            "claim_id": claim.id,
            "contract_id": contract.id,
            "currency": claim_currency,
            "items": items,
            "skipped_unlinked": skipped_unlinked,
            "skipped_no_progress": skipped_no_progress,
            "skipped_foreign_currency": skipped_foreign_currency,
            "gross": gross,
            "retention": retention,
            "prior_claims_total": prior_paid,
            "net_due": net,
        }

    async def commit_preview_to_claim(
        self,
        claim_id: uuid.UUID,
        lines_data: list[Any],
        *,
        actor_id: str | None = None,
    ) -> ProgressClaim:
        """Persist a populated / edited set of claim lines and roll up totals.

        Idempotent: every existing line on the claim is deleted first, then the
        submitted ``lines_data`` is written, so committing the same preview
        twice yields one set of lines (never duplicates). Each line's value is
        recomputed server-side (percent × contract line value, or the supplied
        override clamped to the line value) so a tampered total cannot inflate
        the claim. The claim's gross / retention / prior / net are then re-rolled
        and ``contracts.claim.populated`` is emitted.

        Raises:
            HTTPException 404 if the claim or a referenced contract line is
            missing; 422 if the claim is not line-editable.
        """
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        self._assert_claim_editable(claim)
        contract = await self.get_contract(claim.contract_id)

        # Resolve + validate every referenced contract line belongs to this
        # claim's contract BEFORE mutating anything (no partial writes).
        contract_lines = await self.line_repo.list_for_contract(contract.id)
        line_by_id = {ln.id: ln for ln in contract_lines}
        resolved: list[tuple[Any, dict[str, Decimal]]] = []
        for item in lines_data or []:
            cl_id = item.contract_line_id
            sov_line = line_by_id.get(cl_id)
            if sov_line is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": "contract_line_not_found",
                        "message": (f"Contract line {cl_id} does not belong to contract {contract.id}"),
                        "contract_line_id": str(cl_id),
                    },
                )
            derived = compute_progress_claim_line(
                sov_line,
                getattr(item, "period_completed_pct", 0),
                value_override=getattr(item, "period_completed_value", None),
            )
            resolved.append((sov_line, derived))

        # Idempotent replace: wipe existing lines, then write the new set.
        await self.claim_line_repo.delete_for_claim(claim_id)
        # Running total: cumulative = prior non-rejected period values on this
        # SoV line + this period. costmodel reads cumulative_completed_value as
        # the running claimed-to-date total, so it must net prior claims.
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(
            contract.id,
            exclude_claim_id=claim_id,
        )
        new_lines: list[ProgressClaimLine] = [
            ProgressClaimLine(
                progress_claim_id=claim_id,
                contract_line_id=sov_line.id,
                period_completed_qty=derived["period_completed_qty"],
                period_completed_value=derived["period_completed_value"],
                period_completed_pct=derived["period_completed_pct"],
                cumulative_completed_value=(
                    prior_by_line.get(sov_line.id, DEC_ZERO) + derived["period_completed_value"]
                ).quantize(Decimal("0.0001")),
            )
            for sov_line, derived in resolved
        ]
        if new_lines:
            await self.claim_line_repo.bulk_create(new_lines)

        prior_paid = await self.claim_repo.paid_total(contract.id)
        gross = sum((ln.period_completed_value for ln in new_lines), DEC_ZERO)
        pct = Decimal(str(contract.retention_percent or 0))
        retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
        net = gross - retention - prior_paid
        if net < DEC_ZERO:
            net = DEC_ZERO
        await self.claim_repo.update_fields(
            claim_id,
            gross_amount=gross,
            retention_amount=retention,
            prior_claims_total=prior_paid,
            net_due=net,
        )
        await self.session.refresh(claim)
        event_bus.publish_detached(
            CLAIM_POPULATED,
            data={
                "claim_id": str(claim.id),
                "contract_id": str(contract.id),
                "claim_number": claim.claim_number,
                "line_count": len(new_lines),
                "gross": str(gross),
                "retention": str(retention),
                "net_due": str(net),
                "currency": claim.currency or contract.currency or "",
                "actor": actor_id,
            },
            source_module="contracts",
        )
        return claim

    # ── Gainshare ────────────────────────────────────────────────────────

    async def gainshare_preview(
        self,
        contract_id: uuid.UUID,
        actual_cost: Decimal,
    ) -> dict[str, Any]:
        contract = await self.get_contract(contract_id)
        if contract.contract_type != "gmp":
            raise HTTPException(
                status_code=400,
                detail="Gainshare preview is only valid for GMP contracts",
            )
        cfg = await self.gainshare_repo.get_for_contract(contract_id)
        if cfg is None:
            raise HTTPException(
                status_code=404,
                detail="No gainshare configuration for this contract",
            )
        share = compute_gmp_gainshare(
            actual_cost,
            cfg.target_cost,
            cfg.gmp_cap,
            cfg.savings_split_owner_pct,
            cfg.savings_split_contractor_pct,
        )
        return {
            "actual_cost": Decimal(str(actual_cost)),
            "target_cost": cfg.target_cost,
            "gmp_cap": cfg.gmp_cap,
            "savings": share["savings"],
            "owner_share": share["owner_share"],
            "contractor_share": share["contractor_share"],
            "overrun": share["overrun"],
            "overrun_responsibility": cfg.overrun_responsibility,
        }

    # ── Change orders & close-out ────────────────────────────────────────

    async def apply_change_order_to_contract(
        self,
        contract_id: uuid.UUID,
        co_amount: Decimal,
        co_schedule_days: int = 0,
        co_reference: str | None = None,
    ) -> Contract:
        """Increment the contract value by a change-order delta.

        Emits ``contracts.contract.amended``.

        Change orders are only valid on commercially-live contracts (``active``
        or ``suspended``). Applying a change order to a ``terminated`` or
        ``completed`` contract would silently rewrite the final agreed value,
        corrupt the audit trail, and - for ``terminated`` contracts - partially
        resurrect a dead instrument. Value adjustments after close-out must
        go through a final-account amendment instead.
        """
        contract = await self.get_contract(contract_id)
        if contract.status in ("terminated", "completed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "contract_not_amendable",
                    "message": (
                        f"Change orders cannot be applied to a contract in "
                        f"status {contract.status!r}. Use the final-account "
                        "amendment workflow for post-close adjustments."
                    ),
                    "contract_status": contract.status,
                },
            )
        delta = Decimal(str(co_amount or 0))
        new_value = Decimal(str(contract.total_value or 0)) + delta
        # Mirror the metadata stamps written by the ``changeorder.approved``
        # subscriber (notifications wave-5) so both application paths feed
        # the same rollup: append the CO reference to ``change_order_ids``
        # and accumulate ``change_order_total``. Keeping the key present
        # also lets AIA G702 trust the tracked rollup even when it nets to
        # zero (audit m7).
        md = dict(contract.metadata_ or {})
        applied = list(md.get("change_order_ids") or [])
        if co_reference and str(co_reference) not in {str(v) for v in applied}:
            applied.append(str(co_reference))
        md["change_order_ids"] = applied
        try:
            running = Decimal(str(md.get("change_order_total") or 0))
        except (InvalidOperation, ValueError, TypeError):
            running = Decimal("0")
        md["change_order_total"] = str(running + delta)
        await self.contract_repo.update_fields(
            contract_id,
            total_value=new_value,
            metadata_=md,
        )
        await self.session.refresh(contract)
        event_bus.publish_detached(
            "contracts.contract.amended",
            data={
                "contract_id": str(contract_id),
                "delta_amount": str(delta),
                "new_total_value": str(new_value),
                "schedule_delta_days": int(co_schedule_days or 0),
                "co_reference": co_reference,
            },
            source_module="contracts",
        )
        return contract

    async def close_contract(
        self,
        contract_id: uuid.UUID,
        payload: Any,
        actor_id: str | None = None,
    ) -> FinalAccount:
        """Close a contract - create / update the FinalAccount + flip status."""
        contract = await self.get_contract(contract_id)
        existing = await self.final_account_repo.get_for_contract(contract_id)
        fields: dict[str, Any] = {
            "final_contract_value": Decimal(str(payload.final_contract_value or 0)),
            "total_paid": Decimal(str(payload.total_paid or 0)),
            "retention_held": Decimal(str(payload.retention_held or 0)),
            "retention_released": Decimal(str(payload.retention_released or 0)),
            "final_balance": Decimal(str(payload.final_balance or 0)),
            "sign_off_date": payload.sign_off_date,
            "sign_off_by": payload.sign_off_by or actor_id,
            "status": payload.status,
            "notes": payload.notes,
        }
        if existing is None:
            final_account = FinalAccount(contract_id=contract_id, **fields)
            final_account = await self.final_account_repo.create(final_account)
        else:
            await self.final_account_repo.update_fields(existing.id, **fields)
            await self.session.refresh(existing)
            final_account = existing

        # Mark contract completed if not already.
        if contract.status not in ("completed", "terminated"):
            try:
                assert_contract_transition(contract.status, "completed")
            except InvalidTransitionError:
                logger.warning(
                    "Cannot mark contract %s completed from status %s",
                    contract_id,
                    contract.status,
                )
            else:
                await self.contract_repo.update_fields(
                    contract_id,
                    status="completed",
                )

        event_bus.publish_detached(
            "contracts.contract.closed",
            data={
                "contract_id": str(contract_id),
                "final_balance": str(final_account.final_balance),
                "final_contract_value": str(final_account.final_contract_value),
                "actor": actor_id,
            },
            source_module="contracts",
        )
        return final_account

    # ── SOV status (Schedule of Values per-line tracker) ────────────────

    async def sov_status(self, contract_id: uuid.UUID) -> dict[str, Any]:
        """Build the Schedule-of-Values status: scheduled vs earned vs paid per line."""
        contract = await self.get_contract(contract_id)
        lines = await self.line_repo.list_for_contract(contract.id)
        # Single JOIN instead of N+1 (one claim-line query per claim).
        tagged_claim_lines: list[Any] = []
        for cl, claim_status in await self.claim_line_repo.lines_with_status_for_contract(
            contract.id,
        ):
            try:
                cl._claim_status = claim_status
            except AttributeError:
                pass
            tagged_claim_lines.append(cl)
        return compute_sov_status(
            lines,
            tagged_claim_lines,
            retention_percent=contract.retention_percent,
        )

    # ── Retention release ───────────────────────────────────────────────

    async def release_retention(
        self,
        contract_id: uuid.UUID,
        event: str,
        *,
        custom_schedule: dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Release retention for a contract for ``event``.

        Records the release in contract.metadata['retention_releases'] (an
        append-only list) so audit history survives. Emits
        ``contracts.retention.released``.
        """
        contract = await self.get_contract(contract_id)
        if contract.status not in ("active", "suspended", "completed"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Cannot release retention on contract in status {contract.status!r}"),
            )
        # Sum outstanding retention from claim repo (less anything already released).
        held = await self.claim_repo.outstanding_retention(contract_id)
        meta = dict(contract.metadata_ or {})
        prior_releases = list(meta.get("retention_releases", []) or [])
        # Idempotency / audit-trail integrity: the same event must not be
        # released twice. Pre-fix the audit log was append-only but never
        # consulted to dedupe, so each call would compute net_held = held -
        # already_released and re-release the configured percentage of
        # whatever was left - asymptotically draining retention to zero
        # regardless of the schedule's stated intent.
        if any(r.get("event") == event for r in prior_releases):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "retention_event_already_released",
                    "message": (
                        f"Retention has already been released for event "
                        f"{event!r}. Use a different event key or a custom "
                        "schedule entry to make a further release."
                    ),
                    "event": event,
                },
            )
        already_released = sum(
            (Decimal(str(r.get("amount_released", 0) or 0)) for r in prior_releases),
            DEC_ZERO,
        )
        net_held = held - already_released
        if net_held < DEC_ZERO:
            net_held = DEC_ZERO

        # Validate custom_schedule values up-front so a configuration
        # mistake (negative, > 100, or non-numeric percentage) fails
        # loudly instead of being silently clamped by plan_retention_release.
        if custom_schedule is not None:
            for key, val in custom_schedule.items():
                try:
                    pct = Decimal(str(val))
                except (ArithmeticError, ValueError):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "invalid_custom_schedule",
                            "message": (f"custom_schedule[{key!r}] must be numeric, got {val!r}"),
                        },
                    ) from None
                if pct < DEC_ZERO or pct > DEC_HUNDRED:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "invalid_custom_schedule",
                            "message": (f"custom_schedule[{key!r}] must be between 0 and 100, got {val!r}"),
                        },
                    )

        result = plan_retention_release(
            net_held,
            event,
            schedule=custom_schedule,
        )
        # Persist into metadata
        releases = list(meta.get("retention_releases", []) or [])
        from datetime import UTC
        from datetime import datetime as _dt

        releases.append(
            {
                "event": event,
                "released_at": _dt.now(UTC).isoformat(),
                "released_by": actor_id,
                "percent_released": str(result["percent_released"]),
                "amount_released": str(result["amount_released"]),
                "remaining": str(result["remaining"]),
            }
        )
        meta["retention_releases"] = releases
        await self.contract_repo.update_fields(contract_id, metadata_=meta)
        await self.session.refresh(contract)
        event_bus.publish_detached(
            "contracts.retention.released",
            data={
                "contract_id": str(contract_id),
                "event": event,
                "amount_released": str(result["amount_released"]),
                "remaining": str(result["remaining"]),
                "actor": actor_id,
            },
            source_module="contracts",
        )
        return {
            "contract_id": str(contract_id),
            "event": event,
            "amount_released": str(result["amount_released"]),
            "percent_released": str(result["percent_released"]),
            "remaining": str(result["remaining"]),
            "total_held_before": str(held),
            "released_so_far": str(already_released + result["amount_released"]),
        }

    # ── Lien waivers (US compliance) ────────────────────────────────────

    async def attach_lien_waiver(
        self,
        claim_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach a lien-waiver record to a progress claim.

        Waivers are persisted onto ``ProgressClaim.metadata['lien_waivers']``
        as an append-only list (one waiver per period / signing).
        """
        ok, errors = validate_lien_waiver_payload(payload)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_lien_waiver", "details": errors},
            )
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        # Lien waivers are a legal release of lien rights tied to a specific
        # payment application. A waiver on a draft claim (never submitted)
        # has no underlying lien to release; one on a rejected claim ties
        # the waiver to an amount the owner has explicitly refused. Both
        # are operationally bogus and reject up-front.
        if claim.status in ("draft", "rejected"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "claim_not_in_lienable_state",
                    "message": (
                        "Lien waivers can only be attached to claims that "
                        "have been submitted to the owner. Current status: "
                        f"{claim.status!r}."
                    ),
                    "claim_status": claim.status,
                },
            )
        meta = dict(claim.metadata_ or {})
        waivers = list(meta.get("lien_waivers", []) or [])
        from datetime import UTC
        from datetime import datetime as _dt

        record = {
            "waiver_type": payload["waiver_type"],
            "through_date": payload["through_date"],
            "amount": str(payload["amount"]),
            "signed_by": payload["signed_by"],
            "jurisdiction": payload.get("jurisdiction") or "",
            "document_url": payload.get("document_url") or "",
            "notes": payload.get("notes") or "",
            "attached_at": _dt.now(UTC).isoformat(),
            "attached_by": actor_id,
        }
        waivers.append(record)
        meta["lien_waivers"] = waivers
        await self.claim_repo.update_fields(claim_id, metadata_=meta)
        await self.session.refresh(claim)
        event_bus.publish_detached(
            "contracts.lien_waiver.attached",
            data={
                "claim_id": str(claim_id),
                "contract_id": str(claim.contract_id),
                "waiver_type": record["waiver_type"],
                "amount": record["amount"],
                "through_date": record["through_date"],
                "actor": actor_id,
            },
            source_module="contracts",
        )
        return record

    async def list_lien_waivers(self, claim_id: uuid.UUID) -> list[dict[str, Any]]:
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        return list((claim.metadata_ or {}).get("lien_waivers", []) or [])

    # ── Dashboard ────────────────────────────────────────────────────────

    @staticmethod
    def _change_order_rollup(contract: Contract) -> tuple[int, Decimal]:
        """Count + net value of CO/VO adjustments tracked on the contract.

        The cross-module subscribers (notifications wave-5) stamp every
        applied adjustment onto ``contract.metadata``: approved change
        orders append to ``change_order_ids`` / ``change_order_total`` and
        completed variation orders append to ``variation_ids`` /
        ``variation_total``. Both totals are stored as Decimal strings;
        anything missing or unparseable counts as 0.
        """
        md = contract.metadata_ if isinstance(contract.metadata_, dict) else {}

        def _safe_decimal(raw: Any) -> Decimal:
            try:
                return Decimal(str(raw or 0))
            except (InvalidOperation, ValueError, TypeError):
                return Decimal("0")

        count = len(md.get("change_order_ids") or []) + len(md.get("variation_ids") or [])
        net = _safe_decimal(md.get("change_order_total")) + _safe_decimal(md.get("variation_total"))
        return count, net

    async def contract_dashboard(self, contract_id: uuid.UUID) -> dict[str, Any]:
        contract = await self.get_contract(contract_id)
        paid = await self.claim_repo.paid_total(contract_id)
        retention = await self.claim_repo.outstanding_retention(contract_id)
        _claims, total_claims = await self.claim_repo.claims_for_contract(
            contract_id,
            offset=0,
            limit=1,
        )
        gainshare_estimate: Decimal | None = None
        if contract.contract_type == "gmp":
            cfg = await self.gainshare_repo.get_for_contract(contract_id)
            if cfg is not None and paid > DEC_ZERO:
                share = compute_gmp_gainshare(
                    paid,
                    cfg.target_cost,
                    cfg.gmp_cap,
                    cfg.savings_split_owner_pct,
                    cfg.savings_split_contractor_pct,
                )
                gainshare_estimate = share["savings"] - share["overrun"]
        outstanding = Decimal(str(contract.total_value or 0)) - paid
        change_orders_count, _change_orders_net = self._change_order_rollup(contract)
        return {
            "contract_id": contract_id,
            "total_value": Decimal(str(contract.total_value or 0)),
            "paid_to_date": paid,
            "retention_held": retention,
            "outstanding": outstanding if outstanding > DEC_ZERO else DEC_ZERO,
            "claims_count": total_claims,
            "change_orders_count": change_orders_count,
            "gainshare_estimate": gainshare_estimate,
            "status": contract.status,
        }

    # -- Final-account (close-out) readiness checklist --------------------

    async def _retention_position(
        self,
        contract: Contract,
        final_account: FinalAccount | None,
    ) -> tuple[Decimal, Decimal]:
        """Retention held vs released for the checklist.

        Prefers the final account's own figures as the authoritative close-out
        record; before a final account exists it falls back to the retention
        accrued on approved / certified / paid claims (``outstanding_retention``)
        less anything already logged in ``metadata['retention_releases']``.
        """
        if final_account is not None:
            return (
                Decimal(str(final_account.retention_held or 0)),
                Decimal(str(final_account.retention_released or 0)),
            )
        held = await self.claim_repo.outstanding_retention(contract.id)
        meta = contract.metadata_ if isinstance(contract.metadata_, dict) else {}
        releases = meta.get("retention_releases") or []
        released = sum(
            (Decimal(str(r.get("amount_released", 0) or 0)) for r in releases),
            DEC_ZERO,
        )
        return held, released

    async def final_account_checklist(self, contract_id: uuid.UUID) -> dict[str, Any]:
        """Assemble the final-account readiness checklist for a contract.

        Loads the contract's own stored rows - progress claims, extension-of-time
        claims, financial securities, retention figures and the final account -
        flattens them into a plain :class:`ClosureFacts` and defers to the pure
        evaluator. No new storage: every close-out condition is computed from
        data already persisted. Raises 404 when the contract does not exist.
        """
        contract = await self.get_contract(contract_id)

        # Progress claims: open = not yet paid and not rejected.
        _first, total_claims = await self.claim_repo.claims_for_contract(
            contract_id,
            offset=0,
            limit=1,
        )
        claims, _ = await self.claim_repo.claims_for_contract(
            contract_id,
            offset=0,
            limit=max(int(total_claims), 1),
        )
        open_claims = sum(1 for c in claims if c.status not in ("paid", "rejected"))

        # Extension-of-time claims: pending = draft / submitted / under_review.
        eots = await self.eot_repo.list_for_contract(contract_id)
        pending_eot = sum(1 for e in eots if e.status in ("draft", "submitted", "under_review"))

        # Financial securities: outstanding = required / received / active.
        securities = await self.security_repo.list_for_contract(contract_id)
        outstanding_security = sum(1 for s in securities if s.status in ("required", "received", "active"))

        final_account = await self.final_account_repo.get_for_contract(contract_id)
        retention_held, retention_released = await self._retention_position(contract, final_account)

        facts = ClosureFacts(
            contract_total_value=Decimal(str(contract.total_value or 0)),
            open_progress_claim_count=open_claims,
            total_progress_claim_count=int(total_claims),
            pending_eot_count=pending_eot,
            total_eot_count=len(eots),
            outstanding_security_count=outstanding_security,
            total_security_count=len(securities),
            retention_held=retention_held,
            retention_released=retention_released,
            final_account_present=final_account is not None,
            final_account_agreed=(final_account is not None and final_account.status in ("agreed", "closed")),
            final_account_signed_off=bool(final_account is not None and final_account.sign_off_date),
            final_account_value=(
                Decimal(str(final_account.final_contract_value or 0)) if final_account is not None else DEC_ZERO
            ),
        )
        result = evaluate_final_account_readiness(facts)
        return {
            "contract_id": contract_id,
            "ready": result.ready,
            "completion_percent": result.completion_percent,
            "passed_count": result.passed_count,
            "applicable_count": result.applicable_count,
            "total_count": result.total_count,
            "items": [
                {
                    "key": item.key,
                    "status": item.status,
                    "reason": item.reason,
                    "based_on": item.based_on,
                }
                for item in result.items
            ],
        }

    # ── AIA G702/G703 (US/CA/AU only) ────────────────────────────────────

    async def assert_contract_aia_eligible(self, contract: Contract) -> Any:
        """Raise 404 unless the contract's project is AIA-eligible.

        AIA G702/G703 is country-gated to US/CA/AU. A non-eligible project must
        behave as if the AIA endpoints do not exist, so we raise 404 (not 403)
        to avoid leaking that the feature exists for other tenants. Returns the
        loaded ``Project`` for callers that need its country/currency.
        """
        from app.modules.contracts.aia import is_aia_eligible  # noqa: PLC0415
        from app.modules.projects.models import Project  # noqa: PLC0415

        project = await self.session.get(Project, contract.project_id)
        eligible = project is not None and is_aia_eligible(
            getattr(project, "country_code", None),
            getattr(project, "address", None),
        )
        if not eligible:
            raise HTTPException(
                status_code=404,
                detail="AIA payment applications are only available for US/CA/AU projects",
            )
        return project

    async def build_aia_application(self, claim_id: uuid.UUID) -> dict[str, Any]:
        """Assemble the AIA G702 summary + G703 continuation for one claim.

        Reuses the existing SoV lines (``ContractLine``) and the claim's lines
        (``ProgressClaimLine``); does not recompute the claim FSM or retention
        accrual. Country-gated by the caller via
        :meth:`assert_contract_aia_eligible`. Single-currency by construction
        (the claim inherits the contract currency); no currency is ever blended.
        """
        from app.modules.contracts.aia import (  # noqa: PLC0415
            DEC_ZERO,
            build_g702_summary,
            build_g703,
        )

        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(
                status_code=404,
                detail=translate("errors.claim_not_found", locale=get_locale()),
            )
        contract = await self.get_contract(claim.contract_id)
        await self.assert_contract_aia_eligible(contract)

        contract_lines = await self.line_repo.list_for_contract(contract.id)
        claim_lines = await self.claim_line_repo.list_for_claim(claim_id)
        by_contract_line = {cl.contract_line_id: cl for cl in claim_lines}

        retainage_percent = Decimal(str(contract.retention_percent or 0))
        g703 = build_g703(
            contract_lines,
            by_contract_line,
            retainage_percent=retainage_percent,
        )

        # Previous certificates = prior recognised claim value on this contract
        # (everything billed before this claim), read from the existing
        # per-line prior aggregation so the G702 line 7 ties to the ledger.
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(
            contract.id,
            exclude_claim_id=claim_id,
        )
        previous_certificates_total = sum(prior_by_line.values(), DEC_ZERO)

        # Net change orders: prefer the auto-tracked metadata rollup
        # (change_order_total + variation_total, stamped by the approval
        # subscribers) and fall back to the manually-entered terms value only
        # for contracts that predate the rollup, i.e. neither rollup key is
        # present in metadata. Key PRESENCE decides, not value (audit m7): a
        # tracked rollup that legitimately nets to zero must not resurrect a
        # stale manual figure. Never add the two - a contract that mirrors
        # the rollup into terms would double-count.
        _co_count, meta_change_orders_net = self._change_order_rollup(contract)
        contract_md = contract.metadata_ if isinstance(contract.metadata_, dict) else {}
        rollup_tracked = "change_order_total" in contract_md or "variation_total" in contract_md
        change_orders_net = (
            meta_change_orders_net
            if rollup_tracked
            else Decimal(str((contract.terms or {}).get("change_orders_net", 0) or 0))
        )
        # Prefer the immutable stored baseline when available; fall back
        # to the subtraction reconstruction for contracts that were active
        # before the column existed.
        if contract.original_contract_value is not None:
            original_contract_sum = contract.original_contract_value
        else:
            original_contract_sum = Decimal(str(contract.total_value or 0)) - change_orders_net

        g702 = build_g702_summary(
            g703,
            original_contract_sum=original_contract_sum,
            change_orders_net=change_orders_net,
            previous_certificates_total=previous_certificates_total,
        )

        cert = (claim.metadata_ or {}).get("aia_certification", {}) or {}
        return {
            "claim_id": claim.id,
            "contract_id": contract.id,
            "project_id": contract.project_id,
            "application_number": claim.claim_number or "",
            "period_start": claim.period_start,
            "period_end": claim.period_end,
            "claim_date": claim.claim_date,
            "currency": claim.currency or contract.currency or "",
            "claim_status": claim.status,
            "retainage_percent": retainage_percent.quantize(Decimal("0.01")),
            "summary": g702,
            "lines": g703,
            "certification": {
                "architect_certified_at": cert.get("architect_certified_at"),
                "architect_certified_by": cert.get("architect_certified_by"),
                "owner_certified_at": cert.get("owner_certified_at"),
                "owner_certified_by": cert.get("owner_certified_by"),
                "certified_amount": cert.get("certified_amount"),
            },
        }

    # ── Helpers (shared by the depth entities) ───────────────────────────

    @staticmethod
    def _create_kwargs(data: Any) -> dict[str, Any]:
        """Build ORM kwargs from a create schema, mapping metadata -> metadata_."""
        payload = data.model_dump()
        if "metadata" in payload:
            payload["metadata_"] = payload.pop("metadata")
        return payload

    async def _apply_update(self, repo: Any, obj: Any, data: Any) -> Any:
        """Generic partial update with metadata merge; mirrors update_contract.

        Only fields explicitly set on ``data`` are touched. A provided
        ``metadata`` dict is deep-merged into the existing ``metadata_`` (never
        clobbered). None values are dropped so an omitted optional field is not
        written as NULL, matching the rest of the module's update endpoints.
        """
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(obj, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        fields = {k: v for k, v in fields.items() if v is not None or k == "metadata_"}
        if fields:
            await repo.update_fields(obj.id, **fields)
            await self.session.refresh(obj)
        return obj

    # ── Party / counterparty name resolution ─────────────────────────────

    @staticmethod
    def _contact_display_name(contact: Any) -> str | None:
        """Best display label for a contact row (company, then person, then legal)."""
        if contact is None:
            return None
        company = getattr(contact, "company_name", None)
        if company:
            return str(company)
        first = getattr(contact, "first_name", None) or ""
        last = getattr(contact, "last_name", None) or ""
        full = f"{first} {last}".strip()
        if full:
            return full
        legal = getattr(contact, "legal_name", None)
        return str(legal) if legal else None

    @staticmethod
    def _subcontractor_display_name(sub: Any) -> str | None:
        """Best display label for a subcontractor row (trade name, then legal name)."""
        if sub is None:
            return None
        label = getattr(sub, "trade_name", None) or getattr(sub, "legal_name", None) or ""
        return str(label) or None

    @staticmethod
    def _user_display_name(user: Any) -> str | None:
        """Best display label for a platform user (full name, then email)."""
        if user is None:
            return None
        label = getattr(user, "full_name", None) or getattr(user, "email", None) or ""
        return str(label) or None

    async def _load_contact_name(self, entity_id: uuid.UUID | None) -> str | None:
        if entity_id is None:
            return None
        try:
            from app.modules.contacts.models import Contact  # noqa: PLC0415

            contact = await self.session.get(Contact, entity_id)
        except Exception:
            logger.debug("contracts: contact name resolution failed for %s", entity_id)
            return None
        return self._contact_display_name(contact)

    async def _load_subcontractor_name(self, entity_id: uuid.UUID | None) -> str | None:
        if entity_id is None:
            return None
        try:
            from app.modules.subcontractors.models import Subcontractor  # noqa: PLC0415

            sub = await self.session.get(Subcontractor, entity_id)
        except Exception:
            logger.debug("contracts: subcontractor name resolution failed for %s", entity_id)
            return None
        return self._subcontractor_display_name(sub)

    async def _load_user_name(self, entity_id: uuid.UUID | None) -> str | None:
        if entity_id is None:
            return None
        try:
            from app.modules.users.models import User  # noqa: PLC0415

            user = await self.session.get(User, entity_id)
        except Exception:
            logger.debug("contracts: user name resolution failed for %s", entity_id)
            return None
        return self._user_display_name(user)

    async def resolve_counterparty_name(self, contract: Contract) -> str | None:
        """Resolve a contract counterparty's live display name.

        ``counterparty_id`` is a plain UUID that may reference a contact OR a
        subcontractor row, so both directories are tried (the declared
        ``counterparty_type`` decides which is tried first). Returns ``None``
        when nothing resolves, so the caller can fall back to its own label.
        """
        cid = getattr(contract, "counterparty_id", None)
        if cid is None:
            return None
        if getattr(contract, "counterparty_type", None) == "subcontractor":
            return await self._load_subcontractor_name(cid) or await self._load_contact_name(cid)
        return await self._load_contact_name(cid) or await self._load_subcontractor_name(cid)

    async def resolve_party_name(self, party: ContractParty) -> str | None:
        """Resolve a structured party's live display name from its linked entity.

        Dispatches on ``party_type`` (contact / subcontractor / user). External
        parties have no linked row and resolve to ``None`` (the UI falls back to
        the stored ``display_name``).
        """
        pid = getattr(party, "party_id", None)
        if pid is None:
            return None
        ptype = getattr(party, "party_type", None)
        if ptype == "contact":
            return await self._load_contact_name(pid)
        if ptype == "subcontractor":
            return await self._load_subcontractor_name(pid)
        if ptype == "user":
            return await self._load_user_name(pid)
        return None

    async def list_parties_with_names(
        self,
        contract_id: uuid.UUID,
    ) -> list[tuple[ContractParty, str | None]]:
        """List a contract's parties paired with their resolved live names."""
        parties = await self.party_repo.list_for_contract(contract_id)
        return [(p, await self.resolve_party_name(p)) for p in parties]

    async def counterparty_overview(self, contract: Contract) -> dict[str, Any]:
        """Return the contract counterparty plus its resolved display name."""
        return {
            "contract_id": str(contract.id),
            "counterparty_type": contract.counterparty_type,
            "counterparty_id": (str(contract.counterparty_id) if contract.counterparty_id else None),
            "resolved_name": await self.resolve_counterparty_name(contract),
        }

    # ── Parties (CRUD) ───────────────────────────────────────────────────

    async def create_party(self, data: Any) -> ContractParty:
        await self.get_contract(data.contract_id)
        obj = ContractParty(**self._create_kwargs(data))
        return await self.party_repo.create(obj)

    async def update_party(self, party_id: uuid.UUID, data: Any) -> ContractParty:
        obj = await self.party_repo.get_by_id(party_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Contract party not found")
        return await self._apply_update(self.party_repo, obj, data)

    async def delete_party(self, party_id: uuid.UUID) -> None:
        await self.party_repo.delete(party_id)

    # ── Securities (CRUD + coverage) ─────────────────────────────────────

    async def create_security(self, data: Any) -> ContractSecurity:
        await self.get_contract(data.contract_id)
        obj = ContractSecurity(**self._create_kwargs(data))
        return await self.security_repo.create(obj)

    async def update_security(self, security_id: uuid.UUID, data: Any) -> ContractSecurity:
        obj = await self.security_repo.get_by_id(security_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Contract security not found")
        return await self._apply_update(self.security_repo, obj, data)

    async def delete_security(self, security_id: uuid.UUID) -> None:
        await self.security_repo.delete(security_id)

    async def security_coverage(self, contract_id: uuid.UUID) -> dict[str, Any]:
        """Summarise the bonds / guarantees / insurance held on a contract."""
        contract = await self.get_contract(contract_id)
        securities = await self.security_repo.list_for_contract(contract_id)
        active = [s for s in securities if s.status == "active"]
        total_active = sum((Decimal(str(s.amount or 0)) for s in active), DEC_ZERO)
        by_status: dict[str, int] = {}
        for s in securities:
            by_status[s.status] = by_status.get(s.status, 0) + 1
        return {
            "contract_id": str(contract_id),
            "currency": contract.currency,
            "count": len(securities),
            "active_count": len(active),
            "total_active_amount": str(total_active),
            "by_status": by_status,
            "active_types": sorted({s.security_type for s in active}),
        }

    # ── Extension-of-time claims ─────────────────────────────────────────

    async def _get_eot_or_404(self, eot_id: uuid.UUID) -> EOTClaim:
        eot = await self.eot_repo.get_by_id(eot_id)
        if eot is None:
            raise HTTPException(status_code=404, detail="EOT claim not found")
        return eot

    async def create_eot_claim(self, data: Any) -> EOTClaim:
        """Create an extension-of-time claim (always starts in ``draft``)."""
        contract = await self.get_contract(data.contract_id)
        eot_number = data.eot_number or await self.eot_repo.next_eot_number(contract.id)
        eot = EOTClaim(
            contract_id=contract.id,
            eot_number=eot_number,
            cause_category=data.cause_category,
            description=data.description,
            days_claimed=int(data.days_claimed or 0),
            days_granted=0,
            claim_date=data.claim_date,
            status="draft",
            linked_delay_event_id=data.linked_delay_event_id,
            metadata_=data.metadata,
        )
        return await self.eot_repo.create(eot)

    async def update_eot_claim(self, eot_id: uuid.UUID, data: Any) -> EOTClaim:
        eot = await self._get_eot_or_404(eot_id)
        # Status / days_granted / decision fields are FSM-driven (submit /
        # decide / withdraw), never free-edited here, so EOTClaimUpdate omits
        # them entirely.
        return await self._apply_update(self.eot_repo, eot, data)

    async def delete_eot_claim(self, eot_id: uuid.UUID) -> None:
        await self.eot_repo.delete(eot_id)

    async def transition_eot_claim(
        self,
        eot_id: uuid.UUID,
        target_status: str,
        actor_id: str | None = None,
    ) -> EOTClaim:
        """Apply a non-decision EOT transition (submitted / under_review / withdrawn)."""
        eot = await self._get_eot_or_404(eot_id)
        try:
            assert_eot_transition(eot.status, target_status)
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if target_status in _EOT_DECISION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use the decide endpoint to record an EOT decision",
            )
        await self.eot_repo.update_fields(eot_id, status=target_status)
        await self.session.refresh(eot)
        if target_status == "submitted":
            event_bus.publish_detached(
                EOT_SUBMITTED,
                data={
                    "eot_id": str(eot.id),
                    "contract_id": str(eot.contract_id),
                    "eot_number": eot.eot_number,
                    "days_claimed": int(eot.days_claimed or 0),
                    "actor": actor_id,
                },
                source_module="contracts",
            )
        return eot

    async def decide_eot_claim(
        self,
        eot_id: uuid.UUID,
        decision: str,
        *,
        days_granted: int = 0,
        decision_date: str | None = None,
        revised_completion_date: str | None = None,
        actor_id: str | None = None,
    ) -> EOTClaim:
        """Record a final decision on an EOT claim.

        ``decision`` is one of granted / partially_granted / rejected. Granted
        days are clamped to ``[0, days_claimed]`` (rejected always grants zero)
        so a decision can never award more time than was claimed. Emits
        ``contracts.eot.decided``.
        """
        eot = await self._get_eot_or_404(eot_id)
        if decision not in _EOT_DECISION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid EOT decision: {decision!r}",
            )
        try:
            assert_eot_transition(eot.status, decision)
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        from datetime import UTC, datetime  # noqa: PLC0415

        granted = clamp_eot_days_granted(eot.days_claimed, days_granted, decision)
        fields: dict[str, Any] = {
            "status": decision,
            "days_granted": granted,
            "decision_date": decision_date or datetime.now(UTC).date().isoformat(),
        }
        if revised_completion_date is not None:
            fields["revised_completion_date"] = revised_completion_date
        await self.eot_repo.update_fields(eot_id, **fields)
        await self.session.refresh(eot)
        event_bus.publish_detached(
            EOT_DECIDED,
            data={
                "eot_id": str(eot.id),
                "contract_id": str(eot.contract_id),
                "eot_number": eot.eot_number,
                "status": decision,
                "days_claimed": int(eot.days_claimed or 0),
                "days_granted": granted,
                "revised_completion_date": eot.revised_completion_date,
                "actor": actor_id,
            },
            source_module="contracts",
        )
        return eot

    async def eot_summary(self, contract_id: uuid.UUID) -> dict[str, Any]:
        """Aggregate EOT exposure for a contract (days claimed / granted, dates)."""
        claims = await self.eot_repo.list_for_contract(contract_id)
        granted_states = ("granted", "partially_granted")
        total_claimed = sum(int(c.days_claimed or 0) for c in claims)
        total_granted = sum(int(c.days_granted or 0) for c in claims if c.status in granted_states)
        pending = [c for c in claims if c.status in ("draft", "submitted", "under_review")]
        decided = [c for c in claims if c.status in _EOT_DECISION_STATUSES]
        revised_dates = [c.revised_completion_date for c in claims if c.revised_completion_date]
        return {
            "contract_id": str(contract_id),
            "claims_count": len(claims),
            "pending_count": len(pending),
            "decided_count": len(decided),
            "total_days_claimed": total_claimed,
            "total_days_granted": total_granted,
            "latest_revised_completion_date": (max(revised_dates) if revised_dates else None),
        }

    # ── Documents register (CRUD) ────────────────────────────────────────

    async def create_document(self, data: Any) -> ContractDocument:
        await self.get_contract(data.contract_id)
        obj = ContractDocument(**self._create_kwargs(data))
        return await self.document_repo.create(obj)

    async def update_document(self, document_id: uuid.UUID, data: Any) -> ContractDocument:
        obj = await self.document_repo.get_by_id(document_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Contract document not found")
        return await self._apply_update(self.document_repo, obj, data)

    async def delete_document(self, document_id: uuid.UUID) -> None:
        await self.document_repo.delete(document_id)

    # ── Milestones (CRUD + schedule) ─────────────────────────────────────

    async def create_milestone(self, data: Any) -> ContractMilestone:
        await self.get_contract(data.contract_id)
        obj = ContractMilestone(**self._create_kwargs(data))
        return await self.milestone_repo.create(obj)

    async def update_milestone(self, milestone_id: uuid.UUID, data: Any) -> ContractMilestone:
        obj = await self.milestone_repo.get_by_id(milestone_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Contract milestone not found")
        return await self._apply_update(self.milestone_repo, obj, data)

    async def delete_milestone(self, milestone_id: uuid.UUID) -> None:
        await self.milestone_repo.delete(milestone_id)

    async def milestone_schedule(self, contract_id: uuid.UUID) -> dict[str, Any]:
        """Resolve each milestone's value and the total scheduled milestone value."""
        contract = await self.get_contract(contract_id)
        milestones = await self.milestone_repo.list_for_contract(contract_id)
        contract_value = Decimal(str(contract.total_value or 0))
        items: list[dict[str, Any]] = []
        total_value = DEC_ZERO
        for m in milestones:
            value = compute_milestone_value(m.value, m.percent_of_contract, contract_value)
            total_value += value
            items.append(
                {
                    "id": str(m.id),
                    "code": m.code,
                    "name": m.name,
                    "planned_date": m.planned_date,
                    "trigger": m.trigger,
                    "status": m.status,
                    "value": str(value),
                }
            )
        return {
            "contract_id": str(contract_id),
            "currency": contract.currency,
            "count": len(items),
            "scheduled_value": str(total_value),
            "milestones": items,
        }

    # ── Completeness validation (contracts rule set) ─────────────────────

    async def validate_contract_completeness(self, contract_id: uuid.UUID) -> dict[str, Any]:
        """Run the ``contracts`` rule set against a contract and return the report.

        Returns the report summary plus the grouped error / warning lists,
        mirroring the compliance-gate preview shape. The report is the same one
        the signing gate blocks on, built by the same method, so what this
        screen shows is what that button will do.
        """
        contract = await self.get_contract(contract_id)
        report = await self.run_contract_rules(contract)

        def _serialise(r: Any) -> dict[str, Any]:
            return {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value,
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }

        return {
            "contract_id": str(contract.id),
            "status": report.status.value,
            "score": report.score,
            "summary": report.summary(),
            "errors": [_serialise(r) for r in report.errors],
            "warnings": [_serialise(r) for r in report.warnings],
        }

    # ── Authored clause templates ────────────────────────────────────────

    async def _assert_code_free(self, code: str) -> None:
        """Refuse a template code that is already taken.

        This is the only place either half of the namespace is checked, and
        every write path that mints a new lineage calls it. It has to be a
        function rather than a database constraint because half the namespace
        is not in the database: the built-in codes are module constants, so no
        unique index can see them. That also means two concurrent creates can
        both pass it. The pair (code, version) *is* a real constraint, so the
        race loses a row to an IntegrityError rather than producing two
        lineages under one code.
        """
        if is_builtin_template_code(code):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "template_code_is_builtin",
                    "code": code,
                    "message": (
                        "That code names a built-in standard form. Fork it to a new code instead of shadowing it."
                    ),
                },
            )
        if await self.template_repo.max_version(code) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "template_code_taken", "code": code},
            )

    async def _require_draft(self, code: str, version: int) -> ContractTemplate:
        """Load one version and refuse to mutate it unless it is a draft.

        A published version is what some contract says it was drawn from, so
        editing it in place would silently restate a signed agreement. The
        caller is told to open the next version instead, which is a real
        action rather than advice.
        """
        template = await self.template_repo.get_version(code, version)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "template_version_not_found", "code": code, "version": version},
            )
        if template.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "template_version_frozen",
                    "code": code,
                    "version": version,
                    "status": template.status,
                    "message": (
                        "A published or archived version cannot be edited. Open the next version from it and edit that."
                    ),
                },
            )
        return template

    async def list_templates(self) -> list[dict[str, Any]]:
        """Every template a user may pick from, built-in and authored."""
        return await self.template_repo.list_all()

    async def get_template(self, code: str, version: int | None = None) -> dict[str, Any]:
        """Resolve one template, whichever half of the namespace it lives in.

        ``version`` names an exact authored version. Without it the caller gets
        the current version, which is the latest published one, or the latest
        draft when the lineage has never been published.
        """
        if version is None and is_builtin_template_code(code):
            builtin = get_contract_template(code)
            return {
                "code": code,
                "name": builtin["name"],
                "family": builtin["family"],
                "description": "",
                "retention_release_event": builtin["retention_release_event"],
                "source": "builtin",
                "editable": False,
                "version": 0,
                "status": "published",
                "clauses": [
                    {
                        "number": number,
                        "title": title,
                        "body": "",
                        "sort_order": index,
                        "risk_level": "none",
                        "risk_note": "",
                        "is_optional": False,
                    }
                    for index, (number, title) in enumerate(builtin["key_clauses"].items())
                ],
                "clause_count": len(builtin["key_clauses"]),
            }

        template = (
            await self.template_repo.get_version(code, version)
            if version is not None
            else await self.template_repo.current_version(code)
        )
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "template_not_found", "code": code, "version": version},
            )
        clauses = await self.template_clause_repo.list_for_template(template.id)
        return _template_to_dict(template, clauses)

    async def list_template_versions(self, code: str) -> list[dict[str, Any]]:
        """Every version under ``code``, oldest first.

        A built-in has no versions and is not an error here: it answers with the
        single frozen entry the catalogue holds, so a caller can render one
        version history screen for both halves.
        """
        rows = await self.template_repo.list_versions(code)
        if not rows and is_builtin_template_code(code):
            builtin = get_contract_template(code)
            # Filled out rather than minimal: a history screen that renders both
            # halves would otherwise show a built-in with a blank family and no
            # clause count, which reads as missing data rather than as a
            # constant.
            return [
                {
                    "code": code,
                    "version": 0,
                    "status": "published",
                    "name": builtin["name"],
                    "family": builtin["family"],
                    "description": "",
                    "retention_release_event": builtin["retention_release_event"],
                    "clause_count": builtin["clause_count"],
                    "source": "builtin",
                    "editable": False,
                    "published_at": None,
                    "published_by": None,
                }
            ]
        return [_template_to_dict(row) for row in rows]

    async def create_template(
        self,
        data: Any,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Author a new template as version 1, in draft."""
        code = data.code.strip()
        await self._assert_code_free(code)

        template = ContractTemplate(
            code=code,
            version=1,
            # Version 1 anchors its own lineage, so a template is addressable
            # by lineage from the moment it exists rather than from its second
            # version. The id is minted here instead of leaning on the column
            # default, because lineage_id has to equal it.
            id=(new_id := uuid.uuid4()),
            lineage_id=new_id,
            name=data.name,
            family=(data.family or "").strip(),
            description=data.description or "",
            retention_release_event=data.retention_release_event,
            status="draft",
            derived_from_builtin=None,
            created_by=user_id,
        )
        await self.template_repo.create(template)
        clauses = await self._write_clauses(template.id, getattr(data, "clauses", None) or [])
        return _template_to_dict(template, clauses)

    async def fork_builtin_template(
        self,
        builtin_code: str,
        new_code: str,
        user_id: str | None = None,
        new_name: str | None = None,
    ) -> dict[str, Any]:
        """Copy a built-in standard form into an authored, editable draft.

        This is how a built-in gets edited: not in place, since it is a
        constant, but by taking its clause map as the starting point for the
        tenant's own paper. The built-in clause map carries numbers and titles
        and no body text, so the fork starts with the headings and an empty
        body for each, which is an honest statement of what we shipped rather
        than invented contract language.
        """
        if not is_builtin_template_code(builtin_code):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "builtin_template_not_found", "code": builtin_code},
            )
        code = new_code.strip()
        await self._assert_code_free(code)

        builtin = get_contract_template(builtin_code)
        template = ContractTemplate(
            code=code,
            version=1,
            id=(new_id := uuid.uuid4()),
            lineage_id=new_id,
            name=new_name or f"{builtin['name']} (adapted)",
            family=builtin["family"],
            description="",
            retention_release_event=builtin["retention_release_event"],
            status="draft",
            derived_from_builtin=builtin_code,
            created_by=user_id,
        )
        await self.template_repo.create(template)
        clauses = await self._write_clauses(
            template.id,
            [
                {"number": number, "title": title, "sort_order": index}
                for index, (number, title) in enumerate(builtin["key_clauses"].items())
            ],
        )
        return _template_to_dict(template, clauses)

    async def update_template(
        self,
        code: str,
        version: int,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Edit the header of a draft version. Never its code or its number."""
        template = await self._require_draft(code, version)
        allowed = {"name", "family", "description", "retention_release_event", "metadata_"}
        writes = {key: value for key, value in fields.items() if key in allowed and value is not None}
        if writes:
            await self.template_repo.update_fields(template.id, **writes)
        clauses = await self.template_clause_repo.list_for_template(template.id)
        refreshed = await self.template_repo.get_version(code, version)
        return _template_to_dict(refreshed or template, clauses)

    async def replace_template_clauses(
        self,
        code: str,
        version: int,
        clauses: list[Any],
    ) -> dict[str, Any]:
        """Replace the whole clause set of a draft version.

        Whole-set replacement rather than per-clause edits because clause order
        and numbering are one document, not a bag of rows: renumbering 14.3 to
        14.4 while 14.4 exists is a legal edit of the document and an illegal
        sequence of row updates.
        """
        template = await self._require_draft(code, version)
        await self.template_clause_repo.delete_for_template(template.id)
        written = await self._write_clauses(template.id, clauses)
        return _template_to_dict(template, written)

    async def _write_clauses(self, template_id: uuid.UUID, clauses: list[Any]) -> list[ContractTemplateClause]:
        """Insert a clause set for one template version, rejecting a repeated number."""
        seen: set[str] = set()
        rows: list[ContractTemplateClause] = []
        for index, clause in enumerate(clauses):
            data = clause if isinstance(clause, dict) else clause.model_dump()
            number = str(data.get("number") or "").strip()
            if not number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "clause_number_required", "position": index},
                )
            if number in seen:
                # The unique constraint would catch this too, but as an
                # IntegrityError from the flush, naming a constraint rather
                # than the clause the user typed twice.
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "duplicate_clause_number", "number": number},
                )
            seen.add(number)
            risk = str(data.get("risk_level") or "none")
            if risk not in CLAUSE_RISK_LEVELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "unknown_risk_level",
                        "number": number,
                        "risk_level": risk,
                        "allowed": sorted(CLAUSE_RISK_LEVELS),
                    },
                )
            row = ContractTemplateClause(
                template_id=template_id,
                number=number,
                title=str(data.get("title") or ""),
                body=str(data.get("body") or ""),
                sort_order=int(data.get("sort_order") if data.get("sort_order") is not None else index),
                risk_level=risk,
                risk_note=str(data.get("risk_note") or ""),
                is_optional=bool(data.get("is_optional") or False),
            )
            self.session.add(row)
            rows.append(row)
        await self.session.flush()
        rows.sort(key=lambda row: (row.sort_order, row.number))
        return rows

    async def publish_template(
        self,
        code: str,
        version: int,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Freeze a draft version so contracts can name it.

        An empty template is not publishable. A template with no clauses would
        let a contract record that it was drawn from a document that says
        nothing, which is worse than having no template link at all.
        """
        from datetime import UTC, datetime  # noqa: PLC0415

        template = await self._require_draft(code, version)
        clauses = await self.template_clause_repo.list_for_template(template.id)
        if not clauses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "template_has_no_clauses",
                    "code": code,
                    "version": version,
                },
            )
        await self.template_repo.update_fields(
            template.id,
            status="published",
            published_at=datetime.now(UTC).isoformat(),
            published_by=user_id,
        )
        refreshed = await self.template_repo.get_version(code, version)
        return _template_to_dict(refreshed or template, clauses)

    async def open_next_template_version(
        self,
        code: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Start version N+1 as a draft, copying the current version's clauses.

        Clauses are copied by value. Sharing rows between versions would make
        an edit to the new draft silently rewrite what the published version
        says, which is the exact failure versioning exists to prevent.
        """
        versions = await self.template_repo.list_versions(code)
        if not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "template_not_found", "code": code},
            )
        # Ask the whole lineage, not the current version. ``current_version``
        # answers with the latest *published* row, so once v2 is open as a
        # draft it still returns v1, and a guard reading it would never fire:
        # a second call would branch v3 off v1 and leave two open drafts under
        # one code, which makes "the next version" meaningless.
        open_draft = next((row for row in versions if row.status == "draft"), None)
        if open_draft is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "template_draft_already_open",
                    "code": code,
                    "version": open_draft.version,
                    "message": "That template already has an open draft. Edit it instead.",
                },
            )

        # Branch from the published version when there is one. When every
        # version has been archived there is nothing current, and the newest
        # row is the only sensible starting point.
        source = await self.template_repo.current_version(code) or max(versions, key=lambda row: row.version)
        next_version = await self.template_repo.max_version(code) + 1
        draft = ContractTemplate(
            code=code,
            version=next_version,
            lineage_id=source.lineage_id,
            name=source.name,
            family=source.family,
            description=source.description,
            retention_release_event=source.retention_release_event,
            status="draft",
            derived_from_builtin=source.derived_from_builtin,
            created_by=user_id,
        )
        await self.template_repo.create(draft)
        source_clauses = await self.template_clause_repo.list_for_template(source.id)
        clauses = await self._write_clauses(
            draft.id,
            [
                {
                    "number": clause.number,
                    "title": clause.title,
                    "body": clause.body,
                    "sort_order": clause.sort_order,
                    "risk_level": clause.risk_level,
                    "risk_note": clause.risk_note,
                    "is_optional": clause.is_optional,
                }
                for clause in source_clauses
            ],
        )
        return _template_to_dict(draft, clauses)

    async def archive_template_version(self, code: str, version: int) -> dict[str, Any]:
        """Retire one version so it stops being offered.

        Archiving does not delete it. A contract drawn from version 2 keeps
        naming version 2 after it is retired, and the record of what that
        version said has to survive for the contract to mean anything.
        """
        template = await self.template_repo.get_version(code, version)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "template_version_not_found", "code": code, "version": version},
            )
        await self.template_repo.update_fields(template.id, status="archived")
        refreshed = await self.template_repo.get_version(code, version)
        clauses = await self.template_clause_repo.list_for_template(template.id)
        return _template_to_dict(refreshed or template, clauses)

    async def resolve_template_for_contract(self, code: str | None) -> tuple[str | None, int | None]:
        """Turn a template code on a contract create into the pair we store.

        Returns ``(code, version)`` or ``(None, None)``. The pair is
        both-or-neither on purpose: a code stored without a version would mean
        "whatever is current at read time", so publishing version 3 would
        change what an already-signed contract claims to be drawn from. A
        built-in resolves to version 0, which reads as "not a versioned
        template" and keeps the pair populated.
        """
        if not code:
            return None, None
        if is_builtin_template_code(code):
            return code, 0
        current = await self.template_repo.current_version(code)
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "template_not_found", "code": code},
            )
        if current.status != "published":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "template_not_published",
                    "code": code,
                    "version": current.version,
                    "message": "A contract can only be drawn from a published template version.",
                },
            )
        return current.code, current.version


__all__ = [
    "BOQ_POSITION_META_KEY",
    "CLAUSE_RISK_LEVELS",
    "TEMPLATE_STATUSES",
    "ContractsService",
    "InvalidTransitionError",
    "NTECapExceededError",
    "_REQUIRED_TERM_FIELDS",
    "allowed_claim_transitions",
    "allowed_contract_transitions",
    "allowed_eot_transitions",
    "allowed_final_account_transitions",
    "apply_change_order_to_contract_pure",
    "assert_claim_transition",
    "assert_contract_transition",
    "assert_eot_transition",
    "assert_final_account_transition",
    "boq_position_id_for_line",
    "clamp_eot_days_granted",
    "compute_contract_total",
    "compute_gmp_gainshare",
    "compute_ld_amount",
    "compute_line_total",
    "compute_milestone_value",
    "compute_progress_claim_line",
    "compute_progress_claim_total",
    "generate_cost_plus_claim",
    "generate_lump_sum_claim",
    "generate_tm_claim",
    "generate_unit_price_claim",
    "is_builtin_template_code",
    "validate_contract_terms",
]


def apply_change_order_to_contract_pure(
    contract_total_value: Decimal,
    co_amount: Decimal,
) -> Decimal:
    """Pure helper: new contract total after a change order.

    Provided as a stand-alone function so tests / external integrations can
    project deltas without instantiating the full DB-backed service.
    """
    return Decimal(str(contract_total_value or 0)) + Decimal(str(co_amount or 0))


# ── Schedule of Values (SOV) per-line status ──────────────────────────────


def compute_sov_status(
    lines: list[Any],
    claim_lines: list[Any],
    *,
    retention_percent: Decimal | float | int = Decimal("0"),
) -> dict[str, Any]:
    """Pure: per-contract-line SOV status: scheduled vs billed vs earned vs paid.

    Walks every contract line, sums all `period_completed_value` and
    `cumulative_completed_value` from claim_lines pointing at it, and
    returns a dict ``{line_id_str: {scheduled, billed, earned, retained,
    net_paid, percent_complete}}`` plus a top-level ``totals`` block.

    Note: "earned" = cumulative_completed_value across all claims (all
    statuses except rejected). "billed" = sum across submitted/approved
    claims. "paid" = sum across paid claims. This deliberately splits the
    two because in many contracts the certified-but-unpaid amount matters.

    Caller groups claim_lines by claim_status (one list per status) via the
    ``status`` attribute on the parent claim. To keep this fn pure we
    expect claim_lines to carry a ``_claim_status`` attribute set by the
    service-level call site.
    """
    pct = Decimal(str(retention_percent or 0))
    by_line: dict[str, dict[str, Decimal]] = {}
    for ln in lines:
        line_id = str(getattr(ln, "id", "") or "")
        if not line_id:
            continue
        qty = Decimal(str(getattr(ln, "quantity", 0) or 0))
        rate = Decimal(str(getattr(ln, "unit_rate", 0) or 0))
        by_line[line_id] = {
            "scheduled": qty * rate,
            "billed": DEC_ZERO,
            "earned": DEC_ZERO,
            "paid": DEC_ZERO,
        }

    for cl in claim_lines:
        lid = str(getattr(cl, "contract_line_id", "") or "")
        if lid not in by_line:
            continue
        value = Decimal(str(getattr(cl, "period_completed_value", 0) or 0))
        claim_status = (getattr(cl, "_claim_status", "") or "").lower()
        # Earned = anything that's at least submitted (i.e. recognised
        # as work-in-place by either party).
        if claim_status in (
            "submitted",
            "approved",
            "certified",
            "paid",
        ):
            by_line[lid]["earned"] += value
        if claim_status in ("approved", "certified", "paid"):
            by_line[lid]["billed"] += value
        if claim_status == "paid":
            by_line[lid]["paid"] += value

    rows: dict[str, dict[str, Any]] = {}
    totals: dict[str, Decimal] = {
        "scheduled": DEC_ZERO,
        "billed": DEC_ZERO,
        "earned": DEC_ZERO,
        "paid": DEC_ZERO,
        "retained": DEC_ZERO,
    }
    for lid, row in by_line.items():
        scheduled = row["scheduled"]
        earned = row["earned"]
        billed = row["billed"]
        paid = row["paid"]
        retained = (billed * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
        net_paid = paid - (paid * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
        percent_complete = float((earned / scheduled) * Decimal("100")) if scheduled > DEC_ZERO else 0.0
        rows[lid] = {
            "scheduled": scheduled,
            "billed": billed,
            "earned": earned,
            "paid": paid,
            "retained": retained,
            "net_paid": net_paid,
            "percent_complete": round(percent_complete, 4),
        }
        totals["scheduled"] += scheduled
        totals["earned"] += earned
        totals["billed"] += billed
        totals["paid"] += paid
        totals["retained"] += retained

    grand_pct = (
        float((totals["earned"] / totals["scheduled"]) * Decimal("100")) if totals["scheduled"] > DEC_ZERO else 0.0
    )
    return {
        "by_line": rows,
        "totals": {**totals, "percent_complete": round(grand_pct, 4)},
    }


# ── Retention release (tiered) ────────────────────────────────────────────


def plan_retention_release(
    total_retention_held: Decimal | float | int,
    event: str,
    schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure: compute a tiered retention release payload for an event.

    Standard tiers (used when ``schedule`` is None):
        - ``substantial_completion``: release 50%
        - ``punch_list_complete``: release the remainder (50% of the
          original held, applied to what's still being held)
        - ``defects_liability_end``: release 100% of remaining

    Custom schedule:
        ``{"substantial_completion": 50, "punch_list_complete": 30,
        "defects_liability_end": 20}`` - values are percentages of
        the *original* retention to release at each event.

    Returns ``{event, percent_released, amount_released, remaining}`` -
    callers persist this onto the contract / final account.
    """
    held = Decimal(str(total_retention_held or 0))
    if held <= DEC_ZERO:
        return {
            "event": event,
            "percent_released": DEC_ZERO,
            "amount_released": DEC_ZERO,
            "remaining": DEC_ZERO,
        }
    plan = schedule or {
        "substantial_completion": Decimal("50"),
        "punch_list_complete": Decimal("50"),
        "defects_liability_end": Decimal("100"),
    }
    pct = Decimal(str(plan.get(event, 0)))
    if pct < DEC_ZERO:
        pct = DEC_ZERO
    if pct > DEC_HUNDRED:
        pct = DEC_HUNDRED
    amount = (held * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    remaining = (held - amount).quantize(Decimal("0.0001"))
    if remaining < DEC_ZERO:
        remaining = DEC_ZERO
    return {
        "event": event,
        "percent_released": pct,
        "amount_released": amount,
        "remaining": remaining,
    }


# ── Lien waivers ──────────────────────────────────────────────────────────

LIEN_WAIVER_TYPES = (
    "conditional_partial",
    "unconditional_partial",
    "conditional_final",
    "unconditional_final",
)


def validate_lien_waiver_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Pure: validate a lien-waiver attachment payload.

    Required keys: ``waiver_type``, ``through_date``, ``amount``,
    ``signed_by``. Optional: ``jurisdiction``, ``document_url``, ``notes``.
    """
    errors: list[str] = []
    wt = payload.get("waiver_type")
    if wt not in LIEN_WAIVER_TYPES:
        errors.append(f"waiver_type must be one of {LIEN_WAIVER_TYPES}")
    if not payload.get("through_date"):
        errors.append("through_date is required (ISO date)")
    amt = payload.get("amount")
    if amt is None:
        errors.append("amount is required")
    else:
        try:
            if Decimal(str(amt)) < 0:
                errors.append("amount must be non-negative")
        except (ValueError, ArithmeticError):
            errors.append("amount must be numeric")
    if not payload.get("signed_by"):
        errors.append("signed_by is required")
    return len(errors) == 0, errors


# ── Contract clause templates (FIDIC / JCT / AIA) ────────────────────────


CONTRACT_CLAUSE_TEMPLATES: dict[str, dict[str, Any]] = {
    "fidic_red_1999": {
        "name": "FIDIC Red Book (1999) - Conditions of Contract for Construction",
        "family": "fidic",
        "key_clauses": {
            "14": "Contract Price and Payment",
            "14.3": "Application for Interim Payment Certificates",
            "14.6": "Issue of Interim Payment Certificate",
            "14.7": "Payment",
            "14.10": "Statement at Completion",
            "8.7": "Delay Damages",
            "11": "Defects Liability",
            "13": "Variations and Adjustments",
            "20": "Claims, Disputes and Arbitration",
        },
        "retention_release_event": "performance_certificate",
    },
    "fidic_yellow_1999": {
        "name": "FIDIC Yellow Book (1999) - Plant and Design-Build",
        "family": "fidic",
        "key_clauses": {
            "14": "Contract Price and Payment",
            "14.3": "Application for Interim Payment Certificates",
            "8.7": "Delay Damages",
            "11": "Tests on Completion / Defects Liability",
            "13": "Variations",
            "20": "Claims, Disputes",
        },
        "retention_release_event": "performance_certificate",
    },
    "fidic_silver_1999": {
        "name": "FIDIC Silver Book (1999) - EPC / Turnkey",
        "family": "fidic",
        "key_clauses": {
            "14": "Contract Price and Payment",
            "8.7": "Delay Damages",
            "11": "Defects Liability",
            "13": "Variations",
            "20": "Claims, Disputes",
        },
        "retention_release_event": "performance_certificate",
    },
    "jct_standard_2016": {
        "name": "JCT Standard Building Contract 2016",
        "family": "jct",
        "key_clauses": {
            "4": "Payment",
            "4.9": "Interim Payments",
            "4.15": "Final Certificate",
            "2.32": "Liquidated Damages",
            "5": "Variations",
            "6": "Injury, Damage and Insurance",
            "8": "Termination",
            "9": "Settlement of Disputes",
        },
        "retention_release_event": "practical_completion",
    },
    "jct_design_build_2016": {
        "name": "JCT Design and Build Contract 2016",
        "family": "jct",
        "key_clauses": {
            "4": "Payment",
            "2.29": "Liquidated Damages",
            "5": "Changes",
            "9": "Settlement of Disputes",
        },
        "retention_release_event": "practical_completion",
    },
    "jct_minor_works_2016": {
        "name": "JCT Minor Works Building Contract 2016",
        "family": "jct",
        "key_clauses": {
            "4": "Payment",
            "2.8": "Liquidated Damages",
            "3.6": "Variations",
        },
        "retention_release_event": "practical_completion",
    },
    "nec4_ecc_option_a": {
        "name": "NEC4 Engineering and Construction Contract - Option A (Priced)",
        "family": "nec",
        "key_clauses": {
            "5": "Payment",
            "X7": "Delay Damages",
            "60": "Compensation Events",
            "63": "Assessing Compensation Events",
        },
        "retention_release_event": "completion",
    },
    "nec4_ecc_option_c": {
        "name": "NEC4 ECC - Option C (Target Contract)",
        "family": "nec",
        "key_clauses": {
            "5": "Payment",
            "53": "Pain / Gain Share",
            "60": "Compensation Events",
        },
        "retention_release_event": "completion",
    },
    "aia_a201_2017": {
        "name": "AIA A201-2017 - General Conditions",
        "family": "aia",
        "key_clauses": {
            "9.3": "Applications for Payment",
            "9.5": "Decisions to Withhold Certification",
            "9.7": "Failure of Payment",
            "9.10": "Final Completion and Final Payment",
            "8.3": "Delays / Liquidated Damages",
            "7": "Changes in the Work",
            "15": "Claims and Disputes",
        },
        "retention_release_event": "substantial_completion",
    },
    "aia_a102_2017": {
        "name": "AIA A102-2017 - Owner & Contractor (Cost-Plus, GMP)",
        "family": "aia",
        "key_clauses": {
            "5": "Compensation",
            "5.2": "GMP",
            "6": "Schedule",
            "7": "Owner's Responsibilities",
        },
        "retention_release_event": "substantial_completion",
    },
    "consensusdocs_200": {
        "name": "ConsensusDocs 200 - Standard Owner / Constructor (Lump Sum)",
        "family": "consensusdocs",
        "key_clauses": {
            "9": "Payment",
            "8": "Schedule / Delay",
            "6": "Changes",
            "12": "Dispute Resolution",
        },
        "retention_release_event": "substantial_completion",
    },
}


def list_contract_templates() -> list[dict[str, Any]]:
    """Pure: list every clause template available for selection."""
    return [
        {
            "code": code,
            **{k: v for k, v in body.items() if k != "key_clauses"},
            "clause_count": len(body["key_clauses"]),
        }
        for code, body in CONTRACT_CLAUSE_TEMPLATES.items()
    ]


def get_contract_template(template_code: str) -> dict[str, Any]:
    """Pure: return one template body. Raises ``KeyError`` if unknown."""
    if template_code not in CONTRACT_CLAUSE_TEMPLATES:
        raise KeyError(f"Unknown contract clause template: {template_code}")
    body = CONTRACT_CLAUSE_TEMPLATES[template_code]
    return {"code": template_code, **body}


# ── Authored clause templates ────────────────────────────────────────────
#
# The built-in catalogue above is a constant nobody can edit. What follows is
# the authoring side: a tenant's own paper, versioned, with the rule that a
# published version is frozen. The two halves meet in exactly one place,
# ``ContractTemplateRepository.list_all``; see its docstring for why the
# built-ins are not rows.

# ``TEMPLATE_STATUSES`` and ``CLAUSE_RISK_LEVELS`` are declared in ``models``
# next to the columns whose domain they are, and re-exported here because this
# is where callers of the service look for them.


def is_builtin_template_code(code: str) -> bool:
    """Whether ``code`` names one of the built-in standard forms."""
    return code in CONTRACT_CLAUSE_TEMPLATES


def _template_to_dict(
    template: ContractTemplate,
    clauses: list[ContractTemplateClause] | None = None,
) -> dict[str, Any]:
    """Serialise one authored version, with its clauses when they were loaded."""
    body: dict[str, Any] = {
        "id": str(template.id),
        "code": template.code,
        "version": template.version,
        "lineage_id": str(template.lineage_id),
        "name": template.name,
        "family": template.family,
        "description": template.description,
        "retention_release_event": template.retention_release_event,
        "status": template.status,
        "published_at": template.published_at,
        "published_by": template.published_by,
        "derived_from_builtin": template.derived_from_builtin,
        "source": "authored",
        "editable": template.status == "draft",
        "metadata": dict(template.metadata_ or {}),
    }
    if clauses is not None:
        body["clauses"] = [
            {
                "id": str(clause.id),
                "number": clause.number,
                "title": clause.title,
                "body": clause.body,
                "sort_order": clause.sort_order,
                "risk_level": clause.risk_level,
                "risk_note": clause.risk_note,
                "is_optional": clause.is_optional,
            }
            for clause in clauses
        ]
        body["clause_count"] = len(clauses)
    return body
