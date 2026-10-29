# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure rules of the procurement concept (SPEC section 4). No database, no clock.

Every function takes plain facts and the pinned catalogue and answers
findings ``{code, severity, ref, ...}``. The service builds the facts from
the database; the validation rule set and the API both read these findings,
so a rule cannot say one thing on the screen and another at approval.

Severity: ``error`` blocks approval of the concept; ``warning`` is shown. A
fact the catalogue marks ``unconfirmed`` never yields an error (rule 5).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.procurement_concept.catalogue import (
    CONTRACT_PACKAGE_KIND_MAP,
    LotRule,
    ProcurementCatalogue,
    Threshold,
    parse_amount,
)
from app.modules.project_governance.catalogue import ReviewStatus

ERROR = "error"
WARNING = "warning"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
_CENT = Decimal("0.01")

# Competitions that need a real field of bidders when the procedure names no minimum.
_DEFAULT_MIN_BIDDERS = {"restricted": 3, "negotiated": 3, "dialogue": 3, "innovation_partnership": 3}
DESIGN_BUILD_FORMS = ("design_build", "design_build_novated", "turnkey_epc")
TWO_STAGE_FORMS = ("cm_at_risk", "partnering_two_stage")
SPLIT_FORMS = ("design_bid_build_split",)
MAIN_PACKAGE_KINDS = ("construction", "design_and_construction", "management_services")
SERVICE_CONTRACT_KINDS = ("services", "design_services")


def finding(code: str, severity: str, ref: str, **detail: Any) -> dict[str, Any]:
    """One finding; ``blocks_approval`` defaults to ``severity == error``."""
    out: dict[str, Any] = {"code": code, "severity": severity, "ref": ref}
    out["blocks_approval"] = detail.pop("blocks_approval", severity == ERROR)
    out.update(detail)
    return out


def _sev(*statuses: ReviewStatus | None) -> str:
    return ERROR if all(s == ReviewStatus.verified for s in statuses) else WARNING


@dataclass(frozen=True)
class ConceptFacts:
    jurisdiction: str = "none"
    client_type: str = "private"
    public_client: bool = False
    # VAT rate in percent, used when a threshold is stated gross (UK).
    vat_rate_pct: Decimal = ZERO
    delivery_form: str | None = None


@dataclass(frozen=True)
class PackageFacts:
    """One award package joined with its mod3 ContractPackage."""

    id: str
    code: str
    cp_kind: str
    parent_id: str | None = None
    estimated_value: Decimal | None = None
    currency: str = ""
    lot_group: str = ""
    small_lot_exemption: bool = False
    procedure_code: str | None = None
    tender_basis: str | None = None
    is_advance: bool = False
    advance_reason: str = ""
    advance_released: bool = False
    #: False on a project whose phase model holds procurement behind no gate: there is nothing to be
    #: ahead of, so the flag is a leftover and rule 12 has nothing to ask for.
    advance_applies: bool = True
    framework_agreement_id: str | None = None
    need_date: date | None = None
    lead_time_days: int | None = None
    procedure_days: int | None = None
    planned_start: date | None = None
    state: str = "planned"

    @property
    def package_kind(self) -> str | None:
        return CONTRACT_PACKAGE_KIND_MAP.get(self.cp_kind)


def contract_kind_of(catalogue: ProcurementCatalogue, pkg: PackageFacts) -> str | None:
    """The threshold contract kind of a package (through the catalogue's package kinds)."""
    pk = catalogue.package_kind(pkg.package_kind)
    return pk.contract_kind if pk else None


# ── Thresholds (rules 2-5) ──────────────────────────────────────────────


def applicable_thresholds(
    catalogue: ProcurementCatalogue, facts: ConceptFacts, contract_kind: str | None, day: date
) -> list[Threshold]:
    """Thresholds valid on ``day`` for the concept's jurisdiction, client type and the contract kind.

    Private clients and jurisdiction ``none`` have none (Decision 9).
    """
    if not facts.public_client or contract_kind is None:
        return []
    juris = catalogue.jurisdiction(facts.jurisdiction)
    if juris is None:
        return []
    return [t for t in juris.thresholds if _in_regime(t, facts, contract_kind) and t.valid_on(day)]


