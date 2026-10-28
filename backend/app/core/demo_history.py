# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Marks the span in which the demo seeders write a project's recorded history.

A demo project is shown at a moment of its life: its governance story has already bound the
frame documents, and the permits and design records that belong to that moment must exist
beside them. Written through the services, those records meet the structural guards that make a
live change to a binding frame go through a change request. A seed is not a live change, it is
the history the frame was bound on, so the enrichment sets this flag around the module seeders
and only there.

Exactly two guards read it: the permits roadmap structural guard and the design frame
``assert_not_binding``. Nothing in request handling sets it, and it is always reset with its token.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

RECORDING_DEMO_HISTORY: ContextVar[bool] = ContextVar("recording_demo_history", default=False)


@contextmanager
def recording_demo_history() -> Iterator[None]:
    """Set the flag for the duration of the block and restore it, whatever happens inside."""
    token = RECORDING_DEMO_HISTORY.set(True)
    try:
        yield
    finally:
        RECORDING_DEMO_HISTORY.reset(token)
