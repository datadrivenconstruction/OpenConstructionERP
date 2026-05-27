"""‌⁠‍Contracts service — business logic for the Contract Types Engine.

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
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.contracts.models import (
    Contract,
    ContractLine,
    FeeStructure,
    FinalAccount,
    GainshareConfiguration,
    LDClause,
    ProgressClaim,
    ProgressClaimLine,
    RetentionSchedule,
)
from app.modules.contracts.repository import (
    ContractLineRepository,
    ContractRepository,
    ContractTypeConfigurationRepository,
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
)

# Type-specific required-keys map. Empty list = no extra required keys.
_REQUIRED_TERM_FIELDS: dict[str, tuple[str, ...]] = {
    "lump_sum": (),
    "gmp": ("gmp_cap", "target_cost"),
    "cost_plus": ("fee_percent",),
    "tm": ("tm_nte_cap",),
    "unit_price": (),
    "design_build": (),
    "combination": (),
}


# ── Custom errors ─────────────────────────────────────────────────────────


class NTECapExceededError(Exception):
    """‌⁠‍Raised when a T&M claim would exceed the not-to-exceed (NTE) cap."""


class InvalidTransitionError(Exception):
    """‌⁠‍Raised when an attempted state transition is not allowed."""


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
            # This line has children — skip to avoid double-counting.
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
    # The synthesised objects above lose attribute access — recompute gross
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
            created_by=user_id,
            metadata_=data.metadata,
        )
        contract = await self.contract_repo.create(contract)
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
    #: audit trail — value changes must go through change orders, status
    #: through the transition endpoints.
    _LOCKED_FINANCIAL_FIELDS = (
        "total_value",
        "retention_percent",
        "currency",
        "contract_type",
        "retention_release_event",
        # Type-specific terms (gmp_cap, target_cost, tm_nte_cap, ld_per_day…)
        # are commercial terms too — freezing total_value but letting the
        # GMP cap be rewritten on a live contract would defeat the lock.
        "terms",
    )

    async def update_contract(self, contract_id: uuid.UUID, data: Any) -> Contract:
        contract = await self.get_contract(contract_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
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
        return contract

    async def delete_contract(self, contract_id: uuid.UUID) -> None:
        await self.get_contract(contract_id)
        await self.contract_repo.delete(contract_id)

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
              method is called — so a manager on project A cannot
              ``clone --target_project_id=<project_B_id>`` and copy
              project A's commercial terms into project B.
            * Manager-or-higher RBAC is enforced at the route level
              via ``RequirePermission("contracts.clone")``.

        Lifecycle invariants:
            * Clone is always materialised in ``draft`` status with
              ``signed_at=None`` regardless of the source's lifecycle
              stage — a cloned contract is a brand-new instrument that
              must be re-signed.
            * Payment history (progress claims, claim lines, final
              accounts, lien-waiver attachments, retention-release
              audit entries) is **never** copied — that ledger belongs
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
            # Pass 2 — wire up parent_line_id translations.
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

    async def transition_contract(
        self,
        contract_id: uuid.UUID,
        target_status: str,
        actor_id: str | None = None,
    ) -> Contract:
        """Apply a status transition with state-machine validation."""
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

            fields["signed_at"] = datetime.now(UTC).isoformat()
            event_bus.publish_detached(
                "contracts.contract.signed",
                data={
                    "contract_id": str(contract.id),
                    "code": contract.code,
                    "project_id": str(contract.project_id),
                    "signed_by": actor_id,
                },
                source_module="contracts",
            )
        await self.contract_repo.update_fields(contract_id, **fields)
        await self.session.refresh(contract)
        return contract

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
            fields["metadata_"] = fields.pop("metadata")
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
        elif contract.contract_type == "unit_price":
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
            # GMP / design_build / combination — default to lump-sum semantics
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
        new_lines: list[ProgressClaimLine] = []
        for cl in result.get("claim_lines", []) or []:
            new_lines.append(
                ProgressClaimLine(
                    progress_claim_id=claim_id,
                    contract_line_id=cl["contract_line_id"],
                    period_completed_qty=Decimal(str(cl["period_completed_qty"])),
                    period_completed_value=Decimal(str(cl["period_completed_value"])),
                    period_completed_pct=Decimal(str(cl["period_completed_pct"])),
                    cumulative_completed_value=Decimal(
                        str(cl["cumulative_completed_value"]),
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
        corrupt the audit trail, and — for ``terminated`` contracts — partially
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
        await self.contract_repo.update_fields(
            contract_id,
            total_value=new_value,
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
        """Close a contract — create / update the FinalAccount + flip status."""
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
        # whatever was left — asymptotically draining retention to zero
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
        return {
            "contract_id": contract_id,
            "total_value": Decimal(str(contract.total_value or 0)),
            "paid_to_date": paid,
            "retention_held": retention,
            "outstanding": outstanding if outstanding > DEC_ZERO else DEC_ZERO,
            "claims_count": total_claims,
            "change_orders_count": 0,  # populated via cross-module query later
            "gainshare_estimate": gainshare_estimate,
            "status": contract.status,
        }


__all__ = [
    "ContractsService",
    "InvalidTransitionError",
    "NTECapExceededError",
    "_REQUIRED_TERM_FIELDS",
    "allowed_claim_transitions",
    "allowed_contract_transitions",
    "allowed_final_account_transitions",
    "apply_change_order_to_contract_pure",
    "assert_claim_transition",
    "assert_contract_transition",
    "assert_final_account_transition",
    "compute_contract_total",
    "compute_gmp_gainshare",
    "compute_ld_amount",
    "compute_line_total",
    "compute_progress_claim_total",
    "generate_cost_plus_claim",
    "generate_lump_sum_claim",
    "generate_tm_claim",
    "generate_unit_price_claim",
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
        "defects_liability_end": 20}`` — values are percentages of
        the *original* retention to release at each event.

    Returns ``{event, percent_released, amount_released, remaining}`` —
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
        "name": "FIDIC Red Book (1999) — Conditions of Contract for Construction",
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
        "name": "FIDIC Yellow Book (1999) — Plant and Design-Build",
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
        "name": "FIDIC Silver Book (1999) — EPC / Turnkey",
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
        "name": "NEC4 Engineering and Construction Contract — Option A (Priced)",
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
        "name": "NEC4 ECC — Option C (Target Contract)",
        "family": "nec",
        "key_clauses": {
            "5": "Payment",
            "53": "Pain / Gain Share",
            "60": "Compensation Events",
        },
        "retention_release_event": "completion",
    },
    "aia_a201_2017": {
        "name": "AIA A201-2017 — General Conditions",
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
        "name": "AIA A102-2017 — Owner & Contractor (Cost-Plus, GMP)",
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
        "name": "ConsensusDocs 200 — Standard Owner / Constructor (Lump Sum)",
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
