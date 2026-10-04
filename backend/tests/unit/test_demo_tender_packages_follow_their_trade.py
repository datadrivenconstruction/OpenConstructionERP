# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every seeded tender package holds the trade it is named for, and is dated from today.

The installer used to cut each demo bill into money-balanced contiguous slices
and hand them to the packages in order, so the office demo's "Innenausbau"
(drywall, raised floors, ceilings, finishes, doors) held the roof and the PV
plant and not the drywall partition. Its statuses were whatever the pack
wrote ("draft" next to three submitted bids) and its deadlines fixed dates,
so a demo opened later showed every tender closed months ago.

The population is every registered pack with tender packages, read the way
the installer reads it (``demo_tender_scopes`` is the code both call).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core import demo_projects
from app.core import demo_tender_scopes as scopes
from app.core.demo_tender_scopes import (
    CUSTOMARY,
    OPEN_STATUSES,
    PENDING_INVITEE,
    assign_package_scopes,
    din276_digits,
    package_claim,
    position_trade,
    seeded_deadlines,
    seeded_issued_at,
    seeded_package_statuses,
    seeded_recipients,
    seeded_submitted_at,
)
from app.modules.tendering.schemas import RecipientResponse

_SHOWN = 6

_PACKS = sorted(k for k, t in demo_projects.DEMO_TEMPLATES.items() if t.tender_packages)


