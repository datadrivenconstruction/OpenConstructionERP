# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Probe registry: one probe class per type in ``probe_types.PROBE_TYPES``.

A probe reads one value back out of the learner's project. Usage::

    @register_probe("boq.cost_breakdown")
    class BoqCostBreakdownProbe(Probe):
        args_model = BoqCostBreakdownArgs

        async def read(self, session, ctx, args) -> ProbeReading: ...

The decorator refuses a name outside the closed list, a second class for the
same name, and an ``args_model`` other than the frozen model in
``spec.PROBE_ARGS_MODELS``: the course loader validated the args against that
model, so the probe must read exactly that shape.

A probe never guesses. When the value cannot be read it returns
:meth:`ProbeReading.unknown` with a reason code:

* ``ref_missing`` - the enrolment has no seeded object under that ref (or it is
  not an id); graded as ``missing``.
* ``not_found`` - the object the learner has to create is not there yet (no
  claim, no award, no markup of that name); graded as ``missing``.
* ``not_set`` - the object exists and the field is empty (a draft contract has
  no ``original_contract_value``); graded as ``missing``.
* ``ref_outside_project`` - the seeded id points into another project. The
  foreign value is never returned; graded as ``error``.
* ``ambiguous`` - more than one object answers the selector (two markups with
  the same name, two bidders with the same company name); graded as ``error``.
* ``unreadable`` - the stored value is not of the field's kind (an object where
  the e-invoice VAT rate should be a number); graded as ``error``.
* ``probe_unavailable`` - the owning module is not loaded; graded as ``error``.
* ``not_computed`` - a derived table the learner has not computed yet (the
  levelling table, read by a readback before the learner opened levelling);
  graded as ``missing``. The note is a message key telling the learner where
  to compute it (:data:`OPEN_LEVELING_KEY`).

Mode (decision 36). A readback GET runs in ``read`` mode and writes nothing; a
check runs in ``check`` mode. Only ``bid.leveling`` differs between the two:
in ``check`` mode it recomputes the levelling table before reading it.

Seeded refs are resolved through the enrolment's ``seeded_refs`` mapping (ref
name -> object id). This module only reads that mapping; the enrolment stores
it.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar, Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.trainer.checker.matching import CompareState, Expectation, compare
from app.modules.trainer.checker.units import FieldKind, probe_field_kind
from app.modules.trainer.probe_types import PROBE_TYPE_NAMES
from app.modules.trainer.spec import PROBE_ARGS_MODELS, ProbeArgs, validate_probe

logger = logging.getLogger(__name__)

UnknownReason = Literal[
    "ref_missing",
    "not_found",
    "not_set",
    "ref_outside_project",
    "ambiguous",
    "unreadable",
    "probe_unavailable",
    "not_computed",
]

#: Reasons that mean "the learner has not done it yet"; the rest are errors.
MISSING_REASONS: frozenset[str] = frozenset({"ref_missing", "not_found", "not_set", "not_computed"})

#: ``read``: the readback GET, never writes. ``check``: a check, may recompute.
ProbeMode = Literal["read", "check"]

#: Message key of a ``not_computed`` levelling read: open the levelling view.
OPEN_LEVELING_KEY = "trainer.readback.open_leveling"

ProbeValue = Decimal | str | bool | None


@dataclass(frozen=True, slots=True)
class ProbeContext:
    """Where a probe reads.

    Attributes:
        project_id: The enrolment's project. Every ERP probe refuses an object
            outside it.
        seeded_refs: The enrolment's ``seeded_refs`` (``"boq.main"`` -> id).
        enrolment_id: For the ``panel.*`` probes.
        task_id: For the ``panel.*`` probes (answers are stored per task).
        question_answer_names: ``trace`` / ``explain`` -> the answer name the
            option is stored under (the check id), for ``panel.option``.
        mode: ``read`` (default, writes nothing) or ``check``.
    """

    project_id: uuid.UUID
    seeded_refs: Mapping[str, Any] = field(default_factory=dict)
    enrolment_id: uuid.UUID | None = None
    task_id: str | None = None
    question_answer_names: Mapping[str, str] = field(default_factory=dict)
    mode: ProbeMode = "read"

    def ref_id(self, ref: str) -> uuid.UUID | None:
        """The object id seeded under ``ref``, or None when absent or not an id."""
        raw = self.seeded_refs.get(ref)
        if isinstance(raw, uuid.UUID):
            return raw
        if isinstance(raw, str):
            try:
                return uuid.UUID(raw)
            except ValueError:
                return None
        return None


