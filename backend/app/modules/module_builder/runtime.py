# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The built modules running in this process, as other modules need to see them.

The deadline register reminds records of built modules that have a deadline,
and the comment threads accept records of built modules that take comments.
Both need the same three facts about a module: that it is installed by the
builder, that it is loaded right now, and what its spec says. This is the one
place that answers them, so the two cannot disagree about which modules count.

A module counts only when all of these hold: its directory is under the
runtime module root (a module shipped with the platform never does), it is
loaded (an uninstalled or switched-off module is not), and its ``spec.json``
validates. Anything else answers ``None``, so every caller fails closed.
"""

from __future__ import annotations

import importlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.modules.module_builder.spec import IDENTIFIER_RE, ModuleSpec

logger = logging.getLogger(__name__)

# What generator._spec_json adds to the spec it writes; not part of the spec.
_STAMPS = ("generated_at", "generator")


@dataclass(frozen=True)
class BuiltModule:
    """A loaded built module: its spec and its ORM model."""

    key: str
    spec: ModuleSpec
    model: Any


def loaded_built_module(key: str) -> BuiltModule | None:
    """The built module ``key``, if it is installed, loaded and readable."""
    if not isinstance(key, str) or not IDENTIFIER_RE.match(key):
        return None
    from app.core.module_loader import module_loader
    from app.core.module_runtime_root import runtime_modules_dir

    if f"oe_{key}" not in module_loader.loaded_modules:
        return None
    path = runtime_modules_dir() / key / "spec.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    for stamp in _STAMPS:
        payload.pop(stamp, None)
    try:
        spec = ModuleSpec.model_validate(payload)
    except ValidationError:
        logger.warning("module_builder: %s has a spec.json that no longer validates", key)
        return None
    if spec.key != key:
        return None
    try:
        model = getattr(importlib.import_module(f"app.modules.{key}.models"), spec.class_name)
    except (ImportError, AttributeError):
        logger.warning("module_builder: %s is loaded but its model cannot be found", key, exc_info=True)
        return None
    return BuiltModule(key=key, spec=spec, model=model)


def loaded_built_modules() -> list[BuiltModule]:
    """Every loaded built module, in key order."""
    from app.core.module_runtime_root import runtime_modules_dir

    root = runtime_modules_dir()
    if not root.is_dir():
        return []
    found = (loaded_built_module(child.name) for child in sorted(root.iterdir()) if child.is_dir())
    return [module for module in found if module is not None]
