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
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace
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
from app.modules.contracts.claim_context import collect_claim_context
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
    RetentionRelease,
    RetentionSchedule,
)
from app.modules.contracts.periods import claim_dates_for_write, claim_order_key, claims_before
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
    RetentionReleaseRepository,
    RetentionScheduleRepository,
)
from app.modules.contracts.retention import (
    CANONICAL_RELEASE_EVENTS,
    CONTRACT_RATE_SOURCE,
    OTHER_RELEASE_EVENTS,
    ClaimRetention,
    RetentionPolicy,
    canonical_release_event,
    claim_retention,
    compute_retention,
    flat_policy,
    plan_release,
    policy_from_rule,
    release_spec,
    step_down_release,
)
from app.modules.contracts.retention import percent_complete as retention_percent_complete

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

DEC_ZERO = Decimal("0")
DEC_HUNDRED = Decimal("100")

#: The parts of a retention policy that decide money. They stop being
#: editable the moment a claim leaves draft, because from then on the amount
#: the contract is holding was worked out under the rule as it stood. What is
#: not here, the statute it cites and the notes beside it, decides nothing and
#: is editable for the life of the contract.
_ACCRUAL_POLICY_FIELDS = (
    "tiers",
    "tier_mode",
    "stored_materials_rate",
    "cap_percent_of_contract_sum",
    "effective_date",
)

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

# Certification is the point the money leaves: it stamps the certifier onto
# the claim and publishes ``contracts.claim.certified``, which is what raises
# the AR invoice and moves the dashboards. Rejecting a certified claim used to
# be allowed and reversed none of that - the invoice stayed, the claim went
# back to draft, its lines were rewritten, and every later claim's line 7 was
# built on figures that no longer existed anywhere. Undoing it properly means
# reversing the money, which is a credit note, not a status change, so the
# transition is gone and :meth:`ContractsService.transition_claim` says so.
_CLAIM_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted", "rejected"}),
    "submitted": frozenset({"approved", "rejected"}),
    "approved": frozenset({"certified", "rejected"}),
    "certified": frozenset({"paid"}),
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

#: Key under which a claim's ``metadata_`` keeps the lines whose percent to
#: date came in below what earlier claims billed. Written by the generators,
#: replaced on every run, read by ``pay_application.percent_regressed``.
PERCENT_REGRESSED_META_KEY = "percent_regressed"

#: The money on a final account. A request that leaves one out has not said
#: it is zero; see ContractsService.final_account_figures.
FINAL_ACCOUNT_MONEY_FIELDS = (
    "final_contract_value",
    "total_paid",
    "retention_held",
    "retention_released",
    "final_balance",
)

#: Basis of G702 line 7 when it is rebuilt from the prior claims' stored gross
#: and retention rather than read from a certificate snapshot.
PREVIOUS_CERTIFICATES_RECONSTRUCTED = "reconstructed"
#: Basis of G702 line 7 when it is the previous claim's certified line 6
#: (its snapshot of lines 4 and 5), which is what the form asks for.
PREVIOUS_CERTIFICATES_SNAPSHOT = "snapshot"

#: Contract types billed without a schedule of values. Their claims keep the
#: flat retention their generator works out; the engine needs SoV lines to
#: measure percent complete on.
FLAT_RETENTION_CONTRACT_TYPES = frozenset({"cost_plus", "tm"})

#: Claim statuses whose retention counts as held by the owner, and whose
#: billed releases count as paid back: the statuses outstanding_retention reads.
RETENTION_CERTIFIED_STATUSES = frozenset({"approved", "certified", "paid"})

#: What a RetentionRelease row can be booked against.
RELEASE_ROW_EVENTS = frozenset({*CANONICAL_RELEASE_EVENTS, *OTHER_RELEASE_EVENTS})

#: Bonds whose surety has to consent before retention is paid back.
RETAINAGE_BOND_TYPES = ("performance_bond", "payment_bond")

#: Where the release rule a preview used came from.
RELEASE_RULE_FROM_SCHEDULE = "retention_schedule"
RELEASE_RULE_FROM_PACK = "regional_pack"
RELEASE_RULE_FROM_REQUEST = "request"
RELEASE_RULE_DEFAULT = "default"

#: The release rule when neither the contract nor a national pack gives one:
#: half at substantial completion, the rest at final completion or at the end
#: of the defects period, whichever the contract reaches. Percentages are of
#: the retention held when the event happens. Reported as ``default`` so it
#: is never read as any country's law.
DEFAULT_RELEASE_RULE: dict[str, Any] = {
    "events": [
        {"event": "substantial_completion", "release_percent_of_held": "50"},
        {"event": "final_completion", "release_percent_of_held": "100"},
        {"event": "defects_period_end", "release_percent_of_held": "100"},
    ],
}


def _release_share_outside_schedule(released: Decimal, *, schedule_pool: Decimal, outside_pool: Decimal) -> Decimal:
    """The part of the releases billed to date that comes off retention held outside the schedule.

    Pro rata to what each pool has accrued: ``schedule_pool`` is the retention
    accrued on schedule lines to date, ``outside_pool`` the retention earlier
    claims held on money no schedule line carries. Rounded to the cent and
    never more than ``outside_pool``, so a release beyond everything held
    lands on the schedule's side, where ``retention_release_within_held``
    reports it.
    """
    if released <= DEC_ZERO or outside_pool <= DEC_ZERO:
        return DEC_ZERO
    pool = max(schedule_pool, DEC_ZERO) + outside_pool
    share = (released * outside_pool / pool).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return min(share, outside_pool)


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
    prior_value: Decimal | float | int = DEC_ZERO,
) -> dict[str, Decimal]:
    """Pure: derive one claim line's figures from a SoV line + observed pct.

    ``observed_pct`` is percent complete TO DATE, which is what a progress
    observation and a completion entry both record. The claim bills the
    difference: ``cumulative = line value × pct / 100`` and ``period =
    cumulative - prior_value``, where ``prior_value`` is what earlier claims
    already billed on the line (G703 column D). Storing ``line value × pct``
    as the period value, as this used to, billed the whole percentage again on
    every claim after the first.

    The percent is clamped to [0, 100]. A percentage below what was already
    billed would give a negative period value; that is floored at zero rather
    than written as a credit, and :func:`claim_line_percent_regressed` reports
    it so a person decides whether earlier work was overstated.

    When ``value_override`` is supplied (the user tweaked the period value in
    the preview) it is used instead, clamped to what is left on the line after
    ``prior_value``, so a claim line can never take the line past its
    scheduled value. Quantity progress follows the same split.

    Returns ``{period_completed_qty, period_completed_value,
    period_completed_pct, prior_completed_value, cumulative_completed_value,
    requested_cumulative_value}``, all Decimal. ``period_completed_pct`` keeps
    the observed percent to date, the figure the person entered or observed.
    """
    pct = Decimal(str(observed_pct or 0))
    if pct < DEC_ZERO:
        pct = DEC_ZERO
    if pct > DEC_HUNDRED:
        pct = DEC_HUNDRED
    line_value = Decimal(str(getattr(line, "total_value", 0) or 0))
    qty = Decimal(str(getattr(line, "quantity", 0) or 0))
    prior = Decimal(str(prior_value or 0))
    requested = (line_value * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    if value_override is not None:
        value = Decimal(str(value_override or 0))
        headroom = line_value - prior
        if value < DEC_ZERO:
            value = DEC_ZERO
        if value > headroom:
            value = headroom if headroom > DEC_ZERO else DEC_ZERO
    else:
        value = requested - prior
        # A credit line bills towards a negative total, so "went backwards"
        # is the opposite sign there.
        if (line_value >= DEC_ZERO and value < DEC_ZERO) or (line_value < DEC_ZERO and value > DEC_ZERO):
            value = DEC_ZERO
    cumulative_qty = qty * pct / DEC_HUNDRED
    prior_qty = qty * prior / line_value if line_value != DEC_ZERO else DEC_ZERO
    qty_progress = cumulative_qty - prior_qty
    if value == DEC_ZERO or (qty >= DEC_ZERO and qty_progress < DEC_ZERO):
        qty_progress = DEC_ZERO
    return {
        "period_completed_qty": qty_progress.quantize(Decimal("0.0001")),
        "period_completed_value": value,
        "period_completed_pct": pct.quantize(Decimal("0.0001")),
        "prior_completed_value": prior,
        "cumulative_completed_value": (prior + value).quantize(Decimal("0.0001")),
        "requested_cumulative_value": requested,
    }


def claim_line_percent_regressed(derived: dict[str, Decimal]) -> bool:
    """Whether the percent to date asked for less than earlier claims billed.

    Read off :func:`compute_progress_claim_line`'s output. Only meaningful for
    the percent path; an override states a period value, not a percent.
    """
    requested = derived["requested_cumulative_value"]
    prior = derived["prior_completed_value"]
    # Nothing billed yet means nothing to fall below, on a credit line too.
    if prior > DEC_ZERO:
        return requested < prior
    if prior < DEC_ZERO:
        return requested > prior
    return False


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
    *,
    prior_by_line: dict[uuid.UUID, Decimal] | None = None,
) -> dict[str, Any]:
    """Compute a lump-sum claim payload from per-line completion %.

    ``completion`` maps contract_line_id (UUID or its string form) to percent
    complete TO DATE (0-100). Lines absent from the dict are treated as 0%.
    ``prior_by_line`` is what earlier claims already billed per line (G703
    column D); each line bills ``line total × pct / 100`` less that, so a line
    at 40% then 60% bills 40 and then 20 rather than 40 and then 60. A percent
    below what was already billed bills nothing and is listed in
    ``percent_regressed``.

    Returns a dict with ``claim_lines`` (list of ProgressClaimLine-shaped
    dicts), ``gross``, ``retention``, ``net`` for this period, and
    ``percent_regressed``. ``net`` is gross less retention: gross is this
    period's work, so subtracting earlier payments as well would take them off
    twice. ``prior_paid`` is accepted for callers that still pass it and no
    longer changes the result.
    """
    del prior_paid
    norm: dict[str, Decimal] = {str(k): Decimal(str(v)) for k, v in (completion or {}).items()}
    prior_lookup = prior_by_line or {}
    parent_ids: set[uuid.UUID] = {ln.parent_line_id for ln in lines if getattr(ln, "parent_line_id", None) is not None}

    claim_lines: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    for ln in lines:
        if getattr(ln, "id", None) in parent_ids:
            continue  # skip parent / roll-up rows
        line_id = getattr(ln, "id", None)
        pct = norm.get(str(line_id), DEC_ZERO)
        # Priced off quantity × rate, the figure this generator has always
        # billed a lump-sum line at, rather than the stored total.
        priced = SimpleNamespace(total_value=compute_line_total(ln), quantity=getattr(ln, "quantity", 0))
        derived = compute_progress_claim_line(priced, pct, prior_value=prior_lookup.get(line_id, DEC_ZERO))
        if claim_line_percent_regressed(derived):
            regressed.append(_regressed_entry(ln, derived))
        claim_lines.append({"contract_line_id": line_id, **derived})

    gross = sum((c["period_completed_value"] for c in claim_lines), DEC_ZERO)
    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    net = gross - retention
    if net < DEC_ZERO:
        net = DEC_ZERO
    return {
        "claim_lines": claim_lines,
        "gross": gross,
        "retention": retention,
        "net": net,
        "percent_regressed": regressed,
    }


