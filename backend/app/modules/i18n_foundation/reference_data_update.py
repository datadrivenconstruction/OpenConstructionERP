# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bring an installed database's reference data up to the shipped seed files, on request.

Why this exists beside the boot repairs
---------------------------------------
``seed.py`` fills countries, work calendars and tax rates only while each table
is empty, so a later release's additions never reach an install seeded before
it. The boot repairs in :mod:`app.modules.i18n_foundation.repairs` close part of
that gap automatically, and only the part they can prove safe without asking
anybody: a tax rate line or a calendar the install provably never received.
They do not touch countries at all, never change a field on a row that is
already there, and stay silent on an install whose seed date they cannot read.

This module is the other half, and it is explicit: an administrator previews
the difference (``GET`` in the router, ``update-reference-data`` on the CLI)
and confirms it (``POST``, ``--apply``). Principle 7, the human confirms. A
confirmation widens what may be written, it does not widen it to everything.

The rule
--------
Identity. A country is its ``iso_code``, a calendar its ``(country_code,
year)``, a tax row its ``(country_code, tax_code, effective_from)``, grouped
into rate lines by ``(country_code, tax_code)``. Every row whose identity is
not in the shipped files is the deployment's own and is never read for change,
never updated and never deleted. Nothing in this module deletes anything.

Additions. A shipped row whose identity is absent is offered, unless a delivery
ledger says it was handed to this database before (by this pass or by a boot
repair), in which case somebody removed it and it is listed as kept rather than
put back. A whole absent tax line also has to pass the boot reconciler's own
jurisdiction and tier guard
(:func:`~app.modules.i18n_foundation.tax_seed_reconcile.jurisdiction_refusal`),
so a line is never added beside a rate the deployment typed in for the same
slot. Every delivery is recorded in the boot repairs' ledgers as well as this
one, so a row added here and later deleted is not brought back at the next boot.

Updates. A shipped row whose identity is on file but whose values differ is
updated only if it is unedited, and only in fields that change no amount
already computed from it:

* names, translations, codes and defaults on countries; every shipped field on
  a calendar;
* ``tax_name`` and ``tax_name_translations`` on a tax row;
* ``effective_to`` going from open to a date on a tax row, and only together
  with the windows the shipped file adds after it, so the line's periods never
  overlap. That is the close-and-add the ``superseded`` repairs do.

A tax row whose shipped ``rate_pct``, ``tax_type``, ``combination``,
``subdivision_code`` or ``is_default`` differs, or whose ``effective_to`` would
move from one date to another, is listed for a person and never written: a rate
rewritten in place reprices every document already issued at it, and no
confirmation button changes that. The whole line is held with it, and so is a
line whose projected periods would overlap.

Edited. A row counts as edited by the deployment when its values no longer
match the fingerprint this pass stored in ``metadata["reference_sync"]`` the
last time it wrote the row, or, for a row this pass never wrote, when its
``updated_at`` is more than a second after its ``created_at``. The seeder and
the boot repairs write ``created_at`` and ``updated_at`` together, and every
update through the API moves ``updated_at``.

The miss that rule makes, stated rather than hidden: a boot repair that updated
a shipped row in place (the Canadian and US subdivision and federal scope
labels, Romania's and Nova Scotia's closed windows, Saudi Arabia's calendar
week) moved its ``updated_at`` too, so those rows read as edited and any later
change to them in the shipped file is shown as kept rather than applied. That
errs towards leaving data alone, which is the direction every uncertainty here
resolves to.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_repairs import delivered_keys, record_deliveries
from app.modules.i18n_foundation import tax_history_backfill, tax_seed_reconcile, work_calendar_seed_reconcile
from app.modules.i18n_foundation.models import Country, TaxConfiguration, WorkCalendar
from app.modules.i18n_foundation.seed import (
    country_from_seed_row,
    load_country_seed_rows,
    load_tax_seed_rows,
    load_work_calendar_seed_rows,
    tax_configuration_from_seed_row,
    work_calendar_from_seed_row,
)
from app.modules.i18n_foundation.tax_rules import TaxRateRow, row_from_orm