@dataclass(frozen=True, slots=True)
class ProbeReading:
    """What a probe read: a value, or why there is none."""

    value: ProbeValue
    reason: UnknownReason | None = None
    note: str | None = None

    @classmethod
    def of(cls, value: ProbeValue, note: str | None = None) -> ProbeReading:
        """A value that was read (None becomes ``not_set``)."""
        if value is None:
            return cls(None, "not_set", note)
        return cls(value, None, note)

    @classmethod
    def unknown(cls, reason: UnknownReason, note: str | None = None) -> ProbeReading:
        """No value, and the reason code."""
        return cls(None, reason, note)

    @property
    def found(self) -> bool:
        """True when a value was read."""
        return self.reason is None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """A probe's value compared with what the item expects.

    ``status`` is ``unknown`` exactly when ``value`` is None; ``detail`` then
    holds the reason code (see the module docstring), otherwise an optional
    note.
    """

    value: ProbeValue
    unit: FieldKind
    status: CompareState
    detail: str | None = None

    @property
    def is_missing(self) -> bool:
        """True when the unknown value means the learner has not done it yet."""
        return self.status == "unknown" and (self.detail or "").split(":", 1)[0] in MISSING_REASONS


class Probe(ABC):
    """Base of every probe class."""

    type_name: ClassVar[str] = ""
    args_model: ClassVar[type[ProbeArgs]]
    #: True for the probes that read ERP tables (``probe_types.reads_erp``).
    reads_erp: ClassVar[bool] = True

    def kind(self, args: ProbeArgs) -> FieldKind:
        """The kind of the value this probe returns for ``args``."""
        return probe_field_kind(self.type_name, getattr(args, "field", None))

    @abstractmethod
    async def read(self, session: AsyncSession, ctx: ProbeContext, args: Any) -> ProbeReading:
        """Read the value. Must not raise for a missing or foreign object."""


PROBE_REGISTRY: dict[str, Probe] = {}


def register_probe(name: str) -> Callable[[type[Probe]], type[Probe]]:
    """Class decorator: register one probe class under ``name``.

    Raises:
        ValueError: ``name`` is not on the closed list, is registered twice,
            or the class's ``args_model`` is not the frozen model for it.
    """

    def decorate(cls: type[Probe]) -> type[Probe]:
        if name not in PROBE_TYPE_NAMES:
            msg = f"probe type {name!r} is not in probe_types.PROBE_TYPES"
            raise ValueError(msg)
        if name in PROBE_REGISTRY:
            msg = f"probe type {name!r} is registered twice"
            raise ValueError(msg)
        if getattr(cls, "args_model", None) is not PROBE_ARGS_MODELS[name]:
            msg = f"probe {name!r} must read the frozen args model {PROBE_ARGS_MODELS[name].__name__}"
            raise ValueError(msg)
        cls.type_name = name
        PROBE_REGISTRY[name] = cls()
        return cls

    return decorate


def _load_probes() -> None:
    # The probe classes register themselves on import; importing here keeps
    # the registry usable without the caller knowing about ``probes``.
    from app.modules.trainer.checker import probes  # noqa: F401


def get_probe(name: str) -> Probe:
    """The registered probe for ``name``.

    Raises:
        KeyError: no probe of that type.
    """
    _load_probes()
    return PROBE_REGISTRY[name]


def registered_probe_types() -> frozenset[str]:
    """Every registered probe type name."""
    _load_probes()
    return frozenset(PROBE_REGISTRY)


def _detail(reading: ProbeReading) -> str | None:
    if reading.reason is None:
        return reading.note
    return f"{reading.reason}: {reading.note}" if reading.note else reading.reason


async def run_probe(
    session: AsyncSession,
    probe_spec: Any,
    ctx: ProbeContext,
    expectation: Expectation,
) -> ProbeResult:
    """Run one ``readback[].probe`` and compare its value with ``expectation``.

    Args:
        session: The request session. Probes only read, except
            ``bid.leveling`` (see that probe).
        probe_spec: A validated probe model (``spec.ProbeSpec``) or its dict.
        ctx: Where to read.
        expectation: What the item expects; decides match or mismatch.

    Returns:
        The value, its kind, the comparison state and a detail.
    """
    spec = validate_probe(probe_spec) if isinstance(probe_spec, Mapping) else probe_spec
    probe = get_probe(spec.type)  # type: ignore[attr-defined]
    args = spec.args  # type: ignore[attr-defined]
    kind = probe.kind(args)
    try:
        reading = await probe.read(session, ctx, args)
    except HTTPException as exc:
        # A service refusing the read (404 on a deleted bill, 409 on a state
        # the learner left) means there is nothing to read, not a crash.
        reason: UnknownReason = "not_found" if exc.status_code == 404 else "unreadable"
        reading = ProbeReading.unknown(reason, f"HTTP {exc.status_code}")
    if not reading.found:
        return ProbeResult(None, kind, "unknown", _detail(reading))
    state = compare(reading.value, expectation)
    if state == "unknown":
        # A value of the wrong kind for its field is never shown as a reading.
        return ProbeResult(None, kind, "unknown", f"unreadable: {reading.value!r}")
    return ProbeResult(reading.value, kind, state, _detail(reading))