def _bill(template: demo_projects.DemoTemplate) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Ordinals and ``(trade, din276, description)`` of the lines the installer tenders."""
    ordinals: list[str] = []
    rows: list[tuple[str, str, str]] = []
    for _ordinal, _title, _cls, items in template.sections:
        for ordinal, description, unit, _qty, rate, cls in items:
            if unit == "":
                continue
            meta = demo_projects._enrich_position_metadata(description, unit, rate, cls)
            ordinals.append(ordinal)
            rows.append((position_trade(cls, meta.get("cwicr_ref"), description), din276_digits(cls), description))
    return ordinals, rows


def _scopes(demo_id: str) -> tuple[list[str], list[tuple[str, str, str]], list[list[int]]]:
    template = demo_projects.DEMO_TEMPLATES[demo_id]
    ordinals, rows = _bill(template)
    return ordinals, rows, assign_package_scopes([(p[0], p[1]) for p in template.tender_packages], rows)


def test_the_population_is_the_packs_with_tenders() -> None:
    assert len(_PACKS) >= 60, f"only {len(_PACKS)} packs with tender packages; the loader lost some"


@pytest.mark.parametrize("demo_id", _PACKS)
def test_every_package_holds_only_what_it_promises(demo_id: str) -> None:
    template = demo_projects.DEMO_TEMPLATES[demo_id]
    ordinals, rows, assigned = _scopes(demo_id)
    claims = [package_claim(p[0], p[1]) for p in template.tender_packages]
    coded = any(claim.din276_groups for claim in claims)
    stray: list[str] = []
    for index, claim in enumerate(claims):
        name = template.tender_packages[index][0]
        assert assigned[index], f"{demo_id}: package {name!r} holds no line of the bill"
        for line in assigned[index]:
            trade, din, _description = rows[line]
            if coded:
                promised = any(din.startswith(group) for group in claim.din276_groups)
            else:
                promised = claim.main_contract or trade in claim.trades
            if not promised:
                stray.append(f"{ordinals[line]} ({trade}) in {name!r}")
    assert not stray, f"{demo_id}: lines outside their package's trade: {stray[:_SHOWN]}"
    taken = [line for scope in assigned for line in scope]
    assert len(taken) == len(set(taken)), f"{demo_id}: a line sits in two packages"


@pytest.mark.parametrize("demo_id", _PACKS)
def test_a_line_goes_to_the_package_that_names_its_trade(demo_id: str) -> None:
    """A line whose trade some package names is not left in a package that only carries it by custom."""
    template = demo_projects.DEMO_TEMPLATES[demo_id]
    _ordinals, rows, assigned = _scopes(demo_id)
    claims = [package_claim(p[0], p[1]) for p in template.tender_packages]
    if any(claim.din276_groups for claim in claims):
        return
    for index, claim in enumerate(claims):
        for line in assigned[index]:
            trade = rows[line][0]
            if claim.trades.get(trade, CUSTOMARY) == CUSTOMARY and not claim.main_contract:
                namers = [c for c in claims if c.trades.get(trade, CUSTOMARY) > CUSTOMARY]
                assert not namers, f"{demo_id}: a {trade} line sits in a package that does not name it"


def test_the_office_fit_out_package_holds_the_drywall_and_not_the_roof() -> None:
    template = demo_projects.DEMO_TEMPLATES["office-frankfurt"]
    ordinals, _rows, assigned = _scopes("office-frankfurt")
    names = [p[0] for p in template.tender_packages]
    fit_out = {ordinals[i] for i in assigned[names.index("Innenausbau")]}
    assert {"340.4", "340.5", "340.7", "350.12"} <= fit_out
    assert not fit_out & {"340.1", "350.1", "360.1", "360.3", "420.1", "440.1"}
    assert "340.1" in {ordinals[i] for i in assigned[names.index("Rohbau")]}


@pytest.mark.parametrize(
    ("classification", "cwicr_ref", "description", "trade"),
    [
        ({"din276": "342"}, None, "Trennwand", "fitout"),
        ({"din276": "331"}, None, "Stahlbetonwand", "structure"),
        ({"masterformat": "09 21 16"}, None, "Gypsum board assemblies", "fitout"),
        ({}, "CWICR-DRY-001", "Partition", "fitout"),
        ({}, None, "BESS container 2 MWh", "storage"),
        ({}, None, "Электромонтажные работы, щиты", "electrical"),
        ({}, None, "Кладка стен из кирпича", "masonry"),
        ({}, None, "Something nobody can place", "prelims"),
    ],
)
def test_a_position_trade_is_read_from_code_bucket_or_words(
    classification: dict, cwicr_ref: str | None, description: str, trade: str
) -> None:
    assert position_trade(classification, cwicr_ref, description) == trade


def test_a_package_with_bids_is_collecting_not_draft() -> None:
    assert seeded_package_statuses(["evaluating", "draft", "issued"], [True, True, True]) == [
        "evaluating",
        "collecting",
        "collecting",
    ]
    assert seeded_package_statuses(["draft"], [False]) == ["draft"]


def test_a_pack_with_every_package_closed_reopens_its_last_evaluating_one() -> None:
    assert seeded_package_statuses(["evaluating", "evaluating", "awarded"], [True] * 3) == [
        "evaluating",
        "collecting",
        "awarded",
    ]


@pytest.mark.parametrize("demo_id", _PACKS)
def test_every_pack_has_a_package_still_out(demo_id: str) -> None:
    packages = demo_projects.DEMO_TEMPLATES[demo_id].tender_packages
    statuses = seeded_package_statuses([p[2] for p in packages], [bool(p[3]) for p in packages])
    assert any(s in OPEN_STATUSES for s in statuses), f"{demo_id}: {statuses}"
    for package, status in zip(packages, statuses, strict=True):
        assert not (package[3] and status == "draft"), f"{demo_id}: {package[0]!r} is draft with bids"


def test_the_office_fit_out_is_the_package_still_out() -> None:
    packages = demo_projects.DEMO_TEMPLATES["office-frankfurt"].tender_packages
    statuses = seeded_package_statuses([p[2] for p in packages], [bool(p[3]) for p in packages])
    by_name = {p[0]: s for p, s in zip(packages, statuses, strict=True)}
    assert by_name["Innenausbau"] == "collecting"
    assert by_name["Rohbau"] == "evaluating"


def test_dates_count_from_the_install_day() -> None:
    today = date(2031, 3, 10)
    statuses = ["awarded", "evaluating", "collecting", "evaluating", "collecting"]
    deadlines = seeded_deadlines(statuses, today)
    for status, deadline in zip(statuses, deadlines, strict=True):
        if status in OPEN_STATUSES:
            assert deadline > today
        else:
            assert deadline < today
    closed = [d for s, d in zip(statuses, deadlines, strict=True) if s not in OPEN_STATUSES]
    assert closed == sorted(closed), "the first package tendered closes first"
    for status, deadline in zip(statuses, deadlines, strict=True):
        issued = seeded_issued_at(status, deadline, today)
        for bidder in range(12):
            submitted = seeded_submitted_at(status, deadline, today, bidder)
            assert issued < submitted, "a bid arrived before the package went out"
            assert submitted.date() <= min(deadline, today)


def test_the_open_package_invites_a_firm_that_has_not_quoted() -> None:
    bidders = [("Firm A", "a@a.example"), ("Firm B", "b@b.example")]
    sent = seeded_issued_at("collecting", date(2031, 4, 1), date(2031, 3, 10))
    recipients = seeded_recipients(bidders, sent_at=sent, pending_invitee=PENDING_INVITEE)
    parsed = [RecipientResponse.model_validate(r) for r in recipients]
    assert [r.email for r in parsed] == ["a@a.example", "b@b.example", PENDING_INVITEE[1]]
    assert all(r.status == "sent" and r.sent_at for r in parsed)
    assert len({r.id for r in parsed}) == 3
    assert PENDING_INVITEE[1].endswith(".example")
    closed = seeded_recipients(bidders, sent_at=sent, pending_invitee=None)
    assert [r["email"] for r in closed] == ["a@a.example", "b@b.example"]


def test_the_pending_invitee_is_not_a_bidder_of_any_pack() -> None:
    emails = {
        company[1].lower()
        for template in demo_projects.DEMO_TEMPLATES.values()
        for package in template.tender_packages
        for company in package[3]
    } | {c[1].lower() for t in demo_projects.DEMO_TEMPLATES.values() for c in t.tender_companies}
    assert PENDING_INVITEE[1] not in emails
    assert scopes.PENDING_INVITEE[0] not in {
        company[0] for t in demo_projects.DEMO_TEMPLATES.values() for p in t.tender_packages for company in p[3]
    }


_LEGACY = sorted(k for k, t in demo_projects.DEMO_TEMPLATES.items() if not t.tender_packages and t.tender_companies)


@pytest.mark.parametrize("demo_id", _LEGACY)
def test_a_single_package_pack_also_has_its_tender_out(demo_id: str) -> None:
    """Packs without a package list seed one main package; it is the open one."""
    companies = demo_projects.DEMO_TEMPLATES[demo_id].tender_companies
    today = date(2031, 3, 10)
    status = seeded_package_statuses(["evaluating"], [bool(companies)])[0]
    deadline = seeded_deadlines([status], today)[0]
    assert status in OPEN_STATUSES and deadline > today
    distribution = demo_projects._seeded_distribution(status, deadline, today, companies)
    emails = [r["email"] for r in distribution["recipients"]]
    assert PENDING_INVITEE[1] in emails
    assert {c[1] for c in companies} <= set(emails)


def test_a_closed_package_lists_only_its_bidders() -> None:
    companies = [("Firm A", "a@a.example", 1.0)]
    today = date(2031, 3, 10)
    distribution = demo_projects._seeded_distribution("evaluating", date(2031, 2, 20), today, companies)
    assert [r["email"] for r in distribution["recipients"]] == ["a@a.example"]
    assert demo_projects._seeded_distribution("draft", date(2031, 4, 1), today, []) == {}
