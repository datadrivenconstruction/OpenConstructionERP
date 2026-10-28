# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure storage-connector framework (roadmap item #26).

No DB / network -- exercises only the IO-free normalizer, the in-memory
adapter and the deterministic sync-plan reconciler. Runs on Python 3.11.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.modules.connectors.storage_connector import (
    ALIAS_MAP,
    IncomingDocument,
    InMemoryAdapter,
    StorageAdapter,
    SyncPlan,
    compute_sync_plan,
    hash_bytes,
    is_within_base,
    normalize_entry,
)

# ---------------------------------------------------------------------------
# Alias mapping
# ---------------------------------------------------------------------------

# (canonical_field, raw_key, raw_value, expected_value) for every aliased key.
_ALIAS_CASES = [
    # name
    ("name", "name", "plan.pdf", "plan.pdf"),
    ("name", "filename", "plan.pdf", "plan.pdf"),
    ("name", "title", "plan.pdf", "plan.pdf"),
    ("name", "file_name", "plan.pdf", "plan.pdf"),
    # external_id
    ("external_id", "external_id", "ext-1", "ext-1"),
    ("external_id", "id", "id-1", "id-1"),
    ("external_id", "key", "key-1", "key-1"),
    ("external_id", "path", "/a/b.pdf", "/a/b.pdf"),
    ("external_id", "object_key", "ok-1", "ok-1"),
    # content_hash (lower-cased)
    ("content_hash", "content_hash", "ABC123", "abc123"),
    ("content_hash", "hash", "ABC123", "abc123"),
    ("content_hash", "etag", "ABC123", "abc123"),
    ("content_hash", "checksum", "ABC123", "abc123"),
    ("content_hash", "md5", "ABC123", "abc123"),
    ("content_hash", "sha256", "ABC123", "abc123"),
    # size_bytes
    ("size_bytes", "size_bytes", 10, 10),
    ("size_bytes", "size", 11, 11),
    ("size_bytes", "bytes", 12, 12),
    ("size_bytes", "content_length", 13, 13),
    # content_type
    ("content_type", "content_type", "application/pdf", "application/pdf"),
    ("content_type", "mime", "application/pdf", "application/pdf"),
    ("content_type", "mime_type", "application/pdf", "application/pdf"),
    ("content_type", "type", "application/pdf", "application/pdf"),
    # modified_at
    ("modified_at", "modified_at", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ("modified_at", "modified", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ("modified_at", "last_modified", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ("modified_at", "updated_at", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    # folder
    ("folder", "folder", "drawings", "drawings"),
    ("folder", "prefix", "drawings", "drawings"),
    ("folder", "directory", "drawings", "drawings"),
]


@pytest.mark.parametrize(("canonical", "raw_key", "raw_value", "expected"), _ALIAS_CASES)
def test_alias_mapping_every_field(canonical, raw_key, raw_value, expected):
    # Always include a name so external_id has something to fall back to and
    # the descriptor is realistic; for the name-cases the alias supplies it.
    raw = {raw_key: raw_value}
    if canonical != "name":
        raw["name"] = "doc.pdf"
    doc = normalize_entry(raw, source="src")
    assert getattr(doc, canonical) == expected


def test_alias_map_is_consistent_with_dataclass():
    # Every canonical key in ALIAS_MAP is a real IncomingDocument field, and
    # the first alias for each canonical key is the canonical name itself.
    fields = set(IncomingDocument.__dataclass_fields__)
    for canonical, aliases in ALIAS_MAP.items():
        assert canonical in fields
        assert aliases[0] == canonical


def test_alias_keys_are_case_insensitive():
    raw = {
        "FileName": "Report.PDF",
        "ETag": '"DEADBEEF"',
        "Content-Length-Unknown": 5,  # not an alias -> metadata
        "SIZE": "42",
        "Last_Modified": "2026-06-25",
        "PREFIX": "incoming",
        "OBJECT_KEY": "k-9",
        "MIME": "application/pdf",
    }
    doc = normalize_entry(raw, source="src")
    assert doc.name == "Report.PDF"
    assert doc.content_hash == "deadbeef"  # de-quoted + lower-cased
    assert doc.size_bytes == 42
    assert doc.modified_at == "2026-06-25"
    assert doc.folder == "incoming"
    assert doc.external_id == "k-9"
    assert doc.content_type == "application/pdf"
    # Unknown key preserved with its original spelling.
    assert doc.metadata == {"Content-Length-Unknown": 5}


def test_unknown_keys_go_to_metadata_with_original_spelling():
    raw = {
        "name": "a.txt",
        "Author": "Jane",
        "customField": 7,
        "tags": ["x", "y"],
    }
    doc = normalize_entry(raw, source="src")
    assert doc.metadata == {"Author": "Jane", "customField": 7, "tags": ["x", "y"]}
    # Recognised aliases must NOT leak into metadata.
    assert "name" not in doc.metadata


def test_no_unknown_keys_yields_empty_metadata():
    doc = normalize_entry({"name": "a.txt", "size": 1}, source="src")
    assert doc.metadata == {}


# ---------------------------------------------------------------------------
# Size coercion
# ---------------------------------------------------------------------------

_SIZE_CASES = [
    ("123", 123),  # numeric string
    (" 99 ", 99),  # whitespace-padded numeric string
    (456, 456),  # int passthrough
    (12.9, 12),  # float truncates
    ("12.9", 12),  # numeric-float string truncates
    (None, 0),  # missing
    ("", 0),  # empty string
    ("abc", 0),  # non-numeric
    ("12abc", 0),  # partly numeric -> 0 (not 12)
    (True, 0),  # bool is not a size
    (False, 0),
    (float("nan"), 0),  # NaN
    (float("inf"), 0),  # inf
]


@pytest.mark.parametrize(("raw_size", "expected"), _SIZE_CASES)
def test_size_coercion(raw_size, expected):
    doc = normalize_entry({"name": "a", "size": raw_size}, source="src")
    assert doc.size_bytes == expected
    assert isinstance(doc.size_bytes, int)


def test_missing_size_key_defaults_zero():
    doc = normalize_entry({"name": "a"}, source="src")
    assert doc.size_bytes == 0


# ---------------------------------------------------------------------------
# external_id fallback
# ---------------------------------------------------------------------------


def test_external_id_fallback_folder_and_name():
    doc = normalize_entry({"name": "b.pdf", "folder": "drawings"}, source="src")
    assert doc.external_id == "drawings/b.pdf"


def test_external_id_fallback_name_only_when_no_folder():
    doc = normalize_entry({"name": "b.pdf"}, source="src")
    assert doc.external_id == "b.pdf"


def test_external_id_explicit_wins_over_fallback():
    doc = normalize_entry(
        {"name": "b.pdf", "folder": "drawings", "id": "real-id"},
        source="src",
    )
    assert doc.external_id == "real-id"


def test_external_id_blank_string_falls_back():
    # An empty/whitespace id is treated as absent.
    doc = normalize_entry({"name": "b.pdf", "id": "   "}, source="src")
    assert doc.external_id == "b.pdf"


# ---------------------------------------------------------------------------
# content_hash normalization
# ---------------------------------------------------------------------------


def test_content_hash_lowercased_and_dequoted():
    doc = normalize_entry({"name": "a", "etag": '"AB12CD"'}, source="src")
    assert doc.content_hash == "ab12cd"


def test_content_hash_weak_validator_prefix_stripped():
    doc = normalize_entry({"name": "a", "etag": 'W/"AbCdEf"'}, source="src")
    assert doc.content_hash == "abcdef"


def test_content_hash_missing_stays_empty():
    doc = normalize_entry({"name": "a"}, source="src")
    assert doc.content_hash == ""


def test_empty_hashes_are_never_duplicates_of_each_other():
    # Two distinct documents, both with no content hash, must both be created.
    a = normalize_entry({"name": "a.txt", "id": "a"}, source="src")
    b = normalize_entry({"name": "b.txt", "id": "b"}, source="src")
    assert a.content_hash == "" and b.content_hash == ""
    plan = compute_sync_plan(
        [a, b],
        known_external_ids=set(),
        known_content_hashes=set(),
    )
    assert plan.to_create == (a, b)
    assert plan.duplicate_content == ()


# ---------------------------------------------------------------------------
# String stripping
# ---------------------------------------------------------------------------


def test_text_fields_are_stripped():
    doc = normalize_entry(
        {"name": "  spaced.pdf  ", "id": "  x  ", "mime": "  text/plain  "},
        source="  src  ",
    )
    assert doc.name == "spaced.pdf"
    assert doc.external_id == "x"
    assert doc.content_type == "text/plain"
    assert doc.source == "src"


# ---------------------------------------------------------------------------
# hash_bytes helper
# ---------------------------------------------------------------------------


def test_hash_bytes_matches_hashlib_sha256():
    data = b"hello world"
    assert hash_bytes(data) == hashlib.sha256(data).hexdigest()


def test_hash_bytes_is_lowercase_hex_64_chars():
    h = hash_bytes(b"x")
    assert h == h.lower()
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_bytes_empty_input():
    assert hash_bytes(b"") == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# IncomingDocument dataclass behaviour
# ---------------------------------------------------------------------------


def test_incoming_document_is_frozen():
    doc = normalize_entry({"name": "a", "id": "x"}, source="src")
    with pytest.raises(Exception):
        doc.name = "b"  # type: ignore[misc]


def test_incoming_document_hashable_and_metadata_excluded_from_equality():
    a = IncomingDocument(
        external_id="x",
        name="a",
        content_hash="h",
        size_bytes=1,
        content_type="t",
        source="s",
        metadata={"foo": 1},
    )
    b = IncomingDocument(
        external_id="x",
        name="a",
        content_hash="h",
        size_bytes=1,
        content_type="t",
        source="s",
        metadata={"bar": 2},  # different metadata
    )
    # Hashable (lands in a set) and equal despite differing metadata.
    assert {a, b} == {a}
    assert a == b
    assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# InMemoryAdapter
# ---------------------------------------------------------------------------


def test_inmemory_adapter_roundtrips_through_normalize_entry():
    entries = [
        {"filename": "one.pdf", "id": "1", "etag": '"AA"', "size": "10"},
        {"name": "two.pdf", "folder": "sub", "md5": "BB", "bytes": 20},
    ]
    adapter = InMemoryAdapter(entries, source="watched-folder")
    docs = list(adapter.list_documents())
    assert docs == [
        normalize_entry(entries[0], source="watched-folder"),
        normalize_entry(entries[1], source="watched-folder"),
    ]
    # Source is propagated to every descriptor.
    assert all(d.source == "watched-folder" for d in docs)
    assert docs[0].external_id == "1"
    assert docs[1].external_id == "sub/two.pdf"  # fallback


def test_inmemory_adapter_is_a_storage_adapter_and_sets_source_name():
    adapter = InMemoryAdapter([], source="object-store")
    assert isinstance(adapter, StorageAdapter)
    assert adapter.source_name == "object-store"


def test_inmemory_adapter_empty_listing():
    adapter = InMemoryAdapter([], source="src")
    assert list(adapter.list_documents()) == []


def test_storage_adapter_is_abstract():
    with pytest.raises(TypeError):
        StorageAdapter()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# compute_sync_plan
# ---------------------------------------------------------------------------


def _doc(ext_id, *, name=None, chash="", source="src"):
    return IncomingDocument(
        external_id=ext_id,
        name=name or ext_id,
        content_hash=chash,
        size_bytes=1,
        content_type="application/octet-stream",
        source=source,
    )


def test_sync_plan_all_new():
    docs = [_doc("a", chash="h1"), _doc("b", chash="h2")]
    plan = compute_sync_plan(docs, known_external_ids=set(), known_content_hashes=set())
    assert plan.to_create == (docs[0], docs[1])
    assert plan.duplicate_content == ()
    assert plan.already_known == ()


def test_sync_plan_already_known_by_external_id():
    docs = [_doc("a", chash="h1"), _doc("b", chash="h2")]
    plan = compute_sync_plan(
        docs,
        known_external_ids={"a"},
        known_content_hashes=set(),
    )
    assert plan.already_known == (docs[0],)
    assert plan.to_create == (docs[1],)
    assert plan.duplicate_content == ()


def test_sync_plan_duplicate_by_hash_vs_known_set():
    # Same bytes (h1) as something already stored, but a brand-new id ->
    # duplicate_content, not created and not already_known.
    docs = [_doc("new-id", chash="h1")]
    plan = compute_sync_plan(
        docs,
        known_external_ids={"some-other-id"},
        known_content_hashes={"h1"},
    )
    assert plan.duplicate_content == (docs[0],)
    assert plan.to_create == ()
    assert plan.already_known == ()


def test_sync_plan_duplicate_by_hash_vs_earlier_in_same_run():
    first = _doc("id-1", chash="dup")
    second = _doc("id-2", chash="dup")  # same content, different id, same run
    plan = compute_sync_plan(
        [first, second],
        known_external_ids=set(),
        known_content_hashes=set(),
    )
    assert plan.to_create == (first,)
    assert plan.duplicate_content == (second,)


def test_sync_plan_known_id_takes_precedence_over_duplicate_hash():
    # A doc whose id is known is already_known even if its hash is also a dup.
    doc = _doc("a", chash="h1")
    plan = compute_sync_plan(
        [doc],
        known_external_ids={"a"},
        known_content_hashes={"h1"},
    )
    assert plan.already_known == (doc,)
    assert plan.duplicate_content == ()
    assert plan.to_create == ()


def test_sync_plan_mixed_listing_preserves_order_within_buckets():
    docs = [
        _doc("k1", chash="hk1"),  # already known by id
        _doc("c1", chash="hc1"),  # new
        _doc("d1", chash="hd"),  # duplicate vs known hash
        _doc("c2", chash="hc2"),  # new
        _doc("k2", chash="hk2"),  # already known by id
        _doc("d2", chash="hc1"),  # duplicate vs c1 created earlier this run
    ]
    plan = compute_sync_plan(
        docs,
        known_external_ids={"k1", "k2"},
        known_content_hashes={"hd"},
    )
    assert plan.to_create == (docs[1], docs[3])  # c1, c2 in order
    assert plan.duplicate_content == (docs[2], docs[5])  # d1, d2 in order
    assert plan.already_known == (docs[0], docs[4])  # k1, k2 in order
    assert plan.total_count == 6


def test_sync_plan_repeated_id_in_same_run_second_is_known():
    # Two entries share an external_id within one run; first wins (created),
    # the second is classified as already_known (dedup by id, first wins).
    first = _doc("same", chash="h1")
    second = _doc("same", name="other", chash="h2")
    plan = compute_sync_plan(
        [first, second],
        known_external_ids=set(),
        known_content_hashes=set(),
    )
    assert plan.to_create == (first,)
    assert plan.already_known == (second,)
    assert plan.duplicate_content == ()


def test_sync_plan_empty_listing_is_empty_plan():
    plan = compute_sync_plan([], known_external_ids=set(), known_content_hashes=set())
    assert plan == SyncPlan()
    assert plan.to_create == ()
    assert plan.duplicate_content == ()
    assert plan.already_known == ()
    assert plan.is_empty is True
    assert plan.total_count == 0


def test_sync_plan_counts_and_is_empty_property():
    docs = [_doc("a", chash="h1"), _doc("b"), _doc("c", chash="h1")]
    plan = compute_sync_plan(docs, known_external_ids=set(), known_content_hashes=set())
    # a created, b created (empty hash never dup), c duplicate of a.
    assert plan.created_count == 2
    assert plan.duplicate_count == 1
    assert plan.known_count == 0
    assert plan.total_count == 3
    assert plan.is_empty is False


def test_sync_plan_does_not_mutate_caller_sets():
    known_ids = {"a"}
    known_hashes = {"h-existing"}
    docs = [_doc("b", chash="h-new")]
    compute_sync_plan(docs, known_external_ids=known_ids, known_content_hashes=known_hashes)
    # Inputs are untouched.
    assert known_ids == {"a"}
    assert known_hashes == {"h-existing"}


def test_sync_plan_is_idempotent_on_second_run():
    docs = [
        _doc("a", chash="h1"),
        _doc("b", chash="h2"),
        _doc("c"),  # no hash
    ]
    first = compute_sync_plan(
        docs,
        known_external_ids=set(),
        known_content_hashes=set(),
    )
    assert first.created_count == 3

    # Record what got created, then feed the SAME listing again.
    known_ids = {d.external_id for d in first.to_create}
    known_hashes = {d.content_hash for d in first.to_create if d.content_hash}
    second = compute_sync_plan(
        docs,
        known_external_ids=known_ids,
        known_content_hashes=known_hashes,
    )
    assert second.to_create == ()
    assert second.is_empty is True
    assert second.already_known == (docs[0], docs[1], docs[2])
    assert second.duplicate_content == ()


def test_sync_plan_accepts_generator_input():
    # ``incoming`` is consumed once as an iterable; a generator must work.
    docs = [_doc("a", chash="h1"), _doc("b", chash="h2")]
    plan = compute_sync_plan(
        (d for d in docs),
        known_external_ids=set(),
        known_content_hashes=set(),
    )
    assert plan.to_create == (docs[0], docs[1])


def test_sync_plan_end_to_end_through_adapter():
    # Full path: raw entries -> adapter -> normalize -> sync plan.
    entries = [
        {"id": "stored", "name": "old.pdf", "etag": "h-old"},
        {"id": "fresh", "name": "new.pdf", "etag": "h-new"},
        {"id": "copy", "name": "new-copy.pdf", "etag": "h-new"},  # same bytes as fresh
    ]
    adapter = InMemoryAdapter(entries, source="object-store")
    plan = compute_sync_plan(
        adapter.list_documents(),
        known_external_ids={"stored"},
        known_content_hashes={"h-old"},
    )
    created_ids = [d.external_id for d in plan.to_create]
    dup_ids = [d.external_id for d in plan.duplicate_content]
    known_ids = [d.external_id for d in plan.already_known]
    assert created_ids == ["fresh"]
    assert dup_ids == ["copy"]
    assert known_ids == ["stored"]


# ---------------------------------------------------------------------------
# is_within_base (watched-folder root containment)
# ---------------------------------------------------------------------------

# A base dir spelled with a Windows drive so the cases are valid absolute paths
# on the local (Windows) runner; the comparison itself is OS-agnostic.
_BASE = Path("C:/srv/connectors_watch")


def test_within_base_equal_path_is_inside():
    assert is_within_base(_BASE, Path("C:/srv/connectors_watch")) is True


def test_within_base_direct_child_is_inside():
    assert is_within_base(_BASE, Path("C:/srv/connectors_watch/site-drop")) is True


def test_within_base_deep_descendant_is_inside():
    assert is_within_base(_BASE, Path("C:/srv/connectors_watch/a/b/c")) is True


def test_within_base_unrelated_root_is_outside():
    # The classic abuse: pointing a source at a system directory.
    assert is_within_base(_BASE, Path("C:/Windows")) is False


def test_within_base_parent_is_outside():
    assert is_within_base(_BASE, Path("C:/srv")) is False


def test_within_base_sibling_sharing_a_name_prefix_is_outside():
    # A naive string ``startswith`` would wrongly accept this; ``parents``
    # membership does not, because it compares whole path components.
    assert is_within_base(_BASE, Path("C:/srv/connectors_watch_evil")) is False
    assert is_within_base(_BASE, Path("C:/srv/connectors_watch_evil/x")) is False


def test_within_base_does_no_io():
    # Neither path needs to exist; the function is a pure comparison.
    missing_base = Path("C:/nope/does-not-exist")
    assert is_within_base(missing_base, Path("C:/nope/does-not-exist/child")) is True
    assert is_within_base(missing_base, Path("C:/elsewhere")) is False