def _in_regime(t: Threshold, facts: ConceptFacts, contract_kind: str | None) -> bool:
    return t.contract_kind == contract_kind and t.client_type == facts.client_type


def regime_has_thresholds(catalogue: ProcurementCatalogue, facts: ConceptFacts, contract_kind: str | None) -> bool:
    """Whether the regime has any threshold for this client and contract kind, whatever its validity."""
    if not facts.public_client or contract_kind is None:
        return False
    juris = catalogue.jurisdiction(facts.jurisdiction)
    return juris is not None and any(_in_regime(t, facts, contract_kind) for t in juris.thresholds)


def convert_to_threshold(
    catalogue: ProcurementCatalogue,
    value: Decimal,
    currency: str,
    threshold: Threshold,
    *,
    vat_rate_pct: Decimal,
    day: date,
) -> Decimal | None:
    """``value`` (net, in ``currency``) on the threshold's basis; ``None`` when no rate converts it."""
    out = value
    if threshold.vat_basis == "gross":
        out = out * (HUNDRED + vat_rate_pct) / HUNDRED
    cur = (currency or "").upper()
    if not cur:
        # A value without a currency is not comparable; it is never assumed to be the threshold's currency.
        return None
    if cur != threshold.currency.upper():
        rate = next(
            (
                r
                for r in catalogue.currency_rates
                if r.from_currency.upper() == cur
                and r.to_currency.upper() == threshold.currency.upper()
                and r.valid_on(day)
            ),
            None,
        )
        if rate is None:
            return None
        out = out * parse_amount(rate.rate)
    return out


def aggregation_key(catalogue: ProcurementCatalogue, pkg: PackageFacts) -> tuple[str, str]:
    """Lots that count together (rule 3).

    All works of the project are one group. Supplies and services of the same
    contract kind are one group by default, so an untagged lot is never alone;
    ``lot_group`` narrows that to one kind of supply or service.
    """
    ck = contract_kind_of(catalogue, pkg) or "none"
    if ck == "works":
        return ("works", "")
    return (ck, pkg.lot_group or "")


def aggregated_values(catalogue: ProcurementCatalogue, packages: Sequence[PackageFacts]) -> dict[str, Decimal | None]:
    """Package id -> sum of the estimated values of every live lot in its aggregation group (rule 3).

    Computed, never stored. Currency is not part of the group: a lot in
    another currency would otherwise escape the sum. A group whose valued lots
    do not share one currency (or where one has none) has no sum, ``None``,
    and the threshold check reports it as unresolved.
    """
    sums: dict[tuple[str, str], Decimal] = {}
    currencies: dict[tuple[str, str], set[str]] = {}
    live = [p for p in packages if p.package_kind and p.state != "cancelled"]
    for p in live:
        key = aggregation_key(catalogue, p)
        sums[key] = sums.get(key, ZERO) + (p.estimated_value or ZERO)
        if p.estimated_value is not None:
            currencies.setdefault(key, set()).add((p.currency or "").upper())
    out: dict[str, Decimal | None] = {}
    for p in live:
        key = aggregation_key(catalogue, p)
        cur = currencies.get(key, set())
        out[p.id] = sums[key] if len(cur) <= 1 and "" not in cur else None
    return out


def _small_lot_rule(catalogue: ProcurementCatalogue, facts: ConceptFacts, contract_kind: str) -> LotRule | None:
    juris = catalogue.jurisdiction(facts.jurisdiction)
    if juris is None:
        return None
    for r in juris.lot_rules:
        if r.kind != "small_lots_exemption":
            continue
        if r.contract_kind == contract_kind or (
            r.contract_kind == "supplies" and contract_kind in SERVICE_CONTRACT_KINDS
        ):
            return r
    return None


@dataclass
class ThresholdView:
    """What the package board shows next to a package (badge + explanation)."""

    status: str  # above | below | unconfirmed | unresolved | unavailable | not_applicable
    allowed: list[str] | None = None  # None = no restriction from thresholds
    thresholds: list[dict[str, Any]] = field(default_factory=list)
    single_value: Decimal | None = None
    aggregated_value: Decimal | None = None
    small_lot_exempt: bool = False
    findings: list[dict[str, Any]] = field(default_factory=list)


