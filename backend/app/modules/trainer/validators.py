# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``trainer_spec``: is a course file fit to grade learners?

The rules run on the normalised course dict (``spec.normalise_course_dict``),
not on a parsed :class:`~app.modules.trainer.spec.CourseSpec`. A file that
fails the shape check still gets a verdict from every rule, so an author sees
all of the problems at once. Every rule therefore reads the dict defensively:
a missing or mistyped part is a finding or a skip, never an exception. A rule
that does raise is turned into an engine error by the validation engine, and
the loader treats an engine error as a failed course (fail closed).

Rules (severity):

* ``trainer.task_order_contiguous`` (ERROR) - tasks are numbered 1..N, ids unique.
* ``trainer.task_id_fits_storage`` (ERROR) - ids fit the ``oe_trainer_*`` columns.
* ``trainer.opens_known_lock`` (ERROR) - every ``opens`` is a registered lock id
  (decision 5); a badge lock names this course's badge.
* ``trainer.answer_tolerance_positive`` (ERROR) - 0 < tolerance <= 1, and not
  coarser than the precision the value is written to.
* ``trainer.answer_names_unique`` (ERROR) - answer names are unique in a task.
* ``trainer.every_answer_graded`` (ERROR) - ``graded_by`` follows decision 11.
* ``trainer.numbers_check_subset_of_answer_key`` (ERROR) - every numbers-check
  field is an answer of the task.
* ``trainer.numbers_check_lists_only_panel_answers`` (ERROR) - a numbers check
  never asks the learner to type a probe-only answer (decision 11).
* ``trainer.readback_resolves_in_file`` (ERROR) - a probed readback's expected
  value is in this file (a ledger key or an inline ``expect``).
* ``trainer.readback_has_probe`` (ERROR when graded, WARNING otherwise).
* ``trainer.probe_args_frozen`` (ERROR) - probe types are on the closed list and
  their args match the frozen models in ``spec.py`` (decisions 10, 16).
* ``trainer.task_has_probe_graded_item`` (ERROR) - decision 6.
* ``trainer.task_discriminates_seed_state`` (ERROR) - at least one ERP-probed
  item of each task expects a value the untouched project does not already
  show, so "right numbers in the panel, ERP untouched" fails.
* ``trainer.diagnosis_applies_to_resolves`` (ERROR).
* ``trainer.diagnosis_unique_per_field`` (ERROR) - within one field no wrong
  value is within tolerance of a right value or of another wrong value.
* ``trainer.diagnosis_wrong_value_numeric`` (ERROR).
* ``trainer.single_correct_option`` (ERROR).
* ``trainer.check_id_prefix_matches_task`` (WARNING).
* ``trainer.related_value_unlabelled`` (WARNING, decision 47).
* ``trainer.seed_stage_resolvable`` (ERROR) - decision 12.
* ``trainer.rate_unit_explicit`` (ERROR) - a rule that carries a rate states
  ``percent`` or ``fraction`` (a rule is a rate when the file uses its key as
  one, or when it holds a value in (0, 1]); other rules, such as a money
  amount, need no unit. A stated unit is one of the two, and a fraction is
  never above 1.
* ``trainer.percent_not_written_as_fraction`` (ERROR) - a value bound for an
  ERP percent column does not look like a fraction.
* ``trainer.einvoice_vat_resolvable`` (ERROR) - decision 14.
* ``trainer.sov_signable`` (ERROR) - every SOV line carries a unit and the
  classification the country's compliance pack needs to sign the contract
  (decision 18); the codes are run through the platform's own classification
  rules.
* ``trainer.graded_items_nonzero`` (ERROR) - a check over zero items never passes.
* ``trainer.variation_under_approval_threshold`` (WARNING).
* ``trainer.money_scale`` (ERROR) - seeded money has no more decimals than the
  currency.
* ``trainer.version_not_bumped`` (ERROR) - new content under a version learners
  may have pinned.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import translate
from app.modules.trainer.checker.matching import values_match
from app.modules.trainer.checker.units import probe_field_kind
from app.modules.trainer.locks import BADGE_PREFIX, is_badge_lock_id, is_known_lock_id
from app.modules.trainer.probe_types import ERP_PROBE_TYPE_NAMES, PROBE_TYPE_NAMES
from app.modules.trainer.spec import (
    COLUMN_LIMITS,
    PERCENT_PROBE_FIELDS,
    parse_graded_by,
    parse_stage,
    to_decimal,
    to_percent,
    validate_probe,
)

logger = logging.getLogger(__name__)

#: Rule set name the loader passes to ``ValidationEngine.validate``.
TRAINER_SPEC_RULE_SET = "trainer_spec"

_UNITS = ("percent", "fraction")
_DEFAULT_TOLERANCE = Decimal("0.01")
#: ``variations.service.HIGH_VALUE_APPROVAL_THRESHOLD``, mirrored so validation
#: never imports the service (and through it the database); a unit test reads
#: the service source and fails when the two drift apart.
VARIATION_APPROVAL_THRESHOLD = Decimal("100000")
#: Countries whose course must state a VAT number (decision 14).
_VAT_NUMBER_REQUIRED = frozenset({"GB", "DE", "FR"})
#: The classification key each country's compliance pack reads on a SOV line,
#: and the platform rules (all ERROR) the signing gate runs on it.
SOV_CLASSIFICATION_BY_COUNTRY: dict[str, tuple[str, tuple[str, ...]]] = {
    "GB": ("nrm", ("nrm.classification_required", "nrm.valid_element")),
    "DE": ("din276", ("din276.cost_group_required", "din276.valid_cost_group")),
    "US": ("masterformat", ("masterformat.classification_required", "masterformat.valid_division")),
    "FR": ("dpgf", ("dpgf.lot_required",)),
}
_SEED_BLOCKS_WITH_STAGE = (
    "project",
    "boq",
    "surety_bond_row",
    "bid_package",
    "contract",
)
#: Seed lists whose every entry needs its own stage.
_SEED_LISTS_WITH_STAGE = ("progress_readings", "variations")


# ── Defensive readers ────────────────────────────────────────────────────────


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in _list(value) if isinstance(v, dict)]


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _tasks(data: Any) -> list[dict[str, Any]]:
    return _dicts(_dict(data).get("tasks"))


def _task_ref(task: dict[str, Any], index: int) -> str:
    return _str(task.get("id")) or f"#{index + 1}"


