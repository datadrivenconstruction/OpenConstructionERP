# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project is fitted out by its own country's pack, not always the active one.

One pack is active on an installation, and a contractor works in more than one
country. Project creation copied the active pack's rule sets and methodology
onto every project. Measured on the unmodified service with the Turkish pack
active, a project created with ``country_code="HU"`` stored
``["boq_quality", "birimfiyat"]`` and the ``turkey`` methodology; the BOQ router
then added ``hungary`` from the country row, so a bill with a correct Hungarian
item code on every line failed ``birimfiyat.code_required`` on every line, and a
spreadsheet import could not tell which code its column held. The same held for
a Spanish project, and the other way round for a Turkish project under the
Hungarian pack.

What is pinned here:

* a project in another country gets that country's rule sets and methodology,
  read from that country's manifest, and none of the active pack's;
* a project in the active pack's own country stores exactly what it did;
* a country no pack is written for gets what an installation with no pack
  gives it, and still carries the active pack's tag, because the tag is about
  the installation and a pack hides every untagged project;
* what the caller asks for is kept in every case;
* which pack speaks for a country is one answer whatever order the manifests
  arrive in, and never a derived or industry pack.

The first test below is the control: it runs the old rule (the active pack's
sets on a Hungarian project) through the router and the engine and expects the
three errors, so the tests after it are known to measure the thing that broke.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.partner_pack import discovery as pack_discovery
from app.core.partner_pack.apply import (
    PACK_RULE_SETS_METADATA_KEY,
    resolve_declared_rule_sets,
    split_inherited_rule_sets,
)
from app.core.partner_pack.manifest import PartnerPackManifest
from app.core.validation.engine import validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.router import _build_rule_sets, _national_code_key, _pack_added_rule_sets
from app.modules.projects import service as project_service_module
from app.modules.projects.country_configuration import (
    CONFIGURATION_PACK_METADATA_KEY,
    CONFIGURATION_SOURCE_METADATA_KEY,
    SOURCE_ACTIVE_PACK,
    SOURCE_COUNTRY_PACK,
    SOURCE_COUNTRY_WITHOUT_PACK,
    configuration_pack,
    country_pack_for,
    validated_country,
)
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.projects.service import ProjectService
from tests._pg import transactional_session

#: The two packs a contractor based in Türkiye may have active: the country
#: pack and the industry pack derived from it. Both name the same market.
TURKISH_PACKS = ("turkey-tr", "turkey-tr-mep")


def _shipped() -> list[PartnerPackManifest]:
    return list(pack_discovery.discover_packs())


def _pack(slug: str) -> PartnerPackManifest:
    manifest = pack_discovery.get_pack_by_slug(slug)
    assert manifest is not None, f"pack {slug} was not discovered, so nothing below would measure it"
    return manifest


def _bill(code_key: str, codes: list[str]) -> dict[str, Any]:
    """Priced leaf lines, each carrying one national code under ``code_key``."""
    return {
        "positions": [
            {
                "id": f"p-{i}",
                "parent_id": None,
                "ordinal": f"01.{i:02d}",
                "description": f"Coded line {i}",
                "unit": "m2",
                "quantity": 10.0,
                "unit_rate": 50.0,
                "total": 500.0,
                "classification": {code_key: code},
                "type": "position",
            }
            for i, code in enumerate(codes, start=1)
        ]
    }


HUNGARIAN_BILL = _bill("tetelrend", ["MA-04-12-01", "MA-04-12-02", "MA-04-12-03"])
SPANISH_BILL = _bill("bc3_code", ["E04CM040", "E04CM050", "E04CM060"])
TURKISH_BILL = _bill("birimfiyat", ["15.150.1003", "15.150.1004", "15.150.1005"])


async def _errors(rule_sets: list[str], bill: dict[str, Any]) -> dict[str, int]:
    """Failed error-level results per rule when ``bill`` is validated with ``rule_sets``."""
    register_builtin_rules()
    runnable = [name for name in rule_sets if validation_engine.registry.has_rules(name)]
    report = await validation_engine.validate(
        data=bill, rule_sets=runnable, target_type="boq", metadata={"locale": "en"}
    )
    errors: dict[str, int] = {}
    for result in report.results:
        if not result.passed and result.severity.value == "error":
            errors[result.rule_id] = errors.get(result.rule_id, 0) + 1
    return errors


def _effective_rule_sets(project: Any) -> list[str]:
    """The rule sets the BOQ router validates the project's bills with."""
    return _build_rule_sets(
        project_rule_sets=project.validation_rule_sets or ["boq_quality"],
        classification_standard=project.classification_standard or "",
        region=project.region or "",
        country_code=project.country_code,
        pack_rule_sets=_pack_added_rule_sets(project),
    )


