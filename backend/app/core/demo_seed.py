# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persisted demo-seed choice (first-run "Load demo projects?" decision).

The startup seeder (``app.main._seed_demo_account``) installs demo accounts
and showcase projects unless ``SEED_DEMO`` says otherwise. The environment
variable is ephemeral, so the CLI's first-run prompt and the
``POST /api/v1/projects/demo-data/purge/`` endpoint persist the user's
choice into a small JSON file inside the data dir::

    <data-dir>/demo_seed_choice.json   ->   {"seed_demo": false}

Precedence (highest first):

1. ``SEED_DEMO`` environment variable (explicit operator override)
2. ``demo_seed_choice.json`` in the data dir (persisted first-run answer
   or a demo-data purge)
3. default: seed (the historical out-of-the-box behaviour)

This module is intentionally stdlib-only so the CLI can import it before
``_setup_env`` boots the embedded PostgreSQL cluster.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: File name of the persisted choice, relative to the data dir.
CHOICE_FILENAME = "demo_seed_choice.json"

#: Default data dir - must match ``app.cli.DEFAULT_DATA_DIR``.
DEFAULT_DATA_DIR = Path.home() / ".openestimate"


def resolve_data_dir() -> Path:
    """Return the active data dir.

    Mirrors the resolution order used by ``app.core.storage``: an
    operator-supplied ``OE_DATA_DIR`` / ``DATA_DIR`` wins, then the CLI's
    ``OE_CLI_DATA_DIR`` (set by ``_setup_env``), then the default
    ``~/.openestimate``.
    """
    for env_name in ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR"):
        raw = os.environ.get(env_name)
        if raw and raw.strip():
            return Path(raw.strip()).expanduser()
    return DEFAULT_DATA_DIR


def choice_path(data_dir: Path | None = None) -> Path:
    """Return the path of the persisted choice file.

    Args:
        data_dir: Explicit data dir (the CLI passes its resolved one);
            ``None`` resolves via :func:`resolve_data_dir`.
    """
    base = Path(data_dir).expanduser() if data_dir is not None else resolve_data_dir()
    return base / CHOICE_FILENAME


def read_demo_seed_choice(data_dir: Path | None = None) -> bool | None:
    """Read the persisted choice.

    Returns:
        ``True`` / ``False`` when a valid choice file exists, ``None`` when
        no choice has been recorded (missing/corrupt file - treated as
        "never asked").
    """
    path = choice_path(data_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Could not read demo-seed choice at %s: %s", path, exc)
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Ignoring corrupt demo-seed choice file at %s", path)
        return None
    value = data.get("seed_demo") if isinstance(data, dict) else None
    if isinstance(value, bool):
        return value
    return None


def write_demo_seed_choice(seed_demo: bool, data_dir: Path | None = None) -> bool:
    """Persist the choice. Best-effort: returns ``False`` on I/O failure."""
    path = choice_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"seed_demo": seed_demo}) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist demo-seed choice at %s: %s", path, exc)
        return False
    return True


def seed_demo_enabled() -> bool:
    """Should the startup seeder install demo accounts / showcase projects?

    ``SEED_DEMO`` (when set) keeps its historical semantics: only the
    explicit values ``false`` / ``0`` / ``no`` disable seeding. When the
    variable is unset, the persisted choice file decides; without either,
    seeding stays on (out-of-the-box demo experience).
    """
    env = os.environ.get("SEED_DEMO")
    if env is not None:
        return env.strip().lower() not in ("false", "0", "no")
    choice = read_demo_seed_choice()
    if choice is not None:
        return choice
    return True
