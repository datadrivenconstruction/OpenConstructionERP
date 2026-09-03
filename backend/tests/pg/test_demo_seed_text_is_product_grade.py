# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The demo seeders must write text a customer can read, and must fit the schema.

Two things are gated here, both against a real database rather than by
inspecting the format strings:

1. **The seeders still run.** Several display strings were rewritten to drop
   the word "Demo". A rewritten string is longer than the one it replaced, and
   these columns are ``String(n)``, not ``Text``. Reconstructing the generated
   values by hand to check their length is exactly the sort of arithmetic that
   goes wrong quietly - a transform gets skipped, a dict is iterated by key -
   so the seeders are executed and PostgreSQL is left to raise
   ``StringDataRightTruncation`` if anything overflows.

2. **No user-facing text says "demo".** Swept generically across every
   ``String``/``Text`` column of every table the seeders touched, so a leak in
   a column nobody thought to assert on is still caught. Internal markers are
   allowlisted by name below, and the allowlist is deliberately small and
   explicit: a marker code may keep the word, a sentence a user reads may not.

JSON columns are not swept. ``metadata_`` carries ``demo_id`` on purpose - that
is the internal marker the seeders key their idempotency on, and it is not a
display string.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.database import Base
from app.modules.projects.models import Project

pytestmark = pytest.mark.asyncio


# Columns where the token "DEMO" is domain vocabulary rather than a marker.
# An entry here has to justify itself: the value must mean something to a
# construction professional independently of this product's demo estate.
_INTERNAL_MARKER_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        # Package codes carry a four-letter trade abbreviation - ELEC, HVAC,
        # STRC, SCAF, DEMO. Here DEMO is demolition, and "BP-P00-DEMO" is the
        # demolition package. Renaming it would be the fix removing real data.
        ("oe_bid_management_package", "code"),
    }
)


