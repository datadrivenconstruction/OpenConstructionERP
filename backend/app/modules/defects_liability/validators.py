# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Defects-liability validation rules (limitation of defect claims).

The module exists for one sentence, and it is this one: **a warranty period that
names a legal regime and then disagrees with it is reported, never corrected.**
Under the VOB/B the default period for building works is four years and under the
BGB it is five, and a contract is free to agree something else again. So a record
saying "VOB/B" beside a five-year period is either a contract that agreed five
years or a mistake that will cost a claim, and only a person knows which. The
rules name the provision, both numbers and the difference, and leave the record
alone.

Rules, both registered under the ``defects_liability`` rule set:

* ``defects_liability.limitation_period_matches_regime`` - WARNING. The entry
  names a regime and carries a period, and the two say different things. This is
  the one above. Reported for the stored month count and for the stored end date
  separately, because an entry can disagree on either.
* ``defects_liability.limitation_regime_needs_start_date`` - WARNING. The entry
  names a regime but records no Abnahme date, so the period it claims to follow
  cannot be counted at all.

Both are WARNING rather than ERROR on purpose. A period that departs from the
statutory default is lawful where the contract agreed it, so a finding here is
something a person answers, not something that blocks a save. Nothing in this
module ever writes.

**Silence is the whole design for everyone else.** Every rule returns an empty
list the moment it sees no regime on the entry. A register whose entries never
chose a regime therefore produces no findings at all, not even passing ones - it
gets no column, no badge and no nag, because the rules have nothing to say about
a date nobody claimed a reason for. That is checked directly by the tests rather
than left to be true by accident.

Findings are English prose naming the provision, which is the platform's settled
convention for rule messages (see
:mod:`app.modules.payment_clock.validators`); the reader's language happens on
the screen.

Every rule reads a plain dict built by
:func:`app.modules.defects_liability.service.limitation_snapshot`, so the rules
run against a fixture with no database at all.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.modules.defects_liability import limitation

logger = logging.getLogger(__name__)

DEFECTS_LIABILITY_RULE_SET = "defects_liability"


# -- Snapshot readers --------------------------------------------------------


def _warranty(context: ValidationContext) -> dict[str, Any]:
    """The one warranty section of the snapshot, or an empty dict."""
    data = context.data
    if not isinstance(data, dict):
        return {}
    section = data.get("warranty")
    return section if isinstance(section, dict) else {}


def _parse_date(value: Any) -> date | None:
    """Coerce a snapshot value to a date, or ``None`` (never raise).

    Accepts a ``date``, an ISO ``YYYY-MM-DD`` string and anything with a leading
    ISO date; anything else reads as absent, so a garbled value silently produces
    no finding instead of an engine error about a row somebody merely looked at.
    """
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.split("T", 1)[0].strip())
        except ValueError:
            return None
    return None


