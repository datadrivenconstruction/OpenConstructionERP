# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A contract starts from its country's usual payment terms, and the money follows them.

Until now a contract that named no retention got 5 percent and a release at
substantial completion wherever it was, which is a German habit applied to
every market. These tests hold the replacement to its promises on a real
database: the project's country fills what the author left out and the
contract records which figures it filled; the author's figure always wins; a
project with no country gets nothing invented beyond the one figure the column
cannot leave empty, and that one is stamped as a fallback; a subcontract under
a contract in the same country starts from the same rate.

The money half: a ceiling the country default put on the contract binds the
claims. Three periods each, because the defect this guards against, a cap
checked per period instead of in total, passes the first period and only
shows in the second and third.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.events import event_bus
from app.modules.boq.models import BOQ, Position
from app.modules.contracts.country_defaults import COUNTRY_CONTRACT_DEFAULTS
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest, ContractCreate, ContractUpdate
from app.modules.contracts.service import (
    BOQ_POSITION_META_KEY,
    RELEASE_RULE_FROM_CONTRACT,
    RELEASE_RULE_FROM_PACK,
    ContractsService,
)
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.progress.models import ProgressEntry
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Certificate
from app.modules.subcontractors.schemas import (
    AgreementCreate,
    AgreementUpdate,
    PaymentApplicationCreate,
    SubcontractorCreate,
)
from app.modules.subcontractors.service import SubcontractorService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(event_bus, "publish_detached", lambda *a, **k: None)
    register_contracts_validation_rules()


async def _project(session, country_code: str | None) -> Project:
    suffix = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"defaults-{suffix}@site.example", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Country defaults",
        owner_id=owner.id,
        currency="EUR",
        country_code=country_code,
        metadata_={},
    )
    session.add(project)
    await session.flush()
    return project


async def _create(svc: ContractsService, project: Project, **fields) -> Contract:
    return await svc.create_contract(
        ContractCreate(
            code=f"C-{uuid.uuid4().hex[:8]}",
            contract_type=fields.pop("contract_type", "lump_sum"),
            project_id=project.id,
            total_value=fields.pop("total_value", Decimal("100000")),
            **fields,
        )
    )


# ── Creation ─────────────────────────────────────────────────────────


async def test_a_british_contract_starts_from_jct_terms_and_says_so(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "GB"))

    assert contract.retention_percent == Decimal("3")
    assert contract.retention_release_event == "substantial_completion"
    terms = contract.terms["payment_terms"]
    assert terms == {
        "retention_release_split": [
            {"event": "substantial_completion", "release_percent_of_held": "50"},
            {"event": "defects_period_end", "release_percent_of_held": "100"},
        ],
        "payment_period_days": 14,
        "valuation_interval": "monthly",
        "certificate_name": "Interim Certificate",
    }
    # No usual cap in the UK, so none is written: absent, not zero.
    assert "retention_cap_percent" not in terms
    stamp = contract.metadata_["country_defaults"]
    assert stamp["country_code"] == "GB"
    assert set(stamp["applied"]) >= {"retention_percent", "payment_period_days", "retention_release_event"}
    assert "fallback" not in stamp
    assert stamp["sources"]["retention_percent"]["reference"]


async def test_the_authors_figures_win_and_are_not_called_defaults(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(
        svc,
        await _project(pg_session, "GB"),
        retention_percent=Decimal("3"),
        payment_period_days=30,
        retention_release_event="defects_period_end",
        metadata={"source": "import"},
    )
    assert contract.retention_percent == Decimal("3")
    assert contract.retention_release_event == "defects_period_end"
    assert contract.terms["payment_terms"]["payment_period_days"] == 30
    stamp = contract.metadata_["country_defaults"]
    assert "retention_percent" not in stamp["applied"]
    assert "payment_period_days" not in stamp["applied"]
    assert "retention_release_event" not in stamp["applied"]
    assert stamp["applied"]["valuation_interval"] == "monthly"
    # The caller's own metadata survives beside the stamp.
    assert contract.metadata_["source"] == "import"


async def test_no_cap_on_purpose_survives_a_country_that_usually_caps(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "AE"), retention_cap_percent=None)
    assert contract.retention_percent == Decimal("10")
    assert "retention_cap_percent" not in contract.terms["payment_terms"]
    assert (await svc.retention_policy(contract)).cap_percent_of_contract_sum is None