def threshold_view(
    catalogue: ProcurementCatalogue,
    facts: ConceptFacts,
    pkg: PackageFacts,
    packages: Sequence[PackageFacts],
    day: date,
) -> ThresholdView:
    """The threshold test of one package on ``day`` (the planned procedure start), rules 2 to 5."""
    ck = contract_kind_of(catalogue, pkg)
    rows = applicable_thresholds(catalogue, facts, ck, day)
    if not rows or ck is None:
        if regime_has_thresholds(catalogue, facts, ck):
            # The regime has thresholds for this client and kind but none for this day: a gap in the
            # catalogue, never "no threshold applies".
            return ThresholdView(
                status="unavailable",
                findings=[finding("threshold_not_available_for_date", ERROR, pkg.code, day=day.isoformat())],
            )
        return ThresholdView(status="not_applicable")
    sums = aggregated_values(catalogue, packages)
    agg = sums.get(pkg.id, pkg.estimated_value or ZERO)
    single = pkg.estimated_value or ZERO
    if agg is None:
        return ThresholdView(
            status="unresolved",
            single_value=single,
            findings=[
                finding(
                    "threshold_currency_unresolved",
                    WARNING,
                    pkg.code,
                    reason="lots_in_different_currencies",
                    blocks_approval=facts.public_client,
                )
            ],
        )
    view = ThresholdView(status="below", single_value=single, aggregated_value=agg)

    # Small-lots exemption: only where the catalogue has the rule, within its own cap.
    exempt = False
    exempt_unconfirmed = False
    if pkg.small_lot_exemption:
        rule = _small_lot_rule(catalogue, facts, ck)
        sev = _sev(rule.review_status) if rule else ERROR
        ok = False
        if rule is not None and rule.max_lot_value is not None:
            cap = parse_amount(rule.max_lot_value)
            share = parse_amount(rule.max_share_pct or "0")
            same = [
                p
                for p in packages
                if p.small_lot_exemption and aggregation_key(catalogue, p) == aggregation_key(catalogue, pkg)
            ]
            exempted = sum((p.estimated_value or ZERO for p in same), ZERO)
            ok = single < cap and (agg == ZERO or exempted * HUNDRED <= agg * share)
        if ok:
            exempt = True
            exempt_unconfirmed = rule is not None and rule.review_status != ReviewStatus.verified
        else:
            view.findings.append(
                finding("lot_splitting_avoids_threshold", sev, pkg.code, reason="small_lot_exemption_invalid")
            )
    view.small_lot_exempt = exempt
    basis_value = single if exempt else agg

    allowed: set[str] | None = None
    any_unconfirmed = exempt_unconfirmed
    unresolved = False
    above_any = False
    gross_warned = False
    for t in rows:
        value = convert_to_threshold(catalogue, basis_value, pkg.currency, t, vat_rate_pct=facts.vat_rate_pct, day=day)
        entry = {
            "contract_kind": t.contract_kind,
            "client_type": t.client_type,
            "amount": t.amount,
            "currency": t.currency,
            "vat_basis": t.vat_basis,
            "effect": t.effect,
            "source_url": t.source_url,
            "review_status": t.review_status.value,
            "valid_from": t.valid_from.isoformat() if t.valid_from else None,
            "valid_to": t.valid_to.isoformat() if t.valid_to else None,
            "compared_value": None if value is None else str(value.quantize(_CENT, ROUND_HALF_UP)),
        }
        view.thresholds.append(entry)
        if t.review_status != ReviewStatus.verified:
            any_unconfirmed = True
        if t.vat_basis == "gross" and facts.vat_rate_pct == ZERO and not gross_warned:
            # A gross threshold compared with a net value understates it; the concept has no VAT rate.
            gross_warned = True
            view.findings.append(finding("vat_rate_missing_for_gross_threshold", WARNING, pkg.code))
        if value is None:
            unresolved = True
            continue
        # "Equal to or greater than" the threshold is above it.
        above = value >= t.value
        entry["position"] = "above" if above else "below"
        above_any = above_any or above
        codes = set(t.allowed_above if above else t.allowed_below)
        if codes:
            allowed = codes if allowed is None else allowed & codes
    if unresolved:
        view.status = "unresolved"
        view.findings.append(
            finding(
                "threshold_currency_unresolved",
                WARNING,
                pkg.code,
                currency=pkg.currency,
                reason="no_rate" if pkg.currency else "currency_missing",
                blocks_approval=facts.public_client,
            )
        )
    elif any_unconfirmed:
        view.status = "unconfirmed"
    else:
        view.status = "above" if above_any else "below"
    view.allowed = sorted(allowed) if allowed is not None else None
    if any_unconfirmed:
        view.findings.append(finding("threshold_source_unconfirmed", WARNING, pkg.code))
    return view