async def _make_projects(session, count: int = 2) -> list[uuid.UUID]:
    """Create the minimum real projects the project-scoped seeders need.

    ``Project.owner_id`` is a real foreign key to ``oe_users_user``, so an
    owner has to exist before a project can.
    """
    from app.modules.users.models import User

    # Reused rather than recreated, so calling this twice mirrors a re-seed of
    # an existing estate instead of failing on the owner's unique email.
    email = "site.lead@reference.example"
    owner = (await session.execute(sa.select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference owner")
        session.add(owner)
        await session.flush()

    ids: list[uuid.UUID] = []
    for n in range(count):
        name = f"Reference project {n + 1}"
        project = (await session.execute(sa.select(Project).where(Project.name == name))).scalars().first()
        if project is None:
            project = Project(name=name, owner_id=owner.id)
            session.add(project)
            await session.flush()
        ids.append(uuid.UUID(str(project.id)))
    return ids


def _seeder_calls(project_ids: list[uuid.UUID]) -> list[tuple[str, object]]:
    """Name every seeder alongside the call that runs it.

    Kept as a list of named calls rather than one long block so a pass can run
    each seeder in isolation and report *every* failure, instead of stopping at
    the first one and hiding the rest.
    """
    from app.modules.bid_management.seed import seed_bid_management_demo
    from app.modules.bim_hub.seed import seed_bim_hub
    from app.modules.contracts.seed import seed_contracts_demo
    from app.modules.crm.seed import seed_crm_demo
    from app.modules.moc.seed import seed_moc
    from app.modules.norm_expansion.seed import seed_norm_expansion
    from app.modules.portal.seed import seed_portal_demo
    from app.modules.price_index.seed import seed_price_index_demo
    from app.modules.property_dev.seed import seed_property_dev_demo
    from app.modules.subcontractors.seed import seed_subcontractors_demo
    from app.modules.supplier_catalogs.seed import seed_supplier_catalogs
    from app.modules.variations.seed import seed_variations_demo

    return [
        ("crm", lambda s: seed_crm_demo(s)),
        ("subcontractors", lambda s: seed_subcontractors_demo(s, project_id=project_ids[0])),
        ("contracts", lambda s: seed_contracts_demo(s, list(project_ids))),
        ("portal", lambda s: seed_portal_demo(s, project_ids)),
        ("moc", lambda s: seed_moc(s, list(project_ids))),
        ("variations", lambda s: seed_variations_demo(s, project_ids)),
        ("bid_management", lambda s: seed_bid_management_demo(s, project_ids)),
        ("norm_expansion", lambda s: seed_norm_expansion(s)),
        ("supplier_catalogs", lambda s: seed_supplier_catalogs(s, project_ids[0])),
        ("bim_hub", lambda s: seed_bim_hub(s, list(project_ids))),
        ("price_index", lambda s: seed_price_index_demo(s)),
        ("property_dev", lambda s: seed_property_dev_demo(s, project_ids)),
    ]


async def _run_all_seeders(session) -> dict[str, object]:
    """Run every seeder whose display strings were rewritten.

    Built from :func:`_seeder_calls` rather than repeating the list, so the
    two cannot drift into disagreeing about which seeders exist.

    Returns each seeder's own report, so a seeder that silently wrote nothing
    is visible rather than passing as "did not raise".
    """
    project_ids = await _make_projects(session)
    reports: dict[str, object] = {}
    for name, call in _seeder_calls(project_ids):
        reports[name] = await call(session)
    await session.flush()
    return reports


def _text_columns() -> list[tuple[str, str]]:
    """Every (table, column) holding character data, minus the allowlist."""
    found: list[tuple[str, str]] = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, sa.String):  # covers String and Text
                continue
            if (table.name, column.name) in _INTERNAL_MARKER_COLUMNS:
                continue
            found.append((table.name, column.name))
    return found


async def test_the_rewritten_seeders_run_against_a_real_schema(pg_session) -> None:
    """Every rewritten display string fits the column it is stored in.

    This is the check that a hand-computed length cannot honestly make. If a
    rewritten name outgrew its ``String(n)``, PostgreSQL raises here.

    The returned-something assertion below is weaker than it looks and is not
    a coverage claim: a seeder that skipped its work still returns a truthy
    counts dict of zeros. Whether the rows actually landed is what
    ``test_the_registers_are_not_one_string_with_a_counter`` reads back.
    """
    reports = await _run_all_seeders(pg_session)

    returned_nothing = [name for name, report in reports.items() if not report]
    assert not returned_nothing, f"seeders returned no report at all: {returned_nothing}"


async def test_no_user_facing_seed_text_says_demo(pg_session) -> None:
    """The word "demo" must not survive in anything a user reads.

    Swept across every character column rather than a chosen few, so a leak in
    a column this test's author never considered still fails.
    """
    await _run_all_seeders(pg_session)

    # Whole word only. A substring match calls "Demolition" a leak, and
    # demolition is a trade - the check would then be demanding the removal of
    # real construction vocabulary. ``\m``/``\M`` are PostgreSQL's word
    # boundaries, so "demo", "demo-reviewer" and "demo seed" match while
    # "Demolition" does not.
    needle = r"\mdemos?\M"

    leaks: list[str] = []
    for table_name, column_name in _text_columns():
        rows = (
            (
                await pg_session.execute(
                    sa.text(
                        f'SELECT DISTINCT "{column_name}" FROM "{table_name}" '  # noqa: S608
                        f'WHERE "{column_name}" ~* :needle LIMIT 5'
                    ),
                    {"needle": needle},
                )
            )
            .scalars()
            .all()
        )
        for value in rows:
            leaks.append(f"{table_name}.{column_name} = {value!r}")

    assert not leaks, "user-facing seed text still contains 'demo':\n" + "\n".join(leaks)


async def test_running_the_seeders_twice_does_not_multiply_the_estate(pg_session) -> None:
    """A second pass must be a no-op, not a second copy.

    Re-seeding is a normal operation - it is how the demo box is refreshed -
    so a seeder that doubles its register on the second run corrupts the estate
    it was meant to restore. Row counts are compared before and after rather
    than trusting each seeder's own report, because a seeder that guards
    correctly and one that inserts blindly can return the same numbers.
    """
    from app.modules.bid_management.models import BidPackage
    from app.modules.crm.models import Account, CrmActivity, Opportunity
    from app.modules.moc.models import MoCEntry
    from app.modules.property_dev.models import Development
    from app.modules.subcontractors.models import Subcontractor

    watched = {
        "crm accounts": Account,
        "crm opportunities": Opportunity,
        "crm activities": CrmActivity,
        "subcontractors": Subcontractor,
        "moc entries": MoCEntry,
        "bid packages": BidPackage,
        "developments": Development,
    }

    async def counts() -> dict[str, int]:
        out: dict[str, int] = {}
        for label, model in watched.items():
            out[label] = (await pg_session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one()
        return out

    project_ids = await _make_projects(pg_session)
    seeders = _seeder_calls(project_ids)

    for name, call in seeders:
        await call(pg_session)
    await pg_session.flush()

    after_first = await counts()
    assert any(after_first.values()), "the first pass seeded nothing, so this proves nothing"

    # Each seeder gets its own savepoint on the second pass. Without it the
    # first integrity error poisons the transaction and every later seeder is
    # reported as broken too - or worse, never runs, and the report names one
    # offender when there are several.
    raised: dict[str, str] = {}
    for name, call in seeders:
        savepoint = await pg_session.begin_nested()
        try:
            await call(pg_session)
            await pg_session.flush()
            await savepoint.commit()
        except Exception as exc:  # noqa: BLE001 - the failure is the finding
            await savepoint.rollback()
            raised[name] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"

    after_second = await counts()
    grew = {
        label: (after_first[label], after_second[label])
        for label in watched
        if after_second[label] != after_first[label]
    }

    assert not raised, f"a second pass raised for these seeders: {raised}"
    assert not grew, f"a second seeding pass changed these registers: {grew}"


async def test_the_leak_predicate_can_still_tell_a_leak_from_a_trade(pg_session) -> None:
    """The sweep above is worthless if its pattern matches nothing.

    A green sweep proves the seed text is clean only if the pattern would have
    gone red on a real leak. Both directions are pinned here: the wordings that
    were actually found in this estate must match, and the demolition
    vocabulary that tripped a naive substring check must not.
    """
    should_match = [
        "demo",
        "Demo",
        "demo-reviewer",
        "Seeded demo bidder",
        "Closed via demo seed",
        "DEV-DEMO-01",
        "Demo Project Alpha",
        "demos",
    ]
    should_not_match = [
        "Demolition Contractors CH-41",
        "Demolition phase 1",
        "Item 1 for Demolition phase 1",
        "demolition",
        "Democratic Republic",
    ]

    needle = r"\mdemos?\M"

    for value in should_match:
        hit = (
            await pg_session.execute(sa.text("SELECT :value ~* :needle"), {"value": value, "needle": needle})
        ).scalar_one()
        assert hit, f"the sweep would not have caught {value!r}"

    for value in should_not_match:
        hit = (
            await pg_session.execute(sa.text("SELECT :value ~* :needle"), {"value": value, "needle": needle})
        ).scalar_one()
        assert not hit, f"the sweep calls {value!r} a leak, but it is construction vocabulary"


async def test_the_registers_are_not_one_string_with_a_counter(pg_session) -> None:
    """Renamed registers must carry more than one distinct wording.

    The point of the rename was readability, not novelty, so this asserts a
    floor rather than uniqueness: a register whose every row differs only by a
    trailing number reads as filler, and that is what this catches.
    """
    from app.modules.crm.models import Account, CrmActivity, Opportunity
    from app.modules.subcontractors.models import Subcontractor

    await _run_all_seeders(pg_session)

    async def distinct_of(model, column) -> int:
        return len(set((await pg_session.execute(select(column).select_from(model))).scalars().all()))

    # Stripping trailing digits collapses "…-001", "…-002" back onto one
    # wording, which is what the count is meant to measure.
    async def distinct_wordings(model, column) -> int:
        values = (await pg_session.execute(select(column).select_from(model))).scalars().all()
        return len({str(v).rstrip("0123456789 -") for v in values})

    account_wordings = await distinct_wordings(Account, Account.name)
    assert account_wordings > 5, f"account names use only {account_wordings} wording(s)"

    opp_wordings = await distinct_wordings(Opportunity, Opportunity.title)
    assert opp_wordings > 5, f"opportunity titles use only {opp_wordings} wording(s)"

    subject_wordings = await distinct_wordings(CrmActivity, CrmActivity.subject)
    assert subject_wordings > 5, f"activity subjects use only {subject_wordings} wording(s)"

    sub_wordings = await distinct_wordings(Subcontractor, Subcontractor.legal_name)
    assert sub_wordings > 5, f"subcontractor names use only {sub_wordings} wording(s)"

    assert await distinct_of(Account, Account.name) >= 50


async def test_a_subcontractors_country_tax_id_and_city_agree(pg_session) -> None:
    """A record's country, VAT prefix and city must tell one story.

    Before the fix every subcontractor carried a German tax id and a German
    city whatever country it claimed. That is a coherence bug a screenshot
    shows immediately, so it is gated rather than left to review.
    """
    from app.modules.subcontractors.models import Subcontractor
    from app.modules.subcontractors.seed import _COUNTRY_PROFILES

    await _run_all_seeders(pg_session)

    rows = (await pg_session.execute(select(Subcontractor.country, Subcontractor.tax_id, Subcontractor.address))).all()
    assert rows, "no subcontractors were seeded, so nothing was checked"

    wrong: list[str] = []
    for country, tax_id, address in rows:
        cities, vat_prefix = _COUNTRY_PROFILES[country]
        if not (tax_id or "").startswith(vat_prefix):
            wrong.append(f"{country}: tax id {tax_id!r} is not a {vat_prefix} registration")
        city = (address or {}).get("city")
        if city not in cities:
            wrong.append(f"{country}: city {city!r} is not in {cities}")

    assert not wrong, "country, tax id and city disagree:\n" + "\n".join(wrong)
