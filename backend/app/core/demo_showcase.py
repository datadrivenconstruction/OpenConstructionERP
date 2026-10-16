# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo projects that carry a hand-authored, localised register.

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

from typing import Any

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

#: Demo projects whose site has not started on the install day. The generic seeder writes site
#: registers (open RFIs to the contractors, safety incidents) for every project it builds; on a
#: school still waiting for its construction gate there is no contractor to ask and no site to have
#: an accident on, so those registers stay empty there.
NOT_STARTED_SITE_DEMO_IDS: frozenset[str] = frozenset({"school-ludwigsburg"})


def generic_site_rows(demo_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The generic site register rows for ``demo_id``, none for a site that has not started."""
    return [] if demo_id in NOT_STARTED_SITE_DEMO_IDS else rows


#: How far the money of each cost group has gone on the install day, for demo projects whose story
#: names a construction stage: (share bound by order, share already incurred), keyed by the DIN 276
#: group of the bill section. A group not listed has nothing bound yet. The generic budget seed
#: spends 80 % of the first sections whatever the project, which put a pit-stage site at half its
#: budget spent and "over budget", and a school that has not started at a third. Both budget
#: registers of the hub (the 5D budget lines and the finance budgets) read the same shares, so the
#: two widgets agree.
STAGE_SPEND: dict[str, dict[str, tuple[float, float]]] = {
    # Running site in its pit stage: enabling works and the pit lots are under contract and partly
    # done, the site set-up is half let, the design fees of stages 1 to 4 are mostly paid.
    "residential-regensburg": {"210": (1.0, 0.6), "310": (1.0, 0.35), "390": (0.5, 0.15), "700": (0.6, 0.35)},
    # School before its construction gate: the design contract runs, the ordnance survey is done.
    "school-ludwigsburg": {"210": (0.15, 0.1), "700": (0.5, 0.2)},
}


def stage_spend(demo_id: str, section_code: str | None) -> tuple[float, float] | None:
    """(bound share, incurred share) of a bill section on the install day, None for a generic demo."""
    table = STAGE_SPEND.get(demo_id)
    if table is None:
        return None
    return table.get(str(section_code or "")[:3], (0.0, 0.0))


__all__ = [
    "GERMAN_DIARY_DEMO_IDS",
    "GERMAN_SHOWCASE_DEMO_IDS",
    "NOT_STARTED_SITE_DEMO_IDS",
    "STAGE_SPEND",
    "generic_site_rows",
    "stage_spend",
]
