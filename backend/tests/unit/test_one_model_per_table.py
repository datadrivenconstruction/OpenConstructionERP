"""Every table name in Base.metadata is mapped by exactly one declarative class.

Two classes on one ``__tablename__`` make ``Base.metadata`` raise "Table ... is already
defined" for whichever module is imported second, so the failure depends on import order.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict

from app.database import Base


def _import_everything() -> None:
    import app.core.event_effects  # noqa: F401
    import app.main  # noqa: F401

    for info in pkgutil.walk_packages(app.modules.__path__, "app.modules."):
        if info.name.rsplit(".", 1)[-1] == "models":
            importlib.import_module(info.name)


def test_every_table_has_one_mapped_class() -> None:
    _import_everything()
    owners: dict[str, set[type]] = defaultdict(set)
    for mapper in Base.registry.mappers:
        for table in mapper.tables:
            owners[table.name].add(mapper.class_)
    dupes = {t: sorted(c.__module__ + "." + c.__name__ for c in cs) for t, cs in owners.items() if len(cs) > 1}
    assert not dupes, dupes


def test_event_effect_table_lives_in_core_only() -> None:
    _import_everything()
    classes = {m.class_ for m in Base.registry.mappers if m.local_table.name == "oe_event_effect"}
    assert len(classes) == 1
    assert next(iter(classes)).__module__ == "app.core.event_effects"
