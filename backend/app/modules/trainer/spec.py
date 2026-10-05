# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic v2 models of a course file, and the frozen probe arguments.

A course file is JSON written by course authors. The loader reads it with
``json.loads(parse_float=Decimal)``, runs :func:`normalise_course_dict` (pure,
dict to dict) and then validates the result twice: against :class:`CourseSpec`
here (the shape) and against the ``trainer_spec`` rule set in
``validators.py`` (the meaning). Both run on the same normalised dict, so a
file that fails the shape still gets a verdict from every rule.

Key policy (interface decisions 9 and 18):

* The machine sections (tasks, answer_key, readback, seed, rules, diagnoses),
  the root and every model below are ``extra="forbid"``. An unknown key is an
  error, never a silent pass.
* Authoring-only material lives under the root ``authoring`` object or under a
  key that starts with ``_``. :func:`normalise_course_dict` removes both, at
  every depth and inside opaque blobs too, so neither reaches the stored spec
  nor a learner. Keys that end in ``_note`` are authoring-only as well and must
  move; the one exception is ``seed.contract.vat_note`` (decision 14).
* Opaque blobs the engine never reads stay ``Any``: ``sources``,
  ``constants``, ``conventions``, ``status_vocabulary``, ``rules[].value``,
  ``tasks[].erp_fit``, ``tasks[].dc4_step``, ``tasks[].panel_notes``,
  ``tasks[].video``, ``seed.subcontract``, ``seed.operation``,
  ``seed.boq.app_<country>_template_reference`` and ``schema_additions_vs_uk``.
* Progress readings and instructed changes have ONE canonical shape, the
  lists ``seed.progress_readings[]`` (one entry per valuation period, each with
  its own ``stage`` and ``period``) and ``seed.variations[]`` (one entry per
  instructed change, each with its own ``stage``). The country-named keys of
  the first drafts (``progress_readings_valuation_1``, ``change_order_1``,
  ...) are refused with a message that names the canonical key; there are no
  aliases. A reading's percentage is ``percent_complete`` (the ERP column),
  never ``percent``. The seeder stamps each reading's ``recorded_at`` inside
  its claim period (decision 20: default ``period_to`` minus one day, 12:00
  UTC, never after ``period_to`` 23:59:59.999999 UTC); a course file does not
  carry ``recorded_at``.
* A readback is graded when an answer points at it (``probe:<i>`` or
  ``both``) or when its probe says ``gate: true`` (decision 19, the flag
  sits inside the probe object next to ``expect``). A probed readback
  with neither is informational: the panel shows match or mismatch, and it
  never fails the task nor counts as the task's probe-graded item.
* BOQ positions carry their classification as
  ``seed.boq.positions[].classification`` (``{standard: code}``, the
  ``oe_boq_position.classification`` JSON), and the project may name its
  ``validation_rule_sets``; the ``trainer.project_rule_sets_known`` rule
  checks every name against the registry.

Grammars:

* ``stage`` (decision 12): ``on_enrol`` | ``on_unlock(<task number>)``.
* ``graded_by`` (decision 11): ``panel`` (typed in the panel only, for figures
  the ERP cannot compute) | ``probe:<readback index>`` (read from the ERP only,
  no panel field) | ``both`` (typed in the panel AND read by exactly one
  readback that expects the same ledger key; both must match).
* Rate ``unit``: ``percent`` | ``fraction``. The ERP stores percent
  (``Contract.retention_percent`` Numeric(5,2), ``metadata.einvoice.vat_rate``,
  ``BOQMarkup.percentage``); :func:`to_percent` converts a fraction.
* Seeded refs (decision 10): ``boq.main`` (or ``boq.<name>`` for a second
  bill), ``bid_package.main``, ``contract.main``, always in the typed args
  ``boq_ref`` / ``package_ref`` / ``contract_ref``.
* Selectors (``claim_selector``, ``variation_ref``): ``"latest"`` or an integer
  ``n >= 1``, the n-th object in creation order within its scope. For claims
  that is the claim numbered ``PC-{n:04d}``, because ``next_claim_number``
  (``contracts/repository.py``) numbers a contract's claims ``count + 1``.
  For ``variation.order`` it is the n-th order ON THE SEEDED CONTRACT
  (``affected_contract_id``) in creation order, NOT the order coded
  ``VO-{n:04d}``: order codes count every order of the project, so the first
  order on the contract may well be ``VO-0002``. For ``variation.request``
  (requests carry no contract) it is the n-th request of the project.

Frozen probe arguments (decision 16; one model per type in
``probe_types.PROBE_TYPES``, all ``extra="forbid"``):

=====================  =======================================================  ==========================================
type                   args                                                     reads
=====================  =======================================================  ==========================================
``boq.cost_breakdown`` ``boq_ref``, ``field`` = direct_cost | grand_total |     ``BOQService.get_cost_breakdown(boq_id)``
                       markup_amount, ``markup_name`` (required for             (``boq/service.py``): ``direct_cost``,
                       markup_amount, forbidden otherwise)                      ``grand_total``, ``markups[].amount``
                                                                                matched by name
``boq.position``       ``boq_ref``, ``ordinal``, ``field`` = quantity |         ``oe_boq_position.quantity / unit_rate /
                       unit_rate | total                                        total`` (String(50)) by ``boq_id`` and
                                                                                ``ordinal``
``boq.section_total``  ``boq_ref``, ``section_ordinal``                         sum of ``oe_boq_position.total`` of the
                                                                                leaf positions under the section row
                                                                                (``parent_id``, any depth). A section is
                                                                                what ``boq.service._is_section`` says: unit
                                                                                "" or "section" (trimmed, case-folded) AND
                                                                                quantity 0 AND unit_rate 0. A priced row
                                                                                with an empty unit is a position
``boq.markup``         ``boq_ref``, ``name``, ``field`` = percentage |          ``oe_boq_markup`` (``BOQMarkup``), active
                       fixed_amount | markup_type | apply_to | category |       rows with that name; more than one match is
                       sort_order                                               a probe error, never a guess
