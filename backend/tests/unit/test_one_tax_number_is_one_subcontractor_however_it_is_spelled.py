# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One tax number is one subcontractor, however the number was typed.

``validate_tax_id`` accepts a number in every form its country prints it, and
the register then stored the form that was typed and compared that column for
exact equality. So ``CHE-123.456.789 MWST`` off a German-language letterhead,
``CHE-123.456.789 TVA`` off a French one and ``che123456789`` off an invoice
were three subcontractors, and the duplicate guard, which exists precisely to
stop a firm being registered twice, compared strings the validator had just
declared equivalent and found them different.

The fix is an identity key, ``canonical_tax_id``, beside the validator:
separators, case, an optional country prefix and the register suffixes a
letterhead carries are gone from the key, and the register compares keys.
The stored value is untouched: what was typed is what the screen shows.

Two halves, in the two places the decision is made:

* The key itself, with no database: every spelling of one number reduces to
  one key, different numbers keep different keys, and refused input still
  gets a deterministic key rather than an empty one.
* The register, on the shared PostgreSQL unit database inside a rolled-back
  transaction: a second spelling of a held number is a 409 on create and on a
  PATCH that re-types another firm's number, a firm may re-spell its own, a
  different number or the same digits in another country is a second firm,
  and a deactivated firm no longer blocks the number.

Synthetic values throughout. ``CHE-123.456.789 MWST`` is the specimen the
Swiss Federal Tax Administration prints in its own guidance.

Run:  python -m pytest tests/unit/test_one_tax_number_is_one_subcontractor_however_it_is_spelled.py -q
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.subcontractors.models import Subcontractor
from app.modules.subcontractors.schemas import SubcontractorCreate, SubcontractorUpdate
from app.modules.subcontractors.service import SubcontractorService
from app.modules.subcontractors.tax_id import canonical_tax_id, tax_id_digit_run, validate_tax_id

# ── The key ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OneNumber:
    """Spellings of a single number as they arrive from letterheads and forms."""

    country: str
    key: str
    written: tuple[str, ...]


_ONE_NUMBER: tuple[OneNumber, ...] = (
    OneNumber(
        country="CH",
        key="CHE123456789",
        written=(
            "CHE-123.456.789 MWST",
            "CHE-123.456.789 TVA",
            "CHE-123.456.789 IVA",
            "che123456789",
            "CHE 123 456 789",
            "E123456789",
            "123456789",
        ),
    ),
    OneNumber(
        country="DE",
        key="123456789",
        written=("DE 123 456 789", "DE123456789", "de-123.456.789", "123456789"),
    ),
    OneNumber(
        country="GB",
        key="123456789",
        written=("GB 123 4567 89", "GB123456789", "gb123 4567 89", "123 4567 89"),
    ),
    OneNumber(
        country="US",
        key="123456789",
        written=("12-3456789", "123456789", "12 3456789"),
    ),
    OneNumber(
        country="RU",
        key="7707083893",
        written=("7707083893", "7707 083893", "RU7707083893"),
    ),
    OneNumber(
        country="NO",
        key="123456789",
        written=("123 456 789 MVA", "NO123456789MVA", "123456789"),
    ),
)


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c.country}-{c.key}") for c in _ONE_NUMBER])
def test_every_spelling_of_one_number_has_one_key(case: OneNumber) -> None:
    assert {canonical_tax_id(case.country, spelling) for spelling in case.written} == {case.key}


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c.country}-{c.key}") for c in _ONE_NUMBER])
def test_every_spelling_is_still_valid_and_the_validator_still_echoes_what_it_read(case: OneNumber) -> None:
    """The key folds; the validator does not.

    The form's answer keeps the register suffix and the prefix-stripped body
    it was given, so the screen can show what was understood. Only the
    identity is shared.
    """
    for spelling in case.written:
        assert validate_tax_id(case.country, spelling).format_valid, spelling


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c.country}-{c.key}") for c in _ONE_NUMBER])
def test_the_digit_run_is_shared_by_every_spelling(case: OneNumber) -> None:
    """The coarse key the repository computes in SQL never splits one number."""
    assert {tax_id_digit_run(spelling) for spelling in case.written} == {tax_id_digit_run(case.key)}


def test_a_different_number_keeps_a_different_key() -> None:
    assert canonical_tax_id("CH", "CHE-123.456.789 MWST") != canonical_tax_id("CH", "CHE-123.456.788 MWST")
    assert canonical_tax_id("DE", "DE123456789") != canonical_tax_id("DE", "DE123456780")


def test_the_key_is_an_identity_within_a_country_and_the_register_scopes_by_country() -> None:
    """A German VAT body and a US EIN can be the same nine digits.

    That is not a collision the key has to resolve: the register compares
    keys within one country, which the register tests below pin.
    """
    assert canonical_tax_id("DE", "DE 123 456 789") == canonical_tax_id("US", "12-3456789")


