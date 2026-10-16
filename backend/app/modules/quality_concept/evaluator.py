# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure rules of the quality concept: no database, no clock, no I/O.

The service gathers facts from the evidence tables and calls these functions;
the unit tests call them directly. Every function returns findings as
:class:`Finding` (code, severity, ref, params) so the API, the validation rule
set and the governance evidence provider print the same words.

Rule numbers refer to the module spec, section 4.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.quality_concept import vocab

ERROR = "error"
WARNING = "warning"

# CxIssue severity order (commissioning/schemas.py ``_SEVERITY_PATTERN``).
CX_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
STAGE_DONE = ("released", "not_applicable")
ACCEPTED_STATES = ("accepted", "accepted_with_reservations", "deemed_accepted")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str = ERROR
    ref: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "ref": self.ref, "params": dict(self.params)}


def to_decimal(value: Any) -> Decimal | None:
    """A Decimal from a string or number; ``None`` for empty, junk, NaN or infinity."""
    if value is None or isinstance(value, bool) or isinstance(value, float):
        return None
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def to_date(value: Any) -> date | None:
    """A calendar date from a date, datetime or ISO string (``tested_at`` is ``String(40)``)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


# ── rule 1: concept completeness ───────────────────────────────────────────


@dataclass(frozen=True)
class PackageScope:
    ref: str
    proof_count: int = 0
    no_proofs_rationale: str = ""
    acceptance_unit_count: int = 0


@dataclass(frozen=True)
class StageModelEntry:
    code: str
    order: int
    owner_user_id: str | None
    release_party_role: str | None


@dataclass(frozen=True)
class UnitSummary:
    kind: str
    regime_code: str | None
    package_refs: tuple[str, ...] = ()


def concept_completeness(
    *,
    standards_count: int,
    packages: Sequence[PackageScope],
    stages: Sequence[StageModelEntry],
    units: Sequence[UnitSummary],
) -> list[Finding]:
    """Rule 1: what a concept needs before it may go to review."""
    out: list[Finding] = []
    if standards_count < 1:
        out.append(Finding("standards_basis_missing"))
    for p in packages:
        if p.proof_count < 1 and not p.no_proofs_rationale.strip():
            out.append(Finding("package_without_proofs", ref=p.ref))
    if not stages:
        out.append(Finding("stage_model_missing"))
    for s in stages:
        if not s.owner_user_id:
            out.append(Finding("stage_without_owner", ref=s.code))
        if not s.release_party_role or s.release_party_role not in vocab.PARTY_ROLES:
            out.append(Finding("stage_without_release_party", ref=s.code))
    covered = {ref for u in units for ref in u.package_refs}
    for p in packages:
        if p.ref not in covered:
            out.append(Finding("acceptance_unit_per_package", ref=p.ref))
    for kind in ("total", "handover_to_operation"):
        if not any(u.kind == kind for u in units):
            out.append(Finding(f"acceptance_unit_{kind}_missing"))
    for u in units:
        if not u.regime_code:
            out.append(Finding("acceptance_regime_missing", ref=u.kind))
    return out


# ── rule 2: proof needs deliverer and due ──────────────────────────────────


def proof_findings(
    *,
    ref: str,
    deliverer_role: str | None,
    required_by_kind: str | None,
    required_by_ref: str | None,
    stage_codes: Iterable[str],
    unit_ids: Iterable[str] = (),
) -> list[Finding]:
    """Rule 2: deliverer role and a resolvable ``required_by``."""
    out: list[Finding] = []
    if not deliverer_role or deliverer_role not in vocab.DELIVERER_ROLES:
        out.append(Finding("proof_without_deliverer", ref=ref))
    if not required_by_kind or not required_by_ref:
        out.append(Finding("proof_without_due", ref=ref))
    elif required_by_kind == "stage" and required_by_ref not in set(stage_codes):
        out.append(Finding("proof_due_stage_unknown", ref=ref, params={"stage": required_by_ref}))
    elif required_by_kind == "acceptance_unit" and required_by_ref not in set(unit_ids):
        out.append(Finding("proof_due_unit_unknown", ref=ref, params={"unit": required_by_ref}))
    elif required_by_kind == "date" and to_date(required_by_ref) is None:
        out.append(Finding("proof_due_date_invalid", ref=ref))
    return out


# ── rules 4-6: delivery derivation ─────────────────────────────────────────


@dataclass(frozen=True)
class EvidenceFact:
    """What one linked evidence row says, read by the link resolver.

    ``outcome``: ``pass`` (counts), ``fail`` (a recorded failure), ``pending``
    (exists, not yet conclusive). ``retest_of`` names the link id of the failed
    result this one re-tests (rule 6); ``fail_cleared`` is True when the failed
    row's NCR is closed. ``calibration_expired`` (rule 5) and ``expired_at_use``
    (rule 4, material) make a pass not count.
    """

    link_kind: str
    link_id: str
    outcome: str
    sample: str | None = None
    retest_of: str | None = None
    fail_cleared: bool = False
    calibration_expired: bool = False
    expired_at_use: bool = False
    quantity: Decimal | None = None


@dataclass(frozen=True)
class QuantityRule:
    per_quantity: Decimal
    unit: str
    min_count: int = 1


@dataclass(frozen=True)
class Delivery:
    state: str  # open | partly_delivered | delivered
    counted: int
    required: int
    findings: tuple[Finding, ...] = ()


def required_count(rule: QuantityRule | None, placed: Decimal | None) -> int:
    """Number of passing results a counted proof needs for the placed quantity."""
    if rule is None:
        return 1
    if placed is None or placed <= 0 or rule.per_quantity <= 0:
        return max(1, rule.min_count)
    return max(rule.min_count, math.ceil(placed / rule.per_quantity))


def derive_delivery(
    facts: Sequence[EvidenceFact],
    *,
    rule: QuantityRule | None = None,
    placed_quantity: Decimal | None = None,
    ref: str = "",
) -> Delivery:
    """Rules 4, 5 and 6: the delivery state of one proof from its linked evidence."""
    findings: list[Finding] = []
    passes = 0
    for f in facts:
        if f.outcome != "pass":
            continue
        if f.calibration_expired:
            findings.append(
                Finding("evidence_with_expired_calibration", ref=ref, params={"link": f"{f.link_kind}:{f.link_id}"})
            )
            continue
        if f.expired_at_use:
            findings.append(Finding("material_expired_at_use", ref=ref, params={"link": f"{f.link_kind}:{f.link_id}"}))
            continue
        passes += 1
    cured = {f.retest_of for f in facts if f.outcome == "pass" and f.retest_of and not f.calibration_expired}
    open_fails = [f for f in facts if f.outcome == "fail" and not f.fail_cleared and f.link_id not in cured]
    for f in open_fails:
        findings.append(Finding("failed_evidence_unresolved", ref=ref, params={"link": f"{f.link_kind}:{f.link_id}"}))
    need = required_count(rule, placed_quantity)
    if open_fails:
        return Delivery("open", passes, need, tuple(findings))
    if rule is not None and facts and (placed_quantity is None or placed_quantity <= 0):
        # The number of results a counted proof needs follows the placed quantity; without it
        # the count is unknown, so the proof stays short of delivered and says why. Before any
        # result is linked (a site that has not started) nothing is placed yet and the count
        # does not matter, so the proof is simply open and stays quiet.
        findings.append(Finding("placed_quantity_missing", WARNING, ref))
        return Delivery("partly_delivered" if passes else "open", passes, need, tuple(findings))
    if passes >= need:
        return Delivery("delivered", passes, need, tuple(findings))
    if passes > 0:
        return Delivery("partly_delivered", passes, need, tuple(findings))
    return Delivery("open", passes, need, tuple(findings))


def proof_state(derived: str, decision: str) -> str:
    """The shown state: a stored decision (accepted, waived) wins over the derived one."""
    return decision if decision in ("accepted", "waived") else derived


def calibration_expired(valid_until: Any, used_on: Any) -> bool:
    """Rule 5: an instrument certificate expired on the day of the test or survey."""
    end = to_date(valid_until)
    day = to_date(used_on)
    if end is None or day is None:
        return False
    return day > end


# ── rules 8-9: stage preconditions ─────────────────────────────────────────

PLANT_NOT_APPLICABLE = frozenset({"no_plant_item_linked", "no_plant_register"})
TRIGGERING_ACTIVITIES = frozenset({"excavation", "piling", "demolition", "dewatering"})


@dataclass(frozen=True)
class StageContext:
    """Facts about one commissioning unit (system) at one stage.

    ``None`` means the fact could not be read (no provider registered); a
    predicate on an unknown fact is not met and says why.
    """

    previous_state: str | None = None  # None for the first stage
    delivered_evidence_types: frozenset[str] = frozenset()
    open_cx_issue_severities: tuple[str, ...] = ()
    unreleased_gate_count: int = 0
    plant_item_delivered: bool | None = None
    delivery_limit_agreed: bool | None = None
    # Why the two plant facts are None: ``no_plant_item_linked`` or ``no_plant_register``.
    plant_unavailable_reason: str = ""
    authority_acceptance_present: bool = False
    released_systems_by_stage: dict[str, frozenset[str]] = field(default_factory=dict)
    scope_system_ids: frozenset[str] = frozenset()
    delivered_slot_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PreconditionResult:
    code: str
    met: bool
    reason: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "met": self.met, "reason": self.reason, "params": dict(self.params)}


def evaluate_preconditions(preconditions: Sequence[dict[str, Any]], ctx: StageContext) -> list[PreconditionResult]:
    """Rules 8 and 9. Stage order is always enforced, listed or not."""
    results: list[PreconditionResult] = []
    codes = [p.get("code") for p in preconditions]
    if ctx.previous_state is not None and "previous_stage_released" not in codes:
        preconditions = [{"code": "previous_stage_released", "params": {}}, *preconditions]
    for pre in preconditions:
        code = str(pre.get("code"))
        params = dict(pre.get("params") or {})
        results.append(_evaluate_one(code, params, ctx))
    return results


def _evaluate_one(code: str, params: dict[str, Any], ctx: StageContext) -> PreconditionResult:
    if code == "previous_stage_released":
        ok = ctx.previous_state is None or ctx.previous_state in STAGE_DONE
        return PreconditionResult(code, ok, "" if ok else "previous_stage_not_released")
    if code == "proofs_delivered":
        wanted = set(params.get("evidence_types") or [])
        missing = sorted(wanted - ctx.delivered_evidence_types)
        return PreconditionResult(code, not missing, "" if not missing else "proofs_missing", {"missing": missing})
    if code == "no_open_cx_issues":
        floor = CX_SEVERITY_RANK.get(str(params.get("severity") or "high"), 2)
        blocking = [s for s in ctx.open_cx_issue_severities if CX_SEVERITY_RANK.get(s, 0) >= floor]
        return PreconditionResult(
            code, not blocking, "" if not blocking else "open_cx_issues", {"count": len(blocking)}
        )
    if code == "hold_gates_released":
        ok = ctx.unreleased_gate_count == 0
        return PreconditionResult(code, ok, "" if ok else "hold_gates_open", {"count": ctx.unreleased_gate_count})
    if code in ("plant_item_delivered", "delivery_limit_agreed"):
        value = getattr(ctx, code)
        if value is None:
            if ctx.plant_unavailable_reason in PLANT_NOT_APPLICABLE:
                return PreconditionResult(code, True, ctx.plant_unavailable_reason, {"not_applicable": True})
            return PreconditionResult(code, False, "fact_unavailable")
        return PreconditionResult(code, bool(value), "" if value else code + "_not_met")
    if code == "authority_acceptance_present":
        ok = ctx.authority_acceptance_present
        return PreconditionResult(code, ok, "" if ok else "authority_acceptance_missing")
    if code == "systems_released":
        stage = str(params.get("stage") or "")
        wanted = set(params.get("systems") or ctx.scope_system_ids)
        released = ctx.released_systems_by_stage.get(stage, frozenset())
        missing = sorted(wanted - released)
        return PreconditionResult(
            code, not missing, "" if not missing else "systems_not_released", {"missing": missing}
        )
    if code == "documentation_slots_delivered":
        wanted = set(params.get("keys") or [])
        missing = sorted(wanted - ctx.delivered_slot_keys)
        return PreconditionResult(code, not missing, "" if not missing else "slots_missing", {"missing": missing})
    return PreconditionResult(code, False, "unknown_predicate")


def effective_previous_state(states_in_order: Sequence[str], index: int) -> str | None:
    """The state stage order looks at: the nearest earlier stage that is not ``not_applicable``.

    ``None`` when no earlier stage applies, which is the first-stage case. Skipping a
    not-applicable stage must not also skip the blocked one before it.
    """
    for state in reversed(states_in_order[:index]):
        if state != "not_applicable":
            return state
    return None


def delivered_evidence_types(proofs: Iterable[tuple[str, bool]]) -> frozenset[str]:
    """Evidence types whose in-scope proofs are all done; ``(evidence_type, done)`` per proof.

    One delivered proof of a type does not stand for the others of that type.
    """
    seen: dict[str, bool] = {}
    for code, done in proofs:
        seen[code] = seen.get(code, True) and done
    return frozenset(code for code, ok in seen.items() if ok)


def stage_ready(results: Sequence[PreconditionResult]) -> bool:
    return all(r.met for r in results)


def computed_stage_state(stored: str, results: Sequence[PreconditionResult]) -> str:
    """``blocked`` and ``ready`` follow the preconditions; every other state is stored."""
    if stored in ("blocked", "ready"):
        return "ready" if stage_ready(results) else "blocked"
    return stored


def stale_dependants(
    restarted_system_id: str, dependencies: dict[str, frozenset[str]], released: Iterable[str]
) -> list[str]:
    """Rule 12: released stage-progress rows whose unit depends on a system that re-entered testing.

    ``dependencies`` maps a stage-progress id to the system ids its stage depends on
    (an IST names the systems it integrates).
    """
    rel = set(released)
    return sorted(pid for pid, deps in dependencies.items() if pid in rel and restarted_system_id in deps)


# ── rules 13, 16, 17: acceptance ───────────────────────────────────────────


@dataclass(frozen=True)
class UnmetPrecondition:
    kind: str  # stage | proofs | documentation | defects | partials | final_stage | fm_data
    ref: str


def stages_unmet(
    stage_codes: Sequence[str], rows: Sequence[tuple[str, str, str]], scope_system_ids: Iterable[str] = ()
) -> list[UnmetPrecondition]:
    """Rule 13, stages: ``(system_id, stage_code, state)`` rows against the stages a unit names.

    A named stage with no progress row in scope is unmet (ref ``*:<code>``): nothing was
    tested, which is not the same as everything being released.
    """
    scope = set(scope_system_ids)
    out: list[UnmetPrecondition] = []
    for code in stage_codes:
        mine = [r for r in rows if r[1] == code and (not scope or r[0] in scope)]
        if not mine:
            out.append(UnmetPrecondition("stage", f"*:{code}"))
        out += [UnmetPrecondition("stage", f"{sid}:{code}") for sid, _c, state in mine if state not in STAGE_DONE]
    return out


def acceptance_request_check(
    unmet: Sequence[UnmetPrecondition],
    *,
    reservable: Iterable[str],
    with_reservations: bool,
) -> tuple[list[Finding], list[UnmetPrecondition]]:
    """Rule 13: a request needs every precondition met, or each unmet one as a reservation.

    Returns ``(blocking findings, reservations to record)``.
    """
    allowed = set(reservable)
    if not unmet:
        return [], []
    if not with_reservations:
        return [Finding("acceptance_preconditions_unmet", ref=u.ref, params={"kind": u.kind}) for u in unmet], []
    blocking = [u for u in unmet if u.kind not in allowed]
    if blocking:
        return [Finding("precondition_not_reservable", ref=u.ref, params={"kind": u.kind}) for u in blocking], []
    return [], list(unmet)


def total_acceptance_unmet(partials: Sequence[tuple[str, str, bool]]) -> list[UnmetPrecondition]:
    """Rule 17: ``(unit_id, state, explicitly_included)`` of every partial unit."""
    return [
        UnmetPrecondition("partials", uid)
        for uid, state, included in partials
        if state not in ACCEPTED_STATES and not included
    ]


# ── rule 14: deemed acceptance ─────────────────────────────────────────────


def add_working_days(
    start: date,
    days: int,
    *,
    saturday_is_working_day: bool = True,
    holidays: Iterable[date] = (),
    rest_weekdays: Iterable[int] = (6,),
) -> date:
    """The day ``days`` working days after ``start`` (``start`` itself not counted).

    ``rest_weekdays`` (Monday is 0) never count; the regime names them, Sunday in the
    shipped regimes. Saturdays count when the regime counts ``Werktage`` (VOB/B),
    otherwise not. Public holidays are data the caller passes.
    """
    off = set(holidays)
    rest = set(rest_weekdays)
    if len(rest) >= 7:
        raise ValueError("a regime cannot rest on every weekday")
    current = start
    counted = 0
    while counted < days:
        current += timedelta(days=1)
        wd = current.weekday()
        if wd in rest or (wd == 5 and not saturday_is_working_day) or current in off:
            continue
        counted += 1
    return current


@dataclass(frozen=True)
class DeemedDate:
    trigger: str
    from_date: date
    deemed_on: date | None
    source_url: str | None
    review_status: str
    needs_deadline: bool = False
    source_title: str | None = None


def deemed_dates(
    regime_rules: Sequence[Any],
    *,
    completion_notice_at: Any = None,
    use_started_at: Any = None,
    deadline_at: Any = None,
    holidays: Iterable[date] = (),
) -> list[DeemedDate]:
    """Rule 14: the deemed acceptance dates a unit's records start; shown, never applied."""
    out: list[DeemedDate] = []
    hol = tuple(holidays)
    starts = {"completion_notice": to_date(completion_notice_at), "use_start": to_date(use_started_at)}
    for r in regime_rules:
        trigger = r.trigger
        status = str(getattr(r.review_status, "value", r.review_status))
        if trigger == "deadline_set":
            notice = starts["completion_notice"]
            if notice is None:
                continue
            deadline = to_date(deadline_at)
            out.append(
                DeemedDate(
                    trigger,
                    notice,
                    deadline,
                    r.source_url,
                    status,
                    needs_deadline=deadline is None,
                    source_title=r.source_title,
                )
            )
            continue
        start = starts.get(trigger)
        if start is None:
            continue
        calendar_days = getattr(r, "calendar_days", None)
        if calendar_days is not None:
            on = start + timedelta(days=calendar_days)
        elif r.working_days is not None:
            on = add_working_days(
                start,
                r.working_days,
                saturday_is_working_day=r.saturday_is_working_day,
                holidays=hol,
                rest_weekdays=getattr(r, "rest_weekdays", (6,)),
            )
        else:
            continue
        out.append(DeemedDate(trigger, start, on, r.source_url, status, source_title=r.source_title))
    return out