``bid.submission``     ``package_ref``, ``bidder_name``, ``field`` =            ``oe_bid_management_submission`` joined to
                       total_amount | is_valid                                  ``oe_bid_management_bidder.company_name``
``bid.leveling``       ``package_ref``, ``bidder_name``, ``field`` =            ``oe_bid_management_leveling`` after
                       raw_total | normalized_total | rank                      ``get_or_create_comparison`` +
                                                                                ``compute_leveling``
``bid.award``          ``package_ref``, ``field`` = awarded_bidder_name |       ``oe_bid_management_award.awarded_amount``,
                       awarded_amount                                           ``awarded_bidder_id`` -> bidder name
``contract.field``     ``contract_ref``, ``field`` = total_value |              ``oe_contracts_contract`` columns;
                       original_contract_value | retention_percent | status |   einvoice_vat_rate =
                       einvoice_vat_rate                                        ``metadata["einvoice"]["vat_rate"]``
``claim.field``        ``contract_ref``, ``claim_selector``, ``field`` =        ``oe_contracts_progress_claim``
                       gross_amount | retention_amount | prior_claims_total |
                       net_due | completed_stored_to_date |
                       retention_held_to_date | status
``claim.line``         ``contract_ref``, ``claim_selector``, ``line_code``,     ``oe_contracts_progress_claim_line`` joined
                       ``field`` = period_completed_value |                     to ``oe_contracts_contract_line.code`` on
                       cumulative_completed_value | materials_stored_value |    ``contract_line_id``
                       retention_to_date
``claim.lien_waiver``  ``contract_ref``, ``claim_selector``, ``field`` =        last entry of
                       amount | waiver_type | through_date                      ``claim.metadata["lien_waivers"]``
                                                                                (``attach_lien_waiver``); conditional is
                                                                                encoded in ``waiver_type``
``finance.receivable`` ``contract_ref``, ``claim_selector``, ``field`` =        ``FinanceService.get_receivable_for_claim``
                       amount_subtotal | tax_amount | amount_total              -> ``Invoice`` columns
``variation.request``  ``variation_ref``, ``field`` = estimated_cost_impact |   ``oe_variations_request`` in the learner's
                       agreed_cost_impact | status                              project; it has no contract column, so it
                                                                                takes no ``contract_ref``
``variation.order``    ``contract_ref``, ``variation_ref``, ``field`` =         ``oe_variations_order`` where
                       final_cost_impact | status                               ``affected_contract_id`` = the contract
``panel.answer``       ``answer_name``                                          ``oe_trainer_answer.value_text``
``panel.option``       ``question`` = trace | explain                           ``oe_trainer_answer.option_index``
=====================  =======================================================  ==========================================

Every ERP probe also filters by the enrolment's ``project_id``.

Replaced keys (decisions 19-27). A key the drafts used and a decision renamed
or dropped is refused with a message that names its replacement, so an author
reads the fix in the error instead of in this file:

=====================================  ===========================================================
refused                                write instead
=====================================  ===========================================================
``seed.<country-named block>``         ``seed.progress_readings[]`` / ``seed.variations[]`` (21)
``readings[].line``                    ``readings[].line_code`` (21)
``readings[].percent``                 ``readings[].percent_complete`` (21)
``readings[].recorded_at``             nothing: the seeder stamps it (20)
``progress_readings[].period``         ``period_from`` and ``period_to`` (21)
``readback[].gate``                    ``readback[].probe.gate`` (19)
``readback[].scale``                   nothing; move it under ``authoring`` (25)
``seed.navigation``                    nothing; move it under ``authoring`` (25)
``answer_key[].unit`` = EUR, days ...  ``answer_key[].display_unit`` (23)
``bids[].header_total_typed``          ``bids[].total`` (27)
``bids[].header_ledger_key``           ``bids[].total_ledger_key`` (27)
``bids[].recorded_by`` as prose        ``seed`` | ``learner``; the prose in ``_recorded_by_note`` (38)
=====================================  ===========================================================
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializeAsAny,
    StrictBool,
    StrictInt,
    create_model,
    field_validator,
    model_validator,
)

from app.modules.trainer.probe_types import PROBE_TYPE_NAMES

# ── Grammars ─────────────────────────────────────────────────────────────────

_STAGE_RE = re.compile(r"^(?:on_enrol|on_unlock\(([1-9]\d*)\))$")
_GRADED_BY_RE = re.compile(r"^(?:panel|both|probe:(0|[1-9]\d*))$")
_PROGRESS_LINK_RE = re.compile(r"^(?:csa|none|boq:\S+)$")
_BOQ_REF_RE = re.compile(r"^boq\.[a-z][a-z0-9_]*$")

PACKAGE_REF = "bid_package.main"
CONTRACT_REF = "contract.main"
MAIN_BOQ_REF = "boq.main"

#: Widths of the ``oe_trainer_*`` columns a course id lands in (``models.py``
#: and the migration). Mirrored here so validation never imports the ORM; a
#: unit test reads ``models.py`` and fails when the two drift apart.
COLUMN_LIMITS: dict[str, int] = {
    "course_key": 80,  # oe_trainer_course.course_key
    "version": 20,  # oe_trainer_course.version
    "title": 255,  # oe_trainer_course.title
    "language": 8,  # oe_trainer_course.language
    "task_id": 16,  # oe_trainer_task_state.task_id, oe_trainer_answer.task_id
    "answer_name": 255,  # oe_trainer_answer.answer_name
}

Unit = Literal["percent", "fraction"]
Works = Literal["public", "private"]
LegalReview = Literal["pending", "reviewed"]
RECORDED_BY_VALUES: tuple[str, ...] = ("seed", "learner")

#: Country-named seed keys of the first drafts -> the canonical list they
#: belong in. Refused, never folded: one shape, no aliases.
LEGACY_SEED_KEYS: dict[str, str] = {
    "progress_readings_valuation_1": "progress_readings",
    "progress_readings_application_1": "progress_readings",
    "progress_readings_ar1": "progress_readings",
    "progress_readings_situation_1": "progress_readings",
    "variation_01": "variations",
    "change_order_1": "variations",
    "nachtrag_n01": "variations",
    "ordre_de_service_2": "variations",
}