def _answers(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Required and optional answers of a task."""
    return _dicts(task.get("answer_key")) + _dicts(task.get("optional_answer_key"))


def _probe(readback: dict[str, Any]) -> dict[str, Any] | None:
    probe = readback.get("probe")
    return probe if isinstance(probe, dict) else None


def _probe_field(probe: dict[str, Any]) -> tuple[str, str]:
    return _str(probe.get("type")), _str(_dict(probe.get("args")).get("field"))


def _currency(data: Any) -> str | None:
    currency = _dict(data).get("currency")
    return currency if isinstance(currency, str) else None


def _is_number(value: Any) -> bool:
    return to_decimal(value) is not None


# ── Ledger: every value a key in the file resolves to ────────────────────────


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """A value the file states under a ledger key, and its rate unit if any."""

    value: Any
    unit: str | None


#: ``<x>_ledger_key`` -> the sibling field that holds its value.
_LEDGER_SIBLINGS = {
    "percent": ("value",),
    "pct": ("percent_complete",),
}


def _unit_of(node: dict[str, Any]) -> str | None:
    unit = node.get("unit")
    return unit if unit in _UNITS else None


def _walk_seed(node: Any, ledger: dict[str, LedgerEntry]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_seed(item, ledger)
        return
    if not isinstance(node, dict):
        return
    key = node.get("ledger_key")
    if isinstance(key, str):
        for field in ("value", "amount", "total", "total_ht"):
            if field in node:
                ledger.setdefault(key, LedgerEntry(node[field], _unit_of(node)))
                break
    for name, ref in node.items():
        if isinstance(ref, str) and name.endswith("_ledger_key") and name != "ledger_key":
            base = name[: -len("_ledger_key")]
            for field in _LEDGER_SIBLINGS.get(base, (base,)):
                if field in node:
                    ledger.setdefault(ref, LedgerEntry(node[field], _unit_of(node) if field == "value" else None))
                    break
    for child in node.values():
        _walk_seed(child, ledger)


def build_ledger(data: Any) -> dict[str, LedgerEntry]:
    """Every ledger key the file resolves, first definition wins.

    Order: answers, rules, given values, the seed, question derivations. The
    external ``ledger_*.json`` files are never consulted (design section 3.3).
    """
    ledger: dict[str, LedgerEntry] = {}
    tasks = _tasks(data)
    for task in tasks:
        for answer in _answers(task):
            if isinstance(answer.get("ledger_key"), str):
                ledger.setdefault(answer["ledger_key"], LedgerEntry(answer.get("value"), _unit_of(answer)))
    for rule in _dicts(_dict(data).get("rules")):
        if isinstance(rule.get("key"), str) and not isinstance(rule.get("value"), (dict, list)):
            ledger.setdefault(rule["key"], LedgerEntry(rule.get("value"), _unit_of(rule)))
    for task in tasks:
        for given in _dicts(task.get("given")):
            if isinstance(given.get("ledger_key"), str):
                ledger.setdefault(given["ledger_key"], LedgerEntry(given.get("value"), _unit_of(given)))
    _walk_seed(_dict(data).get("seed"), ledger)
    for task in tasks:
        for question in ("trace_question", "explain_question"):
            for derivation in _dicts(_dict(task.get(question)).get("derivations")):
                if isinstance(derivation.get("name"), str):
                    ledger.setdefault(derivation["name"], LedgerEntry(derivation.get("value"), None))
    return ledger


def readback_expectation(readback: dict[str, Any], ledger: dict[str, LedgerEntry]) -> LedgerEntry | None:
    """What a readback expects: the inline ``expect``, else its first resolvable key."""
    probe = _probe(readback) or {}
    if probe.get("expect") is not None:
        return LedgerEntry(probe["expect"], probe.get("unit") if probe.get("unit") in _UNITS else None)
    for key in _list(readback.get("expects")):
        if isinstance(key, str) and key in ledger:
            entry = ledger[key]
            unit = entry.unit or (probe.get("unit") if probe.get("unit") in _UNITS else None)
            return LedgerEntry(entry.value, unit)
    return None


def _tolerance_for(task: dict[str, Any], readback: dict[str, Any]) -> Decimal:
    keys = {k for k in _list(readback.get("expects")) if isinstance(k, str)}
    for answer in _answers(task):
        if answer.get("ledger_key") in keys:
            tol = to_decimal(answer.get("tolerance"))
            if tol is not None and tol > 0:
                return tol
    return _DEFAULT_TOLERANCE


# ── Seed-state simulation for the discriminating rule ────────────────────────

_ABSENT = "absent"
_VALUE = "value"
_UNKNOWN = "unknown"


def _stage_visible(block: dict[str, Any], task_n: int) -> bool:
    try:
        return parse_stage(block.get("stage")).visible_at(task_n)
    except ValueError:
        return False


def _position_total(position: dict[str, Any]) -> Decimal:
    qty = to_decimal(position.get("qty")) or Decimal(0)
    rate = to_decimal(position.get("rate")) or Decimal(0)
    return qty * rate


def _seeded_markups(seed: dict[str, Any], task_n: int) -> list[dict[str, Any]]:
    boq = _dict(seed.get("boq"))
    markups = [m for m in _dicts(boq.get("markups")) if "stage" not in m or _stage_visible(m, task_n)]
    bond = _dict(seed.get("surety_bond_row"))
    if bond and _stage_visible(bond, task_n):
        markups.append(bond)
    return markups


def _seed_baseline(data: dict[str, Any], task_n: int, probe: dict[str, Any]) -> tuple[str, Any]:
    """What the probe reads on the seeded project before the learner acts.

    Returns ``(state, value)``: ``absent`` when the object does not exist yet
    (the learner creates it), ``value`` with the seeded value, or ``unknown``
    when the seed alone cannot say.
    """
    seed = _dict(data.get("seed"))
    kind, field = _probe_field(probe)
    args = _dict(probe.get("args"))
    boq = _dict(seed.get("boq"))
    boq_visible = bool(boq) and _stage_visible(boq, task_n) and args.get("boq_ref", "boq.main") == "boq.main"
    positions = [p for p in _dicts(boq.get("positions")) if not p.get("built_by_learner")] if boq_visible else []

    if kind == "boq.position":
        match = next((p for p in positions if p.get("code") == args.get("ordinal")), None)
        if match is None:
            return _ABSENT, None
        if field == "quantity":
            return _VALUE, to_decimal(match.get("qty"))
        if field == "unit_rate":
            return _VALUE, to_decimal(match.get("rate")) or Decimal(0)
        return _VALUE, _position_total(match)
    if kind == "boq.section_total":
        ordinal = args.get("section_ordinal")
        listed: set[str] = set()
        for section in _dicts(boq.get("sections")):
            if section.get("ordinal") == ordinal:
                if section.get("built_by_learner"):
                    return _ABSENT, None
                listed |= {c for c in _list(section.get("positions")) if isinstance(c, str)}
        members = [p for p in positions if p.get("section") == ordinal or p.get("code") in listed]
        return (_VALUE, sum((_position_total(p) for p in members), Decimal(0))) if members else (_ABSENT, None)
    if kind == "boq.cost_breakdown":
        if not boq_visible:
            return _ABSENT, None
        direct = sum((_position_total(p) for p in positions), Decimal(0))
        markups = _seeded_markups(seed, task_n)
        if field == "direct_cost":
            return _VALUE, direct
        if field == "grand_total":
            return (_UNKNOWN, None) if markups else (_VALUE, direct)
        name = args.get("markup_name")
        return (_UNKNOWN, None) if any(m.get("name") == name for m in markups) else (_ABSENT, None)
    if kind == "boq.markup":
        match = next((m for m in _seeded_markups(seed, task_n) if m.get("name") == args.get("name")), None)
        if match is None:
            return _ABSENT, None
        return (_VALUE, match[field]) if field in match else (_UNKNOWN, None)
    if kind == "bid.submission":
        package = _dict(seed.get("bid_package"))
        if not package or not _stage_visible(package, task_n):
            return _ABSENT, None
        bid = next((b for b in _dicts(package.get("bids")) if b.get("bidder") == args.get("bidder_name")), None)
        if bid is None:
            return _ABSENT, None
        # Bids are recorded before the package is opened, so none is valid yet.
        return (_VALUE, to_decimal(bid.get("total"))) if field == "total_amount" else (_VALUE, False)
    if kind == "contract.field":
        contract = _dict(seed.get("contract"))
        if not contract or not _stage_visible(contract, task_n):
            return _ABSENT, None
        if field in ("total_value", "original_contract_value"):
            return _VALUE, to_decimal(_dict(contract.get("value")).get("value"))
        if field == "retention_percent":
            raw = contract.get("retention_percent")
            if isinstance(raw, dict):
                value = to_decimal(raw.get("value"))
                return (_VALUE, to_percent(value, raw.get("unit"))) if value is not None else (_UNKNOWN, None)
            return _VALUE, to_decimal(raw)
        if field == "einvoice_vat_rate":
            vat = to_decimal(contract.get("vat_rate_percent"))
            return (_VALUE, vat) if vat is not None else (_ABSENT, None)
        if field == "status":
            return _VALUE, "active"
        return _UNKNOWN, None
    if kind == "variation.request":
        seeded = [v for v in _dicts(seed.get("variations")) if _stage_visible(v, task_n) and v.get("erp_request")]
        if not seeded:
            return _ABSENT, None
        if field == "status":
            return _VALUE, "draft"
        if field == "estimated_cost_impact":
            return _VALUE, Decimal(0)
        return _ABSENT, None
    if kind in ("bid.leveling", "bid.award", "claim.field", "claim.line", "claim.lien_waiver"):
        return _ABSENT, None
    if kind in ("finance.receivable", "variation.order"):
        return _ABSENT, None
    return _UNKNOWN, None


def _probe_identity(probe: dict[str, Any]) -> str:
    return json.dumps([probe.get("type"), _dict(probe.get("args"))], sort_keys=True, default=str)


def discriminating_items(data: Any) -> dict[int, list[tuple[int, bool]]]:
    """Per task index: ``(readback index, discriminates)`` for every graded ERP-probed readback.

    Informational readbacks (no answer, no ``gate``) are left out on both sides:
    they never fail a task, so they neither make it discriminate nor leave a
    state a later task can rely on.

    The baseline of a probe in task n is what an earlier task left behind when
    an earlier task graded the same probe, else what the seed shows. For a
    BOQ grand total with no seeded markups the baseline is the direct cost an
    earlier task graded, because nothing else sits between the two.
    """
    data = _dict(data)
    ledger = build_ledger(data)
    earlier: dict[str, LedgerEntry] = {}
    out: dict[int, list[tuple[int, bool]]] = {}
    for t_index, task in enumerate(_tasks(data)):
        n = task.get("n") if isinstance(task.get("n"), int) else t_index + 1
        items: list[tuple[int, bool]] = []
        graded = graded_readback_indexes(task)
        for r_index, readback in enumerate(_dicts(task.get("readback"))):
            probe = _probe(readback)
            if r_index not in graded or probe is None or probe.get("type") not in ERP_PROBE_TYPE_NAMES:
                continue
            expected = readback_expectation(readback, ledger)
            if expected is None:
                continue
            kind, field = _probe_field(probe)
            identity = _probe_identity(probe)
            if identity in earlier:
                state, baseline, base_unit = _VALUE, earlier[identity].value, earlier[identity].unit
            else:
                state, baseline = _seed_baseline(data, n, probe)
                base_unit = "percent" if (kind, field) in PERCENT_PROBE_FIELDS else None
                if kind == "boq.cost_breakdown" and field == "grand_total" and state == _VALUE:
                    direct = dict(probe, args=dict(_dict(probe.get("args")), field="direct_cost"))
                    if _probe_identity(direct) in earlier:
                        baseline = earlier[_probe_identity(direct)].value
            if state == _ABSENT:
                differs = True
            elif state == _VALUE and baseline is not None:
                differs = (
                    values_match(
                        expected.value,
                        baseline,
                        kind=probe_field_kind(kind, field),
                        tolerance=_tolerance_for(task, readback),
                        unit=expected.unit,
                        observed_unit=base_unit,
                        currency=_currency(data),
                    )
                    is not True
                )
            else:
                differs = False
            items.append((r_index, differs))
        out[t_index] = items
        for r_index, readback in enumerate(_dicts(task.get("readback"))):
            if r_index not in graded:
                continue
            probe = _probe(readback)
            expected = readback_expectation(readback, ledger) if probe else None
            if probe is not None and expected is not None:
                earlier[_probe_identity(probe)] = expected
    return out


# ── Rule base ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Finding:
    """One failure of a rule: the message reason, where, and its parameters."""

    reason: str
    element_ref: str
    params: dict[str, Any]
    severity: Severity | None = None

    def __post_init__(self) -> None:
        # ``translate(key, locale, **params)`` owns these two names; a param
        # spelt the same would crash the rule at report time, not here.
        clash = {"key", "locale"} & set(self.params)
        if clash:
            msg = f"Finding params must not be named {sorted(clash)}"
            raise ValueError(msg)


def _locale(context: ValidationContext) -> str:
    return str(_dict(getattr(context, "metadata", None)).get("locale") or "en")


class TrainerRule(ValidationRule):
    """Base of the ``trainer_spec`` rules.

    A subclass implements :meth:`findings`. No finding gives one passing
    result; each finding gives one failing result whose message is
    ``trainer.<rule>.<reason>`` and whose suggestion is
    ``trainer.<rule>.suggestion``.
    """

    standard = "trainer"
    category = RuleCategory.CONSISTENCY

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        """Yield every failure of this rule on ``data``."""
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Run :meth:`findings` and turn them into results."""
        locale = _locale(context)
        data = _dict(context.data)
        found = list(self.findings(data, context))
        if not found:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate("common.ok", locale=locale),
                )
            ]
        short = self.rule_id.split(".", 1)[1]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=f.severity or self.severity,
                category=self.category,
                passed=False,
                message=translate(f"trainer.{short}.{f.reason}", locale=locale, **f.params),
                element_ref=f.element_ref,
                details={"reason": f.reason, **{k: str(v) for k, v in f.params.items()}},
                suggestion=translate(f"trainer.{short}.suggestion", locale=locale),
            )
            for f in found
        ]


