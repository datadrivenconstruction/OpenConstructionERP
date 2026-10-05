# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compare an observed value with what a task expects, and say why it is wrong.

Pure functions only. :func:`values_match` is THE comparison (decision 37):
the course rules (``validators.discriminating_items`` and the inline-expect
check) and the checker call the same function, so a seed the course rules
accept as "not yet right" is exactly a state the checker fails. The rules:

* **Match.** ``abs(observed - expected) <= tolerance`` for numbers, after both
  sides are put in the field's unit (:mod:`.units`): a fraction answer and its
  tolerance are scaled to percent for a percent field, and money is quantised
  to the course currency on both sides. Text and dates compare exactly,
  case-folded; booleans compare as booleans. ``None`` or an unparseable value
  is ``unknown``, never a match.
* **Also accepted.** ``answer_key[].also_accepted`` values are alternatives
  graded with the answer's own tolerance and unit.
* **Diagnosis.** Runs only on a value that does not match, and only over the
  diagnoses whose ``applies_to`` names this field (its answer name, its ledger
  key, or ``rb<i>`` for a readback). Never another field's, never another
  task's. The first diagnosis whose wrong value equals the observed value
  exactly wins; failing that, the first within the field's tolerance. A
  convention diagnosis without a wrong value is never matched automatically.
  The diagnosis carries no delta: with the observed value it would give the
  expected value away.
