# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The subcontract rules in the ``pay_application`` set, each held red and green.

A rule that never fires passes every test that only asserts the absence of a
finding, so each rule gets an input it must reject and one it must accept, and
the rejected input's message is checked for the value that makes it
actionable. Two of these rules are errors, and an error blocks the GC claim's
submission, so the "nothing to judge" cases are pinned as hard as the failures:
a claim without subcontract data, or without a period end, must come back
with no finding at all.

The last tests go through the engine by set name, because a rule registered
under a set nobody runs is a rule that never runs, and the engine skips an
unknown set without complaint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry, validation_engine
from app.modules.subcontractors.claim_rules import (
    ROLLUP_KEY,
    SUB_ROLLUP_RULES,
    SubCertificateLapsedRule,
    SubExceedsGcLineRule,
    SubLineUnmappedRule,
    SubPriorUnconditionalMissingRule,
    SubUnapprovedIncludedRule,
    SubWaiverMissingRule,
    pay_application_rule_set,
    register_sub_rollup_context,
    register_sub_rollup_rules,
)
from app.modules.subcontractors.messages import is_key_present

pytestmark = pytest.mark.asyncio

_EN = Path(__file__).resolve().parents[2] / "app" / "modules" / "subcontractors" / "messages" / "en.json"


def _included(**overrides: Any) -> dict[str, Any]:
    row = {
        "payment_application_id": "pa-1",
        "application_number": "PA-7",
        "subcontractor_id": "sub-1",
        "subcontractor_name": "Example Concrete",
        "status": "finance_approved",
        "period_end": "2026-04-30",
        "net_amount": "900.00",
        "requires_lien_waiver": False,
        "waiver": {
            "state": "conditional",
            "amount_covered": "900.00",
            "covers_net": True,
            "through_date": "2026-04-30",
        },
        "certificate_findings": [],
    }
    row.update(overrides)
    return row


def _rollup(**overrides: Any) -> dict[str, Any]:
    rollup: dict[str, Any] = {
        "as_of": "2026-04-30",
        "currency": "USD",
        "pack_requires_lien_waiver": False,
        "included": [_included()],
        "prior_paid": [],
        "unmapped_lines": [],
        "lines": [
            {
                "contract_line_id": "line-1",
                "code": "03.10",
                "scheduled_value": "5000.0000",
                "sub_approved_to_date": "4000.00",
            }
        ],
    }
    rollup.update(overrides)
    return rollup


def _context(rollup: dict[str, Any] | None) -> ValidationContext:
    data: dict[str, Any] = {"claim": {"id": "claim-1"}, "lines": [], "currency": "USD"}
    if rollup is not None:
        data[ROLLUP_KEY] = rollup
    return ValidationContext(data=data, metadata={"locale": "en"})


async def _failures(rule: Any, rollup: dict[str, Any] | None) -> list[Any]:
    return [result for result in await rule.validate(_context(rollup)) if not result.passed]


async def _passes(rule: Any, rollup: dict[str, Any] | None) -> list[Any]:
    return [result for result in await rule.validate(_context(rollup)) if result.passed]


# ── Nothing to judge ────────────────────────────────────────────────────────


@pytest.mark.parametrize("rule_class", SUB_ROLLUP_RULES)
async def test_a_claim_without_subcontract_data_gets_no_row_from_any_rule(rule_class: type) -> None:
    assert await rule_class().validate(_context(None)) == []
    assert await rule_class().validate(_context({})) == []


# ── Each rule, both ways ────────────────────────────────────────────────────


async def test_an_unapproved_pay_application_in_the_claim_is_reported_with_its_status() -> None:
    rule = SubUnapprovedIncludedRule()
    [failure] = await _failures(rule, _rollup(included=[_included(status="submitted")]))
    assert failure.severity == Severity.WARNING
    assert "PA-7 (Example Concrete)" in failure.message
    assert "submitted and not yet reviewed" in failure.message
    assert await _failures(rule, _rollup()) == []
    assert len(await _passes(rule, _rollup())) == 1


