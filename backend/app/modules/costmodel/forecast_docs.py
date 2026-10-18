# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Forecast documentation: when a move needs evidence, how snapshots compare.

A monthly forecast is only as good as the reasons behind its moves. A line
whose forecast moved by more than the project's threshold since the last
frozen snapshot needs a comment and at least one piece of evidence (a
document, the minutes of a meeting) before the snapshot can be frozen.

Two readings compare snapshots. The matrix puts several snapshots side by side,
one column each. The delta ladder walks from the previous total to the current
one line by line, largest move first, with the cause of each step (a new line,
a changed method, a more mature source, the same source moving) and the
comment and evidence recorded for it, so the total's movement is explained to
the cent.

Pure, like :mod:`app.modules.costmodel.cost_control`: snapshot rows in (the
dicts a snapshot stores, money as decimal strings), plain values out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
CENT = Decimal("0.01")
PCT = Decimal("0.1")

#: Why a line moved between two snapshots, checked in this order.
CAUSE_NEW = "new"
CAUSE_REMOVED = "removed"
CAUSE_METHOD = "method"
CAUSE_SOURCE = "source"
CAUSE_VALUE = "value"

LADDER_CAUSES: tuple[str, ...] = (CAUSE_NEW, CAUSE_REMOVED, CAUSE_METHOD, CAUSE_SOURCE, CAUSE_VALUE)

#: Kinds of evidence a snapshot line can point at.
EVIDENCE_DOCUMENT = "document"
EVIDENCE_MINUTES = "minutes"
EVIDENCE_OTHER = "other"
EVIDENCE_KINDS: tuple[str, ...] = (EVIDENCE_DOCUMENT, EVIDENCE_MINUTES, EVIDENCE_OTHER)

#: Shortest comment that reads as a reason rather than a placeholder.
MIN_COMMENT = 3

#: The method a row without one was read with (snapshots older than forecast methods).
DEFAULT_METHOD = "best_available"

#: The threshold a new project starts with: a move above 10 % needs evidence.
DEFAULT_THRESHOLD_PCT = Decimal("10")


def money(raw: object) -> Decimal:
    """A stored amount as a Decimal; anything unreadable is zero."""
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return ZERO
    return value if value.is_finite() else ZERO


@dataclass(frozen=True, slots=True)
class EvidenceThreshold:
    """Above which move a line needs evidence.

    ``amount`` is in the project currency, ``pct`` a percentage of the previous
    forecast. A zero (or ``None``) leaves that test out; when both are set a
    move must exceed both, so a small line does not need minutes for a few
    hundred and a large line does not hide a large amount behind a small
    percentage. With neither set every move needs a word.
    """

    amount: Decimal = ZERO
    pct: Decimal | None = DEFAULT_THRESHOLD_PCT


def needs_evidence(previous: Decimal | None, current: Decimal, threshold: EvidenceThreshold) -> bool:
    """Whether a move from ``previous`` (``None`` for a new line) to ``current`` needs evidence."""
    delta = abs(current - (previous or ZERO))
    if delta <= CENT:
        return False
    use_amount = threshold.amount > ZERO
    use_pct = threshold.pct is not None and threshold.pct > ZERO
    if not use_amount and not use_pct:
        return True
    if use_amount and delta <= threshold.amount:
        return False
    # A line out of nothing has no percentage: the percentage test cannot excuse it.
    if use_pct and previous is not None and previous != ZERO:
        return delta / abs(previous) * Decimal("100") > (threshold.pct or ZERO)
    return True


def _evidence_present(item: object) -> bool:
    if not isinstance(item, Mapping):
        return False
    return bool(str(item.get("ref") or "").strip() or str(item.get("document_id") or "").strip())


def note_complete(comment: str | None, evidence: Sequence[object] | None) -> bool:
    """A comment that reads as a reason and at least one piece of evidence."""
    return len((comment or "").strip()) >= MIN_COMMENT and any(_evidence_present(e) for e in evidence or [])


# ── The delta ladder ─────────────────────────────────────────────────────


@dataclass(slots=True)
class LadderStep:
    """One line's move between two snapshots."""

    key: str
    code: str
    description: str
    kind: str
    before: Decimal | None
    after: Decimal | None
    delta: Decimal
    cause: str
    source_before: str = ""
    source_after: str = ""
    method_before: str = ""
    method_after: str = ""
    comment: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Ladder:
    """From ``start`` to ``end``: the steps, largest first, and what was gathered into ``other``."""

    start: Decimal
    end: Decimal
    steps: list[LadderStep]
    other: Decimal = ZERO
    other_count: int = 0


def _by_key(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(r.get("key")): r for r in rows if isinstance(r, Mapping) and r.get("key") is not None}


def _total(rows: Sequence[Mapping[str, Any]]) -> Decimal:
    return sum((money(r.get("forecast")) for r in rows if isinstance(r, Mapping)), ZERO)


