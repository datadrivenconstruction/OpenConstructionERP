# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A French contract's retention follows the law of its works, public or private.

The French row of the contract defaults cited loi n° 71-584 for the rate, the
ceiling and the release of every French contract. That law governs private
works only ("marchés de travaux privés", art. 1). A public contract is
governed by the Code de la commande publique, art. R2191-32 to R2191-42: the
ceiling is five percent of the initial amount plus modifications, three for
an SME under the State and large public buyers (R2191-33), and the retenue is
repaid within 30 days of the end of the délai de garantie or of the lifting of
reserves (R2191-35), not one year after réception unless the client objects.

A project now records whether its client is a public buyer (``works``). These
tests hold what each answer does: public reads the Code, private keeps 71-584,
an unrecorded project keeps today's figures and notes but no longer cites the
private statute alone, a subcontract is private whoever the client is, and no
other country changes.
"""

from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.contracts.country_defaults import (
    COUNTRY_CONTRACT_DEFAULTS,
    WORKS_CONTRACT_DEFAULTS,
    WORKS_NOTE_KEY_PREFIX,
    contract_works,
    note_key,
    resolve_contract_defaults,
    works_note_key,
)
from app.modules.contracts.schemas import ContractCreate
from app.modules.contracts.service import ContractsService
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.subcontractors.schemas import AgreementCreate
from app.modules.subcontractors.service import SubcontractorService

_EN_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "locales" / "en.ts"
_RETENTION = ("retention_percent", "retention_cap_percent", "retention_release_split")
_SPLIT = [{"event": "defects_period_end", "release_percent_of_held": "100"}]


class _Session:
    """Answers ``session.get`` with one project and nothing else."""

    def __init__(self, project: Any) -> None:
        self._project = project

    async def get(self, _model: Any, _key: Any) -> Any:
        return self._project


def _project(works: str | None, country: str = "FR") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), country_code=country, address={"city": "Lyon", "postcode": "69003"}, works=works
    )


def _create(project: SimpleNamespace, counterparty_type: str = "client") -> ContractCreate:
    return ContractCreate(
        code=f"C-{uuid.uuid4().hex[:8]}",
        contract_type="lump_sum",
        counterparty_type=counterparty_type,
        project_id=project.id,
        total_value=Decimal("1000000"),
    )


# ── Public contracts read the Code de la commande publique ───────────────────


def test_a_french_public_contract_starts_from_the_public_procurement_code() -> None:
    resolved = resolve_contract_defaults("FR", works="public")

    assert resolved["works"] == "public"
    assert resolved["standard_form"] == "CCAG-Travaux 2021"
    assert resolved["values"]["retention_percent"] == "5"
    assert resolved["values"]["retention_cap_percent"] == "5"
    assert resolved["values"]["retention_release_split"] == _SPLIT
    sources = resolved["sources"]
    assert "R2191-33" in sources["retention_percent"]["reference"]
    assert "R2191-33" in sources["retention_cap_percent"]["reference"]
    assert "R2191-35" in sources["retention_release_split"]["reference"]
    for field in _RETENTION:
        assert "71-584" not in sources[field]["reference"], f"{field} cites the private-works statute"
        assert sources[field]["source"] == "statute"
        assert sources[field]["note_key"] == works_note_key("FR", "public", field)


def test_the_public_notes_say_what_the_code_says() -> None:
    notes = {f: resolve_contract_defaults("FR", works="public")["sources"][f]["note"] for f in _RETENTION}
    # R2191-33: a lower ceiling for an SME, not a set rate.
    assert "three percent" in notes["retention_cap_percent"]
    # R2191-35: 30 days after the délai de garantie, not one year after réception.
    assert "30 days" in notes["retention_release_split"]
    assert "objected" not in notes["retention_release_split"]
    # The code does not say net or gross of VAT, so no note claims it. The
    # basis, TTC for public works on the ministry's reading, is not a figure
    # the parties pick and lives in COUNTRY_RETENTION_BASIS instead.
    for note in notes.values():
        assert "VAT" not in note and "TTC" not in note and "HT " not in note


@pytest.mark.asyncio
async def test_a_contract_with_a_public_client_is_stamped_with_the_code() -> None:
    project = _project("public")
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    terms, retention, event, stamp = await svc._payment_terms_for_new_contract(_create(project))

    assert retention == Decimal("5")
    assert event == "defects_period_end"
    assert terms["payment_terms"]["retention_cap_percent"] == "5"
    assert stamp["works"] == "public"
    assert "R2191-33" in stamp["sources"]["retention_percent"]["reference"]
    assert "R2191-35" in stamp["sources"]["retention_release_split"]["reference"]


@pytest.mark.asyncio
async def test_the_form_prefills_what_the_server_writes_for_a_public_client() -> None:
    project = _project("public")
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    shown = await svc.country_defaults_for_project(project.id)

    assert shown["works"] == "public"
    assert shown["standard_form"] == "CCAG-Travaux 2021"
    assert "R2191-33" in shown["sources"]["retention_percent"]["reference"]


# ── Private works keep loi 71-584 ─────────────────────────────────────────────


def test_french_private_works_stay_on_loi_71_584() -> None:
    resolved = resolve_contract_defaults("FR", works="private")
    row = COUNTRY_CONTRACT_DEFAULTS["FR"]

    assert resolved["works"] == "private"
    assert resolved["standard_form"] == "NF P03-001"
    assert resolved["sources"]["retention_percent"]["reference"] == "Loi n° 71-584 du 16 juillet 1971, art. 1"
    assert resolved["sources"]["retention_cap_percent"]["reference"] == "Loi n° 71-584 du 16 juillet 1971, art. 1"
    assert resolved["sources"]["retention_release_split"]["reference"] == "Loi n° 71-584 du 16 juillet 1971, art. 2"
    for field in _RETENTION:
        assert "R2191" not in resolved["sources"][field]["reference"]
        # Same figure and same note as the row, so the same translated key.
        assert resolved["values"][field] == row[field]["value"]
        assert resolved["sources"][field]["note"] == row[field]["note"]
        assert resolved["sources"][field]["note_key"] == note_key("FR", field)


@pytest.mark.asyncio
async def test_a_subcontract_on_a_public_project_is_private_works() -> None:
    # The main contractor who lets a subcontract is not a public buyer.
    project = _project("public")
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    _terms, _retention, _event, stamp = await svc._payment_terms_for_new_contract(_create(project, "subcontractor"))

    assert stamp["works"] == "private"
    assert "71-584" in stamp["sources"]["retention_percent"]["reference"]
    assert "R2191" not in stamp["sources"]["retention_percent"]["reference"]


@pytest.mark.asyncio
async def test_a_subcontract_agreement_on_a_public_project_is_private_works() -> None:
    project = _project("public")
    svc = SubcontractorService(_Session(project))  # type: ignore[arg-type]

    rate, _event, stamp = await svc._agreement_retention_terms(
        AgreementCreate(subcontractor_id=uuid.uuid4(), project_id=project.id, title="Gros oeuvre")
    )

    assert rate == Decimal("5")
    assert stamp is not None
    assert stamp["works"] == "private"
    assert "71-584" in stamp["sources"]["retention_percent"]["reference"]


@pytest.mark.parametrize(
    ("project_works", "counterparty", "expected"),
    [
        ("public", "client", "public"),
        ("private", "client", "private"),
        (None, "client", None),
        ("public", None, "public"),
        ("public", "subcontractor", "private"),
        (None, "subcontractor", "private"),
        ("semi-public", "client", None),
    ],
)
def test_which_law_a_contract_follows(
    project_works: str | None, counterparty: str | None, expected: str | None
) -> None:
    assert contract_works(project_works, counterparty) == expected


# ── Not recorded: today's figures, a citation that names both laws ────────────


def test_an_unrecorded_french_contract_keeps_todays_figures() -> None:
    resolved = resolve_contract_defaults("FR")

    assert resolved["works"] is None
    assert resolved["standard_form"] == "NF P03-001 / CCAG-Travaux"
    assert resolved["values"] == {
        "retention_percent": "5",
        "retention_cap_percent": "5",
        "retention_release_split": _SPLIT,
        "payment_period_days": 30,
        "valuation_interval": "monthly",
        "certificate_name": "Situation de travaux",
    }
    for field in resolved["sources"]:
        assert resolved["sources"][field]["note_key"] == note_key("FR", field)
    assert resolve_contract_defaults("FR", works=None) == resolved
    assert resolve_contract_defaults("FR", works="unknown") == resolved


def test_an_unrecorded_french_contract_does_not_cite_the_private_statute_alone() -> None:
    sources = resolve_contract_defaults("FR")["sources"]
    for field in _RETENTION:
        reference = sources[field]["reference"]
        assert "71-584" in reference and "private works" in reference, reference
        assert "R2191-3" in reference and "public contracts" in reference, reference


@pytest.mark.asyncio
async def test_an_unrecorded_french_contract_stamps_no_works() -> None:
    project = _project(None)
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    _terms, retention, _event, stamp = await svc._payment_terms_for_new_contract(_create(project))

    assert retention == Decimal("5")
    assert "works" not in stamp


# ── Every other country is untouched ─────────────────────────────────────────


@pytest.mark.parametrize("country", sorted(set(COUNTRY_CONTRACT_DEFAULTS) - set(WORKS_CONTRACT_DEFAULTS)))
@pytest.mark.parametrize("works", ["public", "private"])
def test_a_country_without_a_works_variant_ignores_the_works(country: str, works: str) -> None:
    assert resolve_contract_defaults(country, works=works) == resolve_contract_defaults(country)


def test_only_france_has_a_works_variant_so_far() -> None:
    # Adding a country here is a decision with its own primary sources, not a refactor.
    assert set(WORKS_CONTRACT_DEFAULTS) == {"FR"}


# ── The project field ─────────────────────────────────────────────────────────


def test_a_project_records_public_private_or_nothing() -> None:
    assert ProjectCreate(name="Lycée", works="public").works == "public"
    assert ProjectCreate(name="Villa", works="private").works == "private"
    assert ProjectCreate(name="Unknown").works is None
    assert ProjectUpdate(works=None).model_dump(exclude_unset=True) == {"works": None}
    with pytest.raises(ValidationError):
        ProjectCreate(name="Mixed", works="semi-public")
    with pytest.raises(ValidationError):
        ProjectUpdate(works="Public")


# ── The notes a reader sees ──────────────────────────────────────────────────


def _en_works_notes() -> dict[str, str]:
    if not _EN_TS.is_file():
        pytest.skip(f"no frontend tree beside the backend at {_EN_TS}")
    entry = re.compile(r'^\s*"(' + re.escape(WORKS_NOTE_KEY_PREFIX) + r'[^"]+)"\s*:\s*("(?:[^"\\]|\\.)*")\s*,?\s*$')
    found: dict[str, str] = {}
    for line in _EN_TS.read_text(encoding="utf-8").splitlines():
        match = entry.match(line)
        if match:
            found[match.group(1)] = json.loads(match.group(2))
    return found


def _table_works_notes() -> dict[str, str]:
    return {
        works_note_key(country, works, field): variant[field]["note"]
        for country, variants in WORKS_CONTRACT_DEFAULTS.items()
        for works, variant in variants.items()
        for field in variant
        if isinstance(variant[field], dict) and "note" in variant[field]
    }


def test_every_works_note_is_in_en_ts_word_for_word() -> None:
    en = _en_works_notes()
    table = _table_works_notes()
    assert table, "the works table carries no note, so this test reads nothing"
    assert set(table) == set(en), f"missing: {sorted(set(table) - set(en))}; stale: {sorted(set(en) - set(table))}"
    drifted = sorted(key for key, note in table.items() if en[key] != note)
    assert not drifted, f"en.ts text differs from the works table for: {drifted}"
