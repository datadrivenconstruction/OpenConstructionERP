# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The last rung of the display-title chain may not be a bare identifier.

:class:`VectorHit` resolves a title from the stored payload, then from the
embedded text, and finally from the row id. Both frontend consumers of the
unified search render that title as the row label, and one of them does so
with no guard of its own, so the last rung put thirty six characters of
hexadecimal in front of the reader. An identifier names nothing to a person
and cannot be told apart from the next unnamed row.

The assertions below compare the title against the id rather than merely
requiring one. A UUID is a non-empty string, so a check that only asked for a
truthy title would pass against exactly the output being fixed here.

No database is involved: ``VectorHit`` is a dataclass with a property.
"""

from __future__ import annotations

from app.core.vector_index import VectorHit

ROW_ID = "4015cdf0-9c2a-4f7e-9a1b-2f8e7d6c5b4a"


def _hit(**overrides: object) -> VectorHit:
    """A hit whose payload and text are empty unless a test says otherwise."""
    kwargs: dict[str, object] = {
        "id": ROW_ID,
        "score": 0.5,
        "text": "",
        "module": "boq",
        "project_id": "",
        "tenant_id": "",
        "payload": {},
        "collection": "oe_boq_positions",
    }
    kwargs.update(overrides)
    return VectorHit(**kwargs)  # type: ignore[arg-type]


def test_a_hit_with_nothing_to_say_is_not_titled_by_its_id() -> None:
    """The rung that used to return the identifier verbatim."""
    hit = _hit()

    assert hit.title != hit.id, "a bare identifier is not a name a person can read"
    assert hit.title.strip(), "and it may not be blank either"


def test_the_last_resort_names_the_kind_and_shortens_the_reference() -> None:
    """A reader needs to know what the row is and to tell it from its neighbour."""
    hit = _hit()

    assert "boq" in hit.title
    assert ROW_ID[:8] in hit.title
    assert ROW_ID not in hit.title, "the whole identifier should not survive"
    assert len(hit.title) < len(ROW_ID)


def test_two_unnamed_hits_of_different_kinds_read_differently() -> None:
    """Otherwise every unnamed row collapses into the same label."""
    boq = _hit(module="boq")
    risk = _hit(module="risk")

    assert boq.title != risk.title


def test_the_collection_names_the_kind_when_the_module_is_empty() -> None:
    """Some adapters set only the collection, and "oe_" is storage, not language."""
    hit = _hit(module="", collection="oe_risks")

    assert "risks" in hit.title
    assert not hit.title.startswith("oe_")


# --- Negative controls: the earlier rungs must keep winning ---


def test_a_payload_title_still_wins() -> None:
    """The stored title is the label whenever the indexer wrote one."""
    hit = _hit(payload={"title": "Concrete C30/37 to foundations"})

    assert hit.title == "Concrete C30/37 to foundations"


def test_the_embedded_text_still_beats_the_last_resort() -> None:
    """A snippet of real text tells the reader more than a type and an id."""
    hit = _hit(text="Reinforcement to the north retaining wall")

    assert hit.title == "Reinforcement to the north retaining wall"
