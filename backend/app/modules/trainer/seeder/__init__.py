# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The trainer seeder: a course's seed written into the learner's own project.

``plan`` turns a course spec into ordered steps per stage (pure); ``stages``
runs the steps of one stage through the owning modules' services and returns
the ``seeded_refs`` the enrolment stores. See design §5 and decisions 10, 12,
14, 18, 20, 21 and 27.
"""

from __future__ import annotations

from app.modules.trainer.seeder.plan import (
    ENROLMENT_STAGES,
    PlanError,
    SeedPlan,
    SeedStep,
    build_plan,
    reading_timestamp,
    stage_key,
)
from app.modules.trainer.seeder.stages import (
    DEFAULT_CSA_BOQ_NAME,
    SeedContext,
    SeedError,
    execute_enrolment,
    execute_stage,
    seeding,
    seeding_enrolment,
)

__all__ = [
    "DEFAULT_CSA_BOQ_NAME",
    "ENROLMENT_STAGES",
    "PlanError",
    "SeedContext",
    "SeedError",
    "SeedPlan",
    "SeedStep",
    "build_plan",
    "execute_enrolment",
    "execute_stage",
    "reading_timestamp",
    "seeding",
    "seeding_enrolment",
    "stage_key",
]