async def test_a_project_with_no_country_gets_nothing_invented(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, None))

    assert "payment_terms" not in contract.terms
    stamp = contract.metadata_["country_defaults"]
    assert stamp["country_code"] is None
    assert stamp["has_country_defaults"] is False
    assert stamp["applied"] == {}
    # The column cannot be empty, so the historical figure stands in, named as such.
    assert contract.retention_percent == Decimal("5")
    assert stamp["fallback"] == ["retention_percent", "retention_release_event"]
    view = await svc.country_defaults_for_project(contract.project_id)
    assert view["has_defaults"] is False
    assert view["values"] == {}


async def test_an_unlisted_country_is_not_answered_with_germany(pg_session) -> None:
    svc = ContractsService(pg_session)
    project = await _project(pg_session, "IT")
    view = await svc.country_defaults_for_project(project.id)
    assert view["country_code"] == "IT"
    assert view["has_defaults"] is False
    contract = await _create(svc, project)
    assert "payment_terms" not in contract.terms
    assert contract.metadata_["country_defaults"]["applied"] == {}


async def test_a_german_contract_keeps_the_packs_release_events(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "DE"))

    assert contract.retention_percent == Decimal("5")
    terms = contract.terms["payment_terms"]
    assert terms["retention_cap_percent"] == "5"
    assert terms["payment_period_days"] == 21
    assert terms["certificate_name"] == "Abschlagsrechnung"
    # The split is the pack's and stays with the pack, documents and all.
    assert "retention_release_split" not in terms
    assert contract.metadata_["country_defaults"]["release_split_source"] == "regional_pack"
    _rule, source = await svc.retention_release_rule(contract)
    assert source == RELEASE_RULE_FROM_PACK


async def test_a_contract_split_decides_what_completion_releases(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "GB"))
    rule, source = await svc.retention_release_rule(contract)
    assert source == RELEASE_RULE_FROM_CONTRACT
    assert [(e["event"], e["release_percent_of_held"]) for e in rule["events"]] == [
        ("substantial_completion", "50"),
        ("defects_period_end", "100"),
    ]


async def test_a_release_event_the_author_names_is_not_overruled_by_a_defaulted_split(pg_session) -> None:
    """GB defaults release half at practical completion; this author says final completion.

    The defaulted JCT split used to be written beside the event, and the
    release rule reads the contract's split before anything else, so the
    engine paid back half at substantial completion against what the
    contract said.
    """
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "GB"), retention_release_event="final_completion")
    assert contract.retention_release_event == "final_completion"
    assert "retention_release_split" not in contract.terms["payment_terms"]
    stamp = contract.metadata_["country_defaults"]
    assert "retention_release_split" not in stamp["applied"]
    assert "retention_release_event" not in stamp["applied"]
    # The rest of the country's terms still apply.
    assert stamp["applied"]["payment_period_days"] == 14
    _rule, source = await svc.retention_release_rule(contract)
    assert source != RELEASE_RULE_FROM_CONTRACT


async def test_a_split_the_author_sends_with_the_event_is_kept(pg_session) -> None:
    split = [
        {"event": "substantial_completion", "release_percent_of_held": "40"},
        {"event": "final_completion", "release_percent_of_held": "100"},
    ]
    svc = ContractsService(pg_session)
    contract = await _create(
        svc,
        await _project(pg_session, "GB"),
        retention_release_event="substantial_completion",
        retention_release_split=split,
    )
    assert contract.terms["payment_terms"]["retention_release_split"] == split
    _rule, source = await svc.retention_release_rule(contract)
    assert source == RELEASE_RULE_FROM_CONTRACT


