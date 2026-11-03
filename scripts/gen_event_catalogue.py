"""Regenerate the webhook event catalogue from the names modules publish on the bus.

Scans backend/app for literal event names passed to the bus publishers and
writes backend/app/modules/integrations/event_catalogue.json. Run after adding
a new event; ``--check`` exits 1 when the file is stale.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "backend" / "app"
OUT = ROOT / "modules" / "integrations" / "event_catalogue.json"

_PUBLISHERS = r"(?:publish|publish_after_commit|publish_detached|_safe_publish|_publish_event|_emit)"
_NAME = r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+"
PATTERN = re.compile(_PUBLISHERS + r"\(\s*(?:[A-Za-z_.]+,\s*)?f?[\"'](" + _NAME + r")[\"']")


def collect() -> list[str]:
    names: set[str] = set()
    for path in ROOT.rglob("*.py"):
        names.update(PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return sorted(names)


def main() -> int:
    text = json.dumps(collect(), indent=0) + "\n"
    if "--check" in sys.argv:
        return 0 if OUT.exists() and OUT.read_text(encoding="utf-8") == text else 1
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
