# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every finding the economics module can raise has a validation rule and a message in both languages."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.modules.economics import rules
from app.modules.economics.seed import StoryError, load_profile, round_up, split
from app.modules.economics.validators import ECONOMICS_RULE_SET, ECONOMICS_RULES
from tests.economics_stories import DEMO_IDS, story_for

MESSAGES = Path(__file__).resolve().parents[2] / "app" / "modules" / "economics" / "messages"


def _load(lang: str) -> dict[str, str]:
    return json.loads((MESSAGES / f"{lang}.json").read_text(encoding="utf-8"))


def _placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{(\w+)\}", text))


def test_every_finding_code_has_exactly_one_rule() -> None:
    ids = sorted(r.rule_id for r in ECONOMICS_RULES)
    assert ids == sorted(f"economics.{code}" for code in rules.CODES)
    assert ECONOMICS_RULE_SET == "economics"


def test_every_rule_and_error_has_a_message_in_both_languages() -> None:
    en, de = _load("en"), _load("de")
    assert set(en) == set(de)
    for code in rules.CODES:
        for part in ("fail", "suggestion"):
            key = f"economics.rules.{code}.{part}"
            assert en.get(key), key
            assert de.get(key), key
            assert _placeholders(en[key]) == _placeholders(de[key]), key


def test_severity_follows_the_code_table() -> None:
    by_id = {r.rule_id: r for r in ECONOMICS_RULES}
    for code, severity in rules.CODES.items():
        assert by_id[f"economics.{code}"].severity.value == severity, code


def test_rounding_up_to_a_step_never_goes_below_the_amount() -> None:
    assert round_up(Decimal("1")) == Decimal("100000")
    assert round_up(Decimal("100000")) == Decimal("100000")
    assert round_up(Decimal("100000.01")) == Decimal("200000")
    assert round_up(Decimal("0")) == Decimal("0")


def test_a_split_adds_up_exactly_and_the_last_part_takes_the_remainder() -> None:
    parts = split(Decimal("100.00"), 3)
    assert parts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(split(Decimal("59200000.37"), 7), Decimal(0)) == Decimal("59200000.37")


TODAY = date(2026, 10, 14)


def test_each_demo_story_ends_with_the_exact_remainder_as_its_last_source() -> None:
    for demo_id in DEMO_IDS:
        profile = load_profile(story_for(demo_id), "de", TODAY)
        assert profile.sources[-1].share is None, demo_id
        assert all(s.share is not None for s in profile.sources[:-1]), demo_id
        shares = sum(Decimal(s.share) for s in profile.sources[:-1] if s.share)
        assert Decimal(0) < shares < Decimal(1), demo_id
        assert all(s.due for s in profile.sources), demo_id


def test_each_demo_story_is_german_in_german_and_has_every_register() -> None:
    for demo_id in DEMO_IDS:
        de = load_profile(story_for(demo_id), "de", TODAY)
        en = load_profile(story_for(demo_id), "en", TODAY)
        assert de.sources[0].name != en.sources[0].name, demo_id
        assert de.securities and de.insurances and de.tax is not None, demo_id
        assert {p.area for p in de.process} == set(rules.PROCESS_AREAS), demo_id
        assert all(s.status in ("requested", "in_place", "released", "expired") for s in de.securities)


def test_the_story_dates_are_offsets_from_the_install_day() -> None:
    later = date(2027, 1, 1)
    a = load_profile(story_for("residential-regensburg"), "de", TODAY)
    b = load_profile(story_for("residential-regensburg"), "de", later)
    assert date.fromisoformat(b.sources[0].due[0]) - date.fromisoformat(a.sources[0].due[0]) == later - TODAY


def test_a_malformed_story_names_the_key() -> None:
    story = story_for("school-ludwigsburg")
    story["sources"][-1]["share"] = "0.1"
    try:
        load_profile(story, "de", TODAY)
    except StoryError as exc:
        assert "sources[3].share" in str(exc)
    else:
        raise AssertionError("a financing plan whose last source is not the remainder must be refused")


def test_the_story_files_carry_no_em_or_en_dash() -> None:
    from tests.economics_stories import DEMO_DIR

    for demo_id in DEMO_IDS:
        text = (DEMO_DIR / f"{demo_id}-economics.json").read_text(encoding="utf-8")
        assert "—" not in text and "–" not in text, demo_id


