# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``commitment_release`` (SPEC section 7).

The rules read one payload, built by ``CommitmentService.validation_payload``::

    {
      "today": "YYYY-MM-DD",
      "schedule": {...pinned authority schedule body...},
      "items":    [item views as the matrix API returns them, with "exposure"],
      "releases": [{"id", "item_id", "outcome", "required_tier", "evaluated_amount",
                    "commitment_type", "flags", "schedule_version", "escalate_outside"}],
      "links":    [{"kind", "document_id", "item_id"}],
      "split_groups": {group: [item ids]}
    }

Several are enforced at write time too. They exist as rules because the
matrix also moves without a write here: a contract is amended, a date passes,
an FX rate is withdrawn, a schedule version is republished.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.commitment_release.catalogue import AuthoritySchedule, validate_authority_schedule
from app.modules.commitment_release.evaluator import required_tier
from app.modules.commitment_release.messages import translate

COMMITMENT_RULE_SET = "commitment_release"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _day(value: Any, locale: str) -> str:
    """A stored ``YYYY-MM-DD`` day as the reader of ``locale`` writes it (German: ``DD.MM.YYYY``).

    Other languages keep the ISO day, and anything that is not an ISO day is returned as stored.
    """
    text = str(value or "")
    if locale.lower().startswith("de") and len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}.{text[5:7]}.{text[:4]}"
    return text


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    raw = _data(context).get(key) or []
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _schedule(context: ValidationContext) -> AuthoritySchedule | None:
    body = _data(context).get("schedule")
    try:
        return AuthoritySchedule.model_validate(body) if isinstance(body, dict) else None
    except Exception:
        return None


_LIVE = ("aborted", "transferred")


class _CommitmentRule(ValidationRule):
    standard = "commitment"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""

    def _result(self, locale: str, passed: bool, ref: str, **params: Any) -> RuleResult:
        base = f"commitment.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=translate("common.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )

    def _items(self, context: ValidationContext) -> list[dict[str, Any]]:
        return [i for i in _rows(context, "items") if i.get("status") not in _LIVE]


class ItemHasCostCode(_CommitmentRule):
    key = "item_has_cost_code"
    rule_id = "commitment_release.item_has_cost_code"
    name = "Item Has Cost Code"
    severity = Severity.WARNING
    description = "An item without a cost line cannot be reconciled with the cost model."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [self._result(loc, bool(i.get("cost_line_id")), i["code"], item=i["code"]) for i in self._items(context)]


class ItemHasPlannedAmountSource(_CommitmentRule):
    key = "item_has_planned_amount_source"
    rule_id = "commitment_release.item_has_planned_amount_source"
    name = "Item Has Planned Amount Source"
    description = "An item whose planned amount cannot be read has no authority tier and no budget check."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, (i.get("planned") or {}).get("amount") is not None, i["code"], item=i["code"])
            for i in self._items(context)
        ]


class ReleaseWithinAuthority(_CommitmentRule):
    key = "release_within_authority"
    rule_id = "commitment_release.release_within_authority"
    name = "Release Within Authority"
    description = "A release decided under the current schedule version needs at least the tier the schedule names."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        schedule = _schedule(context)
        if schedule is None:
            return []
        order = schedule.tier_order()
        out = []
        for r in _rows(context, "releases"):
            if r.get("outcome") != "released" or r.get("schedule_version") != schedule.version:
                continue
            if r.get("escalate_outside") or r.get("commitment_type") not in schedule.type_codes():
                continue
            want = required_tier(schedule, r["commitment_type"], Decimal(r["evaluated_amount"]), r.get("flags") or [])
            have = r.get("required_tier")
            passed = want.tier_code is not None and have in order and order[have] >= order[want.tier_code]
            out.append(self._result(loc, passed, r["id"], release=r["id"], tier=want.tier_code or "escalate_outside"))
        return out


class CommittedWithinRelease(_CommitmentRule):
    key = "committed_within_release"
    rule_id = "commitment_release.committed_within_release"
    name = "Committed Within Release"
    description = "Linked documents bind more than was released plus the schedule's tolerance."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, not i.get("over_release"), i["code"], item=i["code"])
            for i in self._items(context)
            if i.get("committed") not in (None, "0")
        ]


class DecisionDateNotPassed(_CommitmentRule):
    key = "decision_date_not_passed"
    rule_id = "commitment_release.decision_date_not_passed"
    name = "Decision Date Not Passed"
    severity = Severity.WARNING
    description = "The latest responsible decision date has passed and nothing is released."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc,
                not i.get("decision_overdue"),
                i["code"],
                item=i["code"],
                date=_day(i.get("latest_decision_date"), loc),
            )
            for i in self._items(context)
            if i.get("latest_decision_date")
        ]