async def test_changing_the_release_event_on_a_draft_drops_the_defaulted_split(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "GB"))
    assert contract.terms["payment_terms"]["retention_release_split"]

    contract = await svc.update_contract(contract.id, ContractUpdate(retention_release_event="final_completion"))
    assert contract.retention_release_event == "final_completion"
    assert "retention_release_split" not in contract.terms["payment_terms"]
    applied = contract.metadata_["country_defaults"]["applied"]
    assert "retention_release_split" not in applied
    assert "retention_release_event" not in applied
    assert applied["certificate_name"] == "Interim Certificate"
    _rule, source = await svc.retention_release_rule(contract)
    assert source != RELEASE_RULE_FROM_CONTRACT


async def test_changing_the_release_event_keeps_a_split_somebody_typed(pg_session) -> None:
    split = [
        {"event": "substantial_completion", "release_percent_of_held": "40"},
        {"event": "defects_period_end", "release_percent_of_held": "100"},
    ]
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "GB"), retention_release_split=split)
    contract = await svc.update_contract(contract.id, ContractUpdate(retention_release_event="final_completion"))
    assert contract.terms["payment_terms"]["retention_release_split"] == split


async def test_the_country_defaults_view_names_each_figures_source(pg_session) -> None:
    svc = ContractsService(pg_session)
    project = await _project(pg_session, "AE")
    view = await svc.country_defaults_for_project(project.id)
    assert view["has_defaults"] is True
    assert view["standard_form"] == "FIDIC Red Book 2017"
    assert view["values"]["retention_cap_percent"] == "5"
    assert "14.3" in view["sources"]["retention_cap_percent"]["reference"]


# ── Editing a draft ──────────────────────────────────────────────────


async def test_editing_a_defaulted_figure_drops_its_stamp_and_keeps_the_rest(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "GB"))

    contract = await svc.update_contract(
        contract.id, ContractUpdate(retention_percent=Decimal("5"), payment_period_days=21)
    )
    assert contract.retention_percent == Decimal("5")
    assert contract.terms["payment_terms"]["payment_period_days"] == 21
    applied = contract.metadata_["country_defaults"]["applied"]
    assert "retention_percent" not in applied
    assert "payment_period_days" not in applied
    assert applied["certificate_name"] == "Interim Certificate"

    # Replacing terms for another reason keeps the payment terms.
    contract = await svc.update_contract(contract.id, ContractUpdate(terms={"ld_per_day": "100"}))
    assert contract.terms["ld_per_day"] == "100"
    assert contract.terms["payment_terms"]["payment_period_days"] == 21

    # None clears a payment term.
    contract = await svc.update_contract(contract.id, ContractUpdate(certificate_name=None))
    assert "certificate_name" not in contract.terms["payment_terms"]
    assert "certificate_name" not in contract.metadata_["country_defaults"]["applied"]


async def test_payment_terms_lock_with_the_other_financial_terms(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "GB"))
    contract.status = "active"
    await pg_session.flush()
    with pytest.raises(HTTPException) as refused:
        await svc.update_contract(contract.id, ContractUpdate(retention_cap_percent=Decimal("5")))
    assert refused.value.status_code == 409
    assert refused.value.detail["locked_fields"] == ["retention_cap_percent"]


# ── The cap binds the money, period after period ─────────────────────


async def _claim(session, contract: Contract, number: str, month: int) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
        currency="EUR",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    return claim


async def test_a_flat_contract_stops_holding_retention_at_the_gulf_ceiling(pg_session) -> None:
    """FIDIC defaults: 10 percent of each payment until 5 percent of 100000 is held."""
    svc = ContractsService(pg_session)
    contract = await _create(
        svc, await _project(pg_session, "AE"), contract_type="cost_plus", terms={"fee_percent": "0"}
    )
    assert contract.retention_percent == Decimal("10")
    assert contract.terms["payment_terms"]["retention_cap_percent"] == "5"
    contract.status = "active"
    await pg_session.flush()

    accruals = []
    for month, cost in ((3, "40000"), (4, "20000"), (5, "30000")):
        claim = await svc.auto_generate_claim_lines(
            (await _claim(pg_session, contract, f"PC-{month}", month)).id,
            AutoGenerateClaimRequest(actual_costs_total=Decimal(cost)),
        )
        accruals.append(claim.retention_amount)
        assert claim.net_due == claim.gross_amount - claim.retention_amount
        await svc.transition_claim(claim.id, "submitted", "cap-test")

    # A per-period check would hold 4000, 2000 and 3000: 9000 against a 5000 ceiling.
    assert accruals == [Decimal("4000"), Decimal("1000"), Decimal("0")]


