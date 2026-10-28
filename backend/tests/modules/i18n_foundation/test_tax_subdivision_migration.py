"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠v3307 on the path that actually reaches installs, not the one on paper.

``alembic upgrade head`` is not how most of this platform's databases get a new
column. The embedded-PostgreSQL runtime builds its schema with ``create_all``
and *stamps* alembic rather than running it, then heals later columns out of
the models at boot (``app/core/postgres_migrator.py``). On such an install
``v3307_tax_subdivision.upgrade()`` never executes: the column appears, empty,
and the revision's backfill does not.

What that would cost is the reason this file exists. Every Canadian rate would
be present and none of them labelled, so a lookup for Ontario finds no
provincial rate, sees that Ontario is a province the platform knows, and
concludes "federal only, 5 %" - the wrong total, delivered with exactly the
confidence Alberta's correct 5 % deserves. The resolver therefore withholds the
federal-only claim while any sub-national row is unlabelled, which turns that
into a refusal to answer; the repair below is what turns the refusal into 13 %.
Both halves are asserted here, in that order.

So the backfill exists twice, once in the revision for whoever runs alembic and
once as the ``tax_subdivision_backfill`` entry in ``app/core/data_repairs.py``
for everyone else, and this file covers both halves of that arrangement:

* the two backfill tables are identical, so the duplication cannot drift
* the revision points at the registered repair, and the repair is registered
* the boot-time half repairs the state a healed install is actually left in,
  is idempotent, and never overwrites a value somebody set by hand

The revision's own ``upgrade()`` is not executed here. It is DDL against a
table this fixture already created from the models, so running it would prove
only that ``ADD COLUMN IF NOT EXISTS`` is a no-op. What is worth pinning about
it is that its constraint predicate and the model's are the same sentence, and
that is asserted directly.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_repairs import discover_data_repairs
from app.modules.i18n_foundation.models import SUBNATIONAL_COMBINATIONS, TaxConfiguration
from app.modules.i18n_foundation.service import I18nFoundationService
from app.modules.i18n_foundation.subdivisions import (
    SHIPPED_SUBDIVISION_BACKFILL,
    SHIPPED_SUBDIVISION_COMBINATION,
)
from app.modules.i18n_foundation.tax_subdivision_repair import repair_tax_subdivisions

_MIGRATION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3307_tax_subdivision.py"

#: What a fresh install is seeded from, and therefore what an upgraded one has
#: to be repaired into agreement with.
_SEED_FILE = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "i18n_foundation"
    / "seed_data"
    / "tax_configurations.json"
)

# The finished name after ``Base.metadata``'s ``ck_%(table_name)s_%(constraint_name)s``
# convention has been applied to the model's ``subdivision_matches_combination``.
# The revision never spells this out: it hands ``op`` the bare name and lets the
# convention build it, which is what keeps its upgrade and its downgrade agreeing
# about what to drop. That the name the convention produces is the one the model
# gets is the subject of a test below.
_CONSTRAINT = "ck_oe_i18n_tax_config_subdivision_matches_combination"


def _migration() -> Any:
    """Side-load the revision; ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("v3307_tax_subdivision", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_sql(predicate: str) -> str:
    """Collapse whitespace so two spellings of one predicate compare equal."""
    return re.sub(r"\s+", " ", predicate).strip().lower()


# ── The two copies of the backfill ──────────────────────────────────────────


def test_the_migration_and_the_boot_repair_carry_the_same_table() -> None:
    """The anti-drift gate for a deliberate duplication.

    The revision keeps its own literals rather than importing the module's,
    because a migration has to keep working against the schema it was written
    for and importing today's application code is how a revision starts failing
    years later. The cost of that is two tables that can diverge, so they are
    compared here: an install that runs alembic and one that does not must end
    up with the same eleven rows pointing at the same eleven provinces.
    """
    migration_table = {(country, tax_code): subdivision for country, tax_code, subdivision in _migration()._BACKFILL}

    assert migration_table == SHIPPED_SUBDIVISION_BACKFILL


def test_the_migration_and_the_model_state_the_same_constraint() -> None:
    """One invariant, two places it is written down, and they must agree.

    The revision creates the check constraint for an alembic-run install; the
    model declares it so the boot heal creates it everywhere else. A difference
    between the two would mean the same platform enforcing two different rules
    depending on how the database was built.
    """
    migration = _migration()
    model_constraint = next(
        constraint
        for constraint in TaxConfiguration.__table__.constraints
        if getattr(constraint, "name", None) == _CONSTRAINT
    )

    assert _normalize_sql(migration._CHECK) == _normalize_sql(str(model_constraint.sqltext))

    # The revision hands ``op`` the bare name and lets the metadata convention
    # build the finished one, so what has to agree with the model is not a
    # literal but the set of names the revision would recognise. Called outside
    # a migration context it falls back to spelling the convention itself,
    # which is the branch an introspection guard uses against an ORM-built
    # database - the one this test's fixture is.
    assert _CONSTRAINT in migration._constraint_candidates()


def test_every_backfilled_subdivision_belongs_to_the_row_it_repairs() -> None:
    """The table maps each row to a province of its own country, not another's."""
    mismatched = [
        (country, tax_code, subdivision)
        for (country, tax_code), subdivision in SHIPPED_SUBDIVISION_BACKFILL.items()
        if not subdivision.startswith(f"{country}-")
    ]

    assert mismatched == []


