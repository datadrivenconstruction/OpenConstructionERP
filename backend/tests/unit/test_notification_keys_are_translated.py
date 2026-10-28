"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every notification i18n key the backend can emit must exist in ``en.ts``.

A notification row stores ``title_key`` / ``body_key``, and the frontend hands
that string straight to i18next: ``features/inbox/inboxUtils.ts`` ``resolveTitle``
falls back to ``defaultValue: fallback || key``. So a key with no locale entry
renders *as the key* - the QA crawl photographed
``notifications.deadline.overdue.title`` sitting in the inbox list.

This is a static gate rather than a behavioural one for the same reason as
``test_project_budget_currency``: the defect is a *class*. Adding a notification
is a one-line change in whichever module raises it, the missing translation is
invisible until that specific event fires, and 31 keys had accumulated before
anyone looked.

Why the collection rule is what it is. Matching "strings that look like
``notifications.*``" is wrong in both directions: it sweeps up event-bus topics
(``notifications.notification.read``), permission names
(``notifications.admin.webhooks``), websocket frame types (``notifications.hello``)
and the ``_LEGACY_TITLE_ALIASES`` left-hand sides, none of which are ever
rendered - and it still misses ``clash.notification.updated``, which is a real
title key that does not start with ``notifications.``. So the rule is syntactic:
a string is a notification i18n key exactly when it is *passed as one*.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "app"
_EN_TS = _BACKEND.parent / "frontend" / "src" / "app" / "locales" / "en.ts"

# ``NotificationService.notify_users(user_ids, notification_type, title_key, *, ...)``
# - the title is the third positional parameter, so a literal may arrive there
# instead of by keyword. Missing this cost two keys on the first sweep.
_POSITIONAL_TITLE = {"notify_users": 2}
_KEYWORDS = ("title_key", "body_key")


def _emitted_keys() -> dict[str, str]:
    """Map every notification i18n key the backend can emit to where it is written."""
    keys: dict[str, str] = {}

    for path in _APP.rglob("*.py"):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        if "title_key" not in source and "body_key" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - defensive
            continue

        rel = path.relative_to(_BACKEND)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg in _KEYWORDS and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str):
                        keys.setdefault(kw.value.value, f"{rel}:{kw.value.lineno}")
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            idx = _POSITIONAL_TITLE.get(name or "")
            if idx is not None and len(node.args) > idx:
                arg = node.args[idx]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.setdefault(arg.value, f"{rel}:{arg.lineno}")

    # The rendered halves of every _TEMPLATES entry. The dict is keyed by the
    # i18n key itself, so its keys are emitted keys even where no call site in
    # app/ passes them literally.
    templates = (_APP / "modules" / "notifications" / "templates.py").read_text(encoding="utf-8")
    body = templates.split("_TEMPLATES: dict[str, str] = {", 1)[1].split("\n}", 1)[0]
    for key in re.findall(r'^\s*"([^"]+)":', body, re.M):
        keys.setdefault(key, "modules/notifications/templates.py:_TEMPLATES")

    return keys


def test_every_emitted_notification_key_has_an_english_string() -> None:
    """No notification may reach the inbox as a raw i18n key."""
    emitted = _emitted_keys()

    # Guard the guard: a rename or a moved module would otherwise make the
    # assertion below vacuously true.
    assert len(emitted) > 100, (
        f"only {len(emitted)} notification keys collected from {_APP} - the scan is broken, not the codebase"
    )
    assert "notifications.deadline.overdue.title" in emitted, (
        "the key the QA crawl photographed is no longer collected - the scan drifted"
    )

    en_keys = set(re.findall(r'^\s*"([^"]+)":', _EN_TS.read_text(encoding="utf-8"), re.M))
    missing = sorted(f"{k}  ({where})" for k, where in emitted.items() if k not in en_keys)

    assert not missing, (
        f"{len(missing)} notification key(s) have no entry in {_EN_TS.name} and will render "
        "as the raw key in the inbox:\n  " + "\n  ".join(missing)
    )
