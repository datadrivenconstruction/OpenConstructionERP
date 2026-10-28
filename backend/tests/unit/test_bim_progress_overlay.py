# OpenConstructionERP — DataDrivenConstruction (DDC)
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the BIM "By progress" overlay folding logic.

Lane #28 adds a model-based progress overlay to the BIM 3D viewer: each
element is coloured by the latest ``percent_complete`` of its linked BOQ
position(s). The backend computes a ``current_pct`` per element from the
latest ``ProgressEntry`` of every linked position, taking the MAX across
an element's positions.

These tests pin the pure folding step
(``service._fold_progress_onto_elements``) which turns a
``{position_id: latest_pct}`` map into a ``{element_id: current_pct}``
map. The folding is pure (no DB), so it is fully deterministic and runs
without booting Postgres.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.modules.bim_hub.service import (
    _fold_progress_date_onto_elements,
    _fold_progress_onto_elements,
)


@dataclass
class _StubLink:
    """Minimal stand-in for ``BOQElementLink`` — only the field the
    folding helper reads (``boq_position_id``)."""

    boq_position_id: uuid.UUID


@dataclass
class _StubElement:
    """Minimal stand-in for ``BIMElement`` — only ``id`` and the
    eager-loaded ``boq_links`` the folding helper reads."""

    id: uuid.UUID
    boq_links: list[_StubLink] = field(default_factory=list)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()


def test_single_linked_position_uses_its_pct() -> None:
    pos = _new_id()
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(pos)])

    out = _fold_progress_onto_elements([elem], {pos: 42.5})

    assert out == {elem.id: 42.5}


def test_multiple_positions_takes_max() -> None:
    pos_a, pos_b, pos_c = _new_id(), _new_id(), _new_id()
    elem = _StubElement(
        id=_new_id(),
        boq_links=[_StubLink(pos_a), _StubLink(pos_b), _StubLink(pos_c)],
    )

    out = _fold_progress_onto_elements(
        [elem],
        {pos_a: 10.0, pos_b: 80.0, pos_c: 55.0},
    )

    # The most-advanced linked position is the element's headline progress.
    assert out[elem.id] == 80.0


def test_unlinked_element_is_omitted() -> None:
    elem = _StubElement(id=_new_id(), boq_links=[])

    out = _fold_progress_onto_elements([elem], {_new_id(): 99.0})

    # No link → absent from the dict → viewer paints it neutral grey.
    assert elem.id not in out
    assert out == {}


def test_linked_position_without_progress_is_omitted() -> None:
    pos_with = _new_id()
    pos_without = _new_id()
    elem = _StubElement(
        id=_new_id(),
        boq_links=[_StubLink(pos_without)],
    )

    # The map only knows about a DIFFERENT position, so this element has
    # no recorded percentage and must be omitted.
    out = _fold_progress_onto_elements([elem], {pos_with: 33.0})

    assert out == {}


def test_zero_percent_is_kept_not_dropped() -> None:
    # 0% is a real, recorded observation ("not started") and must survive —
    # it is distinct from "no data". The BIM red ramp end depends on it.
    pos = _new_id()
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(pos)])

    out = _fold_progress_onto_elements([elem], {pos: 0.0})

    assert out == {elem.id: 0.0}


def test_hundred_percent_passes_through() -> None:
    pos = _new_id()
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(pos)])

    out = _fold_progress_onto_elements([elem], {pos: 100.0})

    assert out == {elem.id: 100.0}


def test_empty_progress_map_returns_empty() -> None:
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(_new_id())])

    out = _fold_progress_onto_elements([elem], {})

    assert out == {}


def test_multiple_elements_independent() -> None:
    pos_a, pos_b, pos_shared = _new_id(), _new_id(), _new_id()
    elem_a = _StubElement(id=_new_id(), boq_links=[_StubLink(pos_a), _StubLink(pos_shared)])
    elem_b = _StubElement(id=_new_id(), boq_links=[_StubLink(pos_b)])
    elem_c = _StubElement(id=_new_id(), boq_links=[])  # unlinked

    out = _fold_progress_onto_elements(
        [elem_a, elem_b, elem_c],
        {pos_a: 20.0, pos_b: 70.0, pos_shared: 95.0},
    )

    assert out[elem_a.id] == 95.0  # max(20, 95)
    assert out[elem_b.id] == 70.0
    assert elem_c.id not in out


def test_element_with_none_boq_links_is_safe() -> None:
    # Defensive: a row whose ``boq_links`` is None (not an empty list)
    # must not raise — the helper guards with ``elem.boq_links or []``.
    elem = _StubElement(id=_new_id())
    elem.boq_links = None  # type: ignore[assignment]

    out = _fold_progress_onto_elements([elem], {_new_id(): 50.0})

    assert out == {}


# ── Date fold (selected-element "as of <date>" in the By-progress panel) ──


def test_date_fold_single_position_uses_its_date() -> None:
    pos = _new_id()
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(pos)])

    out = _fold_progress_date_onto_elements(
        [elem],
        {pos: 42.5},
        {pos: "2026-06-01T00:00:00+00:00"},
    )

    assert out == {elem.id: "2026-06-01T00:00:00+00:00"}


def test_date_fold_follows_the_max_pct_winner() -> None:
    # The date shown must belong to the SAME entry whose pct is displayed
    # (the MAX), not the most-recently-dated position.
    pos_low, pos_high = _new_id(), _new_id()
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(pos_low), _StubLink(pos_high)])

    out = _fold_progress_date_onto_elements(
        [elem],
        {pos_low: 10.0, pos_high: 90.0},
        {pos_low: "2026-06-05T00:00:00+00:00", pos_high: "2026-05-01T00:00:00+00:00"},
    )

    # 90% wins → its (older) date is the one surfaced.
    assert out[elem.id] == "2026-05-01T00:00:00+00:00"


def test_date_fold_omits_when_winner_has_no_date() -> None:
    pos = _new_id()
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(pos)])

    out = _fold_progress_date_onto_elements([elem], {pos: 30.0}, {pos: None})

    assert out == {}


def test_date_fold_omits_unlinked_element() -> None:
    elem = _StubElement(id=_new_id(), boq_links=[])

    out = _fold_progress_date_onto_elements(
        [elem],
        {_new_id(): 50.0},
        {_new_id(): "2026-06-01T00:00:00+00:00"},
    )

    assert out == {}


def test_date_fold_empty_pct_map_returns_empty() -> None:
    pos = _new_id()
    elem = _StubElement(id=_new_id(), boq_links=[_StubLink(pos)])

    out = _fold_progress_date_onto_elements([elem], {}, {pos: "2026-06-01T00:00:00+00:00"})

    assert out == {}
