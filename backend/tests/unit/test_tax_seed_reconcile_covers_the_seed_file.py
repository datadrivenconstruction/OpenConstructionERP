# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The reconciler has to have an opinion about every rate the seed file ships.

Why this file exists at all
---------------------------
``tax_seed_reconcile`` splits the shipped rate lines three ways: lines added
after the file's first release, which it may deliver; lines another repair
owns, which it must not touch; and everything else, which is what dates a
database's seed.

The third group is derived rather than written out, and that is the hazard. A
line added to ``tax_configurations.json`` without a matching entry in
``LINE_FIRST_SHIPPED`` falls silently into it, where it does two wrong things
at once: it is never delivered to anybody, which is the original defect coming
straight back for that rate, and it becomes evidence about when a database was
seeded, which it cannot be, because the installs being dated are exactly the
ones that do not have it.

Nothing else would notice. The repair still runs, still reports clean, and the
rate is simply absent on every upgraded install - which is the failure mode the
whole registry exists because of. So the seed file is pinned here, and adding a
row to it is meant to fail this test and make somebody say which release the
row first shipped in.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.modules.i18n_foundation.romania_vat import _NEW_REDUCED, _NEW_STANDARD
from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_seed_reconcile import (
    LINE_FIRST_SHIPPED,
    REPAIRED_ELSEWHERE,
    anchor_lines,
    delivery_key,
)

#: How many rate lines have shipped since the seed file's first release and are
#: not owned by another repair. Pinned beside the digest below so a failure says
#: how far off it is before anybody has to read a hash.
EXPECTED_ANCHOR_LINES = 69

#: SHA-256 over the anchoring rate lines, one ``country/tax_code`` per line,
#: sorted. Pinned rather than merely counted so that swapping one line for
#: another - which leaves the count alone and would leave the new line
#: unclassified - fails too.
EXPECTED_ANCHOR_DIGEST = "1d7dc58cb823600bd51b71828a248354cd34bd1c9c7f1cb8ecb32388e7e0daa9"


def _digest(lines) -> str:
    return hashlib.sha256("\n".join(sorted(delivery_key(line) for line in lines)).encode()).hexdigest()


def test_every_shipped_rate_line_is_classified() -> None:
    """A new line in the seed file must be declared, not absorbed by a default."""
    anchors = anchor_lines()
    assert len(anchors) == EXPECTED_ANCHOR_LINES, (
        f"the seed file's set of long-standing rate lines changed: expected "
        f"{EXPECTED_ANCHOR_LINES}, found {len(anchors)}. If you added a rate to "
        "tax_configurations.json, record the date its commit landed in "
        "LINE_FIRST_SHIPPED so it can be delivered to installs seeded before it, then update "
        "the count and digest here. A line left out of that table is never delivered to "
        "anybody and is also treated as evidence about when a database was seeded, which it "
        "cannot be."
    )
    assert _digest(anchors) == EXPECTED_ANCHOR_DIGEST, (
        "the seed file's long-standing rate lines are not the ones this test was pinned "
        "against, even though there are still the same number of them. One was swapped for "
        "another; the new one needs an entry in LINE_FIRST_SHIPPED."
    )


def test_no_line_is_both_deliverable_and_owned_elsewhere() -> None:
    """Two repairs writing one rate line would behave differently by registry order."""
    overlap = set(LINE_FIRST_SHIPPED) & REPAIRED_ELSEWHERE
    assert not overlap, f"rate lines claimed by two repairs at once: {sorted(overlap)}"


def test_every_declared_line_is_actually_in_the_seed_file() -> None:
    """A stale entry would silently narrow what dates a seed, and never be delivered."""
    shipped = {(row["country_code"], row["tax_code"]) for row in load_tax_seed_rows()}
    declared = set(LINE_FIRST_SHIPPED) | REPAIRED_ELSEWHERE
    missing = declared - shipped
    assert not missing, (
        f"declared rate lines that the seed file no longer ships: {sorted(missing)}. "
        "Each one is excluded from the evidence that dates a database's seed while delivering "
        "nothing, so it costs accuracy and buys nothing."
    )


def test_the_romanian_exclusion_is_what_the_romanian_repair_writes() -> None:
    """The exclusion has to track that repair, not a memory of what it used to insert.

    ``romania_vat_2025`` supersedes the 19 % rate rather than adding beside it,
    so it closes a window as it opens one and this repair may not go near those
    lines. If it ever inserts a third tax code, that code has to be excluded
    here too, or both repairs write it and which one wins depends on the order
    the registry happens to be in.
    """
    written_by_romania = {
        ("RO", _NEW_STANDARD["tax_code"]),
        ("RO", _NEW_REDUCED["tax_code"]),
    }
    assert written_by_romania == REPAIRED_ELSEWHERE


def test_every_ship_date_is_a_past_date() -> None:
    """A date in the future would withhold the line from every install for ever."""
    now = datetime.now(UTC)
    for line, iso in LINE_FIRST_SHIPPED.items():
        moment = datetime.fromisoformat(iso).replace(tzinfo=UTC)
        assert moment < now, f"{delivery_key(line)} claims to ship at {iso}, which has not happened yet"
