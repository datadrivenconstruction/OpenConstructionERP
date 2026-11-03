# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ Excel/CSV round-trip diff (GitHub #360).

Pure, dependency-free decision layer for a faithful export -> edit ->
re-import cycle. Given the rows parsed out of a previously exported (and
possibly hand-edited) spreadsheet, plus the set of position ids that
currently live in the *target* BOQ, it decides for every row whether it

* UPDATES an existing position in place (its id column still holds an id
  that belongs to this BOQ),
* CREATES a new position (the id column is blank - a row the user added),
* or carries a foreign / unknown / duplicate id, which is treated as a
  *new* row and flagged (never allowed to mutate a position outside this
  BOQ).

It also reports which of the BOQ's current positions were absent from the
sheet, so the route can (opt-in) delete them and can always tell the user
how many *would* be deleted.

The module is kept free of SQLAlchemy / FastAPI / Pydantic so it unit-tests
against plain data. The route layer feeds it a scoped id set (built solely
from ``list_all_for_boq(boq_id)``) which is the structural guarantee that a
cross-BOQ id can never be honoured as an update: only ids present in that
set are ever emitted as an ``update``.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

# Header label written into the dedicated identity column of every export,
# plus the set of header spellings the importer recognises as that column.
# Keep the label stable - a downstream export/import must agree on it.
ID_COLUMN_HEADER = "Position ID"
ID_COLUMN_ALIASES: frozenset[str] = frozenset(
    {
        "position id",
        "position_id",
        "position-id",
        "id",
        "pos id",
        "pos. id",
        "uuid",
    }
)

# Optional export column holding ``Position.version`` at export time. A sheet
# without it (old export, hand-built) is never checked for stale rows.
ROW_VERSION_COLUMN_HEADER = "Row Version"
# Hidden sheet an export appends (boq_id, exported_at, schema).
EXPORT_META_SHEET = "_oe_meta"
ROW_VERSION_COLUMN_ALIASES: frozenset[str] = frozenset({"row version", "row_version", "row-version"})


