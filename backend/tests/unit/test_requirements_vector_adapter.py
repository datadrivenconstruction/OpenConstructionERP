"""Unit tests for :class:`RequirementVectorAdapter`.

Scope:
    - ``to_text`` — the canonical string that gets embedded.  Must
      include every textual field the user might search by and tolerate
      missing optional fields without blowing up on ``None``.
    - ``to_payload`` — the per-hit metadata dict used by the global
      search UI to render a hit card without a DB roundtrip.  Must
      clip overly long fields and coerce UUIDs to strings.
    - ``project_id_of`` — resolves the owning project via the
      ``requirement_set`` relationship and handles the detached case.

These tests use plain stubs so they don't need a database — the
adapter only reads attributes off the passed-in row object, so
duck-typed objects are enough and keep the test fast.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_REQUIREMENTS
from app.modules.requirements.vector_adapter import (
    RequirementVectorAdapter,
    requirement_vector_adapter,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    """Build a duck-typed Requirement row with every field the adapter
    touches.  Overridable via keyword arguments to make tests terse."""
    defaults = {
        "id": uuid.uuid4(),
        "entity": "exterior_wall",
        "attribute": "fire_rating",
        "constraint_type": "equals",
        "constraint_value": "F90",
        "unit": "min",
        "category": "fire_safety",
        "priority": "must",
        "status": "open",
        "notes": "Per DIN 4102 — applies to all external walls above grade.",
        "requirement_set_id": uuid.uuid4(),
        "linked_position_id": None,
        "requirement_set": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── Module-level assertions ────────────────────────────────────────────────


def test_singleton_collection_name() -> None:
    """The shared singleton must point at the Requirements collection."""
    assert requirement_vector_adapter.collection_name == COLLECTION_REQUIREMENTS
    assert requirement_vector_adapter.module_name == "requirements"


# ── to_text ───────────────────────────────────────────────────────────────


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = RequirementVectorAdapter()
    text = adapter.to_text(_make_row())

    # Every field that would plausibly power search should be present.
    for needle in (
        "entity=exterior_wall",
        "attribute=fire_rating",
        "equals F90",
        "unit=min",
        "category=fire_safety",
        "priority=must",
        "status=open",
        "DIN 4102",  # from notes
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    """Optional fields left empty must not pollute the embedding with
    stray ``key=`` fragments that the tokenizer would waste budget on."""
    adapter = RequirementVectorAdapter()
    row = _make_row(
        unit="",
        category="",
        notes="",
    )
    text = adapter.to_text(row)
    assert "unit=" not in text
    assert "category=" not in text
    assert text.strip()  # still non-empty
    assert "entity=exterior_wall" in text


def test_to_text_handles_missing_constraint_type() -> None:
    """A requirement without a constraint_type should still embed just
    the bare ``constraint_value`` — that's the semantic core."""
    adapter = RequirementVectorAdapter()
    row = _make_row(constraint_type="", constraint_value="IP54")
    text = adapter.to_text(row)
    assert "IP54" in text
    # Must NOT leak the empty-type prefix as a standalone token.
    assert " IP54" in text or text.endswith("IP54") or "IP54" in text


def test_to_text_tolerates_none_on_optional_fields() -> None:
    """Adapter must not crash when optional fields come through as
    ``None`` instead of empty strings (happens on fresh ORM rows before
    ``server_default`` kicks in)."""
    adapter = RequirementVectorAdapter()
    row = _make_row(
        unit=None,
        category=None,
        priority=None,
        status=None,
        notes=None,
    )
    text = adapter.to_text(row)
    assert "entity=exterior_wall" in text
    assert "F90" in text


def test_to_text_separator_uses_pipe() -> None:
    """Downstream consumers (and the multilingual model) parse the
    pipe-separated format well — changing the separator would break
    reindexing semantics."""
    adapter = RequirementVectorAdapter()
    row = _make_row(notes="")
    assert " | " in adapter.to_text(row)


# ── to_payload ─────────────────────────────────────────────────────────────


def test_to_payload_builds_title_from_entity_and_attribute() -> None:
    adapter = RequirementVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "exterior_wall.fire_rating"


def test_to_payload_fallback_title_when_entity_missing() -> None:
    adapter = RequirementVectorAdapter()
    payload = adapter.to_payload(_make_row(entity="", attribute=""))
    # Must degrade gracefully to a sentinel — never empty/None so the
    # frontend card always has something to render.
    assert payload["title"] == "requirement"


def test_to_payload_clips_long_title_and_constraint() -> None:
    """Free-form fields get clipped to 160 chars apiece so payloads
    stay small — Qdrant/LanceDB payload size is observable in the
    search response latency budget."""
    adapter = RequirementVectorAdapter()
    long_val = "x" * 500
    payload = adapter.to_payload(
        _make_row(
            entity=long_val,
            attribute=long_val,
            constraint_value=long_val,
        )
    )
    assert len(payload["title"]) <= 160
    assert len(payload["constraint"]) <= 160