logger = logging.getLogger(__name__)

#: The ledger id this pass records its own deliveries under. Permanent, like
#: every delivery key: renaming it would forget what was handed over.
REPAIR_ID: Final = "reference_data_update"

#: Where the fingerprint of the last values this pass wrote is kept on a row.
SYNC_KEY: Final = "reference_sync"

#: How far apart ``created_at`` and ``updated_at`` may be on a row nobody has
#: edited. Both come from separate clock reads in one flush.
EDIT_TOLERANCE: Final = timedelta(seconds=1)

COUNTRY_FIELDS: Final = (
    "iso_code_3",
    "name_en",
    "name_translations",
    "currency_default",
    "measurement_default",
    "phone_code",
    "region_group",
)
CALENDAR_FIELDS: Final = ("name", "name_translations", "work_hours_per_day", "work_days", "exceptions")
TAX_DESCRIPTIVE_FIELDS: Final = ("tax_name", "tax_name_translations")
#: Tax fields that decide an amount. A difference here is shown, never written.
TAX_STRUCTURAL_FIELDS: Final = ("rate_pct", "tax_type", "combination", "subdivision_code", "is_default")
TAX_FIELDS: Final = (*TAX_DESCRIPTIVE_FIELDS, *TAX_STRUCTURAL_FIELDS, "effective_to")

#: Fields compared as numbers, so "19" and "19.0" are one value.
_NUMERIC_FIELDS: Final = frozenset({"rate_pct", "work_hours_per_day"})

ChangeKind = Literal["country", "calendar", "tax"]
ChangeAction = Literal["add", "update", "none"]
ChangeStatus = Literal["ready", "kept", "review"]

_OPEN_START: Final = "0000-00-00"
_OPEN_END: Final = "9999-99-99"


@dataclass
class FieldChange:
    """One field that differs between the database and the shipped file."""

    field: str
    before: Any
    after: Any


@dataclass
class ReferenceChange:
    """One entry of the preview.

    ``status`` is ``ready`` (applied on confirmation), ``kept`` (the
    deployment's version stays, nothing to decide) or ``review`` (shown for a
    person to settle by hand, never written here). ``reason`` is a stable code
    the UI translates; ``detail`` is an English explanation for logs and the CLI.
    """

    key: str
    kind: ChangeKind
    action: ChangeAction
    status: ChangeStatus
    reason: str
    label: str
    detail: str = ""
    rows_added: int = 0
    fields: list[FieldChange] = field(default_factory=list)
    _adds: list[Any] = field(default_factory=list, repr=False)
    _updates: list[tuple[Any, dict[str, Any], Sequence[str]]] = field(default_factory=list, repr=False)
    _deliveries: list[tuple[str, str]] = field(default_factory=list, repr=False)


@dataclass
class ReferenceDiff:
    """The whole preview."""

    changes: list[ReferenceChange]

    def count(self, status: str) -> int:
        """How many entries carry ``status``."""
        return sum(1 for change in self.changes if change.status == status)


@dataclass
class ReferenceApplyResult:
    """What an apply wrote, and the preview as it reads afterwards."""

    applied: list[str]
    skipped: list[str]
    rows_added: int
    rows_updated: int
    after: ReferenceDiff


# ── Comparison helpers ──────────────────────────────────────────────────────


def _same(field_name: str, left: Any, right: Any) -> bool:
    if field_name in _NUMERIC_FIELDS and left is not None and right is not None:
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except (InvalidOperation, ValueError):
            return str(left) == str(right)
    return left == right


def _canonical(field_name: str, value: Any) -> Any:
    if field_name in _NUMERIC_FIELDS and value is not None:
        try:
            return str(Decimal(str(value)).normalize())
        except (InvalidOperation, ValueError):
            return str(value)
    return value


