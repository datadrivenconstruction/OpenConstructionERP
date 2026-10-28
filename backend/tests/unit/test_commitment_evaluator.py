# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Delegation of authority, decision dates and the matrix's own FX, as pure functions.

Every case names the rule it pins and is built so that removing the rule flips
the answer: bands of the item's own type over ``*`` bands, the lowest sufficient
tier, novelty raising the tier, cumulative and split-group evaluation, the
open top band versus ``escalate_outside``, dated schedule versions, and a
missing rate refusing instead of blending at 1:1.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.commitment_release import evaluator as ev
from app.modules.commitment_release import fx
from app.modules.commitment_release.catalogue import AuthoritySchedule

D = Decimal


def _schedule(**over) -> AuthoritySchedule:
    body = {
        "id": "t",
        "version": 1,
        "name_key": "commitment.catalogue.t.name",
        "currency": "EUR",
        "commitment_types": [
            {"code": "works", "name_key": "commitment.type.works"},
            {"code": "design", "name_key": "commitment.type.design"},
            {"code": "claim_settlement", "name_key": "commitment.type.claim_settlement"},
        ],
        "tiers": [
            {"code": "pm", "name_key": "commitment.tier.pm", "approver": {"kind": "project_role", "ref": "owner_pm"}},
            {"code": "sponsor", "name_key": "commitment.tier.s", "approver": {"kind": "project_role", "ref": "s"}},
            {"code": "board", "name_key": "commitment.tier.b", "approver": {"kind": "project_role", "ref": "b"}},
        ],
        "bands": [
            {"code": "a1", "commitment_type": "*", "tier": "pm", "max_amount": "50000"},
            {"code": "a2", "commitment_type": "*", "tier": "sponsor", "max_amount": "500000"},
            {"code": "a3", "commitment_type": "*", "tier": "board", "max_amount": "5000000"},
            {"code": "w1", "commitment_type": "works", "tier": "pm", "max_amount": "100000"},
            {"code": "w2", "commitment_type": "works", "tier": "board", "max_amount": None},
        ],
        "novelty_flags": [
            {"code": "novel_contentious", "name_key": "commitment.flag.n", "min_tier": "board"},
            {"code": "claim_settlement", "name_key": "commitment.type.claim_settlement", "min_tier": "sponsor"},
        ],
    }
    body.update(over)
    return AuthoritySchedule.model_validate(body)


@pytest.mark.parametrize(
    ("ctype", "amount", "tier", "band"),
    [
        # ``*`` bands: the lowest sufficient tier, boundaries inclusive.
        ("design", "50000", "pm", "a1"),
        ("design", "50000.01", "sponsor", "a2"),
        ("design", "500000", "sponsor", "a2"),
        ("design", "5000000", "board", "a3"),
        # Own-type bands replace ``*``: 75k works is still pm (``*`` would say sponsor).
        ("works", "75000", "pm", "w1"),
        # Own-type open top band: no escalation however large.
        ("works", "900000000", "board", "w2"),
    ],
)
def test_required_tier_reads_the_lowest_sufficient_band(ctype: str, amount: str, tier: str, band: str) -> None:
    r = ev.required_tier(_schedule(), ctype, D(amount))
    assert (r.tier_code, r.band_code, r.escalate_outside) == (tier, band, False)


def test_above_the_top_band_escalates_outside_and_names_no_tier() -> None:
    r = ev.required_tier(_schedule(), "design", D("5000000.01"))
    assert r.escalate_outside is True
    assert r.tier_code is None


def test_a_novelty_flag_raises_the_tier_regardless_of_amount() -> None:
    plain = ev.required_tier(_schedule(), "design", D("1000"))
    flagged = ev.required_tier(_schedule(), "design", D("1000"), {"novel_contentious"})
    assert plain.tier_code == "pm"
    assert (flagged.tier_code, flagged.raised_by) == ("board", ("novel_contentious",))


def test_a_type_named_as_novelty_flag_raises_its_own_items() -> None:
    assert ev.required_tier(_schedule(), "claim_settlement", D("10")).tier_code == "sponsor"


def test_a_novelty_flag_never_lowers_a_tier() -> None:
    r = ev.required_tier(_schedule(), "claim_settlement", D("4000000"))
    assert r.tier_code == "board"
    assert r.raised_by == ()


def test_an_unknown_type_is_refused() -> None:
    with pytest.raises(ValueError):
        ev.required_tier(_schedule(), "catering", D("1"))


@pytest.mark.parametrize(
    ("aggregation", "item", "group", "asked", "expected"),
    [
        ("item_total", "40000", "0", "20000", "60000"),
        ("request_only", "40000", "0", "20000", "20000"),
        # Anti-splitting: the other items of the split group count in both modes.
        ("item_total", "0", "45000", "10000", "55000"),
        ("request_only", "30000", "45000", "10000", "55000"),
    ],
)
def test_evaluated_amount(aggregation: str, item: str, group: str, asked: str, expected: str) -> None:
    got = ev.evaluated_amount(
        request=D(asked), released_on_item=D(item), released_on_group_others=D(group), aggregation=aggregation
    )
    assert got == D(expected)