def _each_task(data: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any], str]]:
    for index, task in enumerate(_tasks(data)):
        yield index, task, _task_ref(task, index)


# ── Rules ────────────────────────────────────────────────────────────────────


class TaskOrderContiguous(TrainerRule):
    """Tasks are numbered 1..N in order and their ids are unique."""

    rule_id = "trainer.task_order_contiguous"
    name = "Trainer tasks numbered 1..N"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        tasks = _tasks(data)
        numbers = [t.get("n") for t in tasks]
        if not tasks or numbers != list(range(1, len(tasks) + 1)):
            yield Finding("numbering", "tasks", {"numbers": numbers})
        seen: set[str] = set()
        for _i, task, ref in _each_task(data):
            if ref in seen:
                yield Finding("duplicate_id", f"tasks[{ref}]", {"task_id": ref})
            seen.add(ref)


class TaskIdFitsStorage(TrainerRule):
    """Course, version, task and answer names fit their ``oe_trainer_*`` columns."""

    rule_id = "trainer.task_id_fits_storage"
    name = "Trainer ids fit their columns"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        limits = COLUMN_LIMITS
        for field, value in (
            ("course_key", data.get("id")),
            ("version", data.get("version")),
            ("title", data.get("title")),
            ("language", data.get("language")),
        ):
            if isinstance(value, str) and len(value) > limits[field]:
                yield Finding(field, field, {"value": value, "length": len(value), "max": limits[field]})
        for _i, task, ref in _each_task(data):
            if len(ref) > limits["task_id"]:
                yield Finding("task_id", f"tasks[{ref}]", {"value": ref, "length": len(ref), "max": limits["task_id"]})
            for answer in _answers(task):
                name = _str(answer.get("name"))
                if len(name) > limits["answer_name"]:
                    yield Finding(
                        "answer_name",
                        f"tasks[{ref}].answer_key",
                        {"value": name[:40], "length": len(name), "max": limits["answer_name"]},
                    )


