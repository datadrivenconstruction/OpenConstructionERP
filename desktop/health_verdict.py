# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Judge an /api/health body the way the desktop launcher does.

Mirror of ``blocking_fault`` in desktop/src-tauri/src/main.rs, used by the
release workflow's serve check so a build the launcher would refuse cannot
pass the gate. tests/test_health_verdict.py keeps the two in step.

Usage: ``python desktop/health_verdict.py '<body>'``; exit 0 when the launcher
would open the app, exit 1 with the reason on stdout when it would not.
"""

from __future__ import annotations

import json
import sys

LAUNCHER_FIELDS = ("status", "database", "frontend_dist_present")


def verdict(body: str) -> str | None:
    """Reason the launcher would refuse this body, or ``None`` when it would open the app."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("status") != "degraded":
        return None
    database = data.get("database")
    if isinstance(database, str) and database != "ok":
        return "the local database is not answering"
    if data.get("frontend_dist_present") is False:
        return "this installation is missing the application files it serves"
    return None


def main(argv: list[str]) -> int:
    reason = verdict(argv[1] if len(argv) > 1 else "")
    if reason:
        print(reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
