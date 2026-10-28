# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the ``subcontract`` validation rule set.

Three layers, because each catches something the others cannot:

* the pure checks in ``subcontractors.validators``, called directly, which pins
  what they return for a given agreement;
* the engine contract, which pins what the report makes of those returns, since
  a rule can be correct and still be filtered out of ``report.errors``;
* reachability, which pins that a caller passes the set by name. A rule set
  nobody passes never runs, and every test above it still passes -- three
  ``ai_takeoff`` rules shipped that way.

No database. The clock arrives as data (``as_of``) so none of this rots.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from app.core.validation.engine import Severity, rule_registry, validation_engine
from app.core.validation.rules import (
    SubcontractAgreementCurrencySet,
    SubcontractAgreementDatesOrdered,
    SubcontractAgreementHasScope,
    SubcontractAgreementValuePositive,
    SubcontractInsuranceValidAtStart,
    SubcontractPackageScopeDescribed,
    SubcontractPackagesWithinValue,
    SubcontractRetentionWithinBounds,
    register_builtin_rules,
)
from app.modules.subcontractors import validators as checks

SUBCONTRACT_RULES = [
    SubcontractAgreementHasScope,
    SubcontractPackageScopeDescribed,
    SubcontractAgreementValuePositive,
    SubcontractPackagesWithinValue,
    SubcontractAgreementDatesOrdered,
    SubcontractAgreementCurrencySet,
    SubcontractRetentionWithinBounds,
    SubcontractInsuranceValidAtStart,
]

TODAY = "2026-07-26"


