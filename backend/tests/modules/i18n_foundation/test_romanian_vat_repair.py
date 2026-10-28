# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Healing an install that was seeded before Romania's 2025 VAT reform.

What is being tested, and against what
--------------------------------------
``seed.py`` writes ``oe_i18n_tax_config`` only when it is empty, so shipping a
corrected seed file reaches new installations and nobody else. Every database
seeded before 1 August 2025 still carries one open Romanian row at 19 % and no
reduced rate. ``repair_romanian_vat_rates`` is what reaches those, and it runs
from the boot-path registry rather than from a revision body, because this
product does not run ``alembic upgrade``.

**The fixture here is the pre-reform state, built explicitly.** Seeding the
current JSON and running the repair would prove nothing at all: the current
JSON already carries both standard rows and the reduced band, so the repair
would correctly do nothing and the test would pass without ever exercising it.
Every case below starts from the row the old seeder wrote and asserts what the
repair-absent state resolves to before asserting what the repaired one does.

The money assertions
--------------------
Rates are asserted by pricing a real net amount through the resolver the API
serves, not by reading a column back. A rate that round-trips through a field
is not evidence anybody can invoice with it.

Rate sources are cited on ``ROMANIA_VAT_SOURCES`` in
``app/modules/i18n_foundation/romania_vat.py``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.romania_vat import repair_romanian_vat_rates
from app.modules.i18n_foundation.service import I18nFoundationService
from tests.modules.i18n_foundation.conftest import make_tax

#: A date after the reform.
TODAY = "2026-08-26"

#: The last day the old rate applied, and the first day the new one does.
BEFORE = "2025-07-31"
AFTER = "2025-08-01"

NET = Decimal("100000.00")


def _tax_on(net: Decimal, rate_pct: str) -> tuple[Decimal, Decimal]:
    """Tax and gross for ``net`` at ``rate_pct``, rounded as an invoice rounds."""
    tax = (net * Decimal(rate_pct) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return tax, (net + tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def seed_pre_reform_romania(session: AsyncSession) -> TaxConfiguration:
    """The single open Romanian row the old seed file wrote, and nothing else."""
    return await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        combination="national",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=True,
    )


async def _romanian_rows(session: AsyncSession) -> list[TaxConfiguration]:
    session.expire_all()
    result = await session.execute(
        select(TaxConfiguration).where(TaxConfiguration.country_code == "RO").order_by(TaxConfiguration.rate_pct)
    )
    return list(result.scalars().all())


# ── The stale install, before and after ──────────────────────────────────────


async def test_before_the_repair_a_stale_install_still_prices_at_nineteen(session: AsyncSession) -> None:
    """The control that makes the next test mean something.

    If this ever fails, the fixture is no longer the pre-reform state and every
    "after" assertion below is being made about a database that was already
    correct.
    """
    await seed_pre_reform_romania(session)
    service = I18nFoundationService(session)

    resolution = await service.resolve_tax_rate("RO", None, TODAY)

    assert resolution.combined_rate_pct == "19"
    assert _tax_on(NET, resolution.combined_rate_pct) == (Decimal("19000.00"), Decimal("119000.00"))


async def test_the_repair_puts_a_stale_install_on_twenty_one(session: AsyncSession) -> None:
    """A tenant nobody updated starts pricing new work at the rate in force."""
    await seed_pre_reform_romania(session)

    changed = await repair_romanian_vat_rates(session)

    assert changed == 3, "expected the 19 % row closed and the 21 % and 11 % rows added"
    resolution = await I18nFoundationService(session).resolve_tax_rate("RO", None, TODAY)
    assert resolution.combined_rate_pct == "21"
    assert _tax_on(NET, resolution.combined_rate_pct) == (Decimal("21000.00"), Decimal("121000.00"))


async def test_the_repair_adds_the_reduced_band(session: AsyncSession) -> None:
    """11 % lands on file, priceable, and not as the country's default rate."""
    await seed_pre_reform_romania(session)

    await repair_romanian_vat_rates(session)

    reduced = [r for r in await _romanian_rows(session) if r.tax_code == "TVA_RED"]
    assert [(r.rate_pct, r.effective_from, r.effective_to, r.is_default) for r in reduced] == [
        ("11.0", AFTER, None, False)
    ]
    assert _tax_on(NET, reduced[0].rate_pct) == (Decimal("11000.00"), Decimal("111000.00"))


# ── The negative control: issued work must not change value ──────────────────


async def test_a_document_priced_before_the_reform_still_computes_at_nineteen(session: AsyncSession) -> None:
    """The whole reason the repair closes the old row instead of rewriting it.

    An estimate or invoice dated before 1 August 2025 was issued at 19 %. If
    the repair had edited the row to say 21, that document would have changed
    value the moment a customer restarted the app, with nothing to say so.
    """
    await seed_pre_reform_romania(session)
    await repair_romanian_vat_rates(session)
    service = I18nFoundationService(session)

    old = await service.resolve_tax_rate("RO", None, BEFORE)
    new = await service.resolve_tax_rate("RO", None, AFTER)

    assert old.combined_rate_pct == "19"
    assert _tax_on(NET, old.combined_rate_pct) == (Decimal("19000.00"), Decimal("119000.00"))
    assert new.combined_rate_pct == "21"
    assert _tax_on(NET, new.combined_rate_pct) == (Decimal("21000.00"), Decimal("121000.00"))


async def test_the_old_rate_keeps_its_own_percentage_on_disk(session: AsyncSession) -> None:
    """Read from the table, not through the resolver: 19.0 is still 19.0.

    The resolver could mask a rewrite by picking the other row. This looks at
    what is stored.
    """
    await seed_pre_reform_romania(session)

    await repair_romanian_vat_rates(session)

    rows = {(r.rate_pct, r.effective_from, r.effective_to) for r in await _romanian_rows(session)}
    assert ("19.0", "2017-01-01", BEFORE) in rows
    assert ("21.0", AFTER, None) in rows


# ── Idempotence ──────────────────────────────────────────────────────────────


async def test_running_it_twice_changes_nothing_the_second_time(session: AsyncSession) -> None:
    """The contract every registered repair owes: it runs on every boot."""
    await seed_pre_reform_romania(session)

    first = await repair_romanian_vat_rates(session)
    before = [
        (r.tax_code, r.rate_pct, r.effective_from, r.effective_to, r.is_default) for r in await _romanian_rows(session)
    ]
    second = await repair_romanian_vat_rates(session)
    after = [
        (r.tax_code, r.rate_pct, r.effective_from, r.effective_to, r.is_default) for r in await _romanian_rows(session)
    ]

    assert (first, second) == (3, 0)
    assert before == after


async def test_an_install_that_already_has_the_split_only_gains_the_reduced_band(session: AsyncSession) -> None:
    """The cohort seeded between the split shipping and the reduced band shipping.

    Gating the reduced rate on the standard-rate repair would have left this
    cohort without it forever, which is the same defect one release later.
    """
    await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to=BEFORE,
        is_default=False,
    )
    await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="21.0",
        tax_type="vat",
        effective_from=AFTER,
        effective_to=None,
        is_default=True,
    )

    changed = await repair_romanian_vat_rates(session)

    assert changed == 1
    assert [r.rate_pct for r in await _romanian_rows(session) if r.tax_code == "TVA_RED"] == ["11.0"]


