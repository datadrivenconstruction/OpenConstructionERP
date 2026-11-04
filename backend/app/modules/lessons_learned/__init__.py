# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned: a cross-project register captured at closeout and surfaced as "seen on N past projects"."""

from app.modules.lessons_learned.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.lessons_learned.permissions import register_lessons_learned_permissions
    from app.modules.lessons_learned.validators import register_lessons_learned_rules

    register_lessons_learned_permissions()
    register_lessons_learned_rules()
