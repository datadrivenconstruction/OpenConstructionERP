# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Persisted "is the public demo login enabled" switch (admin-controlled).

This is deliberately separate from :mod:`app.core.demo_seed`, which decides
whether the startup seeder installs the demo accounts and showcase projects.
That decision is about what gets created on boot; this flag is about whether the
password-free "Try demo" sign-in is *offered* right now. Keeping them apart lets
a site admin turn the demo login off from the Settings screen at runtime,
without a restart and without wiping the seeded demo data (which they can still
remove separately).

Persistence is a small JSON file in the data dir, exactly like
:mod:`app.core.app_branding`, so it needs no database table and no migration::

    <data-dir>/demo_login_enabled.json   ->   {"enabled": false}

The default, when no file has been written, is ``True`` - the historical
behaviour where a seeded demo account can be used to sign in. The *effective*
availability of the demo login is::

    seed_demo_enabled() AND demo_login_enabled()

i.e. there must be a demo account to sign into AND the admin must not have
switched it off. Operators who want to force the demo login off regardless of
the admin toggle can still set ``SEED_DEMO=false``, which disables it through the
seed gate.

stdlib-only so it stays cheap to import (the auth path calls it on every demo
sign-in) and reuses the same data-dir resolution as the other core singletons.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.demo_seed import resolve_data_dir

logger = logging.getLogger(__name__)

#: File name of the persisted flag, relative to the data dir.
DEMO_LOGIN_FILENAME = "demo_login_enabled.json"


def demo_login_flag_path(data_dir: Path | None = None) -> Path:
    """Return the path of the persisted demo-login flag file.

    Args:
        data_dir: Explicit data dir (tests pass a ``tmp_path``); ``None``
            resolves via :func:`app.core.demo_seed.resolve_data_dir`.
    """
    base = Path(data_dir).expanduser() if data_dir is not None else resolve_data_dir()
    return base / DEMO_LOGIN_FILENAME


def demo_login_enabled(data_dir: Path | None = None) -> bool:
    """Return whether the public demo login is currently switched on.

    Reads the persisted admin choice. Returns ``True`` only when no choice has
    ever been recorded (the historical default). This is a security control, so
    it fails closed: if the flag file exists but cannot be read or parsed, or
    holds no usable boolean, the demo login is treated as off rather than
    silently re-opening a password-free login the admin may have switched off.
    A genuinely absent file still defaults to on, gated as always by
    :func:`app.core.demo_seed.seed_demo_enabled`.

    Args:
        data_dir: Explicit data dir override (tests); ``None`` uses the active
            data dir.

    Returns:
        ``True`` if the demo login is enabled, ``False`` if the admin turned it
        off.
    """
    path = demo_login_flag_path(data_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Never configured -> historical default: the demo login is available.
        return True
    except OSError as exc:
        # The file exists but cannot be read. Fail closed: do not re-open a demo
        # login the admin may have turned off just because we hit a read error.
        logger.warning("Could not read demo-login flag at %s, treating demo login as off: %s", path, exc)
        return False
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Corrupt demo-login flag file at %s, treating demo login as off", path)
        return False
    value = data.get("enabled") if isinstance(data, dict) else None
    if isinstance(value, bool):
        return value
    # File present but no usable boolean -> fail closed rather than assume on.
    return False


def set_demo_login_enabled(enabled: bool, data_dir: Path | None = None) -> bool:
    """Persist the admin's on/off choice for the public demo login.

    Best-effort write: on I/O failure the change will not survive a restart, but
    the returned value still reflects what the admin asked for so the API
    response stays consistent within the running process.

    Args:
        enabled: The new state to persist.
        data_dir: Explicit data dir override (tests); ``None`` uses the active
            data dir.

    Returns:
        The boolean state that is now in effect.
    """
    path = demo_login_flag_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"enabled": bool(enabled)}) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist demo-login flag at %s: %s", path, exc)
    return bool(enabled)
