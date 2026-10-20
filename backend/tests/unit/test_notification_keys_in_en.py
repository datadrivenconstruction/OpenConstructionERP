"""Every notification title/body key the backend can emit has an English text.

The inbox and the bell translate ``title_key`` on the client. A key missing
from ``en.ts`` shows up as raw ``notifications.x.y.title`` text.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULES = ROOT / "backend" / "app" / "modules"
EN = ROOT / "frontend" / "src" / "app" / "locales" / "en.ts"

_LITERAL = re.compile(r"""["'](notifications\.[a-z0-9_]+\.[a-z0-9_]+\.(?:title|body))["']""")
_DYNAMIC = re.compile(r'f"notifications\.([a-z0-9_]+)\.\{kind\}\.(?:title|body)"')
_KIND_CALL = re.compile(r'_notify\(\s*[^,\n]+,\s*"([a-z_]+)"')


def _emitted() -> set[str]:
    keys: set[str] = set()
    for path in MODULES.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        keys.update(_LITERAL.findall(text))
        for ns in set(_DYNAMIC.findall(text)):
            for kind in _KIND_CALL.findall(text):
                keys.update((f"notifications.{ns}.{kind}.title", f"notifications.{ns}.{kind}.body"))
    return keys


def test_every_emitted_notification_key_exists_in_en() -> None:
    en = EN.read_text(encoding="utf-8")
    emitted = _emitted()
    assert len(emitted) > 100  # guards the scan itself
    missing = sorted(k for k in emitted if f'"{k}"' not in en)
    assert not missing, f"notification keys missing from en.ts: {missing}"