def test_refused_input_still_gets_a_deterministic_key() -> None:
    """Two rows misspelt the same way are still one firm, not "matches nothing"."""
    assert not validate_tax_id("CH", "CHE-123 VAT").format_valid
    assert canonical_tax_id("CH", "CHE-123 VAT") == canonical_tax_id("CH", "che 123 vat")
    assert canonical_tax_id("CH", "CHE-123 VAT")


def test_nothing_but_separators_is_an_empty_key() -> None:
    assert canonical_tax_id("DE", "-- . /") == ""
    assert canonical_tax_id(None, None) == ""


def test_with_no_country_nothing_is_taken_for_a_prefix() -> None:
    """Every string starts with the empty string; that used to cut two characters off."""
    assert canonical_tax_id("", "AB-123") == "AB123"
    assert validate_tax_id("", "AB-123").tax_id_normalised == "AB123"


# ── The register ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    from tests._pg import transactional_session

    async with transactional_session() as s:
        yield s


async def _register(session: AsyncSession, *, country: str, tax_id: str, name: str | None = None) -> Subcontractor:
    payload = SubcontractorCreate(
        legal_name=name or f"Firm {uuid.uuid4().hex[:6]}",
        tax_id=tax_id,
        country=country,
    )
    return await SubcontractorService(session).create_subcontractor(payload)


async def _refused(session: AsyncSession, *, country: str, tax_id: str) -> None:
    with pytest.raises(HTTPException) as refusal:
        await _register(session, country=country, tax_id=tax_id)
    assert refusal.value.status_code == 409, refusal.value.detail


@pytest.mark.asyncio
async def test_the_swiss_number_entered_in_three_languages_is_one_firm(session: AsyncSession) -> None:
    first = await _register(session, country="CH", tax_id="CHE-123.456.789 MWST", name="Bauwerk AG")

    await _refused(session, country="CH", tax_id="CHE-123.456.789 TVA")
    await _refused(session, country="CH", tax_id="CHE-123.456.789 IVA")
    await _refused(session, country="CH", tax_id="che123456789")
    await _refused(session, country="CH", tax_id="123456789")

    # What was typed is what is stored. The key is compared, never written.
    assert first.tax_id == "CHE-123.456.789 MWST"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c.country}-{c.key}") for c in _ONE_NUMBER])
async def test_a_second_spelling_of_a_held_number_is_refused(session: AsyncSession, case: OneNumber) -> None:
    first = await _register(session, country=case.country, tax_id=case.written[0])
    assert first.tax_id == case.written[0]

    for spelling in case.written[1:]:
        await _refused(session, country=case.country, tax_id=spelling)


@pytest.mark.asyncio
async def test_a_different_number_in_the_same_country_is_a_second_firm(session: AsyncSession) -> None:
    await _register(session, country="CH", tax_id="CHE-123.456.789 MWST")
    other = await _register(session, country="CH", tax_id="CHE-123.456.788 MWST")

    assert other.tax_id == "CHE-123.456.788 MWST"


@pytest.mark.asyncio
async def test_the_same_digits_in_two_countries_are_two_firms(session: AsyncSession) -> None:
    await _register(session, country="DE", tax_id="DE 123 456 789")
    other = await _register(session, country="US", tax_id="12-3456789")

    assert other.country == "US"


@pytest.mark.asyncio
async def test_a_patch_cannot_retype_another_firms_number(session: AsyncSession) -> None:
    await _register(session, country="DE", tax_id="DE 123 456 789", name="Erste GmbH")
    second = await _register(session, country="DE", tax_id="DE 987 654 321", name="Zweite GmbH")

    with pytest.raises(HTTPException) as refusal:
        await SubcontractorService(session).update_subcontractor(
            second.id, SubcontractorUpdate(tax_id="de-123.456.789")
        )
    assert refusal.value.status_code == 409

    kept = await SubcontractorService(session).get_subcontractor(second.id)
    assert kept.tax_id == "DE 987 654 321"


@pytest.mark.asyncio
async def test_a_firm_may_respell_its_own_number(session: AsyncSession) -> None:
    firm = await _register(session, country="DE", tax_id="DE 123 456 789")

    updated = await SubcontractorService(session).update_subcontractor(
        firm.id, SubcontractorUpdate(tax_id="de-123.456.789")
    )

    assert updated.tax_id == "de-123.456.789"


@pytest.mark.asyncio
async def test_a_deactivated_firm_no_longer_holds_the_number(session: AsyncSession) -> None:
    firm = await _register(session, country="GB", tax_id="GB 123 4567 89")
    await SubcontractorService(session).update_subcontractor(firm.id, SubcontractorUpdate(is_active=False))

    again = await _register(session, country="GB", tax_id="123456789")

    assert again.id != firm.id
