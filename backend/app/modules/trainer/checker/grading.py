# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Grade one task: panel answers plus probe readings -> per-item verdicts.

:func:`grade_task` is pure. It takes the task, the learner's stored answers and
the probe results already read (by :func:`run_task_probes`, the one function
here that touches the database) and returns the parts of
``schemas.AttemptResult`` the checker owns: verdict, item counts, the per-item
``FieldResult`` list and the three rings. The service adds ids, progress,
unlocks and hints.

Graded items, in this order (the order of ``tests/fixtures/trainer/api``):

1. ``answer_key`` entries, keyed by answer name. ``optional_answer_key`` is
   never graded.

   * ``panel`` (decision 11): the typed answer only, for figures the ERP
     cannot compute.
   * ``probe:<i>``: readback ``i`` only; the learner types nothing.
   * ``both``: the typed answer AND exactly one readback that expects the
     same ledger key; both must match. Zero or several such readbacks is a
     course defect and grades ``error``. When the ERP side is wrong the item
     reports the ERP value; when only the panel is wrong it reports the
     panel value.

2. Readbacks no answer grades but whose probe says ``gate: true``
   (decision 19), keyed ``rb<i>``. Which readbacks are graded is decided by
   ``validators.graded_readback_indexes``, the same function the course
   rules use, so the checker and ``trainer.task_discriminates_seed_state``
   cannot drift apart. Any other probed readback is informational: it is shown
   by :func:`readback_values` and never fails the task.

3. Trace and explain checks, keyed by check id; the observed value is the
   chosen option index and ``feedback`` is that option's feedback only.

A task passes when it has at least one graded item and every one is ``ok``.
Nothing returned carries an expected value, a ``correct`` flag, a wrong value
or the feedback of an option the learner did not choose (design section 7).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_registry import CURRENCIES, minor_units
from app.core.validation.messages import translate
from app.modules.trainer.checker.matching import (
    UNIT_SLIP_DIAGNOSIS_ID,
    Expectation,
    compare,
    is_unit_slip,
    match_diagnosis,
    scoped_diagnoses,
)
from app.modules.trainer.checker.registry import OPEN_LEVELING_KEY, ProbeContext, ProbeMode, ProbeResult, run_probe
from app.modules.trainer.checker.units import (
    NUMERIC_KINDS,
    SCHEMA_KIND,
    FieldKind,
    format_decimal,
    format_value,
    parse_panel_number,
    probe_field_kind,
)
from app.modules.trainer.schemas import Diagnosis, FieldResult, ReadbackValue, RelatedValue, TaskRings
from app.modules.trainer.spec import (
    AnswerKeySpec,
    DiagnosisSpec,
    ReadbackSpec,
    TaskSpec,
    parse_graded_by,
    to_decimal,
)
from app.modules.trainer.validators import LedgerEntry, graded_readback_indexes, ledger_label_map, readback_expectation

#: Tolerance of an inline ``probe.expect`` that no answer grades; the same
#: default the course rules use.
DEFAULT_TOLERANCE = Decimal("0.01")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RATE_UNITS = ("percent", "fraction")


@dataclass(frozen=True, slots=True)
class PanelAnswer:
    """One stored answer (``oe_trainer_answer``): typed text or a chosen option."""

    value_text: str | None = None
    option_index: int | None = None


@dataclass(frozen=True, slots=True)
class GradeOutcome:
    """The checker's part of an ``AttemptResult``."""

    verdict: Literal["pass", "fail"]
    graded_items: int
    passed_items: int
    fields: list[FieldResult]
    rings: TaskRings

    @property
    def passed(self) -> bool:
        """True for a pass."""
        return self.verdict == "pass"


# ── Expectations ─────────────────────────────────────────────────────────────


def _probe_kind(readback: ReadbackSpec | None) -> FieldKind | None:
    if readback is None or readback.probe is None:
        return None
    return probe_field_kind(readback.probe.type, getattr(readback.probe.args, "field", None))