def _fingerprint(row: Any, fields: Sequence[str]) -> str:
    payload = {name: _canonical(name, getattr(row, name)) for name in fields}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _is_edited(row: Any, fields: Sequence[str]) -> bool:
    """Whether the deployment has changed this row since it was written. See the module docstring."""
    stored = (row.metadata_ or {}).get(SYNC_KEY) if isinstance(row.metadata_, dict) else None
    if isinstance(stored, str) and stored:
        return stored != _fingerprint(row, fields)
    created, updated = row.created_at, row.updated_at
    if created is None or updated is None:
        return False
    if (created.tzinfo is None) != (updated.tzinfo is None):
        created, updated = created.replace(tzinfo=None), updated.replace(tzinfo=None)
    return updated - created > EDIT_TOLERANCE


def _diff(existing: Any, target: Any, fields: Iterable[str]) -> list[FieldChange]:
    return [
        FieldChange(name, getattr(existing, name), getattr(target, name))
        for name in fields
        if not _same(name, getattr(existing, name), getattr(target, name))
    ]


def _stamp(row: Any, fields: Sequence[str]) -> None:
    """Record the values this pass just wrote, so a later edit can be told apart."""
    meta = dict(row.metadata_) if isinstance(row.metadata_, dict) else {}
    meta[SYNC_KEY] = _fingerprint(row, fields)
    row.metadata_ = meta


# ── Countries and calendars ─────────────────────────────────────────────────


async def _country_changes(session: AsyncSession, ours: frozenset[str]) -> list[ReferenceChange]:
    on_file = {
        c.iso_code.upper(): c
        for c in (await session.execute(select(Country).execution_options(populate_existing=True))).scalars().all()
    }
    changes: list[ReferenceChange] = []
    for row in load_country_seed_rows():
        target = country_from_seed_row(row)
        iso = target.iso_code.upper()
        key = f"country:{iso}"
        label = f"{iso} {target.name_en}"
        existing = on_file.get(iso)
        if existing is None:
            if key in ours:
                changes.append(ReferenceChange(key, "country", "none", "kept", "removed_here", label))
                continue
            changes.append(
                ReferenceChange(
                    key,
                    "country",
                    "add",
                    "ready",
                    "new",
                    label,
                    rows_added=1,
                    _adds=[target],
                    _deliveries=[(REPAIR_ID, key)],
                )
            )
            continue
        diffs = _diff(existing, target, COUNTRY_FIELDS)
        if not diffs:
            continue
        if _is_edited(existing, COUNTRY_FIELDS):
            changes.append(ReferenceChange(key, "country", "none", "kept", "edited_locally", label, fields=diffs))
            continue
        updates = {d.field: d.after for d in diffs}
        changes.append(
            ReferenceChange(
                key,
                "country",
                "update",
                "ready",
                "fields_changed",
                label,
                fields=diffs,
                _updates=[(existing, updates, COUNTRY_FIELDS)],
            )
        )
    return changes


