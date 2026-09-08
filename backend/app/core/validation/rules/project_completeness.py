# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``project_completeness`` rule set: is the project record fit to estimate against.

Twenty two shipped demo templates asked for this set by name and no rule
registered into it. The engine logged "0 rules registered" and carried on, so
twenty two dashboards listed a completeness check that never ran. The rules
below are what an estimator expects that check to be. They read the project,
not the bill: the country the rates are for, the currency the money is in, the
standard the codes follow, the dates the programme runs between, the client the
estimate is addressed to, whether there is a priced bill at all, and, once the
project has moved past estimating, whether procurement has begun.

Every rule reads the project record that
:func:`app.core.validation.project_context.with_project_context` puts in the
payload, under :data:`~app.core.validation.project_context.PROJECT_RECORD_KEY`.
A payload without that key was assembled by a surface that never asked about
the project, and a null under it means the question was asked and the project
could not be found. Both leave every rule silent, on purpose: a completeness
finding about a project the rule has not seen would be a finding about the
payload, and nothing on the dashboard could clear it.

Two of the facts are errors and the rest are warnings. A missing country or
currency does not make the estimate incomplete, it makes it unreadable: no
regional pack, no tax, no markup region, no exchange rate can be resolved for
it, so every downstream figure is a guess. The rest are gaps an estimator
closes before the document leaves the office, and a warning is the right
weight for a gap that does not yet corrupt a number.

The rules live in their own module rather than in the package ``__init__``
alongside every other built-in set because the built-in file is nine
thousand lines and edited from several directions at once; the registration
in ``register_builtin_rules`` is the only line the two share.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.project_context import PROJECT_RECORD_KEY
from app.core.validation.rules import _get_locale, _get_positions, _ok, _position_currency

#: The set every rule here registers into, and the prefix of every rule id.
PROJECT_COMPLETENESS_RULE_SET = "project_completeness"

#: Project phases at which estimating is over and procurement is expected to
#: have started. The vocabulary is the project wizard's own; a phase outside it
#: (including none) is read as "still estimating, or not stated" and the
#: procurement rule stays silent rather than guessing at the stage.
POST_ESTIMATING_PHASES: frozenset[str] = frozenset({"tender", "procurement", "construction", "handover"})

#: Classification values that mean no standard was chosen. The column has a
#: default, so an empty string is rare; "none" is what the matching settings
#: write when the user opts out of a classifier, and it is not a standard.
_NO_STANDARD: frozenset[str] = frozenset({"", "none", "null"})


def _record(context: ValidationContext) -> dict[str, Any] | None:
    """The project record the payload carries, or ``None`` when there is none to judge."""
    data = context.data
    if not isinstance(data, dict):
        return None
    record = data.get(PROJECT_RECORD_KEY)
    return record if isinstance(record, dict) else None


def _text(value: Any) -> str:
    """A stripped string, or ``""`` for null and non-string values."""
    return value.strip() if isinstance(value, str) else ""


def _read_date(value: Any) -> date | None:
    """Parse a stored project date, which is a string column and may be a full timestamp."""
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _bill_base_date(bill: dict[str, Any]) -> str:
    """The base date a bill states, on its own column or in the metadata it was imported with.

    Same lookup order as the NRM base date rule: the column first, then the
    ``base_date`` and ``price_level`` keys the demo templates and the importers
    write into the bill's metadata.
    """
    if _text(bill.get("base_date")):
        return _text(bill.get("base_date"))
    meta = bill.get("metadata")
    if not isinstance(meta, dict):
        return ""
    return _text(meta.get("base_date")) or _text(meta.get("price_level"))


class _ProjectRule(ValidationRule):
    """Shared shape: one result per rule, silent without a project record."""

    standard = PROJECT_COMPLETENESS_RULE_SET
    category = RuleCategory.COMPLETENESS

    def _result(
        self,
        locale: str,
        *,
        passed: bool,
        fail_key: str,
        details: dict[str, Any],
        element_ref: str | None = None,
        **params: Any,
    ) -> RuleResult:
        message_key = f"{self.rule_id}.{fail_key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=_ok(locale) if passed else translate(message_key, locale=locale, **params),
            element_ref=element_ref,
            details=details,
            suggestion=None if passed else translate(f"{self.rule_id}.suggestion", locale=locale, **params),
        )


class ProjectCountrySet(_ProjectRule):
    """The project names the country its rates, tax and calendar are for.

    The country code alone counts. ``region`` is not evidence of a choice: the
    column has a non-null default, so every project carries one whether or not
    anybody picked it, and a rule that accepted it would never fail.
    """

    rule_id = "project_completeness.country_set"
    name = "Project Country Set"
    severity = Severity.ERROR
    description = "The project must name the country whose prices, tax and working calendar apply"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        country = _text(record.get("country_code")).upper()
        passed = len(country) == 2 and country.isalpha()
        return [
            self._result(
                _get_locale(context),
                passed=passed,
                fail_key="fail",
                details={"country_code": country or None, "region": record.get("region")},
            )
        ]


