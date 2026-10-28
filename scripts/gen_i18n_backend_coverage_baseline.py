#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regenerate scripts/i18n_backend_coverage_baseline.json from backend/locales.

The baseline records, per locale, how many of en.json's keys that locale is
still missing, plus a digest of which keys those are. It is declared debt and
may only shrink: backend/tests/unit/test_backend_locale_catalogue.py fails when
a locale is shorter than its entry allows, and fails on an unchanged count with
a changed digest, which is a key dropped while another was filled.

Run it after filling a locale, or after adding keys to en.json, from the repo
root. It rewrites the whole file, so read the diff before committing: a number
going UP is the guard telling you something, not a baseline to accept.

    python scripts/gen_i18n_backend_coverage_baseline.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "backend" / "locales"
BASELINE_PATH = REPO_ROOT / "scripts" / "i18n_backend_coverage_baseline.json"


def flatten(data: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dicts the way app.core.i18n._flatten_dict does."""
    items: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.update(flatten(value, path))
        else:
            items[path] = str(value)
    return items


def load(code: str) -> dict[str, str]:
    return flatten(json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8")))


def main() -> int:
    codes = sorted(p.stem for p in LOCALES_DIR.glob("*.json"))
    if "en" not in codes:
        print(f"no en.json under {LOCALES_DIR}", file=sys.stderr)
        return 1

    english = load("en")
    locales: dict[str, dict[str, object]] = {}
    for code in codes:
        if code == "en":
            continue
        missing = sorted(key for key in english if key not in load(code))
        locales[code] = {
            "missing": len(missing),
            "digest": hashlib.sha256("\n".join(missing).encode("utf-8")).hexdigest()[:16],
        }

    payload = {"english_keys": len(english), "locales": locales}
    BASELINE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    total = sum(int(entry["missing"]) for entry in locales.values())
    print(f"{BASELINE_PATH.relative_to(REPO_ROOT)}: {len(locales)} locales, {total} keys of debt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