# ── Control ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_old_rule_fails_every_line_of_a_correctly_coded_hungarian_bill() -> None:
    """The defect, reproduced without the service: the active pack's sets on a Hungarian project."""
    register_builtin_rules()
    stored, pack_added = split_inherited_rule_sets(["boq_quality"], _pack("turkey-tr"))
    assert stored == ["boq_quality", "birimfiyat"]
    effective = _build_rule_sets(stored, "", "", "HU", pack_rule_sets=pack_added)
    assert effective == ["boq_quality", "birimfiyat", "hungary"]
    assert await _errors(effective, HUNGARIAN_BILL) == {"birimfiyat.code_required": 3}
    assert _national_code_key(effective, "") is None, "two code sets used to leave an import with no key to file under"


# ── Which country a project is validated as ──────────────────────────────────


@pytest.mark.parametrize(
    ("region", "column", "expected"),
    [
        ("", "HU", "HU"),
        ("", "hu", "HU"),
        ("HU", "TR", "HU"),
        ("ES_MADRID", "TR", "ES"),
        # A group label names no single country, so the column decides.
        ("DACH", "AT", "AT"),
        ("GCC", "SA", "SA"),
        # Free text the registry cannot read gives way to the column.
        ("Central Europe", "HU", "HU"),
        ("", None, None),
        ("", "", None),
        # A country the classification registry has no row for is still a country.
        ("", "XK", "XK"),
    ],
)
def test_a_region_that_names_a_country_wins_over_the_column(
    region: str, column: str | None, expected: str | None
) -> None:
    assert validated_country(region, column) == expected


# ── Which pack speaks for a country ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("country", "slug"),
    [
        ("HU", "hungary-hu"),
        ("ES", "spain-es"),
        # The derived industry pack shares the market and is never the answer.
        ("TR", "turkey-tr"),
        # Three United States packs: the one that names no state.
        ("US", "us-costdata"),
        # Two German packs: the one with no regional programme.
        ("DE", "germany-de"),
        # Two Canadian packs that narrow nothing: the slug decides.
        ("CA", "batimatech-ca"),
        ("AU", "aus"),
    ],
)
def test_the_pack_for_a_country_is_one_answer_in_any_order(country: str, slug: str) -> None:
    shipped = _shipped()
    assert country_pack_for(country, shipped).slug == slug  # type: ignore[union-attr]
    assert country_pack_for(country, list(reversed(shipped))).slug == slug  # type: ignore[union-attr]
    assert country_pack_for(country.lower(), shipped).slug == slug  # type: ignore[union-attr]


@pytest.mark.parametrize("country", ["KE", "XK", "", None])
def test_a_country_no_pack_is_written_for_has_no_pack(country: str | None) -> None:
    assert country_pack_for(country, _shipped()) is None


def test_no_industry_or_derived_pack_ever_speaks_for_a_country() -> None:
    shipped = _shipped()
    excluded = {m.slug for m in shipped if m.type != "country" or (m.metadata or {}).get("derived_from")}
    assert "turkey-tr-mep" in excluded, "the derived pack this rule exists for is no longer in the population"
    markets = {m.market_country_code for m in shipped if m.market_country_code}
    assert len(markets) > 30, f"only {len(markets)} markets discovered, the walk below would prove little"
    chosen = {country_pack_for(country, shipped).slug for country in markets}  # type: ignore[union-attr]
    assert not chosen & excluded


def test_the_packs_of_one_country_agree_on_what_a_project_inherits() -> None:
    """The tie-break picks a manifest, and it must not pick a configuration.

    Several countries have more than one country pack. A project elsewhere in
    the country inherits the rule sets and the methodology of whichever is
    chosen, so the candidates have to agree on both; a new pack that disagrees
    turns the slug order into a decision nobody made.
    """
    register_builtin_rules()
    by_country: dict[str, list[PartnerPackManifest]] = {}
    for manifest in _shipped():
        if manifest.type == "country" and manifest.market_country_code:
            if not (manifest.metadata or {}).get("derived_from"):
                by_country.setdefault(manifest.market_country_code, []).append(manifest)
    shared = {country: packs for country, packs in by_country.items() if len(packs) > 1}
    assert {"US", "DE", "CA"} <= set(shared), f"the multi-pack countries moved: {sorted(shared)}"
    for country, packs in shared.items():
        answers = {(tuple(sorted(resolve_declared_rule_sets(m))), m.default_methodology) for m in packs}
        assert len(answers) == 1, f"{country}: {[m.slug for m in packs]} disagree: {sorted(answers)}"


