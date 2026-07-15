# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""E5.2 — Locked-figure guard (policy-as-code).

The commercial-trust heart of the module. Once a human confirms a
commercially-sensitive figure (a baseline date, quantified impact days,
entitlement, LDs-avoided, prolongation/acceleration cost), that figure is
*locked*: no later flow — a recompute, a single-store re-render, an apply
action — may silently change it. Every write path in the module funnels
through :class:`LockedFigureGuard` before it persists a value the guard knows
about, and rejects any change with a :class:`LockedFigureViolation`.

Design tenets:
    * **Pure & dependency-free.** The guard core takes an explicit set of
      locked entries and knows nothing about SQLAlchemy, FastAPI, or the DB.
      That is what makes the negative-injection suite exhaustive and fast —
      no fixture, no session. :meth:`LockedFigureGuard.from_rows` adapts ORM
      rows into it at the edge.
    * **Byte-identical, not approximately-equal.** Comparison is on a
      *canonical string* serialization (:func:`canonical_value`), so ``5``,
      ``5.0`` and ``"5"`` compare equal but ``5`` and ``5.01`` do not. Values
      are normalised the same way going in (at lock time) and coming back
      (at write time), so the check is stable across float/Decimal/str inputs.
    * **Idempotent re-writes pass.** Writing the *same* canonical value to a
      locked path is allowed — single-store re-renders (spec E4.3) re-emit the
      confirmed figure constantly and must not trip the guard. Only a *change*
      is a violation.
    * **Fail closed, explain loudly.** A violation names the path, the locked
      value, and the rejected value so the audit trail and the UI can show
      exactly what was blocked (spec P5 — never silent).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


def canonical_value(value: Any) -> str:
    """Serialize ``value`` to the canonical string used for lock comparison.

    The same function is applied at lock time and at every write, so two
    inputs that represent the same figure produce the same string regardless
    of their Python type:

        canonical_value(5) == canonical_value(5.0) == canonical_value("5")
        canonical_value(Decimal("12.50")) == canonical_value(12.5)

    Numbers are normalised through :class:`~decimal.Decimal` and stripped of
    trailing-zero noise; containers are JSON with sorted keys and tight
    separators; ``None`` is the literal ``"null"``. Anything else falls back
    to ``str()``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        # bool is an int subclass — handle before the numeric branch.
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return _canonical_number(value)
    if isinstance(value, str):
        # A numeric-looking string canonicalises as a number so "5" == 5;
        # a non-numeric string is used verbatim.
        stripped = value.strip()
        try:
            return _canonical_number(Decimal(stripped))
        except (InvalidOperation, ValueError):
            return value
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


def _canonical_number(value: int | float | Decimal) -> str:
    """Normalise a number to a stable decimal string (no trailing zeros)."""
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    # normalize() drops trailing zeros; the exponent guard turns e.g.
    # Decimal("5E+1") back into "50" instead of scientific notation, and
    # "0" stays "0" rather than "0E+…".
    normalized = dec.normalize()
    if normalized == 0:
        return "0"
    formatted = format(normalized, "f")
    return formatted


def _jsonable(value: Any) -> Any:
    """Recursively coerce a container into JSON-serialisable primitives."""
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return _canonical_number(value)
    return value


def value_hash(canonical: str) -> str:
    """SHA-256 of a canonical value — the tamper-detection / audit fingerprint."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LockedEntry:
    """One locked figure, addressed by its canonical ``path``.

    ``value`` is stored already-canonicalised so comparison is a plain string
    equality. Build entries via :meth:`for_value` (which canonicalises for you)
    rather than the constructor when starting from a raw value.
    """

    path: str
    value: str
    figure_type: str | None = None

    @classmethod
    def for_value(cls, path: str, value: Any, *, figure_type: str | None = None) -> LockedEntry:
        return cls(path=path, value=canonical_value(value), figure_type=figure_type)

    @property
    def value_hash(self) -> str:
        return value_hash(self.value)


class LockedFigureViolation(Exception):
    """Raised when a write would change a locked figure.

    Carries the structured fields the router maps to an HTTP 409 and the audit
    log records verbatim, so a blocked write is always explainable.
    """

    def __init__(self, path: str, locked_value: str, attempted_value: str) -> None:
        self.path = path
        self.locked_value = locked_value
        self.attempted_value = attempted_value
        super().__init__(
            f"Locked figure {path!r} may not change: locked={locked_value!r} attempted={attempted_value!r}"
        )


class LockedFigureGuard:
    """Enforces that locked figures never change from any write flow.

    Construct with the set of currently-locked entries (from the DB via
    :meth:`from_rows`, or inline in tests), then gate every write through
    :meth:`assert_writable` / :meth:`assert_batch_writable`. After an apply,
    call :meth:`verify_unchanged` to prove the persisted figure still equals
    its locked value byte-for-byte (spec E4.3-AC4).
    """

    def __init__(self, entries: Iterable[LockedEntry] = ()) -> None:
        self._by_path: dict[str, LockedEntry] = {}
        for entry in entries:
            self._by_path[entry.path] = entry

    @classmethod
    def from_rows(cls, rows: Iterable[Any]) -> LockedFigureGuard:
        """Build a guard from ``LockedFigure`` ORM rows (``active`` only).

        Rows are duck-typed (``active``, ``path``, ``value``, ``figure_type``)
        so this stays import-free of the models layer and trivially testable
        with stubs.
        """
        entries = [
            LockedEntry(
                path=row.path,
                value=row.value,
                figure_type=getattr(row, "figure_type", None),
            )
            for row in rows
            if getattr(row, "active", True)
        ]
        return cls(entries)

    def is_locked(self, path: str) -> bool:
        return path in self._by_path

    def locked_value(self, path: str) -> str | None:
        entry = self._by_path.get(path)
        return entry.value if entry is not None else None

    def assert_writable(self, path: str, proposed_value: Any) -> None:
        """Reject a write to ``path`` that would change a locked figure.

        No-op when ``path`` is not locked, or when ``proposed_value``
        canonicalises to the locked value (idempotent re-write). Raises
        :class:`LockedFigureViolation` otherwise.
        """
        entry = self._by_path.get(path)
        if entry is None:
            return  # path carries no lock — free to write
        proposed = canonical_value(proposed_value)
        if proposed != entry.value:
            raise LockedFigureViolation(path, entry.value, proposed)

    def assert_batch_writable(self, writes: Mapping[str, Any]) -> None:
        """Assert every write in a batch is permitted.

        Reports the *first* offending path (deterministic order) so the caller
        gets a single, stable violation for an apply payload that touches many
        fields.
        """
        for path in sorted(writes):
            self.assert_writable(path, writes[path])

    def verify_unchanged(self, path: str, current_value: Any) -> None:
        """Post-apply proof that a locked figure survived a write unchanged.

        Unlike :meth:`assert_writable`, an *unlocked* path here is itself an
        error — you only verify things you locked. Raises
        :class:`LockedFigureViolation` if the current value drifted, or
        :class:`KeyError` if ``path`` was never locked.
        """
        entry = self._by_path.get(path)
        if entry is None:
            raise KeyError(f"No locked figure at path {path!r} to verify")
        current = canonical_value(current_value)
        if current != entry.value:
            raise LockedFigureViolation(path, entry.value, current)