async def test_a_cost_plus_contract_with_no_total_keeps_holding_its_rate(pg_session) -> None:
    """German defaults (5 percent, capped at 5 percent of the sum) on a contract that states no sum.

    The cap is a percent of the contract sum. Measured against a sum of 0 it
    was 0, and every claim held nothing; before country defaults brought the
    cap, the same contract held its 5 percent. Without a sum there is no
    ceiling to measure, so every period holds its rate.
    """
    svc = ContractsService(pg_session)
    contract = await _create(
        svc,
        await _project(pg_session, "DE"),
        contract_type="cost_plus",
        terms={"fee_percent": "0"},
        total_value=Decimal("0"),
    )
    assert contract.retention_percent == Decimal("5")
    assert contract.terms["payment_terms"]["retention_cap_percent"] == "5"
    assert contract.total_value == Decimal("0")
    contract.status = "active"
    await pg_session.flush()

    accruals = []
    for month, cost in ((3, "20000"), (4, "20000"), (5, "40000")):
        claim = await svc.auto_generate_claim_lines(
            (await _claim(pg_session, contract, f"PC-{month}", month)).id,
            AutoGenerateClaimRequest(actual_costs_total=Decimal(cost)),
        )
        accruals.append(claim.retention_amount)
        assert claim.net_due == claim.gross_amount - claim.retention_amount
        await svc.transition_claim(claim.id, "submitted", "cap-test")

    assert accruals == [Decimal("1000"), Decimal("1000"), Decimal("2000")]


async def test_a_claim_raised_while_the_one_before_is_a_draft_still_stops_at_the_ceiling(pg_session) -> None:
    """FIDIC defaults again, but nothing is submitted before the next month is raised.

    "Previous certificates" leave drafts out, and the ceiling used to read
    the same list, so April raised while March was still a draft saw nothing
    held and could hold up to the whole ceiling again: 4000, 2000 and 3000,
    9000 against a limit of 5000 once all three went out.
    """
    svc = ContractsService(pg_session)
    contract = await _create(
        svc, await _project(pg_session, "AE"), contract_type="cost_plus", terms={"fee_percent": "0"}
    )
    contract.status = "active"
    await pg_session.flush()

    accruals = []
    for month, cost in ((3, "40000"), (4, "20000"), (5, "30000")):
        claim = await svc.auto_generate_claim_lines(
            (await _claim(pg_session, contract, f"PC-{month}", month)).id,
            AutoGenerateClaimRequest(actual_costs_total=Decimal(cost)),
        )
        assert claim.status == "draft"
        accruals.append(claim.retention_amount)

    assert accruals == [Decimal("4000"), Decimal("1000"), Decimal("0")]