# ── The decision ─────────────────────────────────────────────────────────────


def _never() -> list[PartnerPackManifest]:
    raise AssertionError("discovery was asked for a project that is not in another country")


def test_no_active_pack_decides_nothing() -> None:
    assert configuration_pack(region="", country_code="HU", active_pack=None, shipped=_never) == (
        None,
        SOURCE_ACTIVE_PACK,
    )


@pytest.mark.parametrize("slug", TURKISH_PACKS)
@pytest.mark.parametrize(("region", "column"), [("", "TR"), ("", "tr"), ("TR_ISTANBUL", "TR"), ("Marmara", "TR")])
def test_a_project_in_the_packs_own_country_keeps_the_active_pack(slug: str, region: str, column: str) -> None:
    active = _pack(slug)
    assert configuration_pack(region=region, country_code=column, active_pack=active, shipped=_never) == (
        active,
        SOURCE_ACTIVE_PACK,
    )


@pytest.mark.parametrize("slug", TURKISH_PACKS)
@pytest.mark.parametrize(
    ("region", "column", "expected"),
    [("", "HU", "hungary-hu"), ("", "ES", "spain-es"), ("HU", "TR", "hungary-hu"), ("ES_MADRID", "TR", "spain-es")],
)
def test_a_project_in_another_country_gets_that_countrys_pack(
    slug: str, region: str, column: str, expected: str
) -> None:
    pack, source = configuration_pack(region=region, country_code=column, active_pack=_pack(slug), shipped=_shipped)
    assert (pack.slug if pack else None, source) == (expected, SOURCE_COUNTRY_PACK)


def test_a_turkish_project_under_another_countrys_pack_gets_the_plain_turkish_pack() -> None:
    pack, source = configuration_pack(region="", country_code="TR", active_pack=_pack("hungary-hu"), shipped=_shipped)
    assert (pack.slug if pack else None, source) == ("turkey-tr", SOURCE_COUNTRY_PACK)


def test_a_country_without_a_pack_gets_no_pack_at_all() -> None:
    assert configuration_pack(region="", country_code="KE", active_pack=_pack("turkey-tr"), shipped=_shipped) == (
        None,
        SOURCE_COUNTRY_WITHOUT_PACK,
    )


@pytest.mark.parametrize("slug", ["doker-formwork", "retail-grocery-dach"])
def test_a_pack_that_names_no_market_applies_to_every_project(slug: str) -> None:
    """A sector pack has no country for a project to differ from, so nothing changes under one."""
    active = _pack(slug)
    assert active.market_country_code is None
    assert configuration_pack(region="", country_code="HU", active_pack=active, shipped=_never) == (
        active,
        SOURCE_ACTIVE_PACK,
    )


# ── Through project creation, on PostgreSQL ──────────────────────────────────


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

    user = User(email=f"owner-{uuid.uuid4().hex}@test.local", hashed_password="x", full_name="Owner")
    session.add(user)
    await session.flush()
    return user.id


def _service(session: AsyncSession) -> ProjectService:
    return ProjectService(session, Settings(_env_file=None))


async def _create(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    active_slug: str | None,
    **fields: Any,
) -> Any:
    """Create one project with ``active_slug`` as the installation's pack."""
    register_builtin_rules()
    active = _pack(active_slug) if active_slug else None
    monkeypatch.setattr(pack_discovery, "get_active_pack", lambda: active)
    payload: dict[str, Any] = {"name": f"Project {uuid.uuid4().hex[:8]}", "region": "", **fields}
    project = await _service(session).create_project(ProjectCreate(**payload), owner_id)
    await session.flush()
    return project


@pytest.mark.asyncio
@pytest.mark.parametrize("active_slug", TURKISH_PACKS)
@pytest.mark.parametrize(
    ("country", "currency", "locale", "rule_set", "methodology", "own_pack", "code_key", "bill"),
    [
        ("HU", "HUF", "hu", "hungary", "hungary", "hungary-hu", "tetelrend", HUNGARIAN_BILL),
        ("ES", "EUR", "es", "bc3", "spain", "spain-es", "bc3_code", SPANISH_BILL),
    ],
)
async def test_a_foreign_project_under_the_turkish_pack_gets_its_own_countrys_configuration(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    active_slug: str,
    country: str,
    currency: str,
    locale: str,
    rule_set: str,
    methodology: str,
    own_pack: str,
    code_key: str,
    bill: dict[str, Any],
) -> None:
    project = await _create(
        session, owner_id, monkeypatch, active_slug, country_code=country, currency=currency, locale=locale
    )
    meta = project.metadata_

    assert project.country_code == country
    assert (project.currency, project.locale) == (currency, locale), "currency and locale are the caller's"
    assert project.validation_rule_sets == ["boq_quality", rule_set]
    assert meta[PACK_RULE_SETS_METADATA_KEY] == [rule_set]
    assert meta["methodology_slug"] == methodology
    assert meta[CONFIGURATION_SOURCE_METADATA_KEY] == SOURCE_COUNTRY_PACK
    assert meta[CONFIGURATION_PACK_METADATA_KEY] == own_pack
    # The tag is about the installation: without it the pack's scoped project
    # list would hide the project.
    assert meta["partner_pack"] == active_slug
    assert "country_from_pack" not in meta

    effective = _effective_rule_sets(project)
    assert effective == ["boq_quality", rule_set]
    assert await _errors(effective, bill) == {}
    assert _national_code_key(effective, "") == code_key