async def _calendar_changes(session: AsyncSession, ours: frozenset[str]) -> list[ReferenceChange]:
    boot = await delivered_keys(session, work_calendar_seed_reconcile.REPAIR_ID)
    on_file = {
        (c.country_code.upper(), str(c.year)): c
        for c in (await session.execute(select(WorkCalendar).execution_options(populate_existing=True))).scalars().all()
    }
    changes: list[ReferenceChange] = []
    for row in load_work_calendar_seed_rows():
        target = work_calendar_from_seed_row(row)
        slot = (target.country_code.upper(), str(target.year))
        key = f"calendar:{slot[0]}/{slot[1]}"
        boot_key = work_calendar_seed_reconcile.delivery_key(slot)
        label = f"{slot[0]} {slot[1]} {target.name}"
        existing = on_file.get(slot)
        if existing is None:
            if key in ours or boot_key in boot:
                changes.append(ReferenceChange(key, "calendar", "none", "kept", "removed_here", label))
                continue
            changes.append(
                ReferenceChange(
                    key,
                    "calendar",
                    "add",
                    "ready",
                    "new",
                    label,
                    rows_added=1,
                    _adds=[target],
                    _deliveries=[(REPAIR_ID, key), (work_calendar_seed_reconcile.REPAIR_ID, boot_key)],
                )
            )
            continue
        diffs = _diff(existing, target, CALENDAR_FIELDS)
        if not diffs:
            continue
        if _is_edited(existing, CALENDAR_FIELDS):
            changes.append(ReferenceChange(key, "calendar", "none", "kept", "edited_locally", label, fields=diffs))
            continue
        changes.append(
            ReferenceChange(
                key,
                "calendar",
                "update",
                "ready",
                "fields_changed",
                label,
                fields=diffs,
                _updates=[(existing, {d.field: d.after for d in diffs}, CALENDAR_FIELDS)],
            )
        )
    return changes


# ── Tax rate lines ──────────────────────────────────────────────────────────


def _window(start: str | None, end: str | None) -> tuple[str, str]:
    return (start or _OPEN_START, end or _OPEN_END)


def _overlaps(windows: Sequence[tuple[str, str]]) -> bool:
    ordered = sorted(windows)
    return any(ordered[i + 1][0] <= ordered[i][1] for i in range(len(ordered) - 1))


def _window_key(country: str, code: str, start: str | None) -> str:
    return f"tax:{country}/{code}@{start or '-'}"


async def _tax_changes(session: AsyncSession, ours: frozenset[str]) -> list[ReferenceChange]:
    line_ledger = await delivered_keys(session, tax_seed_reconcile.REPAIR_ID)
    window_ledger = await delivered_keys(session, tax_history_backfill.REPAIR_ID)
    configs = list(
        (await session.execute(select(TaxConfiguration).execution_options(populate_existing=True))).scalars().all()
    )

    held_by_line: dict[tuple[str, str], list[TaxConfiguration]] = {}
    for config in configs:
        if config.tax_code is not None:
            held_by_line.setdefault((config.country_code.upper(), config.tax_code), []).append(config)
    projected: list[TaxRateRow] = [row_from_orm(config) for config in configs]

    shipped: dict[tuple[str, str], list[dict]] = {}
    for row in load_tax_seed_rows():
        shipped.setdefault((row["country_code"].upper(), row["tax_code"]), []).append(row)

    changes: list[ReferenceChange] = []
    for (country, code), seed_rows in shipped.items():
        key = f"tax:{country}/{code}"
        targets = [tax_configuration_from_seed_row(row) for row in seed_rows]
        label = f"{country} {code} {targets[0].tax_name}"
        held = held_by_line.get((country, code), [])

        if not held:
            line_key = tax_seed_reconcile.delivery_key((country, code))
            if key in ours or line_key in line_ledger:
                changes.append(ReferenceChange(key, "tax", "none", "kept", "removed_here", label))
                continue
            planned = [row_from_orm(target) for target in targets]
            refusal = tax_seed_reconcile.jurisdiction_refusal(projected, planned, country)
            if refusal:
                changes.append(ReferenceChange(key, "tax", "none", "review", "jurisdiction", label, detail=refusal))
                continue
            deliveries = [(REPAIR_ID, key), (tax_seed_reconcile.REPAIR_ID, line_key)]
            deliveries += [
                (tax_history_backfill.REPAIR_ID, tax_history_backfill.delivery_key((country, code, t.effective_from)))
                for t in targets
                if t.effective_from
            ]
            changes.append(
                ReferenceChange(
                    key,
                    "tax",
                    "add",
                    "ready",
                    "new",
                    label,
                    rows_added=len(targets),
                    fields=[FieldChange("rate_pct", None, t.rate_pct) for t in targets],
                    _adds=targets,
                    _deliveries=deliveries,
                )
            )
            projected.extend(planned)
            continue

        changes.extend(_line_changes(country, code, key, label, targets, held, ours, window_ledger))
    return changes