def answer_kind(
    answer: AnswerKeySpec, readback: ReadbackSpec | None = None, *, task: TaskSpec | None = None
) -> FieldKind:
    """The kind of an answer. Never money by default.

    In order: the kind of the probe field that grades it (``readback``); else
    percent for a rate unit; else what ``display_unit`` says (decision 23):
    money for a currency code, a plain number for anything else (days, m2);
    else the kind of a readback in ``task`` that reads the same ledger key
    from the ERP; else a plain number. A panel-only amount must therefore
    carry its currency as ``display_unit``, or be read back somewhere.
    """
    kind = _probe_kind(readback)
    if kind is not None:
        return kind
    if answer.unit in _RATE_UNITS:
        return "percent"
    if answer.display_unit is not None:
        return "money" if answer.display_unit.strip().upper() in CURRENCIES else "number"
    if task is not None:
        reading = next(
            (r for r in task.readback if r.probe is not None and answer.ledger_key in r.expects),
            None,
        )
        kind = _probe_kind(reading)
        if kind is not None:
            return kind
    return "number"


def answer_expectation(answer: AnswerKeySpec, kind: FieldKind, currency: str | None) -> Expectation:
    """What an answer expects, with its alternatives, tolerance and rate unit."""
    return Expectation(
        value=answer.value,
        kind=kind,
        tolerance=answer.tolerance,
        unit=answer.unit,
        also_accepted=tuple(a.value for a in answer.also_accepted),
        currency=currency,
    )


def _both_readbacks(task: TaskSpec, answer: AnswerKeySpec) -> list[int]:
    return [i for i, r in enumerate(task.readback) if r.probe is not None and answer.ledger_key in r.expects]


def _grading_answer(task: TaskSpec, index: int) -> AnswerKeySpec | None:
    """The required answer that grades readback ``index``, if any."""
    for answer in task.answer_key:
        grading = answer.grading
        if grading.kind == "probe" and grading.readback_index == index:
            return answer
        if grading.kind == "both" and _both_readbacks(task, answer) == [index]:
            return answer
    return None


def readback_expectation_for(
    task: TaskSpec,
    index: int,
    *,
    currency: str | None,
    ledger: Mapping[str, LedgerEntry] | None = None,
) -> Expectation | None:
    """What readback ``index`` expects.

    The grading answer when one points at it, else the inline ``probe.expect``,
    else the first ``expects`` ledger key that ``ledger`` resolves
    (``validators.build_ledger`` of the whole course). None when nothing
    resolves.
    """
    readback = task.readback[index]
    kind = _probe_kind(readback)
    if kind is None:
        return None
    answer = _grading_answer(task, index)
    if answer is not None:
        return answer_expectation(answer, kind, currency)
    entry = readback_expectation(readback.model_dump(mode="python"), dict(ledger or {}))
    if entry is None:
        return None
    tolerance = DEFAULT_TOLERANCE
    for candidate in [*task.answer_key, *task.optional_answer_key]:
        if candidate.ledger_key in readback.expects:
            tolerance = candidate.tolerance
            break
    return Expectation(value=entry.value, kind=kind, tolerance=tolerance, unit=entry.unit, currency=currency)


# ── Item evaluation ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Verdict:
    verdict: Literal["ok", "wrong", "missing", "error"]
    observed: str | None
    value: object = None


def _related_kind(value: Decimal, name: str, ledger: Mapping[str, LedgerEntry], currency: str | None) -> str:
    entry = ledger.get(name)
    if entry is not None and entry.unit in _RATE_UNITS:
        return "percent"
    # A figure written to the currency's minor unit is money; anything else
    # (a quantity, a count) is a plain number.
    return "money" if value.as_tuple().exponent == -minor_units(currency) else "number"


def _diagnosis_view(diagnosis: DiagnosisSpec, ledger: Mapping[str, LedgerEntry], currency: str | None) -> Diagnosis:
    related: list[RelatedValue] = []
    for item in diagnosis.related:
        number = to_decimal(item.value)
        if number is not None:
            kind = _related_kind(number, item.name, ledger, currency)
            entry = ledger.get(item.name)
            if kind == "percent" and entry is not None and entry.unit == "fraction":
                number = number * 100
            related.append(
                RelatedValue(name=item.name, value=format_decimal(number), kind=kind, label=item.label)  # type: ignore[arg-type]
            )
        elif isinstance(item.value, str) and item.value:
            related.append(RelatedValue(name=item.name, value=item.value, kind="text", label=item.label))
    return Diagnosis(id=diagnosis.id, kind=diagnosis.kind, message=diagnosis.message, related=related)