@pytest.mark.asyncio
@pytest.mark.parametrize("active_slug", TURKISH_PACKS)
@pytest.mark.parametrize("fields", [{"country_code": "TR"}, {}, {"region": "TR_ISTANBUL"}])
async def test_a_turkish_project_under_the_turkish_pack_is_unchanged(
    session: AsyncSession,
    owner_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    active_slug: str,
    fields: dict[str, Any],
) -> None:
    project = await _create(session, owner_id, monkeypatch, active_slug, **fields)
    meta = project.metadata_

    assert project.country_code == "TR"
    assert project.validation_rule_sets == ["boq_quality", "birimfiyat"]
    assert meta[PACK_RULE_SETS_METADATA_KEY] == ["birimfiyat"]
    assert meta["methodology_slug"] == "turkey"
    assert meta["partner_pack"] == active_slug
    assert CONFIGURATION_SOURCE_METADATA_KEY not in meta
    assert CONFIGURATION_PACK_METADATA_KEY not in meta
    assert ("country_from_pack" in meta) == ("country_code" not in fields)

    effective = _effective_rule_sets(project)
    assert effective == ["boq_quality", "birimfiyat"]
    assert await _errors(effective, TURKISH_BILL) == {}
    assert await _errors(effective, HUNGARIAN_BILL) == {"birimfiyat.code_required": 3}, (
        "the Turkish code rule no longer fires on a Turkish project, so the tests above prove nothing by passing"
    )


