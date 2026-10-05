# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A French public contract holds its retenue de garantie on the TTC payment.

The Code de la commande publique (R2191-32 to R2191-36) sets the retenue at
up to five percent of the initial amount and has it withheld in instalments
from each payment, without saying HT or TTC. The ministry's legal directorate
reads both as TTC in its technical fiche "Les garanties financières"
(Direction des affaires juridiques, economie.gouv.fr, updated 2019-04-01,
page 4): the initial amount the ceiling is taken on is the one in the acte
d'engagement, "toutes taxes comprises", and each instalment is taken from
the payment after price revision and after the VAT is added (the "prix de
paiement").

The case: an acompte of 92,260.14 HT at 20 % TVA is 110,712.17 TTC. Five
percent of that is 5,535.61. Measured on the HT, as the platform did, it was
4,613.01.

Only public works move. Private works under loi 71-584, a project that does
not record its works, and every subcontract (a main contractor is not a
public buyer) keep the HT basis they had.

Pure tests, no database.

Run::

    cd backend
    python -m pytest tests/unit/test_french_public_retention_is_cut_from_the_payment_with_tva.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.contracts.country_defaults import (
    COUNTRY_RETENTION_BASIS,
    resolve_retention_basis,
)
from app.modules.contracts.retention import (
    RETENTION_BASIS_GROSS,
    RETENTION_BASIS_NET,
    RetentionPolicy,
    claim_retention,
    compute_retention,
    flat_policy,
    flat_retention_within_cap,
    on_retention_basis,
)
from app.modules.contracts.service import ContractsService

D = Decimal

ACOMPTE_HT = D("92260.14")
CONTRACT_SUM_HT = D("1000000.00")


def _capped(rate: str, cap: str) -> RetentionPolicy:
    policy = flat_policy(rate)
    return RetentionPolicy(tiers=policy.tiers, source=policy.source, cap_percent_of_contract_sum=D(cap))


def _engine_accrual(basis_vat: Decimal | None) -> Decimal:
    position = compute_retention(
        {"L1": ACOMPTE_HT},
        contract_sum=CONTRACT_SUM_HT,
        policy=_capped("5", "5"),
        basis_vat_percent=basis_vat,
    )
    figures = claim_retention(position, completed_by_line={"L1": ACOMPTE_HT}, accrued_before=0, released_to_date=0)
    return figures.accrual


# ── The country data ─────────────────────────────────────────────────────


def test_a_french_public_contract_is_measured_on_the_ttc_and_says_why() -> None:
    basis = resolve_retention_basis("FR", works="public")
    assert (basis.basis, basis.vat_percent, basis.vat_source) == (RETENTION_BASIS_GROSS, D("20"), "country_standard")
    assert "R2191-33" in (basis.reference or "")
    assert "garanties financières" in (basis.reference or "")


@pytest.mark.parametrize("works", ["private", None, "", "unknown"])
def test_private_or_unrecorded_french_works_stay_on_the_ht(works: str | None) -> None:
    basis = resolve_retention_basis("FR", works=works, project_vat_rate="20")
    assert (basis.basis, basis.vat_percent) == (RETENTION_BASIS_NET, None)


def test_a_subcontract_on_a_public_project_stays_on_the_ht() -> None:
    # contract_works() turns every subcontract into private works before the
    # basis is resolved; the resolver must not let the flag alone go gross.
    basis = resolve_retention_basis("FR", works="private", subcontract=True, project_vat_rate="20")
    assert (basis.basis, basis.vat_percent) == (RETENTION_BASIS_NET, None)


def test_the_french_row_is_public_works_only_and_presumes_nothing_for_a_subcontract() -> None:
    row = COUNTRY_RETENTION_BASIS["FR"]
    assert row["basis"] == RETENTION_BASIS_GROSS
    assert row["works"] == "public"
    assert "subcontract_vat_percent" not in row


def test_the_contracts_agreed_tva_comes_before_the_projects_and_the_countrys() -> None:
    agreed = resolve_retention_basis("FR", works="public", agreed_vat_rate="10", project_vat_rate="5.5")
    assert (agreed.vat_percent, agreed.vat_source) == (D("10"), "contract_einvoice")
    project = resolve_retention_basis("FR", works="public", project_vat_rate="5.5")
    assert (project.vat_percent, project.vat_source) == (D("5.5"), "project_default")


def test_germany_is_unaffected_by_works() -> None:
    for works in ("public", "private", None):
        assert resolve_retention_basis("DE", works=works).vat_percent == D("19")


# ── The acompte ──────────────────────────────────────────────────────────


def test_the_acompte_holds_five_percent_of_110712_17() -> None:
    vat = resolve_retention_basis("FR", works="public").vat_percent
    assert on_retention_basis(ACOMPTE_HT, vat) == D("110712.17")
    assert _engine_accrual(vat) == D("5535.61")


def test_the_flat_path_holds_the_same() -> None:
    vat = resolve_retention_basis("FR", works="public").vat_percent
    held = flat_retention_within_cap(
        ACOMPTE_HT,
        D("5"),
        cap_percent=D("5"),
        contract_sum=CONTRACT_SUM_HT,
        accrued_before=D("0"),
        basis_vat_percent=vat,
    )
    assert held.quantize(D("0.01")) == D("5535.61")


def test_private_works_still_hold_five_percent_of_the_ht() -> None:
    vat = resolve_retention_basis("FR", works="private").vat_percent
    assert _engine_accrual(vat) == D("4613.01")


# ── The ceiling ──────────────────────────────────────────────────────────


def test_the_public_ceiling_is_five_percent_of_the_initial_amount_ttc() -> None:
    """Between 5 % of the HT sum (50,000) and of the TTC sum (60,000) the two bases part."""
    public = resolve_retention_basis("FR", works="public").vat_percent
    private = resolve_retention_basis("FR", works="private").vat_percent
    kwargs: dict[str, Any] = {
        "cap_percent": D("5"),
        "contract_sum": CONTRACT_SUM_HT,
        "accrued_before": D("55000.00"),
    }
    assert flat_retention_within_cap(ACOMPTE_HT, D("5"), basis_vat_percent=public, **kwargs) == D("5000.00")
    assert flat_retention_within_cap(ACOMPTE_HT, D("5"), basis_vat_percent=private, **kwargs) == D("0")

    position = compute_retention(
        {"L1": D("1000000")}, contract_sum=CONTRACT_SUM_HT, policy=_capped("10", "5"), basis_vat_percent=public
    )
    assert position.capped is True
    assert position.total == D("60000.00")


# ── The service asks with the contract's works ───────────────────────────


class _Session:
    def __init__(self, project: Any) -> None:
        self._project = project

    async def get(self, _model: Any, _id: Any) -> Any:
        return self._project


def _project(works: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), country_code="FR", default_vat_rate=None, works=works)


def _contract(project: SimpleNamespace, counterparty_type: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), project_id=project.id, metadata_={}, counterparty_type=counterparty_type)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("works", "counterparty", "expected"),
    [
        ("public", "client", D("20")),
        ("public", "subcontractor", None),
        ("private", "client", None),
        (None, "client", None),
    ],
)
async def test_the_service_resolves_the_basis_with_the_contracts_works(
    works: str | None, counterparty: str, expected: Decimal | None
) -> None:
    project = _project(works)
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]
    basis = await svc.retention_basis(_contract(project, counterparty))  # type: ignore[arg-type]
    assert basis.vat_percent == expected