* **Unit slip.** A percent field holding ``x`` where ``x * 100`` matches is the
  built-in diagnosis :data:`UNIT_SLIP_DIAGNOSIS_ID` ("typed a fraction where a
  percent was asked"). It is tried after the course's own diagnoses.

Values read back from a stored spec arrive as strings (``spec.Scalar`` keeps a
string a string), so every value is parsed by the field's kind, never by its
Python type.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.modules.trainer.checker.units import NUMERIC_KINDS, FieldKind, rate_to_percent, to_kind_decimal
from app.modules.trainer.spec import DiagnosisSpec, to_decimal

CompareState = Literal["match", "mismatch", "unknown"]

#: Id (and message key) of the engine's own unit diagnosis.
UNIT_SLIP_DIAGNOSIS_ID = "trainer.diag.unit_fraction_vs_percent"


@dataclass(frozen=True, slots=True)
class Expectation:
    """What one graded or read-back item expects.

    Attributes:
        value: The expected value as written in the course (Decimal, numeric
            string, text or bool).
        kind: The field kind, from :func:`.units.probe_field_kind` or the
            answer.
        tolerance: In the unit of ``value`` (a fraction answer's tolerance is
            a fraction too).
        unit: ``percent`` | ``fraction`` for a rate, else None.
        also_accepted: Alternative accepted values, same unit and tolerance.
        currency: The course currency, for money quantisation.
    """

    value: object
    kind: FieldKind
    tolerance: Decimal = Decimal(0)
    unit: str | None = None
    also_accepted: tuple[object, ...] = ()
    currency: str | None = None


def observed_comparable(observed: object, expectation: Expectation) -> Decimal | None:
    """An observed number (ERP or panel, always in the field's own unit) in comparison form."""
    if isinstance(observed, bool):
        return None
    return to_kind_decimal(observed, expectation.kind, expectation.currency)


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().casefold() in ("true", "false"):
        return value.strip().casefold() == "true"
    return None


def _as_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    return str(value).strip().casefold()


def within_tolerance(observed: Decimal, expected: Decimal, tolerance: Decimal) -> bool:
    """``abs(observed - expected) <= tolerance``. Neither side is rounded here."""
    return abs(observed - expected) <= tolerance


def values_match(
    expected: object,
    observed: object,
    *,
    kind: FieldKind,
    tolerance: object = Decimal(0),
    unit: str | None = None,
    observed_unit: str | None = None,
    currency: str | None = None,
) -> bool | None:
    """Does ``observed`` equal ``expected`` for a field of ``kind``? The one comparison.

    Args:
        expected: The value the course states, written in ``unit``.
        observed: The value read (ERP, panel or a seed baseline).
        kind: The field kind (:func:`.units.probe_field_kind`).
        tolerance: In ``unit``, like ``expected``: a fraction answer's
            tolerance is a fraction and is scaled with it.
        unit: ``percent`` | ``fraction`` for a rate written in the course.
        observed_unit: The rate unit of ``observed``; None means the field's
            own unit (percent for a percent field), which is what the ERP and
            the panel hold.
        currency: Money on both sides is quantised half up to this
            currency's minor unit before the tolerance applies.

    Returns:
        True or False; None when either side is missing or is not a value of
        the kind (an unreadable value is neither a match nor a mismatch).
    """
    if expected is None or observed is None:
        return None
    if kind in NUMERIC_KINDS:
        wanted, got = to_decimal(expected), to_decimal(observed)
        if wanted is None or got is None:
            return None
        allowed = abs(to_decimal(tolerance) or Decimal(0))
        if kind == "percent":
            wanted, got = rate_to_percent(wanted, unit), rate_to_percent(got, observed_unit)
            allowed = rate_to_percent(allowed, unit)
        wanted, got = to_kind_decimal(wanted, kind, currency), to_kind_decimal(got, kind, currency)
        if wanted is None or got is None:
            return None
        return within_tolerance(got, wanted, allowed)
    if kind == "bool":
        wanted_bool, got_bool = _as_bool(expected), _as_bool(observed)
        if wanted_bool is None or got_bool is None:
            return None
        return wanted_bool is got_bool
    wanted_text, got_text = _as_text(expected), _as_text(observed)
    if not wanted_text or got_text is None:
        return None
    return wanted_text == got_text


def _match_any(observed: object, values: Iterable[object], expectation: Expectation, tolerance: object) -> bool | None:
    """values_match over several course-side values: True if any, None if none was comparable."""
    seen_false = False
    for value in values:
        result = values_match(
            value,
            observed,
            kind=expectation.kind,
            tolerance=tolerance,
            unit=expectation.unit,
            currency=expectation.currency,
        )
        if result:
            return True
        seen_false = seen_false or result is False
    return False if seen_false else None


def compare(observed: object, expectation: Expectation) -> CompareState:
    """Does ``observed`` match the expectation (or one of its alternatives)?

    :func:`values_match` against the value and each ``also_accepted`` value.
    ``observed`` is in the field's own unit (the ERP's, or the panel's, which
    asks for the same unit).

    Returns:
        ``unknown`` when the observed value is None or unreadable for the
        field's kind, or when the expectation itself has no usable value;
        ``match`` or ``mismatch`` otherwise.
    """
    if expectation.kind in NUMERIC_KINDS and observed_comparable(observed, expectation) is None:
        return "unknown"
    result = _match_any(observed, (expectation.value, *expectation.also_accepted), expectation, expectation.tolerance)
    if result is None:
        return "unknown"
    return "match" if result else "mismatch"


def scoped_diagnoses(diagnoses: Iterable[DiagnosisSpec], field_keys: Iterable[str]) -> list[DiagnosisSpec]:
    """The diagnoses whose ``applies_to`` is one of ``field_keys``, in file order."""
    keys = set(field_keys)
    return [d for d in diagnoses if d.applies_to in keys]


def match_diagnosis(
    observed: object, candidates: Iterable[DiagnosisSpec], expectation: Expectation
) -> DiagnosisSpec | None:
    """The diagnosis that explains a wrong ``observed`` value, if any.

    ``candidates`` must already be scoped to this field
    (:func:`scoped_diagnoses`). A diagnosis's wrong value is written in the
    answer's unit, so it is converted like the answer before the comparison.

    Returns:
        The first exact match, else the first within tolerance, else None.
    """
    pool = [d for d in candidates if d.wrong_value is not None]
    if not pool or observed is None:
        return None
    for tolerance in (Decimal(0), expectation.tolerance):
        hit = next((d for d in pool if _match_any(observed, (d.wrong_value,), expectation, tolerance)), None)
        if hit is not None:
            return hit
    return None


def is_unit_slip(observed: object, expectation: Expectation) -> bool:
    """A percent field holding the rate as a fraction: ``observed * 100`` matches.

    Only for percent fields, and never for an observed zero (zero times 100 is
    still zero and would "explain" a missing value).
    """
    if expectation.kind != "percent":
        return False
    got = observed_comparable(observed, expectation)
    if got is None or got == 0:
        return False
    return bool(
        _match_any(got * 100, (expectation.value, *expectation.also_accepted), expectation, expectation.tolerance)
    )