@pytest.mark.asyncio
async def test_a_turkish_project_under_the_hungarian_pack_gets_turkish_configuration(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The symmetric case, and the plain country pack, never the derived one."""
    project = await _create(session, owner_id, monkeypatch, "hungary-hu", country_code="TR")
    meta = project.metadata_

    assert project.validation_rule_sets == ["boq_quality", "birimfiyat"]
    assert meta[PACK_RULE_SETS_METADATA_KEY] == ["birimfiyat"]
    assert meta["methodology_slug"] == "turkey"
    assert meta[CONFIGURATION_PACK_METADATA_KEY] == "turkey-tr"
    assert meta["partner_pack"] == "hungary-hu"
    assert await _errors(_effective_rule_sets(project), TURKISH_BILL) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("country", ["HU", "ES", "TR", "KE", None])
async def test_an_installation_with_no_pack_is_unchanged(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, country: str | None
) -> None:
    project = await _create(session, owner_id, monkeypatch, None, country_code=country)
    meta = project.metadata_ or {}

    assert project.country_code == country
    assert project.validation_rule_sets == ["boq_quality"]
    for key in (
        PACK_RULE_SETS_METADATA_KEY,
        "methodology_slug",
        "partner_pack",
        CONFIGURATION_SOURCE_METADATA_KEY,
        CONFIGURATION_PACK_METADATA_KEY,
    ):
        assert key not in meta


@pytest.mark.asyncio
@pytest.mark.parametrize("active_slug", TURKISH_PACKS)
async def test_a_country_without_a_pack_is_left_as_an_installation_with_no_pack_leaves_it(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, active_slug: str
) -> None:
    under_pack = await _create(session, owner_id, monkeypatch, active_slug, country_code="KE")
    bare = await _create(session, owner_id, monkeypatch, None, country_code="KE")
    meta = under_pack.metadata_

    assert under_pack.validation_rule_sets == bare.validation_rule_sets == ["boq_quality"]
    assert PACK_RULE_SETS_METADATA_KEY not in meta
    assert "methodology_slug" not in meta, "no methodology of its own means the international default"
    assert meta[CONFIGURATION_SOURCE_METADATA_KEY] == SOURCE_COUNTRY_WITHOUT_PACK
    assert CONFIGURATION_PACK_METADATA_KEY not in meta
    assert meta["partner_pack"] == active_slug
    assert _effective_rule_sets(under_pack) == _effective_rule_sets(bare)
    assert "birimfiyat" not in _effective_rule_sets(under_pack)


@pytest.mark.asyncio
async def test_what_the_caller_asks_for_is_kept(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit rule sets and an explicit standard survive, including the active pack's own set."""
    project = await _create(
        session,
        owner_id,
        monkeypatch,
        "turkey-tr",
        country_code="HU",
        classification_standard="tetelrend",
        validation_rule_sets=["boq_quality", "din276", "birimfiyat"],
    )
    meta = project.metadata_

    assert project.classification_standard == "tetelrend"
    assert project.validation_rule_sets == ["boq_quality", "din276", "birimfiyat", "hungary"]
    # A set the creator asked for is never recorded as the pack's, so the
    # router never drops it: a dual-coded bill asks for a second code on purpose.
    assert meta[PACK_RULE_SETS_METADATA_KEY] == ["hungary"]
    assert "birimfiyat" in _effective_rule_sets(project)


@pytest.mark.asyncio
async def test_creation_names_no_classification_standard_for_any_country(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The standard stays the caller's, as it is for a project in the pack's own country.

    No pack has ever written a classification standard onto a project: a blank
    one is read from the project's country wherever it matters. Writing
    ``tetelrend`` on the foreign project alone would make it the only kind of
    project whose standard the product chose.
    """
    foreign = await _create(session, owner_id, monkeypatch, "turkey-tr", country_code="HU")
    own = await _create(session, owner_id, monkeypatch, "turkey-tr", country_code="TR")
    assert (foreign.classification_standard, own.classification_standard) == ("", "")


@pytest.mark.asyncio
async def test_a_region_that_names_another_country_decides_the_configuration(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The column is still filled from the pack; the rule sets follow what the router validates."""
    project = await _create(session, owner_id, monkeypatch, "turkey-tr", region="HU")

    assert project.country_code == "TR", "the pack's country outranks a region in the column, as before"
    assert project.validation_rule_sets == ["boq_quality", "hungary"]
    assert project.metadata_["methodology_slug"] == "hungary"
    effective = _effective_rule_sets(project)
    assert effective == ["boq_quality", "hungary"]
    assert await _errors(effective, HUNGARIAN_BILL) == {}


@pytest.mark.asyncio
async def test_a_country_read_from_the_address_is_not_overwritten_by_the_pack(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A site address in Hungary under the Turkish pack used to be stored as Turkey."""
    project = await _create(session, owner_id, monkeypatch, "turkey-tr", address={"country": "Hungary"})
    meta = project.metadata_

    assert project.country_code == "HU"
    assert meta["country_from_address"] == "HU"
    assert "country_from_pack" not in meta
    assert project.compliance_rule_packs == ["hu_compliance"]
    assert project.validation_rule_sets == ["boq_quality", "hungary"]


@pytest.mark.asyncio
async def test_an_address_the_resolver_cannot_read_still_inherits_the_packs_country(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = await _create(session, owner_id, monkeypatch, "turkey-tr", address={"country": "Nowhere in particular"})
    assert project.country_code == "TR"
    assert project.metadata_["country_from_pack"] == "TR"


@pytest.mark.asyncio
async def test_a_project_created_before_the_fix_is_repaired_through_the_update(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing rows are not rewritten; an administrator patches the three fields.

    The row is built the way the old service left it, by asking for the Turkish
    set explicitly and writing the old record and methodology beside it.
    """
    project = await _create(
        session, owner_id, monkeypatch, None, country_code="HU", validation_rule_sets=["boq_quality", "birimfiyat"]
    )
    service = _service(session)
    project = await service.update_project(
        project.id,
        ProjectUpdate(metadata={PACK_RULE_SETS_METADATA_KEY: ["birimfiyat"], "methodology_slug": "turkey"}),
    )
    assert await _errors(_effective_rule_sets(project), HUNGARIAN_BILL) == {"birimfiyat.code_required": 3}

    project = await service.update_project(
        project.id,
        ProjectUpdate(
            validation_rule_sets=["boq_quality", "hungary"],
            metadata={PACK_RULE_SETS_METADATA_KEY: ["hungary"], "methodology_slug": "hungary"},
        ),
    )
    await session.flush()

    assert project.validation_rule_sets == ["boq_quality", "hungary"]
    assert project.metadata_["methodology_slug"] == "hungary"
    effective = _effective_rule_sets(project)
    assert effective == ["boq_quality", "hungary"]
    assert await _errors(effective, HUNGARIAN_BILL) == {}