def _unit_slip_view(locale: str) -> Diagnosis:
    return Diagnosis(
        id=UNIT_SLIP_DIAGNOSIS_ID,
        kind="error",
        message=translate(UNIT_SLIP_DIAGNOSIS_ID, locale=locale),
        related=[],
    )


def _diagnose(
    value: object,
    candidates: list[DiagnosisSpec],
    expectation: Expectation,
    ledger: Mapping[str, LedgerEntry],
    locale: str,
) -> Diagnosis | None:
    hit = match_diagnosis(value, candidates, expectation)
    if hit is not None:
        return _diagnosis_view(hit, ledger, expectation.currency)
    if is_unit_slip(value, expectation):
        return _unit_slip_view(locale)
    return None


def _erp_verdict(result: ProbeResult | None, expectation: Expectation) -> _Verdict:
    if result is None:
        return _Verdict("error", None)
    if result.value is None:
        return _Verdict("missing" if result.is_missing else "error", None)
    state = compare(result.value, expectation)
    if state == "unknown":
        return _Verdict("error", None)
    observed = format_value(result.value, expectation.kind, expectation.currency)
    return _Verdict("ok" if state == "match" else "wrong", observed, result.value)


def _panel_verdict(answer: PanelAnswer | None, expectation: Expectation) -> _Verdict:
    text = answer.value_text if answer is not None else None
    if text is None or not text.strip():
        return _Verdict("missing", None)
    if expectation.kind in NUMERIC_KINDS:
        parsed = parse_panel_number(text)
        if parsed is None:
            return _Verdict("error", text.strip()[:64])
        state = compare(parsed, expectation)
        return _Verdict("ok" if state == "match" else "wrong", format_decimal(parsed), parsed)
    state = compare(text, expectation)
    return _Verdict("ok" if state == "match" else "wrong", text.strip()[:64], text)


def _field(
    key: str,
    source: Literal["panel", "erp"],
    verdict: _Verdict,
    *,
    candidates: list[DiagnosisSpec],
    expectation: Expectation | None,
    ledger: Mapping[str, LedgerEntry],
    locale: str,
) -> FieldResult:
    diagnosis = None
    if verdict.verdict == "wrong" and expectation is not None:
        diagnosis = _diagnose(verdict.value, candidates, expectation, ledger, locale)
    return FieldResult(
        key=key, source=source, verdict=verdict.verdict, observed=verdict.observed, diagnosis=diagnosis, feedback=None
    )


def _option_field(check_id: str, question: Any, answer: PanelAnswer | None) -> FieldResult:
    index = answer.option_index if answer is not None else None
    if index is None:
        return FieldResult(
            key=check_id, source="panel", verdict="missing", observed=None, diagnosis=None, feedback=None
        )
    if not 0 <= index < len(question.options):
        return FieldResult(
            key=check_id, source="panel", verdict="error", observed=str(index), diagnosis=None, feedback=None
        )
    option = question.options[index]
    return FieldResult(
        key=check_id,
        source="panel",
        verdict="ok" if option.correct else "wrong",
        observed=str(index),
        diagnosis=None,
        # Only the feedback of the option the learner chose.
        feedback=option.feedback,
    )


# ── grade_task ───────────────────────────────────────────────────────────────


def _as_task(task: TaskSpec | Mapping[str, Any]) -> TaskSpec:
    return task if isinstance(task, TaskSpec) else TaskSpec.model_validate(task)


def ledger_labels(tasks: Iterable[TaskSpec]) -> dict[str, str]:
    """Fallback names of ledger keys, in the course language (decision 47).

    Used for a related value whose spec carries no ``label``; the rule is
    :func:`validators.ledger_label_map`, shared with the loader warning.
    """
    return ledger_label_map([t.model_dump(mode="python") for t in tasks])


def _with_labels(fields: list[FieldResult], labels: Mapping[str, str]) -> list[FieldResult]:
    out: list[FieldResult] = []
    for item in fields:
        diagnosis = item.diagnosis
        if diagnosis is not None and diagnosis.related:
            related = [
                r if r.label is not None else r.model_copy(update={"label": labels.get(r.name)})
                for r in diagnosis.related
            ]
            item = item.model_copy(update={"diagnosis": diagnosis.model_copy(update={"related": related})})
        out.append(item)
    return out


