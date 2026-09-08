# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project's country has to be settled before its compliance pack is resolved.

``ProjectService.create_project`` did two things in the wrong order. It
resolved the compliance rule pack from ``data.country_code``, and only
afterwards - once the project object already existed - filled that same
``country_code`` in from the active country pack. The create form never sends
a country (it posts ``region`` and leaves ``country_code`` unset), so a project
created that way resolved its pack against ``None``, landed on ``universal``,
and was then stamped with the pack's country. The stored row said Hungary and
enforced nothing Hungarian, and the settings page renders the universal pack
exactly like a national one, so nothing anywhere said so.

This file pins the order and the three cases that order has to get right:

* the create-form path - no country, an active country pack - inherits the
  pack's country *and* the pack's compliance packs;
* an explicitly named country is never overridden by the active pack, and it
  is the country that decides the compliance packs;
* a country that registers no compliance pack still lands on ``universal``,
  which is the honest answer, but says in the record that it got there because
  the country claimed no pack rather than because nobody named a country.

That last one is why ``compliance_pack_source`` exists. Nine shipped countries
(IT, NL, PL, KR, AE, ZA, SA, AU, NZ) deliberately have no national rule set
registered, so ``universal`` is correct for them and must not read as an
anomaly. What was missing was not an alarm but a record of which input decided: the
country, the region label, or nothing at all. Where the country itself came
from stays the separate fact it already was, ``country_from_pack``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.partner_pack import discovery as pack_discovery
from app.core.partner_pack.manifest import PartnerPackManifest
from app.modules.projects import service as project_service_module
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import ProjectService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _clear_reservation_set() -> Any:
    """Isolate the process-global project-code reservation set per test."""
    project_service_module._PROJECT_CODE_RESERVED.clear()
    yield
    project_service_module._PROJECT_CODE_RESERVED.clear()


@pytest_asyncio.fixture
async def owner_id(session: AsyncSession) -> uuid.UUID:
    """Insert a single owner User row and return its id."""
    from app.modules.users.models import User

    user = User(
        email=f"owner-{uuid.uuid4().hex}@test.local",
        hashed_password="x",
        full_name="Owner",
    )
    session.add(user)
    await session.flush()
    return user.id


def _service(session: AsyncSession) -> ProjectService:
    return ProjectService(session, Settings(_env_file=None))


def _country_pack(country: str | None) -> PartnerPackManifest:
    """A minimal manifest declaring (or not declaring) a single market."""
    metadata: dict[str, Any] = {} if country is None else {"country": country}
    return PartnerPackManifest(  # type: ignore[call-arg]
        slug="test-country-pack",
        partner_name="Test partner",
        metadata=metadata,
    )


def _activate(monkeypatch: pytest.MonkeyPatch, pack: PartnerPackManifest | None) -> None:
    """Make ``pack`` the active pack for the duration of one test.

    ``create_project`` imports ``get_active_pack`` lazily, inside the function
    body, so it resolves the attribute from the discovery module at call time
    and this reaches it without touching the pack machinery itself.
    """
    monkeypatch.setattr(pack_discovery, "get_active_pack", lambda: pack)


def _wizard_payload(**overrides: Any) -> ProjectCreate:
    """What the create form posts: a name, an empty region, no country.

    ``frontend/src/features/projects/CreateProjectPage.tsx`` seeds ``region``
    with the empty string and never assigns ``country_code`` at all, so this is
    the real shape of a create from the UI, not a reduced one.
    """
    fields: dict[str, Any] = {"name": f"Wizard project {uuid.uuid4().hex[:8]}", "region": ""}
    fields.update(overrides)
    return ProjectCreate(**fields)