class ProjectCurrencySet(_ProjectRule):
    """The project states the currency its money is in."""

    rule_id = "project_completeness.currency_set"
    name = "Project Currency Set"
    severity = Severity.ERROR
    description = "The project must state the currency every bill, markup and contract is priced in"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        currency = _text(record.get("currency")).upper()
        return [
            self._result(
                _get_locale(context),
                passed=bool(currency),
                fail_key="fail",
                details={"currency": currency or None},
            )
        ]


class ProjectCurrencyMatchesBill(_ProjectRule):
    """Every priced row of the bill under validation is in the project's currency.

    Silent when the project has no currency (the rule above speaks) and when no
    row records one: a bill whose rows carry no currency is priced in the
    project's by definition, and there is nothing to disagree with.
    """

    rule_id = "project_completeness.currency_matches_bill"
    name = "Project Currency Matches the Bill"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Rows priced in a currency other than the project's cannot be summed into its total"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        project_currency = _text(record.get("currency")).upper()
        if not project_currency:
            return []
        stated = [_position_currency(pos) for pos in _get_positions(context) if isinstance(pos, dict)]
        found = sorted({currency for currency in stated if currency})
        if not found:
            return []
        foreign = [currency for currency in found if currency != project_currency]
        return [
            self._result(
                _get_locale(context),
                passed=not foreign,
                fail_key="fail",
                details={
                    "project_currency": project_currency,
                    "bill_currencies": found,
                    "rows_in_other_currency": sum(
                        1 for currency in stated if currency and currency != project_currency
                    ),
                },
                project_currency=project_currency,
                bill_currencies=", ".join(foreign),
            )
        ]


class ProjectHasPricedBill(_ProjectRule):
    """At least one of the project's bills of quantities has rows in it.

    Silent when the payload does not say which bills exist (a null list), which
    is the case for a surface that could not ask the database.
    """

    rule_id = "project_completeness.priced_bill_present"
    name = "Project Has a Bill with Positions"
    severity = Severity.WARNING
    description = "A project with no bill of quantities, or only empty ones, has nothing to estimate from"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None or not isinstance(record.get("bills"), list):
            return []
        bills = [bill for bill in record["bills"] if isinstance(bill, dict)]
        with_rows = [bill for bill in bills if int(bill.get("position_count") or 0) > 0]
        return [
            self._result(
                _get_locale(context),
                passed=bool(with_rows),
                fail_key="fail",
                details={"bills": len(bills), "bills_with_positions": len(with_rows)},
            )
        ]


class ProjectBillsHaveBaseDate(_ProjectRule):
    """Every bill states the date its rates are current at, one result per bill.

    The element reference is the bill id, so a finding links to the bill it is
    about. A project with no bills produces nothing here; that gap belongs to
    the rule above and reporting it twice would count it twice in the score.
    """

    rule_id = "project_completeness.bill_base_date_set"
    name = "Every Bill States Its Base Date"
    severity = Severity.WARNING
    description = "A bill without a base date cannot be indexed, taxed at its own date or compared to another"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None or not isinstance(record.get("bills"), list):
            return []
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for bill in record["bills"]:
            if not isinstance(bill, dict):
                continue
            base_date = _bill_base_date(bill)
            results.append(
                self._result(
                    locale,
                    passed=bool(base_date),
                    fail_key="fail",
                    element_ref=_text(bill.get("id")) or None,
                    details={"bill": bill.get("name"), "base_date": base_date or None},
                    bill=_text(bill.get("name")) or _text(bill.get("id")),
                )
            )
        return results


class ProjectClassificationStandardSet(_ProjectRule):
    """The project has chosen the classification standard its positions are coded to."""

    rule_id = "project_completeness.classification_standard_set"
    name = "Project Classification Standard Set"
    severity = Severity.WARNING
    description = "Without a classification standard no country rule set can be derived and no code can be checked"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        standard = _text(record.get("classification_standard")).lower()
        return [
            self._result(
                _get_locale(context),
                passed=standard not in _NO_STANDARD,
                fail_key="fail",
                details={"classification_standard": standard or None},
            )
        ]