class OpensKnownLock(TrainerRule):
    """Every ``opens`` is a registered lock id; a badge names this course's badge."""

    rule_id = "trainer.opens_known_lock"
    name = "Trainer task opens a known lock"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        badge = _str(_dict(data.get("badge")).get("id"))
        for _i, task, ref in _each_task(data):
            lock_id = task.get("opens")
            if not isinstance(lock_id, str) or not is_known_lock_id(lock_id):
                yield Finding("unknown", f"tasks[{ref}].opens", {"task_id": ref, "lock_id": lock_id})
            elif is_badge_lock_id(lock_id) and lock_id != f"{BADGE_PREFIX}{badge}":
                yield Finding(
                    "wrong_badge", f"tasks[{ref}].opens", {"task_id": ref, "lock_id": lock_id, "badge": badge}
                )


class AnswerTolerancePositive(TrainerRule):
    """0 < tolerance <= 1, and no coarser than the precision of the value."""

    rule_id = "trainer.answer_tolerance_positive"
    name = "Trainer answer tolerance is sane"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            for answer in _answers(task):
                name = _str(answer.get("name"))
                tol = to_decimal(answer.get("tolerance"))
                where = f"tasks[{ref}].answer_key[{name}]"
                if tol is None or not (Decimal(0) < tol <= 1):
                    yield Finding(
                        "out_of_range", where, {"task_id": ref, "answer": name, "tolerance": answer.get("tolerance")}
                    )
                    continue
                value = to_decimal(answer.get("value"))
                if value is None or value == 0:
                    continue
                exponent = value.normalize().as_tuple().exponent
                step = Decimal(1).scaleb(min(int(exponent), 0)) if isinstance(exponent, int) else Decimal(1)
                if tol > step:
                    yield Finding("coarser", where, {"task_id": ref, "answer": name, "tolerance": tol, "value": value})


class AnswerNamesUnique(TrainerRule):
    """Answer names are unique within a task (ledger keys may repeat)."""

    rule_id = "trainer.answer_names_unique"
    name = "Trainer answer names unique"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            seen: set[str] = set()
            for answer in _answers(task):
                name = _str(answer.get("name"))
                if name in seen:
                    yield Finding("duplicate", f"tasks[{ref}].answer_key[{name}]", {"task_id": ref, "answer": name})
                seen.add(name)


class EveryAnswerGraded(TrainerRule):
    """``graded_by`` is ``panel`` | ``both`` | ``probe:<i>`` and means it (decision 11)."""

    rule_id = "trainer.every_answer_graded"
    name = "Trainer answer grading source"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            readbacks = _dicts(task.get("readback"))
            for answer in _answers(task):
                name = _str(answer.get("name"))
                key = answer.get("ledger_key")
                where = f"tasks[{ref}].answer_key[{name}]"
                try:
                    grading = parse_graded_by(answer.get("graded_by"))
                except ValueError:
                    yield Finding(
                        "invalid", where, {"task_id": ref, "answer": name, "graded_by": answer.get("graded_by")}
                    )
                    continue
                if grading.kind == "probe":
                    index = grading.readback_index or 0
                    if index >= len(readbacks):
                        yield Finding("index_out_of_range", where, {"task_id": ref, "answer": name, "index": index})
                    elif key not in _list(readbacks[index].get("expects")):
                        yield Finding(
                            "ledger_mismatch",
                            where,
                            {"task_id": ref, "answer": name, "index": index, "ledger_key": key},
                        )
                elif grading.kind == "both":
                    readers = [r for r in readbacks if key in _list(r.get("expects"))]
                    if len(readers) != 1:
                        yield Finding(
                            "both_needs_one_reader", where, {"task_id": ref, "answer": name, "count": len(readers)}
                        )


def _numbers_checks(task: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in _dicts(task.get("checks")) if c.get("kind") == "numbers"]


def _answers_named(task: dict[str, Any], item: Any) -> list[dict[str, Any]]:
    return [a for a in _answers(task) if item in (a.get("name"), a.get("ledger_key"))]


class NumbersCheckSubsetOfAnswerKey(TrainerRule):
    """Every field of a numbers check is an answer of the same task."""

    rule_id = "trainer.numbers_check_subset_of_answer_key"
    name = "Trainer numbers check resolves"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            for check in _numbers_checks(task):
                for item in _list(check.get("expects")):
                    if not _answers_named(task, item):
                        yield Finding(
                            "unresolved",
                            f"tasks[{ref}].checks[{check.get('id')}]",
                            {"task_id": ref, "check": check.get("id"), "name": item},
                        )


class NumbersCheckListsOnlyPanelAnswers(TrainerRule):
    """A numbers check never asks the learner to type a probe-only answer."""

    rule_id = "trainer.numbers_check_lists_only_panel_answers"
    name = "Trainer numbers check asks only panel answers"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            for check in _numbers_checks(task):
                for item in _list(check.get("expects")):
                    matches = _answers_named(task, item)
                    if not matches:
                        continue
                    gradings = []
                    for answer in matches:
                        try:
                            gradings.append(parse_graded_by(answer.get("graded_by")))
                        except ValueError:
                            gradings.append(None)
                    if not any(g is not None and g.has_panel_field for g in gradings):
                        yield Finding(
                            "probe_only",
                            f"tasks[{ref}].checks[{check.get('id')}]",
                            {
                                "task_id": ref,
                                "check": check.get("id"),
                                "name": item,
                                "graded_by": matches[0].get("graded_by"),
                            },
                        )


class ReadbackResolvesInFile(TrainerRule):
    """A probed readback's expected value is stated in this file."""

    rule_id = "trainer.readback_resolves_in_file"
    name = "Trainer readback expectation resolves"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        ledger = build_ledger(data)
        for _i, task, ref in _each_task(data):
            for index, readback in enumerate(_dicts(task.get("readback"))):
                probe = _probe(readback)
                if probe is None:
                    continue
                where = f"tasks[{ref}].readback[{index}]"
                expects = [k for k in _list(readback.get("expects")) if isinstance(k, str)]
                has_inline = probe.get("expect") is not None
                if not expects and not has_inline:
                    yield Finding("expects_nothing", where, {"task_id": ref, "readback": index})
                    continue
                for key in expects:
                    if key not in ledger:
                        if not has_inline:
                            yield Finding("unresolved", where, {"task_id": ref, "readback": index, "ledger_key": key})
                        continue
                    if has_inline:
                        entry = ledger[key]
                        # The tolerance is the answer's, written in the
                        # ledger entry's unit, so the entry is the expected side.
                        if (
                            values_match(
                                entry.value,
                                probe["expect"],
                                kind=probe_field_kind(*_probe_field(probe)),
                                tolerance=_tolerance_for(task, readback),
                                unit=entry.unit,
                                observed_unit=probe.get("unit") if probe.get("unit") in _UNITS else None,
                                currency=_currency(data),
                            )
                            is not True
                        ):
                            yield Finding("disagree", where, {"task_id": ref, "readback": index, "ledger_key": key})