def _int_or_none(value: Any) -> int | None:
    """Coerce a snapshot value to an int, or ``None`` (never raise)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _element_ref(context: ValidationContext) -> str:
    """The entry a finding is about, named the way the register names it."""
    warranty = _warranty(context)
    return _text(warranty.get("reference")) or _text(warranty.get("id")) or "this warranty"


def _spec(context: ValidationContext) -> limitation.LimitationRegimeSpec | None:
    """The regime the entry named, or ``None`` when it named none (or an unknown one)."""
    return limitation.regime_for(_text(_warranty(context).get("limitation_regime")) or None)


def _start(context: ValidationContext) -> date | None:
    """The acceptance date the period counts from, or ``None``."""
    warranty = _warranty(context)
    return limitation.limitation_start(
        _parse_date(warranty.get("warranty_start_date")),
        _parse_date(warranty.get("handover_date")),
    )


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


# -- The rule the module exists for ------------------------------------------


class LimitationPeriodMatchesRegime(ValidationRule):
    """A period that names a regime and then contradicts it."""

    rule_id = "defects_liability.limitation_period_matches_regime"
    name = "Warranty Period Agrees With The Regime It Names"
    standard = "defects_liability"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Where a warranty entry names a limitation regime, the period it records has to be the period that "
        "regime gives, or the departure has to be a deliberate one somebody can point at in the contract."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        spec = _spec(context)
        if spec is None:
            # No regime was chosen, so there is no reason for the period to
            # agree with and nothing to report. This is the opt-in: an entry
            # that never named a regime is not examined at all.
            return []

        warranty = _warranty(context)
        stored_months = _int_or_none(warranty.get("warranty_months"))
        stored_end = _parse_date(warranty.get("warranty_end_date"))
        start = _start(context)
        derived = limitation.derive_period(spec.code, start)
        statutory_end = derived.end_date if derived is not None else None

        results: list[RuleResult] = []

        if stored_months is not None and stored_months != spec.months:
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"The entry names {spec.code} and records a warranty period of {stored_months} "
                        f"months, but {limitation.describe(spec)}, which is {spec.months} months. "
                        f"{spec.statute_reference}."
                    ),
                    element_ref=_element_ref(context),
                    suggestion=(
                        "If the contract agreed this period, record where it says so in the notes; the "
                        "agreed period governs and this finding is then a note rather than a defect. If it "
                        f"did not, the period is {spec.months} months."
                    ),
                    details={
                        "limitation_regime": spec.code,
                        "statute": spec.statute,
                        "statutory_months": spec.months,
                        "recorded_months": stored_months,
                    },
                )
            )
        elif stored_months is not None:
            results.append(
                _result(
                    self,
                    True,
                    "OK",
                    details={"limitation_regime": spec.code, "statutory_months": spec.months},
                )
            )

        if stored_end is not None and statutory_end is not None and stored_end != statutory_end:
            days = (stored_end - statutory_end).days
            direction = "later than" if days > 0 else "earlier than"
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"The entry names {spec.code} and ends on {stored_end.isoformat()}, "
                        f"{abs(days)} days {direction} the statutory date. Counting from the acceptance "
                        f"date {start.isoformat() if start is not None else 'recorded'}, "
                        f"{limitation.describe(spec, statutory_end)}. {spec.statute_reference}."
                    ),
                    element_ref=_element_ref(context),
                    suggestion=(
                        "Check the acceptance date first, because the statutory date is counted from it. "
                        "If the date is right and the period was agreed differently, record where the "
                        "contract says so; otherwise the period ends on "
                        f"{statutory_end.isoformat()}."
                    ),
                    details={
                        "limitation_regime": spec.code,
                        "statute": spec.statute,
                        "recorded_end_date": stored_end.isoformat(),
                        "statutory_end_date": statutory_end.isoformat(),
                        "difference_days": days,
                    },
                )
            )
        elif stored_end is not None and statutory_end is not None:
            results.append(
                _result(
                    self,
                    True,
                    "OK",
                    details={"limitation_regime": spec.code, "statutory_end_date": statutory_end.isoformat()},
                )
            )

        return results


class LimitationRegimeNeedsStartDate(ValidationRule):
    """A regime was named but nothing records the Abnahme it counts from."""

    rule_id = "defects_liability.limitation_regime_needs_start_date"
    name = "A Named Regime Has An Acceptance Date To Count From"
    standard = "defects_liability"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = (
        "Both shipped limitation regimes count from Abnahme, so an entry that names one without recording "
        "an acceptance date claims a period that cannot be counted."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        spec = _spec(context)
        if spec is None:
            return []
        start = _start(context)
        if start is not None:
            return [
                _result(
                    self,
                    True,
                    "OK",
                    details={"limitation_regime": spec.code, "counts_from": start.isoformat()},
                )
            ]
        return [
            _result(
                self,
                False,
                (
                    f"The entry names {spec.code}, which runs from Abnahme, but records neither a warranty "
                    f"start date nor a handover date, so the period cannot be counted. "
                    f"{spec.statute_reference}."
                ),
                element_ref=_element_ref(context),
                suggestion=(
                    "Record the acceptance date on the entry. Until it is there the entry names a legal "
                    "period and shows no date it produces."
                ),
                details={"limitation_regime": spec.code, "statute": spec.statute},
            )
        ]


_DEFECTS_LIABILITY_RULES: tuple[ValidationRule, ...] = (
    LimitationPeriodMatchesRegime(),
    LimitationRegimeNeedsStartDate(),
)


#: Rule set of the photo evidence rule. Kept apart from the limitation set,
#: which runs per warranty snapshot and must not see defect lists.
DEFECT_EVIDENCE_RULE_SET = "defects_liability_evidence"

#: Defect statuses at which the rectification is claimed done.
_RECTIFIED_STATUSES = frozenset({"closed"})


class RectifiedDefectHasPhoto(ValidationRule):
    """A defect closed as rectified should show the rectification with a photo."""

    rule_id = "defects_liability.rectified_defect_has_photo"
    name = "Rectified defects have photo evidence"
    standard = "defects_liability"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Defects closed as rectified should carry at least one photo with evidence"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from app.core.i18n import t

        data = context.data if isinstance(context.data, dict) else {}
        locale = (context.metadata or {}).get("locale")
        results: list[RuleResult] = []
        for defect in data.get("defects") or []:
            if not isinstance(defect, dict) or _text(defect.get("status")) not in _RECTIFIED_STATUSES:
                continue
            passed = bool(defect.get("photos"))
            ref = _text(defect.get("reference")) or _text(defect.get("id"))
            results.append(
                _result(
                    self,
                    passed,
                    "OK" if passed else t("field_evidence.defect_no_photo", locale, reference=ref),
                    element_ref=_text(defect.get("id")),
                    suggestion=None if passed else t("field_evidence.defect_no_photo_fix", locale),
                )
            )
        return results


def register_defects_liability_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook,
    because importing this module is not enough to put a rule in the registry.
    """
    for rule in _DEFECTS_LIABILITY_RULES:
        rule_registry.register(rule, [DEFECTS_LIABILITY_RULE_SET])
    rule_registry.register(RectifiedDefectHasPhoto(), [DEFECT_EVIDENCE_RULE_SET])
    logger.debug("Registered %d defects-liability validation rules", len(_DEFECTS_LIABILITY_RULES))