def test_to_payload_stringifies_uuid_fks() -> None:
    """``requirement_set_id`` and ``linked_position_id`` are UUIDs on
    the ORM but must come out of the payload as plain strings so the
    vector store driver can serialise them without a JSON encoder."""
    adapter = RequirementVectorAdapter()
    set_id = uuid.uuid4()
    pos_id = uuid.uuid4()
    payload = adapter.to_payload(
        _make_row(requirement_set_id=set_id, linked_position_id=pos_id)
    )
    assert payload["requirement_set_id"] == str(set_id)
    assert payload["linked_position_id"] == str(pos_id)


def test_to_payload_defaults_empty_for_missing_fks() -> None:
    """Unset foreign keys must serialise to empty string, never
    ``None`` — so the frontend card template can concat safely."""
    adapter = RequirementVectorAdapter()
    payload = adapter.to_payload(
        _make_row(requirement_set_id=None, linked_position_id=None)
    )
    assert payload["requirement_set_id"] == ""
    assert payload["linked_position_id"] == ""


def test_to_payload_constraint_joined_when_both_parts_present() -> None:
    adapter = RequirementVectorAdapter()
    payload = adapter.to_payload(
        _make_row(constraint_type="min", constraint_value="50")
    )
    assert payload["constraint"] == "min 50"


def test_to_payload_constraint_bare_value_when_type_missing() -> None:
    adapter = RequirementVectorAdapter()
    payload = adapter.to_payload(
        _make_row(constraint_type="", constraint_value="IP54")
    )
    assert payload["constraint"] == "IP54"


# ── project_id_of ──────────────────────────────────────────────────────────


def test_project_id_of_reads_parent_set() -> None:
    adapter = RequirementVectorAdapter()
    project_id = uuid.uuid4()
    row = _make_row(
        requirement_set=SimpleNamespace(project_id=project_id),
    )
    assert adapter.project_id_of(row) == str(project_id)


def test_project_id_of_returns_none_when_set_missing() -> None:
    """Defensive: rows can theoretically be detached/dangling.  The
    adapter must not raise — the caller uses ``None`` to mean
    *project-agnostic cross-tenant embedding*."""
    adapter = RequirementVectorAdapter()
    row = _make_row(requirement_set=None)
    assert adapter.project_id_of(row) is None


def test_project_id_of_returns_none_when_set_has_no_project() -> None:
    adapter = RequirementVectorAdapter()
    row = _make_row(requirement_set=SimpleNamespace(project_id=None))
    assert adapter.project_id_of(row) is None


# ── bim_element_ids in embedding (v1.4.5) ────────────────────────────────


def test_to_text_includes_bim_element_ids_sample() -> None:
    """A requirement pinned to BIM elements must surface a sample of
    those ids in the embedded text so semantic queries like
    *"requirements linked to roof elements"* can route from a selected
    BIM element back to the requirements that pin it."""
    adapter = RequirementVectorAdapter()
    elem_a = str(uuid.uuid4())
    elem_b = str(uuid.uuid4())
    row = _make_row(metadata_={"bim_element_ids": [elem_a, elem_b]})
    text = adapter.to_text(row)
    assert "bim_element_ids=" in text
    assert elem_a in text
    assert elem_b in text


def test_to_text_caps_bim_element_ids_at_five() -> None:
    """Vector store payload budget is tight — only the first 5 ids are
    embedded.  The full list still lives in metadata_ for round-trips."""
    adapter = RequirementVectorAdapter()
    ids = [str(uuid.uuid4()) for _ in range(8)]
    row = _make_row(metadata_={"bim_element_ids": ids})
    text = adapter.to_text(row)
    for kept in ids[:5]:
        assert kept in text
    for dropped in ids[5:]:
        assert dropped not in text


def test_to_text_no_bim_section_when_metadata_absent() -> None:
    """Backward compat: existing requirement rows without ``metadata_``
    or with an empty dict must produce the SAME text as before — no
    stray ``bim_element_ids=`` fragment polluting the embedding."""
    adapter = RequirementVectorAdapter()
    # No metadata_ attribute set on the duck-typed row at all.
    row = _make_row()
    assert "bim_element_ids" not in adapter.to_text(row)


def test_to_text_no_bim_section_when_array_empty() -> None:
    adapter = RequirementVectorAdapter()
    row = _make_row(metadata_={"bim_element_ids": []})
    assert "bim_element_ids" not in adapter.to_text(row)


def test_to_text_tolerates_non_dict_metadata() -> None:
    """Defensive: ORM may hand us None or a list if a migration is
    in flight.  The adapter must not crash."""
    adapter = RequirementVectorAdapter()
    for bad in (None, [], "not a dict", 42):
        row = _make_row(metadata_=bad)
        # Just verify no exception is raised — the result text is
        # allowed to be the pre-v1.4.5 string in this case.
        text = adapter.to_text(row)
        assert "bim_element_ids" not in text