#: Keys that are always authoring-only, wherever they appear (decision 9).
#: ``*_note`` is handled by suffix, with ``vat_note`` as the one exception.
AUTHORING_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "rewalk",
        "provenance_vocabulary",
        "graded_by_semantics",
        "count_claims",
        "requires_walk_or_test",
        "expected_stored",
        "opens_dependency",
        "diagnosis_scope",
    }
)
_NOTE_KEYS_ALLOWED: frozenset[str] = frozenset({"vat_note"})

#: Probe fields whose ERP column holds a percent (0-100).
PERCENT_PROBE_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("contract.field", "retention_percent"),
        ("contract.field", "einvoice_vat_rate"),
        ("boq.markup", "percentage"),
    }
)
#: Probe fields that hold text, compared case-folded and exactly.
TEXT_PROBE_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("boq.markup", "markup_type"),
        ("boq.markup", "apply_to"),
        ("boq.markup", "category"),
        ("bid.award", "awarded_bidder_name"),
        ("contract.field", "status"),
        ("claim.field", "status"),
        ("claim.lien_waiver", "waiver_type"),
        ("claim.lien_waiver", "through_date"),
        ("variation.request", "status"),
        ("variation.order", "status"),
    }
)


@dataclass(frozen=True, slots=True)
class Stage:
    """A parsed seed ``stage``: on enrolment, or when task ``task_n`` unlocks."""

    kind: Literal["on_enrol", "on_unlock"]
    task_n: int | None = None

    def visible_at(self, task_n: int) -> bool:
        """True when this stage has run by the time task ``task_n`` is unlocked."""
        return self.kind == "on_enrol" or (self.task_n is not None and self.task_n <= task_n)


@dataclass(frozen=True, slots=True)
class GradedBy:
    """A parsed ``graded_by``."""

    kind: Literal["panel", "both", "probe"]
    readback_index: int | None = None

    @property
    def has_panel_field(self) -> bool:
        """True when the learner types this answer in the panel."""
        return self.kind in ("panel", "both")


def parse_stage(value: object) -> Stage:
    """Parse ``on_enrol`` / ``on_unlock(<n>)``.

    Raises:
        ValueError: anything else, including the old ``seeded_at`` prose.
    """
    if not isinstance(value, str):
        msg = f"stage must be a string, got {type(value).__name__}"
        raise ValueError(msg)
    match = _STAGE_RE.match(value)
    if match is None:
        msg = f"stage {value!r} is not on_enrol or on_unlock(<task number>)"
        raise ValueError(msg)
    return Stage("on_enrol") if match.group(1) is None else Stage("on_unlock", int(match.group(1)))


def parse_graded_by(value: object) -> GradedBy:
    """Parse ``panel`` / ``both`` / ``probe:<readback index>``.

    Raises:
        ValueError: anything else.
    """
    if not isinstance(value, str):
        msg = f"graded_by must be a string, got {type(value).__name__}"
        raise ValueError(msg)
    match = _GRADED_BY_RE.match(value)
    if match is None:
        msg = f"graded_by {value!r} is not panel, both or probe:<readback index>"
        raise ValueError(msg)
    if match.group(1) is not None:
        return GradedBy("probe", int(match.group(1)))
    return GradedBy(value)  # type: ignore[arg-type]


def to_decimal(value: object) -> Decimal | None:
    """A JSON number (or numeric string) as Decimal; None for anything else.

    Booleans are not numbers here, and floats go through ``str`` so 0.1 stays
    0.1.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None
    return None


def to_percent(value: Decimal, unit: str | None) -> Decimal:
    """Express a rate in the ERP's percent unit. Exact in Decimal."""
    return value * 100 if unit == "fraction" else value


def is_authoring_key(key: str) -> bool:
    """True for a key the loader strips: ``_x``, or a decision-9 authoring key.

    Only the leading underscore is stripped silently. The named authoring keys
    and ``*_note`` must be moved by the author; they are reported, not dropped.
    """
    return key.startswith("_")


def is_misplaced_authoring_key(key: str) -> bool:
    """True for a decision-9 authoring key left outside ``authoring``/``_``."""
    if key in AUTHORING_ONLY_KEYS:
        return True
    return key.endswith("_note") and key not in _NOTE_KEYS_ALLOWED


# ── Normalisation (pure) ─────────────────────────────────────────────────────


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if not (isinstance(k, str) and is_authoring_key(k))}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def normalise_course_dict(raw: Any) -> tuple[Any, list[str]]:
    """Strip authoring material. Pure.

    Args:
        raw: The parsed JSON of one course file.

    Returns:
        ``(normalised, problems)``. ``normalised`` is a new object; ``raw`` is
        not modified. ``problems`` lists what normalisation itself could not
        settle (today only a root that is not an object); the loader treats
        each one as an ERROR.
    """
    if not isinstance(raw, dict):
        return copy.deepcopy(raw), ["the course file is not a JSON object"]
    return _strip({k: v for k, v in raw.items() if k != "authoring"}), []


# ── Field types ──────────────────────────────────────────────────────────────


def _num_before(value: Any) -> Any:
    if isinstance(value, bool):
        msg = "a number is required, got a boolean"
        raise ValueError(msg)
    parsed = to_decimal(value)
    if parsed is None:
        msg = f"a number is required, got {value!r}"
        raise ValueError(msg)
    return parsed