# ── What it declines to touch ────────────────────────────────────────────────


async def test_a_rate_an_operator_edited_is_left_exactly_as_it_is(session: AsyncSession) -> None:
    """An install managing its own Romanian rate keeps it.

    The guard matches all four fields the seeder wrote. A row at 20 % is not
    the row we shipped, whatever else it says, so the standard-rate step is
    skipped entirely rather than closing somebody's own rate for them.
    """
    await make_tax(
        session,
        country_code="RO",
        tax_name="Local TVA",
        tax_code="TVA",
        rate_pct="20.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=True,
    )

    await repair_romanian_vat_rates(session)

    standard = [r for r in await _romanian_rows(session) if r.tax_code == "TVA"]
    assert [(r.rate_pct, r.effective_to) for r in standard] == [("20.0", None)]
    resolution = await I18nFoundationService(session).resolve_tax_rate("RO", None, TODAY)
    assert resolution.combined_rate_pct == "20"


async def test_an_install_with_no_romanian_rows_gains_none(session: AsyncSession) -> None:
    """A repair is for data that is there. Inserting rates nobody seeded is not one."""
    changed = await repair_romanian_vat_rates(session)

    assert changed == 0
    assert await _romanian_rows(session) == []


async def test_a_row_somebody_already_closed_by_hand_is_not_reopened(session: AsyncSession) -> None:
    """An ``effective_to`` already set means somebody made a decision here."""
    await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to="2026-12-31",
        is_default=True,
    )

    changed = await repair_romanian_vat_rates(session)

    standard = [r for r in await _romanian_rows(session) if r.tax_code == "TVA"]
    # Only the reduced band is added; the hand-set window is untouched and no
    # 21 % row appears beside it, because the split was never applied here.
    assert changed == 1
    assert [(r.rate_pct, r.effective_to) for r in standard] == [("19.0", "2026-12-31")]


# ── What it refuses, because applying it would cost the country its rate ─────
#
# ``resolve`` names a country's rate from the row flagged ``is_default``, or
# from the single row on file when there is one and nothing is flagged. Adding
# a second, unflagged row to an install of the second kind leaves neither -
# ``default_rate_ambiguous``, no rate at all. Every case below is an install
# that prices correctly today and would stop pricing if the repair ran, and
# each asserts the money still comes out, not merely that a column is intact.