async def test_a_rejected_claim_leaves_its_room_under_the_ceiling(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(
        svc, await _project(pg_session, "AE"), contract_type="cost_plus", terms={"fee_percent": "0"}
    )
    contract.status = "active"
    await pg_session.flush()
    march = await svc.auto_generate_claim_lines(
        (await _claim(pg_session, contract, "PC-3", 3)).id,
        AutoGenerateClaimRequest(actual_costs_total=Decimal("40000")),
    )
    march.status = "rejected"
    await pg_session.flush()
    april = await svc.auto_generate_claim_lines(
        (await _claim(pg_session, contract, "PC-4", 4)).id,
        AutoGenerateClaimRequest(actual_costs_total=Decimal("20000")),
    )
    # March certified nothing and holds nothing, so April has the whole room.
    assert april.retention_amount == Decimal("2000")


async def test_the_populate_preview_holds_what_the_commit_holds_once_the_ceiling_binds(pg_session) -> None:
    """The preview used to hold the full rate on a flat claim and the commit the capped one.

    FIDIC defaults on 100000: March holds 4600 of a 5000 ceiling, so April's
    8000 of progress has 400 of room left where 10 percent would be 800. A
    preview of 800 told the person 400 less net than the claim then paid.
    """
    project = await _project(pg_session, "AE")
    svc = ContractsService(pg_session)
    contract = await _create(svc, project, contract_type="cost_plus", terms={"fee_percent": "0"})
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Main BOQ")
    pg_session.add(boq)
    await pg_session.flush()
    position = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="01.001",
        description="Concrete",
        unit="m3",
        quantity="100",
        unit_rate="200",
        total="20000",
    )
    pg_session.add(position)
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="A",
        description="Concrete",
        quantity=Decimal("10"),
        unit_rate=Decimal("2000"),
        total_value=Decimal("20000"),
        order_index=0,
        metadata_={BOQ_POSITION_META_KEY: str(position.id)},
    )
    pg_session.add(line)
    contract.status = "active"
    await pg_session.flush()

    march = await svc.auto_generate_claim_lines(
        (await _claim(pg_session, contract, "PC-3", 3)).id,
        AutoGenerateClaimRequest(actual_costs_total=Decimal("46000")),
    )
    assert march.retention_amount == Decimal("4600")
    await svc.transition_claim(march.id, "submitted", "cap-test")

    april = await _claim(pg_session, contract, "PC-4", 4)
    pg_session.add(
        ProgressEntry(
            id=uuid.uuid4(),
            project_id=project.id,
            boq_position_id=position.id,
            period_label="2026-04",
            percent_complete=Decimal("40"),
            recorded_at=datetime(2026, 4, 10, 9, 0, tzinfo=UTC),
        )
    )
    await pg_session.flush()

    preview = await svc.populate_claim_from_progress(april.id)
    assert preview["gross"] == Decimal("8000")
    assert preview["retention"] == Decimal("400")
    assert preview["net_due"] == Decimal("7600")

    [item] = preview["items"]
    committed = await svc.commit_preview_to_claim(
        april.id,
        [SimpleNamespace(contract_line_id=item["contract_line_id"], period_completed_pct=item["observed_pct"])],
    )
    assert committed.gross_amount == preview["gross"]
    assert committed.retention_amount == preview["retention"]
    assert committed.net_due == preview["net_due"]


async def test_the_subcontractor_rollup_preview_holds_the_same_capped_rate(pg_session, monkeypatch) -> None:
    """The claim preview built from the subs' pay applications used the full rate too.

    What the subs billed is stubbed to one 8000 line; the rollup itself is
    tested elsewhere. What matters here is the retention the preview puts
    beside that gross once March has held 4600 of a 5000 ceiling.
    """
    from app.modules.subcontractors import rollup as sub_rollup

    svc = ContractsService(pg_session)
    contract = await _create(
        svc, await _project(pg_session, "AE"), contract_type="cost_plus", terms={"fee_percent": "0"}
    )
    contract.status = "active"
    await pg_session.flush()
    march = await svc.auto_generate_claim_lines(
        (await _claim(pg_session, contract, "PC-3", 3)).id,
        AutoGenerateClaimRequest(actual_costs_total=Decimal("46000")),
    )
    await svc.transition_claim(march.id, "submitted", "cap-test")
    april = await _claim(pg_session, contract, "PC-4", 4)

    subs = SubcontractorService(pg_session)

    async def _rollup(_claim, _contract):
        return {"currency": "EUR"}, [], []

    monkeypatch.setattr(subs, "_assemble_claim_rollup", _rollup)
    monkeypatch.setattr(sub_rollup, "suggest_claim_lines", lambda *_args: [{"period_completed_value": Decimal("8000")}])
    preview = await subs.suggested_claim_lines(april.id)
    assert preview["gross"] == Decimal("8000")
    # 10 percent would be 800; the ceiling leaves 400.
    assert preview["retention"] == Decimal("400")