def _value_before(value: Any) -> Any:
    """Numbers become Decimal; booleans, text and null pass through."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    parsed = to_decimal(value)
    return parsed if parsed is not None else value


Num = Annotated[Decimal, BeforeValidator(_num_before)]
#: A value that may be a number, text or a boolean (an ``expect`` of a probe).
Scalar = Annotated[StrictBool | Decimal | str | None, BeforeValidator(_value_before)]
#: ``"latest"`` or the n-th object (1-based) in creation order.
Selector = Literal["latest"] | Annotated[StrictInt, Field(ge=1)]


def _check_boq_ref(value: str) -> str:
    if not _BOQ_REF_RE.match(value):
        msg = f"boq_ref {value!r} is not boq.main or boq.<name> (decision 10)"
        raise ValueError(msg)
    return value


def _fixed_ref(expected: str, arg: str) -> Any:
    def check(value: str) -> str:
        if value != expected:
            msg = f"{arg} {value!r} must be {expected!r} (decision 10)"
            raise ValueError(msg)
        return value

    return BeforeValidator(check)


def _check_recorded_by(value: Any) -> Any:
    if isinstance(value, str) and value not in RECORDED_BY_VALUES:
        msg = (
            f"recorded_by {value[:40]!r} is not 'seed' or 'learner'; "
            "move any explanation to '_recorded_by_note' (decision 38)"
        )
        raise ValueError(msg)
    return value


#: Who records a seeded bid (decision 38).
RecordedBy = Annotated[Literal["seed", "learner"], BeforeValidator(_check_recorded_by)]
BoqRef = Annotated[str, BeforeValidator(_check_boq_ref)]
PackageRef = Annotated[str, _fixed_ref(PACKAGE_REF, "package_ref")]
ContractRef = Annotated[str, _fixed_ref(CONTRACT_REF, "contract_ref")]
NonEmpty = Annotated[str, Field(min_length=1)]


class _Strict(BaseModel):
    """Base of every course model: unknown keys are an error."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    #: Keys a decision renamed or dropped -> what the author writes instead.
    REPLACED_KEYS: ClassVar[dict[str, str]] = {}

    @model_validator(mode="before")
    @classmethod
    def _name_misplaced_authoring_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            replaced = sorted(k for k in data if k in cls.REPLACED_KEYS)
            if replaced:
                msg = "; ".join(f"'{k}' is replaced: {cls.REPLACED_KEYS[k]}" for k in replaced)
                raise ValueError(msg)
            misplaced = sorted(k for k in data if isinstance(k, str) and is_misplaced_authoring_key(k))
            if misplaced:
                msg = (
                    f"authoring-only keys {misplaced} must move under the root 'authoring' object "
                    "or take a leading underscore (decision 9)"
                )
                raise ValueError(msg)
        return data


# ── Probe arguments ──────────────────────────────────────────────────────────


class ProbeArgs(_Strict):
    """Base of the per-type probe argument models."""


class BoqCostBreakdownArgs(ProbeArgs):
    """``boq.cost_breakdown``."""

    boq_ref: BoqRef
    field: Literal["direct_cost", "grand_total", "markup_amount"]
    markup_name: NonEmpty | None = None

    @model_validator(mode="after")
    def _markup_name_iff_markup_amount(self) -> BoqCostBreakdownArgs:
        if (self.field == "markup_amount") != (self.markup_name is not None):
            msg = "markup_name is required for field markup_amount and only for it"
            raise ValueError(msg)
        return self


class BoqPositionArgs(ProbeArgs):
    """``boq.position``."""

    boq_ref: BoqRef
    ordinal: NonEmpty
    field: Literal["quantity", "unit_rate", "total"]


class BoqSectionTotalArgs(ProbeArgs):
    """``boq.section_total``."""

    boq_ref: BoqRef
    section_ordinal: NonEmpty


class BoqMarkupArgs(ProbeArgs):
    """``boq.markup``."""

    boq_ref: BoqRef
    name: NonEmpty
    field: Literal["percentage", "fixed_amount", "markup_type", "apply_to", "category", "sort_order"]


class BidSubmissionArgs(ProbeArgs):
    """``bid.submission``."""

    package_ref: PackageRef
    bidder_name: NonEmpty
    field: Literal["total_amount", "is_valid"]


class BidLevelingArgs(ProbeArgs):
    """``bid.leveling``."""

    package_ref: PackageRef
    bidder_name: NonEmpty
    field: Literal["raw_total", "normalized_total", "rank"]


class BidAwardArgs(ProbeArgs):
    """``bid.award``."""

    package_ref: PackageRef
    field: Literal["awarded_bidder_name", "awarded_amount"]


class ContractFieldArgs(ProbeArgs):
    """``contract.field`` (frozen by decision 16)."""

    contract_ref: ContractRef
    field: Literal["total_value", "original_contract_value", "retention_percent", "status", "einvoice_vat_rate"]


class ClaimFieldArgs(ProbeArgs):
    """``claim.field`` (frozen by decision 16)."""

    contract_ref: ContractRef
    claim_selector: Selector
    field: Literal[
        "gross_amount",
        "retention_amount",
        "prior_claims_total",
        "net_due",
        "completed_stored_to_date",
        "retention_held_to_date",
        "status",
    ]


class ClaimLineArgs(ProbeArgs):
    """``claim.line`` (frozen by decision 16)."""

    contract_ref: ContractRef
    claim_selector: Selector
    line_code: NonEmpty
    field: Literal[
        "period_completed_value", "cumulative_completed_value", "materials_stored_value", "retention_to_date"
    ]


class ClaimLienWaiverArgs(ProbeArgs):
    """``claim.lien_waiver``: the last waiver attached to the claim."""

    contract_ref: ContractRef
    claim_selector: Selector
    field: Literal["amount", "waiver_type", "through_date"]


class FinanceReceivableArgs(ProbeArgs):
    """``finance.receivable``: the invoice raised from the claim."""

    contract_ref: ContractRef
    claim_selector: Selector
    field: Literal["amount_subtotal", "tax_amount", "amount_total"]


class VariationRequestArgs(ProbeArgs):
    """``variation.request``. Requests carry no contract, so no ``contract_ref``."""

    variation_ref: Selector
    field: Literal["estimated_cost_impact", "agreed_cost_impact", "status"]


class VariationOrderArgs(ProbeArgs):
    """``variation.order`` (frozen by decision 16)."""

    contract_ref: ContractRef
    variation_ref: Selector
    field: Literal["final_cost_impact", "status"]


class PanelAnswerArgs(ProbeArgs):
    """``panel.answer``: a typed answer, by answer name."""

    answer_name: NonEmpty


