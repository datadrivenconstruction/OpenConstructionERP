# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Demo projects that carry a hand-authored, localised register.

Some demo projects are filmed and demonstrated in German. Their registers
are written by dedicated seeders (``seed_variations_showcase_de``,
``seed_daily_diary_showcase_de``) in German, on German working days, with
the contractual detail a Bauleiter expects to see.

Every generic English sprinkle must filter these projects out **before**
its own already-seeded guard, not after. Filtering after the guard is the
same bug twice: the sprinkle's own thin rows read as "something is already
here", the rich seeder skips the project, and the project ends up with the
sprinkle rather than the register it was written for.

The set lives here rather than in any one seeder so the filter reads the
same list everywhere. It is deliberately keyed on ``demo_id`` (the marker
in ``Project.metadata_``) and not on project name or id, because those
differ per install while the demo id does not.
"""

from __future__ import annotations

GERMAN_SHOWCASE_DEMO_IDS: frozenset[str] = frozenset(
    {
        "office-frankfurt",
        "retail-market-heidelberg",
        "retail-market-karlsruhe",
        "retail-market-heilbronn",
    }
)

#: Demo projects whose field diary is the German hand-authored one, though their other registers are
#: told by a pack. The two pack projects are filmed in German, and the generic English diary
#: ("Day shift record", "Overcast") has no place in them. Kept apart from the set above because
#: that one also switches the variations and contracts seeders, which these projects do not use.
GERMAN_DIARY_DEMO_IDS: frozenset[str] = GERMAN_SHOWCASE_DEMO_IDS | {"residential-regensburg", "school-ludwigsburg"}

__all__ = ["GERMAN_DIARY_DEMO_IDS", "GERMAN_SHOWCASE_DEMO_IDS"]