def deemed_due_findings(dates: Sequence[DeemedDate], today: date, ref: str) -> list[Finding]:
    return [
        Finding(
            "deemed_acceptance_due",
            WARNING,
            ref,
            {"trigger": d.trigger, "deemed_on": d.deemed_on.isoformat(), "review_status": d.review_status},
        )
        for d in dates
        if d.deemed_on is not None and d.deemed_on <= today
    ]


# ── rule 15: legal effects ─────────────────────────────────────────────────


def proposed_effects(regime_effects: Sequence[Any], applied: Iterable[str]) -> list[Any]:
    """Effects of the regime not yet confirmed for this unit (idempotent per effect)."""
    done = set(applied)
    return [e for e in regime_effects if e.effect not in done]


# ── rule 18: certification ─────────────────────────────────────────────────


def level_index(levels: Sequence[Any], code: str | None) -> int | None:
    for i, lv in enumerate(levels):
        if lv.code == code:
            return i
    return None


def certification_target_at_risk(
    levels: Sequence[Any],
    target_level: str | None,
    points_targeted: Sequence[Decimal],
    ref: str = "",
    *,
    points_available: Decimal | None = None,
) -> list[Finding]:
    """Rule 18: tracked credits whose targeted points fall below the target level's floor.

    A floor in ``points`` is compared with the sum of targeted points. A floor in ``percent``
    is compared with targeted points as a share of ``points_available``; without that total
    the comparison has no meaning and nothing is reported.
    """
    if not points_targeted:
        return []
    idx = level_index(levels, target_level)
    if idx is None:
        return []
    floor = to_decimal(levels[idx].min_score)
    if floor is None:
        return []
    total = sum(points_targeted, Decimal("0"))
    if str(getattr(levels[idx], "score_unit", "points")) == "percent":
        if points_available is None or points_available <= 0:
            return []
        total = total * Decimal("100") / points_available
    if total >= floor:
        return []
    status = str(getattr(levels[idx].review_status, "value", levels[idx].review_status))
    return [
        Finding(
            "certification_target_at_risk",
            WARNING,
            ref,
            {"targeted": str(total), "min_score": str(floor), "review_status": status},
        )
    ]