def _line_changes(
    country: str,
    code: str,
    key: str,
    label: str,
    targets: list[TaxConfiguration],
    held: list[TaxConfiguration],
    ours: frozenset[str],
    window_ledger: frozenset[str],
) -> list[ReferenceChange]:
    """The change for a rate line this database already holds at least one window of."""
    by_start: dict[str | None, list[TaxConfiguration]] = {}
    for row in held:
        by_start.setdefault(row.effective_from, []).append(row)

    adds: list[TaxConfiguration] = []
    updates: list[tuple[Any, dict[str, Any], Sequence[str]]] = []
    shown: list[FieldChange] = []
    kept_fields: list[FieldChange] = []
    removed = False
    review_reason = ""
    review_fields: list[FieldChange] = []
    closes = False
    new_end: dict[int, str | None] = {}

    for target in targets:
        matches = by_start.get(target.effective_from, [])
        if not matches:
            history_key = tax_history_backfill.delivery_key((country, code, target.effective_from))
            if _window_key(country, code, target.effective_from) in ours or (
                target.effective_from and history_key in window_ledger
            ):
                removed = True
                continue
            adds.append(target)
            continue
        if len(matches) > 1:
            review_reason = review_reason or "field_conflict"
            continue
        existing = matches[0]
        structural = _diff(existing, target, TAX_STRUCTURAL_FIELDS)
        if structural:
            review_fields.extend(structural)
            rate_moved = any(change.field == "rate_pct" for change in structural)
            review_reason = "rate_differs" if rate_moved else (review_reason or "field_conflict")
            continue
        edited = _is_edited(existing, TAX_FIELDS)
        row_updates: dict[str, Any] = {}
        if existing.effective_to != target.effective_to:
            change = FieldChange("effective_to", existing.effective_to, target.effective_to)
            if existing.effective_to is not None:
                review_fields.append(change)
                review_reason = review_reason or "field_conflict"
                continue
            if edited:
                kept_fields.append(change)
            else:
                row_updates["effective_to"] = target.effective_to
                new_end[id(existing)] = target.effective_to
                shown.append(change)
                closes = True
        descriptive = _diff(existing, target, TAX_DESCRIPTIVE_FIELDS)
        if descriptive:
            if edited:
                kept_fields.extend(descriptive)
            else:
                row_updates.update({d.field: d.after for d in descriptive})
                shown.extend(descriptive)
        if row_updates:
            updates.append((existing, row_updates, TAX_FIELDS))

    if review_reason:
        return [
            ReferenceChange(
                key,
                "tax",
                "none",
                "review",
                review_reason,
                label,
                detail="the shipped file disagrees with this database on a value that decides an amount",
                fields=review_fields,
            )
        ]

    windows = [_window(row.effective_from, new_end.get(id(row), row.effective_to)) for row in held]
    windows += [_window(target.effective_from, target.effective_to) for target in adds]
    if (adds or closes) and _overlaps(windows):
        return [
            ReferenceChange(
                key,
                "tax",
                "none",
                "review",
                "overlap",
                label,
                detail="the shipped periods would overlap a period this database holds",
                fields=[FieldChange("effective_from", None, t.effective_from) for t in adds],
            )
        ]

    out: list[ReferenceChange] = []
    if adds or updates:
        deliveries = [(REPAIR_ID, _window_key(country, code, t.effective_from)) for t in adds]
        deliveries += [
            (tax_history_backfill.REPAIR_ID, tax_history_backfill.delivery_key((country, code, t.effective_from)))
            for t in adds
            if t.effective_from
        ]
        out.append(
            ReferenceChange(
                key,
                "tax",
                "add" if adds else "update",
                "ready",
                "new_period" if (adds or closes) else "fields_changed",
                label,
                rows_added=len(adds),
                fields=[*shown, *(FieldChange("rate_pct", None, t.rate_pct) for t in adds)],
                _adds=adds,
                _updates=updates,
                _deliveries=deliveries,
            )
        )
    if kept_fields:
        out.append(ReferenceChange(f"{key}#edited", "tax", "none", "kept", "edited_locally", label, fields=kept_fields))
    if removed:
        out.append(ReferenceChange(f"{key}#removed", "tax", "none", "kept", "removed_here", label))
    return out


