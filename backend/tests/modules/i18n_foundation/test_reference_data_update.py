# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The explicit "update reference data" pass, against an install seeded from an older file.

The cohort is rebuilt from today's seed file rather than vendored: every
country and calendar, and every tax row except the four rate lines that
shipped on 2026-10-04 (Ireland's 9 % and zero rate, Hungary's 18 % and 5 %).
Each row carries one old ``created_at`` and the same ``updated_at``, which is
what the seeder leaves behind and what the edit rule reads as "untouched".

The boot repairs are deliberately NOT run while the cohort is built. They
would deliver the four lines themselves and every assertion about the preview
would then be measuring nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_repairs import DataRepairDelivery, snapshot_table
from app.modules.i18n_foundation.models import Country, TaxConfiguration, WorkCalendar
from app.modules.i18n_foundation.reference_data_update import (
    apply_reference_update,
    compute_reference_diff,
)
from app.modules.i18n_foundation.seed import (
    country_from_seed_row,
    load_country_seed_rows,
    load_tax_seed_rows,
    load_work_calendar_seed_rows,
    tax_configuration_from_seed_row,
    work_calendar_from_seed_row,
)
from app.modules.i18n_foundation.tax_history_backfill import backfill_past_tax_windows
from app.modules.i18n_foundation.tax_seed_reconcile import reconcile_shipped_tax_rows
from app.modules.i18n_foundation.tax_window_supersede import repair_superseded_tax_windows
from app.modules.i18n_foundation.work_calendar_seed_reconcile import reconcile_shipped_work_calendars
from tests.modules.i18n_foundation.conftest import API_PREFIX, build_app, http_client

pytestmark = pytest.mark.asyncio

#: The four rate lines the 2026-10-04 seed file added, and the Turkish list (I)
#: tier the 2026-10-10 one added.
NEW_LINES = {("IE", "VAT_RED_9"), ("IE", "VAT_ZERO"), ("HU", "AFA_18"), ("HU", "AFA_5"), ("TR", "KDV_1")}
NEW_LINES.add(("ES", "IVA_SRED"))
NEW_KEYS = {f"tax:{cc}/{code}" for cc, code in NEW_LINES}

#: When the old install was seeded: before any of the four shipped.
SEEDED_AT = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)

PREVIEW_URL = f"{API_PREFIX}/reference-data/updates/"
APPLY_URL = f"{API_PREFIX}/reference-data/updates/apply/"


def _stamp(row, at: datetime = SEEDED_AT):
    row.created_at = at
    row.updated_at = at
    return row


def _old_tax_rows() -> list[dict]:
    rows = [r for r in load_tax_seed_rows() if (r["country_code"], r["tax_code"]) not in NEW_LINES]
    # The cohort must really be the broken one, or every assertion below is vacuous.
    assert len(rows) == len(load_tax_seed_rows()) - len(NEW_LINES)
    held = {(r["country_code"], r["tax_code"]) for r in rows}
    assert ("IE", "VAT") in held and ("IE", "VAT_RED") in held and ("HU", "AFA") in held
    assert ("TR", "KDV") in held and ("TR", "KDV_RED") in held
    assert not (held & NEW_LINES)
    return rows


async def _install_old(session: AsyncSession) -> None:
    """An install seeded from the file as it stood before the IE and HU tiers shipped."""
    for model in (TaxConfiguration, WorkCalendar, Country):
        await session.execute(delete(model))
    await session.execute(delete(DataRepairDelivery))
    for row in load_country_seed_rows():
        session.add(_stamp(country_from_seed_row(row)))
    for row in load_work_calendar_seed_rows():
        session.add(_stamp(work_calendar_from_seed_row(row)))
    for row in _old_tax_rows():
        session.add(_stamp(tax_configuration_from_seed_row(row)))
    await session.flush()


async def _collapse_irish_standard_rate(session: AsyncSession, *, edited: bool) -> None:
    """The Irish standard rate as an install seeded before its 2020 cut holds it: one open 23 % row."""
    rows = await _tax(session, "IE", "VAT")
    assert sorted(r.effective_from for r in rows) == ["2012-01-01", "2020-09-01", "2021-03-01"]
    for row in rows:
        if row.effective_from != "2012-01-01":
            await session.delete(row)
    first = next(r for r in rows if r.effective_from == "2012-01-01")
    first.effective_to = None
    first.updated_at = SEEDED_AT + (timedelta(days=30) if edited else timedelta(microseconds=1))
    await session.flush()


