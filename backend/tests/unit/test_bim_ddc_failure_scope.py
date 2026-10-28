# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - a DDC conversion failure belongs to the conversion that hit it.

``process_ifc_file`` runs on a shared thread pool (``asyncio.to_thread`` in
the bim_hub router), so two users' uploads convert at the same time. The
failure context the router folds into ``model.error_message`` therefore has
to be scoped to one conversion. A record shared by the whole process reports
one upload's stderr tail - which carries the other user's file path and file
name - on someone else's model.

The tests below interleave two conversions on purpose: both record a failure
before either reads one back. A process-wide record fails them.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.bim_hub.ifc_processor import ddc_failure_scope


def _fail(tag: str, exit_code: int, barrier: threading.Barrier | None = None) -> None:
    """Record one converter failure the way ``_try_cad2data`` does.

    Runs in the worker thread. When a barrier is passed, the write is held
    open until every worker has recorded its own failure, so a shared record
    is guaranteed to have been overwritten by the time anyone reads.
    """
    ifc_processor._record_ddc_failure(
        "ifc",
        "nonzero_exit",
        exit_code=exit_code,
        stderr=f"/tmp/upload-{tag}/original.ifc: converter died".encode(),
    )
    if barrier is not None:
        barrier.wait(timeout=30)


async def _one_conversion(tag: str, exit_code: int, barrier: threading.Barrier) -> dict:
    """One upload's conversion, shaped like the router's background task."""
    with ddc_failure_scope() as record:
        await asyncio.to_thread(_fail, tag, exit_code, barrier)
        return dict(record)


@pytest.mark.asyncio
async def test_overlapping_conversions_do_not_read_each_others_failure() -> None:
    barrier = threading.Barrier(2)

    alpha, bravo = await asyncio.gather(
        _one_conversion("alpha", 1, barrier),
        _one_conversion("bravo", 2, barrier),
    )

    assert alpha["stderr"] == "/tmp/upload-alpha/original.ifc: converter died"
    assert alpha["exit_code"] == 1
    assert bravo["stderr"] == "/tmp/upload-bravo/original.ifc: converter died"
    assert bravo["exit_code"] == 2


@pytest.mark.asyncio
async def test_a_worker_thread_writes_into_the_record_bound_by_its_caller() -> None:
    """The bind has to survive the ``asyncio.to_thread`` hop, or the router
    reads nothing at all and every failure message loses its diagnostics."""
    with ddc_failure_scope() as record:
        await asyncio.to_thread(_fail, "solo", 7)

        assert ifc_processor.last_ddc_failure() == record

    assert record["stderr"] == "/tmp/upload-solo/original.ifc: converter died"
    assert record["exit_code"] == 7


@pytest.mark.asyncio
async def test_a_conversion_that_did_not_fail_reports_no_failure() -> None:
    """A later conversion must not inherit an earlier one's record."""
    # An earlier upload failed.
    with ddc_failure_scope() as earlier:
        await asyncio.to_thread(_fail, "earlier", 3)

    assert earlier["exit_code"] == 3

    # This one converted cleanly, so it has nothing to report.
    with ddc_failure_scope() as current:
        await asyncio.to_thread(lambda: None)

        assert ifc_processor.last_ddc_failure() == {}

    assert current == {}


def test_reading_outside_a_scope_yields_nothing() -> None:
    """There is deliberately no process-wide record to fall back on."""
    _fail("unscoped", 9)

    assert ifc_processor.last_ddc_failure() == {}