def _graded_readback_indexes(task: dict[str, Any]) -> set[int]:
    readbacks = _dicts(task.get("readback"))
    graded: set[int] = set()
    for answer in _answers(task):
        try:
            grading = parse_graded_by(answer.get("graded_by"))
        except ValueError:
            continue
        if grading.kind == "probe" and grading.readback_index is not None:
            graded.add(grading.readback_index)
        elif grading.kind == "both":
            graded |= {i for i, r in enumerate(readbacks) if answer.get("ledger_key") in _list(r.get("expects"))}
    return graded


def graded_readback_indexes(task: dict[str, Any]) -> set[int]:
    """Readbacks that can fail the task: an answer grades them, or ``probe.gate`` is true (decision 19).

    Any other probed readback is informational; it is shown as match or
    mismatch and never fails the task.
    """
    gated = {i for i, r in enumerate(_dicts(task.get("readback"))) if _dict(r.get("probe")).get("gate") is True}
    return _graded_readback_indexes(task) | gated


class ReadbackHasProbe(TrainerRule):
    """A graded readback has a probe; an ungraded one without a probe is flagged."""

    rule_id = "trainer.readback_has_probe"
    name = "Trainer readback has a probe"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            graded = graded_readback_indexes(task)
            for index, readback in enumerate(_dicts(task.get("readback"))):
                if _probe(readback) is not None:
                    continue
                where = f"tasks[{ref}].readback[{index}]"
                if index in graded:
                    yield Finding("graded_unprobed", where, {"task_id": ref, "readback": index})
                else:
                    yield Finding("unprobed", where, {"task_id": ref, "readback": index}, Severity.WARNING)


class ProbeArgsFrozen(TrainerRule):
    """Probe types are on the closed list; args match the frozen models."""

    rule_id = "trainer.probe_args_frozen"
    name = "Trainer probe arguments"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            for index, readback in enumerate(_dicts(task.get("readback"))):
                if "probe" not in readback:
                    continue
                probe = readback.get("probe")
                where = f"tasks[{ref}].readback[{index}].probe"
                kind = _dict(probe).get("type")
                if kind not in PROBE_TYPE_NAMES:
                    yield Finding("unknown_type", where, {"task_id": ref, "readback": index, "type": kind})
                    continue
                try:
                    validate_probe(probe)
                except ValidationError as exc:
                    errors = "; ".join(
                        f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in exc.errors()[:3]
                    )
                    yield Finding("bad_args", where, {"task_id": ref, "readback": index, "type": kind, "error": errors})


def _erp_graded_readbacks(task: dict[str, Any], ledger: dict[str, LedgerEntry]) -> list[int]:
    graded = graded_readback_indexes(task)
    return [
        i
        for i, r in enumerate(_dicts(task.get("readback")))
        if i in graded
        and _dict(_probe(r)).get("type") in ERP_PROBE_TYPE_NAMES
        and readback_expectation(r, ledger) is not None
    ]


class TaskHasProbeGradedItem(TrainerRule):
    """Every task grades at least one item through a probe that reads the ERP."""

    rule_id = "trainer.task_has_probe_graded_item"
    name = "Trainer task touches the ERP"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        ledger = build_ledger(data)
        for _i, task, ref in _each_task(data):
            if not _erp_graded_readbacks(task, ledger):
                yield Finding("fail", f"tasks[{ref}]", {"task_id": ref})


class TaskDiscriminatesSeedState(TrainerRule):
    """At least one ERP-probed item per task differs from the untouched project."""

    rule_id = "trainer.task_discriminates_seed_state"
    name = "Trainer task cannot pass with the ERP untouched"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        items = discriminating_items(data)
        for index, task, ref in _each_task(data):
            task_items = items.get(index, [])
            if task_items and not any(differs for _r, differs in task_items):
                yield Finding("fail", f"tasks[{ref}]", {"task_id": ref, "count": len(task_items)})