async def test_a_missing_waiver_blocks_when_the_agreement_requires_one() -> None:
    rule = SubWaiverMissingRule()
    no_waiver = {"state": "none", "amount_covered": "0", "covers_net": False, "through_date": None}
    [failure] = await _failures(rule, _rollup(included=[_included(requires_lien_waiver=True, waiver=no_waiver)]))
    assert failure.severity == Severity.ERROR
    assert "900.00 USD" in failure.message
    assert failure.details["severity"] == "error"


async def test_a_missing_waiver_only_the_pack_expects_is_a_warning() -> None:
    rule = SubWaiverMissingRule()
    short = {"state": "conditional", "amount_covered": "500.00", "covers_net": False, "through_date": "2026-04-30"}
    [failure] = await _failures(rule, _rollup(pack_requires_lien_waiver=True, included=[_included(waiver=short)]))
    assert failure.severity == Severity.WARNING
    assert "500.00 USD" in failure.message


async def test_a_waiver_through_a_date_before_the_period_end_does_not_cover_it() -> None:
    rule = SubWaiverMissingRule()
    early = {"state": "conditional", "amount_covered": "900.00", "covers_net": True, "through_date": "2026-04-15"}
    [failure] = await _failures(rule, _rollup(included=[_included(requires_lien_waiver=True, waiver=early)]))
    assert "2026-04-15" in failure.message
    assert "2026-04-30" in failure.message
    assert failure.details["reason"] == "through_date"


async def test_a_waiver_nobody_requires_is_not_checked_and_not_claimed_as_checked() -> None:
    rule = SubWaiverMissingRule()
    no_waiver = {"state": "none", "amount_covered": "0", "covers_net": False, "through_date": None}
    assert await rule.validate(_context(_rollup(included=[_included(waiver=no_waiver)]))) == []
    # Required and covered: one green row.
    assert len(await _passes(rule, _rollup(included=[_included(requires_lien_waiver=True)]))) == 1


async def test_a_sub_paid_earlier_without_an_unconditional_waiver_is_reported() -> None:
    rule = SubPriorUnconditionalMissingRule()
    paid = {
        "payment_application_id": "pa-0",
        "application_number": "PA-6",
        "subcontractor_name": "Example Concrete",
        "period_end": "2026-03-31",
        "unconditional_through": None,
    }
    [failure] = await _failures(rule, _rollup(prior_paid=[paid]))
    assert failure.severity == Severity.WARNING
    assert "PA-6" in failure.message
    assert "2026-03-31" in failure.message
    released = {**paid, "unconditional_through": "2026-03-31"}
    assert await _failures(rule, _rollup(prior_paid=[released])) == []
    assert len(await _passes(rule, _rollup(prior_paid=[released]))) == 1
    # No earlier payment at all: nothing was checked, so no green row.
    assert await rule.validate(_context(_rollup())) == []


async def test_an_unmapped_line_is_reported_with_why() -> None:
    rule = SubLineUnmappedRule()
    unmapped = {
        "payment_application_id": "pa-1",
        "application_number": "PA-7",
        "subcontractor_name": "Example Concrete",
        "work_package_name": "Footings",
        "approved_amount": "250.00",
        "reason": "parent_line",
    }
    [failure] = await _failures(rule, _rollup(unmapped_lines=[unmapped]))
    assert "Footings" in failure.message
    assert "250.00 USD" in failure.message
    assert "grouping line" in failure.message
    assert await _failures(rule, _rollup()) == []


async def test_approvals_above_the_scheduled_value_are_reported_outside_rounding_only() -> None:
    rule = SubExceedsGcLineRule()
    over = [
        {
            "contract_line_id": "line-1",
            "code": "03.10",
            "scheduled_value": "5000.0000",
            "sub_approved_to_date": "5000.02",
        }
    ]
    [failure] = await _failures(rule, _rollup(lines=over))
    assert "03.10" in failure.message
    assert "5,000.02 USD" in failure.message
    rounding = [{**over[0], "sub_approved_to_date": "5000.01"}]
    assert await _failures(rule, _rollup(lines=rounding)) == []