class PanelOptionArgs(ProbeArgs):
    """``panel.option``: the option chosen for a question."""

    question: Literal["trace", "explain"]


#: Probe type -> its frozen argument model.
PROBE_ARGS_MODELS: dict[str, type[ProbeArgs]] = {
    "boq.cost_breakdown": BoqCostBreakdownArgs,
    "boq.position": BoqPositionArgs,
    "boq.section_total": BoqSectionTotalArgs,
    "boq.markup": BoqMarkupArgs,
    "bid.submission": BidSubmissionArgs,
    "bid.leveling": BidLevelingArgs,
    "bid.award": BidAwardArgs,
    "contract.field": ContractFieldArgs,
    "claim.field": ClaimFieldArgs,
    "claim.line": ClaimLineArgs,
    "claim.lien_waiver": ClaimLienWaiverArgs,
    "finance.receivable": FinanceReceivableArgs,
    "variation.request": VariationRequestArgs,
    "variation.order": VariationOrderArgs,
    "panel.answer": PanelAnswerArgs,
    "panel.option": PanelOptionArgs,
}

if set(PROBE_ARGS_MODELS) != PROBE_TYPE_NAMES:  # pragma: no cover - import-time guard
    msg = "PROBE_ARGS_MODELS and probe_types.PROBE_TYPE_NAMES disagree"
    raise RuntimeError(msg)


class _ProbeBase(_Strict):
    """Fields every probe carries besides ``type`` and ``args``.

    ``expect`` is an inline expected value, used when the value has no ledger
    key in the file. ``unit`` is the unit of the expected value (a fraction is
    converted to percent before it is compared with a percent column).
    ``gate`` (decision 19) makes a readback no answer grades fail the task on
    a mismatch; without it such a readback is informational.
    """

    expect: Scalar = None
    unit: Unit | None = None
    gate: StrictBool = False


def _probe_class(type_name: str, args_model: type[ProbeArgs]) -> type[_ProbeBase]:
    class_name = "Probe_" + type_name.replace(".", "_")
    return create_model(  # type: ignore[call-overload,no-any-return]
        class_name,
        __base__=_ProbeBase,
        type=(Literal[type_name], ...),
        args=(args_model, ...),
    )


PROBE_MODELS: dict[str, type[_ProbeBase]] = {name: _probe_class(name, m) for name, m in PROBE_ARGS_MODELS.items()}
ProbeSpec = Annotated[Union[tuple(PROBE_MODELS.values())], Field(discriminator="type")]  # noqa: UP007


def validate_probe(probe: Any) -> _ProbeBase:
    """Validate one ``readback[].probe`` object on its own.

    Raises:
        pydantic.ValidationError: unknown type or arguments off the frozen model.
    """
    from pydantic import TypeAdapter

    return TypeAdapter(ProbeSpec).validate_python(probe)


# ── Shared small shapes ──────────────────────────────────────────────────────


class LedgerFigure(_Strict):
    """A figure with its ledger key and how it was derived."""

    value: Num | None = None
    ledger_key: str | None = None
    derivation: str | None = None
    note: str | None = None


class RelatedValue(_Strict):
    """A derivation shown next to a diagnosis or a rule.

    ``name`` is a ledger key. ``label`` is how an estimator would name the
    figure on screen, in the course language (decision 47); without it the
    checker falls back to a readback or given that names the same key, and
    the loader warns (``trainer.related_value_unlabelled``).
    """

    name: str
    label: str | None = None
    value: Scalar = None
    derivation: str | None = None


class Derivation(_Strict):
    """A worked derivation attached to a question."""

    name: str
    value: Scalar = None
    derivation: str | None = None


# ── Rules ────────────────────────────────────────────────────────────────────


class RuleSpec(_Strict):
    """One rule the course cites (``rules[]``)."""

    key: NonEmpty
    value: Any = None
    unit: Unit | None = None
    status: str
    source: str | None = None
    checked_on: str | None = None
    note: str | None = None
    applicability: str | None = None
    as_of: str | None = None
    effective_from: str | None = None
    text: str | None = None
    condition: str | None = None
    review_by: str | None = None


# ── Tasks ────────────────────────────────────────────────────────────────────


class AlsoAccepted(_Strict):
    """An alternative accepted value, graded with the answer's tolerance."""

    value: Num
    ledger_key: str | None = None
    convention: str | None = None


def _also_accepted_before(value: Any) -> Any:
    if isinstance(value, list):
        return [v if isinstance(v, dict) else {"value": v} for v in value]
    return value


class AnswerKeySpec(_Strict):
    """One expected answer."""

    name: NonEmpty
    ledger_key: NonEmpty
    value: Num
    tolerance: Num
    graded_by: str
    unit: Unit | None = None
    display_unit: Annotated[str, Field(min_length=1, max_length=16)] | None = None
    also_accepted: Annotated[list[AlsoAccepted], BeforeValidator(_also_accepted_before)] = Field(default_factory=list)

    @field_validator("graded_by")
    @classmethod
    def _graded_by_grammar(cls, value: str) -> str:
        parse_graded_by(value)
        return value

    @field_validator("unit", mode="before")
    @classmethod
    def _unit_is_a_rate_unit(cls, value: Any) -> Any:
        if isinstance(value, str) and value not in ("percent", "fraction"):
            msg = (
                f"unit {value!r} is not a rate unit (percent | fraction); "
                "a display unit goes in 'display_unit' (decision 23)"
            )
            raise ValueError(msg)
        return value

    @property
    def grading(self) -> GradedBy:
        """The parsed ``graded_by``."""
        return parse_graded_by(self.graded_by)


class ReadbackSpec(_Strict):
    """One value the panel reads back from the ERP."""

    what: NonEmpty
    expects: list[str] = Field(default_factory=list)
    probe: SerializeAsAny[ProbeSpec] | None = None  # type: ignore[valid-type]
    table: str | None = None
    field: str | None = None

    REPLACED_KEYS: ClassVar[dict[str, str]] = {
        "gate": "write it inside the probe as 'probe.gate' (decision 19)",
        "scale": "dropped from the schema; move it under the root 'authoring' object (decision 25)",
    }


