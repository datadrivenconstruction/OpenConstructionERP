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
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.events import event_bus
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest, ContractCreate, ContractUpdate
from app.modules.contracts.service import RELEASE_RULE_FROM_CONTRACT, RELEASE_RULE_FROM_PACK, ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.subcontractors.schemas import AgreementCreate, SubcontractorCreate
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