def test_the_two_repair_tables_describe_the_same_rows() -> None:
    """Subdivision and combination are two halves of one statement per row.

    The repair reads both tables with the same key, so a row present in one and
    absent from the other is a KeyError on the boot path of an upgraded install
    and nowhere else. Held here instead.
    """
    assert set(SHIPPED_SUBDIVISION_COMBINATION) == set(SHIPPED_SUBDIVISION_BACKFILL)


def test_every_repaired_combination_is_a_sub_national_one() -> None:
    """A repaired row gets a subdivision, so its combination has to allow one.

    The check constraint is an equality, not an implication: writing a
    subdivision onto a row whose combination is ``national`` or ``federal`` is
    refused, and the repair would then fail on every boot.
    """
    wrong = {
        key: combination
        for key, combination in SHIPPED_SUBDIVISION_COMBINATION.items()
        if combination not in SUBNATIONAL_COMBINATIONS
    }

    assert wrong == {}


def test_the_repair_table_agrees_with_the_shipped_seed() -> None:
    """What the repair writes is what a fresh install would have had.

    The point of the repair is that an upgraded database ends up holding what
    the seed file gives a new one. Two hand-maintained copies of the same ten
    rows drift, and the drift would only show as a Canadian rate that combines
    one way on an old install and another way on a new one.
    """
    seed = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
    from_seed = {
        (row["country_code"], row["tax_code"]): (row["subdivision_code"], row["combination"])
        for row in seed
        if (row.get("country_code"), row.get("tax_code")) in SHIPPED_SUBDIVISION_BACKFILL
    }
    from_tables = {
        key: (SHIPPED_SUBDIVISION_BACKFILL[key], SHIPPED_SUBDIVISION_COMBINATION[key])
        for key in SHIPPED_SUBDIVISION_BACKFILL
    }

    assert from_seed == from_tables


# ── The boot repair, against the state a healed install is left in ──────────


async def _drop_constraint(session: AsyncSession) -> None:
    """Reproduce a database holding rows that break the rule.

    That is what an upgraded install looks like between the heal adding the
    column and the boot repair filling it: the rows are already there and the
    subdivision is NULL. This fixture's table was built by ``create_all``, so
    the constraint is on it and fully validated, and the broken state cannot be
    written while it stands - which is the constraint doing its job, and also
    why the repair has to be tested against a database put into that state
    deliberately rather than a clean one.

    Dropping it is only half the story on a real install, where the heal puts
    the constraint back as ``NOT VALID`` before the repair runs;
    ``test_the_repair_runs_against_the_constraint_the_heal_adds_first`` covers
    that ordering.
    """
    await session.execute(text(f'ALTER TABLE oe_i18n_tax_config DROP CONSTRAINT "{_CONSTRAINT}"'))


async def _insert_unmigrated(session: AsyncSession, tax_code: str, combination: str, rate: str) -> None:
    """Insert a row the way a pre-v3307 install holds it: no subdivision."""
    await session.execute(
        text(
            "INSERT INTO oe_i18n_tax_config "
            "(id, country_code, tax_name, tax_code, rate_pct, tax_type, combination, is_default, metadata) "
            "VALUES (gen_random_uuid(), 'CA', :name, :tax_code, :rate, 'gst', :combination, false, '{}')"
        ).bindparams(name=tax_code, tax_code=tax_code, rate=rate, combination=combination)
    )


