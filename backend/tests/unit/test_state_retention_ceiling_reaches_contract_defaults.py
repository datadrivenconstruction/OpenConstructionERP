# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A state's statutory retention ceiling reaches the terms a US contract starts from.

The US row of the contract defaults opens retention at ten percent, which is
the common pattern where no statute speaks. California has capped retention at
five percent of each payment on private work since 1 January 2026 (Civil Code
§ 8811, added by SB 61) and on public work since 2012 (Public Contract Code
§ 7201). The California pack carried both rules, dated and cited, but nothing
on the contract path could reach them: the defaults were read by country
alone, so a California contract started at ten percent, twice what the law
allows.

These tests hold the join. The state comes from the project address, which is
where a US address keeps it. The ceiling is chosen by the date the contract is
entered into, so an agreement dated before the private cap commenced keeps the
national figure. A state whose pack writes no ceiling that binds every kind of
works (Texas caps public work only) changes nothing, and neither does a US
project whose state is not recorded.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.contracts import country_defaults
from app.modules.contracts.country_defaults import (
    STATUTORY_CEILING_NOTE_KEY,
    resolve_contract_defaults,
    statutory_retention_ceiling,
    subcontract_retention_default,
    subdivision_from_address,
)
from app.modules.contracts.schemas import ContractCreate
from app.modules.contracts.service import ContractsService
from app.modules.subcontractors.schemas import AgreementCreate
from app.modules.subcontractors.service import SubcontractorService
from app.modules.us_ca_pack.config import STATE_RULES as CA_RULES
from app.modules.us_tx_pack.config import STATE_RULES as TX_RULES

_EN_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "locales" / "en.ts"


class _Session:
    """Answers ``session.get`` with one project and nothing else."""

    def __init__(self, project: Any) -> None:
        self._project = project

    async def get(self, _model: Any, _key: Any) -> Any:
        return self._project


def _project(state: str | None, country: str | None = "US") -> SimpleNamespace:
    address = {"street": "1 Main St", "city": "Sacramento", "postcode": "95814"}
    if state is not None:
        address["state"] = state
    return SimpleNamespace(id=uuid.uuid4(), country_code=country, address=address)


def _create(project: SimpleNamespace) -> ContractCreate:
    return ContractCreate(
        code=f"C-{uuid.uuid4().hex[:8]}",
        contract_type="lump_sum",
        project_id=project.id,
        total_value=Decimal("1000000"),
    )