def allowed_procedures(
    catalogue: ProcurementCatalogue,
    facts: ConceptFacts,
    pkg: PackageFacts,
    packages: Sequence[PackageFacts],
    day: date,
) -> list[dict[str, Any]]:
    """Every catalogue procedure with ``allowed`` and the reason (procedure picker, screen 2)."""
    view = threshold_view(catalogue, facts, pkg, packages, day)
    out = []
    for p in catalogue.procedures:
        reason = None
        if not facts.public_client and p.sector == "public":
            reason = "public_procedure_for_private_client"
        elif facts.public_client and p.sector == "private" and view.status != "below":
            reason = "private_procedure_for_public_client"
        elif view.allowed is not None and p.code not in view.allowed:
            reason = "not_allowed_at_value"
        out.append({"code": p.code, "name_key": p.name_key, "allowed": reason is None, "reason": reason})
    return out


def procedure_findings(
    catalogue: ProcurementCatalogue,
    facts: ConceptFacts,
    pkg: PackageFacts,
    packages: Sequence[PackageFacts],
    day: date,
) -> list[dict[str, Any]]:
    """Rules 2 to 5 for one package with a procedure."""
    view = threshold_view(catalogue, facts, pkg, packages, day)
    out = list(view.findings)
    if not pkg.procedure_code:
        return out
    proc = catalogue.procedure(pkg.procedure_code)
    if proc is None:
        return [*out, finding("procedure_unknown", ERROR, pkg.code, procedure=pkg.procedure_code)]
    flagged = False
    if facts.public_client and proc.sector == "private" and view.status != "below":
        # A public client may use a private procedure only below every threshold.
        sev = ERROR if view.status in ("above", "not_applicable", "unavailable") else _sev_from_view(view)
        out.append(finding("procedure_not_allowed_above_threshold", sev, pkg.code, procedure=proc.code))
        flagged = True
    if not facts.public_client and proc.sector == "public":
        out.append(finding("procedure_not_allowed_for_client", ERROR, pkg.code, procedure=proc.code))
        flagged = True
    # A private procedure below every threshold was judged by sector above.
    exempt_private = facts.public_client and proc.sector == "private"
    if not flagged and not exempt_private and view.allowed is not None and proc.code not in view.allowed:
        sev = _sev_from_view(view)
        single_below = all((t.get("position") == "below") for t in _single_positions(catalogue, facts, pkg, day))
        code = (
            "lot_splitting_avoids_threshold"
            if single_below and not view.small_lot_exempt
            else ("procedure_not_allowed_above_threshold")
        )
        out.append(finding(code, sev, pkg.code, procedure=proc.code, allowed=view.allowed))
    if pkg.tender_basis and pkg.tender_basis != "mixed" and pkg.tender_basis not in proc.tender_basis_allowed:
        out.append(finding("tender_basis_not_allowed", ERROR, pkg.code, procedure=proc.code))
    return out


def _sev_from_view(view: ThresholdView) -> str:
    return WARNING if view.status in ("unconfirmed", "unresolved") else ERROR


def _single_positions(
    catalogue: ProcurementCatalogue, facts: ConceptFacts, pkg: PackageFacts, day: date
) -> list[dict[str, Any]]:
    """Position of the lot's own value against each threshold (to tell splitting from a plain breach)."""
    ck = contract_kind_of(catalogue, pkg)
    out = []
    for t in applicable_thresholds(catalogue, facts, ck, day):
        v = convert_to_threshold(
            catalogue, pkg.estimated_value or ZERO, pkg.currency, t, vat_rate_pct=facts.vat_rate_pct, day=day
        )
        out.append({"position": None if v is None else ("above" if v >= t.value else "below")})
    return out


