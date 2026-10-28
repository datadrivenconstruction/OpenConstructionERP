# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo EIR matrix shows a project, not a failed one.

Two defects, both found by looking at a screenshot rather than by walking the
tree, and both invisible to every gate because the data was well formed and
merely wrong to read.

The matrix painted every cell red and scored nought per cent on every row. It
was not a rendering fault: the matrix is reconstructed from deliverable rows and
scores coverage as accepted over the rows that exist, and the demo seeded a
requirement set with no deliverables at all. Zero rows is zero coverage, so the
screen told the truth about data that should never have shipped.

The requirement names were slugs. ``entity`` was minted by lowercasing a trade
item and punching out its spaces, which put ``blinding_concrete,__15_mpa`` on
screen where "Blinding concrete, 15 MPa" belongs. Nothing depended on the slug
form: ``entity`` is matched against a model's ``element_type`` and a bill's
trade item never matched one in either spelling.

These assertions are about generated data only, so they run in the unit lane and
need no database.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data

#: The project start the installer uses, so the generated dates line up.
BASE = datetime(2026, 4, 1)

#: A slug in the sense that caused the defect: underscores doing the work of
#: spaces. Written as a positive description of the bad shape rather than as a
#: list of the two names that were reported, so a third one cannot slip in.
LOOKS_LIKE_A_SLUG = re.compile(r"^[^ ]*_[^ ]*$")


def _requirements(demo_id: str) -> list[dict]:
    """Every generated requirement of one demo template."""
    template = DEMO_TEMPLATES[demo_id]
    generated = _generate_module_data(template, uuid.uuid4(), uuid.uuid4(), "demo", BASE)
    return [item for rs in generated.get("requirements", []) for item in rs.get("items", [])]


def _status(row: dict) -> str:
    """The state the matrix derives, from the timestamps, as the model does."""
    if row.get("accepted_at") is not None:
        return "accepted"
    if row.get("submitted_at") is not None:
        return "submitted"
    return "missing"


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_every_demo_requirement_demands_at_least_one_deliverable(demo_id: str) -> None:
    """No deliverables is not an empty matrix, it is a red one scored at nought."""
    items = _requirements(demo_id)
    assert items, f"{demo_id} generates no requirements at all"

    without = [item["entity"] for item in items if not item.get("deliverables")]
    assert not without, (
        f"{demo_id}: {len(without)} requirements carry no deliverable rows, so their matrix row paints "
        f"entirely red at nought per cent however healthy the project is. First: {without[:3]}"
    )


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_the_demo_matrix_shows_more_than_one_state(demo_id: str) -> None:
    """All green teaches as little as all red.

    The screen exists to show that coverage is partial and where it is thin, so
    a demo that is uniform in either direction demonstrates nothing. Asserted on
    the states themselves rather than on a coverage percentage, because a single
    number can be middling while every row is identical.
    """
    rows = [row for item in _requirements(demo_id) for row in item.get("deliverables", [])]
    assert rows, f"{demo_id} generates no deliverables"

    states = {_status(row) for row in rows}
    assert len(states) > 1, f"{demo_id}: every deliverable is {states.pop()!r}, so the matrix is one flat colour"
    assert "accepted" in states, f"{demo_id}: nothing is signed off, so coverage is nought on every row"


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_a_requirement_is_named_and_not_slugged(demo_id: str) -> None:
    """``entity`` is what the matrix prints, so it has to read as a name."""
    slugged = [
        item["entity"] for item in _requirements(demo_id) if LOOKS_LIKE_A_SLUG.match(str(item.get("entity", "")))
    ]
    assert not slugged, (
        f"{demo_id}: {len(slugged)} requirement names are slugs rather than names, which is what put "
        f"'blinding_concrete,__15_mpa' in front of a reader. Offenders: {slugged[:3]}"
    )