def normalise_id(raw: Any) -> str | None:
    """Canonicalise an id cell to a comparable token, or ``None`` if blank.

    Strips whitespace and lowercases so a copy-pasted / re-cased id still
    matches. Returns ``None`` for a blank / empty cell (a brand-new row).

    Deliberately does NOT validate UUID shape: a non-empty but
    unrecognisable value is returned as-is (lowered) so the differ can flag
    it and treat it as a new row. It will not be present in the current-BOQ
    id set, so it can never update anything.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text.lower()


def is_formula_id(raw: Any) -> bool:
    """True when an id cell would run as a spreadsheet formula (``= + - @``, tab, CR).

    Uses the same trigger set as the export-side neutraliser. A genuine
    position id is a UUID and can never start with one of these.
    """
    from app.core.csv_safety import neutralise_formula

    if not isinstance(raw, str):
        return False
    text = raw.lstrip(" ")
    return bool(text) and neutralise_formula(text) != text


@dataclass(slots=True, frozen=True)
class RoundTripRow:
    """One parsed spreadsheet row as seen by the differ.

    ``position_id`` is the RAW id-column value (may be blank, re-cased,
    malformed, or from another BOQ). ``row_index`` is the 1-based sheet row
    used only for user-facing messages. ``payload`` is the already-parsed
    field dict the route hands to the service; the differ never inspects it.
    """

    row_index: int
    position_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    # ``Position.version`` the sheet was exported at; ``None`` = not stamped.
    row_version: int | None = None


@dataclass(slots=True, frozen=True)
class RoundTripAction:
    """A resolved create/update decision for one sheet row."""

    kind: Literal["create", "update"]
    row: RoundTripRow
    # Target position id for ``kind == "update"`` (a normalised token that
    # equals ``str(uuid)``); ``None`` for ``kind == "create"``.
    position_id: str | None = None


@dataclass(slots=True)
class RoundTripPlan:
    """Full resolved plan for one re-import."""

    updates: list[RoundTripAction] = field(default_factory=list)
    creates: list[RoundTripAction] = field(default_factory=list)
    # Actionable deletes - populated only when ``delete_missing=True``.
    deletes: list[str] = field(default_factory=list)
    # Every current-BOQ id absent from the sheet, ALWAYS populated so the
    # route can report "N would be deleted" even with the flag off.
    would_delete: list[str] = field(default_factory=list)
    # Per-row advisories (unknown id -> new, duplicate id -> new, ...).
    problems: list[dict[str, Any]] = field(default_factory=list)
    # Normalised ids of ``updates`` whose row was exported at an older
    # ``Position.version`` than the one stored now AND that actually differ
    # from the stored values. Applied only on explicit consent.
    stale_ids: set[str] = field(default_factory=set)

    @property
    def counts(self) -> dict[str, int]:
        """Headline counts for the import summary."""
        return {
            "updated": len(self.updates),
            "created": len(self.creates),
            "deleted": len(self.deletes),
            "would_delete": len(self.would_delete),
            "problems": len(self.problems),
        }


@dataclass(slots=True, frozen=True)
class ApplyChoices:
    """What the person chose in the review step, as normalised id tokens.

    ``delete`` is ``None`` when the caller did not list ids (then the plain
    ``delete_missing`` flag decides); a list, even an empty one, means only
    those ids may be deleted.
    """

    accept: frozenset[str] = frozenset()
    skip: frozenset[str] = frozenset()
    delete: frozenset[str] | None = None
    overwrite_conflicts: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "accept": sorted(self.accept),
            "skip": sorted(self.skip),
            "delete": None if self.delete is None else sorted(self.delete),
            "overwrite_conflicts": self.overwrite_conflicts,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any] | None) -> ApplyChoices | None:
        if not data:
            return None
        delete = data.get("delete")
        return cls(
            accept=frozenset(data.get("accept") or ()),
            skip=frozenset(data.get("skip") or ()),
            delete=None if delete is None else frozenset(delete),
            overwrite_conflicts=bool(data.get("overwrite_conflicts")),
        )


@dataclass(slots=True, frozen=True)
class FieldChange:
    """One human-facing field whose sheet value differs from the stored one."""

    field: str
    old: Any
    new: Any

    def as_dict(self) -> dict[str, Any]:
        return {"field": self.field, "old": self.old, "new": self.new}


_QUANT = Decimal("0.0001")


def _dec4(value: Any) -> Decimal | None:
    """Quantise a numeric-ish value to 4 dp (the storage precision); ``None`` if unparsable."""
    try:
        d = Decimal(str(value).strip() or "0")
        if not d.is_finite():
            return None
        return d.quantize(_QUANT)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _text(value: Any) -> str:
    """Trimmed NFC text; ``None`` is empty."""
    return unicodedata.normalize("NFC", str(value or "")).strip()


def _attr(stored: Any, name: str) -> Any:
    if isinstance(stored, Mapping):
        return stored.get(name)
    return getattr(stored, name, None)


def _num_out(value: Decimal) -> str:
    """Plain trailing-zero-free string for a Decimal (display and JSON safe)."""
    return format(value.normalize(), "f")


def field_changes(
    stored: Any,
    payload: Mapping[str, Any],
    *,
    code_of: Callable[[Mapping[str, Any]], str] | None = None,
) -> list[FieldChange]:
    """Fields of ``payload`` (a prepared sheet row) that differ from ``stored``.

    The single source of truth for "does this row change the position": the
    apply step builds its update from exactly these changes, so a row listed
    as unchanged in a preview is never written by the apply. Rules:

    * text is trimmed and NFC-normalised; unit is compared case-insensitively;
    * a blank unit / ordinal / classification cell never clears the stored
      value (a missing cell is not an edit);
    * numbers are compared as Decimals at the 4 dp storage precision;
    * ``stored is None`` reports every field as changed.

    Args:
        stored: The stored position (object or mapping).
        payload: The prepared row (description, unit, ordinal, quantity,
            unit_rate, classification).
        code_of: Reads the displayed classification code out of a stored
            classification dict. Defaults to the ``code`` key.
    """
    out: list[FieldChange] = []

    new_desc = _text(payload.get("description"))
    old_desc = _text(_attr(stored, "description")) if stored is not None else ""
    if stored is None or new_desc != old_desc:
        out.append(FieldChange("description", old_desc, new_desc))

    new_unit = _text(payload.get("unit"))
    old_unit = _text(_attr(stored, "unit")) if stored is not None else ""
    if new_unit and (stored is None or new_unit.lower() != old_unit.lower()):
        out.append(FieldChange("unit", old_unit, new_unit))

    new_ord = _text(payload.get("ordinal"))
    old_ord = _text(_attr(stored, "ordinal")) if stored is not None else ""
    if new_ord and (stored is None or new_ord != old_ord):
        out.append(FieldChange("ordinal", old_ord, new_ord))

    new_qty = _dec4(payload.get("quantity", 0.0))
    old_qty = _dec4(_attr(stored, "quantity") if stored is not None else 0)
    if new_qty is not None and (stored is None or new_qty != old_qty):
        out.append(FieldChange("quantity", None if old_qty is None else _num_out(old_qty), _num_out(new_qty)))

    new_rate = _dec4(payload.get("unit_rate", 0))
    old_rate = _dec4(_attr(stored, "unit_rate") if stored is not None else 0)
    if new_rate is not None and (stored is None or new_rate != old_rate):
        out.append(FieldChange("unit_rate", None if old_rate is None else _num_out(old_rate), _num_out(new_rate)))

    new_cls = payload.get("classification") or {}
    new_code = _text(new_cls.get("code") if isinstance(new_cls, Mapping) else "")
    if new_code:
        old_cls = (_attr(stored, "classification") if stored is not None else None) or {}
        reader = code_of or (lambda c: str(c.get("code", "") or ""))
        old_code = _text(reader(old_cls)) if isinstance(old_cls, Mapping) else ""
        if new_code != old_code:
            out.append(FieldChange("classification", old_code, new_code))

    return out


def conflict(stored_version: int | None, row_version: int | None) -> bool:
    """True when the sheet was exported at another row version than the stored one.

    A row without a stamped version (``None``) is never a conflict.
    """
    if row_version is None or stored_version is None:
        return False
    return int(row_version) != int(stored_version)


def parse_row_version(raw: Any) -> int | None:
    """Row-version cell to a non-negative int, or ``None`` when blank or unreadable."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        text = str(raw).strip()
        if not text:
            return None
        value = int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None
    return value if value >= 0 else None