class CheckSpec(_Strict):
    """One check of a task."""

    id: NonEmpty
    kind: Literal["numbers", "trace", "explain"]
    prompt: NonEmpty
    expects: list[str] = Field(default_factory=list)


class OptionSpec(_Strict):
    """One option of a trace or explain question."""

    text: NonEmpty
    correct: StrictBool
    feedback: str


class QuestionSpec(_Strict):
    """A trace or explain question."""

    prompt: NonEmpty
    options: list[OptionSpec] = Field(min_length=2)
    derivations: list[Derivation] = Field(default_factory=list)


class DiagnosisSpec(_Strict):
    """Why a value is wrong, matched within ``applies_to`` only."""

    id: NonEmpty
    applies_to: NonEmpty
    kind: Literal["error", "convention"]
    provenance: str | None = None
    when: str | None = None
    wrong_value: Scalar = None
    derivation: str | None = None
    message: NonEmpty
    related: list[RelatedValue] = Field(default_factory=list)


class Band(_Strict):
    """One band of a banded rate."""

    up_to: Num | None = None
    percentage: Num


class GivenSpec(_Strict):
    """A value the task states up front."""

    name: NonEmpty
    value: Scalar = None
    ledger_key: str | None = None
    unit: str | None = None
    rate_key: str | None = None
    rule_key: str | None = None
    text: str | None = None
    bands: list[Band] | None = None


class TaskSpec(_Strict):
    """One task."""

    id: NonEmpty
    n: StrictInt = Field(ge=1)
    title: NonEmpty
    role: str | None = None
    module: NonEmpty
    opens: NonEmpty
    opens_label: str | None = None
    estimated_minutes: StrictInt | None = Field(default=None, ge=0)
    brief: NonEmpty
    steps: list[str] = Field(default_factory=list)
    given: list[GivenSpec] = Field(default_factory=list)
    answer_key: list[AnswerKeySpec] = Field(default_factory=list)
    optional_answer_key: list[AnswerKeySpec] = Field(default_factory=list)
    readback: list[ReadbackSpec] = Field(default_factory=list)
    checks: list[CheckSpec] = Field(min_length=1)
    trace_question: QuestionSpec
    explain_question: QuestionSpec
    diagnoses: list[DiagnosisSpec] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    panel_notes: Any = None
    video: Any = None
    erp_fit: Any = None
    dc4_step: Any = None
    seeder: str | None = None


# ── Seed ─────────────────────────────────────────────────────────────────────


class _Staged(_Strict):
    stage: str

    @field_validator("stage")
    @classmethod
    def _stage_grammar(cls, value: str) -> str:
        parse_stage(value)
        return value

    @property
    def parsed_stage(self) -> Stage:
        """The parsed ``stage``."""
        return parse_stage(self.stage)


class AddressSpec(_Strict):
    """A project address (decision 9)."""

    street: str | None = None
    city: str | None = None
    postcode: str | None = None
    state: str | None = None
    subdivision: str | None = None
    country: str | None = None


class ProjectSeed(_Staged):
    """``seed.project``."""

    name: NonEmpty
    country: str
    currency: str
    region: str | None = None
    location: str | None = None
    description: str | None = None
    classification_standard: str | None = None
    regional_pack: str | None = None
    validation_rule_sets: list[str] | None = None
    address: AddressSpec | None = None
    address_country: str | None = None
    country_code: str | None = None
    area_sf: Num | None = None
    works: Works | None = None
    note: str | None = None


class PartySeed(_Strict):
    """``seed.parties[]``."""

    name: NonEmpty
    role: str
    note: str | None = None
    stage: str | None = None


class UserSeed(_Strict):
    """``seed.users[]``."""

    role: str
    grant: str | None = None
    note: str | None = None
    stage: str | None = None


class SectionLineSeed(_Strict):
    """A priced line listed under a section (US general conditions)."""

    code: NonEmpty
    description: str | None = None
    unit: str | None = None
    qty: Num | None = None
    qty_ledger_key: str | None = None
    rate: Num | None = None
    ledger_key: str | None = None


class SectionSeed(_Strict):
    """``seed.boq.sections[]``."""

    ordinal: NonEmpty
    title: str | None = None
    positions: list[str] = Field(default_factory=list)
    lines: list[SectionLineSeed] | None = None
    line: str | None = None
    unit: str | None = None
    amount: Num | None = None
    amount_after_t1: Num | None = None
    amount_after_t2: Num | None = None
    ledger_key: str | None = None
    built_by_learner: StrictBool | str | None = None
    din276: str | None = None
    note: str | None = None


class PositionSeed(_Strict):
    """``seed.boq.positions[]``. A null ``rate`` is seeded as 0 for the learner to price."""

    code: NonEmpty
    section: str | None = None
    description: str
    unit: str
    qty: Num
    rate: Num | None = None
    qty_ledger_key: str | None = None
    answer_rate_key: str | None = None
    answer_amount_key: str | None = None
    classification: dict[NonEmpty, NonEmpty] | None = None
    note: str | None = None


class MarkupSeed(_Strict):
    """A markup row: pre-seeded, or the expected shape after a task."""

    stage: str | None = None
    name: NonEmpty
    markup_type: Literal["percentage", "fixed", "banded", "escalation"] | None = None
    apply_to: Literal["direct_cost", "subtotal", "cumulative"] | None = None
    category: str | None = None
    sort_order: StrictInt | None = None
    percentage: Num | None = None
    fixed_amount: Num | None = None
    fixed_amount_ledger_key: str | None = None
    unit: Unit | None = None
    rate_key: str | None = None
    metadata: dict[str, Any] | None = None


class BoqSeed(_Staged):
    """``seed.boq``."""

    name: NonEmpty
    note: str | None = None
    classification: str | None = None
    template_source: str | None = None
    sections: list[SectionSeed] = Field(default_factory=list)
    positions: list[PositionSeed] = Field(default_factory=list)
    markups: list[MarkupSeed] = Field(default_factory=list)
    markups_expected_after_t2: list[MarkupSeed] | None = None
    direct_cost_before_t1: LedgerFigure | None = None
    direct_cost_after_t1: LedgerFigure | None = None
    direct_cost_after_t2: LedgerFigure | None = None
    direct_cost_after_t2_lines: LedgerFigure | None = None
    app_uk_template_reference: Any = None
    app_us_template_reference: Any = None
    app_dach_template_reference: Any = None
    app_fr_template_reference: Any = None


