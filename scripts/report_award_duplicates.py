"""List purchase orders and contracts drafted more than once for one award.

Read-only: prints JSON, deletes nothing. Run from ``backend/`` with the install's
``DATABASE_URL`` set: ``python ../scripts/report_award_duplicates.py``.
Exit code 1 when duplicates exist.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


async def _main() -> int:
    from app.core.event_effects import find_award_duplicates
    from app.database import async_session_factory

    async with async_session_factory() as session:
        found = await find_award_duplicates(session)
        await session.rollback()
    print(json.dumps(found, indent=2))
    return 1 if any(found.values()) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