def grade_task(
    task_spec: TaskSpec | Mapping[str, Any],
    panel_answers: Mapping[str, PanelAnswer],
    probe_results: Mapping[int, ProbeResult],
    *,
    currency: str | None,
    ledger: Mapping[str, LedgerEntry] | None = None,
    locale: str = "en",
    labels: Mapping[str, str] | None = None,
) -> GradeOutcome:
    """Grade one task. Pure.

    Args:
        task_spec: The task from the enrolment's pinned spec.
        panel_answers: Stored answers by answer name (number answers) or by
            check id (trace / explain options).
        probe_results: Probe results by readback index
            (:func:`run_task_probes`). A graded readback without a result
            grades ``error``.
        currency: The course currency (money is quantised to it).
        ledger: ``validators.build_ledger`` of the whole course, for gated
            readbacks that expect a ledger key instead of an inline value,
            and to label related values.
        locale: Language of the engine's own diagnosis messages.
        labels: :func:`ledger_labels` of the whole course: the fallback for a
            related value whose spec has no ``label`` (decision 47). The
            spec label always wins; None leaves the unlabelled ones null.

    Returns:
        Verdict, counts, per-item results and rings.
    """
    task = _as_task(task_spec)
    ledger = dict(ledger or {})
    fields: list[FieldResult] = []
    numbers_items: list[FieldResult] = []
    covered: set[int] = set()

    for answer in task.answer_key:
        grading = parse_graded_by(answer.graded_by)
        keys = {answer.name, answer.ledger_key}
        if grading.kind == "panel":
            expectation = answer_expectation(answer, answer_kind(answer, task=task), currency)
            verdict = _panel_verdict(panel_answers.get(answer.name), expectation)
            item = _field(
                answer.name,
                "panel",
                verdict,
                candidates=scoped_diagnoses(task.diagnoses, keys),
                expectation=expectation,
                ledger=ledger,
                locale=locale,
            )
        else:
            indexes = [grading.readback_index] if grading.kind == "probe" else _both_readbacks(task, answer)
            valid = [i for i in indexes if i is not None and 0 <= i < len(task.readback) and task.readback[i].probe]
            if len(valid) != 1:
                item = FieldResult(
                    key=answer.name, source="erp", verdict="error", observed=None, diagnosis=None, feedback=None
                )
            else:
                index = valid[0]
                covered.add(index)
                keys.add(f"rb{index}")
                candidates = scoped_diagnoses(task.diagnoses, keys)
                expectation = answer_expectation(answer, answer_kind(answer, task.readback[index]), currency)
                erp = _erp_verdict(probe_results.get(index), expectation)
                common = {"candidates": candidates, "expectation": expectation, "ledger": ledger, "locale": locale}
                item = _field(answer.name, "erp", erp, **common)  # type: ignore[arg-type]
                if grading.kind == "both" and erp.verdict == "ok":
                    panel = _panel_verdict(panel_answers.get(answer.name), expectation)
                    if panel.verdict != "ok":
                        item = _field(answer.name, "panel", panel, **common)  # type: ignore[arg-type]
        fields.append(item)
        numbers_items.append(item)

    gated = sorted(i for i in graded_readback_indexes(task.model_dump(mode="python")) if i not in covered)
    for index in gated:
        if not 0 <= index < len(task.readback) or task.readback[index].probe is None:
            continue
        key = f"rb{index}"
        expectation = readback_expectation_for(task, index, currency=currency, ledger=ledger)
        if expectation is None:
            item = FieldResult(key=key, source="erp", verdict="error", observed=None, diagnosis=None, feedback=None)
        else:
            item = _field(
                key,
                "erp",
                _erp_verdict(probe_results.get(index), expectation),
                candidates=scoped_diagnoses(task.diagnoses, {key}),
                expectation=expectation,
                ledger=ledger,
                locale=locale,
            )
        fields.append(item)
        numbers_items.append(item)

    ring_items: dict[str, list[FieldResult]] = {"trace": [], "explain": []}
    for check in task.checks:
        if check.kind not in ring_items:
            continue
        question = task.trace_question if check.kind == "trace" else task.explain_question
        item = _option_field(check.id, question, panel_answers.get(check.id))
        fields.append(item)
        ring_items[check.kind].append(item)

    def closed(items: list[FieldResult]) -> bool:
        # A ring over zero items stays open: an empty check never passes.
        return bool(items) and all(i.verdict == "ok" for i in items)

    if labels:
        fields = _with_labels(fields, labels)
    passed_items = sum(1 for f in fields if f.verdict == "ok")
    passing = bool(fields) and passed_items == len(fields)
    return GradeOutcome(
        verdict="pass" if passing else "fail",
        graded_items=len(fields),
        passed_items=passed_items,
        fields=fields,
        rings=TaskRings(
            numbers=closed(numbers_items), trace=closed(ring_items["trace"]), explain=closed(ring_items["explain"])
        ),
    )