def _agreement(**overrides: object) -> dict:
    """A clean agreement: every check passes unless a test breaks one."""
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Mechanical fit-out",
        "status": "draft",
        "currency": "EUR",
        "total_value": "250000.00",
        "retention_percent": "5.00",
        "start_date": "2026-08-01",
        "end_date": "2026-12-20",
        "insurance_expiry_date": "2027-01-31",
        "as_of": TODAY,
        "work_packages": [
            {
                "name": "Ductwork",
                "scope": "Supply and install ductwork to levels 1-4",
                "planned_value": "150000.00",
                "status": "planned",
            },
            {
                "name": "Plant",
                "scope": "AHU installation and commissioning",
                "planned_value": "100000.00",
                "status": "planned",
            },
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestHasScope:
    def test_a_clean_agreement_passes(self) -> None:
        assert checks.check_has_scope(_agreement()) == []

    def test_no_work_packages_is_reported(self) -> None:
        findings = checks.check_has_scope(_agreement(work_packages=[]))
        assert len(findings) == 1
        assert findings[0].element_ref == "Mechanical fit-out"
        assert findings[0].details["work_package_count"] == 0

    def test_a_malformed_packages_value_counts_as_none(self) -> None:
        """A non-list in the payload must not crash the rule.

        The payload is built by the service, but a rule that raises on odd data
        takes the whole report down and hides every other finding with it.
        """
        assert len(checks.check_has_scope(_agreement(work_packages="oops"))) == 1
        assert len(checks.check_has_scope(_agreement(work_packages=None))) == 1


class TestPackageScopeDescribed:
    def test_described_packages_pass(self) -> None:
        assert checks.check_package_scope_described(_agreement()) == []

    def test_a_package_without_scope_is_reported_by_name(self) -> None:
        agreement = _agreement(
            work_packages=[
                {"name": "Ductwork", "scope": "", "planned_value": "1.00", "status": "planned"},
            ]
        )
        findings = checks.check_package_scope_described(agreement)
        assert len(findings) == 1
        assert findings[0].element_ref == "1 (Ductwork)"

    def test_every_undescribed_package_is_reported_not_just_the_first(self) -> None:
        agreement = _agreement(
            work_packages=[
                {"name": "A", "scope": None, "planned_value": "1.00", "status": "planned"},
                {"name": "B", "scope": "   ", "planned_value": "1.00", "status": "planned"},
                {"name": "C", "scope": "real scope", "planned_value": "1.00", "status": "planned"},
            ]
        )
        findings = checks.check_package_scope_described(agreement)
        assert [f.element_ref for f in findings] == ["1 (A)", "2 (B)"]


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


class TestValuePositive:
    def test_a_positive_value_passes(self) -> None:
        assert checks.check_value_positive(_agreement()) == []

    @pytest.mark.parametrize("value", ["0", "0.00", "-1.00"])
    def test_zero_or_negative_is_reported(self, value: str) -> None:
        findings = checks.check_value_positive(_agreement(total_value=value))
        assert len(findings) == 1

    def test_an_unparseable_value_is_reported_rather_than_raised(self) -> None:
        findings = checks.check_value_positive(_agreement(total_value="one hundred"))
        assert len(findings) == 1
        assert findings[0].details["reason"] == "unparseable_total_value"


class TestPackagesWithinValue:
    def test_packages_inside_the_contract_pass(self) -> None:
        assert checks.check_packages_within_value(_agreement()) == []

    def test_packages_exactly_equal_to_the_contract_pass(self) -> None:
        """The common case: the packages are the contract, to the cent."""
        assert checks.check_packages_within_value(_agreement(total_value="250000.00")) == []

    def test_packages_worth_more_than_the_contract_are_reported(self) -> None:
        findings = checks.check_packages_within_value(_agreement(total_value="200000.00"))
        assert len(findings) == 1
        assert findings[0].params["planned"] == "250,000.00 EUR"
        assert findings[0].params["total"] == "200,000.00 EUR"

    def test_a_cent_of_rounding_is_not_an_overrun(self) -> None:
        agreement = _agreement(
            total_value="100.00",
            work_packages=[
                {"name": "A", "scope": "s", "planned_value": "100.01", "status": "planned"},
            ],
        )
        assert checks.check_packages_within_value(agreement) == []

    def test_an_agreement_with_no_packages_is_left_to_the_scope_rule(self) -> None:
        """One problem, one finding. Double-counting makes a report harder to act on."""
        assert checks.check_packages_within_value(_agreement(work_packages=[])) == []


class TestRetentionWithinBounds:
    def test_a_normal_retention_passes(self) -> None:
        assert checks.check_retention_within_bounds(_agreement()) == []

    @pytest.mark.parametrize("percent", ["0", "50", "49.99"])
    def test_the_boundary_is_inclusive(self, percent: str) -> None:
        assert checks.check_retention_within_bounds(_agreement(retention_percent=percent)) == []

    @pytest.mark.parametrize("percent", ["-1", "50.01", "5000"])
    def test_outside_the_range_is_reported(self, percent: str) -> None:
        assert len(checks.check_retention_within_bounds(_agreement(retention_percent=percent))) == 1

    def test_an_amount_typed_as_a_rate_is_what_this_catches(self) -> None:
        """The failure this rule exists for: 12 500 entered where 5 belonged."""
        findings = checks.check_retention_within_bounds(_agreement(retention_percent="12500.00"))
        assert len(findings) == 1
        assert findings[0].params["percent"] == "12500.00"
        assert findings[0].params["max"] == "50.00"


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


class TestDatesOrdered:
    def test_a_forward_period_passes(self) -> None:
        assert checks.check_dates_ordered(_agreement()) == []

    def test_a_single_day_contract_passes(self) -> None:
        assert checks.check_dates_ordered(_agreement(start_date="2026-08-01", end_date="2026-08-01")) == []

    def test_an_end_before_the_start_is_reported(self) -> None:
        findings = checks.check_dates_ordered(_agreement(start_date="2026-09-01", end_date="2026-08-01"))
        assert len(findings) == 1
        assert findings[0].params == {"start": "2026-09-01", "end": "2026-08-01"}

    @pytest.mark.parametrize("missing", ["start_date", "end_date"])
    def test_a_missing_date_is_not_an_ordering_finding(self, missing: str) -> None:
        """Absence is the completeness rules' business, not this one's."""
        assert checks.check_dates_ordered(_agreement(**{missing: None})) == []


class TestInsuranceValidAtStart:
    def test_current_insurance_passes(self) -> None:
        assert checks.check_insurance_valid_at_start(_agreement()) == []

    def test_insurance_expiring_before_work_starts_is_reported(self) -> None:
        findings = checks.check_insurance_valid_at_start(_agreement(insurance_expiry_date="2026-07-01"))
        assert len(findings) == 1
        assert findings[0].params == {"expiry": "2026-07-01", "reference": "2026-08-01"}

    def test_insurance_expiring_exactly_on_the_start_date_passes(self) -> None:
        assert checks.check_insurance_valid_at_start(_agreement(insurance_expiry_date="2026-08-01")) == []

    def test_an_unknown_expiry_is_not_treated_as_expired(self) -> None:
        """A missing certificate is the certificate register's problem.

        Calling an unknown date expired would make this rule fire on every
        agreement whose insurance is tracked outside the platform, which trains
        people to ignore it.
        """
        assert checks.check_insurance_valid_at_start(_agreement(insurance_expiry_date=None)) == []

    def test_without_a_start_date_the_supplied_clock_is_used(self) -> None:
        agreement = _agreement(start_date=None, insurance_expiry_date="2026-07-01")
        findings = checks.check_insurance_valid_at_start(agreement)
        assert len(findings) == 1
        assert findings[0].params["reference"] == TODAY

    def test_no_rule_in_this_module_reads_the_system_clock(self) -> None:
        """The clock is data. A rule that calls ``today()`` cannot be pinned.

        Walks the syntax tree rather than grepping the text, so the prose in the
        module docstring explaining this rule does not satisfy it.
        """
        tree = ast.parse(inspect.getsource(checks))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "today" not in called
        assert "now" not in called
        assert "utcnow" not in called


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------


class TestCurrencySet:
    def test_a_currency_passes(self) -> None:
        assert checks.check_currency_set(_agreement()) == []

    @pytest.mark.parametrize("currency", ["", "   ", None])
    def test_a_blank_currency_is_reported(self, currency: str | None) -> None:
        """The column's server default is an empty string, so blank is reachable."""
        assert len(checks.check_currency_set(_agreement(currency=currency))) == 1


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


class TestReachability:
    def test_all_eight_rules_are_registered_under_the_subcontract_set(self) -> None:
        register_builtin_rules()
        registered = {r.rule_id for r in rule_registry.get_rules_for_sets(["subcontract"])}
        assert {rule_cls.rule_id for rule_cls in SUBCONTRACT_RULES}.issubset(registered)

    def test_the_subcontract_set_is_one_a_caller_actually_passes(self) -> None:
        """The ai_takeoff guard, applied here.

        A rule registered with ``rule_sets=None`` lands in the set named by its
        ``standard`` and never runs unless somebody passes that name. If the
        call site below is deleted or renamed, these eight rules go dead while
        every behaviour test above still passes, so this is the test that
        notices.
        """
        from app.modules.subcontractors.service import SUBCONTRACT_RULE_SET, SubcontractorService

        assert SUBCONTRACT_RULE_SET == "subcontract"
        source = inspect.getsource(SubcontractorService._validate_agreement)
        assert "SUBCONTRACT_RULE_SET" in source
        assert "validation_engine.validate" in source

    def test_activation_consults_validation(self) -> None:
        """Going live must run the checks, not merely offer an endpoint."""
        from app.modules.subcontractors.service import SubcontractorService

        source = inspect.getsource(SubcontractorService.update_agreement)
        assert "_report_agreement_validation" in source

    def test_activation_reports_rather_than_refuses(self) -> None:
        """A deliberate choice, pinned so a later change is a decision.

        Activation already has two hard gates (the state machine and the
        prequalification check). These rules report; promoting them to a refusal
        is a one-line change in ``_report_agreement_validation``, and it should
        be made knowingly rather than by drift.
        """
        from app.modules.subcontractors.service import SubcontractorService

        source = inspect.getsource(SubcontractorService._report_agreement_validation)
        assert "raise" not in source
        assert "logger.warning" in source

    def test_the_read_only_endpoint_exists_for_the_same_set(self) -> None:
        from app.modules.subcontractors.service import SubcontractorService

        source = inspect.getsource(SubcontractorService.validate_agreement)
        assert "_validate_agreement" in source


# ---------------------------------------------------------------------------
# Engine contract
# ---------------------------------------------------------------------------


class TestEngineContract:
    """What a caller reads: the report, not the check's return value.

    Every rule emits a row on success too, so a passing agreement produces
    ``ERROR``-severity rows with ``passed=True``. If ``errors`` ever filtered on
    severity alone rather than on failure, a clean agreement would look broken
    and the detail would list "OK" messages. No database.
    """

    async def _report(self, agreement: dict):
        register_builtin_rules()
        return await validation_engine.validate(
            data=agreement,
            rule_sets=["subcontract"],
            target_type="subcontract_agreement",
            target_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            metadata={"locale": "en"},
        )

    async def test_a_clean_agreement_has_no_errors(self) -> None:
        report = await self._report(_agreement())
        assert not report.has_errors
        assert report.errors == []

    async def test_a_single_isolated_error_is_reported_alone(self) -> None:
        report = await self._report(_agreement(currency=""))
        assert [r.rule_id for r in report.errors] == ["subcontract.agreement_currency_set"]

    async def test_an_advisory_finding_never_becomes_an_error(self) -> None:
        agreement = _agreement(
            work_packages=[
                {"name": "Ductwork", "scope": "", "planned_value": "1.00", "status": "planned"},
            ]
        )
        report = await self._report(agreement)
        assert not report.has_errors
        assert "subcontract.package_scope_described" in {r.rule_id for r in report.warnings}

    async def test_every_problem_is_listed_at_once(self) -> None:
        """A report that stops at the first problem makes the user rediscover the rest."""
        report = await self._report(_agreement(currency="", total_value="0", work_packages=[]))
        assert {r.rule_id for r in report.errors} >= {
            "subcontract.agreement_currency_set",
            "subcontract.agreement_value_positive",
            "subcontract.agreement_has_scope",
        }

    async def test_the_message_is_translated_not_a_key(self) -> None:
        report = await self._report(_agreement(currency=""))
        message = report.errors[0].message
        assert "subcontract." not in message
        assert "currency" in message.lower()

    async def test_the_rule_set_resolves(self) -> None:
        register_builtin_rules()
        assert rule_registry.has_rules("subcontract")

    async def test_severity_survives_the_round_trip(self) -> None:
        report = await self._report(_agreement(currency=""))
        assert report.errors[0].severity is Severity.ERROR
