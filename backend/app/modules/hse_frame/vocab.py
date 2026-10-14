# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closed vocabularies of the HSE frame: states and link kinds.

Everything a jurisdiction decides (topics, roles, templates, thresholds, the
list of particularly hazardous works) is catalogue data. What is fixed here is
what the code branches on.
"""

from __future__ import annotations

# draft -> in_review -> approved -> binding; a binding frame is revised (revising) and submitted again.
FRAME_STATES = ("draft", "in_review", "approved", "binding", "revising")
FRAME_EDITABLE = ("draft", "revising")
ITEM_STATUSES = ("open", "in_progress", "met", "waived", "not_applicable")
ITEM_DONE = ("met", "waived", "not_applicable")
OBLIGATIONS = ("mandatory", "recommended")
AUDIENCES = ("owner", "designer", "contractor", "coordinator", "operator")
ROLE_STATUSES = ("proposed", "appointed", "ended")
PLAN_STATUSES = ("not_started", "draft", "issued", "in_force")
LATER_WORKS_STATUSES = ("not_started", "draft", "complete")
# What makes a duty apply, as the catalogue names it (a role or template ``required_when``).
TRIGGERS = ("always", "multiple_employers", "plan_required", "advance_notice", "hazardous_work")

# Records of other modules an item may point at. The owner module keeps the row; the link only
# proves it belongs to the project.
LINK_KINDS = (
    "permit_condition",
    "safety_incident",
    "safety_observation",
    "hse_ptw",
    "hse_jsa",
    "hse_audit",
    "hse_capa",
    "quality_inspection",
    "cc_inspection",
)
# How a catalogue topic is read for the gate: from the item register, from the appointed roles, or
# from the permit conditions the permits module keeps.
TOPIC_BASES = ("items", "roles", "permits")