async def test_the_repair_gives_the_shipped_rows_their_province(session: AsyncSession) -> None:
    """The upgraded install, repaired at boot.

    Rows that a pre-v3307 database holds with a NULL subdivision get one, and
    the resolver then answers Ontario with 13 % instead of declining.
    """
    await _drop_constraint(session)
    await _insert_unmigrated(session, "GST", "federal", "5.0")
    await _insert_unmigrated(session, "HST_ON", "replaces_federal", "13.0")
    await _insert_unmigrated(session, "PST_BC", "stacks_on_federal", "7.0")
    service = I18nFoundationService(session)

    # Unrepaired, the answer is a refusal rather than a confident 5 %. This is
    # the assertion that stops the whole feature resting on a boot repair
    # having succeeded: if it never runs, Ontario is unanswered, not wrong.
    before = await service.resolve_tax_rate("CA", "CA-ON", "2026-08-26")
    assert before.status == "subdivision_unknown"
    assert before.combined_rate_pct is None
    assert "backfill" in (before.reason or "")

    repaired = await repair_tax_subdivisions(session)

    assert repaired == 2, "only the two sub-national rows should be touched"
    session.expire_all()
    after = await service.resolve_tax_rate("CA", "CA-ON", "2026-08-26")
    assert (after.status, after.combined_rate_pct) == ("harmonised", "13")

    british_columbia = await service.resolve_tax_rate("CA", "CA-BC", "2026-08-26")
    assert (british_columbia.status, british_columbia.combined_rate_pct) == ("stacked", "12")


async def test_the_repair_leaves_the_federal_row_country_wide(session: AsyncSession) -> None:
    """A NULL that means "country-wide" is not a NULL waiting to be filled.

    The federal GST row belongs to no province. The repair must not reach for
    it, or the check constraint would refuse the row it just broke.
    """
    await _drop_constraint(session)
    await _insert_unmigrated(session, "GST", "federal", "5.0")

    await repair_tax_subdivisions(session)

    session.expire_all()
    row = (await session.execute(select(TaxConfiguration).where(TaxConfiguration.tax_code == "GST"))).scalar_one()
    assert row.subdivision_code is None


async def test_the_repair_is_idempotent(session: AsyncSession) -> None:
    """It runs on every boot, so the second run must do nothing.

    The predicate is the stored value being NULL, not a version marker, which
    is what makes a partially repaired database safe to run this against.
    """
    await _drop_constraint(session)
    await _insert_unmigrated(session, "HST_ON", "replaces_federal", "13.0")

    first = await repair_tax_subdivisions(session)
    second = await repair_tax_subdivisions(session)

    assert first == 1
    assert second == 0


async def test_the_repair_does_not_overwrite_a_correction(session: AsyncSession) -> None:
    """An operator who moved a rate by hand keeps where they moved it to.

    The repair writes only where the column is still NULL. A deployment that
    reassigned a rate - or that renamed a province's row - is not second-guessed
    on the next boot.
    """
    await _drop_constraint(session)
    await _insert_unmigrated(session, "HST_ON", "replaces_federal", "13.0")
    await session.execute(text("UPDATE oe_i18n_tax_config SET subdivision_code = 'CA-NB' WHERE tax_code = 'HST_ON'"))

    repaired = await repair_tax_subdivisions(session)

    assert repaired == 0
    session.expire_all()
    row = (await session.execute(select(TaxConfiguration).where(TaxConfiguration.tax_code == "HST_ON"))).scalar_one()
    assert row.subdivision_code == "CA-NB"


def test_the_repair_is_registered_against_this_revision() -> None:
    """The revision names a repair id, and the live registry has to hold it.

    ``# boot-repair: registry=tax_subdivision_backfill`` in the revision is
    checked by ``scripts/check_data_rewrite_boot_repair.py`` at commit time,
    against source text. This asserts the other end of the same link against
    the registry the application actually builds, so a repair whose
    ``repairs.py`` stopped importing - and would therefore never run on boot -
    fails here rather than nowhere.
    """
    entry = next(r for r in discover_data_repairs() if r.repair_id == "tax_subdivision_backfill")

    assert entry.revision == "v3307_tax_subdivision"
    assert entry.run is not None