def diff_import_rows(
    rows: Iterable[RoundTripRow],
    current_position_ids: Iterable[str],
    *,
    delete_missing: bool = False,
    stored_versions: Mapping[str, int] | None = None,
    stored: Mapping[str, Any] | None = None,
    code_of: Callable[[Mapping[str, Any]], str] | None = None,
) -> RoundTripPlan:
    """Resolve one re-import into create / update / delete actions.

    Args:
        rows: The parsed spreadsheet rows. Order is preserved but matching is
            purely by id, so reordering the sheet never changes the outcome.
        current_position_ids: ``str(id)`` of every position that currently
            belongs to the TARGET BOQ, and only that BOQ. This scoping is the
            guarantee that a foreign id can never update another BOQ.
        delete_missing: When ``True``, current positions not referenced by any
            row are queued for deletion; otherwise they are only reported via
            ``would_delete``.
        stored_versions: ``id -> Position.version`` now. With it, an update
            whose row carries another ``row_version`` is flagged
            ``stale_row`` (an error problem) and listed in ``stale_ids``.
        stored: ``id -> stored position``. When given, a stale row whose
            values equal the stored ones is not a conflict (nothing to lose).
        code_of: Classification-code reader, see :func:`field_changes`.

    Returns:
        A :class:`RoundTripPlan`. Guarantees:

        * a row becomes an UPDATE only when its normalised id is present in
          ``current_position_ids``;
        * each current id is the update target of at most ONE row (any later
          duplicate is flagged and demoted to a create);
        * ``updates`` and ``creates`` together cover every input row exactly
          once.
    """
    current: set[str] = set()
    for cid in current_position_ids:
        token = normalise_id(cid)
        if token is not None:
            current.add(token)

    plan = RoundTripPlan()
    consumed: set[str] = set()

    for row in rows:
        token = normalise_id(row.position_id)
        if token is None:
            # Blank id -> a row the user added in Excel. Plain create.
            plan.creates.append(RoundTripAction(kind="create", row=row))
            continue
        if token not in current:
            # An id that does not belong to THIS BOQ: a stale paste, an id
            # from another BOQ / project, or garbage. NEVER update across the
            # boundary - import as a new row and flag it.
            plan.creates.append(RoundTripAction(kind="create", row=row))
            plan.problems.append(
                {
                    "row": row.row_index,
                    "position_id": str(row.position_id),
                    "severity": "warning",
                    "issue": "unknown_id",
                    "message": (
                        "Row carries an id that is not in this BOQ; imported as "
                        "a NEW position (an id from another BOQ can never "
                        "overwrite one here)."
                    ),
                }
            )
            continue
        if token in consumed:
            # A second row claims an id already matched above. Updating twice
            # would be silent last-write-wins; demote the duplicate to a new
            # row and flag it.
            plan.creates.append(RoundTripAction(kind="create", row=row))
            plan.problems.append(
                {
                    "row": row.row_index,
                    "position_id": str(row.position_id),
                    "severity": "warning",
                    "issue": "duplicate_id",
                    "message": (
                        "The same position id appears on more than one row; the "
                        "first updates in place, this one is imported as a NEW "
                        "position."
                    ),
                }
            )
            continue
        consumed.add(token)
        plan.updates.append(RoundTripAction(kind="update", row=row, position_id=token))
        if stored_versions is not None and conflict(stored_versions.get(token), row.row_version):
            if stored is not None and not field_changes(stored.get(token), row.payload, code_of=code_of):
                continue
            plan.stale_ids.add(token)
            plan.problems.append(
                {
                    "row": row.row_index,
                    "position_id": str(row.position_id),
                    "severity": "error",
                    "issue": "stale_row",
                    "message": (
                        "This position changed in the app after the sheet was exported "
                        f"(version {stored_versions.get(token)}, sheet {row.row_version}); "
                        "it is not overwritten unless you choose the Excel value."
                    ),
                }
            )

    # Deterministic order so reporting / tests are stable.
    missing = sorted(token for token in current if token not in consumed)
    plan.would_delete = missing
    if delete_missing:
        plan.deletes = list(missing)

    return plan