async def _tax(session: AsyncSession, country: str, code: str) -> list[TaxConfiguration]:
    session.expire_all()
    result = await session.execute(
        select(TaxConfiguration).where(TaxConfiguration.country_code == country, TaxConfiguration.tax_code == code)
    )
    return list(result.scalars().all())


def _by_status(diff, status: str) -> set[str]:
    return {c.key for c in diff.changes if c.status == status}


async def test_the_preview_shows_exactly_the_new_ie_and_hu_lines(session: AsyncSession) -> None:
    await _install_old(session)

    diff = await compute_reference_diff(session)

    assert _by_status(diff, "ready") == NEW_KEYS
    assert _by_status(diff, "review") == set()
    for change in diff.changes:
        if change.key in NEW_KEYS:
            assert change.action == "add"
            assert change.reason == "new"
            assert change.rows_added == 1


async def test_the_preview_writes_nothing(session: AsyncSession) -> None:
    await _install_old(session)
    before = await snapshot_table(session, "oe_i18n_tax_config")

    await compute_reference_diff(session)

    assert await snapshot_table(session, "oe_i18n_tax_config") == before


async def test_apply_adds_the_new_rows_and_a_second_apply_is_a_no_op(session: AsyncSession) -> None:
    await _install_old(session)
    before = await snapshot_table(session, "oe_i18n_tax_config")

    result = await apply_reference_update(session, None)

    assert set(result.applied) == NEW_KEYS
    assert result.rows_added == len(NEW_LINES)
    assert result.rows_updated == 0
    nine = await _tax(session, "IE", "VAT_RED_9")
    assert [r.rate_pct for r in nine] == ["9.0"]
    five = await _tax(session, "HU", "AFA_5")
    assert [r.rate_pct for r in five] == ["5.0"]

    # Purely additive: no row that was on file changed.
    after = await snapshot_table(session, "oe_i18n_tax_config")
    for key, row in before.items():
        assert {k: v for k, v in after[key].items() if k != "updated_at"} == {
            k: v for k, v in row.items() if k != "updated_at"
        }

    again = await apply_reference_update(session, None)
    assert again.applied == []
    assert again.rows_added == 0
    assert again.rows_updated == 0
    assert _by_status(await compute_reference_diff(session), "ready") == set()


async def test_apply_only_writes_the_keys_it_was_given(session: AsyncSession) -> None:
    await _install_old(session)

    result = await apply_reference_update(session, ["tax:IE/VAT_RED_9", "tax:XX/NOT_A_LINE"])

    assert result.applied == ["tax:IE/VAT_RED_9"]
    assert "tax:XX/NOT_A_LINE" in result.skipped
    assert await _tax(session, "HU", "AFA_5") == []


async def test_a_row_the_user_edited_is_left_alone(session: AsyncSession) -> None:
    """A shipped row whose shipped value differs, so leaving it alone is a real decision."""
    await _install_old(session)
    hu = (await _tax(session, "HU", "AFA"))[0]
    de = (await _tax(session, "DE", "VAT"))[0]
    hu.tax_name = "Our own HU VAT label"
    hu.updated_at = SEEDED_AT + timedelta(days=30)
    # And its twin that nobody touched, drifted only because the file was renamed
    # since. ``updated_at`` has to be assigned a value that differs from the one
    # on file, or the ORM leaves it out of the UPDATE and ``onupdate`` stamps now.
    shipped_name, de_id = de.tax_name, de.id
    de.tax_name = "An older shipped label"
    de.updated_at = SEEDED_AT + timedelta(microseconds=1)
    await session.flush()

    diff = await compute_reference_diff(session)
    edited = [c for c in diff.changes if c.key == "tax:HU/AFA#edited"]
    assert edited and edited[0].status == "kept" and edited[0].reason == "edited_locally"
    assert [(f.field, f.before) for f in edited[0].fields] == [("tax_name", "Our own HU VAT label")]
    assert not any(c.key == "tax:HU/AFA" for c in diff.changes)
    ready_de = next(c for c in diff.changes if c.key == "tax:DE/VAT")
    assert (ready_de.status, ready_de.reason) == ("ready", "fields_changed")

    await apply_reference_update(session, None)

    assert (await _tax(session, "HU", "AFA"))[0].tax_name == "Our own HU VAT label"
    session.expire_all()
    assert (await session.get(TaxConfiguration, de_id)).tax_name == shipped_name


