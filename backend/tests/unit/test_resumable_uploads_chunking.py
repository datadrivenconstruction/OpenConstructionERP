# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - resumable upload chunk math and integrity checks.

``resumable_uploads`` shipped with no tests at all, and this is the half of it
that decides whether a reassembled file is the file the client sent. The
service layer wires these helpers to the ORM and the filesystem; the helpers
themselves are stateless, so everything here runs without a session or storage.

The load-bearing property is the one at the bottom of the first class: the
per-index sizes must sum to exactly ``total_size``. Every individual bound could
be right while the partition still loses or invents bytes, and an upload that
assembles to the wrong length is the failure this module exists to prevent.

Pure-Python, no database.
"""

from __future__ import annotations

import hashlib

import pytest

from app.modules.resumable_uploads.chunking import (
    ChunkValidationError,
    IntegrityCheck,
    add_chunk_index,
    compute_total_chunks,
    expected_chunk_size,
    is_complete,
    missing_chunks,
    normalize_received,
    validate_chunk,
    verify_assembled,
)

#: (total_size, chunk_size) pairs: even division, one trailing byte, a full
#: trailing chunk, a file smaller than one chunk, and a single-byte file.
SIZE_CASES = [
    (1000, 100),
    (1001, 100),
    (999, 100),
    (50, 100),
    (1, 100),
]


class TestChunkPartition:
    def test_even_division(self) -> None:
        assert compute_total_chunks(1000, 100) == 10

    def test_remainder_needs_one_more_chunk(self) -> None:
        assert compute_total_chunks(1001, 100) == 11

    def test_file_smaller_than_one_chunk_is_still_one_chunk(self) -> None:
        assert compute_total_chunks(50, 100) == 1

    @pytest.mark.parametrize(("total_size", "chunk_size"), [(0, 100), (-1, 100), (100, 0), (100, -1)])
    def test_non_positive_arguments_are_rejected(self, total_size: int, chunk_size: int) -> None:
        with pytest.raises(ChunkValidationError):
            compute_total_chunks(total_size, chunk_size)

    def test_every_chunk_but_the_last_is_full(self) -> None:
        total_chunks = compute_total_chunks(1001, 100)
        for index in range(total_chunks - 1):
            assert expected_chunk_size(index, total_size=1001, chunk_size=100, total_chunks=total_chunks) == 100

    def test_last_chunk_carries_the_remainder(self) -> None:
        assert expected_chunk_size(10, total_size=1001, chunk_size=100, total_chunks=11) == 1

    def test_last_chunk_is_full_when_the_file_divides_evenly(self) -> None:
        """The remainder is ``chunk_size``, not zero -- an off-by-one here would
        demand an empty final chunk that the client never sends."""
        assert expected_chunk_size(9, total_size=1000, chunk_size=100, total_chunks=10) == 100

    @pytest.mark.parametrize("index", [-1, 10, 999])
    def test_index_outside_the_range_is_rejected(self, index: int) -> None:
        with pytest.raises(ChunkValidationError):
            expected_chunk_size(index, total_size=1000, chunk_size=100, total_chunks=10)

    @pytest.mark.parametrize(("total_size", "chunk_size"), SIZE_CASES)
    def test_the_partition_covers_the_file_exactly(self, total_size: int, chunk_size: int) -> None:
        """Sizes must sum to ``total_size``: no lost and no invented bytes."""
        total_chunks = compute_total_chunks(total_size, chunk_size)
        sizes = [
            expected_chunk_size(i, total_size=total_size, chunk_size=chunk_size, total_chunks=total_chunks)
            for i in range(total_chunks)
        ]
        assert sum(sizes) == total_size
        assert all(size > 0 for size in sizes), "an empty chunk can never be uploaded"
        assert all(size <= chunk_size for size in sizes)


class TestValidateChunk:
    def test_a_correct_chunk_passes(self) -> None:
        validate_chunk(0, 100, total_size=1001, chunk_size=100, total_chunks=11)

    def test_a_correct_short_final_chunk_passes(self) -> None:
        validate_chunk(10, 1, total_size=1001, chunk_size=100, total_chunks=11)

    def test_an_empty_body_is_rejected(self) -> None:
        with pytest.raises(ChunkValidationError, match="empty"):
            validate_chunk(0, 0, total_size=1001, chunk_size=100, total_chunks=11)

    def test_a_short_body_on_a_full_chunk_is_rejected(self) -> None:
        """Truncated bodies are what silently corrupt an assembled file."""
        with pytest.raises(ChunkValidationError, match="expected 100"):
            validate_chunk(0, 99, total_size=1001, chunk_size=100, total_chunks=11)

    def test_an_oversized_body_is_rejected(self) -> None:
        with pytest.raises(ChunkValidationError):
            validate_chunk(0, 101, total_size=1001, chunk_size=100, total_chunks=11)

    def test_a_full_body_on_the_short_final_chunk_is_rejected(self) -> None:
        with pytest.raises(ChunkValidationError):
            validate_chunk(10, 100, total_size=1001, chunk_size=100, total_chunks=11)

    @pytest.mark.parametrize("index", [-1, 11])
    def test_index_outside_the_range_is_rejected(self, index: int) -> None:
        with pytest.raises(ChunkValidationError, match="out of range"):
            validate_chunk(index, 100, total_size=1001, chunk_size=100, total_chunks=11)


class TestReceivedSet:
    def test_none_and_empty_read_as_nothing_received(self) -> None:
        assert normalize_received(None) == set()
        assert normalize_received([]) == set()

    def test_numeric_strings_are_coerced(self) -> None:
        """The column is JSON, so a round-trip can hand back strings."""
        assert normalize_received(["0", "1", 2]) == {0, 1, 2}

    def test_junk_entries_are_dropped_rather_than_raising(self) -> None:
        """A single corrupt entry must not make the whole session unresumable."""
        assert normalize_received([0, None, "x", {}, 3]) == {0, 3}

    def test_missing_chunks_are_sorted_and_complete(self) -> None:
        assert missing_chunks([0, 2], 5) == [1, 3, 4]

    def test_nothing_received_means_everything_missing(self) -> None:
        assert missing_chunks(None, 3) == [0, 1, 2]

    def test_is_complete_only_when_every_index_is_present(self) -> None:
        assert is_complete([0, 1, 2], 3) is True
        assert is_complete([0, 2], 3) is False

    def test_extra_indices_do_not_fake_completeness(self) -> None:
        """A stray out-of-range index must not stand in for a missing one."""
        assert is_complete([0, 1, 7], 3) is False

    def test_adding_a_new_index_is_not_a_duplicate(self) -> None:
        received, duplicate = add_chunk_index([0, 1], 2)
        assert received == [0, 1, 2]
        assert duplicate is False

    def test_re_adding_reports_a_duplicate_and_changes_nothing(self) -> None:
        """A retried chunk upload is a replay, not a second chunk."""
        received, duplicate = add_chunk_index([0, 1], 1)
        assert received == [0, 1]
        assert duplicate is True

    def test_the_result_is_sorted_regardless_of_arrival_order(self) -> None:
        received, _ = add_chunk_index([5, 1, 3], 0)
        assert received == [0, 1, 3, 5]


class TestVerifyAssembled:
    def test_matching_size_without_a_client_hash_is_ok(self) -> None:
        result = verify_assembled(
            assembled_size=1000,
            expected_size=1000,
            computed_sha256=None,
            expected_sha256=None,
        )
        assert result == IntegrityCheck(ok=True, reason=None)

    def test_a_size_mismatch_fails_and_says_both_numbers(self) -> None:
        result = verify_assembled(
            assembled_size=999,
            expected_size=1000,
            computed_sha256=None,
            expected_sha256=None,
        )
        assert result.ok is False
        assert "999" in (result.reason or "")
        assert "1000" in (result.reason or "")

    def test_a_matching_hash_is_ok(self) -> None:
        digest = hashlib.sha256(b"contract drawing").hexdigest()
        result = verify_assembled(
            assembled_size=10,
            expected_size=10,
            computed_sha256=digest,
            expected_sha256=digest,
        )
        assert result.ok is True

    def test_hash_comparison_ignores_case(self) -> None:
        """Clients differ on hex case; that must not read as corruption."""
        digest = hashlib.sha256(b"contract drawing").hexdigest()
        result = verify_assembled(
            assembled_size=10,
            expected_size=10,
            computed_sha256=digest.upper(),
            expected_sha256=digest.lower(),
        )
        assert result.ok is True

    def test_a_hash_mismatch_fails(self) -> None:
        result = verify_assembled(
            assembled_size=10,
            expected_size=10,
            computed_sha256=hashlib.sha256(b"a").hexdigest(),
            expected_sha256=hashlib.sha256(b"b").hexdigest(),
        )
        assert result.ok is False
        assert result.reason == "sha256 mismatch"

    def test_a_promised_hash_that_was_never_computed_fails(self) -> None:
        """Silently skipping the check would turn a promise into a no-op."""
        result = verify_assembled(
            assembled_size=10,
            expected_size=10,
            computed_sha256=None,
            expected_sha256=hashlib.sha256(b"a").hexdigest(),
        )
        assert result.ok is False
        assert result.reason == "missing computed checksum"

    def test_size_is_checked_before_the_hash(self) -> None:
        """Both are wrong; the size is the more actionable message."""
        result = verify_assembled(
            assembled_size=1,
            expected_size=10,
            computed_sha256=hashlib.sha256(b"a").hexdigest(),
            expected_sha256=hashlib.sha256(b"b").hexdigest(),
        )
        assert result.ok is False
        assert "size" in (result.reason or "")


class TestValidatorsSurface:
    """``validators.py`` is a re-export shim, and the module contract says so.

    Platform principle #4 means every module has a discoverable validation
    entry point. If a helper is renamed in ``chunking`` and the shim is not
    updated, callers importing from ``validators`` break at runtime; this fails
    at test time instead.
    """

    def test_every_exported_name_is_the_chunking_implementation(self) -> None:
        from app.modules.resumable_uploads import chunking, validators

        assert validators.__all__, "the validation entry point exports nothing"
        for name in validators.__all__:
            assert hasattr(validators, name), name
            assert getattr(validators, name) is getattr(chunking, name), name
