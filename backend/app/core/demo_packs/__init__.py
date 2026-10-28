# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Auto-discovered partner-pack flagship demo projects.

Each sibling module defines a module-level ``TEMPLATE`` (an
``app.core.demo_projects.DemoTemplate``) describing one realistic,
country/company-specific demo project for a partner pack. Filenames use the
project's ``demo_id`` and may contain hyphens, so the modules are loaded by
file path rather than via dotted import.

After loading, this module pushes ``PACK_TEMPLATES`` into
``app.core.demo_projects`` via ``register_pack_templates`` so they install
through the normal ``install_demo_project()`` path and appear in
``DEMO_CATALOG``. The merge runs packs -> demo_projects (never the reverse) so
it is order-independent regardless of which module is imported first. A
malformed pack is skipped with a warning and never breaks boot.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PACK_TEMPLATES: list[Any] = []

_dir = Path(__file__).resolve().parent
for _f in sorted(_dir.glob("*.py")):
    if _f.name == "__init__.py" or _f.name.startswith("_"):
        continue
    try:
        _spec = importlib.util.spec_from_file_location("oe_demo_pack_" + _f.stem.replace("-", "_"), _f)
        if _spec is None or _spec.loader is None:
            continue
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _tpl = getattr(_mod, "TEMPLATE", None)
        if _tpl is not None:
            PACK_TEMPLATES.append(_tpl)
    except Exception:  # pragma: no cover - a broken pack must not break boot
        logger.warning("failed to load demo pack %s", _f.name, exc_info=True)

# Push the loaded templates into the demo-project registry + catalog. This
# direction (packs -> demo_projects) keeps the merge order-independent: the
# pack files above only import ``DemoTemplate`` from demo_projects, never
# ``PACK_TEMPLATES`` back from here. ``demo_projects`` also imports this module
# at the bottom of its own file so the loader runs when it is imported first.
try:
    from app.core import demo_projects as _demo_projects

    _demo_projects.register_pack_templates(PACK_TEMPLATES)
except Exception:  # pragma: no cover - never let registration break boot
    logger.warning("failed to register pack templates into demo_projects", exc_info=True)