async def test_the_repair_runs_against_the_constraint_the_heal_adds_first(session: AsyncSession) -> None:
    """Boot order: the constraint lands before the data is right, and must not block it.

    ``_heal_constraints`` in ``app/core/postgres_migrator.py`` issues check
    constraints as ``ADD CONSTRAINT ... NOT VALID``, and the schema heal runs
    ahead of the data repairs. So on the first boot after an upgrade the rule is
    live while the eleven shipped rows are still in breach of it - ``NOT VALID``
    is what lets that state exist rather than failing the boot.

    What ``NOT VALID`` does *not* skip is the check on an ``UPDATE``. The repair
    is an ``UPDATE`` over exactly those rows, so if it ever wrote a combination
    and subdivision that disagreed, the boot repair would fail every start and
    the rates would stay unlabelled forever. This reproduces that order - breach
    first, constraint second, repair third - and asserts the repair goes
    through.
    """
    await _drop_constraint(session)
    await _insert_unmigrated(session, "GST", "federal", "5.0")
    await _insert_unmigrated(session, "HST_ON", "replaces_federal", "13.0")
    await _insert_unmigrated(session, "PST_BC", "stacks_on_federal", "7.0")
    # The heal's own DDL, verbatim in shape: the rule goes on over rows that
    # break it, which a plain ADD CONSTRAINT would refuse.
    await session.execute(
        text(f'ALTER TABLE oe_i18n_tax_config ADD CONSTRAINT "{_CONSTRAINT}" CHECK ({_migration()._CHECK}) NOT VALID')
    )

    repaired = await repair_tax_subdivisions(session)
    await session.flush()

    assert repaired == 2
    session.expire_all()
    service = I18nFoundationService(session)
    assert (await service.resolve_tax_rate("CA", "CA-ON", "2026-08-26")).combined_rate_pct == "13"


async def test_the_repair_runs_on_a_database_that_predates_the_combination_column(
    session: AsyncSession,
) -> None:
    """The cohort seeded before v15.5.0, which is where this used to fail.

    ``combination`` arrived two releases before ``subdivision_code``. A database
    seeded before it gets the column from the boot heal, and the heal fills
    every existing row with the server default ``national`` - so the Ontario row
    on such an install says it is a country-wide rate.

    Nothing drops the check constraint here, and nothing needs to. ``national``
    with a NULL subdivision is a perfectly legal row: that is why the state was
    invisible. What is illegal is the half-write the repair used to make, and
    ``NOT VALID`` exempts existing rows but never an ``UPDATE``, so the repair
    was refused on every start and the provinces stayed unlabelled for the life
    of the install. The repair now moves both halves together.
    """
    await _insert_unmigrated(session, "GST", "national", "5.0")
    await _insert_unmigrated(session, "HST_ON", "national", "13.0")
    await _insert_unmigrated(session, "PST_BC", "national", "7.0")

    repaired = await repair_tax_subdivisions(session)
    await session.flush()

    assert repaired == 2
    session.expire_all()
    rows = {
        row.tax_code: (row.subdivision_code, row.combination)
        for row in (await session.execute(select(TaxConfiguration))).scalars()
    }
    assert rows["HST_ON"] == ("CA-ON", "replaces_federal")
    assert rows["PST_BC"] == ("CA-BC", "stacks_on_federal")
    # The federal row is not in the repair table, so it keeps what it had. Its
    # combination is wrong on this cohort too - it should read ``federal`` - but
    # that is a country-wide row with no subdivision either way, so it neither
    # breaks the constraint nor blocks the repair. Recorded, not fixed here.
    assert rows["GST"] == (None, "national")

    service = I18nFoundationService(session)
    assert (await service.resolve_tax_rate("CA", "CA-ON", "2026-08-26")).combined_rate_pct == "13"


async def test_the_repair_stays_idempotent_on_the_pre_combination_cohort(
    session: AsyncSession,
) -> None:
    """Writing two columns instead of one must not cost idempotence.

    The predicate is still the subdivision being NULL, so the second pass finds
    nothing - including nothing whose combination it would rewrite.
    """
    await _insert_unmigrated(session, "HST_ON", "national", "13.0")

    first = await repair_tax_subdivisions(session)
    second = await repair_tax_subdivisions(session)

    assert (first, second) == (1, 0)