async def test_a_schedule_of_values_contract_holds_the_cap_in_total(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(
        svc,
        await _project(pg_session, None),
        retention_percent=Decimal("10"),
        retention_cap_percent=Decimal("5"),
    )
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="A",
        description="Works",
        quantity=Decimal("1"),
        unit_rate=Decimal("100000"),
        total_value=Decimal("100000"),
        order_index=0,
    )
    pg_session.add(line)
    contract.status = "active"
    contract.original_contract_value = Decimal("100000")
    await pg_session.flush()

    accruals = []
    for month, percent in ((3, "40"), (4, "60"), (5, "90")):
        claim = await svc.auto_generate_claim_lines(
            (await _claim(pg_session, contract, f"PC-{month}", month)).id,
            AutoGenerateClaimRequest(completion={str(line.id): Decimal(percent)}),
        )
        accruals.append(claim.retention_amount)
        await svc.transition_claim(claim.id, "submitted", "cap-test")

    assert accruals == [Decimal("4000"), Decimal("1000"), Decimal("0")]
    assert claim.retention_held_to_date == Decimal("5000")


async def test_a_schedule_cleared_on_purpose_is_not_given_the_contracts_cap(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _project(pg_session, "FR"))
    assert (await svc.retention_policy(contract)).cap_percent_of_contract_sum == Decimal("5")

    from app.modules.contracts.schemas import RetentionPolicyUpdate

    await svc.set_retention_policy(
        contract,
        RetentionPolicyUpdate(
            tiers=[{"from_percent_complete": Decimal("0"), "rate": Decimal("5")}],
            cap_percent_of_contract_sum=None,
        ),
    )
    assert (await svc.retention_policy(contract)).cap_percent_of_contract_sum is None


# ── Subcontracts take the same defaults ──────────────────────────────


async def _agreement(session, project: Project, **fields):
    svc = SubcontractorService(session)
    sub = await svc.create_subcontractor(SubcontractorCreate(legal_name=f"Sub {uuid.uuid4().hex[:6]}"))
    return await svc.create_agreement(
        AgreementCreate(
            subcontractor_id=sub.id,
            project_id=project.id,
            title="Drywall",
            total_value=Decimal("50000"),
            currency="EUR",
            **fields,
        )
    )


async def test_a_subcontract_starts_from_the_same_rate_as_a_contract_there(pg_session) -> None:
    agreement = await _agreement(pg_session, await _project(pg_session, "GB"))
    assert agreement.retention_percent == Decimal("3")
    assert agreement.retention_release_event == "substantial_completion"
    stamp = agreement.metadata_["country_defaults"]
    assert set(stamp["applied"]) == {"retention_percent", "retention_release_event"}


@pytest.mark.parametrize(("country", "rate"), [("GB", "3"), ("DE", "5"), ("FR", "5"), ("CN", "3"), ("US", "10")])
async def test_a_subcontract_takes_the_countrys_rate_where_it_is_within_the_cap(pg_session, country, rate) -> None:
    agreement = await _agreement(pg_session, await _project(pg_session, country))
    assert agreement.retention_percent == Decimal(rate)
    stamp = agreement.metadata_["country_defaults"]
    assert "retention_percent_from" not in stamp
    assert (
        stamp["sources"]["retention_percent"]["note"]
        == (COUNTRY_CONTRACT_DEFAULTS[country]["retention_percent"]["note"])
    )