class SuretyBondSeed(MarkupSeed):
    """``seed.surety_bond_row`` (a banded markup row, US)."""

    stage: str  # type: ignore[assignment]


class ScopeLineSeed(_Strict):
    """``seed.bid_package.scope_lines[]``."""

    code: NonEmpty
    description: str | None = None
    unit: str
    qty: Num
    qty_ledger_key: str | None = None
    mandatory: StrictBool = True
    boq_position: str | None = None
    ansatz_ledger_key: str | None = None


class BidLineSeed(_Strict):
    """One priced line of a bid. Null rate and amount mean the bidder left it blank."""

    code: NonEmpty
    rate: Num | None = None
    rate_ledger_key: str | None = None
    amount: Num | None = None
    amount_ledger_key: str | None = None
    note: str | None = None
    comment: str | None = None
    inclusion_status: str | None = None


class BidDiscountSeed(_Strict):
    """A discount stated on a bid (FR ``remise``)."""

    rate: Num | None = None
    rate_ledger_key: str | None = None
    unit: Unit | None = None
    amount: Num | None = None
    ledger_key: str | None = None
    note: str | None = None


class BidVariantSeed(_Strict):
    """A variant offered with a bid (FR ``variante``)."""

    description: str | None = None
    total_ht: Num | None = None
    ledger_key: str | None = None
    conforming: StrictBool | None = None


class BidAlternativeSeed(_Strict):
    """An alternative line offered with a bid (DE)."""

    code: str | None = None
    rate: Num | None = None
    rate_ledger_key: str | None = None
    total_with_alternative: Num | None = None
    total_ledger_key: str | None = None
    note: str | None = None


class BidSeed(_Strict):
    """``seed.bid_package.bids[]``, recorded before the bids are opened.

    ``total`` is the bid's header total, the figure the seeder writes into
    ``oe_bid_management_submission.total_amount``; it is required on every
    bid, including one whose lines do not add up to it (then ``line_sum`` and
    ``declared_discrepancy`` carry the other figure). There is no second name
    for the header total.

    ``recorded_by`` (decision 38) says who records the bid: ``seed`` (the
    seeder, while the package is published) or ``learner`` (the learner in a
    task; the seeder then creates the bidder and the invitation, never the
    bid). Any explanation goes in ``_recorded_by_note``, which the loader
    strips.
    """

    bidder: NonEmpty
    recorded_by: RecordedBy
    total: Num
    total_ledger_key: str | None = None
    lines: list[BidLineSeed] = Field(default_factory=list)
    exclusions: list[str] | None = None

    REPLACED_KEYS: ClassVar[dict[str, str]] = {
        "header_total_typed": "write 'total', the bid's header total (decision 27)",
        "header_ledger_key": "write 'total_ledger_key' (decision 27)",
    }
    conditions: str | None = None
    declared_discrepancy: LedgerFigure | None = None
    line_sum: Num | None = None
    line_sum_ledger_key: str | None = None
    lines_total: Num | None = None
    letter_total_ttc: LedgerFigure | None = None
    remise: BidDiscountSeed | None = None
    variante: BidVariantSeed | None = None
    alternative: BidAlternativeSeed | None = None


class BidPackageSeed(_Staged):
    """``seed.bid_package``."""

    ref: Annotated[str, _fixed_ref(PACKAGE_REF, "ref")] | None = None
    module: str | None = None
    title: NonEmpty
    currency: str
    status_at_start: str | None = None
    budget: LedgerFigure | None = None
    alternatives_allowed: StrictBool | None = None
    bid_form_instruction: str | None = None
    scope_lines: list[ScopeLineSeed] = Field(default_factory=list)
    bids: list[BidSeed] = Field(default_factory=list)


class RateFigure(_Strict):
    """A rate with its unit (decision 18). A bare number means percent."""

    value: Num
    unit: Unit | None = None
    rate_key: str | None = None
    percent_ledger_key: str | None = None
    note: str | None = None


class SovMetadata(_Strict):
    """``schedule_of_values[].metadata``; the seeder copies it to the line."""

    classification: dict[str, str] = Field(default_factory=dict)


class SovLineSeed(_Strict):
    """One schedule-of-values line (decision 18)."""

    code: NonEmpty
    description: str
    unit: str
    amount: Num
    ledger_key: str | None = None
    quantity: Num | None = None
    metadata: SovMetadata
    progress_link: str | None = None
    boq_link: str | None = None
    derivation: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_flat_classification(cls, data: Any) -> Any:
        if isinstance(data, dict) and "classification" in data:
            msg = "classification must sit under metadata.classification, not flat on the line (decision 18)"
            raise ValueError(msg)
        return data

    @field_validator("progress_link")
    @classmethod
    def _progress_link_grammar(cls, value: str | None) -> str | None:
        if value is not None and not _PROGRESS_LINK_RE.match(value):
            msg = f"progress_link {value!r} is not csa, none or boq:<ordinal>"
            raise ValueError(msg)
        return value


class ContractSeed(_Staged):
    """``seed.contract``."""

    ref: Annotated[str, _fixed_ref(CONTRACT_REF, "ref")] | None = None
    title: NonEmpty
    counterparty: str | None = None
    contract_type: str | None = None
    contract_date: str | None = None
    currency: str | None = None
    start_date: str
    status: str | None = None
    status_after_seed: str | None = None
    value: LedgerFigure
    retention_percent: Num | RateFigure
    retention_cap: LedgerFigure | None = None
    vat_rate_percent: Num | None = None
    vat_note: str | None = None
    works: Works | None = None
    schedule_of_values: list[SovLineSeed] = Field(min_length=1)
    schedule_total: LedgerFigure | None = None

    @property
    def retention_as_percent(self) -> Decimal:
        """The retention rate in the ERP's percent unit."""
        if isinstance(self.retention_percent, RateFigure):
            return to_percent(self.retention_percent.value, self.retention_percent.unit)
        return self.retention_percent