async def test_a_lapsed_certificate_blocks_and_is_named_in_words() -> None:
    rule = SubCertificateLapsedRule()
    lapsed = _included(
        certificate_findings=[{"document_type": "insurance", "state": "expired", "lapsed_on": "2026-04-15"}]
    )
    [failure] = await _failures(rule, _rollup(included=[lapsed]))
    assert failure.severity == Severity.ERROR
    assert "Example Concrete" in failure.message
    assert "insurance certificate" in failure.message
    assert "2026-04-30" in failure.message
    assert await _failures(rule, _rollup()) == []
    assert len(await _passes(rule, _rollup())) == 1


async def test_a_certificate_type_the_bundle_has_no_word_for_is_printed_as_it_is() -> None:
    rule = SubCertificateLapsedRule()
    odd = _included(certificate_findings=[{"document_type": "new_pack_clearance", "state": "missing"}])
    [failure] = await _failures(rule, _rollup(included=[odd]))
    assert "new_pack_clearance" in failure.message
    assert "pay_application." not in failure.message


async def test_certificates_without_a_period_end_are_neither_failed_nor_passed() -> None:
    rule = SubCertificateLapsedRule()
    lapsed = _included(certificate_findings=[{"document_type": "insurance", "state": "expired"}])
    assert await rule.validate(_context(_rollup(as_of=None, included=[lapsed]))) == []


# ── Messages ────────────────────────────────────────────────────────────────


async def test_every_message_key_a_rule_can_ask_for_exists_in_english() -> None:
    keys = ["common.ok"]
    for rule_class in SUB_ROLLUP_RULES:
        keys.append(f"{rule_class.rule_id}.suggestion")
    keys += [
        "pay_application.sub_unapproved_included.fail",
        "pay_application.sub_waiver_missing.fail_amount",
        "pay_application.sub_waiver_missing.fail_through_date",
        "pay_application.sub_prior_unconditional_missing.fail",
        "pay_application.sub_line_unmapped.fail_none",
        "pay_application.sub_line_unmapped.fail_foreign_line",
        "pay_application.sub_line_unmapped.fail_parent_line",
        "pay_application.sub_exceeds_gc_line.fail",
        "pay_application.sub_certificate_lapsed.fail_missing",
        "pay_application.sub_certificate_lapsed.fail_expired",
        "pay_application.sub_certificate_lapsed.fail_revoked",
    ]
    from app.modules.subcontractors.validators import PAYMENT_DATE_STATES

    keys += [f"pay_application.sub_certificate_payment_date.fail_{state}" for state in PAYMENT_DATE_STATES]
    keys += [
        f"pay_application.sub_certificate_payment_date.withholding.{kind}"
        for kind in ("gross_limit", "gross", "net_limit", "net", "unknown")
    ]
    missing = [key for key in keys if not is_key_present(key, "en")]
    assert missing == []


def _flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{path}."))
        else:
            flat[path] = str(value)
    return flat


@pytest.mark.parametrize("locale", ["de", "ru"])
async def test_every_shipped_locale_answers_every_key_with_the_same_placeholders(locale: str) -> None:
    """A translation missing a key falls back to English; one missing a placeholder drops the value.

    The second is the worse failure: the sentence reads fine and no longer
    says which pay application or how much.
    """
    import string

    english = _flatten(json.loads(_EN.read_text(encoding="utf-8")))
    other = _flatten(json.loads((_EN.parent / f"{locale}.json").read_text(encoding="utf-8")))
    assert sorted(other) == sorted(english)

    def fields(text: str) -> set[str]:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    mismatched = [key for key in english if fields(english[key]) != fields(other[key])]
    assert mismatched == []


async def test_every_certificate_type_the_api_accepts_has_a_word() -> None:
    from app.modules.subcontractors.schemas import _CERT_TYPE_PATTERN

    types = _CERT_TYPE_PATTERN.removeprefix("^(").removesuffix(")$").split("|")
    documents = json.loads(_EN.read_text(encoding="utf-8"))["pay_application"]["sub_certificate_lapsed"]["documents"]
    assert sorted(types) == sorted(documents)


# ── Registration and the engine ─────────────────────────────────────────────