async def test_a_different_rate_on_the_same_period_is_never_applied(session: AsyncSession) -> None:
    await _install_old(session)
    at = (await _tax(session, "AT", "VAT"))[0]
    shipped_rate, at_id = at.rate_pct, at.id
    assert shipped_rate == "20.0"
    at.rate_pct = "21.0"
    wrong = at.rate_pct
    await session.flush()

    diff = await compute_reference_diff(session)
    review = [c for c in diff.changes if c.key == "tax:AT/VAT"]
    assert review and review[0].status == "review" and review[0].reason == "rate_differs"

    await apply_reference_update(session, [review[0].key])
    session.expire_all()
    assert (await session.get(TaxConfiguration, at_id)).rate_pct == wrong


async def test_a_missing_country_is_offered_and_a_drifted_one_is_updated(session: AsyncSession) -> None:
    await _install_old(session)
    gone = (await session.execute(select(Country).where(Country.iso_code == "MT"))).scalar_one()
    await session.delete(gone)
    bg = (await session.execute(select(Country).where(Country.iso_code == "BG"))).scalar_one()
    shipped_currency = bg.currency_default
    bg.currency_default = "XXX"
    bg.updated_at = SEEDED_AT + timedelta(microseconds=1)
    await session.flush()

    diff = await compute_reference_diff(session)
    ready = {c.key: c for c in diff.changes if c.status == "ready"}
    assert ready["country:MT"].action == "add"
    assert ready["country:BG"].action == "update"
    assert [(f.field, f.before, f.after) for f in ready["country:BG"].fields] == [
        ("currency_default", "XXX", shipped_currency)
    ]

    await apply_reference_update(session, ["country:MT", "country:BG"])
    session.expire_all()
    assert (await session.execute(select(Country).where(Country.iso_code == "MT"))).scalar_one() is not None
    assert (await session.execute(select(Country).where(Country.iso_code == "BG"))).scalar_one().currency_default == (
        shipped_currency
    )


async def test_apply_reloads_a_country_changed_since_the_preview(session: AsyncSession) -> None:
    await _install_old(session)
    country = (await session.execute(select(Country).where(Country.iso_code == "BG"))).scalar_one()
    country.currency_default = "XXX"
    country.updated_at = SEEDED_AT + timedelta(microseconds=1)
    await session.flush()
    preview = await compute_reference_diff(session)
    assert "country:BG" in _by_status(preview, "ready")

    # A separate writer's update leaves this session's preview objects stale.
    await session.execute(
        update(Country)
        .where(Country.id == country.id)
        .values(currency_default="USD", updated_at=SEEDED_AT + timedelta(days=1))
        .execution_options(synchronize_session=False)
    )
    result = await apply_reference_update(session, ["country:BG"])

    assert result.applied == []
    assert result.skipped == ["country:BG"]
    session.expire_all()
    current = (await session.execute(select(Country).where(Country.iso_code == "BG"))).scalar_one()
    assert current.currency_default == "USD"


async def test_the_boot_repairs_find_nothing_left_after_apply(session: AsyncSession) -> None:
    await _install_old(session)
    await apply_reference_update(session, None)

    assert await reconcile_shipped_tax_rows(session) == 0
    assert await backfill_past_tax_windows(session) == 0
    assert await repair_superseded_tax_windows(session) == 0
    assert await reconcile_shipped_work_calendars(session) == 0


