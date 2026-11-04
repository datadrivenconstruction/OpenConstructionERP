"""Every table name is mapped by exactly one declarative class.

Two classes on one ``__tablename__`` make ``Base.metadata`` raise "Table ... is already
defined" for whichever module is imported second, so the failure depends on import order.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict

import app.core
from app.database import Base


def _import_core_models() -> None:
    for info in pkgutil.iter_modules(app.core.__path__):
        if info.name.startswith("event_effect"):
            importlib.import_module(f"app.core.{info.name}")


def test_event_effect_table_has_one_mapped_class() -> None:
    _import_core_models()
    owners: dict[str, set[type]] = defaultdict(set)
    for mapper in Base.registry.mappers:
        owners[mapper.local_table.name].add(mapper.class_)
    assert len(owners["oe_event_effect"]) == 1, owners["oe_event_effect"]