def certify_allowed(levels: Sequence[Any], target_level: str | None, achieved_level: str | None) -> bool:
    """Rule 18: ``certified`` needs an achieved level at or above the target.

    A scheme that ships no levels has no order to compare, so any stated level certifies.
    """
    if not levels:
        return bool(achieved_level)
    t = level_index(levels, target_level)
    a = level_index(levels, achieved_level)
    return t is not None and a is not None and a >= t


# ── rules 19-20: evidence preservation ─────────────────────────────────────


@dataclass(frozen=True)
class SurveyFact:
    id: str
    subject_ref: str
    phase: str
    state: str
    acknowledged: bool = False
    access_refused: bool = False
    paired_with_id: str | None = None


@dataclass(frozen=True)
class SubjectFact:
    ref: str
    kind: str
    triggers: frozenset[str]
    activity_starts: dict[str, date | None] = field(default_factory=dict)  # trigger -> start date of the activity


def preservation_unplanned(subjects: Sequence[SubjectFact], surveys: Sequence[SurveyFact]) -> list[str]:
    """Subjects under a triggering activity with no before survey planned at all (gate readiness)."""
    planned = {s.subject_ref for s in surveys if s.phase == "before"}
    return sorted(sub.ref for sub in subjects if sub.triggers & TRIGGERING_ACTIVITIES and sub.ref not in planned)


