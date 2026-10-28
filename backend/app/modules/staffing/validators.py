# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``staffing`` (SPEC section 7).

The rules read one in-process payload built by
``StaffingService.validation_payload`` (catalogue object, plan, positions,
fills, handovers, gate dates, people with requirements and document statuses,
documents, retention) and call the same pure functions the service uses
(``rules.py``), so every check has one implementation.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.staffing import rules
from app.modules.staffing.catalogue import HEALTH_KIND
from app.modules.staffing.messages import translate

STAFFING_RULE_SET = "staffing"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _locale(context: ValidationContext) -> str:
    return str((getattr(context, "metadata", None) or {}).get("locale") or "en")


class _StaffingRule(ValidationRule):
    standard = "staffing"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    key = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.rule_id = f"staffing.{cls.key}"
        cls.name = cls.key.replace("_", " ").capitalize()
        cls.description = f"staffing.rules.{cls.key}.description"

    def _result(self, locale: str, passed: bool, ref: str, severity: Severity | None = None) -> RuleResult:
        base = f"staffing.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=passed,
            message=translate("staffing.rules.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, ref=ref),
            element_ref=ref,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )

    def refs(self, data: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        data = _data(context)
        if not data:
            return [self._result(loc, True, "project")]
        failing = self.refs(data)
        if not failing:
            return [self._result(loc, True, "project")]
        return [self._result(loc, False, ref) for ref in failing]


class PositionFteValid(_StaffingRule):
    key = "position_fte_valid"

    def refs(self, data):
        return [
            str(p["id"])
            for p in data.get("positions") or []
            if {"fte_out_of_range", "headcount_invalid"}
            & set(rules.position_errors(p["fte"], p["headcount"], None, None))
        ]


class PositionDatesValid(_StaffingRule):
    key = "position_dates_valid"

    def refs(self, data):
        return [
            str(p["id"])
            for p in data.get("positions") or []
            if p.get("entry_date") and p.get("exit_date") and p["exit_date"] < p["entry_date"]
        ]


def _submission(data: dict[str, Any], codes: set[str]) -> list[str]:
    plan = data.get("plan") or {}
    found = rules.submission_findings(
        data["catalogue"],
        data.get("positions") or [],
        data.get("fills") or [],
        data.get("handovers") or [],
        plan.get("commissioning_date"),
    )
    return [f.ref for f in found if f.code in codes]


class KeyRolesPresent(_StaffingRule):
    key = "key_roles_present"

    def refs(self, data):
        return _submission(data, {"key_role_missing", "operation_role_late", "commissioning_date_missing"})


class KeyRolesFilledBeforeGate(_StaffingRule):
    key = "key_roles_filled_before_gate"

    def refs(self, data):
        positions = data.get("positions") or []
        fills = data.get("fills") or []
        out: list[str] = []
        # Each gate with what the phase behind it enables; a position is matched by that tag, never by a gate code.
        for gate in data.get("gates") or []:
            found = rules.key_role_gate_findings(positions, fills, gate["enabled"], gate.get("date"))
            out += [f.ref for f in found if f.ref not in out]
        return out


class PersonNotOverallocated(_StaffingRule):
    key = "person_not_overallocated"

    def refs(self, data):
        by_person: dict[Any, list] = {}
        for f in data.get("fills") or []:
            if f.get("roster_member_id") is not None:
                by_person.setdefault(f["roster_member_id"], []).append(f)
        return [str(m) for m, own in by_person.items() if rules.first_overallocated_day(own) is not None]


class HandoverRolesLinked(_StaffingRule):
    key = "handover_roles_linked"

    def refs(self, data):
        return _submission(data, {"handover_missing"})


class RequiredDocumentsPresent(_StaffingRule):
    key = "required_documents_present"

    def refs(self, data):
        return [str(p["roster_member_id"]) for p in data.get("people") or [] if p.get("confirmed") and p["missing"]]


class DocumentsNotExpiredOnStart(_StaffingRule):
    key = "documents_not_expired_on_start"

    def refs(self, data):
        return [str(p["roster_member_id"]) for p in data.get("people") or [] if p.get("confirmed") and p["expired"]]


class HealthRecordMinimal(_StaffingRule):
    key = "health_record_minimal"

    def refs(self, data):
        return [
            d["id"]
            for d in data.get("documents") or []
            if d.get("fit_for_role") is not None
            and (d["document_kind"] != HEALTH_KIND or d["fit_for_role"] not in rules.HEALTH_FIT_VALUES)
        ]


class DocumentNumberMasked(_StaffingRule):
    key = "document_number_masked"

    def refs(self, data):
        catalogue = data["catalogue"]
        out = []
        for d in data.get("documents") or []:
            value = d.get("number_last4")
            if value is None:
                continue
            kind = catalogue.document_kind(d["document_kind"])
            if kind is None or not kind.store_number or len(value) > 4:
                out.append(d["id"])
        return out


class RetentionRuleAssigned(_StaffingRule):
    key = "retention_rule_assigned"

    def refs(self, data):
        return [r["id"] for r in data.get("retention") or [] if not r["assigned"]]


class AccommodationForRemoteSite(_StaffingRule):
    key = "accommodation_for_remote_site"
    severity = Severity.WARNING

    def refs(self, data):
        plan = data.get("plan") or {}
        out = []
        for p in data.get("people") or []:
            # Whether a person has a bed is their file; the payload withholds it from a caller who may not read it.
            if not p.get("confirmed") or p.get("restricted"):
                continue
            f = rules.accommodation_finding(
                bool(plan.get("requires_accommodation")),
                p.get("start"),
                p.get("bookings") or [],
                str(p["roster_member_id"]),
            )
            if f is not None:
                out.append(f.ref)
        return out


STAFFING_RULES: tuple[type[ValidationRule], ...] = (
    PositionFteValid,
    PositionDatesValid,
    KeyRolesPresent,
    KeyRolesFilledBeforeGate,
    PersonNotOverallocated,
    HandoverRolesLinked,
    RequiredDocumentsPresent,
    DocumentsNotExpiredOnStart,
    HealthRecordMinimal,
    DocumentNumberMasked,
    RetentionRuleAssigned,
    AccommodationForRemoteSite,
)


def register_staffing_rules() -> None:
    """Idempotently register the staffing rules."""
    for rule in STAFFING_RULES:
        rule_registry.register(rule(), rule_sets=[STAFFING_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_staffing_rules()