@pytest.mark.asyncio
async def test_the_create_form_path_gets_the_active_packs_compliance_packs(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect itself: country HU on the row, universal in the packs.

    On the unmodified service the ``country_code`` assertion passes and the
    ``compliance_rule_packs`` one fails with ``['universal'] != ['hu_compliance']``,
    because the pack was resolved from a country that was still unset and the
    country was filled in a few lines later.
    """
    _activate(monkeypatch, _country_pack("HU"))
    project = await _service(session).create_project(_wizard_payload(), owner_id)
    await session.flush()

    assert project.country_code == "HU"
    assert project.compliance_rule_packs == ["hu_compliance"], (
        f"a project the product itself decided is Hungarian enforces "
        f"{project.compliance_rule_packs}, which is the cross-market baseline. The settings page "
        f"renders that identically to a national pack, so nothing tells the owner."
    )
    # Two separate facts, deliberately two separate keys: the country decided
    # the pack, and the country itself came from the active pack rather than
    # from anything the caller typed.
    assert project.metadata_.get("compliance_pack_source") == "country"
    assert project.metadata_.get("country_from_pack") == "HU"


@pytest.mark.asyncio
async def test_an_explicitly_named_country_decides_and_the_pack_does_not_override_it(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller who names a country keeps it, and it is what picks the pack.

    The active pack is Hungarian and the caller said France. Both halves matter:
    the column must stay FR, and the compliance packs must be the French ones
    rather than the Hungarian pack's or the universal fallback.
    """
    _activate(monkeypatch, _country_pack("HU"))
    project = await _service(session).create_project(_wizard_payload(country_code="FR"), owner_id)
    await session.flush()

    assert project.country_code == "FR"
    assert project.compliance_rule_packs == ["fr_compliance"]
    assert "country_from_pack" not in project.metadata_
    assert project.metadata_.get("compliance_pack_source") == "country"


@pytest.mark.asyncio
async def test_a_country_with_no_pack_lands_on_universal_and_says_why(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Italy registers no national rule set, so universal is the right answer.

    Right, and until now indistinguishable from the wrong one. The record has
    to separate "this country claims no pack" from "nobody named a country",
    because those two produce the same pack id and mean opposite things.
    """
    _activate(monkeypatch, None)
    project = await _service(session).create_project(_wizard_payload(country_code="IT"), owner_id)
    await session.flush()

    assert project.country_code == "IT"
    assert project.compliance_rule_packs == ["universal"]
    assert project.metadata_.get("compliance_pack_source") == "country_without_pack", (
        "an Italian project falls into the universal pack with nothing on the row saying it was "
        "the country that claimed no pack. That reads exactly like a project nobody gave a "
        "country to."
    )


@pytest.mark.asyncio
async def test_no_country_and_no_pack_leaves_the_country_unset(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing named a country, so the column stays NULL rather than guessing.

    ``country_code`` became nullable in ``v3319`` precisely so this state can be
    recorded instead of being spelled 'DE'. The universal pack here is the
    default arrived at by default, and says so.
    """
    _activate(monkeypatch, None)
    project = await _service(session).create_project(_wizard_payload(), owner_id)
    await session.flush()

    assert project.country_code is None
    assert project.compliance_rule_packs == ["universal"]
    assert project.metadata_.get("compliance_pack_source") == "default"
    assert "country_from_pack" not in project.metadata_


@pytest.mark.asyncio
async def test_an_explicit_pack_choice_survives_an_active_country_pack(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settling the country earlier must not start overriding a real choice.

    A caller that named its own non-default packs keeps them, and the country
    is still inherited from the pack - the two decisions are independent.
    """
    _activate(monkeypatch, _country_pack("HU"))
    project = await _service(session).create_project(
        _wizard_payload(compliance_rule_packs=["uk_compliance"]),
        owner_id,
    )
    await session.flush()

    assert project.compliance_rule_packs == ["uk_compliance"]
    assert project.country_code == "HU"
    assert project.metadata_.get("compliance_pack_source") == "explicit"


@pytest.mark.asyncio
async def test_the_packs_country_outranks_a_free_text_region(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deliberate change of answer, recorded here so it is not a surprise.

    Before this fix a create with no country and the region "Germany" resolved
    the German pack, because the region label was the only thing left to read.
    Now the Hungarian pack's country is settled first and an ISO country
    outranks free text, which is ``resolve_pack``'s documented contract. The
    project is Hungarian, so it enforces the Hungarian pack.
    """
    _activate(monkeypatch, _country_pack("HU"))
    project = await _service(session).create_project(_wizard_payload(region="Germany"), owner_id)
    await session.flush()

    assert project.country_code == "HU"
    assert project.compliance_rule_packs == ["hu_compliance"]


@pytest.mark.asyncio
async def test_a_region_alone_still_decides_when_no_country_is_known(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The region label keeps working as the last resort it always was."""
    _activate(monkeypatch, None)
    project = await _service(session).create_project(_wizard_payload(region="Hungary"), owner_id)
    await session.flush()

    assert project.country_code is None
    assert project.compliance_rule_packs == ["hu_compliance"]
    assert project.metadata_.get("compliance_pack_source") == "region"


@pytest.mark.asyncio
async def test_a_region_with_no_pack_is_not_reported_as_nothing_named(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same conflation, one axis over, which is the easy one to leave in.

    A project whose region reads "Italy" reaches the universal pack for exactly
    the reason an Italian ``country_code`` does - no Italian rule set is
    registered - and calling that ``default`` would say nobody named a
    jurisdiction when somebody did. Most of the countries that have no national
    rule set ship a demo and a region label, so this is the common way in, not
    a corner.
    """
    _activate(monkeypatch, None)
    project = await _service(session).create_project(_wizard_payload(region="Italy"), owner_id)
    await session.flush()

    assert project.compliance_rule_packs == ["universal"]
    assert project.metadata_.get("compliance_pack_source") == "region_without_pack"
