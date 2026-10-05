# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The closed list of probe types a course readback may name.

A probe reads one value back out of the learner's project (or, for the two
``panel.*`` types, out of the learner's typed answers). Course files name a
probe in ``tasks[].readback[].probe.type``; any type not listed here is a
loader ERROR.

The checker's probe registry (``checker/registry.py``) must register exactly
these names; its own test compares the two. The list lives in a file of its
own so the course fixture, the spec loader and the checker can all read it
without importing each other.

``reads_erp`` marks the probes that look at ERP tables. Rule
``trainer.task_has_probe_graded_item`` needs every task to grade at least one
item through such a probe: a task the learner can pass by typing the right
numbers into the panel while leaving the ERP untouched teaches nothing. The
``panel.*`` probes do not count towards that rule.

Data only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProbeType:
    """One probe type name and whether it reads the ERP."""

    name: str
    reads_erp: bool


PROBE_TYPES: tuple[ProbeType, ...] = (
    ProbeType("boq.cost_breakdown", True),
    ProbeType("boq.position", True),
    ProbeType("boq.section_total", True),
    ProbeType("boq.markup", True),
    ProbeType("bid.submission", True),
    ProbeType("bid.leveling", True),
    ProbeType("bid.award", True),
    ProbeType("contract.field", True),
    ProbeType("claim.field", True),
    ProbeType("claim.line", True),
    ProbeType("claim.lien_waiver", True),
    ProbeType("finance.receivable", True),
    ProbeType("variation.request", True),
    ProbeType("variation.order", True),
    ProbeType("panel.answer", False),
    ProbeType("panel.option", False),
)

#: Every probe type name.
PROBE_TYPE_NAMES: frozenset[str] = frozenset(p.name for p in PROBE_TYPES)

#: The probe types that read ERP tables, the ones that satisfy
#: ``trainer.task_has_probe_graded_item``.
ERP_PROBE_TYPE_NAMES: frozenset[str] = frozenset(p.name for p in PROBE_TYPES if p.reads_erp)
