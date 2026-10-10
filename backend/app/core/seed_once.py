# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run a boot-time baseline seed once per application version.

The baseline seeds (countries and taxes, starter cost items, regional indices,
house-type presets) are idempotent, but each still queried its tables on every
boot to find out it had nothing to do. A completed seed now leaves a marker in
``oe_process_settings`` (the registry's ``flag:`` rows, readable through
``process_registry.get_flag``) keyed by seed name and app version, and a later boot of
the same version skips it. An upgrade changes the key, so a release that ships
new baseline rows runs its seeds again. A failed seed stamps nothing and runs
again on the next boot, as before.

Under ``OE_TEST_FAST_STARTUP`` the markers are ignored: the suite rebuilds and
truncates tables between modules and relies on every boot re-seeding.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.core.processes.semantic import fast_startup
from app.core.processes.store import DbProcessStore, ProcessStore

logger = logging.getLogger(__name__)

_PREFIX = "flag:seeds/"


def marker_key(name: str, version: str) -> str:
    """Key of the completion marker for ``name`` at ``version``."""
    return f"{_PREFIX}{name}@{version}"


class SeedOnce:
    """Runs named seeds once per version against one store.

    Args:
        version: Running application version.
        store: Where markers live; the database by default.
    """

    def __init__(self, version: str, store: ProcessStore | None = None) -> None:
        self.version = version
        self.store: ProcessStore = store or DbProcessStore()
        self._done: dict[str, bool] | None = None

    async def run(self, name: str, seed: Callable[[], Awaitable[object]], failure: str) -> bool:
        """Run ``seed`` unless this version already completed it. Never raises.

        Args:
            name: Stable seed name, part of the marker key.
            seed: The seed; raising means it did not complete.
            failure: Logged with the traceback when the seed raises.

        Returns:
            True when the seed ran and completed now.
        """
        key = marker_key(name, self.version)
        honour_markers = not fast_startup()
        if honour_markers:
            if self._done is None:
                self._done = await self.store.load()
            if self._done.get(key):
                logger.debug("Seed %s skipped - already completed for version %s", name, self.version)
                return False
        try:
            await seed()
        except Exception:
            logger.exception(failure)
            return False
        if honour_markers:
            try:
                await self.store.save(key, True, updated_by="seed")
                self._done[key] = True  # type: ignore[index]
            except Exception:
                # No marker only means the idempotent seed runs again next boot.
                logger.debug("Could not record seed marker %s", key, exc_info=True)
        return True


#: Set while a demo project seed is in flight, cleared when it completes.
DEMO_PROJECTS_PENDING = f"{_PREFIX}demo_projects_pending"


async def demo_projects_pending(store: ProcessStore | None = None) -> bool:
    """Whether an earlier demo project seed started and never completed."""
    try:
        return bool((await (store or DbProcessStore()).load()).get(DEMO_PROJECTS_PENDING))
    except Exception:
        logger.debug("Could not read the demo seed flag", exc_info=True)
        return False


async def set_demo_projects_pending(pending: bool, store: ProcessStore | None = None) -> None:
    """Record that a demo project seed started (True) or completed (False). Never raises."""
    try:
        await (store or DbProcessStore()).save(DEMO_PROJECTS_PENDING, pending, updated_by="seed")
    except Exception:
        logger.debug("Could not record the demo seed flag", exc_info=True)