def _freeze_today(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    monkeypatch.setattr(country_defaults, "_today", lambda: day)


# ── The defect: a California contract started at ten percent ──────────────────


@pytest.mark.asyncio
async def test_a_california_contract_starts_within_the_state_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_today(monkeypatch, date(2026, 10, 5))
    project = _project("CA")
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    _terms, retention, _event, stamp = await svc._payment_terms_for_new_contract(_create(project))

    assert retention == Decimal("5"), f"a California contract entered into in 2026 started at {retention} percent"
    source = stamp["sources"]["retention_percent"]
    assert source["source"] == "statute"
    assert "§ 8811" in source["reference"]
    assert "§ 7201" in source["reference"]
    assert source["note_key"] == STATEWIDE_KEY


@pytest.mark.asyncio
async def test_the_form_prefills_the_same_figure_the_server_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_today(monkeypatch, date(2026, 10, 5))
    project = _project("CA")
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    shown = await svc.country_defaults_for_project(project.id)

    assert shown["values"]["retention_percent"] == "5"
    assert shown["subcontract_retention_percent"] == "5"
    assert shown["subdivision_code"] == "US-CA"


@pytest.mark.asyncio
async def test_a_california_subcontract_starts_within_the_state_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    # § 8811(b)(1)(A) reaches every tier, contractor to subcontractor included.
    _freeze_today(monkeypatch, date(2026, 10, 5))
    project = _project("CA")
    svc = SubcontractorService(_Session(project))  # type: ignore[arg-type]

    rate, _event, stamp = await svc._agreement_retention_terms(
        AgreementCreate(subcontractor_id=uuid.uuid4(), project_id=project.id, title="Drywall")
    )

    assert rate == Decimal("5")
    assert stamp is not None
    assert stamp["sources"]["retention_percent"]["source"] == "statute"


# ── The date the contract is entered into decides ─────────────────────────────


def test_an_agreement_entered_into_in_2025_keeps_the_national_figure() -> None:
    # The public cap was in force, the private one was not: with the works type
    # unrecorded there is no ceiling that binds every California contract.
    resolved = resolve_contract_defaults("US", subdivision_code="US-CA", as_of=date(2025, 12, 31))
    assert resolved is not None
    assert resolved["values"]["retention_percent"] == "10"
    assert resolved["statutory_ceiling"] is None


def test_the_private_cap_binds_from_its_first_day() -> None:
    # "entered into on or after January 1, 2026": the boundary is inclusive.
    resolved = resolve_contract_defaults("US", subdivision_code="US-CA", as_of=date(2026, 1, 1))
    assert resolved is not None
    assert resolved["values"]["retention_percent"] == "5"
    ceiling = resolved["statutory_ceiling"]
    assert ceiling["percent"] == "5"
    assert ceiling["subdivision_code"] == "US-CA"
    assert {rule["code"] for rule in ceiling["rules"]} == {"ca_private_retention_cap", "ca_public_retention_cap"}


@pytest.mark.asyncio
async def test_a_california_contract_created_in_2025_kept_ten_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_today(monkeypatch, date(2025, 6, 1))
    project = _project("CA")
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    _terms, retention, _event, stamp = await svc._payment_terms_for_new_contract(_create(project))

    assert retention == Decimal("10")
    assert stamp["sources"]["retention_percent"]["source"] == "industry_practice"


# ── Other states, and a state nobody recorded, are unchanged ──────────────────


@pytest.mark.asyncio
async def test_a_texas_contract_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    # Texas caps retainage on public work only, so with the works type
    # unrecorded nothing binds every Texas contract.
    _freeze_today(monkeypatch, date(2026, 10, 5))
    project = _project("TX")
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    _terms, retention, _event, _stamp = await svc._payment_terms_for_new_contract(_create(project))

    assert retention == Decimal("10")
    assert resolve_contract_defaults("US", subdivision_code="US-TX", as_of=date(2026, 10, 5)) == (
        resolve_contract_defaults("US", as_of=date(2026, 10, 5))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [None, "", "NY"])
async def test_a_us_project_without_a_state_pack_keeps_ten_percent(
    monkeypatch: pytest.MonkeyPatch, state: str | None
) -> None:
    _freeze_today(monkeypatch, date(2026, 10, 5))
    project = _project(state)
    svc = ContractsService(_Session(project))  # type: ignore[arg-type]

    _terms, retention, _event, _stamp = await svc._payment_terms_for_new_contract(_create(project))

    assert retention == Decimal("10")


def test_an_author_figure_still_wins() -> None:
    # A default pre-fills and never locks: the statute has exceptions (a
    # low-rise purely residential job, a subcontractor that failed to bond, a
    # public job found substantially complex) under which more may be agreed.
    from app.modules.contracts.country_defaults import apply_contract_defaults

    defaults = resolve_contract_defaults("US", subdivision_code="US-CA", as_of=date(2026, 10, 5))
    values, stamp = apply_contract_defaults({"retention_percent": "10"}, defaults, country_code="US")
    assert values["retention_percent"] == "10"
    assert "retention_percent" not in stamp["applied"]


def test_a_country_with_no_state_rules_is_untouched_by_a_subdivision() -> None:
    assert resolve_contract_defaults("GB", subdivision_code="GB-ENG", as_of=date(2026, 10, 5)) == (
        resolve_contract_defaults("GB")
    )


def test_the_subcontract_default_follows_the_ceiling() -> None:
    defaults = resolve_contract_defaults("US", subdivision_code="US-CA", as_of=date(2026, 10, 5))
    assert subcontract_retention_default(defaults) == ("5", "retention_percent")


# ── Where the state comes from ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ({"state": "CA"}, "US-CA"),
        ({"state": " ca "}, "US-CA"),
        ({"state": "US-CA"}, "US-CA"),
        ({"state": "California"}, "US-CA"),
        ({"state": "TX"}, "US-TX"),
        ({"state": "NY"}, "US-NY"),
        ({"state": "Calif."}, None),
        ({"state": "CA-ON"}, None),
        ({"state": ""}, None),
        ({}, None),
        (None, None),
    ],
)
def test_the_state_is_read_from_the_address_without_guessing(address: Any, expected: str | None) -> None:
    assert subdivision_from_address("US", address) == expected


def test_no_country_means_no_state() -> None:
    assert subdivision_from_address(None, {"state": "CA"}) is None


# ── The rules are data, dated and cited ──────────────────────────────────────


def _ceiling_rules() -> list[dict[str, Any]]:
    return [
        rule
        for rules in (CA_RULES, TX_RULES)
        for rule in rules.get("retainage", [])
        if rule.get("per_payment_percent") is not None
    ]


def test_every_per_payment_ceiling_says_which_works_and_from_which_day() -> None:
    rules = _ceiling_rules()
    assert rules, "no state pack writes a per-payment retention ceiling"
    for rule in rules:
        assert rule.get("works") in ("private", "public"), rule["code"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(rule.get("effective_date"))), rule["code"]
        assert rule.get("statute_reference"), rule["code"]
        Decimal(rule["per_payment_percent"])


def test_the_reader_names_no_state() -> None:
    # The join is data-driven: nothing in the reader may special-case a state.
    source = Path(country_defaults.__file__).read_text(encoding="utf-8")
    assert "US-CA" not in source
    assert "8811" not in source


def test_statutory_ceiling_is_none_without_a_subdivision() -> None:
    assert statutory_retention_ceiling("US", None, as_of=date(2026, 10, 5)) is None
    assert statutory_retention_ceiling("US", "US-NY", as_of=date(2026, 10, 5)) is None


# ── The note a reader sees beside the figure ─────────────────────────────────

STATEWIDE_KEY = STATUTORY_CEILING_NOTE_KEY


def test_the_ceiling_note_is_in_en_ts_word_for_word() -> None:
    if not _EN_TS.is_file():
        pytest.skip(f"no frontend tree beside the backend at {_EN_TS}")
    entry = re.compile(r'^\s*"' + re.escape(STATUTORY_CEILING_NOTE_KEY) + r'"\s*:\s*("(?:[^"\\]|\\.)*")\s*,?\s*$')
    found = [
        json.loads(m.group(1)) for line in _EN_TS.read_text(encoding="utf-8").splitlines() if (m := entry.match(line))
    ]
    assert found == [country_defaults.STATUTORY_CEILING_NOTE], "en.ts must carry the ceiling note once, word for word"