def test_a_second_tranche_can_need_a_higher_tier_than_the_first() -> None:
    s = _schedule()
    first = ev.evaluated_amount(
        request=D("40000"), released_on_item=D("0"), released_on_group_others=D("0"), aggregation="item_total"
    )
    second = ev.evaluated_amount(
        request=D("40000"), released_on_item=D("40000"), released_on_group_others=D("0"), aggregation="item_total"
    )
    assert ev.required_tier(s, "design", first).tier_code == "pm"
    assert ev.required_tier(s, "design", second).tier_code == "sponsor"


def test_split_items_cannot_stay_under_a_band_each() -> None:
    s = _schedule()
    alone = ev.evaluated_amount(
        request=D("30000"), released_on_item=D("0"), released_on_group_others=D("0"), aggregation="item_total"
    )
    grouped = ev.evaluated_amount(
        request=D("30000"), released_on_item=D("0"), released_on_group_others=D("30000"), aggregation="item_total"
    )
    assert ev.required_tier(s, "design", alone).tier_code == "pm"
    assert ev.required_tier(s, "design", grouped).tier_code == "sponsor"


def test_a_non_positive_request_is_refused() -> None:
    with pytest.raises(ValueError):
        ev.evaluated_amount(request=D("0"), released_on_item=D("0"), released_on_group_others=D("0"), aggregation="")


def test_schedule_in_force_picks_the_version_dated_for_the_day() -> None:
    old = _schedule(version=1, effective_to="2025-09-30")
    new = _schedule(version=2, effective_from="2025-10-01")
    assert ev.schedule_in_force([old, new], date(2025, 9, 30)).version == 1
    assert ev.schedule_in_force([old, new], date(2025, 10, 1)).version == 2
    assert ev.schedule_in_force([new], date(2025, 1, 1)) is None


def test_tolerance_ceiling_takes_the_larger_allowance() -> None:
    assert ev.tolerance_ceiling(D("100000"), D("1000"), D("0.02")) == D("102000")
    assert ev.tolerance_ceiling(D("10000"), D("1000"), D("0.02")) == D("11000")


@pytest.mark.parametrize(
    ("kw", "latest", "basis"),
    [
        (
            {"late_start": "2027-03-31", "start_date": "2027-03-01", "lead_time_days": 60, "decision_buffer_days": 14},
            date(2027, 1, 16),
            "late_start",
        ),
        ({"late_start": None, "start_date": "2027-03-01", "lead_time_days": 60}, date(2026, 12, 31), "start_date"),
        ({"fixed": "2026-12-01", "lead_time_days": 99}, date(2026, 12, 1), "fixed"),
        ({}, None, "none"),
    ],
)
def test_latest_decision_date(kw: dict, latest: date | None, basis: str) -> None:
    got = ev.latest_decision_date(**kw)
    assert (got.latest, got.basis) == (latest, basis)


def test_overdue_is_a_flag_for_unreleased_items_only() -> None:
    latest = date(2026, 10, 1)
    assert ev.decision_overdue(latest, date(2026, 10, 2), "planned", D("0")) is True
    assert ev.decision_overdue(latest, date(2026, 10, 1), "planned", D("0")) is False
    assert ev.decision_overdue(latest, date(2026, 10, 2), "released", D("100")) is False
    assert ev.decision_overdue(None, date(2026, 10, 2), "planned", D("0")) is False


# ── FX ─────────────────────────────────────────────────────────────────────


def test_project_rates_cross_through_the_base() -> None:
    # base EUR; 1 GBP = 1.20 EUR, 1 USD = 0.90 EUR -> 1 GBP = 1.333.. USD
    q = fx.project_rates_quote("GBP", "USD", "EUR", {"GBP": "1.20", "USD": "0.90"}, date(2026, 10, 1))
    assert q is not None
    assert q.source == fx.SOURCE_PROJECT
    assert q.apply(D("900")) == D("1200")


def test_project_rates_to_and_from_the_base() -> None:
    to_base = fx.project_rates_quote("GBP", "EUR", "EUR", {"GBP": "1.20"}, None)
    from_base = fx.project_rates_quote("EUR", "GBP", "EUR", {"GBP": "1.25"}, None)
    assert to_base.apply(D("100")) == D("120.00")
    assert from_base.apply(D("125")) == D("100")


@pytest.mark.parametrize("rates", [{}, {"GBP": "junk"}, {"GBP": "0"}, {"GBP": "-1"}])
def test_a_missing_or_junk_project_rate_gives_no_quote(rates: dict) -> None:
    assert fx.project_rates_quote("GBP", "EUR", "EUR", rates, None) is None