async def test_an_unflagged_operator_rate_does_not_lose_the_country_its_rate(session: AsyncSession) -> None:
    """One unflagged row prices fine alone; a band beside it would end that."""
    await make_tax(
        session,
        country_code="RO",
        tax_name="Local TVA",
        tax_code="TVA",
        rate_pct="20.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=False,
    )
    service = I18nFoundationService(session)
    assert (await service.resolve_tax_rate("RO", None, TODAY)).combined_rate_pct == "20"

    changed = await repair_romanian_vat_rates(session)

    assert changed == 0
    assert [r.tax_code for r in await _romanian_rows(session)] == ["TVA"]
    after = await service.resolve_tax_rate("RO", None, TODAY)
    assert after.combined_rate_pct == "20"
    assert _tax_on(NET, after.combined_rate_pct) == (Decimal("20000.00"), Decimal("120000.00"))


async def test_an_unflagged_hand_closed_row_keeps_pricing(session: AsyncSession) -> None:
    """The hand-closed window and the unflagged flag together are the trap.

    The standard-rate step already declines a row somebody closed by hand, so
    only the reduced band would be added - and that alone is enough to leave
    two rows in force with no default between them.
    """
    await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to="2026-12-31",
        is_default=False,
    )

    changed = await repair_romanian_vat_rates(session)

    assert changed == 0
    assert [r.tax_code for r in await _romanian_rows(session)] == ["TVA"]
    after = await I18nFoundationService(session).resolve_tax_rate("RO", None, TODAY)
    assert after.combined_rate_pct == "19"
    assert _tax_on(NET, after.combined_rate_pct) == (Decimal("19000.00"), Decimal("119000.00"))


async def test_a_second_flagged_default_is_not_created_beside_an_operator_s_own(session: AsyncSession) -> None:
    """The opposite failure: the plan's own 21 % row would be the second default.

    This install already answers - the operator's row is the one flagged - and
    the repair inserting a flagged standard rate beside it would take that
    answer away.
    """
    await make_tax(
        session,
        country_code="RO",
        tax_name="Negotiated TVA",
        tax_code="TVA_LOCAL",
        rate_pct="24.0",
        tax_type="vat",
        effective_from="2020-01-01",
        effective_to=None,
        is_default=True,
    )
    await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=False,
    )
    service = I18nFoundationService(session)
    assert (await service.resolve_tax_rate("RO", None, TODAY)).combined_rate_pct == "24"

    changed = await repair_romanian_vat_rates(session)

    assert changed == 0
    stored = {(r.tax_code, r.rate_pct, r.effective_to) for r in await _romanian_rows(session)}
    assert stored == {("TVA_LOCAL", "24.0", None), ("TVA", "19.0", None)}
    after = await service.resolve_tax_rate("RO", None, TODAY)
    assert after.combined_rate_pct == "24"
    assert _tax_on(NET, after.combined_rate_pct) == (Decimal("24000.00"), Decimal("124000.00"))


async def test_the_refusal_does_not_swallow_the_install_it_is_meant_to_fix(session: AsyncSession) -> None:
    """The guard's own negative control: the ordinary stale install still heals.

    A guard that refused everything would make every other test in this file
    pass by doing nothing, so this asserts the plain pre-reform database is
    still repaired and still prices at the new rate.
    """
    await seed_pre_reform_romania(session)

    assert await repair_romanian_vat_rates(session) == 3
    after = await I18nFoundationService(session).resolve_tax_rate("RO", None, TODAY)
    assert after.combined_rate_pct == "21"
    assert _tax_on(NET, after.combined_rate_pct) == (Decimal("21000.00"), Decimal("121000.00"))


# ── The limit of the guard, stated as a test rather than as a comment ────────


async def test_a_deliberate_holder_and_a_stale_tenant_are_byte_identical(session: AsyncSession) -> None:
    """The question the repair cannot answer, pinned so nobody assumes it away.

    Two Romanian installs. One is a tenant nobody ever updated. The other is a
    tenant who wants 19 % and has decided to keep it. Both were seeded by the
    same seeder and neither has edited anything, because *keeping* the old rate
    requires no edit - which is exactly why the two are indistinguishable.

    This asserts they are equal on every column the table carries, timestamps
    included. ``updated_at`` has a Python-side ``onupdate``, so it does detect
    that somebody touched a row; it cannot detect somebody deciding to leave
    one alone. If a future change adds a column that would separate them - an
    explicit "managed by operator" flag, a rate provenance field - this test
    fails, and that is the signal to revisit the guard.

    What makes the repair safe despite this is not a guard. It is that closing
    the window preserves 19 % for every pre-reform date, so the tenant who
    wanted the old rate for historical work still has it.
    """
    stale = await seed_pre_reform_romania(session)
    session.expunge(stale)

    deliberate = await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        combination="national",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=True,
    )

    columns = [c.name for c in TaxConfiguration.__table__.columns if c.name != "id"]
    rows = await _romanian_rows(session)
    assert len(rows) == 2, "the fixture must build two separate rows to compare"
    first, second = ({c: getattr(r, c if c != "metadata" else "metadata_") for c in columns} for r in rows)

    differing = {c for c in columns if first[c] != second[c] and c not in {"created_at", "updated_at"}}
    assert differing == set(), f"a column separates them after all, and the guard should use it: {differing}"
    assert deliberate is not None