@pytest.mark.parametrize("country", ["AE", "SA"])
async def test_a_gulf_subcontract_never_holds_past_the_fidic_limit(pg_session, country) -> None:
    """FIDIC says ten percent until five percent of the sum is held; an agreement has no ceiling.

    Started at the country's ten percent, an agreement billed in full would
    hold 100,000 on 1,000,000, twice the limit the same row states. It starts
    from the limit instead, and the stamp says the rate is the cap.
    """
    project = await _project(pg_session, country)
    svc = SubcontractorService(pg_session)
    sub = await svc.create_subcontractor(SubcontractorCreate(legal_name=f"Sub {uuid.uuid4().hex[:6]}"))
    # What a subcontractor must hold to be paid at all.
    for cert_type in ("insurance", "license"):
        pg_session.add(
            Certificate(subcontractor_id=sub.id, cert_type=cert_type, valid_until=date(2030, 12, 31), status="valid")
        )
    await pg_session.flush()
    agreement = await svc.create_agreement(
        AgreementCreate(
            subcontractor_id=sub.id,
            project_id=project.id,
            title="MEP",
            total_value=Decimal("1000000"),
            currency="AED",
        )
    )
    assert agreement.retention_percent == Decimal("5")
    stamp = agreement.metadata_["country_defaults"]
    assert stamp["applied"]["retention_percent"] == "5"
    assert stamp["retention_percent_from"] == "retention_cap_percent"
    assert "Limit of Retention Money" in stamp["sources"]["retention_percent"]["reference"]

    await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))
    held = Decimal("0")
    for gross in (Decimal("600000"), Decimal("400000")):
        payment = await svc.submit_payment_application(
            PaymentApplicationCreate(agreement_id=agreement.id, gross_amount=gross, currency="AED"),
            today=date(2026, 9, 30),
        )
        assert payment.net_amount == payment.gross_amount - payment.retention_amount
        held += payment.retention_amount
    # The whole agreement billed holds exactly the FIDIC limit, not 100,000.
    assert held == Decimal("50000")

    # The contract above it keeps ten percent with the cap that stops it.
    view = await ContractsService(pg_session).country_defaults_for_project(project.id)
    assert view["values"]["retention_percent"] == "10"
    assert view["subcontract_retention_percent"] == "5"
    assert view["subcontract_retention_from"] == "retention_cap_percent"


async def test_a_subcontract_rate_sent_wins_and_stamps_nothing(pg_session) -> None:
    agreement = await _agreement(pg_session, await _project(pg_session, "GB"), retention_percent=Decimal("5"))
    assert agreement.retention_percent == Decimal("5")
    assert "country_defaults" not in (agreement.metadata_ or {})


async def test_a_subcontract_with_no_country_is_stamped_as_a_fallback(pg_session) -> None:
    agreement = await _agreement(pg_session, await _project(pg_session, None))
    assert agreement.retention_percent == Decimal("5")
    assert agreement.metadata_["country_defaults"]["fallback"] == ["retention_percent"]


async def test_a_project_id_with_no_row_still_creates_on_the_fallback(pg_session) -> None:
    # The country lookup must not turn a missing project into a 500.
    project = SimpleNamespace(id=uuid.uuid4())
    svc = ContractsService(pg_session)
    assert await svc.project_country(project.id) is None


# ── A province reaches the services, not only the resolver ───────────


async def _manitoba_project(session) -> Project:
    project = await _project(session, "CA")
    project.subdivision_code = "CA-MB"
    await session.flush()
    return project


async def test_a_manitoba_contract_starts_from_the_provincial_holdback(pg_session) -> None:
    """The resolver knows Manitoba; the contract only does if the service passes the province on."""
    svc = ContractsService(pg_session)
    contract = await _create(svc, await _manitoba_project(pg_session))
    assert contract.retention_percent == Decimal("7.5")
    stamp = contract.metadata_["country_defaults"]
    assert "retention_percent" in stamp["applied"]
    assert "Manitoba" in stamp["sources"]["retention_percent"]["note"]


async def test_the_contract_form_offers_the_provincial_rate(pg_session) -> None:
    svc = ContractsService(pg_session)
    answer = await svc.country_defaults_for_project((await _manitoba_project(pg_session)).id)
    assert answer["subdivision_code"] == "CA-MB"
    assert Decimal(str(answer["values"]["retention_percent"])) == Decimal("7.5")


async def test_a_manitoba_subcontract_starts_from_the_provincial_holdback(pg_session) -> None:
    agreement = await _agreement(pg_session, await _manitoba_project(pg_session))
    assert agreement.retention_percent == Decimal("7.5")


async def test_a_canadian_project_without_a_province_keeps_the_national_row(pg_session) -> None:
    """The control: the same create without a province reads ten, so 7.5 above came from the province."""
    contract = await _create(ContractsService(pg_session), await _project(pg_session, "CA"))
    assert contract.retention_percent == Decimal("10")
