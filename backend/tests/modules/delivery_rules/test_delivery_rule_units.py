"""The service, signing, value, prefab and preliminaries rule sets: each rule fires, a valid record passes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as bundle
from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.prefab import validators as pv
from app.modules.preliminaries import validators as plv
from app.modules.service import validators as sv
from app.modules.signing import validators as gv
from app.modules.value import validators as vv

TODAY = "2026-11-04"
NOW = "2026-11-04T12:00:00+00:00"


async def _run(rule, data, locale="en"):
    context = ValidationContext(data=data, metadata={"locale": locale, "today": TODAY, "now": NOW})
    return await rule().validate(context)


def _contract(**kw):
    base = {
        "id": "c1",
        "period_start": "2026-01-01",
        "period_end": "2027-12-31",
        "status": "active",
        "value": "1000",
        "currency": "EUR",
    }
    return {"contract": {**base, **kw}}


def _wo(status="completed", items=None):
    items = [{"id": "i1", "quantity": "2", "unit_rate": "10", "total": "20"}] if items is None else items
    return {"work_order": {"id": "w1", "status": status, "currency": "EUR"}, "items": items}


def _session(**kw):
    base = {
        "id": "s1",
        "status": "awaiting_signatures",
        "expires_at": "2027-01-01T00:00:00+00:00",
        "signatory_map": [{"name": "A", "role": "owner", "required": True}],
        "document_content_hash": "abc",
    }
    return {"session": {**base, **kw}}


def _signature(**kw):
    return {**_session(), "signature": {"signed_at": NOW, "content_hash": "abc", "signatory_role": "owner", **kw}}


def _unit(**kw):
    base = {
        "id": "u1",
        "ref": "M-01",
        "operation": "update",
        "status": "design",
        "target_install_date": "2027-03-01",
        "bim_element_ids": ["a", "b"],
    }
    return {"unit": {**base, **kw}}


def _item(**kw):
    base = {
        "id": "p1",
        "label": "Site hoarding",
        "item_type": "time_related",
        "rate_per_period": "500",
        "periods": "12",
        "fixed_amount": "0",
    }
    return {"item": {**base, **kw}}


def _factors(*rows):
    return {"factors": list(rows)}


def _f(module="rfi", action="rfi_answered", minutes="30", known=True):
    return {"module": module, "action": action, "minutes": minutes, "default_minutes": "30", "known": known}


# (rule, bad data, valid data, expected rule id, severity)
CASES = [
    (
        sv.ContractDatesRule,
        _contract(period_start="2026-02-31"),
        _contract(),
        "service.contract_dates_valid",
        Severity.ERROR,
    ),
    (
        sv.ContractDatesRule,
        _contract(period_end="2025-12-31"),
        _contract(),
        "service.contract_dates_valid",
        Severity.ERROR,
    ),
    (
        sv.ContractCurrencyRule,
        _contract(currency=""),
        _contract(),
        "service.contract_currency_stated",
        Severity.WARNING,
    ),
    (
        sv.ContractLapsedRule,
        _contract(period_end="2026-06-30"),
        _contract(),
        "service.contract_not_lapsed",
        Severity.WARNING,
    ),
    (
        sv.WorkOrderItemTotalRule,
        _wo(items=[{"id": "i1", "quantity": "2", "unit_rate": "10", "total": "99"}]),
        _wo(),
        "service.work_order_item_total",
        Severity.ERROR,
    ),
    (sv.CompletedWorkItemsRule, _wo(items=[]), _wo(), "service.completed_work_has_items", Severity.WARNING),
    (
        gv.SessionHasRequiredSignatoryRule,
        _session(signatory_map=[]),
        _session(),
        "signing.required_signatory_named",
        Severity.WARNING,
    ),
    (
        gv.SessionExpiryRule,
        _session(expires_at="2026-01-01T00:00:00+00:00"),
        _session(),
        "signing.expiry_in_future",
        Severity.ERROR,
    ),
    (
        gv.SignedAtNotFutureRule,
        _signature(signed_at="2026-11-05T12:00:00+00:00"),
        _signature(),
        "signing.signed_at_not_future",
        Severity.ERROR,
    ),
    (
        gv.SignedCurrentVersionRule,
        _signature(content_hash="old"),
        _signature(),
        "signing.signed_current_version",
        Severity.WARNING,
    ),
    (
        vv.FactorPairUniqueRule,
        _factors(_f(), _f(minutes="40")),
        _factors(_f()),
        "value.factor_pair_unique",
        Severity.ERROR,
    ),
    (
        vv.FactorKnownActionRule,
        _factors(_f(action="nothing", known=False)),
        _factors(_f()),
        "value.factor_action_known",
        Severity.WARNING,
    ),
    (
        vv.FactorWithinWorkdayRule,
        _factors(_f(minutes="600")),
        _factors(_f()),
        "value.factor_within_workday",
        Severity.WARNING,
    ),
    (
        pv.UnitEntryStageRule,
        _unit(operation="create", status="installed"),
        _unit(operation="create"),
        "prefab.entry_before_qa",
        Severity.ERROR,
    ),
    (pv.UnitBimElementsRule, _unit(bim_element_ids=["a", "a"]), _unit(), "prefab.bim_elements_clean", Severity.ERROR),
    (pv.UnitBimElementsRule, _unit(bim_element_ids=["a", " "]), _unit(), "prefab.bim_elements_clean", Severity.ERROR),
    (
        pv.UnitInstallDateRule,
        _unit(target_install_date="2026-09-01"),
        _unit(),
        "prefab.install_date_ahead",
        Severity.WARNING,
    ),
    (
        pv.UnitDispatchPlannedRule,
        _unit(status="dispatched", target_install_date=None),
        _unit(status="dispatched"),
        "prefab.dispatch_has_install_date",
        Severity.WARNING,
    ),
    (
        plv.PrelimIgnoredAmountRule,
        _item(item_type="fixed", rate_per_period="500", fixed_amount="900"),
        _item(item_type="fixed", rate_per_period="0", periods="0", fixed_amount="900"),
        "preliminaries.amount_counted",
        Severity.ERROR,
    ),
    (
        plv.PrelimIgnoredAmountRule,
        _item(fixed_amount="900"),
        _item(),
        "preliminaries.amount_counted",
        Severity.ERROR,
    ),
    (plv.PrelimUnpricedRule, _item(periods="0"), _item(), "preliminaries.line_priced", Severity.WARNING),
    (plv.PrelimLabelRule, _item(label=""), _item(), "preliminaries.label_present", Severity.ERROR),
    (plv.PrelimDurationRule, _item(periods="5000"), _item(), "preliminaries.duration_sane", Severity.ERROR),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "good", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, bad, good, rule_id, severity):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed, rule_id
    assert {r.rule_id for r in failed} == {rule_id}
    assert all(r.severity == severity for r in failed)
    assert all("{" not in r.message and r.suggestion for r in failed)
    assert all(r.passed for r in await _run(rule, good))


@pytest.mark.asyncio
async def test_rules_leave_alone_what_they_do_not_judge():
    assert all(r.passed for r in await _run(sv.ContractCurrencyRule, _contract(currency="", value="0")))
    assert all(
        r.passed for r in await _run(sv.ContractLapsedRule, _contract(period_end="2020-01-01", status="expired"))
    )
    assert all(r.passed for r in await _run(sv.CompletedWorkItemsRule, _wo(status="in_progress", items=[])))
    assert all(
        r.passed for r in await _run(gv.SessionHasRequiredSignatoryRule, _session(status="draft", signatory_map=[]))
    )
    assert all(
        r.passed
        for r in await _run(pv.UnitInstallDateRule, _unit(status="installed", target_install_date="2020-01-01"))
    )
    assert all(r.passed for r in await _run(plv.PrelimLabelRule, _item(label="", rate_per_period="0", periods="0")))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(plv.PrelimUnpricedRule, _item(periods="0"), "de") if not r.passed]
    assert "null" in failed[0].message


@pytest.mark.parametrize(
    ("rule_set", "register", "count"),
    [
        ("service", sv.register_service_validation_rules, 5),
        ("signing", gv.register_signing_validation_rules, 4),
        ("value", vv.register_value_validation_rules, 3),
        ("prefab", pv.register_prefab_validation_rules, 4),
        ("preliminaries", plv.register_preliminaries_validation_rules, 4),
    ],
)
def test_rule_set_is_registered(rule_set, register, count):
    register()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([rule_set])}) == count


KEYS = {
    "service": ["contract_date_invalid", "contract_lapsed", "completed_without_items"],
    "signing": ["no_required_signatory", "expiry_past", "signed_in_future", "signed_other_version"],
    "value": ["factor_duplicate", "factor_unknown_action", "factor_over_workday"],
    "prefab": ["entry_past_qa", "bim_ids_invalid", "install_date_passed", "dispatch_without_date"],
    "preliminaries": ["fixed_carries_rate", "timed_carries_fixed", "line_unpriced"],
}
HERE = Path(bundle.__file__).parent
LOCALES = sorted(p.stem for p in HERE.glob("*.json"))


def _load(locale: str) -> dict:
    return json.loads((HERE / f"{locale}.json").read_text(encoding="utf-8"))


def _placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{(\w+)\}", text))


@pytest.mark.parametrize("locale", LOCALES)
def test_every_locale_has_every_key_with_the_english_placeholders(locale):
    base, mine = _load("en"), _load(locale)
    for section, keys in KEYS.items():
        for key in keys:
            for part in ("fail", "suggestion"):
                text = mine[section][key][part]
                assert text.strip()
                assert _placeholders(text) == _placeholders(base[section][key][part])


@pytest.mark.parametrize("locale", [loc for loc in LOCALES if loc != "en"])
def test_non_english_locales_are_translated(locale):
    base, mine = _load("en"), _load(locale)
    same = [(s, k) for s, keys in KEYS.items() for k in keys if mine[s][k]["fail"] == base[s][k]["fail"]]
    assert not same


def test_uzbek_uses_the_modifier_letter_not_a_quote():
    text = json.dumps({s: _load("uz")[s] for s in KEYS}, ensure_ascii=False)
    assert "ʻ" in text
    assert "o'" not in text and "g'" not in text and "‘" not in text


@pytest.mark.parametrize("section", sorted(KEYS))
def test_every_key_the_rules_emit_is_in_the_bundle(section):
    source = (Path(bundle.__file__).parents[3] / "modules" / section / "validators.py").read_text(encoding="utf-8")
    used = set(re.findall(r'self\.fail\(\s*context,\s*"(\w+)"', source))
    own = used & set(_load("en").get(section, {}))
    shared = used - own
    assert set(KEYS[section]) <= own
    assert shared <= set(_load("en")["money"])