@pytest.mark.parametrize("kind", ["calendar", "tax"])
async def test_apply_reloads_other_reference_rows_changed_since_preview(session: AsyncSession, kind: str) -> None:
    await _install_old(session)
    model = WorkCalendar if kind == "calendar" else TaxConfiguration
    column = "name" if kind == "calendar" else "tax_name"
    query = select(model).where(model.country_code == "DE")
    if kind == "tax":
        query = query.where(TaxConfiguration.tax_code == "VAT")
    row = (await session.execute(query)).scalars().first()
    key = f"calendar:DE/{row.year}" if kind == "calendar" else "tax:DE/VAT"
    setattr(row, column, "An older shipped label")
    row.updated_at = SEEDED_AT + timedelta(microseconds=1)
    await session.flush()
    preview = await compute_reference_diff(session)
    assert key in _by_status(preview, "ready")
    await session.execute(
        update(model)
        .where(model.id == row.id)
        .values(
            **{column: "Our own label", "updated_at": SEEDED_AT + timedelta(days=1)},
        )
        .execution_options(synchronize_session=False)
    )

    result = await apply_reference_update(session, [key])

    assert result.applied == []
    assert result.skipped == [key]
    await session.refresh(row)
    assert getattr(row, column) == "Our own label"


async def test_delivery_failure_rolls_back_all_reference_writes(session: AsyncSession, monkeypatch) -> None:
    from app.modules.i18n_foundation import reference_data_update as updater

    await _install_old(session)
    before = await snapshot_table(session, "oe_i18n_tax_config")

    async def fail_delivery(*args, **kwargs):
        raise RuntimeError("injected delivery failure")

    monkeypatch.setattr(updater, "record_deliveries", fail_delivery)
    with pytest.raises(RuntimeError, match="injected delivery failure"):
        await apply_reference_update(session, None)

    assert await snapshot_table(session, "oe_i18n_tax_config") == before
    assert _by_status(await compute_reference_diff(session), "ready") == NEW_KEYS


async def test_a_delivered_row_that_is_deleted_stays_deleted(session: AsyncSession) -> None:
    """Neither the boot reconciler nor the next preview may put it back."""
    await _install_old(session)
    await apply_reference_update(session, None)
    for row in await _tax(session, "IE", "VAT_RED_9"):
        await session.delete(row)
    await session.flush()

    assert await reconcile_shipped_tax_rows(session) == 0
    assert await _tax(session, "IE", "VAT_RED_9") == []

    diff = await compute_reference_diff(session)
    change = next(c for c in diff.changes if c.key == "tax:IE/VAT_RED_9")
    assert change.status == "kept"
    assert change.reason == "removed_here"
    await apply_reference_update(session, None)
    assert await _tax(session, "IE", "VAT_RED_9") == []


async def test_rows_the_user_created_are_never_touched(session: AsyncSession) -> None:
    await _install_old(session)
    own = TaxConfiguration(
        country_code="DE",
        tax_name="Our special levy",
        tax_code="OWN_LEVY",
        rate_pct="3.0",
        tax_type="vat",
        combination="national",
        effective_from="2020-01-01",
        is_default=False,
        metadata_={},
    )
    session.add(own)
    await session.flush()
    own_id = own.id

    diff = await compute_reference_diff(session)
    assert not any("OWN_LEVY" in c.key for c in diff.changes)
    await apply_reference_update(session, None)
    session.expire_all()
    kept = await session.get(TaxConfiguration, own_id)
    assert kept is not None and kept.rate_pct == "3.0"


async def test_a_rate_change_closes_the_old_period_and_adds_the_new_ones(session: AsyncSession) -> None:
    """Close and add, never rewrite: the 23 % row keeps its rate and only gains an end date."""
    await _install_old(session)
    await _collapse_irish_standard_rate(session, edited=False)
    before = await snapshot_table(session, "oe_i18n_tax_config")

    diff = await compute_reference_diff(session)
    line = next(c for c in diff.changes if c.key == "tax:IE/VAT")
    assert (line.status, line.reason, line.rows_added) == ("ready", "new_period", 2)

    await apply_reference_update(session, ["tax:IE/VAT"])

    after = await snapshot_table(session, "oe_i18n_tax_config")
    for key, old in before.items():
        new = after[key]
        moved = {col for col in old if col not in ("updated_at", "metadata") and old[col] != new[col]}
        if moved:
            assert moved == {"effective_to"}, f"row {key} changed {moved}"
            assert old["effective_to"] is None and new["effective_to"] == "2020-08-31"
            assert new["rate_pct"] == old["rate_pct"] == "23.0"
    rows = sorted(await _tax(session, "IE", "VAT"), key=lambda r: r.effective_from)
    assert [(r.effective_from, r.effective_to, r.rate_pct) for r in rows] == [
        ("2012-01-01", "2020-08-31", "23.0"),
        ("2020-09-01", "2021-02-28", "21.0"),
        ("2021-03-01", None, "23.0"),
    ]
    # The boot supersede repair finds nothing left to do on the line.
    assert await repair_superseded_tax_windows(session) == 0


