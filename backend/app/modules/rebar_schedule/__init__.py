# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebar schedule module.

Imports, validates, stores and re-exports reinforcement bending schedules in
the ABS interchange format - the file a CAD system writes alongside the printed
bending schedule so a bending shop can drive its machines from it.

The format is specified by the BVBS guideline "Datenaustausch von
Bewehrungsdaten", version 3.1 of May 2021. :mod:`app.modules.rebar_schedule.abs_format`
is written from that document and carries the details.

The module is named for what it carries rather than for the acronym: BVBS
already means the publisher of the GAEB conformance files elsewhere in this
codebase, and one word standing for two unrelated systems is how a reader ends
up in the wrong one.

The codec (:mod:`app.modules.rebar_schedule.abs_format`) and the rules
(:mod:`app.modules.rebar_schedule.validators`) do no import-time database or
registry work, so both can be unit tested on any interpreter. Permission and
rule registration are deferred to :func:`on_startup`, which the module loader
calls.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and the ``bvbs_abs`` rule set and the ``bar_bending_schedule`` rule set."""
    from app.modules.rebar_schedule.bbs_validators import register_bbs_rules
    from app.modules.rebar_schedule.permissions import register_rebar_schedule_permissions
    from app.modules.rebar_schedule.validators import register_rules

    register_rebar_schedule_permissions()
    register_rules()
    register_bbs_rules()