class ProjectDatesSet(_ProjectRule):
    """Both planned dates are recorded and each reads as a date.

    Four failure messages rather than one with a parameter: the word that
    changes between them is "start" and "end", and a word passed as a
    parameter cannot be translated.
    """

    rule_id = "project_completeness.planned_dates_set"
    name = "Project Planned Dates Set"
    severity = Severity.WARNING
    description = "A project without a planned start and end has no programme to price time-related cost against"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        start_text = _text(record.get("planned_start_date"))
        end_text = _text(record.get("planned_end_date"))
        start, end = _read_date(start_text), _read_date(end_text)
        details = {"planned_start_date": start_text or None, "planned_end_date": end_text or None}
        unreadable = next(
            (text for text, parsed in ((start_text, start), (end_text, end)) if text and not parsed), None
        )
        if unreadable is not None:
            fail_key, params = "unreadable", {"value": unreadable}
        elif not start_text and not end_text:
            fail_key, params = "both_missing", {}
        elif not start_text:
            fail_key, params = "start_missing", {}
        else:
            fail_key, params = "end_missing", {}
        return [
            self._result(
                _get_locale(context),
                passed=start is not None and end is not None,
                fail_key=fail_key,
                details=details,
                **params,
            )
        ]


class ProjectDatesOrdered(_ProjectRule):
    """The planned start is not after the planned end. Silent unless both dates read."""

    rule_id = "project_completeness.planned_dates_ordered"
    name = "Project Planned Start Before End"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A programme that ends before it starts has a negative duration and prices time backwards"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        start, end = _read_date(record.get("planned_start_date")), _read_date(record.get("planned_end_date"))
        if start is None or end is None:
            return []
        return [
            self._result(
                _get_locale(context),
                passed=start <= end,
                fail_key="fail",
                details={"planned_start_date": start.isoformat(), "planned_end_date": end.isoformat()},
                start=start.isoformat(),
                end=end.isoformat(),
            )
        ]


class ProjectClientRecorded(_ProjectRule):
    """The project records who it is for: a client on the project, or an employer party on a contract."""

    rule_id = "project_completeness.client_recorded"
    name = "Project Client Recorded"
    severity = Severity.WARNING
    description = "An estimate is addressed to somebody; a project with no client or employer has no addressee"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        client_id = _text(record.get("client_id"))
        parties = record.get("client_party_count")
        party_count = int(parties) if isinstance(parties, int) else 0
        return [
            self._result(
                _get_locale(context),
                passed=bool(client_id) or party_count > 0,
                fail_key="fail",
                details={"client_id": client_id or None, "client_party_count": parties},
            )
        ]


class ProjectProcurementStarted(_ProjectRule):
    """Past the estimating stage, the project has at least one contract or tender package.

    Applies only when the project states a phase in
    :data:`POST_ESTIMATING_PHASES`. Silent when neither the contracts nor the
    tendering module could be asked, because "no register" and "an empty
    register" are different facts and only the second is a finding.
    """

    rule_id = "project_completeness.procurement_started"
    name = "Procurement Started Past the Estimating Stage"
    severity = Severity.WARNING
    description = "A project in tender or later with no contract and no tender package is estimating in name only"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if record is None:
            return []
        phase = _text(record.get("phase")).lower()
        if phase not in POST_ESTIMATING_PHASES:
            return []
        contracts = record.get("contract_count")
        tenders = record.get("tender_count")
        if not isinstance(contracts, int) and not isinstance(tenders, int):
            return []
        contract_count = contracts if isinstance(contracts, int) else 0
        tender_count = tenders if isinstance(tenders, int) else 0
        return [
            self._result(
                _get_locale(context),
                passed=contract_count > 0 or tender_count > 0,
                fail_key="fail",
                details={"phase": phase, "contract_count": contracts, "tender_count": tenders},
                phase=phase,
            )
        ]


#: Every rule in the set, in the order the dashboard should list them. The
#: registration in ``register_builtin_rules`` instantiates these; the tuple of
#: classes rather than instances keeps that call idempotent in the same way
#: the sibling sets are, one fresh instance per call.
PROJECT_COMPLETENESS_RULES: tuple[type[ValidationRule], ...] = (
    ProjectCountrySet,
    ProjectCurrencySet,
    ProjectCurrencyMatchesBill,
    ProjectHasPricedBill,
    ProjectBillsHaveBaseDate,
    ProjectClassificationStandardSet,
    ProjectDatesSet,
    ProjectDatesOrdered,
    ProjectClientRecorded,
    ProjectProcurementStarted,
)

__all__ = [
    "POST_ESTIMATING_PHASES",
    "PROJECT_COMPLETENESS_RULES",
    "PROJECT_COMPLETENESS_RULE_SET",
    "ProjectBillsHaveBaseDate",
    "ProjectClassificationStandardSet",
    "ProjectClientRecorded",
    "ProjectCountrySet",
    "ProjectCurrencyMatchesBill",
    "ProjectCurrencySet",
    "ProjectDatesOrdered",
    "ProjectDatesSet",
    "ProjectHasPricedBill",
    "ProjectProcurementStarted",
]