def _registers(**over: object) -> dict:
    reg: dict = {
        "today": "2026-10-14",
        "securities": [
            {"id": "s1", "description": "Performance guarantee", "status": "in_place", "valid_until": "2027-12-31"}
        ],
        "insurances": [{"id": "i1", "label": "BAR-1", "status": "in_place", "period_to": "2027-12-31"}],
        "tax": {"confirmed": True, "input_tax_deduction": True},
        "process": [{"area": a, "status": "set_up"} for a in rules.PROCESS_AREAS],
    }
    reg.update(over)
    return {"registers": reg}


def test_complete_registers_raise_nothing_and_answer_every_gate_question() -> None:
    payload = _registers()
    assert rules.register_findings(payload) == []
    assert all(rules.register_state(payload).values())


def test_a_payload_without_registers_raises_no_register_finding() -> None:
    assert rules.register_findings({}) == []


def test_a_security_past_its_end_date_is_flagged_and_is_not_in_place() -> None:
    payload = _registers(
        securities=[{"id": "s1", "description": "Warranty bond", "status": "in_place", "valid_until": "2026-10-13"}]
    )
    assert [f.code for f in rules.register_findings(payload)] == ["security_expired"]
    assert rules.register_state(payload)["securities"] is False


def test_a_released_security_is_in_place_and_never_expired() -> None:
    payload = _registers(
        securities=[{"id": "s1", "description": "Bid bond", "status": "released", "valid_until": "2025-01-01"}]
    )
    assert rules.register_findings(payload) == []
    assert rules.register_state(payload)["securities"] is True


def test_an_unconfirmed_tax_treatment_and_open_processes_are_flagged() -> None:
    payload = _registers(
        tax={"confirmed": False, "input_tax_deduction": None},
        process=[{"area": "receivables", "status": "set_up"}],
    )
    codes = [f.code for f in rules.register_findings(payload)]
    assert codes == ["tax_not_confirmed", "process_not_set_up", "process_not_set_up"]
    state = rules.register_state(payload)
    assert state["tax"] is False
    assert state["receivables_payables"] is False
    assert state["administration"] is False


def test_no_securities_or_insurance_at_all_is_not_in_place() -> None:
    state = rules.register_state(_registers(securities=[], insurances=[]))
    assert state["securities"] is False
    assert state["insurance"] is False


def test_a_drawn_tranche_lies_in_the_past_and_the_story_is_refused_otherwise() -> None:
    profile = load_profile(story_for("residential-regensburg"), "en", TODAY)
    equity = profile.sources[0]
    assert equity.drawn == 1 and date.fromisoformat(equity.due[0]) < TODAY
    assert all(s.drawn == 0 for s in profile.sources[1:])
    story = story_for("residential-regensburg")
    story["sources"][0]["drawn"] = 2
    try:
        load_profile(story, "en", TODAY)
    except StoryError as err:
        assert "drawn" in str(err)
    else:
        raise AssertionError("a tranche in the future cannot be drawn")


def test_a_request_whose_start_lies_ahead_does_not_block_but_an_overdue_one_does() -> None:
    ahead = {
        "id": "s2",
        "description": "Warranty",
        "status": "requested",
        "valid_from": "2027-01-01",
        "valid_until": "2030-01-01",
    }
    base = _registers()["registers"]["securities"]
    assert rules.register_state(_registers(securities=[*base, ahead]))["securities"] is True
    overdue = {**ahead, "valid_from": "2026-01-01"}
    assert rules.register_state(_registers(securities=[*base, overdue]))["securities"] is False
    only_requested = _registers(securities=[ahead])
    assert rules.register_state(only_requested)["securities"] is False


def _frame_payload(**plan: object) -> dict:
    return {
        "plan": {"bill_count": 2, "bill_currency": "EUR", "currency": "EUR", **plan},
        "frame": {"lines": [{"code": "300", "amount": "10", "estimate": "5"}], "committed_available": True},
    }


def test_several_bills_warn_until_the_owner_has_chosen_one() -> None:
    codes = [f.code for f in rules.cost_frame_findings(_frame_payload())]
    assert "several_bills" in codes
    codes = [f.code for f in rules.cost_frame_findings(_frame_payload(bill_chosen=True))]
    assert "several_bills" not in codes


def test_a_process_finding_names_the_area_in_the_readers_language() -> None:
    from app.modules.economics.messages import translate

    assert translate("economics.process_area.administration", locale="de") == "Verwaltung"
    assert translate("economics.process_area.administration", locale="en") == "Administration"