class ReadingSeed(_Strict):
    """One progress reading of one SOV line, on the ERP's 0-100 scale (decision 21).

    ``value`` and the ledger keys state what the reading is worth for the
    answer key; the seeder writes ``line_code`` and ``percent_complete`` only.
    """

    line_code: NonEmpty
    percent_complete: Num
    value: Num | None = None
    ledger_key: str | None = None
    pct_ledger_key: str | None = None

    REPLACED_KEYS: ClassVar[dict[str, str]] = {
        "line": "write 'line_code' (decision 21)",
        "percent": "write 'percent_complete', on the ERP's 0-100 scale (decision 21)",
        "recorded_at": "drop it; the seeder stamps recorded_at inside the period (decision 20)",
    }


class ProgressReadingsSeed(_Staged):
    """One entry of ``seed.progress_readings[]``: the readings of one claim period.

    ``period_from`` and ``period_to`` are ISO dates, inclusive, in order. The
    seeder stamps every reading inside them (decision 20).
    """

    period_from: date
    period_to: date
    readings: list[ReadingSeed] = Field(min_length=1)
    by_hand: list[ReadingSeed] | None = None

    REPLACED_KEYS: ClassVar[dict[str, str]] = {
        "period": "write the ISO dates 'period_from' and 'period_to' (decision 21)",
    }

    @field_validator("period_from", "period_to", mode="before")
    @classmethod
    def _iso_date_only(cls, value: Any) -> Any:
        if not isinstance(value, str):
            msg = "a period date is an ISO date string, YYYY-MM-DD"
            raise ValueError(msg)  # noqa: TRY004 - pydantic reports a ValueError
        return value

    @model_validator(mode="after")
    def _period_in_order(self) -> ProgressReadingsSeed:
        if self.period_from > self.period_to:
            msg = "period_from is after period_to"
            raise ValueError(msg)
        return self


class VariationRequestSeed(_Strict):
    """The ERP variation request the seeder creates in draft, with no cost."""

    title: NonEmpty
    contract_clause_ref: str | None = None
    description: str | None = None


class VariationScopeSeed(_Strict):
    """One line of an instructed change."""

    code: NonEmpty
    description: str | None = None
    unit: str | None = None
    qty: Num | None = None
    qty_ledger_key: str | None = None
    rate: Num | None = None
    rate_ledger_key: str | None = None
    amount: Num | None = None
    ledger_key: str | None = None
    who: str | None = None
    kind: str | None = None
    price_key: str | None = None
    h_ledger_key: str | None = None
    stoff_ledger_key: str | None = None


class VariationSeed(_Staged):
    """One entry of ``seed.variations[]``: one instructed change."""

    ref: str | None = None
    title: str | None = None
    instruction_ref: str | None = None
    from_: str | None = Field(default=None, alias="from")
    erp_request: VariationRequestSeed | None = None
    scope: list[VariationScopeSeed] = Field(default_factory=list)
    scope_total: LedgerFigure | None = None
    case_assumptions: str | None = None
    markups_expected: str | None = None
    mehrkostenanzeige: str | None = None


class SeedSpec(_Strict):
    """``seed``. Only ``project`` is required; the rest depends on the course."""

    project: ProjectSeed
    parties: list[PartySeed] = Field(default_factory=list)
    users: list[UserSeed] = Field(default_factory=list)
    boq: BoqSeed | None = None
    surety_bond_row: SuretyBondSeed | None = None
    bid_package: BidPackageSeed | None = None
    contract: ContractSeed | None = None
    progress_readings: list[ProgressReadingsSeed] = Field(default_factory=list)
    variations: list[VariationSeed] = Field(default_factory=list)
    subcontract: Any = None
    operation: Any = None

    REPLACED_KEYS: ClassVar[dict[str, str]] = {
        "navigation": "dropped from the schema; move it under the root 'authoring' object (decision 25)",
    }

    @model_validator(mode="before")
    @classmethod
    def _refuse_legacy_slot_names(cls, data: Any) -> Any:
        if isinstance(data, dict):
            legacy = sorted(k for k in data if k in LEGACY_SEED_KEYS)
            if legacy:
                moves = ", ".join(f"{k} -> seed.{LEGACY_SEED_KEYS[k]}[]" for k in legacy)
                msg = f"country-named seed keys are not accepted; move them into the canonical lists: {moves}"
                raise ValueError(msg)
        return data


# ── Root ─────────────────────────────────────────────────────────────────────


class BadgeSpec(_Strict):
    """The course badge the last task earns."""

    id: NonEmpty
    title: NonEmpty
    awarded_when: str | None = None


class CourseSpec(_Strict):
    """One course file, after :func:`normalise_course_dict`."""

    id: NonEmpty
    version: NonEmpty
    status: str
    title: NonEmpty
    summary: str | None = None
    country: Annotated[str, Field(min_length=2, max_length=2)]
    region: str | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    language: NonEmpty
    locale: str | None = None
    date_style: str | None = None
    legal_review: LegalReview
    as_of: str | None = None
    story_period: str | None = None
    rules_checked_on: str | None = None
    contract: str | None = None
    fictional_case: StrictBool | None = None
    erp_walked_version: str | None = None
    derivation_language: str | None = None
    sources: Any = None
    constants: Any = None
    conventions: Any = None
    status_vocabulary: Any = None
    rules: list[RuleSpec] = Field(default_factory=list)
    seed: SeedSpec
    tasks: list[TaskSpec] = Field(min_length=1)
    badge: BadgeSpec
    contract_choice_reason: str | None = None
    diagnosis_semantics: str | None = None
    jurisdiction: str | None = None
    schema_additions_vs_uk: Any = None

    def dump_for_storage(self) -> dict[str, Any]:
        """The JSON-safe spec stored in ``oe_trainer_course.spec``.

        Decimals become strings, so nothing round-trips through a float.
        """
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)