# ── Package plan (rules 1, 6, 7, 12) ────────────────────────────────────


def plan_findings(cp_rows: Iterable[dict[str, Any]], award_ids: set[str]) -> list[dict[str, Any]]:
    """Rule 1: every ContractPackage except ``project_agreement`` has an award package."""
    out = []
    for cp in cp_rows:
        if CONTRACT_PACKAGE_KIND_MAP.get(str(cp.get("kind"))) is None:
            continue
        if str(cp["id"]) not in award_ids:
            out.append(finding("package_without_procedure_plan", ERROR, str(cp.get("code") or cp["id"])))
    return out


def package_findings(catalogue: ProcurementCatalogue, pkg: PackageFacts) -> list[dict[str, Any]]:
    """Per-package completeness: procedure set, design rules (7), advance release (12)."""
    out = []
    if pkg.package_kind is None or pkg.state == "cancelled":
        return out
    if not pkg.procedure_code:
        out.append(finding("package_without_procedure_plan", ERROR, pkg.code))
    if pkg.package_kind == "design":
        ck = contract_kind_of(catalogue, pkg)
        if ck not in SERVICE_CONTRACT_KINDS:
            out.append(finding("design_package_uses_works_rules", ERROR, pkg.code, contract_kind=ck))
        if pkg.estimated_value is None or pkg.estimated_value <= ZERO:
            out.append(finding("design_fee_estimate_missing", ERROR, pkg.code))
    if pkg.is_advance and not pkg.advance_applies:
        # The flag was set under a phase model that had a release gate. It is shown, and it blocks nothing.
        out.append(finding("advance_flag_not_applicable", WARNING, pkg.code))
        return out
    if pkg.is_advance and not pkg.advance_reason.strip():
        out.append(finding("advance_without_reason", ERROR, pkg.code))
    if pkg.is_advance and not pkg.advance_released:
        out.append(finding("advance_package_not_released", ERROR, pkg.code))
    return out


def consistency_findings(
    catalogue: ProcurementCatalogue, delivery_form: str | None, packages: Sequence[PackageFacts]
) -> list[dict[str, Any]]:
    """Rule 6: procedures and tender basis consistent with mod3's delivery form."""
    if not delivery_form:
        return []
    live = [p for p in packages if p.state != "cancelled"]
    out = []
    if delivery_form in DESIGN_BUILD_FORMS:
        for p in live:
            if p.cp_kind == "design_and_construction" and p.tender_basis not in ("functional", "mixed"):
                out.append(finding("procedure_inconsistent_with_delivery_form", ERROR, p.code, form=delivery_form))
    if delivery_form in TWO_STAGE_FORMS:
        for p in live:
            if p.parent_id is None and p.cp_kind in MAIN_PACKAGE_KINDS:
                proc = catalogue.procedure(p.procedure_code)
                if proc is None or proc.stages != 2:
                    out.append(finding("procedure_inconsistent_with_delivery_form", ERROR, p.code, form=delivery_form))
    if delivery_form in SPLIT_FORMS:
        works = [p for p in live if p.cp_kind == "construction"]
        if len(works) < 2:
            out.append(finding("split_form_without_trade_packages", WARNING, delivery_form, form=delivery_form))
    return out


# ── Prequalification (rules 8, 10) ──────────────────────────────────────


def weights_findings(criteria: Sequence[dict[str, Any]], ref: str) -> list[dict[str, Any]]:
    """Scored weights sum to 100 (Decimal)."""
    total = sum((Decimal(str(c["weight"])) for c in criteria if c.get("kind") == "scored"), ZERO)
    if any(c.get("kind") == "scored" for c in criteria) and total != HUNDRED:
        return [finding("prequal_weights_not_100", ERROR, ref, total=str(total))]
    return []