async def test_an_edited_open_period_holds_the_whole_line(session: AsyncSession) -> None:
    """The close is skipped on an edited row, so adding the new periods would overlap it."""
    await _install_old(session)
    await _collapse_irish_standard_rate(session, edited=True)

    diff = await compute_reference_diff(session)
    line = next(c for c in diff.changes if c.key == "tax:IE/VAT")
    assert (line.status, line.reason) == ("review", "overlap")

    await apply_reference_update(session, None)
    rows = await _tax(session, "IE", "VAT")
    assert [(r.effective_from, r.effective_to) for r in rows] == [("2012-01-01", None)]


# ── CLI ──────────────────────────────────────────────────────────────────────


def _hand_cli_the_session(monkeypatch: pytest.MonkeyPatch, session: AsyncSession) -> None:
    """Point the command's ``async_session_factory`` at this test's rolled-back session."""
    import app.database

    class _Borrowed:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(app.database, "async_session_factory", lambda: _Borrowed())


async def test_the_cli_dry_run_prints_the_diff_and_writes_nothing(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli import run_reference_data_update

    await _install_old(session)
    # The dry run rolls its session back, which in this fixture is the savepoint
    # holding the cohort, so the cohort has to be committed into it first.
    await session.commit()
    _hand_cli_the_session(monkeypatch, session)

    out: list[str] = []
    diff = await run_reference_data_update(False, write=out.append)

    assert {c.key for c in diff.changes if c.status == "ready"} == NEW_KEYS
    text = "\n".join(out)
    assert "tax:IE/VAT_RED_9" in text and "Dry run" in text
    assert await _tax(session, "IE", "VAT_RED_9") == []


async def test_the_cli_apply_writes_and_a_second_run_has_nothing_left(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli import run_reference_data_update

    await _install_old(session)
    await session.commit()
    _hand_cli_the_session(monkeypatch, session)

    applied: list[str] = []
    await run_reference_data_update(True, write=applied.append)
    assert any(f"{len(NEW_LINES)} row(s) added" in line for line in applied)
    assert [r.rate_pct for r in await _tax(session, "HU", "AFA_18")] == ["18.0"]

    again: list[str] = []
    diff = await run_reference_data_update(False, write=again.append)
    assert diff.count("ready") == 0
    assert any("already matches" in line for line in again)


def test_the_cli_defaults_to_a_dry_run_and_refuses_both_modes() -> None:
    from app import cli

    parser = cli._build_parser()
    assert parser.parse_args(["update-reference-data"]).apply is False
    assert parser.parse_args(["update-reference-data", "--apply"]).apply is True
    with pytest.raises(SystemExit):
        parser.parse_args(["update-reference-data", "--apply", "--dry-run"])


# ── HTTP ─────────────────────────────────────────────────────────────────────


async def test_an_editor_can_neither_preview_nor_apply(session: AsyncSession) -> None:
    await _install_old(session)
    async with http_client(build_app(session, role="editor")) as client:
        assert (await client.get(PREVIEW_URL)).status_code == 403
        assert (await client.post(APPLY_URL, json={"keys": sorted(NEW_KEYS)})).status_code == 403
    assert await _tax(session, "IE", "VAT_RED_9") == []


async def test_an_admin_previews_and_applies_over_http(session: AsyncSession) -> None:
    await _install_old(session)
    async with http_client(build_app(session, role="admin")) as client:
        preview = await client.get(PREVIEW_URL)
        assert preview.status_code == 200
        body = preview.json()
        ready = {c["key"] for c in body["changes"] if c["status"] == "ready"}
        assert ready == NEW_KEYS
        assert body["ready"] == len(NEW_LINES)

        applied = await client.post(APPLY_URL, json={"keys": sorted(ready)})
        assert applied.status_code == 200
        assert applied.json()["rows_added"] == len(NEW_LINES)
        assert applied.json()["preview"]["ready"] == 0
    assert [r.rate_pct for r in await _tax(session, "IE", "VAT_RED_9")] == ["9.0"]
