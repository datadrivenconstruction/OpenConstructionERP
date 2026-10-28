# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-unit tests for the resumable-upload chunk math.

No DB, no storage, no request layer - exercises
:mod:`app.modules.resumable_uploads.chunking` directly. Covers the
assembly / integrity math and the idempotency + missing-chunk logic the
resumable upload depends on.
"""

from __future__ import annotations

import pytest

from app.modules.resumable_uploads.chunking import (
    ChunkValidationError,
    add_chunk_index,
    compute_total_chunks,
    expected_chunk_size,
    is_complete,
    missing_chunks,
    normalize_received,
    validate_chunk,
    verify_assembled,
)

# ── compute_total_chunks ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("total_size", "chunk_size", "expected"),
    [
        (100, 30, 4),  # 30+30+30+10
        (90, 30, 3),  # divides evenly
        (1, 30, 1),  # tiny file, one chunk
        (8 * 1024 * 1024, 8 * 1024 * 1024, 1),
        (8 * 1024 * 1024 + 1, 8 * 1024 * 1024, 2),
    ],
)
def test_compute_total_chunks(total_size: int, chunk_size: int, expected: int) -> None:
    assert compute_total_chunks(total_size, chunk_size) == expected


def test_compute_total_chunks_rejects_nonpositive() -> None:
    with pytest.raises(ChunkValidationError):
        compute_total_chunks(0, 30)
    with pytest.raises(ChunkValidationError):
        compute_total_chunks(100, 0)


# ── expected_chunk_size ──────────────────────────────────────────────────────


def test_expected_chunk_size_uneven_tail() -> None:
    # 100 bytes in 30-byte chunks: chunks 0..2 are 30, the tail (chunk 3) is 10.
    assert expected_chunk_size(0, total_size=100, chunk_size=30, total_chunks=4) == 30
    assert expected_chunk_size(2, total_size=100, chunk_size=30, total_chunks=4) == 30
    assert expected_chunk_size(3, total_size=100, chunk_size=30, total_chunks=4) == 10


def test_expected_chunk_size_even_split_tail_full() -> None:
    # 90 bytes in 30-byte chunks: every chunk including the last is 30.
    assert expected_chunk_size(2, total_size=90, chunk_size=30, total_chunks=3) == 30


def test_expected_chunk_size_out_of_range_rejected() -> None:
    with pytest.raises(ChunkValidationError):
        expected_chunk_size(4, total_size=100, chunk_size=30, total_chunks=4)
    with pytest.raises(ChunkValidationError):
        expected_chunk_size(-1, total_size=100, chunk_size=30, total_chunks=4)


# ── validate_chunk ───────────────────────────────────────────────────────────


def test_validate_chunk_accepts_correct_size() -> None:
    # No raise == accepted.
    validate_chunk(0, 30, total_size=100, chunk_size=30, total_chunks=4)
    validate_chunk(3, 10, total_size=100, chunk_size=30, total_chunks=4)


def test_validate_chunk_rejects_out_of_range_index() -> None:
    with pytest.raises(ChunkValidationError):
        validate_chunk(4, 10, total_size=100, chunk_size=30, total_chunks=4)
    with pytest.raises(ChunkValidationError):
        validate_chunk(-1, 30, total_size=100, chunk_size=30, total_chunks=4)


def test_validate_chunk_rejects_wrong_size() -> None:
    # A middle chunk that is not exactly chunk_size is rejected.
    with pytest.raises(ChunkValidationError):
        validate_chunk(0, 29, total_size=100, chunk_size=30, total_chunks=4)
    # The tail chunk must be exactly the remainder.
    with pytest.raises(ChunkValidationError):
        validate_chunk(3, 30, total_size=100, chunk_size=30, total_chunks=4)


def test_validate_chunk_rejects_empty_body() -> None:
    with pytest.raises(ChunkValidationError):
        validate_chunk(0, 0, total_size=100, chunk_size=30, total_chunks=4)


# ── missing_chunks / is_complete / normalize ────────────────────────────────


def test_missing_chunks_reports_exact_gaps() -> None:
    assert missing_chunks([0, 2], 4) == [1, 3]
    assert missing_chunks([], 3) == [0, 1, 2]
    assert missing_chunks([0, 1, 2], 3) == []


def test_missing_chunks_ignores_duplicates_and_order() -> None:
    assert missing_chunks([2, 0, 2, 0], 4) == [1, 3]


def test_is_complete() -> None:
    assert is_complete([0, 1, 2, 3], 4) is True
    assert is_complete([0, 1, 3], 4) is False
    assert is_complete([], 1) is False


def test_normalize_received_tolerates_garbage() -> None:
    assert normalize_received(None) == set()
    assert normalize_received([0, "1", 2, None, "x"]) == {0, 1, 2}


# ── add_chunk_index idempotency ──────────────────────────────────────────────


def test_add_chunk_index_new_is_not_duplicate() -> None:
    new_list, duplicate = add_chunk_index([0, 1], 2)
    assert new_list == [0, 1, 2]
    assert duplicate is False


def test_add_chunk_index_existing_is_duplicate_noop() -> None:
    new_list, duplicate = add_chunk_index([0, 1, 2], 1)
    assert new_list == [0, 1, 2]
    assert duplicate is True


# ── verify_assembled integrity ───────────────────────────────────────────────


def test_verify_assembled_size_match_no_hash() -> None:
    check = verify_assembled(
        assembled_size=100,
        expected_size=100,
        computed_sha256=None,
        expected_sha256=None,
    )
    assert check.ok is True


def test_verify_assembled_wrong_size_rejected() -> None:
    check = verify_assembled(
        assembled_size=99,
        expected_size=100,
        computed_sha256="abc",
        expected_sha256=None,
    )
    assert check.ok is False
    assert "size" in (check.reason or "")


def test_verify_assembled_sha_match_case_insensitive() -> None:
    check = verify_assembled(
        assembled_size=100,
        expected_size=100,
        computed_sha256="DEADBEEF",
        expected_sha256="deadbeef",
    )
    assert check.ok is True


def test_verify_assembled_sha_mismatch_rejected() -> None:
    check = verify_assembled(
        assembled_size=100,
        expected_size=100,
        computed_sha256="aaaa",
        expected_sha256="bbbb",
    )
    assert check.ok is False
    assert check.reason == "sha256 mismatch"