# ── Readback ─────────────────────────────────────────────────────────────────


def readback_values(
    task_spec: TaskSpec | Mapping[str, Any],
    probe_results: Mapping[int, ProbeResult],
    *,
    currency: str | None,
    ledger: Mapping[str, LedgerEntry] | None = None,
) -> list[ReadbackValue]:
    """Live readback items for ``GET /tasks/{id}/readback``: never the expected value.

    Every readback of the task gets one item ``rb<i>``: ``match`` or
    ``mismatch`` with the value the ERP holds, or ``unknown`` with no value
    when there is no probe, no result or nothing to compare with.
    """
    task = _as_task(task_spec)
    items: list[ReadbackValue] = []
    for index, readback in enumerate(task.readback):
        kind = _probe_kind(readback) or "text"
        schema_kind = SCHEMA_KIND[kind]
        result = probe_results.get(index)
        expectation = readback_expectation_for(task, index, currency=currency, ledger=ledger)
        state = compare(result.value, expectation) if result is not None and expectation is not None else "unknown"
        value = format_value(result.value, kind, currency) if state != "unknown" and result is not None else None
        if schema_kind == "date" and value is not None and not _ISO_DATE_RE.match(value):
            schema_kind = "text"
        reason_key = readback_reason_key(result) if state == "unknown" else None
        items.append(
            ReadbackValue(id=f"rb{index}", state=state, app_value=value, kind=schema_kind, reason_key=reason_key)
        )
    return items


def readback_reason_key(result: ProbeResult | None) -> str | None:
    """The i18n key that tells the learner what to do about an unknown reading (decision 40).

    Only a levelling table the learner has not computed yet has an action to
    name today (:data:`registry.OPEN_LEVELING_KEY`); every other reason has
    nothing the learner can do from the panel, and gets no key.
    """
    if result is None or result.status != "unknown" or not result.detail:
        return None
    reason = result.detail.split(":", 1)[0].strip()
    return OPEN_LEVELING_KEY if reason == "not_computed" else None


# ── Running the probes of a task ─────────────────────────────────────────────


async def run_task_probes(
    session: AsyncSession,
    task_spec: TaskSpec | Mapping[str, Any],
    ctx: ProbeContext,
    *,
    currency: str | None,
    ledger: Mapping[str, LedgerEntry] | None = None,
    mode: ProbeMode,
) -> dict[int, ProbeResult]:
    """Run every probe of the task's readbacks, by readback index.

    A readback with nothing to compare with is not run.

    Args:
        mode: Required, and it replaces ``ctx.mode``, so a caller cannot
            check in read mode by accident. ``read`` for the readback GET: nothing is written, and a
            levelling table the learner has not computed reads as
            ``not_computed`` (decision 36). ``check`` for a check:
            ``bid.leveling`` recomputes the table first, the only probe that
            writes.
    """
    task = _as_task(task_spec)
    questions = {c.kind: c.id for c in task.checks if c.kind in ("trace", "explain")}
    context = dataclasses.replace(ctx, task_id=ctx.task_id or task.id, question_answer_names=questions, mode=mode)
    results: dict[int, ProbeResult] = {}
    for index, readback in enumerate(task.readback):
        if readback.probe is None:
            continue
        expectation = readback_expectation_for(task, index, currency=currency, ledger=ledger)
        if expectation is None:
            continue
        results[index] = await run_probe(session, readback.probe, context, expectation)
    return results