async def test_the_rules_join_the_set_the_contracts_module_runs_on_submission() -> None:
    from app.modules.contracts.validators import PAY_APPLICATION_RULE_SET, register_contracts_validation_rules

    register_contracts_validation_rules()
    assert register_sub_rollup_rules() == PAY_APPLICATION_RULE_SET
    assert pay_application_rule_set() == PAY_APPLICATION_RULE_SET
    registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([PAY_APPLICATION_RULE_SET])}
    assert {rule_class.rule_id for rule_class in SUB_ROLLUP_RULES} <= registered
    # The contracts half is still there: joining the set did not replace it.
    assert "pay_application.line_overbilled" in registered


async def test_the_engine_runs_them_by_set_name_and_finds_both_ways() -> None:
    from app.modules.contracts.validators import PAY_APPLICATION_RULE_SET

    register_sub_rollup_rules()
    claim = {"id": "claim-1", "number": "PC-4", "period_from": "2026-04-01", "period_to": "2026-04-30"}
    base = {"claim": claim, "previous_claim": None, "lines": [], "currency": "USD", "as_of": "2026-04-30"}

    clean = await validation_engine.validate(
        data={**base, ROLLUP_KEY: _rollup()},
        rule_sets=[PAY_APPLICATION_RULE_SET],
        target_type="progress_claim",
        metadata={"locale": "en"},
    )
    assert clean.unsupported_rule_sets == []
    assert not clean.has_errors

    lapsed = _included(
        requires_lien_waiver=True,
        waiver={"state": "none", "amount_covered": "0", "covers_net": False, "through_date": None},
        certificate_findings=[{"document_type": "license", "state": "missing"}],
    )
    dirty = await validation_engine.validate(
        data={**base, ROLLUP_KEY: _rollup(included=[lapsed])},
        rule_sets=[PAY_APPLICATION_RULE_SET],
        target_type="progress_claim",
        metadata={"locale": "en"},
    )
    failed = {result.rule_id for result in dirty.errors}
    assert {"pay_application.sub_waiver_missing", "pay_application.sub_certificate_lapsed"} <= failed


# ── The rollup reaches contracts through its registry, not an import ──────


@pytest.fixture
def empty_claim_context(monkeypatch):
    """The contracts claim-context registry, emptied for one test."""
    from app.modules.contracts import claim_context

    monkeypatch.setattr(claim_context, "_providers", {})
    return claim_context


async def test_startup_hands_contracts_the_rollup_under_the_key_the_rules_read(empty_claim_context) -> None:
    # Rules without their data judge nothing and say nothing: registering one
    # half at startup and not the other is the failure this pins.
    from app.modules.subcontractors import on_startup
    from app.modules.subcontractors.rollup import claim_rule_context

    await on_startup()
    assert empty_claim_context._providers == {ROLLUP_KEY: claim_rule_context}


async def test_the_registered_provider_is_what_contracts_collects(empty_claim_context, monkeypatch) -> None:
    from app.modules.subcontractors import rollup

    seen: list[Any] = []

    async def fake_rollup(session, claim):
        seen.append(claim)
        return {"included": []}

    # Registration looks the function up when it runs, so the stand-in is
    # what lands in the registry.
    monkeypatch.setattr(rollup, "claim_rule_context", fake_rollup)
    assert register_sub_rollup_context() is True
    claim = object()
    assert await empty_claim_context.collect_claim_context(None, claim) == {ROLLUP_KEY: {"included": []}}
    assert seen == [claim]


async def test_without_the_contracts_module_there_is_nothing_to_register_with(empty_claim_context, monkeypatch) -> None:
    import sys

    # ``None`` in sys.modules makes the import raise ModuleNotFoundError for
    # exactly that name, which is what an install without contracts raises.
    monkeypatch.setitem(sys.modules, "app.modules.contracts.claim_context", None)
    assert register_sub_rollup_context() is False
    assert empty_claim_context._providers == {}


async def test_a_broken_contracts_module_is_not_mistaken_for_an_absent_one(monkeypatch) -> None:
    import sys
    import types

    # The module is there but lacks the function: a defect, which must surface
    # rather than quietly leave every claim without its rollup.
    monkeypatch.setitem(sys.modules, "app.modules.contracts.claim_context", types.ModuleType("claim_context"))
    with pytest.raises(ImportError):
        register_sub_rollup_context()