def preservation_findings(subjects: Sequence[SubjectFact], surveys: Sequence[SurveyFact], today: date) -> list[Finding]:
    """Rule 19 (before survey surveyed before a triggering activity starts) and rule 20."""
    out: list[Finding] = []
    triggering = TRIGGERING_ACTIVITIES
    by_subject: dict[str, list[SurveyFact]] = {}
    for s in surveys:
        by_subject.setdefault(s.subject_ref, []).append(s)
    ids = {s.id: s for s in surveys}
    for sub in subjects:
        hits = sorted(sub.triggers & triggering)
        if not hits:
            continue
        before_done = any(
            s.phase == "before" and s.state in ("surveyed", "report_issued", "closed")
            for s in by_subject.get(sub.ref, [])
        )
        if before_done:
            continue
        starts = [d for t in hits if (d := sub.activity_starts.get(t)) is not None]
        started = any(d <= today for d in starts)
        out.append(
            Finding(
                "preservation_missing_before_start",
                ERROR if started else WARNING,
                sub.ref,
                {"triggers": hits, "starts": sorted(d.isoformat() for d in starts)},
            )
        )
    for s in surveys:
        if (
            s.subject_ref
            and s.state in ("surveyed", "report_issued", "closed")
            and not s.acknowledged
            and not s.access_refused
        ):
            out.append(Finding("preservation_acknowledged", WARNING, s.id))
        if s.phase == "after":
            partner = ids.get(s.paired_with_id or "")
            if partner is None or partner.phase != "before" or partner.subject_ref != s.subject_ref:
                out.append(Finding("preservation_after_unpaired", WARNING, s.id))
    return out


# ── rule 21: material test frequency ───────────────────────────────────────


def material_frequency_short(
    *, plan_code: str, per_quantity: Decimal, placed: Decimal | None, passing: int, review_status: str
) -> list[Finding]:
    """Rule 21: fewer passing results than the placed quantity calls for."""
    if placed is None or placed <= 0:
        return []
    need = required_count(QuantityRule(per_quantity, ""), placed)
    if passing >= need:
        return []
    return [
        Finding(
            "material_test_frequency_short",
            WARNING,
            plan_code,
            {"required": need, "passing": passing, "placed": str(placed), "review_status": review_status},
        )
    ]