async def evaluate_limitation(snapshot: dict[str, Any], *, warranty_id: str = "") -> list[RuleResult]:
    """Run the limitation rules over one entry's snapshot; passing results dropped.

    Guarded the way the sibling modules guard theirs: a broken rule must not stop
    somebody reading a register, so a failure degrades to "no findings" and a log
    line rather than a 500. The findings are advisory to the screen and never
    block a save.

    Args:
        snapshot: The dict built by
            :func:`app.modules.defects_liability.service.limitation_snapshot`.
        warranty_id: The entry the snapshot describes, for the report target.

    Returns:
        The failing, non-engine-error results, which is an empty list for an
        entry that named no regime.
    """
    try:
        report = await validation_engine.validate(
            data=snapshot,
            rule_sets=[DEFECTS_LIABILITY_RULE_SET],
            target_type="dlp_warranty",
            target_id=warranty_id,
        )
    except Exception:  # noqa: BLE001 - the review augments a read; never break it
        logger.warning("defects-liability validation failed for warranty %s", warranty_id, exc_info=True)
        return []
    return [result for result in report.results if not result.passed and not result.is_engine_error]


__all__ = [
    "DEFECTS_LIABILITY_RULE_SET",
    "LimitationPeriodMatchesRegime",
    "LimitationRegimeNeedsStartDate",
    "evaluate_limitation",
    "register_defects_liability_rules",
]