@pytest.mark.asyncio
async def test_resolve_refuses_instead_of_one_to_one() -> None:
    with pytest.raises(fx.FxRateMissing):
        await fx.resolve_quote(
            None,
            from_currency="GBP",
            to_currency="EUR",
            on_date=date(2026, 10, 1),
            project_id=None,
            base="EUR",
            project_rates={},
            policy="project_rates",
        )


@pytest.mark.asyncio
async def test_same_currency_needs_no_rate() -> None:
    q = await fx.resolve_quote(
        None,
        from_currency="eur",
        to_currency="EUR",
        on_date=date(2026, 10, 1),
        project_id=None,
        base="",
        project_rates={},
        policy="project_rates",
    )
    assert (q.rate, q.source) == (D("1"), fx.SOURCE_SAME)


def test_an_expired_release_covers_what_is_bound_and_nothing_new() -> None:
    from decimal import Decimal as D

    from app.modules.commitment_release.evaluator import release_in_force

    # Nothing expired: the released sum stands whatever is bound.
    assert release_in_force(D("100000"), D("0"), D("40000")) == D("100000")
    # All of it expired with 40,000 bound: those 40,000 stay covered, the other 60,000 are gone.
    assert release_in_force(D("100000"), D("100000"), D("40000")) == D("40000")
    # Expired and nothing bound: nothing is in force.
    assert release_in_force(D("100000"), D("100000"), D("0")) == D("0")
    # More bound than the expired release ever covered: it still covers only its own amount.
    assert release_in_force(D("100000"), D("100000"), D("130000")) == D("100000")
    # A tranche still in date keeps its full amount beside an expired one that is fully bound.
    assert release_in_force(D("150000"), D("100000"), D("100000")) == D("150000")
    # A renewal of 60,000 beside the expired 100,000 of which 40,000 are bound: 100,000 in force again.
    assert release_in_force(D("160000"), D("100000"), D("40000")) == D("100000")
    # A credit never turns an expired release into authority.
    assert release_in_force(D("100000"), D("100000"), D("-500")) == D("0")


@pytest.mark.parametrize(
    ("plant", "own", "requisition", "expected"),
    [
        (84, 30, 14, (84, "plant_item")),  # the register wins over everything typed here
        (84, None, None, (84, "plant_item")),
        (0, 30, 14, (0, "plant_item")),  # zero is an answer, not a gap
        (None, 30, 14, (30, "item")),  # linked but the register has no lead time, or not linked
        (None, 0, 14, (0, "item")),
        (None, None, 14, (14, "requisition")),
        (None, None, None, (None, None)),
    ],
)
def test_the_lead_time_in_force_follows_one_precedence(plant, own, requisition, expected) -> None:
    from app.modules.commitment_release.evaluator import lead_time_in_force

    assert lead_time_in_force(plant_item_days=plant, own_days=own, requisition_days=requisition) == expected


def test_a_plant_item_order_date_decides_before_the_items_own_dates() -> None:
    from datetime import date as day

    from app.modules.commitment_release.evaluator import decision_date_for_item

    own = {"late_start": "2027-06-01", "fixed": "2027-01-10", "lead_time_days": 30}
    # The register's latest order date already holds its need date and lead time: only the buffer comes off.
    got = decision_date_for_item(
        plant_latest_order=day(2027, 2, 1), plant_need_date=day(2027, 8, 1), decision_buffer_days=10, **own
    )
    assert (got.latest, got.basis) == (day(2027, 1, 22), "plant_item")
    # No order date from the register (no need date there): the item's own inputs apply unchanged.
    got = decision_date_for_item(plant_latest_order=None, decision_buffer_days=10, **own)
    assert (got.latest, got.basis) == (day(2027, 4, 22), "late_start")


def test_the_governance_port_is_the_only_country_default_of_the_module() -> None:
    """No file of the module reads a project's country to choose a schedule; ``set_matrix`` asks the port."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app" / "modules" / "commitment_release"
    sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(root.glob("*.py"))}
    assert len(sources) > 10, sorted(sources)
    # The jurisdiction of a shipped schedule is read by nothing here; only the port matches it to a country.
    # It is declared on the two catalogue models and mentioned nowhere else.
    mentions = {name: text.count("jurisdiction_countries") for name, text in sources.items()}
    assert {n: c for n, c in mentions.items() if c} == {"catalogue.py": 2}, mentions
    assert sources["catalogue.py"].count("jurisdiction_countries: tuple[str, ...] = ()") == 2
    # The project's country is read in exactly one place, and there it is handed to the port.
    uses = {name: text.count("country_code") for name, text in sources.items() if "country_code" in text}
    assert uses == {"service.py": 1}, uses
    tree = ast.parse(sources["service.py"])
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "default_catalogue_pin"
    ]
    assert len(calls) == 1
    assert "country_code" in ast.unparse(calls[0])
