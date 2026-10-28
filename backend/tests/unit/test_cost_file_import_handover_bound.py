"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A cost-file import must hand rows to the service in bounded slices.

The upload cap on this endpoint is 100 MB, which is well over a million rows of
CSV. Turning every one of them into a schema object before the first insert
meant the file existed several times over at the peak - the parsed rows, the
schema objects built from them, and the ORM instances the service built from
those. On a server with 3 GB of RAM the kernel kills the process there, and
because that is a SIGKILL the operator sees a server that stopped rather than an
import that failed.

The bound is checked by watching the sizes the service is called with rather
than by measuring memory. The slice size is what this code decides; resident
memory is decided by the allocator, the CSV reader and the garbage collector as
well, and a test that measured it would fail for reasons that had nothing to do
with this loop.

Two of the tests are the control. One runs the same import with the bound raised
out of reach, which is what removing the hand-over would look like from inside
the loop, and asserts the single unbounded batch that would then appear. The
other puts a duplicate code across a slice boundary: slicing moves that row from
the service's in-memory duplicate set onto its database lookup, so the reported
counts have to come out the same either way or the bound changed behaviour
rather than only peak memory.

No database is involved: the service is replaced by a recorder that models the
one contract the router depends on - a code already created is not created
again, whichever call first carried it.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from app.modules.costs import router

HANDOVER = 7
ITEMS = 25

# Rows 2 and 10 land in different slices at a bound of 7 (0-6, 7-13), which is
# the case that cannot be answered by the in-memory set inside one call.
DUPLICATE_SOURCE = 2
DUPLICATE_TARGET = 10


def _csv(codes: list[str]) -> bytes:
    """A minimal cost catalogue: one priced line per code."""
    lines = ["code,description,unit,rate,currency"]
    lines += [f"{code},Work item {index},m3,{100 + index},EUR" for index, code in enumerate(codes)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _distinct_codes() -> list[str]:
    return [f"C{index:04d}" for index in range(ITEMS)]


def _codes_with_a_duplicate_across_a_slice() -> list[str]:
    codes = _distinct_codes()
    codes[DUPLICATE_TARGET] = codes[DUPLICATE_SOURCE]
    return codes


class _Upload:
    """The two members of ``UploadFile`` this endpoint touches."""

    def __init__(self, content: bytes) -> None:
        self.filename = "catalogue.csv"
        self._content = content

    async def read(self) -> bytes:
        return self._content


class _RecordingService:
    """Stands in for ``CostItemService``, modelling its duplicate contract.

    The real ``bulk_import`` flushes each slice before the next one looks a code
    up, so a code already created is skipped whether its first copy arrived in
    this call or an earlier one. That is the property slicing leans on, so the
    recorder implements it rather than assuming it away.
    """

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []
        self.created_codes: list[str] = []
        self._seen: set[str] = set()

    async def bulk_import(self, items: list[Any]) -> list[Any]:
        # The router clears the list it passed, so the length has to be taken
        # now. Keeping the list itself would record every batch as empty and
        # the assertions below would all pass against a broken import.
        self.batch_sizes.append(len(items))
        created = []
        for item in items:
            if item.code in self._seen:
                continue
            self._seen.add(item.code)
            self.created_codes.append(item.code)
            created.append(item)
        return created


async def _import_with_bound(
    bound: int, codes: list[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[_RecordingService, dict[str, Any]]:
    """Run an import against a recording service and return it with the response."""
    monkeypatch.setattr(router, "_IMPORT_HANDOVER_ROWS", bound)
    service = _RecordingService()
    response = await router.import_cost_file(
        user={"sub": None, "role": "user"},
        file=_Upload(_csv(codes)),  # type: ignore[arg-type]
        column_map=None,
        catalog_id=None,
        catalog_name=None,
        catalog_currency=None,
        service=service,  # type: ignore[arg-type]
        catalog_service=None,  # type: ignore[arg-type]
    )
    return service, response


@pytest.fixture
async def bounded(monkeypatch: pytest.MonkeyPatch) -> tuple[_RecordingService, dict[str, Any]]:
    return await _import_with_bound(HANDOVER, _distinct_codes(), monkeypatch)


async def test_no_batch_exceeds_the_handover_bound(bounded: tuple[_RecordingService, dict[str, Any]]) -> None:
    service, _ = bounded
    assert service.batch_sizes, "the import handed nothing over, so the bound was never exercised"
    assert max(service.batch_sizes) <= HANDOVER, (
        f"a batch of {max(service.batch_sizes)} rows passed a bound of {HANDOVER}"
    )


async def test_the_import_hands_over_more_than_once(bounded: tuple[_RecordingService, dict[str, Any]]) -> None:
    # The assertion above is also satisfied by an import that dropped every row
    # but one, and by one that never entered the loop at all. This is the half
    # that says the slicing happened.
    service, _ = bounded
    assert len(service.batch_sizes) == math.ceil(ITEMS / HANDOVER)


async def test_every_row_still_arrives(bounded: tuple[_RecordingService, dict[str, Any]]) -> None:
    # Bounding the batches is only correct if the bound loses nothing. An
    # off-by-one in the hand-over is the failure this catches, and it is
    # invisible to the two assertions above.
    service, response = bounded
    assert sum(service.batch_sizes) == ITEMS
    assert service.created_codes == _distinct_codes()
    assert response["imported"] == ITEMS
    assert response["skipped"] == 0
    assert response["total_rows"] == ITEMS


async def test_an_unreachable_bound_produces_the_one_batch_the_others_forbid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = await _import_with_bound(10**9, _distinct_codes(), monkeypatch)

    assert service.batch_sizes == [ITEMS]
    assert max(service.batch_sizes) > HANDOVER
    assert len(service.batch_sizes) != math.ceil(ITEMS / HANDOVER)


async def test_a_duplicate_across_a_slice_boundary_is_counted_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # The control the bound itself cannot give. Inside one call the service
    # catches a repeated code with an in-memory set; split across two calls the
    # same row has to be caught by the lookup against what the earlier slice
    # already wrote. If the split changed which of those fires, the counts the
    # endpoint reports move - so they are compared against the unsliced run.
    codes = _codes_with_a_duplicate_across_a_slice()
    sliced_service, sliced = await _import_with_bound(HANDOVER, codes, monkeypatch)
    whole_service, whole = await _import_with_bound(10**9, codes, monkeypatch)

    assert len(sliced_service.batch_sizes) > 1, "the duplicate did not straddle a boundary"
    assert sliced["imported"] == whole["imported"] == ITEMS - 1
    assert sliced["skipped"] == whole["skipped"] == 1
    assert sliced_service.created_codes == whole_service.created_codes