def candidate_score(criteria: Sequence[dict[str, Any]], scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """``{total, passed_all, missing}``: total = sum(score x weight) / 100 over scored criteria (score 0..100)."""
    total = ZERO
    passed_all = True
    missing = []
    for c in criteria:
        s = scores.get(c["code"])
        if c.get("kind") == "pass_fail":
            if s is None or s.get("passed") is None:
                missing.append(c["code"])
                passed_all = False
            elif not s["passed"]:
                passed_all = False
        else:
            if s is None or s.get("score") is None:
                missing.append(c["code"])
                continue
            total += Decimal(str(s["score"])) * Decimal(str(c["weight"])) / HUNDRED
    return {"total": total.quantize(_CENT, ROUND_HALF_UP), "passed_all": passed_all, "missing": missing}


def min_bidders_of(catalogue: ProcurementCatalogue, procedure_code: str | None) -> int:
    proc = catalogue.procedure(procedure_code)
    if proc is None:
        return 1
    if proc.min_bidders is not None:
        return proc.min_bidders
    return _DEFAULT_MIN_BIDDERS.get(proc.competition, 1)


def shortlist_findings(
    catalogue: ProcurementCatalogue,
    pkg: PackageFacts,
    criteria: Sequence[dict[str, Any]],
    pass_mark: Decimal,
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rule 8. ``candidates``: ``{id, name, list, registered, rationale, scores}``."""
    out = []
    short = [c for c in candidates if c["list"] == "short"]
    need = min_bidders_of(catalogue, pkg.procedure_code)
    if len(short) < need:
        out.append(finding("shortlist_below_min_bidders", ERROR, pkg.code, have=len(short), need=need))
    for c in candidates:
        if c["list"] == "excluded" and not (c.get("rationale") or "").strip():
            out.append(finding("excluded_candidate_without_rationale", ERROR, str(c["id"])))
    for c in short:
        if not c.get("registered"):
            out.append(finding("candidate_not_registered", ERROR, str(c["id"])))
        sc = candidate_score(criteria, c.get("scores") or {})
        if not sc["passed_all"] or sc["total"] < pass_mark:
            out.append(finding("shortlisted_candidate_fails_prequal", ERROR, str(c["id"]), total=str(sc["total"])))
    return out


def evidence_findings(
    candidate_ref: str, evidence: Sequence[dict[str, Any]], award_date: date | None
) -> list[dict[str, Any]]:
    """Rule 10: an evidence item (certificate, insurance) expiring before the planned award date warns."""
    if award_date is None:
        return []
    return [
        finding(
            "prequal_evidence_expires_before_award",
            WARNING,
            candidate_ref,
            evidence=e.get("ref"),
            expires=str(e["expires"]),
        )
        for e in evidence
        if e.get("expires") is not None and e["expires"] < award_date
    ]


# ── Market sounding (rule 9) ────────────────────────────────────────────


def capacity_findings(soundings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        finding("capacity_unmitigated", ERROR, str(s["id"]), signal=s["capacity_signal"])
        for s in soundings
        if s.get("capacity_signal") in ("tight", "insufficient")
        and not (s.get("mitigation") or "").strip()
        and not s.get("resplit")
    ]


# ── Award schedule (rule 11) ────────────────────────────────────────────


@dataclass(frozen=True)
class BackwardPass:
    award_date: date
    start_date: date
    procedure_days: int
    lead_time_days: int


def procedure_days(catalogue: ProcurementCatalogue, pkg: PackageFacts) -> int | None:
    """Sum of the procedure's step durations (package override first, then catalogue default)."""
    if pkg.procedure_days is not None:
        return pkg.procedure_days
    lt = catalogue.lead_time(pkg.procedure_code)
    return lt.total_days() if lt else None


def backward_pass(catalogue: ProcurementCatalogue, pkg: PackageFacts) -> BackwardPass | None:
    """award = need - lead time; start = award - procedure durations. ``None`` without need date or procedure."""
    days = procedure_days(catalogue, pkg)
    if pkg.need_date is None or days is None:
        return None
    lead = pkg.lead_time_days or 0
    award = pkg.need_date - timedelta(days=lead)
    return BackwardPass(award, award - timedelta(days=days), days, lead)


def schedule_findings(
    catalogue: ProcurementCatalogue, pkg: PackageFacts, *, today: date, release_date: date | None
) -> list[dict[str, Any]]:
    """Rule 11: a start in the past or before the releasing gate is an error, unless an approved advance package."""
    bp = backward_pass(catalogue, pkg)
    if bp is None:
        if pkg.need_date is None and pkg.package_kind is not None and pkg.state != "cancelled":
            return [finding("need_date_missing", WARNING, pkg.code)]
        return []
    excused = pkg.is_advance and pkg.advance_reason.strip() and pkg.advance_released
    out = []
    if bp.start_date < today:
        out.append(
            finding(
                "award_schedule_infeasible",
                WARNING if excused else ERROR,
                pkg.code,
                reason="start_in_past",
                start=bp.start_date.isoformat(),
            )
        )
    elif release_date is not None and bp.start_date < release_date:
        out.append(
            finding(
                "award_schedule_infeasible",
                WARNING if excused else ERROR,
                pkg.code,
                reason="start_before_release_gate",
                start=bp.start_date.isoformat(),
                release=release_date.isoformat(),
            )
        )
    return out


# ── Frameworks (rule 13) ────────────────────────────────────────────────


def framework_findings(
    catalogue: ProcurementCatalogue,
    pkg: PackageFacts,
    framework: dict[str, Any] | None,
    *,
    award_date: date | None,
    remaining: Decimal | None,
) -> list[dict[str, Any]]:
    """A call-off needs an active framework covering the kind, running past award, with value left.

    ``remaining`` is ``None`` when the ledger holds entries it cannot express
    in the framework currency. The remaining value is then unknown, which
    blocks: an unknown remainder must not read as "enough".
    """
    call_off = catalogue.is_call_off(pkg.procedure_code)
    if not pkg.framework_agreement_id:
        return [finding("framework_missing", ERROR, pkg.code)] if call_off else []
    if framework is None:
        return [finding("framework_missing", ERROR, pkg.code)]
    out = []
    fw_currency = str(framework.get("currency") or "").upper()
    if pkg.estimated_value is not None and (pkg.currency or "").upper() != fw_currency:
        out.append(finding("framework_currency_mismatch", ERROR, pkg.code, framework_currency=fw_currency))
    elif remaining is None:
        out.append(finding("framework_remaining_unknown", ERROR, pkg.code))
    if framework["state"] == "exhausted":
        out.append(finding("framework_exhausted", ERROR, pkg.code))
    elif framework["state"] != "active":
        out.append(finding("framework_not_active", ERROR, pkg.code, state=framework["state"]))
    kinds = framework.get("package_kinds") or []
    if kinds and pkg.package_kind not in kinds:
        out.append(finding("framework_scope_mismatch", ERROR, pkg.code))
    end = framework.get("end_date")
    if end is not None and award_date is not None and end < award_date:
        out.append(finding("framework_expired", ERROR, pkg.code, end=end.isoformat()))
    if remaining is not None and pkg.estimated_value is not None and remaining < pkg.estimated_value:
        if not any(f["code"] == "framework_exhausted" for f in out):
            out.append(finding("framework_exhausted", ERROR, pkg.code, remaining=str(remaining)))
    if not call_off:
        out.append(finding("framework_procedure_mismatch", ERROR, pkg.code))
    return out


def profile_paths(facts: ConceptFacts, contract_kind: str | None, procedure_code: str | None) -> tuple[str, ...]:
    """Profile paths the procedure test of one package reads (thresholds of its kind and client, its procedure)."""
    out = []
    if contract_kind and facts.client_type:
        out.append(f"thresholds/{contract_kind}/{facts.client_type}/")
    if procedure_code:
        out.append(f"procedures/{procedure_code}/")
    return tuple(out)


def profile_findings(resolved: Any, prefixes: Sequence[str], ref: str) -> list[dict[str, Any]]:
    """Advisory warnings for every unconfirmed or stale profile value under ``prefixes``; they never block.

    ``resolved`` is a :class:`~app.modules.procurement_concept.profile.ResolvedProfile`.
    """
    if resolved is None or not prefixes:
        return []
    out = []
    for v in resolved.under(*prefixes):
        if v.status == "confirmed":
            continue
        out.append(
            finding(
                f"profile_value_{v.status}",
                WARNING,
                ref,
                blocks_approval=False,
                path=v.path,
                jurisdiction=v.origin,
                source_url=v.value.source_url,
                effective_from=v.value.effective_from.isoformat() if v.value.effective_from else None,
                effective_to=v.value.effective_to.isoformat() if v.value.effective_to else None,
            )
        )
    return out