def _regressed_entry(line: Any, derived: dict[str, Decimal]) -> dict[str, str]:
    """One ``percent_regressed`` record, as plain strings for claim metadata."""
    return {
        "contract_line_id": str(getattr(line, "id", "") or ""),
        "code": str(getattr(line, "code", "") or getattr(line, "description", "") or ""),
        "observed_pct": str(derived["period_completed_pct"]),
        "requested_value": str(derived["requested_cumulative_value"]),
        "previous_value": str(derived["prior_completed_value"]),
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
    ``actual_costs_total`` is this period's cost, so net is gross less
    retention. It used to subtract what earlier claims were paid as well,
    which took every earlier payment off each new claim a second time.
    ``prior_paid`` is accepted for callers that still pass it and no longer
    changes the result.
    """
    del prior_paid
    base = Decimal(str(actual_costs_total or 0))
    fee = _fee_amount_from_structure(fee_structure, base)
    gross = base + fee
    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    net = gross - retention
    if net < DEC_ZERO:
        net = DEC_ZERO
    return {
        "actual_costs": base,
        "fee": fee,
        "gross": gross,
        "retention": retention,
        "net": net,
    }


def generate_tm_claim(
    contract: Contract | Any,
    time_entries_total: Decimal,
    material_entries_total: Decimal,
    fee_structure: FeeStructure | dict[str, Any] | None,
    prior_billed: Decimal = DEC_ZERO,
) -> dict[str, Any]:
    """Compute a T&M claim payload.

    Respects ``contract.terms.tm_nte_cap``. Raises ``NTECapExceededError``
    if (prior_billed + this gross) would exceed the cap. The cap limits what
    is billed, so ``prior_billed`` is the gross of every other claim on the
    contract that went out and was not rejected; checking it against what
    was paid let every claim still awaiting payment slip past the cap. Net is this
    period's gross less retention, for the reason given in
    :func:`generate_cost_plus_claim`.
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
        if cap is not None and (Decimal(str(prior_billed or 0)) + gross) > cap:
            raise NTECapExceededError(
                f"T&M claim would exceed NTE cap: prior={prior_billed}, this={gross}, cap={cap}",
            )

    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    net = gross - retention
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


def _subdivision_caps_declared(country: str | None) -> bool:
    """Whether a country's state or province packs carry retainage statutes.

    The prior question to "is this claim over the cap": are there caps to
    miss. ``resolve_progress_billing`` answers about a subdivision only when
    it is handed an ISO 3166-2 code, and nothing on a project holds one, so
    the state caps are unreachable from the contracts module today. This reads
    the pack listing directly to say whether that silence is costing anything
    on this contract's country, which it does in the United States and nowhere
    else so far.
    """
    if not country:
        return False
    from app.core.regional_packs import packs_for_country  # noqa: PLC0415

    for config in packs_for_country(country):
        if not config.get("parent_pack"):
            continue  # A national pack. Only a subdivision carries state law.
        rules = config.get("state_rules")
        retainage = rules.get("retainage") if isinstance(rules, dict) else None
        if isinstance(retainage, list) and retainage:
            return True
    return False


def _tm_cap_context(contract: Contract, claim: ProgressClaim, ordered: list[ProgressClaim]) -> dict[str, str] | None:
    """What a T&M claim would put against the not-to-exceed cap, or None.

    :func:`generate_tm_claim` checks the cap when it works the claim out, and
    that is the only place it was checked. Two drafts raised the same week
    each fit under the cap on their own, because neither counts the other,
    and both then went out: the cap was a check on generation rather than on
    what is billed. This is the same arithmetic at the moment the claim
    leaves the contractor, when the other draft has usually gone first.

    None when the contract carries no cap, when the cap is unreadable, or on
    a claim that already went out - a claim past draft is history, and a
    finding on it asks a person to undo something they cannot.
    """
    raw = (getattr(contract, "terms", None) or {}).get("tm_nte_cap")
    if raw in (None, "") or claim.status != "draft":
        return None
    try:
        cap = Decimal(str(raw))
    except (ValueError, ArithmeticError):
        return None
    billed = sum(
        (
            Decimal(str(other.gross_amount or 0))
            for other in ordered
            if other.id != claim.id and other.status not in ("draft", "rejected")
        ),
        DEC_ZERO,
    )
    this = Decimal(str(claim.gross_amount or 0))
    return {
        "kind": "tm_nte",
        "limit": str(cap),
        "billed_elsewhere": str(billed),
        "this_claim": str(this),
        "would_be": str(billed + this),
    }


def generate_unit_price_claim(
    contract: Contract | Any,
    lines: list[ContractLine | Any],
    measurements: dict[uuid.UUID | str, Decimal | float | int],
    prior_paid: Decimal = DEC_ZERO,
    *,
    prior_by_line: dict[uuid.UUID, Decimal] | None = None,
) -> dict[str, Any]:
    """Compute a unit-price claim from per-line quantities measured this period.

    A measurement is the quantity put in place during the period, so it is
    the period value as it stands; ``prior_by_line`` only supplies G703 column
    D and the running total. ``net`` is gross less retention, for the same
    reason as in :func:`generate_lump_sum_claim`; ``prior_paid`` no longer
    changes the result.
    """
    del prior_paid
    norm: dict[str, Decimal] = {str(k): Decimal(str(v)) for k, v in (measurements or {}).items()}
    prior_lookup = prior_by_line or {}
    parent_ids: set[uuid.UUID] = {ln.parent_line_id for ln in lines if getattr(ln, "parent_line_id", None) is not None}
    claim_lines: list[dict[str, Any]] = []
    for ln in lines:
        if getattr(ln, "id", None) in parent_ids:
            continue
        line_id = getattr(ln, "id", None)
        measured = norm.get(str(line_id), DEC_ZERO)
        rate = Decimal(str(getattr(ln, "unit_rate", 0) or 0))
        value = (measured * rate).quantize(Decimal("0.0001"))
        qty_contract = Decimal(str(getattr(ln, "quantity", 0) or 0))
        pct = (
            DEC_ZERO
            if qty_contract == DEC_ZERO
            else ((measured / qty_contract * DEC_HUNDRED).quantize(Decimal("0.0001")))
        )
        prior = Decimal(str(prior_lookup.get(line_id, DEC_ZERO)))
        claim_lines.append(
            {
                "contract_line_id": line_id,
                "period_completed_qty": measured,
                "period_completed_value": value,
                "period_completed_pct": pct,
                "prior_completed_value": prior,
                "cumulative_completed_value": (prior + value).quantize(Decimal("0.0001")),
            }
        )

    gross = sum((c["period_completed_value"] for c in claim_lines), DEC_ZERO)
    pct = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
    retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
    net = gross - retention
    if net < DEC_ZERO:
        net = DEC_ZERO
    return {
        "claim_lines": claim_lines,
        "gross": gross,
        "retention": retention,
        "net": net,
        "percent_regressed": [],
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
        self.release_repo = RetentionReleaseRepository(session)
        self.fee_repo = FeeStructureRepository(session)
        self.gainshare_repo = GainshareConfigurationRepository(session)
        self.ld_repo = LDClauseRepository(session)
        self.claim_repo = ProgressClaimRepository(session)
        self.claim_line_repo = ProgressClaimLineRepository(session)
        # Memo for prior_gross_without_schedule_lines, which a certificate
        # build asks twice. Per request, like the service itself.
        self._prior_without_lines_cache: dict[tuple[Any, Any], Decimal] = {}
        # Its retention twin, prior_retention_without_schedule_lines. Same
        # key shape, its own dict, so neither can answer for the other.
        self._prior_retention_without_lines_cache: dict[tuple[Any, Any], Decimal] = {}
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
            # The engine applies the newest schedule that carries tiers and
            # ignores the rest without saying so, which is fine as a rule and
            # bad as a surprise. The rule that reads this says out loud that
            # more than one exists and which one is in force.
            "retention_schedules": [
                {
                    "id": str(s.id),
                    "has_tiers": bool(isinstance(s.accrual_rule, dict) and s.accrual_rule.get("tiers")),
                }
                for s in await self._retention_schedules(contract)
            ],
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
            # The country's retention ladder is frozen onto the contract here
            # for the same reason the contract value above it is. Both stamps
            # go into the one dict: a second assignment to fields["metadata_"]
            # would drop the compliance audit without saying so.
            meta["retention_policy_seed"] = await self.seed_retention_schedule(contract)
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

    #: Contract statuses in which the schedule of values may still be edited
    #: in place. Draft alone: every other status means the contract is signed,
    #: and "suspended" is signed work that has stopped, not work not yet
    #: agreed.
    _LINE_EDITABLE_CONTRACT_STATUSES = frozenset({"draft"})

    async def _assert_contract_lines_editable(self, contract_id: uuid.UUID) -> None:
        """Raise 409 unless this contract's schedule of values is still a draft.

        The contract lines are what every claim bills against. A claim line
        points at one of them, the certificate's "completed from previous
        applications" column is assembled per line from what earlier claims
        billed, and percent complete is measured against the line's scheduled
        value. Editing a line on a signed contract restates all of that
        underneath certificates that have already gone to the payer, and
        nothing on the contract records that anything moved. The instrument
        for changing a signed scope is a change order, which is a document
        both sides see, so the refusal names it rather than only saying no.

        The contract screen already enables line editing only for a draft, so
        this is not a new rule, it is the same rule on the side that cannot be
        bypassed by calling the route directly. A guard that lives only in the
        client is a guard against the client.
        """
        contract = await self.get_contract(contract_id)
        if contract.status in self._LINE_EDITABLE_CONTRACT_STATUSES:
            return
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "contract_lines_frozen",
                "message": (
                    "The schedule of values can only be edited while the contract is a draft; "
                    f"this contract is {contract.status!r}. Raise a change order to alter a signed scope."
                ),
                "contract_status": contract.status,
            },
        )

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
        await self._assert_contract_lines_editable(line.contract_id)
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
            # Deleting what is not there stays a no-op rather than a 404, so a
            # retried delete is not an error. The guard below is reached only
            # for a line that exists, which is the only case that can destroy
            # anything.
            return
        await self._assert_contract_lines_editable(line.contract_id)
        await self.line_repo.delete(line_id)

    # ── Progress claims ──────────────────────────────────────────────────

    async def create_progress_claim(self, data: Any) -> ProgressClaim:
        contract = await self.get_contract(data.contract_id)
        claim_number = data.claim_number or await self.claim_repo.next_claim_number(
            contract.id,
        )
        period = {
            "period_start": data.period_start,
            "period_end": data.period_end,
            "claim_date": data.claim_date,
        }
        claim = ProgressClaim(
            contract_id=contract.id,
            claim_number=claim_number,
            **period,
            # The dates are the parsed strings, written together so the two
            # can never disagree. The period rules and every "claims before
            # this one" lookup read the dates.
            **claim_dates_for_write(period),
            currency=data.currency or contract.currency,
            milestone_id=getattr(data, "milestone_id", None),
            metadata_=data.metadata,
            status="draft",
        )
        return await self.claim_repo.create(claim)

    #: What a claim bills for, and the number it bills under. Once the claim
    #: has left draft these are part of the application the payer is reading,
    #: and the period is what puts the claim in billing order: moving a
    #: certified claim's period rewrites what every later claim counts as
    #: previously certified, which is G702 line 7 and therefore the money.
    _CLAIM_FROZEN_FIELDS = ("period_start", "period_end", "claim_number", "currency", "milestone_id")

    async def update_progress_claim_fields(self, claim: ProgressClaim, fields: dict[str, Any]) -> None:
        """Write a partial update to a claim, keeping the period dates in step.

        The claim PATCH route used to write straight to the repository, so a
        corrected period end would have left ``period_to`` on the old day and
        the claim sorted in the wrong place for good.

        Raises:
            HTTPException: 409 when the claim has left draft and the update
                touches a field the application is built on.
        """
        if claim.status not in self._CLAIM_EDITABLE_STATUSES:
            frozen = sorted(
                name
                for name in self._CLAIM_FROZEN_FIELDS
                if name in fields and str(fields[name] or "") != str(getattr(claim, name, None) or "")
            )
            if frozen:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "claim_terms_locked",
                        "message": (
                            f"This claim is {claim.status!r}; its period and number are part of the application "
                            "that went out. Reject it to reopen them, or correct the figures in the next claim."
                        ),
                        "claim_status": claim.status,
                        "locked_fields": frozen,
                    },
                )
        fields = {**fields, **claim_dates_for_write(fields)}
        if fields:
            await self.claim_repo.update_fields(claim.id, **fields)
            await self.session.refresh(claim)

    async def previous_certificates(self, claim: ProgressClaim) -> tuple[Decimal, str]:
        """G702 line 7, less previous certificates for payment, for one claim.

        The sum over the claims before this one in billing order, rejected ones
        left out, of what each certified: its period gross less the retention
        it held. It used to be the prior claims' gross alone, which left their
        retention in line 7 and under-billed line 8 by it every month.

        Which earlier claims count is a decision, not an oversight: every
        application that was not rejected, submitted and approved ones
        included, rather than only those already certified or paid as the
        form's wording reads. A claim's net due is worked out when it is
        generated and is not worked out again at certification, and nothing
        stops the next claim being generated while this one is still with the
        owner. A line 7 of certified claims only would leave the pending
        claim's net inside the next claim's line 8, and once both are
        certified that work is paid twice. Counting it can only err the other
        way, when the pending claim is later rejected, and then the claim
        after picks the work up again: an underpayment for a month, never a
        double payment. Reading line 7 as certified claims only needs
        certification to refuse or re-work an overlapping claim first
        (test_overlapping_claims_never_pay_the_same_work_twice).

        Returns the amount and the basis it was worked out on. ``"snapshot"``
        when the previous claim stores its certificate: line 7 is then its
        line 6, lines 4 less 5 as it certified them, which is what the form
        asks for. ``"reconstructed"`` for a previous claim from before the
        snapshot: the figure is rebuilt from each prior claim's stored gross
        and retention plus the releases billed on it, which is exact for
        claims generated since the claim basis fix and carries the old double
        count for claims generated before it.

        The snapshot is also refused, in favour of reconstruction, when some
        earlier claim billed gross that no line of its own accounts for. The
        two are not the same quantity. A snapshot is one claim's cumulative
        to date, which is assembled from schedule lines, so a month carried
        by no line is missing from it permanently. Reconstruction sums each
        claim's own gross, so that month is counted once, on the claim that
        billed it. The snapshot is not a cheaper reconstruction, it is a
        lossier one that happens to agree whenever every month has lines,
        which is why it survived: that is the whole population anyone had.

        Both read values that are frozen when a claim is certified. Every
        writer of ``gross_amount`` and ``retention_amount`` requires the
        claim to be a draft, a release can only be billed onto a draft claim
        and cannot be voided off a locked one, and ``certified`` leads only
        to ``paid``. So reconstruction is no more exposed to a later edit
        than the snapshot is; it is simply the more complete of the two.
        """
        prior = await self.claim_repo.prior_claims(claim.contract_id, before_claim_id=claim.id)
        outside = await self.prior_gross_without_schedule_lines(
            claim.contract_id,
            before_claim_id=claim.id,
            prior_claims=prior,
        )
        if (
            prior
            and outside <= DEC_ZERO
            and prior[-1].completed_stored_to_date is not None
            and prior[-1].retention_held_to_date is not None
        ):
            last = prior[-1]
            certified = Decimal(str(last.completed_stored_to_date)) - Decimal(str(last.retention_held_to_date))
            return certified.quantize(Decimal("0.0001")), PREVIOUS_CERTIFICATES_SNAPSHOT
        total = sum(
            (Decimal(str(c.gross_amount or 0)) - Decimal(str(c.retention_amount or 0)) for c in prior),
            DEC_ZERO,
        )
        released = await self.release_repo.billed_on_claims([c.id for c in prior]) if prior else []
        total += sum((Decimal(str(r.amount or 0)) for r in released), DEC_ZERO)
        return total.quantize(Decimal("0.0001")), PREVIOUS_CERTIFICATES_RECONSTRUCTED

    async def prior_gross_without_schedule_lines(
        self,
        contract_id: uuid.UUID,
        *,
        before_claim_id: uuid.UUID | None,
        prior_claims: list[Any] | None = None,
    ) -> Decimal:
        """Gross on earlier claims that no line of those claims accounts for.

        The G703 continuation sheet is assembled per schedule line, and so is
        every cumulative figure frozen on a claim. Money billed with no line
        behind it is therefore invisible to both, while remaining fully
        visible to what the claim certified. This is that money, and it is
        the one definition of it: the sheet puts it on a row of its own and
        :meth:`previous_certificates` refuses the snapshot on the strength of
        it, so the quantity and the condition that depends on it cannot drift
        apart into two answers.

        Two different things arrive in this figure and it is deliberately
        blind to which. A claim may have had no lines at all, billed from
        cost. Or its gross outran the schedule it was apportioned across and
        the remainder was left unplaced. Both are gross that no line carries.

        Floored per claim rather than on the total. The two forms differ only
        when some claim's gross is below its own lines, and which of them
        depends on that never happening is the point: this one is correct
        whether or not the list of writers is complete, the aggregate form is
        correct only if it is. They agree on every shape measured today,
        because a recompute on each line write holds gross equal to the sum
        of the lines, and that recompute is being removed so a claim billed
        from cost keeps its basis when somebody adds a line by hand.

        Memoised on the service, which lives for one request, keyed on
        ``(contract_id, before_claim_id)``. That key is the whole input: the
        residual is a function of the prior claims of one claim on one
        contract, and ``prior_claims`` is only ever those same claims handed
        in to save resolving them twice.

        The memo cannot go stale inside a request, and it is worth saying why
        because the code shows only that it is fast. What it reads is the
        stored gross of claims BEFORE this one, and every writer of that
        column refuses a claim that is not a draft, while nothing that writes
        it goes on to draw a certificate in the same request. The certificate
        path itself only reads. Certification does write, but it writes the
        claim being certified, which by construction is not among the claims
        this is measuring. So no request both populates this and then changes
        what it answers.

        Args:
            contract_id: the contract to measure.
            before_claim_id: claims strictly before this one in billing
                order, rejected ones left out; ``None`` counts every
                non-rejected claim.
            prior_claims: the same claims when the caller already has them,
                to save resolving them twice.

        Returns: the residual, never negative.
        """
        prior = (
            prior_claims
            if prior_claims is not None
            else await self.claim_repo.prior_claims(contract_id, before_claim_id=before_claim_id)
        )
        if not prior:
            return DEC_ZERO
        cache_key = (contract_id, before_claim_id)
        if cache_key in self._prior_without_lines_cache:
            return self._prior_without_lines_cache[cache_key]
        # A certificate build asks for this twice: once here on behalf of
        # line 7, once for the sheet's own row. The answer cannot change
        # inside one request, so it is kept. The service is built per request,
        # so the cache dies with it and never spans a write.
        #
        # One sum per claim, from an aggregate. It used to hydrate every claim
        # line on the contract to add them up here, thousands of rows on a
        # long schedule billed over years, and the retention twin of this
        # method below reads the same sums.
        line_totals = await self.claim_line_repo.period_value_by_claim(contract_id)
        residual = sum(
            (max(Decimal(str(c.gross_amount or 0)) - line_totals.get(c.id, DEC_ZERO), DEC_ZERO) for c in prior),
            DEC_ZERO,
        )
        self._prior_without_lines_cache[cache_key] = residual
        return residual

    async def prior_retention_without_schedule_lines(
        self,
        contract_id: uuid.UUID,
        *,
        before_claim_id: uuid.UUID | None,
        prior_claims: list[Any] | None = None,
    ) -> Decimal:
        """Retention earlier claims held on the gross no line of theirs accounts for.

        The retention half of :meth:`prior_gross_without_schedule_lines`, over
        the same claims and the same residual: per claim, the gross its own
        lines do not carry, floored at zero, and of the retention that claim
        stored the same share, ``retention_amount x residual / gross``. A claim
        with no lines gives all of its retention, a claim whose lines carry its
        whole gross gives none.

        It is what the continuation sheet's row for that money holds in
        column I before any release, and what the retention engine leaves out
        of the retention it measures the schedule against. Read off what each
        claim stored rather than worked out at a rate, because the stored
        figure is what the claim actually held, and a ladder or an edited
        contract rate makes the two differ.

        Memoised per request like its sibling, in a dict of its own, and for
        the same reason it cannot go stale: every writer of a claim's gross or
        retention refuses a claim that is not a draft, and the claims this
        measures come before the one being worked on.

        Returns: the retention, at cents, never negative.
        """
        prior = (
            prior_claims
            if prior_claims is not None
            else await self.claim_repo.prior_claims(contract_id, before_claim_id=before_claim_id)
        )
        if not prior:
            return DEC_ZERO
        cache_key = (contract_id, before_claim_id)
        if cache_key in self._prior_retention_without_lines_cache:
            return self._prior_retention_without_lines_cache[cache_key]
        line_totals = await self.claim_line_repo.period_value_by_claim(contract_id)
        held = DEC_ZERO
        for c in prior:
            gross = Decimal(str(c.gross_amount or 0))
            if gross <= DEC_ZERO:
                continue
            residual = max(gross - line_totals.get(c.id, DEC_ZERO), DEC_ZERO)
            held += Decimal(str(c.retention_amount or 0)) * residual / gross
        held = max(held, DEC_ZERO).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._prior_retention_without_lines_cache[cache_key] = held
        return held

    async def _retention_before(
        self,
        claim: ProgressClaim,
        contract_id: uuid.UUID,
        prior: list[Any],
    ) -> tuple[Decimal, Decimal, Decimal]:
        """What the claims before ``claim`` accrued, by where it sits, and every release billed so far.

        Returns ``(on_schedule, outside_schedule, released)``: the retention
        the earlier claims accrued on schedule lines, the retention they held
        on money no line of theirs carries (see
        :meth:`prior_retention_without_schedule_lines`), and the releases
        billed on them and on ``claim``.
        """
        accrued = sum((Decimal(str(c.retention_amount or 0)) for c in prior), DEC_ZERO)
        outside = await self.prior_retention_without_schedule_lines(
            contract_id,
            before_claim_id=claim.id,
            prior_claims=prior,
        )
        billed = await self.release_repo.billed_on_claims([c.id for c in prior] + [claim.id])
        released = sum((Decimal(str(r.amount or 0)) for r in billed), DEC_ZERO)
        return accrued - outside, outside, released

    async def outside_schedule_retention_held(
        self,
        claim: ProgressClaim,
        contract: Contract,
        *,
        schedule_accrual: Decimal,
        releases_come_off_it: bool,
        prior_claims: list[Any] | None = None,
    ) -> Decimal:
        """G703 column I on the row for money no schedule line carries.

        The retention the earlier claims held on that money (see
        :meth:`prior_retention_without_schedule_lines`), less its share of the
        releases billed to date. A release is claim level, it pays back
        retention rather than the retention of a particular row, so it comes
        off the two pools pro rata to what each has accrued: the schedule's,
        which is what the earlier claims accrued on schedule lines plus
        ``schedule_accrual``, this claim's own, and this row's. The engine
        takes the schedule's share off the retention it holds on the schedule
        (:meth:`claim_retention_figures`), so line 5, the two added up, is
        everything withheld to date less everything released, and a release
        of all of it clears both.

        The split is worked out afresh at every claim from the pools as they
        stand, which needs no history and keeps the two pools in the same
        proportion; the total is what the money depends on, the split
        between the rows is presentation.

        ``releases_come_off_it`` is False where nothing takes a release off
        the schedule's column I: a contract on flat retention prints it at the
        flat rate whatever has been released, and so does a claim the engine
        has not worked out. This row then does the same rather than be the
        one row a release reaches.
        """
        prior = (
            prior_claims
            if prior_claims is not None
            else await self.claim_repo.prior_claims(contract.id, before_claim_id=claim.id)
        )
        on_schedule, outside, released = await self._retention_before(claim, contract.id, prior)
        if outside <= DEC_ZERO or not releases_come_off_it:
            return outside
        share = _release_share_outside_schedule(
            released,
            schedule_pool=on_schedule.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) + schedule_accrual,
            outside_pool=outside,
        )
        return max(outside - share, DEC_ZERO)

    async def _engine_net_due(
        self,
        claim: ProgressClaim,
        contract: Contract,
        figures: ClaimRetention,
        prior_certified: Decimal,
    ) -> Decimal:
        """G702 line 8 for a claim the retention engine works out: line 6 less line 7.

        ``figures`` measure the schedule alone, while line 7 is every earlier
        certificate, the ones for money no schedule line carries included. So
        that money goes back in on both sides, its gross into what has been
        earned and the retention held on it into what is kept, exactly as the
        sheet adds it to line 4 and line 5. Without it the figure the
        certified event carries fell short of line 8 by that money's net.
        """
        outside_gross = await self.prior_gross_without_schedule_lines(contract.id, before_claim_id=claim.id)
        outside_held = await self.outside_schedule_retention_held(
            claim,
            contract,
            schedule_accrual=figures.accrual,
            releases_come_off_it=True,
        )
        earned_less_retention = (figures.completed_stored_to_date + outside_gross) - (figures.held + outside_held)
        return max(earned_less_retention - prior_certified, DEC_ZERO)

    async def claim_completed_and_held(
        self,
        claim: ProgressClaim,
        *,
        contract: Contract | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Work completed and stored to date, and retention held, for a claim.

        The American payment application prints these as lines 4 and 5, but
        they are facts about the contract rather than about the form: a German
        cost-plus job holds retention on the work done to date exactly as an
        American one does, and only the sheet that prints it is country gated.
        Reading them back off :meth:`build_aia_application`, which refuses a
        project outside the US, Canada and Australia, made certifying a claim
        fail with a 404 everywhere else. This answers for every country.

        The two shapes match the sheet's, because they are the same two
        shapes the work has. A claim with a gross and no lines behind it is
        cost-plus or time and materials billing actual cost: there is no
        schedule of values to roll up, so completed to date is what the claims
        before it billed plus what it bills, and held is the retention each of
        them accrued. A claim with lines is rolled up through
        :func:`build_g703`, the same function the sheet uses, so the figure
        frozen here is the figure the sheet prints, down to the cent and
        including how the retainage column is rounded, for a contract whose
        months all carry schedule lines.

        Where they part is a contract that changed shape partway. The sheet
        also carries what earlier claims billed that no schedule line
        carries, which :func:`build_g703` takes as ``prior_without_schedule``
        and this method does not pass, so what is frozen here measures the
        schedule alone. That is deliberate rather than pending: the residual
        belongs in line 5 once, and :meth:`build_aia_application` assembles
        it there from this figure plus that row. Passing it here as well
        would count it twice. The consequence to know is that on such a
        contract the stored figure is smaller than the line 4 the sheet
        prints, and neither is wrong; they answer different questions.

        Args:
            claim: the claim to measure.
            contract: its contract, when the caller already has it.

        Returns:
            ``(completed_stored_to_date, retention_held_to_date)``, at cents.
        """
        from app.modules.contracts.aia import (  # noqa: PLC0415
            bills_without_schedule,
            build_g703,
            sheet_sov_lines,
        )

        if contract is None:
            contract = await self.get_contract(claim.contract_id)
        claim_lines = await self.claim_line_repo.list_for_claim(claim.id)
        gross = Decimal(str(claim.gross_amount or 0))
        cents = Decimal("0.01")

        if bills_without_schedule(claim, claim_lines):
            prior = await self.claim_repo.prior_claims(contract.id, before_claim_id=claim.id)
            completed = sum((Decimal(str(c.gross_amount or 0)) for c in prior), DEC_ZERO) + gross
            held = sum((Decimal(str(c.retention_amount or 0)) for c in prior), DEC_ZERO) + Decimal(
                str(claim.retention_amount or 0)
            )
            return completed.quantize(cents), held.quantize(cents)

        contract_lines = await self.line_repo.list_for_contract(contract.id)
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(contract.id, before_claim_id=claim.id)
        by_contract_line = {cl.contract_line_id: cl for cl in claim_lines}
        # Literally the same rule the sheet uses, because it is the sheet's.
        sov_lines = sheet_sov_lines(contract_lines, by_contract_line, prior_by_line)
        rows = build_g703(
            sov_lines,
            by_contract_line,
            retainage_percent=Decimal(str(contract.retention_percent or 0)),
            prior_by_line=prior_by_line,
        )
        completed = sum((Decimal(str(row["total_completed_stored"])) for row in rows), DEC_ZERO)
        held = sum((Decimal(str(row["retainage"])) for row in rows), DEC_ZERO)
        return completed.quantize(cents), held.quantize(cents)

    async def claim_line_running_totals(
        self,
        claim: ProgressClaim,
        contract_line_id: uuid.UUID,
        period_value: Decimal | float | int | str | None,
    ) -> dict[str, Decimal]:
        """Column D and the running total for one hand-edited claim line.

        The same "prior" as the generators, so a line typed in by hand and a
        generated one agree on what came before.
        """
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(
            claim.contract_id,
            before_claim_id=claim.id,
        )
        prior = prior_by_line.get(contract_line_id, DEC_ZERO)
        return {
            "prior_completed_value": prior,
            "cumulative_completed_value": (prior + Decimal(str(period_value or 0))).quantize(Decimal("0.0001")),
        }

    async def record_percent_regressed(self, claim: ProgressClaim, entries: list[dict[str, str]]) -> None:
        """Keep the lines whose percent to date went backwards on the claim.

        Replaced on every generation, so a regenerated claim never carries a
        finding from the previous run. Read by ``pay_application.percent_regressed``.
        """
        meta = dict(claim.metadata_ or {})
        if entries:
            meta[PERCENT_REGRESSED_META_KEY] = entries
        elif PERCENT_REGRESSED_META_KEY in meta:
            meta.pop(PERCENT_REGRESSED_META_KEY)
        else:
            return
        await self.claim_repo.update_fields(claim.id, metadata_=meta)

    # ── Payment application rules (pay_application) ─────────────────────

    async def claim_rule_context(self, claim: ProgressClaim) -> dict[str, Any]:
        """Build the plain dict the ``pay_application`` rules read.

        One builder for both callers, the validation route the screen polls
        and the gate that runs on submission, so the report a user reads is
        the check that blocks them.
        """
        from app.modules.contracts.aia import build_g703_line  # noqa: PLC0415

        contract = await self.get_contract(claim.contract_id)
        ordered = await self.claim_repo.ordered_for_contract(contract.id)
        earlier = [c for c in claims_before(ordered, claim.id) if c.status != "rejected"]
        previous = earlier[-1] if earlier else None

        contract_lines = {ln.id: ln for ln in await self.line_repo.list_for_contract(contract.id)}
        # What the claims before this one bill on each SoV line NOW, against
        # which this claim's stored column D is checked: an earlier claim
        # regenerated after this one was written leaves the two apart, and
        # nothing else notices.
        prior_now = await self.claim_line_repo.prior_period_value_by_line(contract.id, before_claim_id=claim.id)
        claim_lines = await self.claim_line_repo.list_for_claim(claim.id)
        lines: list[dict[str, Any]] = []
        for index, claim_line in enumerate(claim_lines, start=1):
            contract_line = contract_lines.get(claim_line.contract_line_id)
            if contract_line is None:
                continue
            # The continuation-sheet row itself, so "billed to date" here is
            # column G exactly as the payment application adds it up.
            row = build_g703_line(contract_line, claim_line, line_number=index, retainage_percent=DEC_ZERO)
            lines.append(
                {
                    "contract_line_id": str(contract_line.id),
                    "code": contract_line.code or "",
                    "description": contract_line.description or "",
                    "scheduled_value": str(row["scheduled_value"]),
                    "previous_value": str(row["previous_value"]),
                    "this_period_value": str(row["this_period_value"]),
                    "materials_stored": str(row["materials_stored"]),
                    "total_completed_stored": str(row["total_completed_stored"]),
                    "prior_billed_now": str(prior_now.get(contract_line.id, DEC_ZERO)),
                }
            )

        def _day(value: Any) -> str | None:
            return value.isoformat() if value is not None else None

        context: dict[str, Any] = {
            "claim": {
                "id": str(claim.id),
                "number": claim.claim_number or "",
                "status": claim.status,
                "period_start": claim.period_start,
                "period_end": claim.period_end,
                "claim_date": claim.claim_date,
                "period_from": _day(claim.period_from),
                "period_to": _day(claim.period_to),
                "application_date": _day(claim.application_date),
            },
            "previous_claim": (
                {
                    "id": str(previous.id),
                    "number": previous.claim_number or "",
                    "period_from": _day(previous.period_from),
                    "period_to": _day(previous.period_to),
                }
                if previous is not None
                else None
            ),
            "lines": lines,
            # Written by the generators when a percent to date came in below
            # what earlier claims billed; see compute_progress_claim_line.
            "percent_regressed": list((claim.metadata_ or {}).get(PERCENT_REGRESSED_META_KEY) or []),
            "currency": claim.currency or contract.currency or "",
            # The clock is data: a check about what held at the end of the
            # period gives the same answer when it is re-run next year.
            "as_of": _day(claim.period_to),
            "retention": await self._claim_retention_context(claim, contract),
            # The claim's own stored money beside what it should be now. The
            # header used to be written only by the generator, so a line
            # edited by hand or an earlier claim regenerated left these apart
            # with nothing on screen to say so, and the invoice was raised
            # from the stored figures.
            "totals": {
                "gross_amount": str(claim.gross_amount or 0),
                "retention_amount": str(claim.retention_amount or 0),
                "net_due": str(claim.net_due or 0),
                "prior_claims_total": str(claim.prior_claims_total or 0),
                "lines_total": str(
                    sum((Decimal(str(line.period_completed_value or 0)) for line in claim_lines), DEC_ZERO)
                ),
                "has_lines": bool(claim_lines),
                # What the gross is made of, because "gross equals its lines"
                # is the rule for a claim made of lines and the wrong question
                # for one billed off recorded cost. Empty string for a claim
                # written before the column existed, which reads as the former.
                "gross_basis": claim.gross_basis or "",
                "previous_certificates_now": str((await self.previous_certificates(claim))[0]),
            },
            "cap": _tm_cap_context(contract, claim, ordered),
            "retention_cap": await self._claim_retention_cap_context(claim, contract),
        }

        # What other modules add (the subcontractor pay apps rolled into this
        # claim, when that module is installed). They register with
        # contracts.claim_context rather than contracts importing them, so an
        # install without them checks the claim on its own data.
        extra = await collect_claim_context(self.session, claim)
        clash = sorted(context.keys() & extra.keys())
        if clash:
            # A provider replacing "lines" or "claim" would change what every
            # rule reads without a word; that is a defect in the provider.
            raise RuntimeError(f"claim context providers may not replace core keys: {', '.join(clash)}")
        context.update(extra)
        return context

    async def _claim_retention_cap_context(self, claim: ProgressClaim, contract: Contract) -> dict[str, Any]:
        """The ceiling on retention, the figure it binds, and where there is none.

        Two kinds of cap and only one of them is readable from here. The
        policy carries its own, written by the parties or by a national pack,
        and that is checkable on every claim. The other is state or province
        law, which the subdivision packs hold: reading it needs an ISO 3166-2
        code and a project has no field for one, so those caps cannot be
        applied at all. That is worth saying out loud on a claim in a country
        that has them rather than passing in silence, which is why the country
        and whether it declares any travel with the figures.

        Unlike :meth:`_claim_retention_context` this answers for every claim,
        including the flat-retention shapes. A cost-plus claim holds retention
        too, and a cap binds what is held however it was worked out.
        """
        policy = await self.retention_policy(contract)
        country = ((await self._progress_billing(contract)) or {}).get("country_code")
        held = getattr(claim, "retention_held_to_date", None)
        return {
            "held": None if held is None else str(held),
            "contract_sum": str(contract.total_value or 0),
            "cap_percent": (
                None if policy.cap_percent_of_contract_sum is None else str(policy.cap_percent_of_contract_sum)
            ),
            "country_code": country,
            "subdivision_caps_declared": _subdivision_caps_declared(country),
        }

    async def _claim_retention_context(self, claim: ProgressClaim, contract: Contract) -> dict[str, Any] | None:
        """What the claim stores for retention beside what its policy gives now.

        None for a claim the engine has not worked out (its figures predate
        the snapshot) and for one on flat retention: there is nothing stored
        to compare.
        """
        if getattr(claim, "retention_held_to_date", None) is None:
            return None
        fresh = await self.claim_retention_figures(claim, contract=contract)
        if fresh is None:
            return None
        return {
            "held": str(claim.retention_held_to_date),
            "expected_held": str(fresh.held),
            "accrual": str(claim.retention_amount),
            "expected_accrual": str(fresh.accrual),
            "accrued_to_date": str(fresh.accrued_to_date),
            "released_to_date": str(fresh.released_to_date),
        }

    async def run_claim_rules(self, claim: ProgressClaim) -> ValidationReport:
        """Run the ``pay_application`` rule set against one claim."""
        from app.modules.contracts.validators import PAY_APPLICATION_RULE_SET  # noqa: PLC0415

        contract = await self.get_contract(claim.contract_id)
        return await validation_engine.validate(
            data=await self.claim_rule_context(claim),
            rule_sets=[PAY_APPLICATION_RULE_SET],
            target_type="progress_claim",
            target_id=str(claim.id),
            project_id=str(contract.project_id),
            metadata={"locale": get_locale(), "workflow": "progress_claim_submission"},
        )

    async def enforce_claim_rules(self, claim: ProgressClaim) -> ValidationReport:
        """Refuse to submit a claim while its payment application rules block.

        Every ERROR in the set blocks, including the ones other modules
        register into it, for the same reason ``enforce_contract_rules`` does
        not name a rule: the set is the statement of what a payment
        application must be before it goes to the owner.
        """
        from app.modules.contracts.messages import translate as contracts_translate  # noqa: PLC0415
        from app.modules.contracts.validators import PAY_APPLICATION_RULE_SET  # noqa: PLC0415

        report = await self.run_claim_rules(claim)
        locale = get_locale()
        if PAY_APPLICATION_RULE_SET in report.unsupported_rule_sets:
            # A set with no rules registered checks nothing, and its silence
            # must not read as a pass on a document that goes to the owner.
            logger.error("contracts: rule set %s is not registered; claim gate cannot run", PAY_APPLICATION_RULE_SET)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=contracts_translate("pay_application.errors.rules_unavailable", locale=locale),
            )
        if not report.has_errors:
            return report

        # The submit button's error path is a toast, so the findings have to
        # survive being flattened to one line.
        heads = "; ".join(r.message for r in report.errors[:3])
        more = len(report.errors) - 3
        if more > 0:
            heads = f"{heads} (+{more})"
        logger.info(
            "Payment application rules BLOCKED submission of claim %s (%d errors)", claim.id, len(report.errors)
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=self._compliance_http_detail(
                report,
                [],
                message=contracts_translate("pay_application.errors.submission_blocked", locale=locale, findings=heads),
            ),
        )

    async def validate_claim(self, claim_id: uuid.UUID) -> dict[str, Any]:
        """The ``pay_application`` report for one claim, as a traffic light.

        Built by :meth:`run_claim_rules`, the method the submission gate uses,
        so what the panel shows is what the submit button will do.
        """
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        report = await self.run_claim_rules(claim)

        def _serialise(r: Any) -> dict[str, Any]:
            return {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value,
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
                "details": r.details,
            }

        return {
            "claim_id": str(claim.id),
            "status": report.status.value,
            "score": report.score,
            "summary": report.summary(),
            "rule_sets": report.rule_sets_applied,
            "unsupported_rule_sets": report.unsupported_rule_sets,
            "errors": [_serialise(r) for r in report.errors],
            "warnings": [_serialise(r) for r in report.warnings],
        }

    async def transition_claim(
        self,
        claim_id: uuid.UUID,
        target_status: str,
        actor_id: str | None = None,
    ) -> ProgressClaim:
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        if claim.status == "certified" and target_status == "rejected":
            # Named rather than left to the transition map, because the map
            # can only say "not allowed" and the person asking has a real
            # problem to solve. See the comment on _CLAIM_TRANSITIONS.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "certified_claim_not_reversible",
                    "message": (
                        "A certified claim cannot be rejected: the certificate is out and the invoice "
                        "behind it is not reversed by a status change. Correct the amount on the next "
                        "claim, or credit the invoice."
                    ),
                    "claim_status": claim.status,
                },
            )
        try:
            assert_claim_transition(claim.status, target_status)
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        from datetime import UTC, datetime

        if claim.status == "draft" and target_status == "submitted":
            # The moment the claim leaves the contractor. Checked here rather
            # than at approval because a payment application with a broken
            # period or an overbilled line should never reach the owner.
            await self.enforce_claim_rules(claim)

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
            # Freeze work completed and stored to date, and retention held,
            # onto the claim. The retention engine writes them whenever it has
            # a schedule of values to work on; a cost-plus or T&M claim has
            # none, so it stored nothing and those figures were worked out
            # again from the claims around it every time anything was drawn.
            # This is the moment they stop moving, and a claim that already
            # carries them is left exactly as it is.
            if (
                getattr(claim, "completed_stored_to_date", None) is None
                or getattr(claim, "retention_held_to_date", None) is None
            ):
                completed, held = await self.claim_completed_and_held(claim)
                fields["completed_stored_to_date"] = completed
                fields["retention_held_to_date"] = held
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
        fee_structure = await self.fee_repo.get_for_contract(contract.id)
        # What the claims before this one already billed per SoV line (G703
        # column D). A percent to date bills only the difference, and every
        # line's running total builds on it. Read before the old draft lines
        # are deleted, and "before" is billing order, so regenerating an
        # earlier claim never counts a later one as previous.
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(
            contract.id,
            before_claim_id=claim_id,
        )

        result: dict[str, Any]
        # What the gross about to be written is made of, recorded rather than
        # inferred later. "lines" is the default because every branch below
        # sums the claim's own period values into the gross; the two that do
        # not say so themselves, beside the empty line list that is the same
        # fact stated differently. Set here from the branch taken rather than
        # from the contract type at the bottom, so a branch that changes shape
        # has to say what it now means instead of inheriting an answer.
        gross_basis = "lines"
        # Every generator bills this period and nets it to gross less
        # retention; cost-plus and T&M have no SoV lines behind them.
        if contract.contract_type == "lump_sum":
            result = generate_lump_sum_claim(
                contract,
                lines,
                payload.completion or {},
                prior_by_line=prior_by_line,
            )
        elif contract.contract_type in ("unit_price", "remeasurement"):
            # Remeasurement contracts bill re-measured quantities at agreed
            # unit rates, exactly like unit-price, so they share the generator.
            result = generate_unit_price_claim(
                contract,
                lines,
                payload.measurements or {},
                prior_by_line=prior_by_line,
            )
        elif contract.contract_type == "cost_plus":
            result = generate_cost_plus_claim(
                contract,
                fee_structure,
                Decimal(str(payload.actual_costs_total or 0)),
            )
            result["claim_lines"] = []
            gross_basis = "cost"
        elif contract.contract_type == "tm":
            # A not-to-exceed cap is lifetime billing, so it counts every
            # other claim on the contract that went out and was not rejected,
            # paid or not and before or after this one in billing order.
            # Another draft has not been billed, and counting it would let
            # two drafts in progress block each other.
            prior_billed = sum(
                (
                    Decimal(str(c.gross_amount or 0))
                    for c in await self.claim_repo.ordered_for_contract(contract.id)
                    if c.id != claim_id and c.status not in ("draft", "rejected")
                ),
                DEC_ZERO,
            )
            try:
                result = generate_tm_claim(
                    contract,
                    Decimal(str(payload.time_entries_total or 0)),
                    Decimal(str(payload.material_entries_total or 0)),
                    fee_structure,
                    prior_billed,
                )
            except NTECapExceededError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "nte_cap_exceeded", "message": str(exc)},
                ) from exc
            result["claim_lines"] = []
            gross_basis = "cost"
        else:
            # GMP / design_build / combination - default to lump-sum semantics
            result = generate_lump_sum_claim(
                contract,
                lines,
                payload.completion or {},
                prior_by_line=prior_by_line,
            )

        # Persist new claim lines (replacing any existing draft ones).
        existing = await self.claim_line_repo.list_for_claim(claim_id)
        for ex in existing:
            await self.claim_line_repo.delete(ex.id)
        # Running total: per SoV line, cumulative = what the earlier claims
        # billed + this period. costmodel's claimed-to-date reads
        # cumulative_completed_value as that running total, and column D is
        # stored so a later re-render reads the same prior as this one.
        new_lines: list[ProgressClaimLine] = []
        for cl in result.get("claim_lines", []) or []:
            period_value = Decimal(str(cl["period_completed_value"]))
            prior_value = Decimal(
                str(cl.get("prior_completed_value", prior_by_line.get(cl["contract_line_id"], DEC_ZERO)))
            )
            new_lines.append(
                ProgressClaimLine(
                    progress_claim_id=claim_id,
                    contract_line_id=cl["contract_line_id"],
                    period_completed_qty=Decimal(str(cl["period_completed_qty"])),
                    period_completed_value=period_value,
                    period_completed_pct=Decimal(str(cl["period_completed_pct"])),
                    prior_completed_value=prior_value,
                    cumulative_completed_value=(prior_value + period_value).quantize(
                        Decimal("0.0001"),
                    ),
                )
            )
        if new_lines:
            await self.claim_line_repo.bulk_create(new_lines)

        # Roll up totals on the claim row. "Prior claims" is the previous
        # certificates (G702 line 7), which net_due is already net of.
        prior_claims_total, _basis = await self.previous_certificates(claim)
        await self.claim_repo.update_fields(
            claim_id,
            gross_amount=Decimal(str(result["gross"])),
            retention_amount=Decimal(str(result["retention"])),
            prior_claims_total=prior_claims_total,
            net_due=Decimal(str(result["net"])),
            gross_basis=gross_basis,
        )
        await self.record_percent_regressed(claim, list(result.get("percent_regressed") or []))
        # The generator's flat figures stand for cost-plus and T&M; on a
        # schedule of values the policy works retention out on work to date.
        return await self.roll_claim_retention(claim_id)

    # ── Progress bridge (Gap I) ──────────────────────────────────────────

    #: Claim statuses whose line breakdown may still be edited. A draft only.
    #: A submitted claim used to be editable too, on the reasoning that a
    #: re-measure mid-review is common, and that is how a claim already with
    #: the payer had its lines changed under it: the application the payer is
    #: reading says one thing and the lines behind it another, and every later
    #: claim's line 7 is built on the figures it certified. A re-measure now
    #: goes back through rejection, which is a decision somebody records.
    _CLAIM_EDITABLE_STATUSES = frozenset({"draft"})

    def _assert_claim_editable(self, claim: ProgressClaim) -> None:
        """Raise HTTP 422 unless the claim is in a line-editable status."""
        if claim.status not in self._CLAIM_EDITABLE_STATUSES:
            # What to do next depends on the status, and saying the wrong
            # thing sends the reader into a door the server then holds shut:
            # a certified or paid claim cannot be rejected back to draft,
            # because the certificate is out and the money has moved.
            way_back = (
                "Correct it on the next claim, or credit the invoice."
                if claim.status in ("certified", "paid")
                else "Reject it to reopen the breakdown."
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "claim_not_editable",
                    "message": (
                        "Progress lines can only be populated / committed on a draft claim; "
                        f"this claim is {claim.status!r}. {way_back}"
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
        from datetime import UTC, datetime, time  # noqa: PLC0415

        # The claim bills one period, so it reads the site as it stood at the
        # end of that period. Reading the latest observation instead billed
        # work done after the period closed, which the next claim then had to
        # take back off. The end of the day, because the reading carries a
        # time of day and the period end is a date; an undated claim has no
        # period to read as of, and gets what it always got.
        period_to = getattr(claim, "period_to", None)
        as_of = datetime.combine(period_to, time.max, tzinfo=UTC) if period_to else None

        lines = await self.line_repo.list_for_contract(contract.id)
        # Roll-up / parent rows are summed from children - never bill them
        # directly, exactly as the auto-generate path does.
        parent_ids = {ln.parent_line_id for ln in lines if getattr(ln, "parent_line_id", None) is not None}

        # Column D per line: the preview bills percent to date less what the
        # claims before this one already billed, exactly as commit will.
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(
            contract.id,
            before_claim_id=claim.id,
        )

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
            entry = await progress_repo.get_latest_for_position(contract.project_id, pos_id, as_of=as_of)
            if entry is None:
                skipped_no_progress += 1
                continue
            observed_pct = Decimal(str(entry.percent_complete or 0))
            derived = compute_progress_claim_line(ln, observed_pct, prior_value=prior_by_line.get(ln.id, DEC_ZERO))
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
                    "prior_completed_value": derived["prior_completed_value"],
                    "cumulative_completed_value": derived["cumulative_completed_value"],
                    "percent_regressed": claim_line_percent_regressed(derived),
                }
            )

        prior_certified, _basis = await self.previous_certificates(claim)
        # The claim as it would stand once every previewed line is committed:
        # its other lines stay, the previewed ones replace theirs.
        previewed = {it["contract_line_id"] for it in items}
        existing = await self.claim_line_repo.list_for_claim(claim.id)
        stored_by_line = {ln.contract_line_id: ln.materials_stored_value for ln in existing}
        would_be = [ln for ln in existing if ln.contract_line_id not in previewed] + [
            SimpleNamespace(
                contract_line_id=it["contract_line_id"],
                period_completed_value=it["period_completed_value"],
                prior_completed_value=it["prior_completed_value"],
                cumulative_completed_value=it["cumulative_completed_value"],
                materials_stored_value=stored_by_line.get(it["contract_line_id"], DEC_ZERO),
            )
            for it in items
        ]
        gross = sum((Decimal(str(ln.period_completed_value or 0)) for ln in would_be), DEC_ZERO)
        figures = await self.claim_retention_figures(claim, contract=contract, lines=would_be)
        if figures is None:
            pct = Decimal(str(contract.retention_percent or 0))
            retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
            # Gross is this period's work, so net due is gross less retention.
            net = gross - retention
        else:
            retention = figures.accrual
            # The net the commit will write, worked out the same way.
            net = await self._engine_net_due(claim, contract, figures, prior_certified)
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
            "prior_claims_total": prior_certified,
            "net_due": net,
        }

    async def commit_preview_to_claim(
        self,
        claim_id: uuid.UUID,
        lines_data: list[Any],
        *,
        actor_id: str | None = None,
    ) -> ProgressClaim:
        """Persist the ticked rows of a populate preview and roll up totals.

        Only the SoV lines in ``lines_data`` are written: whatever the claim
        had on those lines is replaced, so committing the same preview twice
        yields one line each, never duplicates. A claim line on any SoV line
        that is not in ``lines_data`` stays exactly as it was. The preview
        lists only lines with progress behind them, so a line typed in by hand
        is never on it, and unticking a row means "do not change this", not
        "delete what I entered".

        Each written line's value is recomputed server-side (percent to date
        less what earlier claims billed, or the supplied override clamped to
        what is left on the line), so a tampered total cannot inflate the
        claim. The claim's gross / retention / prior / net are then re-rolled
        over every line it now has, and ``contracts.claim.populated`` is
        emitted.

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
        # Read before the draft lines are wiped; see auto_generate_claim_lines.
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(
            contract.id,
            before_claim_id=claim_id,
        )
        resolved: list[tuple[Any, dict[str, Decimal]]] = []
        # An override states a period value rather than a percent, so only
        # the lines committed on the percent can have gone backwards.
        regressed: list[dict[str, str]] = []
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
            override = getattr(item, "period_completed_value", None)
            derived = compute_progress_claim_line(
                sov_line,
                getattr(item, "period_completed_pct", 0),
                value_override=override,
                prior_value=prior_by_line.get(sov_line.id, DEC_ZERO),
            )
            if override is None and claim_line_percent_regressed(derived):
                regressed.append(_regressed_entry(sov_line, derived))
            resolved.append((sov_line, derived))

        # Replace the ticked SoV lines only; see the docstring.
        ticked = {sov_line.id for sov_line, _derived in resolved}
        await self.claim_line_repo.delete_for_claim_lines(claim_id, ticked)
        # Running total: cumulative = what the earlier claims billed on this
        # SoV line + this period, with column D stored beside it. costmodel
        # reads cumulative_completed_value as claimed-to-date.
        new_lines: list[ProgressClaimLine] = [
            ProgressClaimLine(
                progress_claim_id=claim_id,
                contract_line_id=sov_line.id,
                period_completed_qty=derived["period_completed_qty"],
                period_completed_value=derived["period_completed_value"],
                period_completed_pct=derived["period_completed_pct"],
                prior_completed_value=derived["prior_completed_value"],
                cumulative_completed_value=derived["cumulative_completed_value"],
            )
            for sov_line, derived in resolved
        ]
        if new_lines:
            await self.claim_line_repo.bulk_create(new_lines)

        prior_certified, _basis = await self.previous_certificates(claim)
        # The claim's gross is every line it has, the kept ones included.
        all_lines = await self.claim_line_repo.list_for_claim(claim_id)
        gross = sum((Decimal(str(ln.period_completed_value or 0)) for ln in all_lines), DEC_ZERO)
        pct = Decimal(str(contract.retention_percent or 0))
        retention = (gross * pct / DEC_HUNDRED).quantize(Decimal("0.0001"))
        # This period's gross, so net due is gross less retention; see
        # generate_lump_sum_claim.
        net = gross - retention
        if net < DEC_ZERO:
            net = DEC_ZERO
        await self.claim_repo.update_fields(
            claim_id,
            gross_amount=gross,
            retention_amount=retention,
            prior_claims_total=prior_certified,
            net_due=net,
            # This path just made the gross the sum of the claim's lines, so
            # it says so, including on a claim generated from cost: nothing
            # stops a populate on a cost-plus contract that also carries a
            # schedule of values, and a claim that records a basis it no
            # longer has would be held to the wrong rule for the rest of its
            # life. Adding one line by hand is the opposite case and leaves
            # the basis alone, because a breakdown row is not a decision to
            # rebuild the claim from the schedule.
            gross_basis="lines",
        )
        # Findings on the lines left alone still stand; the ticked lines get
        # this commit's.
        ticked_ids = {str(line_id) for line_id in ticked}
        kept_findings = [
            entry
            for entry in (claim.metadata_ or {}).get(PERCENT_REGRESSED_META_KEY) or []
            if entry.get("contract_line_id") not in ticked_ids
        ]
        await self.record_percent_regressed(claim, kept_findings + regressed)
        claim = await self.roll_claim_retention(claim_id, gross_follows_lines=True)
        event_bus.publish_detached(
            CLAIM_POPULATED,
            data={
                "claim_id": str(claim.id),
                "contract_id": str(contract.id),
                "claim_number": claim.claim_number,
                "line_count": len(new_lines),
                "gross": str(claim.gross_amount),
                "retention": str(claim.retention_amount),
                "net_due": str(claim.net_due),
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

    async def final_account_figures(
        self,
        contract: Contract,
        payload: Any,
        existing: FinalAccount | None,
    ) -> dict[str, Decimal]:
        """The money on a final account: what the request states, else what is already agreed, else the ledger.

        Once a final account exists the checklist reads retention from it and
        not from the claims, so a figure written here is the contract's
        retention for good. The Close button sends only the final value and a
        status, and the schema used to fill everything else with 0: closing a
        contract that held retention recorded that none was ever withheld, and
        overwrote an agreed final account with zeros. So a figure the request
        leaves out is never 0 by default. An existing final account keeps its
        figure, because someone agreed it; without one the figure comes from
        the ledger, the same figures the checklist shows before close.
        ``final_balance`` is what is left to pay, the final value less what
        was paid, as the seeded final accounts write it.
        """
        stated = {name: getattr(payload, name, None) for name in FINAL_ACCOUNT_MONEY_FIELDS}
        ledger: dict[str, Decimal] | None = None
        figures: dict[str, Decimal] = {}
        for name in FINAL_ACCOUNT_MONEY_FIELDS:
            if name == "final_balance":
                continue
            if stated[name] is not None:
                figures[name] = Decimal(str(stated[name]))
            elif existing is not None:
                figures[name] = Decimal(str(getattr(existing, name) or 0))
            else:
                if ledger is None:
                    ledger = await self._final_account_ledger(contract)
                figures[name] = ledger[name]
        if stated["final_balance"] is not None:
            figures["final_balance"] = Decimal(str(stated["final_balance"]))
        elif existing is not None and stated["final_contract_value"] is None and stated["total_paid"] is None:
            figures["final_balance"] = Decimal(str(existing.final_balance or 0))
        else:
            figures["final_balance"] = figures["final_contract_value"] - figures["total_paid"]
        return figures

    async def _final_account_ledger(self, contract: Contract) -> dict[str, Decimal]:
        """What the claims and releases say a final account should hold, before anyone agrees it."""
        held, released = await self._retention_ledger(contract)
        return {
            "final_contract_value": Decimal(str(contract.total_value or 0)),
            "total_paid": await self.claim_repo.paid_total(contract.id),
            "retention_held": held,
            "retention_released": released,
        }

    async def create_final_account(self, payload: Any) -> FinalAccount:
        """Create a final account; figures the request leaves out come from the ledger."""
        contract = await self.get_contract(payload.contract_id)
        figures = await self.final_account_figures(contract, payload, None)
        final_account = FinalAccount(
            contract_id=contract.id,
            **figures,
            sign_off_date=payload.sign_off_date,
            sign_off_by=payload.sign_off_by,
            status=payload.status,
            notes=payload.notes,
        )
        return await self.final_account_repo.create(final_account)

    async def close_contract(
        self,
        contract_id: uuid.UUID,
        payload: Any,
        actor_id: str | None = None,
    ) -> FinalAccount:
        """Close a contract - create / update the FinalAccount + flip status.

        The final account's money comes from :meth:`final_account_figures`,
        so a Close that sends only the final value keeps the retention held.
        """
        contract = await self.get_contract(contract_id)
        existing = await self.final_account_repo.get_for_contract(contract_id)
        fields: dict[str, Any] = {
            **await self.final_account_figures(contract, payload, existing),
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
        # Single JOIN instead of N+1 (one claim-line query per claim). Each
        # line arrives with its claim, so the status and the billing order are
        # read from the claim rather than tagged onto the line here.
        return compute_sov_status(
            lines,
            await self.claim_line_repo.lines_with_claim_for_contract(contract.id),
            retention_percent=contract.retention_percent,
        )

    # ── Retention ledger ─────────────────────────────────────────────────
    #
    # Two ledgers. Accrual lives on the claims: each claim's retention_amount
    # is what it added, and its snapshot (lines 4 and 5, column I per line)
    # is what its payment application certified. Release lives on
    # RetentionRelease rows, proposed, approved against the documents the
    # event needs, and billed on a claim, where it takes line 5 down and adds
    # to what that claim pays.

    async def _retention_schedules(self, contract: Contract) -> list[RetentionSchedule]:
        """The contract's retention schedules, the most recent first."""
        schedules = await self.retention_repo.list_for_contract(contract.id)
        return sorted(schedules, key=lambda s: (s.created_at is not None, s.created_at), reverse=True)

    async def _accrual_lock(self, contract: Contract) -> ProgressClaim | None:
        """The first claim on the contract that has left draft, or None.

        A rejected claim does not lock anything: it was taken back, it counts
        as nothing certified everywhere else in this module, and it can be
        returned to draft. Anything else has gone to the payer.
        """
        for claim in await self.claim_repo.ordered_for_contract(contract.id):
            if claim.status not in ("draft", "rejected"):
                return claim
        return None

    #: Why a contract was, or was not, given its country's retention ladder as
    #: it was signed. Recorded on ``metadata_["retention_policy_seed"]``.
    RETENTION_SEED_REASONS: tuple[str, ...] = (
        "seeded",
        "pack_silent",
        "pack_declares_no_tiers",
        "pack_policy_unreadable",
        "policy_already_set",
        "flat_retention_contract_type",
        "contract_rate_differs",
    )

    async def seed_retention_schedule(self, contract: Contract) -> dict[str, Any]:
        """Freeze the country's retention ladder onto a contract as it is signed.

        The packs declare a retention policy per country and the engine applies
        one only from a :class:`RetentionSchedule` row, which nothing ever
        wrote. So a United States contract retained its opening rate to the end
        of the job while the pack said the rate halves at half complete: the
        rule was declared and never applied. This writes it onto the contract
        at the moment it is signed, for the same reason
        ``original_contract_value`` is frozen there. A later correction to a
        pack, or a change to the project's country, then cannot rewrite what an
        already signed contract withholds.

        Nothing is written unless the pack's opening rate is the rate the
        parties agreed. Equality, not a bound: a ladder opening below the
        agreed rate releases money early, one opening above it withholds more
        than was agreed, and those are as wrong as each other. Where they
        agree, the parties took the country's standard opening rate and the
        country's standard step-down goes with it, which from there can only
        reduce what is held.

        ``release_rule`` is left empty deliberately. Releases already resolve
        through the pack on every read, and a release rule frozen here would
        outlive a correction to the documents an event requires, which is the
        half of this our packs are still young enough to get wrong.

        Returns:
            The audit stamp for ``metadata_["retention_policy_seed"]``:
            ``seeded``, a ``reason`` from :data:`RETENTION_SEED_REASONS`, and
            the country and schedule id where there is one.
        """

        def skipped(reason: str, **extra: Any) -> dict[str, Any]:
            return {"seeded": False, "reason": reason, **extra}

        if contract.contract_type in FLAT_RETENTION_CONTRACT_TYPES:
            # No schedule of values, so percent complete has nothing to measure
            # against and the ladder is never consulted. Writing one would make
            # this stamp say the contract steps down when it does not.
            return skipped("flat_retention_contract_type")
        for existing in await self._retention_schedules(contract):
            rule = existing.accrual_rule if isinstance(existing.accrual_rule, dict) else {}
            if rule.get("tiers"):
                # Somebody has already written a policy for this contract.
                # Read through retention_policy() this would refuse the signing
                # over a malformed schedule, which signing is not about.
                return skipped("policy_already_set", retention_schedule_id=str(existing.id))
        billing = await self._progress_billing(contract)
        country = (billing or {}).get("country_code")
        pack_rule = (billing or {}).get("retention_policy")
        if not isinstance(pack_rule, dict):
            return skipped("pack_silent", country_code=country)
        if not pack_rule.get("tiers"):
            return skipped("pack_declares_no_tiers", country_code=country)
        agreed = Decimal(str(contract.retention_percent or 0))
        try:
            policy = policy_from_rule(pack_rule, fallback_rate=agreed)
        except ValueError as exc:
            # The pack is wrong. A contract nobody can sign is a worse answer
            # than a contract on its own flat rate, so this is recorded and
            # the signing goes through.
            return skipped("pack_policy_unreadable", country_code=country, message=str(exc))
        opening = policy.tiers[0].rate
        if opening != agreed:
            # Both written at the scale of the column the agreed rate lives in.
            # Decimal comparison ignores scale but str does not, and a stamp
            # that reads "5" or "5.00" depending on whether the row had been
            # read back from the database is a poor thing to audit against.
            places = Decimal("0.01")
            return skipped(
                "contract_rate_differs",
                country_code=country,
                pack_opening_rate=f"{opening.quantize(places):f}",
                contract_rate=f"{agreed.quantize(places):f}",
            )
        row = await self.retention_repo.create(
            RetentionSchedule(contract_id=contract.id, accrual_rule=dict(pack_rule), release_rule={})
        )
        return {
            "seeded": True,
            "reason": "seeded",
            "country_code": country,
            "retention_schedule_id": str(row.id),
            "tier_count": len(policy.tiers),
        }

    async def retention_policy_view(self, contract: Contract) -> dict[str, Any]:
        """The accrual policy in force, and what about it can still change.

        The editor needs three things the engine alone does not say: which
        schedule the policy came from, so a change knows where to land; that
        the contract's own flat rate is standing in when no schedule carries
        tiers; and which fields a save would refuse, so the screen can grey
        them before the person types rather than after.
        """
        policy = await self.retention_policy(contract)
        schedule = next(
            (
                candidate
                for candidate in await self._retention_schedules(contract)
                if isinstance(candidate.accrual_rule, dict) and candidate.accrual_rule.get("tiers")
            ),
            None,
        )
        lock = await self._accrual_lock(contract)
        return {
            "contract_id": contract.id,
            "retention_schedule_id": schedule.id if schedule is not None else None,
            "source": policy.source or CONTRACT_RATE_SOURCE,
            "tiers": [{"from_percent_complete": t.from_percent_complete, "rate": t.rate} for t in policy.tiers],
            "tier_mode": policy.tier_mode,
            "stored_materials_rate": policy.stored_materials_rate,
            "cap_percent_of_contract_sum": policy.cap_percent_of_contract_sum,
            "statute_reference": policy.statute_reference,
            "effective_date": policy.effective_date,
            "accrual_locked": lock is not None,
            "locked_by_claim": None
            if lock is None
            else {
                "claim_id": lock.id,
                "claim_number": lock.claim_number or "",
                "claim_status": lock.status,
            },
            "locked_fields": list(_ACCRUAL_POLICY_FIELDS) if lock is not None else [],
        }

    async def set_retention_policy(self, contract: Contract, payload: Any) -> dict[str, Any]:
        """Write the contract's accrual policy, refusing what is already history.

        The ladder decides money that has already been taken off the
        contractor and already stated on a certificate somebody has read. A
        certified claim carries its own frozen figures and is safe either way,
        but the next draft claim is not: its retention is built on what the
        earlier claims accrued, worked out under the rule as it was. Move the
        rule underneath that and the contract no longer explains the amount it
        is holding, with nothing anywhere able to say which rule produced
        which part of it.

        So the ladder is editable only while every claim is a draft or was
        rejected, and the change is made through a change order or the next
        contract after that, never backwards. The words around the ladder,
        the statute it cites and the notes, are always editable: they decide
        nothing.

        Raises:
            HTTPException 409 with ``retention_accrual_locked`` when the
                request would move the ladder after a claim has gone out; the
                claim that locked it is named in the detail.
        """
        sent = payload.model_dump(exclude_unset=True)
        touched = [field for field in _ACCRUAL_POLICY_FIELDS if field in sent]
        lock = await self._accrual_lock(contract)
        if touched and lock is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "retention_accrual_locked",
                    "message": (
                        f"How this contract holds retention cannot be changed: claim "
                        f"{lock.claim_number or lock.id} is {lock.status!r}, so the rule is already "
                        "part of what it certified. Agree the change on a change order or the next "
                        "contract; it does not apply to work already billed."
                    ),
                    "claim_id": str(lock.id),
                    "claim_number": lock.claim_number or "",
                    "claim_status": lock.status,
                    "locked_fields": touched,
                },
            )

        schedules = await self._retention_schedules(contract)
        target = next(
            (s for s in schedules if isinstance(s.accrual_rule, dict) and s.accrual_rule.get("tiers")),
            None,
        ) or next(iter(schedules), None)
        rule = dict(target.accrual_rule) if target is not None and isinstance(target.accrual_rule, dict) else {}

        if "tiers" in sent:
            rule["tiers"] = [
                {"from_percent_complete": str(tier["from_percent_complete"]), "rate": str(tier["rate"])}
                for tier in sent["tiers"]
            ]
        for field in ("tier_mode", "stored_materials_rate", "statute_reference"):
            if field in sent:
                value = sent[field]
                rule[field] = None if value is None else str(value)
        if "cap_percent_of_contract_sum" in sent:
            value = sent["cap_percent_of_contract_sum"]
            # The engine reads the cap nested, because a cap has more than one
            # possible basis and only this one is wired.
            rule["cap"] = None if value is None else {"percent_of_contract_sum": str(value)}
        if "effective_date" in sent:
            rule["effective_date"] = None if sent["effective_date"] is None else sent["effective_date"].isoformat()

        # Refuse a ladder nobody can apply here, where it is written, rather
        # than on every payment application from now on.
        try:
            policy_from_rule(rule, fallback_rate=contract.retention_percent or 0)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "retention_policy_unreadable",
                    "message": f"This retention policy cannot be applied: {exc}",
                },
            ) from exc

        fields: dict[str, Any] = {"accrual_rule": rule}
        if "notes" in sent:
            fields["notes"] = sent["notes"]
        if target is None:
            await self.retention_repo.create(RetentionSchedule(contract_id=contract.id, release_rule={}, **fields))
        else:
            await self.retention_repo.update_fields(target.id, **fields)
        return await self.retention_policy_view(contract)

    async def retention_policy(self, contract: Contract) -> RetentionPolicy:
        """The accrual policy in force: the latest schedule that has tiers, else the contract's flat rate.

        A schedule without tiers (the older shape, ``{"per_claim_percent": 5}``)
        is not a policy, and the contract's own rate stands. A schedule whose
        tiers cannot be read refuses with 422 rather than falling back, so a
        policy nobody can apply is never replaced by a flat rate in silence.
        """
        for schedule in await self._retention_schedules(contract):
            rule = schedule.accrual_rule if isinstance(schedule.accrual_rule, dict) else {}
            if not rule.get("tiers"):
                continue
            try:
                return policy_from_rule(rule, fallback_rate=contract.retention_percent or 0)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "retention_policy_unreadable",
                        "message": f"The retention schedule of this contract cannot be applied: {exc}",
                        "retention_schedule_id": str(schedule.id),
                    },
                ) from exc
        return flat_policy(getattr(contract, "retention_percent", 0) or 0)

    async def _progress_billing(self, contract: Contract) -> dict[str, Any] | None:
        """The progress billing block of the project's national pack, or None when none answers."""
        from app.core.regional_packs import resolve_progress_billing  # noqa: PLC0415
        from app.modules.projects.models import Project  # noqa: PLC0415

        project = await self.session.get(Project, contract.project_id)
        if project is None:
            return None
        return resolve_progress_billing(
            country_code=getattr(project, "country_code", None),
            region=getattr(project, "region", None),
        )

    async def retention_release_rule(self, contract: Contract) -> tuple[dict[str, Any], str]:
        """What each release event pays, and where that came from.

        The contract's own schedule first, when its ``release_rule`` lists
        events; the older ``{"on_event": ...}`` shape names an event and no
        amount, so it falls through. Then the project's national pack. Then
        :data:`DEFAULT_RELEASE_RULE`, labelled as the default so nobody reads
        it as the law of the country.
        """
        for schedule in await self._retention_schedules(contract):
            rule = schedule.release_rule if isinstance(schedule.release_rule, dict) else {}
            if isinstance(rule.get("events"), list) and rule["events"]:
                return rule, RELEASE_RULE_FROM_SCHEDULE
        billing = await self._progress_billing(contract)
        pack_rule = (billing or {}).get("release_events")
        if isinstance(pack_rule, dict) and pack_rule.get("events"):
            return pack_rule, RELEASE_RULE_FROM_PACK
        return DEFAULT_RELEASE_RULE, RELEASE_RULE_DEFAULT

    @staticmethod
    def _line_work_to_date(line: Any) -> Decimal:
        """Work completed to date on a claim line, G703 D plus E, added the way the sheet adds them."""
        period = Decimal(str(getattr(line, "period_completed_value", 0) or 0))
        prior = getattr(line, "prior_completed_value", None)
        if prior not in (None, ""):
            return Decimal(str(prior)) + period
        cumulative = Decimal(str(getattr(line, "cumulative_completed_value", 0) or 0))
        return max(cumulative - period, DEC_ZERO) + period

    def _uses_flat_retention(self, contract: Contract, claim: ProgressClaim, lines: list[Any]) -> bool:
        """Cost-plus and T&M claims, and a claim that carries a gross with no lines behind it.

        Those keep the flat retention their generator worked out: there is no
        schedule of values for the engine to measure percent complete on.

        The lineless claim is held at the contract's flat retention percent
        even where a retention schedule sets a ladder, because the ladder
        measures percent complete on schedule lines and this money is on none
        of them (see the flat branch of :meth:`roll_claim_retention`).
        """
        if contract.contract_type in FLAT_RETENTION_CONTRACT_TYPES:
            return True
        return not lines and Decimal(str(claim.gross_amount or 0)) != DEC_ZERO

    async def claim_retention_figures(
        self,
        claim: ProgressClaim,
        *,
        contract: Contract | None = None,
        lines: list[Any] | None = None,
    ) -> ClaimRetention | None:
        """What a claim's payment application should print for retention, worked out now.

        ``lines`` replaces the claim's stored lines, for a preview of lines not
        written yet. None for a claim on flat retention (see
        :meth:`_uses_flat_retention`).

        Work to date per SoV line is the claim's own line where it has one and
        what the earlier claims billed where it has not, so a claim that bills
        only a release still measures the whole contract.

        Everything here measures the schedule, on both sides of the accrual.
        What the policy requires is worked out on schedule lines, so what the
        earlier claims already accrued is taken on schedule lines too: the
        retention they held on money no line of theirs carries is left out
        (:meth:`prior_retention_without_schedule_lines`), and so is that
        money's share of the releases (:meth:`outside_schedule_retention_held`).
        It used to measure the schedule's requirement against everything the
        earlier claims held. A month billed with no line behind it then either
        ratcheted into the schedule's held figure, which the sheet then
        printed a second time on the row carrying that month, or was taken off
        this claim's accrual, which under-accrued it. The sheet and the net
        due add that money back on both sides (:meth:`_engine_net_due`).
        """
        contract = contract or await self.get_contract(claim.contract_id)
        if lines is None:
            lines = await self.claim_line_repo.list_for_claim(claim.id)
        if self._uses_flat_retention(contract, claim, lines):
            return None
        policy = await self.retention_policy(contract)
        completed: dict[Any, Decimal] = dict(
            await self.claim_line_repo.prior_period_value_by_line(contract.id, before_claim_id=claim.id)
        )
        stored: dict[Any, Decimal] = {}
        for line in lines:
            completed[line.contract_line_id] = self._line_work_to_date(line)
            stored[line.contract_line_id] = Decimal(str(getattr(line, "materials_stored_value", 0) or 0))
        position = compute_retention(
            completed,
            contract_sum=getattr(contract, "total_value", 0) or 0,
            policy=policy,
            stored_by_line=stored,
        )
        prior = await self.claim_repo.prior_claims(contract.id, before_claim_id=claim.id)
        on_schedule, outside, released = await self._retention_before(claim, contract.id, prior)
        on_schedule = on_schedule.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # claim_retention accrues max(required - before, 0), so the schedule
        # has accrued the larger of the two once this claim is counted.
        released_outside = _release_share_outside_schedule(
            released,
            schedule_pool=max(position.total, on_schedule),
            outside_pool=outside,
        )
        return claim_retention(
            position,
            completed_by_line=completed,
            stored_by_line=stored,
            accrued_before=on_schedule,
            released_to_date=released - released_outside,
        )

    async def roll_claim_retention(
        self,
        claim_id: uuid.UUID,
        *,
        gross_follows_lines: bool = False,
    ) -> ProgressClaim:
        """Work a claim's retention, line 5 and net due out again from what it holds now.

        Run after anything that changes a claim's lines or the releases billed
        on it: generation, populate, a line edited by hand, a release billed or
        voided. Writes the period accrual to ``retention_amount``, lines 4 and
        5 to the certificate snapshot, column I to each line, and net due as
        G702 line 8 (line 6 less the previous certificates), so a release
        billed here is paid with this claim.

        ``gross_follows_lines`` says the caller has just written the claim's
        lines, so the claim's gross is whatever they add up to, an empty set
        included. It matters only on the flat retention path: a cost-plus or
        T&M claim carries a gross with no lines behind it, and a claim whose
        last line was deleted has to reach zero rather than keep the figure
        that line put there.
        """
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        contract = await self.get_contract(claim.contract_id)
        prior_certified, _basis = await self.previous_certificates(claim)
        lines = await self.claim_line_repo.list_for_claim(claim.id)
        figures = await self.claim_retention_figures(claim, contract=contract, lines=lines)
        if figures is None:
            # Flat retention stands; a release billed here is paid on top of
            # this period's net.
            #
            # Gross is read back from the lines whenever they are what the
            # claim is made of, because this method runs after a line was
            # edited by hand and the stored figure is the one that edit made
            # wrong. A cost-plus or T&M claim generated from costs carries a
            # gross with nothing to add up, and keeps it.
            gross = Decimal(str(claim.gross_amount or 0))
            # A claim that recorded a cost basis keeps its figures whatever
            # lines it has. Its lines are a breakdown somebody typed against a
            # gross that came from costs, not the thing the gross is made of,
            # and summing them replaces a measured fifty thousand with the
            # value of one hand-written row. This is the only place the basis
            # is read; every other caller of this method is unaffected because
            # a claim made of lines records "lines" and a claim written before
            # the column existed records nothing and behaves as it always did.
            if (lines or gross_follows_lines) and claim.gross_basis != "cost":
                gross = sum((Decimal(str(line.period_completed_value or 0)) for line in lines), DEC_ZERO)
            # Retention is derived from the gross and the contract's rate here
            # rather than read back off the claim. It used to be preserved
            # whenever the gross was, which is the same number for every claim
            # any current writer produces, because every generator computes it
            # with this formula. What it is not is a guarantee: a future writer
            # that sets a gross and forgets the retention would have billed the
            # whole gross with nothing held and said nothing about it, in the
            # direction of paying out too much. The ladder branch below already
            # restates retention in full, so the flat branch preserving it was
            # the odd one out rather than a decision.
            #
            # The rate is the contract's own flat percentage, and that holds
            # for a claim with a gross and no lines on a contract whose
            # retention the engine otherwise works out, on a ladder too. That
            # is a decision, not a gap. A ladder is a rate against percent
            # complete on the schedule of values, and money no schedule line
            # carries is not on that measure: whether the ladder has stepped
            # down says nothing about it. So it is held at the rate the
            # contract states, even past the point where the ladder has
            # stopped retaining on the schedule, and the certificate carries
            # it on a row of its own that a release pays back like any other
            # retention (outside_schedule_retention_held).
            rate = Decimal(str(getattr(contract, "retention_percent", 0) or 0))
            retention = (gross * rate / DEC_HUNDRED).quantize(Decimal("0.0001"))
            billed_here = await self.release_repo.billed_on_claims([claim.id])
            released_here = sum((Decimal(str(r.amount or 0)) for r in billed_here), DEC_ZERO)
            net = gross - retention + released_here
            await self.claim_repo.update_fields(
                claim.id,
                gross_amount=gross,
                retention_amount=retention,
                prior_claims_total=prior_certified,
                net_due=max(net, DEC_ZERO),
            )
            await self.session.refresh(claim)
            return claim

        for line in lines:
            share = figures.lines.get(line.contract_line_id)
            if share is None:
                continue
            await self.claim_line_repo.update_fields(
                line.id,
                retention_to_date=share.retention_to_date,
                retention_stored_to_date=share.retention_stored_to_date,
                retention_rate=share.retention_rate,
            )
        gross = sum((Decimal(str(line.period_completed_value or 0)) for line in lines), DEC_ZERO)
        net = await self._engine_net_due(claim, contract, figures, prior_certified)
        await self.claim_repo.update_fields(
            claim.id,
            gross_amount=gross,
            retention_amount=figures.accrual,
            prior_claims_total=prior_certified,
            net_due=net.quantize(Decimal("0.0001")),
            completed_stored_to_date=figures.completed_stored_to_date,
            retention_held_to_date=figures.held,
        )
        await self._propose_step_down(contract, claim, figures)
        await self.session.refresh(claim)
        return claim

    async def _propose_step_down(self, contract: Contract, claim: ProgressClaim, figures: ClaimRetention) -> None:
        """Propose the release a recompute-mode rate reduction frees, once per claim.

        Nothing is paid until a person approves it, because in the US a
        reduction needs the surety's consent where there is a bond. The
        proposal follows the claim: regenerating it resizes the proposal, and
        a claim that no longer crosses the threshold voids it. One already
        approved or billed is left alone.
        """
        policy = await self.retention_policy(contract)
        if policy.tier_mode != "recompute":
            return
        contract_sum = Decimal(str(getattr(contract, "total_value", 0) or 0))
        prior_work = sum(
            (
                value
                for value in (
                    await self.claim_line_repo.prior_period_value_by_line(contract.id, before_claim_id=claim.id)
                ).values()
            ),
            DEC_ZERO,
        )
        rate_before = policy.rate_at(retention_percent_complete(prior_work, contract_sum))
        amount = step_down_release(
            policy,
            held_before=figures.held,
            required_now=figures.position.total,
            rate_before=rate_before,
            rate_now=figures.position.rate_now,
        )
        mine = [
            row
            for row in await self.release_repo.list_for_contract(contract.id)
            if row.event == "rate_step_down" and (row.metadata_ or {}).get("proposed_for_claim_id") == str(claim.id)
        ]
        if any(row.status in ("approved", "billed") for row in mine):
            return
        live = [row for row in mine if row.status == "proposed"]
        if amount <= DEC_ZERO:
            for row in live:
                await self.release_repo.update_fields(row.id, status="void")
            return
        if live:
            await self.release_repo.update_fields(live[0].id, amount=amount)
            return
        rule, source = await self.retention_release_rule(contract)
        spec = release_spec(rule, "rate_step_down") or {}
        await self.release_repo.create(
            RetentionRelease(
                contract_id=contract.id,
                event="rate_step_down",
                status="proposed",
                amount=amount,
                withheld_for_open_items=DEC_ZERO,
                document_ids=[],
                metadata_={
                    "proposed_for_claim_id": str(claim.id),
                    "rate_before": str(rate_before),
                    "rate_now": str(figures.position.rate_now),
                    "rule_source": source,
                    "required_documents": list(spec.get("required_documents") or []),
                    "required_documents_when_bonded": list(spec.get("required_documents_when_bonded") or []),
                    "statute_reference": spec.get("statute_reference"),
                },
            )
        )

    @staticmethod
    def _legacy_releases(contract: Contract) -> list[dict[str, Any]]:
        """Releases logged in ``metadata['retention_releases']`` before RetentionRelease existed."""
        meta = contract.metadata_ if isinstance(contract.metadata_, dict) else {}
        return [entry for entry in meta.get("retention_releases") or [] if isinstance(entry, dict)]

    async def retention_summary(self, contract: Contract) -> dict[str, Any]:
        """Retention on a contract: accrued, paid back, committed to a release, and free to release.

        ``accrued`` is the retention the approved, certified and paid claims
        hold. ``released`` is what went back: releases billed on such a claim,
        and the older metadata log. ``pending_release`` is every other release
        that is not void (proposed, approved, or billed on a claim nobody has
        approved yet), so two releases cannot both be planned from the same
        money.
        """
        accrued = await self.claim_repo.outstanding_retention(contract.id)
        status_by_claim = {c.id: c.status for c in await self.claim_repo.ordered_for_contract(contract.id)}
        released = sum(
            (Decimal(str(entry.get("amount_released", 0) or 0)) for entry in self._legacy_releases(contract)),
            DEC_ZERO,
        )
        pending = DEC_ZERO
        rows = await self.release_repo.list_for_contract(contract.id)
        for row in rows:
            if row.status == "void":
                continue
            amount = Decimal(str(row.amount or 0))
            if row.status == "billed" and status_by_claim.get(row.progress_claim_id) in RETENTION_CERTIFIED_STATUSES:
                released += amount
            else:
                pending += amount
        held = accrued - released
        return {
            "contract_id": contract.id,
            "currency": contract.currency or "",
            "accrued": accrued,
            "released": released,
            "held": held,
            "pending_release": pending,
            "available_for_release": max(held - pending, DEC_ZERO),
            "releases": rows,
        }

    async def _open_items(self, contract: Contract) -> dict[str, Any]:
        """The open punch items on the contract's project and what they are estimated to cost.

        Only items costed in the contract's currency are added up; the others
        are counted as without a cost, so the preview can say the withholding
        does not see them. Without the punch list module the answer is
        ``unavailable``, never zero open items.
        """
        try:
            from sqlalchemy import select  # noqa: PLC0415

            from app.modules.punchlist.intl import DONE_STATUSES  # noqa: PLC0415
            from app.modules.punchlist.models import PunchItem  # noqa: PLC0415
        except ImportError:
            return {"value": DEC_ZERO, "count": 0, "without_cost": 0, "source": "unavailable"}
        result = await self.session.execute(
            select(PunchItem).where(
                PunchItem.project_id == contract.project_id,
                PunchItem.status.notin_(tuple(DONE_STATUSES)),
            )
        )
        currency = (contract.currency or "").upper()
        value, count, without_cost = DEC_ZERO, 0, 0
        for item in result.scalars().all():
            count += 1
            item_currency = (item.rework_cost_currency or "").upper()
            try:
                cost = Decimal(str(item.rework_cost)) if item.rework_cost not in (None, "") else None
            except (InvalidOperation, ValueError):
                cost = None
            if cost is None or (currency and item_currency != currency):
                without_cost += 1
                continue
            value += cost
        return {"value": value, "count": count, "without_cost": without_cost, "source": "punch_list"}

    async def _contract_is_bonded(self, contract: Contract) -> bool:
        """True when a performance or payment bond is active on the contract."""
        for kind in RETAINAGE_BOND_TYPES:
            if await self.security_repo.has_active_of_type(contract.id, kind):
                return True
        return False

    async def _event_already_released(self, contract: Contract, event: str) -> bool:
        """A completion event releases once; a step-down or a substituted bond may recur."""
        if event not in CANONICAL_RELEASE_EVENTS:
            return False
        if any(canonical_release_event(entry.get("event")) == event for entry in self._legacy_releases(contract)):
            return True
        return any(
            row.status != "void" and canonical_release_event(row.event) == event
            for row in await self.release_repo.list_for_contract(contract.id)
        )

    async def preview_retention_release(
        self,
        contract_id: uuid.UUID,
        data: Any,
        *,
        release_rule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """What a release for ``data.event`` would pay; writes nothing.

        The amount is the rule's percentage of the retention held and not yet
        committed to another release, less the open punch items at the rule's
        multiple (in the US, 100% at substantial completion less 1.5 times
        the open items). ``release_rule`` replaces the rule the contract would
        use, for the older endpoint's custom schedule.
        """
        contract = await self.get_contract(contract_id)
        event = canonical_release_event(data.event)
        if event not in RELEASE_ROW_EVENTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "unknown_release_event",
                    "message": f"{data.event!r} is not a retention release event",
                    "event": data.event,
                },
            )
        summary = await self.retention_summary(contract)
        held = summary["available_for_release"]
        if release_rule is not None:
            rule, source = release_rule, RELEASE_RULE_FROM_REQUEST
        else:
            rule, source = await self.retention_release_rule(contract)
        if data.open_items_value is not None:
            items: dict[str, Any] = {
                "value": Decimal(str(data.open_items_value)),
                "count": 0,
                "without_cost": 0,
                "source": "request",
            }
        else:
            items = await self._open_items(contract)
        try:
            plan = plan_release(held, event, rule, open_items_value=items["value"], amount=data.amount)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "release_amount_required", "message": str(exc), "event": event},
            ) from exc
        bonded = await self._contract_is_bonded(contract)
        required = list(
            dict.fromkeys([*plan.required_documents, *(plan.required_documents_when_bonded if bonded else ())])
        )
        return {
            "contract_id": contract.id,
            "event": event,
            "currency": contract.currency or "",
            "held": plan.held,
            "percent_of_held": plan.percent_of_held,
            "open_items_value": Decimal(str(items["value"])),
            "open_items_count": items["count"],
            "open_items_without_cost": items["without_cost"],
            "open_items_source": items["source"],
            "withheld_for_open_items": plan.withheld_for_open_items,
            "amount": plan.amount,
            "remaining": plan.remaining,
            "rule_source": source,
            "statute_reference": plan.statute_reference,
            "required_documents": required,
            "required_documents_when_bonded": list(plan.required_documents_when_bonded),
            "bonded": bonded,
            "already_released": await self._event_already_released(contract, event),
        }

    async def _contract_document_ids(self, contract: Contract, ids: list[Any]) -> list[str]:
        """``ids`` as strings, refused with 422 unless each is a document registered on this contract."""
        wanted = list(dict.fromkeys(str(i) for i in ids or []))
        if not wanted:
            return []
        known = {str(doc.id) for doc in await self.document_repo.list_for_contract(contract.id)}
        unknown = [i for i in wanted if i not in known]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "document_not_on_contract",
                    "message": "Attach documents registered on this contract",
                    "document_ids": unknown,
                },
            )
        return wanted

    async def _get_release(self, release_id: uuid.UUID) -> RetentionRelease:
        row = await self.release_repo.get_by_id(release_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "release_not_found", "message": "Retention release not found"},
            )
        return row

    async def create_retention_release(
        self,
        contract_id: uuid.UUID,
        data: Any,
        actor_id: str | None = None,
        *,
        release_rule: dict[str, Any] | None = None,
    ) -> RetentionRelease:
        """Propose a release sized by :meth:`preview_retention_release`.

        It pays nothing yet: it is approved once the documents the event needs
        are attached, and paid when it is billed on a claim. A completion event
        releases once (409 on a second one); a release of nothing is refused.
        """
        contract = await self.get_contract(contract_id)
        if contract.status not in ("active", "suspended", "completed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "contract_not_releasable",
                    "message": f"Retention cannot be released on a contract in status {contract.status!r}",
                    "contract_status": contract.status,
                },
            )
        preview = await self.preview_retention_release(contract_id, data, release_rule=release_rule)
        if preview["already_released"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "retention_event_already_released",
                    "message": (
                        f"Retention has already been released for {preview['event']!r}; "
                        "void that release first to propose it again"
                    ),
                    "event": preview["event"],
                },
            )
        if preview["amount"] <= DEC_ZERO:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "nothing_to_release",
                    "message": "No retention is left to release for this event",
                    "held": str(preview["held"]),
                    "withheld_for_open_items": str(preview["withheld_for_open_items"]),
                },
            )
        document_ids = await self._contract_document_ids(contract, getattr(data, "document_ids", []))
        row = await self.release_repo.create(
            RetentionRelease(
                contract_id=contract.id,
                event=preview["event"],
                status="proposed",
                amount=preview["amount"],
                withheld_for_open_items=preview["withheld_for_open_items"],
                released_on=getattr(data, "released_on", None),
                document_ids=document_ids,
                created_by=actor_id,
                metadata_={
                    "held_at_proposal": str(preview["held"]),
                    "percent_of_held": None if preview["percent_of_held"] is None else str(preview["percent_of_held"]),
                    "open_items_value": str(preview["open_items_value"]),
                    "open_items_source": preview["open_items_source"],
                    "rule_source": preview["rule_source"],
                    "statute_reference": preview["statute_reference"],
                    "required_documents": [
                        d for d in preview["required_documents"] if d not in preview["required_documents_when_bonded"]
                    ],
                    "required_documents_when_bonded": preview["required_documents_when_bonded"],
                    "notes": getattr(data, "notes", None),
                },
            )
        )
        event_bus.publish_detached(
            "contracts.retention.release_proposed",
            data={
                "contract_id": str(contract.id),
                "release_id": str(row.id),
                "event": row.event,
                "amount": str(row.amount),
                "actor": actor_id,
            },
            source_module="contracts",
        )
        return row

    async def retention_release_context(
        self,
        contract: Contract,
        row: RetentionRelease,
        document_ids: list[str],
    ) -> dict[str, Any]:
        """The plain dict the ``retention_release`` rules read."""
        meta = row.metadata_ or {}
        required = list(meta.get("required_documents") or [])
        if await self._contract_is_bonded(contract):
            required += list(meta.get("required_documents_when_bonded") or [])
        wanted = set(document_ids)
        documents = [
            {"id": str(doc.id), "doc_role": doc.doc_role, "title": doc.title or ""}
            for doc in await self.document_repo.list_for_contract(contract.id)
            if str(doc.id) in wanted
        ]
        summary = await self.retention_summary(contract)
        # This release is in pending already; what it may take is what is
        # free plus its own share.
        own = DEC_ZERO if row.status == "void" else Decimal(str(row.amount or 0))
        return {
            "release": {"id": str(row.id), "event": row.event, "status": row.status, "amount": str(row.amount)},
            "currency": contract.currency or "",
            "available": str(summary["available_for_release"] + own),
            "required_documents": list(dict.fromkeys(required)),
            "documents": documents,
        }

    async def approve_retention_release(
        self,
        release_id: uuid.UUID,
        data: Any,
        actor_id: str | None = None,
    ) -> RetentionRelease:
        """Approve a proposed release once the ``retention_release`` rules pass.

        Every ERROR blocks: a document the event needs that is not attached,
        or an amount above the retention still free to release.
        """
        from app.modules.contracts.messages import translate as contracts_translate  # noqa: PLC0415
        from app.modules.contracts.validators import RETENTION_RELEASE_RULE_SET  # noqa: PLC0415

        row = await self._get_release(release_id)
        if row.status != "proposed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "release_not_proposed",
                    "message": f"Only a proposed release can be approved; this one is {row.status!r}",
                    "status": row.status,
                },
            )
        contract = await self.get_contract(row.contract_id)
        document_ids = await self._contract_document_ids(
            contract, [*(row.document_ids or []), *(getattr(data, "document_ids", None) or [])]
        )
        locale = get_locale()
        report = await validation_engine.validate(
            data=await self.retention_release_context(contract, row, document_ids),
            rule_sets=[RETENTION_RELEASE_RULE_SET],
            target_type="retention_release",
            target_id=str(row.id),
            project_id=str(contract.project_id),
            metadata={"locale": locale, "workflow": "retention_release_approval"},
        )
        if RETENTION_RELEASE_RULE_SET in report.unsupported_rule_sets:
            logger.error(
                "contracts: rule set %s is not registered; release gate cannot run", RETENTION_RELEASE_RULE_SET
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=contracts_translate("retention_release.errors.rules_unavailable", locale=locale),
            )
        if report.has_errors:
            heads = "; ".join(r.message for r in report.errors[:3])
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=self._compliance_http_detail(
                    report,
                    [],
                    message=contracts_translate(
                        "retention_release.errors.approval_blocked", locale=locale, findings=heads
                    ),
                ),
            )
        from datetime import UTC, datetime  # noqa: PLC0415

        meta = dict(row.metadata_ or {})
        meta["approved_by"] = actor_id
        meta["approved_at"] = datetime.now(UTC).isoformat()
        await self.release_repo.update_fields(row.id, status="approved", document_ids=document_ids, metadata_=meta)
        await self.session.refresh(row)
        return row

    async def bill_retention_release(
        self,
        release_id: uuid.UUID,
        data: Any,
        actor_id: str | None = None,
    ) -> RetentionRelease:
        """Bill an approved release on a draft claim of the same contract, and re-work that claim.

        The claim's line 5 goes down by the release and its net due goes up by
        it; the release is paid when the claim is.
        """
        row = await self._get_release(release_id)
        if row.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "release_not_approved",
                    "message": f"Only an approved release can be billed; this one is {row.status!r}",
                    "status": row.status,
                },
            )
        claim = await self.claim_repo.get_by_id(data.progress_claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
        if claim.contract_id != row.contract_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "claim_on_other_contract",
                    "message": "A release is billed on a claim of its own contract",
                },
            )
        self._assert_claim_editable(claim)
        meta = dict(row.metadata_ or {})
        meta["billed_by"] = actor_id
        await self.release_repo.update_fields(
            row.id,
            status="billed",
            progress_claim_id=claim.id,
            released_on=row.released_on or claim.period_to,
            metadata_=meta,
        )
        await self.roll_claim_retention(claim.id)
        await self.session.refresh(row)
        return row

    async def void_retention_release(self, release_id: uuid.UUID, actor_id: str | None = None) -> RetentionRelease:
        """Void a release. One billed on a claim that can still be edited is taken off it first."""
        row = await self._get_release(release_id)
        if row.status == "void":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "release_already_void", "message": "This release is already void"},
            )
        claim_id = row.progress_claim_id if row.status == "billed" else None
        if claim_id is not None:
            claim = await self.claim_repo.get_by_id(claim_id)
            if claim is not None and claim.status not in self._CLAIM_EDITABLE_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "release_billed_on_locked_claim",
                        "message": (
                            f"This release is billed on claim {claim.claim_number or claim.id}, which is "
                            f"{claim.status!r}; a release that was paid cannot be voided"
                        ),
                        "claim_status": claim.status,
                    },
                )
        from datetime import UTC, datetime  # noqa: PLC0415

        meta = dict(row.metadata_ or {})
        meta["voided_by"] = actor_id
        meta["voided_at"] = datetime.now(UTC).isoformat()
        if claim_id is not None:
            meta["billed_on_claim_id"] = str(claim_id)
        await self.release_repo.update_fields(row.id, status="void", progress_claim_id=None, metadata_=meta)
        if claim_id is not None and await self.claim_repo.get_by_id(claim_id) is not None:
            await self.roll_claim_retention(claim_id)
        await self.session.refresh(row)
        return row

    async def release_retention(
        self,
        contract_id: uuid.UUID,
        event: str,
        *,
        custom_schedule: dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Propose a retention release for ``event``; the older endpoint's shape.

        It used to append to ``contract.metadata['retention_releases']`` and
        count the money as released at once, with no documents and no claim
        to bill it on. It now proposes a :class:`RetentionRelease` like the
        release endpoints do, and the answer says so (``status`` and
        ``release_id``). ``custom_schedule`` maps events to a percentage of
        the retention held and replaces the contract's rule for this call.
        """
        rule: dict[str, Any] | None = None
        if custom_schedule is not None:
            events: list[dict[str, Any]] = []
            for key, val in custom_schedule.items():
                try:
                    pct = Decimal(str(val))
                except (ArithmeticError, ValueError):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "invalid_custom_schedule",
                            "message": f"custom_schedule[{key!r}] must be numeric, got {val!r}",
                        },
                    ) from None
                if pct < DEC_ZERO or pct > DEC_HUNDRED:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "invalid_custom_schedule",
                            "message": f"custom_schedule[{key!r}] must be between 0 and 100, got {val!r}",
                        },
                    )
                events.append({"event": canonical_release_event(key), "release_percent_of_held": str(pct)})
            rule = {"events": events}
        row = await self.create_retention_release(
            contract_id,
            SimpleNamespace(event=event, amount=None, open_items_value=None, document_ids=[], notes=None),
            actor_id,
            release_rule=rule,
        )
        meta = row.metadata_ or {}
        held = Decimal(str(meta.get("held_at_proposal") or 0))
        return {
            "contract_id": str(contract_id),
            "release_id": str(row.id),
            "status": row.status,
            "event": row.event,
            "amount_released": str(row.amount),
            "percent_released": str(meta.get("percent_of_held") or ""),
            "remaining": str(held - Decimal(str(row.amount))),
            "total_held_before": str(held),
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
        # Held is what the owner still keeps: accrued less what was paid back.
        accrued, released = await self._retention_ledger(contract)
        retention = accrued - released
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
        change_orders_count, change_orders_net = self._change_order_rollup(contract)

        # Commercial breakdown (PR-14 / PR-15 of issue #435).
        original = contract.original_contract_value
        current_value = Decimal(str(contract.total_value or 0))
        agreed_variations = change_orders_net

        # Pending variations: sum of VR cost impacts that are submitted or
        # under review but not yet approved.  This is a cross-module query
        # that tolerates the variations module being absent.
        pending_variations = DEC_ZERO
        try:
            from sqlalchemy import func, select

            from app.modules.variations.models import VariationRequest

            row = (
                await self.session.execute(
                    select(func.coalesce(func.sum(VariationRequest.estimated_cost_impact), 0)).where(
                        VariationRequest.project_id == contract.project_id,
                        VariationRequest.status.in_(("submitted", "under_review")),
                    )
                )
            ).scalar_one()
            pending_variations = Decimal(str(row or 0))
        except (ImportError, Exception):
            pass

        forecast = current_value + pending_variations

        return {
            "contract_id": contract_id,
            "total_value": current_value,
            "original_contract_value": original,
            "agreed_variations": agreed_variations,
            "current_contract_value": current_value,
            "pending_variations": pending_variations,
            "forecast_contract_value": forecast,
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
        less the releases paid back (:meth:`_retention_ledger`).
        """
        if final_account is not None:
            return (
                Decimal(str(final_account.retention_held or 0)),
                Decimal(str(final_account.retention_released or 0)),
            )
        return await self._retention_ledger(contract)

    async def _retention_ledger(self, contract: Contract) -> tuple[Decimal, Decimal]:
        """Retention accrued on approved / certified / paid claims, and what was paid back of it.

        Paid back is a release billed on such a claim, plus the older metadata
        log; see :meth:`retention_summary`.
        """
        summary = await self.retention_summary(contract)
        return summary["accrued"], summary["released"]

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

    async def build_aia_application(self, claim_id: uuid.UUID, *, locale: str | None = None) -> dict[str, Any]:
        """Assemble the AIA G702 summary + G703 continuation for one claim.

        Reuses the existing SoV lines (``ContractLine``) and the claim's lines
        (``ProgressClaimLine``); does not recompute the claim FSM or retention
        accrual. Line 5 and column I are the claim's retention snapshot when
        the engine has worked it out, else the contract's flat rate. Country-gated by the caller via
        :meth:`assert_contract_aia_eligible`. Single-currency by construction
        (the claim inherits the contract currency); no currency is ever blended.

        ``locale`` is the language the application is read in, and the one
        string written here, the description of the row for money no schedule
        line carries, follows it. It defaults to the request's language, which
        is what the screen shows every other label in. The printed form is
        drawn from English literals and declares itself English, so its route
        passes ``"en"`` and the row reads in the same language as the rest of
        the page.
        """
        from app.modules.contracts.aia import (  # noqa: PLC0415
            apply_retention_snapshot,
            bills_without_schedule,
            build_cost_of_work_row,
            build_g702_summary,
            build_g703,
            sheet_sov_lines,
        )
        from app.modules.contracts.messages import translate as contracts_translate  # noqa: PLC0415

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

        # G702 line 7: what the claims before this one certified, each net of
        # the retention it held. Worked out by the service rather than here so
        # every country's application reads the same figure.
        previous_certificates_total, previous_certificates_basis = await self.previous_certificates(claim)

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

        retainage_percent = Decimal(str(contract.retention_percent or 0))
        prior_by_line = await self.claim_line_repo.prior_period_value_by_line(contract.id, before_claim_id=claim.id)
        # Both branches need the prior claims, so they are read once. The two
        # calls answer the same population: prior_period_value_by_line resolves
        # "prior" through this very method, rejected claims left out.
        prior_claims = await self.claim_repo.prior_claims(contract.id, before_claim_id=claim.id)
        if bills_without_schedule(claim, claim_lines):
            # The claim's own figures go on a single cost-of-work row. What
            # makes a claim this shape is decided once, in aia.py, because
            # certification freezes the same two figures the sheet prints.
            held = (
                Decimal(str(claim.retention_held_to_date))
                if claim.retention_held_to_date is not None
                else sum((Decimal(str(c.retention_amount or 0)) for c in prior_claims), DEC_ZERO)
                + Decimal(str(claim.retention_amount or 0))
            )
            g703 = [
                build_cost_of_work_row(
                    item_number=contract.code or "1",
                    description=contract.title or "",
                    scheduled=original_contract_sum + change_orders_net,
                    previous=sum((Decimal(str(c.gross_amount or 0)) for c in prior_claims), DEC_ZERO),
                    this_period=Decimal(str(claim.gross_amount or 0)),
                    retainage=held,
                )
            ]
        else:
            # What earlier claims billed that no line of their own carries.
            # Column D here is assembled from claim lines, so that money is
            # invisible to it while line 7 still carries its certificate, and
            # line 8 then subtracts a certificate the columns never added.
            #
            # Asked of the one method that defines it, which is also what
            # previous_certificates consults before it trusts a snapshot. The
            # sheet and line 7 therefore cannot end up with two answers to the
            # same question, which is how this defect stayed hidden: line 4 and
            # line 7 were wrong by the same amount and cancelled.
            prior_without_schedule = await self.prior_gross_without_schedule_lines(
                contract.id,
                before_claim_id=claim.id,
                prior_claims=prior_claims,
            )
            # Column I on that row: what the earlier claims actually held on
            # that money, less its share of the releases where a release
            # comes off line 5 at all. The same method the net due is worked
            # out with, so the sheet and the claim cannot disagree about it.
            # schedule_accrual is this claim's own accrual as stored, which
            # is what the engine accrued when it last worked the claim out;
            # nothing is worked out again for a claim already certified.
            out_of_schedule_retainage = None
            if prior_without_schedule > DEC_ZERO:
                out_of_schedule_retainage = await self.outside_schedule_retention_held(
                    claim,
                    contract,
                    schedule_accrual=Decimal(str(claim.retention_amount or 0)),
                    releases_come_off_it=(
                        claim.retention_held_to_date is not None
                        and contract.contract_type not in FLAT_RETENTION_CONTRACT_TYPES
                    ),
                    prior_claims=prior_claims,
                )
            # Which lines the sheet lists, roll-up parents excluded, is decided
            # once in aia.py so this and the certification freeze cannot drift.
            sov_lines = sheet_sov_lines(contract_lines, by_contract_line, prior_by_line)
            g703 = build_g703(
                sov_lines,
                by_contract_line,
                retainage_percent=retainage_percent,
                prior_by_line=prior_by_line,
                prior_without_schedule=prior_without_schedule,
                out_of_schedule_retainage=out_of_schedule_retainage,
                out_of_schedule_label=contracts_translate(
                    "aia.g703.billed_not_on_a_schedule_line",
                    locale=locale or get_locale(),
                ),
            )
            if claim.retention_held_to_date is not None:
                # Worked out by the retention engine: column I and line 5 are the
                # claim's certified figures, with any release billed on it taken off.
                #
                # Only the schedule rows are handed over, which is also why the
                # two lists stay the same length. That stored line 5 measures
                # the schedule and nothing else, so putting the out-of-schedule
                # row in front of it spreads the row's own retainage back into
                # the same total and loses the retention held on the month it
                # carries: line 5 then under-states by exactly that, and line 8
                # over-pays by it. The slice is shallow and the snapshot writes
                # through to the row dictionaries the sheet keeps.
                apply_retention_snapshot(
                    g703[: len(sov_lines)],
                    sov_lines,
                    by_contract_line,
                    held=claim.retention_held_to_date,
                )

        g702 = build_g702_summary(
            g703,
            original_contract_sum=original_contract_sum,
            change_orders_net=change_orders_net,
            previous_certificates_total=previous_certificates_total,
            previous_certificates_basis=previous_certificates_basis,
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
    "PERCENT_REGRESSED_META_KEY",
    "PREVIOUS_CERTIFICATES_RECONSTRUCTED",
    "PREVIOUS_CERTIFICATES_SNAPSHOT",
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
    "claim_line_percent_regressed",
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
    claim_lines: list[tuple[Any, Any]],
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

    ``claim_lines`` is a list of ``(claim_line, claim)`` pairs. The status and
    the billing order are read from the claim, so this stays pure without the
    caller tagging derived values onto the rows it passes in.

    Retention is read from the claims rather than recomputed. Each claim line
    carries ``retention_to_date``, what its claim certified to date on that
    SoV line, which is the figure the payment application printed;
    :mod:`~app.modules.contracts.aia` already prefers it the same way. The
    figure is cumulative, so the rollup is the latest counted claim's and
    never a sum. Where no claim recorded one, and only there, the contract's
    flat rate is applied to what has been billed, which is what this did for
    every contract before ladders existed.
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

    # The latest claim, in billing order, that recorded a retention figure for
    # a line: one for what has been billed and one for what has been paid,
    # because the two answer different questions and can be different claims.
    latest_billed_retention: dict[str, tuple[Any, Decimal]] = {}
    latest_paid_retention: dict[str, tuple[Any, Decimal]] = {}

    for cl, claim in claim_lines:
        lid = str(getattr(cl, "contract_line_id", "") or "")
        if lid not in by_line:
            continue
        value = Decimal(str(getattr(cl, "period_completed_value", 0) or 0))
        claim_status = (getattr(claim, "status", "") or "").lower()
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

        held = getattr(cl, "retention_to_date", None)
        if held is None:
            # No figure recorded is not a figure of zero. A claim written
            # before these columns existed, or by a route that does not fill
            # them, leaves the line to the flat fallback below.
            continue
        # Ties are possible and have to break the same way every time:
        # claim_number has no unique constraint and defaults to empty, so two
        # claims raised together can match on all three parts of the key. The
        # id is an arbitrary tiebreak but a stable one, and a figure that
        # flips with the row order is worse than one that is merely wrong.
        order = (claim_order_key(claim), str(getattr(claim, "id", "")))
        for bucket, statuses in (
            (latest_billed_retention, ("approved", "certified", "paid")),
            (latest_paid_retention, ("paid",)),
        ):
            if claim_status not in statuses:
                continue
            current = bucket.get(lid)
            if current is None or order > current[0]:
                bucket[lid] = (order, Decimal(str(held)))

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
        recorded = latest_billed_retention.get(lid)
        recorded_paid = latest_paid_retention.get(lid)
        held = recorded[1] if recorded is not None else billed * pct / DEC_HUNDRED
        held_on_paid = recorded_paid[1] if recorded_paid is not None else paid * pct / DEC_HUNDRED
        retained = held.quantize(Decimal("0.0001"))
        net_paid = paid - held_on_paid.quantize(Decimal("0.0001"))
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


# ── Contract clause templates (FIDIC / JCT / AIA / CCDC) ────────────────


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
        "retention_release_event": "defects_period_end",
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
        "retention_release_event": "defects_period_end",
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
        "retention_release_event": "defects_period_end",
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
        "retention_release_event": "substantial_completion",
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
        "retention_release_event": "substantial_completion",
    },
    "jct_minor_works_2016": {
        "name": "JCT Minor Works Building Contract 2016",
        "family": "jct",
        "key_clauses": {
            "4": "Payment",
            "2.8": "Liquidated Damages",
            "3.6": "Variations",
        },
        "retention_release_event": "substantial_completion",
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
        "retention_release_event": "substantial_completion",
    },
    "nec4_ecc_option_c": {
        "name": "NEC4 ECC - Option C (Target Contract)",
        "family": "nec",
        "key_clauses": {
            "5": "Payment",
            "53": "Pain / Gain Share",
            "60": "Compensation Events",
        },
        "retention_release_event": "substantial_completion",
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
    "ccdc_2_2020": {
        "name": "CCDC 2-2020 - Stipulated Price Contract",
        "family": "ccdc",
        "key_clauses": {
            "GC 5.3": "Progress Payment",
            "GC 5.7": "Final Payment",
            "GC 6.1": "Owner's Right to Make Changes",
            "GC 6.3": "Change Order",
            "GC 6.5": "Delay in Performance",
            "GC 6.6": "Claims for a Change in Contract Price",
            "GC 7.1": "Owner's Right to Perform, Correct or Terminate",
            "GC 12.1": "Dispute Resolution",
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