def _field_answers(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for answer in _answers(task):
        for key in (answer.get("name"), answer.get("ledger_key")):
            if isinstance(key, str):
                out.setdefault(key, answer)
    return out


class DiagnosisAppliesToResolves(TrainerRule):
    """``applies_to`` names an answer, a numbers-check field or a readback (``rb<i>``)."""

    rule_id = "trainer.diagnosis_applies_to_resolves"
    name = "Trainer diagnosis field resolves"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            names = set(_field_answers(task))
            names |= {i for c in _numbers_checks(task) for i in _list(c.get("expects")) if isinstance(i, str)}
            names |= {f"rb{i}" for i in range(len(_dicts(task.get("readback"))))}
            for diagnosis in _dicts(task.get("diagnoses")):
                if diagnosis.get("applies_to") not in names:
                    yield Finding(
                        "fail",
                        f"tasks[{ref}].diagnoses[{diagnosis.get('id')}]",
                        {"task_id": ref, "diagnosis": diagnosis.get("id"), "field": diagnosis.get("applies_to")},
                    )


class DiagnosisUniquePerField(TrainerRule):
    """Within one field, wrong values are apart from the right ones and each other."""

    rule_id = "trainer.diagnosis_unique_per_field"
    name = "Trainer diagnoses cannot collide"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            answers = _field_answers(task)
            by_field: dict[str, list[tuple[str, Decimal]]] = {}
            for diagnosis in _dicts(task.get("diagnoses")):
                wrong = to_decimal(diagnosis.get("wrong_value"))
                field = diagnosis.get("applies_to")
                if wrong is not None and isinstance(field, str) and field in answers:
                    by_field.setdefault(field, []).append((_str(diagnosis.get("id")), wrong))
            for field, wrongs in by_field.items():
                answer = answers[field]
                tol = to_decimal(answer.get("tolerance")) or _DEFAULT_TOLERANCE
                rights = [to_decimal(answer.get("value"))]
                rights += [to_decimal(_dict(a).get("value", a)) for a in _list(answer.get("also_accepted"))]
                for i, (diag_id, wrong) in enumerate(wrongs):
                    where = f"tasks[{ref}].diagnoses[{diag_id}]"
                    if any(r is not None and abs(wrong - r) <= tol for r in rights):
                        yield Finding("equals_correct", where, {"task_id": ref, "diagnosis": diag_id, "field": field})
                    for other_id, other in wrongs[i + 1 :]:
                        if abs(wrong - other) <= tol:
                            yield Finding(
                                "collide",
                                where,
                                {"task_id": ref, "diagnosis": diag_id, "other": other_id, "field": field},
                            )


class DiagnosisWrongValueNumeric(TrainerRule):
    """A diagnosis has a numeric wrong value, or is a convention with ``when``."""

    rule_id = "trainer.diagnosis_wrong_value_numeric"
    name = "Trainer diagnosis wrong value"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            for diagnosis in _dicts(task.get("diagnoses")):
                if _is_number(diagnosis.get("wrong_value")):
                    continue
                convention = (
                    diagnosis.get("kind") == "convention"
                    and diagnosis.get("wrong_value") is None
                    and bool(_str(diagnosis.get("when")))
                )
                if not convention:
                    yield Finding(
                        "fail",
                        f"tasks[{ref}].diagnoses[{diagnosis.get('id')}]",
                        {"task_id": ref, "diagnosis": diagnosis.get("id")},
                    )


class SingleCorrectOption(TrainerRule):
    """Each question has exactly one correct option and feedback on every option."""

    rule_id = "trainer.single_correct_option"
    name = "Trainer question has one right answer"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            for question in ("trace_question", "explain_question"):
                options = _dicts(_dict(task.get(question)).get("options"))
                where = f"tasks[{ref}].{question}"
                count = sum(1 for o in options if o.get("correct") is True)
                if count != 1:
                    yield Finding("correct_count", where, {"task_id": ref, "question": question, "count": count})
                for index, option in enumerate(options):
                    if not _str(option.get("feedback")).strip():
                        yield Finding(
                            "feedback_missing", where, {"task_id": ref, "question": question, "option": index}
                        )


def ledger_label_map(tasks: Iterable[Any]) -> dict[str, str]:
    """Fallback screen names of ledger keys, from the course itself (decision 47).

    A readback that reads exactly one key names it by its ``what``; a given
    with a ``ledger_key`` names it by its ``name``. The first source in task
    order wins. A key the course names nowhere has no fallback.
    """
    labels: dict[str, str] = {}
    ordered = sorted(_dicts(list(tasks)), key=lambda t: t.get("n") if isinstance(t.get("n"), int) else 0)
    for task in ordered:
        for readback in _dicts(task.get("readback")):
            expects = [e for e in _list(readback.get("expects")) if isinstance(e, str)]
            what = _str(readback.get("what")).strip()
            if len(expects) == 1 and what:
                labels.setdefault(expects[0], what)
        for given in _dicts(task.get("given")):
            key, name = given.get("ledger_key"), _str(given.get("name")).strip()
            if isinstance(key, str) and key and name:
                labels.setdefault(key, name)
    return labels


class RelatedValueLabelled(TrainerRule):
    """Every related value of a diagnosis has a screen name (decision 47).

    The name comes from the value's own ``label``, else from a readback or a
    given that names the same ledger key. Without either the dock hides the
    row, so the learner never sees the figure the diagnosis points at.
    """

    rule_id = "trainer.related_value_unlabelled"
    name = "Trainer related values have a label"
    severity = Severity.WARNING

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        fallback = ledger_label_map(_tasks(data))
        for _i, task, ref in _each_task(data):
            for diagnosis in _dicts(task.get("diagnoses")):
                for item in _dicts(diagnosis.get("related")):
                    if _str(item.get("label")).strip() or item.get("name") in fallback:
                        continue
                    yield Finding(
                        "fail",
                        f"tasks[{ref}].diagnoses[{diagnosis.get('id')}].related[{item.get('name')}]",
                        {"task_id": ref, "diagnosis": diagnosis.get("id"), "name": item.get("name")},
                    )


class CheckIdPrefixMatchesTask(TrainerRule):
    """Check ids start with ``t<n>-`` (renumbering residue does not grade wrong)."""

    rule_id = "trainer.check_id_prefix_matches_task"
    name = "Trainer check id prefix"
    severity = Severity.WARNING
    category = RuleCategory.STRUCTURE

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            prefix = f"t{task.get('n')}-"
            for check in _dicts(task.get("checks")):
                if not _str(check.get("id")).startswith(prefix):
                    yield Finding(
                        "fail", f"tasks[{ref}].checks", {"task_id": ref, "check": check.get("id"), "prefix": prefix}
                    )


class SeedStageResolvable(TrainerRule):
    """Every seed block has a stage of the decision-12 grammar, on a real task."""

    rule_id = "trainer.seed_stage_resolvable"
    name = "Trainer seed stage"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        seed = _dict(data.get("seed"))
        count = len(_tasks(data))
        blocks: list[tuple[str, dict[str, Any], bool]] = [
            (name, _dict(seed.get(name)), True) for name in _SEED_BLOCKS_WITH_STAGE if isinstance(seed.get(name), dict)
        ]
        for name in _SEED_LISTS_WITH_STAGE:
            blocks += [(f"{name}[{i}]", item, True) for i, item in enumerate(_dicts(seed.get(name)))]
        for name in ("parties", "users"):
            blocks += [(f"{name}[{i}]", item, False) for i, item in enumerate(_dicts(seed.get(name)))]
        for name in ("subcontract", "operation"):
            if isinstance(seed.get(name), dict) and "stage" in seed[name]:
                blocks.append((name, seed[name], False))
        for name, block, required in blocks:
            where = f"seed.{name}"
            if "stage" not in block:
                if required:
                    yield Finding("missing", where, {"block": name})
                continue
            try:
                stage = parse_stage(block.get("stage"))
            except ValueError:
                yield Finding("invalid", where, {"block": name, "stage": block.get("stage")})
                continue
            if stage.task_n is not None and stage.task_n > count:
                yield Finding("task_out_of_range", where, {"block": name, "stage": block.get("stage"), "count": count})


def _rates(data: dict[str, Any]) -> Iterator[tuple[str, Any, Any]]:
    """``(where, value, unit)`` of every place that states a rate with a unit slot."""
    for rule in _dicts(data.get("rules")):
        yield f"rules[{rule.get('key')}]", rule.get("value"), rule.get("unit")
    for _i, task, ref in _each_task(data):
        for answer in _answers(task):
            if "unit" in answer:
                yield f"tasks[{ref}].answer_key[{answer.get('name')}]", answer.get("value"), answer.get("unit")
    retention = _dict(_dict(data.get("seed")).get("contract")).get("retention_percent")
    if isinstance(retention, dict):
        yield "seed.contract.retention_percent", retention.get("value"), retention.get("unit")


def _keys_used_as_rates(data: dict[str, Any]) -> set[str]:
    """Rule keys the file uses as a rate: named by ``rate_key`` / ``rule_key``
    on a rate, or expected by a readback of an ERP percent column.
    """
    keys: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for name in ("rate_key", "rule_key"):
                if isinstance(node.get(name), str):
                    keys.add(node[name])
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(data.get("seed"))
    for _i, task, _ref in _each_task(data):
        walk(task.get("given"))
        for readback in _dicts(task.get("readback")):
            if _probe_field(_probe(readback) or {}) in PERCENT_PROBE_FIELDS:
                keys |= {k for k in _list(readback.get("expects")) if isinstance(k, str)}
    return keys


def _numeric_leaves(value: Any) -> list[Decimal]:
    if isinstance(value, dict):
        return [d for v in value.values() for d in _numeric_leaves(v)]
    if isinstance(value, list):
        return [d for v in value for d in _numeric_leaves(v)]
    number = to_decimal(value) if not isinstance(value, str) else None
    return [number] if number is not None else []


class RateUnitExplicit(TrainerRule):
    """Every rate states ``percent`` or ``fraction``; a fraction is never above 1."""

    rule_id = "trainer.rate_unit_explicit"
    name = "Trainer rate unit"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        rate_keys = _keys_used_as_rates(data)
        for where, value, unit in _rates(data):
            leaves = _numeric_leaves(value)
            if unit is None:
                key = where[len("rules[") : -1] if where.startswith("rules[") else None
                is_rate = key in rate_keys or any(_looks_like_fraction(leaf) for leaf in leaves)
                if key is not None and leaves and is_rate:
                    yield Finding("missing", where, {"where": where})
                continue
            if unit not in _UNITS:
                yield Finding("invalid", where, {"where": where, "unit": unit})
                continue
            if unit == "fraction":
                # ``unit`` covers every number in ``value``; a composite value
                # that mixes rates with money must split, not hide the money.
                above = [leaf for leaf in leaves if abs(leaf) > 1]
                if above:
                    yield Finding("fraction_above_one", where, {"where": where, "value": above[0]})
        for _i, task, ref in _each_task(data):
            for index, readback in enumerate(_dicts(task.get("readback"))):
                probe = _probe(readback) or {}
                expect = to_decimal(probe.get("expect")) if not isinstance(probe.get("expect"), str) else None
                if probe.get("unit") == "fraction" and expect is not None and abs(expect) > 1:
                    where = f"tasks[{ref}].readback[{index}]"
                    yield Finding("fraction_above_one", where, {"where": where, "value": expect})


def _looks_like_fraction(value: Decimal | None) -> bool:
    return value is not None and Decimal(0) < abs(value) <= 1


class PercentNotWrittenAsFraction(TrainerRule):
    """A value bound for an ERP percent column (0-100) does not look like a fraction."""

    rule_id = "trainer.percent_not_written_as_fraction"
    name = "Trainer percent written as a fraction"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        contract = _dict(_dict(data.get("seed")).get("contract"))
        retention = contract.get("retention_percent")
        if isinstance(retention, dict):
            if retention.get("unit") != "fraction" and _looks_like_fraction(to_decimal(retention.get("value"))):
                yield Finding(
                    "fail",
                    "seed.contract.retention_percent",
                    {"where": "seed.contract.retention_percent", "value": retention.get("value")},
                )
        elif _looks_like_fraction(to_decimal(retention)):
            yield Finding(
                "fail",
                "seed.contract.retention_percent",
                {"where": "seed.contract.retention_percent", "value": retention},
            )
        if _looks_like_fraction(to_decimal(contract.get("vat_rate_percent"))):
            yield Finding(
                "fail",
                "seed.contract.vat_rate_percent",
                {"where": "seed.contract.vat_rate_percent", "value": contract.get("vat_rate_percent")},
            )
        for _i, task, ref in _each_task(data):
            readbacks = _dicts(task.get("readback"))
            for index, readback in enumerate(readbacks):
                probe = _probe(readback) or {}
                if _probe_field(probe) not in PERCENT_PROBE_FIELDS or probe.get("unit") == "fraction":
                    continue
                expect = probe.get("expect")
                if not isinstance(expect, (str, bool)) and _looks_like_fraction(to_decimal(expect)):
                    where = f"tasks[{ref}].readback[{index}]"
                    yield Finding("fail", where, {"where": where, "value": expect})
            for answer in _answers(task):
                try:
                    grading = parse_graded_by(answer.get("graded_by"))
                except ValueError:
                    continue
                if (
                    grading.kind != "probe"
                    or grading.readback_index is None
                    or grading.readback_index >= len(readbacks)
                ):
                    continue
                probe = _probe(readbacks[grading.readback_index]) or {}
                if _probe_field(probe) in PERCENT_PROBE_FIELDS and answer.get("unit") != "fraction":
                    if _looks_like_fraction(to_decimal(answer.get("value"))):
                        where = f"tasks[{ref}].answer_key[{answer.get('name')}]"
                        yield Finding("fail", where, {"where": where, "value": answer.get("value")})


class EinvoiceVatResolvable(TrainerRule):
    """``seed.contract.vat_rate_percent`` is a number (GB, DE, FR) or null with ``vat_note``."""

    rule_id = "trainer.einvoice_vat_resolvable"
    name = "Trainer contract VAT"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        contract = _dict(_dict(data.get("seed")).get("contract"))
        if not contract:
            return
        country = _str(data.get("country")).upper()
        where = "seed.contract.vat_rate_percent"
        if "vat_rate_percent" not in contract:
            yield Finding("missing", where, {"country": country})
            return
        raw = contract["vat_rate_percent"]
        if raw is None:
            if country in _VAT_NUMBER_REQUIRED:
                yield Finding("number_required", where, {"country": country})
            elif not _str(contract.get("vat_note")).strip():
                yield Finding("null_needs_note", where, {"country": country})
            return
        value = to_decimal(raw) if not isinstance(raw, (str, dict, list)) else None
        if value is None:
            yield Finding("not_a_number", where, {"value": raw})
        elif not (Decimal(0) <= value <= 100):
            yield Finding("out_of_range", where, {"value": value})


def _ensure_builtin_rules(rule_ids: Iterable[str]) -> None:
    if all(rule_registry.get_rule(r) is not None for r in rule_ids):
        return
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()


class SovSignable(TrainerRule):
    """Every SOV line can pass the contract signing gate of the course's country.

    The line needs a non-empty ``unit`` and ``metadata.classification.<key>``
    for its country (decision 18). The codes are then run through the same
    platform classification rules the signing gate runs (contract lines are
    mapped to positions as ``ContractsService._contract_lines_as_positions``
    maps them), so an invalid code fails here and not at signing. Only those
    classification rules run: the rest of each country pack (bill quality,
    statutory checks) is out of a course file's reach.
    """

    rule_id = "trainer.sov_signable"
    name = "Trainer contract can be signed"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        contract = _dict(_dict(data.get("seed")).get("contract"))
        if not contract:
            return
        lines = _dicts(contract.get("schedule_of_values"))
        if not lines:
            yield Finding("no_lines", "seed.contract.schedule_of_values", {})
            return
        country = _str(data.get("country")).upper()
        standard, platform_rules = SOV_CLASSIFICATION_BY_COUNTRY.get(country, ("", ()))
        allowed = {standard} if standard else {s for s, _r in SOV_CLASSIFICATION_BY_COUNTRY.values()}
        for line in lines:
            code = line.get("code")
            where = f"seed.contract.schedule_of_values[{code}]"
            if "classification" in line:
                yield Finding("flat_classification", where, {"line": code})
            if not _str(line.get("unit")).strip():
                yield Finding("unit_missing", where, {"line": code})
            classification = _dict(_dict(line.get("metadata")).get("classification"))
            if not any(_str(classification.get(s)).strip() for s in allowed):
                yield Finding("classification_missing", where, {"line": code, "standard": "|".join(sorted(allowed))})
        yield from self._platform_findings(lines, platform_rules)

    def _platform_findings(self, lines: list[dict[str, Any]], rule_ids: tuple[str, ...]) -> Iterator[Finding]:
        if not rule_ids:
            return
        import asyncio

        _ensure_builtin_rules(rule_ids)
        positions = [
            {
                "id": _str(line.get("code")),
                "ordinal": _str(line.get("code")),
                "description": _str(line.get("description")),
                "unit": line.get("unit"),
                "quantity": str(line.get("quantity") if line.get("quantity") is not None else 1),
                "unit_rate": str(line.get("amount") if line.get("amount") is not None else 0),
                "total": str(line.get("amount") if line.get("amount") is not None else 0),
                "classification": _dict(_dict(line.get("metadata")).get("classification")),
                "parent_id": None,
                "type": "position",
            }
            for line in lines
        ]
        context = ValidationContext(data={"positions": positions}, metadata={"locale": "en"})
        for rule_id in rule_ids:
            rule = rule_registry.get_rule(rule_id)
            if rule is None:
                yield Finding("platform_rule_missing", "seed.contract.schedule_of_values", {"rule": rule_id})
                continue
            results = _run_sync(rule.validate(context), asyncio)
            for result in results:
                if not result.passed and result.severity == Severity.ERROR:
                    yield Finding(
                        "platform_rule",
                        f"seed.contract.schedule_of_values[{result.element_ref}]",
                        {"line": result.element_ref, "rule": rule_id},
                    )


def _run_sync(coro: Any, asyncio: Any) -> list[RuleResult]:
    """Run a platform rule's coroutine from inside a sync ``findings``.

    The built-in classification rules are pure (no I/O) and finish on the
    first step, so driving the coroutine by hand never blocks the caller's
    event loop.
    """
    try:
        coro.send(None)
    except StopIteration as stop:
        return list(stop.value or [])
    coro.close()
    msg = "a platform classification rule awaited I/O"
    raise RuntimeError(msg)


class ProjectRuleSetsKnown(TrainerRule):
    """Every name in ``seed.project.validation_rule_sets`` is a registered rule set.

    The engine skips an unknown rule set name with a log line and no red
    anywhere, so a misspelt name would leave the learner's project silently
    unvalidated. Only the built-in sets are certain to be registered when a
    course loads; a name that a module registers later is flagged for a
    human to confirm rather than failed, hence WARNING.
    """

    rule_id = "trainer.project_rule_sets_known"
    name = "Trainer project rule sets are registered"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        names = _list(_dict(_dict(data.get("seed")).get("project")).get("validation_rule_sets"))
        if not names:
            return
        _ensure_builtin_rules(("boq_quality.position_has_quantity",))
        known = set(rule_registry.list_rule_sets())
        for name in names:
            if not isinstance(name, str) or name not in known:
                yield Finding("unknown", "seed.project.validation_rule_sets", {"name": name})


class GradedItemsNonzero(TrainerRule):
    """Each task grades at least one item; a check over zero items never passes."""

    rule_id = "trainer.graded_items_nonzero"
    name = "Trainer task grades something"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        for _i, task, ref in _each_task(data):
            count = len(_dicts(task.get("answer_key")))
            graded = graded_readback_indexes(task)
            count += sum(1 for i, r in enumerate(_dicts(task.get("readback"))) if i in graded and _probe(r) is not None)
            count += sum(1 for q in ("trace_question", "explain_question") if _dicts(_dict(task.get(q)).get("options")))
            if count == 0:
                yield Finding("fail", f"tasks[{ref}]", {"task_id": ref})


_VARIATION_COST_FIELDS = {
    ("variation.request", "estimated_cost_impact"),
    ("variation.request", "agreed_cost_impact"),
    ("variation.order", "final_cost_impact"),
}


class VariationUnderApprovalThreshold(TrainerRule):
    """A course variation stays under the threshold one manager may approve alone."""

    rule_id = "trainer.variation_under_approval_threshold"
    name = "Trainer variation under the approval threshold"
    severity = Severity.WARNING

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        ledger = build_ledger(data)
        for _i, task, ref in _each_task(data):
            for index, readback in enumerate(_dicts(task.get("readback"))):
                probe = _probe(readback)
                if probe is None or _probe_field(probe) not in _VARIATION_COST_FIELDS:
                    continue
                expected = readback_expectation(readback, ledger)
                value = to_decimal(expected.value) if expected and not isinstance(expected.value, str) else None
                if value is not None and abs(value) > VARIATION_APPROVAL_THRESHOLD:
                    yield Finding(
                        "fail",
                        f"tasks[{ref}].readback[{index}]",
                        {"task_id": ref, "value": value, "threshold": VARIATION_APPROVAL_THRESHOLD},
                    )


def _money_values(seed: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    contract = _dict(seed.get("contract"))
    yield "seed.contract.value", _dict(contract.get("value")).get("value")
    yield "seed.contract.schedule_total", _dict(contract.get("schedule_total")).get("value")
    for line in _dicts(contract.get("schedule_of_values")):
        yield f"seed.contract.schedule_of_values[{line.get('code')}].amount", line.get("amount")
    package = _dict(seed.get("bid_package"))
    yield "seed.bid_package.budget", _dict(package.get("budget")).get("value")
    for bid in _dicts(package.get("bids")):
        yield f"seed.bid_package.bids[{bid.get('bidder')}].total", bid.get("total")
        for line in _dicts(bid.get("lines")):
            yield f"seed.bid_package.bids[{bid.get('bidder')}].lines[{line.get('code')}].amount", line.get("amount")
    for index, period in enumerate(_dicts(seed.get("progress_readings"))):
        for reading in _dicts(period.get("readings")) + _dicts(period.get("by_hand")):
            yield f"seed.progress_readings[{index}].readings[{reading.get('line_code')}].value", reading.get("value")


class MoneyScale(TrainerRule):
    """Seeded money has no more decimals than the course currency."""

    rule_id = "trainer.money_scale"
    name = "Trainer money scale"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        from app.core.currency_registry import minor_units

        places = minor_units(_str(data.get("currency")) or None)
        for where, raw in _money_values(_dict(data.get("seed"))):
            value = to_decimal(raw) if not isinstance(raw, str) else None
            if value is None:
                continue
            exponent = value.normalize().as_tuple().exponent
            if isinstance(exponent, int) and -exponent > places:
                yield Finding("fail", where, {"where": where, "value": value, "places": places})


class VersionNotBumped(TrainerRule):
    """New content under a (course, version) learners may have pinned is refused.

    The loader passes the stored sha256 as ``metadata["previous_sha256"]``.
    """

    rule_id = "trainer.version_not_bumped"
    name = "Trainer course version bumped"
    severity = Severity.ERROR

    def findings(self, data: dict[str, Any], context: ValidationContext) -> Iterable[Finding]:
        meta = _dict(getattr(context, "metadata", None))
        previous, current = meta.get("previous_sha256"), meta.get("sha256")
        if previous and current and previous != current:
            yield Finding("fail", "version", {"course": data.get("id"), "version": data.get("version")})


#: Every rule of the set, in report order.
TRAINER_RULES: tuple[type[TrainerRule], ...] = (
    TaskOrderContiguous,
    TaskIdFitsStorage,
    OpensKnownLock,
    AnswerTolerancePositive,
    AnswerNamesUnique,
    EveryAnswerGraded,
    NumbersCheckSubsetOfAnswerKey,
    NumbersCheckListsOnlyPanelAnswers,
    ReadbackResolvesInFile,
    ReadbackHasProbe,
    ProbeArgsFrozen,
    TaskHasProbeGradedItem,
    TaskDiscriminatesSeedState,
    DiagnosisAppliesToResolves,
    DiagnosisUniquePerField,
    DiagnosisWrongValueNumeric,
    RelatedValueLabelled,
    SingleCorrectOption,
    CheckIdPrefixMatchesTask,
    SeedStageResolvable,
    RateUnitExplicit,
    PercentNotWrittenAsFraction,
    EinvoiceVatResolvable,
    SovSignable,
    ProjectRuleSetsKnown,
    GradedItemsNonzero,
    VariationUnderApprovalThreshold,
    MoneyScale,
    VersionNotBumped,
)


def register_trainer_rules() -> None:
    """Idempotently register the ``trainer_spec`` rule set (keyed on rule_id)."""
    for rule_class in TRAINER_RULES:
        rule_registry.register(rule_class(), rule_sets=[TRAINER_SPEC_RULE_SET])
