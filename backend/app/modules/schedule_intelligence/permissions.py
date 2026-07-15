# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Schedule Intelligence module permission definitions.

Maps each verb in the Watch → Score → Attribute → Quantify → Decide pipeline
(plus the two governance verbs, ``configure`` and ``lock``) to a minimum role
on the shared ``admin > manager > editor > viewer`` ladder. Registered at boot
from ``__init__.on_startup``.

Rationale for the role floors:
    * ``read`` — VIEWER: anyone on the project may see insights.
    * ``score`` / ``attribute`` / ``quantify`` — EDITOR: running the engines
      and staging analysis is normal project work.
    * ``decide`` — MANAGER: choosing a claim-vs-accelerate recommendation is a
      commercial judgement.
    * ``apply`` — MANAGER: applying a decision changes committed state; it also
      still passes through the existing ``app/core`` approval gate + audit (this
      module adds NO new gate — see plan Phase 0 step 4).
    * ``configure`` — MANAGER: editing confidence thresholds is a policy change
      (versioned + audit-logged, E2.1-AC7).
    * ``lock`` — MANAGER: locking/unlocking a commercial figure is the
      trust-critical E5.2 action.
"""

from app.core.permissions import Role, permission_registry


def register_schedule_intelligence_permissions() -> None:
    """Register permissions for the schedule_intelligence module."""
    permission_registry.register_module_permissions(
        "schedule_intelligence",
        {
            "schedule_intelligence.read": Role.VIEWER,
            "schedule_intelligence.score": Role.EDITOR,
            "schedule_intelligence.attribute": Role.EDITOR,
            "schedule_intelligence.quantify": Role.EDITOR,
            "schedule_intelligence.decide": Role.MANAGER,
            "schedule_intelligence.apply": Role.MANAGER,
            "schedule_intelligence.configure": Role.MANAGER,
            "schedule_intelligence.lock": Role.MANAGER,
        },
    )