class ReleaseInDate(_CommitmentRule):
    key = "release_in_date"
    rule_id = "commitment_release.release_in_date"
    name = "Release In Date"
    severity = Severity.WARNING
    description = "A release past its validity date authorises nothing new until it is renewed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc,
                not i.get("release_expired"),
                i["code"],
                item=i["code"],
                date=", ".join(_day(d, loc) for d in i.get("expired_release_dates") or []),
            )
            for i in self._items(context)
        ]


class PlantItemInRegister(_CommitmentRule):
    key = "plant_item_in_register"
    rule_id = "commitment_release.plant_item_in_register"
    name = "Plant Item In Register"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "An item that names a plant item reads its lead time from the plant register."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, not i.get("plant_item_missing"), i["code"], item=i["code"])
            for i in self._items(context)
            if i.get("plant_item_id")
        ]


class AbortTermsPresentForCommitted(_CommitmentRule):
    key = "abort_terms_present_for_committed"
    rule_id = "commitment_release.abort_terms_present_for_committed"
    name = "Abort Terms Present For Committed"
    severity = Severity.WARNING
    description = "A committed item without abort terms has an unknown residual loss."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc,
                (i.get("exposure") or {}).get("reason") not in ("abort_terms_missing", "abort_terms_incomplete"),
                i["code"],
                item=i["code"],
            )
            for i in self._items(context)
            if i.get("status") in ("committed", "re_release_required")
        ]


class DocumentLinkedOnce(_CommitmentRule):
    key = "document_linked_once"
    rule_id = "commitment_release.document_linked_once"
    name = "Document Linked Once"
    description = "A document counted in two items is committed twice."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        seen: dict[tuple[str, str], int] = {}
        for lk in _rows(context, "links"):
            key = (str(lk.get("kind")), str(lk.get("document_id")))
            seen[key] = seen.get(key, 0) + 1
        return [self._result(loc, n == 1, f"{k}:{d}", document=d) for (k, d), n in seen.items()]


class FxRateAvailable(_CommitmentRule):
    key = "fx_rate_available"
    rule_id = "commitment_release.fx_rate_available"
    name = "FX Rate Available"
    description = "A linked amount cannot be converted into the schedule currency; the authority check refuses it."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, i.get("committed_reason") != "fx_rate_missing", i["code"], item=i["code"])
            for i in self._items(context)
            if i.get("links")
        ]


class AuthorityScheduleBandsMonotonic(_CommitmentRule):
    key = "authority_schedule_bands_monotonic"
    rule_id = "commitment_release.authority_schedule_bands_monotonic"
    name = "Authority Schedule Bands Monotonic"
    description = "Higher tiers must carry strictly higher ceilings in the pinned schedule."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        schedule = _schedule(context)
        if schedule is None:
            return []
        errors = [e for e in validate_authority_schedule(schedule, "tenant") if e.startswith("bands_")]
        return [self._result(loc, not errors, schedule.id, schedule=schedule.id)]


class SplitGroupNotBypassingTier(_CommitmentRule):
    key = "split_group_not_bypassing_tier"
    rule_id = "commitment_release.split_group_not_bypassing_tier"
    name = "Split Group Not Bypassing Tier"
    description = "The items of a split group were released under a lower tier than their sum needs."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        schedule = _schedule(context)
        if schedule is None:
            return []
        order = schedule.tier_order()
        items = {i["id"]: i for i in _rows(context, "items")}
        out = []
        for group, ids in (_data(context).get("split_groups") or {}).items():
            released = [
                r for r in _rows(context, "releases") if r.get("item_id") in ids and r.get("outcome") == "released"
            ]
            if not released:
                continue
            total = sum((Decimal(items[i]["released"] or "0") for i in ids if i in items), Decimal("0"))
            types = {r.get("commitment_type") for r in released} & schedule.type_codes()
            ok = True
            for t in types:
                want = required_tier(schedule, t, total)
                top = max((order.get(r.get("required_tier") or "", -1) for r in released), default=-1)
                if want.tier_code is None or top < order[want.tier_code]:
                    ok = False
            out.append(self._result(loc, ok, group, group=group))
        return out


COMMITMENT_RULES: tuple[type[ValidationRule], ...] = (
    ItemHasCostCode,
    ItemHasPlannedAmountSource,
    ReleaseWithinAuthority,
    CommittedWithinRelease,
    DecisionDateNotPassed,
    ReleaseInDate,
    PlantItemInRegister,
    AbortTermsPresentForCommitted,
    DocumentLinkedOnce,
    FxRateAvailable,
    AuthorityScheduleBandsMonotonic,
    SplitGroupNotBypassingTier,
)


def register_commitment_rules() -> None:
    """Idempotently register the commitment release rules."""
    for rule in COMMITMENT_RULES:
        rule_registry.register(rule(), rule_sets=[COMMITMENT_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_commitment_rules()