def _cause(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> str:
    if before is None:
        return CAUSE_NEW
    if after is None:
        return CAUSE_REMOVED
    # A snapshot older than forecast methods was read with the best available source.
    if str(before.get("method") or DEFAULT_METHOD) != str(after.get("method") or DEFAULT_METHOD):
        return CAUSE_METHOD
    if str(before.get("source") or "") != str(after.get("source") or ""):
        return CAUSE_SOURCE
    return CAUSE_VALUE


def delta_ladder(
    before_rows: Sequence[Mapping[str, Any]],
    after_rows: Sequence[Mapping[str, Any]],
    notes: Mapping[str, tuple[str, list[dict[str, Any]]]],
    *,
    min_step: Decimal = ZERO,
    limit: int | None = None,
) -> Ladder:
    """Walk from the earlier snapshot's total to the later one's, one line at a time.

    Args:
        before_rows: The earlier snapshot's rows.
        after_rows: The later snapshot's rows (or today's report as rows).
        notes: Comment and evidence per row key, recorded on the later snapshot.
        min_step: Moves smaller than this (in absolute terms) are gathered into
            ``other`` so the ladder stays readable.
        limit: Keep at most this many steps; the rest goes into ``other``.

    The start plus every step plus ``other`` is the end, to the cent.
    """
    before = _by_key(before_rows)
    after = _by_key(after_rows)
    steps: list[LadderStep] = []
    for key in {*before, *after}:
        b = before.get(key)
        a = after.get(key)
        b_amount = money(b.get("forecast")) if b is not None else None
        a_amount = money(a.get("forecast")) if a is not None else None
        delta = (a_amount or ZERO) - (b_amount or ZERO)
        if abs(delta) < CENT:
            continue
        ref = a if a is not None else b
        assert ref is not None
        comment, evidence = notes.get(key, ("", []))
        steps.append(
            LadderStep(
                key=key,
                code=str(ref.get("code") or ""),
                description=str(ref.get("description") or ""),
                kind=str(ref.get("kind") or ""),
                before=b_amount,
                after=a_amount,
                delta=delta,
                cause=_cause(b, a),
                source_before=str(b.get("source") or "") if b is not None else "",
                source_after=str(a.get("source") or "") if a is not None else "",
                method_before=str(b.get("method") or "") if b is not None else "",
                method_after=str(a.get("method") or "") if a is not None else "",
                comment=comment,
                evidence=list(evidence),
            )
        )
    steps.sort(key=lambda s: (-abs(s.delta), s.code, s.key))
    kept: list[LadderStep] = []
    other = ZERO
    other_count = 0
    for step in steps:
        if abs(step.delta) < min_step or (limit is not None and len(kept) >= limit):
            other += step.delta
            other_count += 1
            continue
        kept.append(step)
    return Ladder(_total(before_rows), _total(after_rows), kept, other, other_count)


# ── The comparison matrix ────────────────────────────────────────────────

#: Rows that are not cost lines sort after the cost lines, in this order.
_SPECIAL_ORDER = ("allowance", "unassigned", "changes_without_contract")


@dataclass(slots=True)
class MatrixRow:
    """One line across the compared snapshots; ``None`` where a snapshot does not have it."""

    key: str
    code: str
    description: str
    kind: str
    values: list[Decimal | None]
    delta: Decimal
    delta_pct: Decimal | None


def comparison_matrix(snapshots: Sequence[Sequence[Mapping[str, Any]]]) -> tuple[list[Decimal], list[MatrixRow]]:
    """Totals per snapshot and one row per line across them, oldest snapshot first.

    ``delta`` is the last snapshot minus the first, a missing value read as
    nothing; ``delta_pct`` is that against the first, empty when the first has
    no figure.
    """
    indexed = [_by_key(rows) for rows in snapshots]
    keys: dict[str, Mapping[str, Any]] = {}
    for rows in indexed:
        for key, row in rows.items():
            keys[key] = row
    out: list[MatrixRow] = []
    for key, ref in keys.items():
        values = [money(rows[key].get("forecast")) if key in rows else None for rows in indexed]
        first = values[0] if values else None
        last = values[-1] if values else None
        delta = (last or ZERO) - (first or ZERO)
        pct = None
        if first not in (None, ZERO):
            assert first is not None
            pct = (delta / first * Decimal("100")).quantize(PCT)
        out.append(
            MatrixRow(
                key=key,
                code=str(ref.get("code") or ""),
                description=str(ref.get("description") or ""),
                kind=str(ref.get("kind") or ""),
                values=values,
                delta=delta,
                delta_pct=pct,
            )
        )

    def order(row: MatrixRow) -> tuple[int, str, str]:
        rank = _SPECIAL_ORDER.index(row.kind) + 1 if row.kind in _SPECIAL_ORDER else 0
        return (rank, row.code, row.key)

    out.sort(key=order)
    return [_total(rows) for rows in snapshots], out