# ── Entry points ────────────────────────────────────────────────────────────


async def compute_reference_diff(session: AsyncSession) -> ReferenceDiff:
    """Compare the shipped seed files with this database. Writes nothing.

    Args:
        session: An open session.

    Returns:
        Every difference, each marked ``ready``, ``kept`` or ``review``.
    """
    ours = await delivered_keys(session, REPAIR_ID)
    changes = [
        *await _country_changes(session, ours),
        *await _calendar_changes(session, ours),
        *await _tax_changes(session, ours),
    ]
    return ReferenceDiff(changes=changes)


async def apply_reference_update(session: AsyncSession, keys: Iterable[str] | None) -> ReferenceApplyResult:
    """Write the ``ready`` changes the caller confirmed.

    The difference is computed again here rather than trusted from the preview,
    so a key the caller saw as ready but that is no longer ready (somebody
    edited the row in between) is skipped rather than written.

    Args:
        session: An open session. The caller commits.
        keys: The preview keys the administrator confirmed, or None for every
            ready change (the CLI's ``--apply``).

    Returns:
        What was applied and skipped, row counts, and the preview afterwards.
    """
    # These small reference tables are written rarely. A table lock also
    # protects absent identities: row locks and an Apply-only advisory lock
    # cannot stop an ordinary API request inserting a custom tax rate between
    # the jurisdiction check and our INSERT. Readers remain unblocked.
    # Refresh ORM identities only AFTER waiting for earlier writers to commit.
    async with session.begin_nested():
        await session.execute(
            text("LOCK TABLE oe_i18n_country, oe_i18n_work_calendar, oe_i18n_tax_config IN SHARE ROW EXCLUSIVE MODE")
        )
        return await _apply_reference_update_locked(session, keys)


async def _apply_reference_update_locked(session: AsyncSession, keys: Iterable[str] | None) -> ReferenceApplyResult:
    diff = await compute_reference_diff(session)
    ready = {change.key: change for change in diff.changes if change.status == "ready"}
    wanted = list(ready) if keys is None else list(dict.fromkeys(keys))

    applied: list[str] = []
    skipped: list[str] = []
    rows_added = 0
    rows_updated = 0
    deliveries: dict[str, list[str]] = {}
    for key in wanted:
        change = ready.get(key)
        if change is None:
            skipped.append(key)
            continue
        fields = {"country": COUNTRY_FIELDS, "calendar": CALENDAR_FIELDS, "tax": TAX_FIELDS}[change.kind]
        for obj in change._adds:
            _stamp(obj, fields)
            session.add(obj)
            rows_added += 1
        for obj, values, obj_fields in change._updates:
            for name, value in values.items():
                setattr(obj, name, value)
            _stamp(obj, obj_fields)
            rows_updated += 1
        for repair_id, delivery in change._deliveries:
            deliveries.setdefault(repair_id, []).append(delivery)
        applied.append(key)

    if applied:
        await session.flush()
        for repair_id, keys_for_repair in deliveries.items():
            await record_deliveries(session, repair_id, keys_for_repair)
        logger.info(
            "Reference data update: applied %d change(s), %d row(s) added, %d updated (%s).",
            len(applied),
            rows_added,
            rows_updated,
            ", ".join(applied),
        )

    after = await compute_reference_diff(session)
    return ReferenceApplyResult(
        applied=applied, skipped=skipped, rows_added=rows_added, rows_updated=rows_updated, after=after
    )
