# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Seeded register values, read out of the shapes the wide gate cannot see.

``test_demo_seed_speaks_module_vocabularies.py`` asks the same question across
every module, and its answer is trustworthy for the shape it reads: a dict
literal whose keys name schema fields. Two shapes fall outside it, and a tender
package status seeded "open" survived in both at once.

The first is the tuple. ``tendering/seed.py`` writes its packages as
``(suffix, trade, status, deadline, budget)``, and a tuple has no keys, so
there is nothing for the wide gate to attribute. Its own docstring names this
gap: the safety defect it misses is a tuple pool for the same reason.

The second is the directory. That gate globs ``demo_*.py`` beside
``demo_projects.py`` and ``modules/*/seed.py``. ``core/demo_packs/`` is a
subdirectory of neither, so the twenty-odd project packs, which carry most of
the seeded records a reader ever sees, are not read at all.

There is a third reason a value survives, and it is invisible from outside
because the record looks like exactly the shape the wide gate reads. The punch
items in ``demo_projects.py`` ARE dict literals, they ARE read, and they still
pass. Measured rather than assumed: the attribution was instrumented on 18.08
and those records land on ``PunchItemResponse``, which carries no pattern,
because the response schema is the one that also has ``trade``, ``location_x``
and ``resolution_notes`` and therefore covers the record best. A vocabulary
lives on Create and Update; attributing by key coverage steers towards
Response, which is where a seeded row's extra fields are.

So this file is the narrow and deep half of that division of labour, for the
registers where the miss reached a screenshot. It reads the vocabulary out of
the schema rather than restating it, so widening the product widens the test
with it and a copy of the word list cannot drift from the real one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from app.core import demo_projects
from app.modules.inspections.schemas import InspectionUpdate
from app.modules.punchlist.schemas import PunchItemUpdate
from app.modules.tendering.schemas import PackageUpdate

_ALTERNATION = re.compile(r"\^\(([a-z0-9_|\-]+)\)\$")

# Floors, so that a collector which stops finding anything fails instead of
# passing over nothing. Measured 18.08: 135 package statuses are reachable from
# these sources, of which 112 are "evaluating", and 30 punch categories. Set
# well under both so ordinary drift does not trip them, and far enough above
# zero that a collector reading nothing cannot look clean.
_MIN_PACKAGE_STATUSES = 90
_MIN_PUNCH_CATEGORIES = 20
_MIN_INSPECTION_TYPES = 15  # measured 21


def _vocabulary(model: Any, field: str) -> set[str]:
    """The words a schema field accepts, read off its own constraint."""
    for meta in model.model_fields[field].metadata or []:
        pattern = getattr(meta, "pattern", None)
        match = _ALTERNATION.fullmatch(pattern) if isinstance(pattern, str) else None
        if match:
            return set(match.group(1).split("|"))
    raise AssertionError(f"{model.__name__}.{field} no longer states a vocabulary this test can read")


def _sources() -> list[Path]:
    """Every seed file that can mint a register row, packs included."""
    core = Path(demo_projects.__file__).parent
    backend_app = core.parent
    return (
        sorted(core.glob("demo_*.py"))
        + sorted((core / "demo_packs").glob("*.py"))
        + sorted(backend_app.glob("modules/*/seed.py"))
    )


def _where(path: Path, line: int) -> str:
    parts = path.parts
    stem = "/".join(parts[parts.index("app") :]) if "app" in parts else path.name
    return f"{stem}:{line}"


def _holder_value(node: ast.AST, holders: set[str]) -> ast.expr | None:
    """The expression a named holder is bound to, keyword or assignment alike."""
    if isinstance(node, ast.keyword):
        return node.value if node.arg in holders else None
    if isinstance(node, ast.Assign):
        return node.value if any(isinstance(t, ast.Name) and t.id in holders for t in node.targets) else None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.value if node.target.id in holders else None
    return None


def _tuple_field(path: Path, holders: set[str], index: int) -> list[tuple[str, str]]:
    """Constant strings at ``index`` of every tuple under a named holder.

    ``holders`` are the keyword arguments and assignment targets whose value is
    a list of record tuples - ``tender_packages=[...]`` in a pack, and
    ``_PACKAGE_SPECS = [...]`` in a module seed. Reading the position rather
    than searching the file for status-shaped words is what keeps this from
    reporting a trade name that happens to read like a status.
    """
    found: list[tuple[str, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        value = _holder_value(node, holders)
        if not isinstance(value, ast.List | ast.Tuple):
            continue
        for element in value.elts:
            if not isinstance(element, ast.Tuple) or len(element.elts) <= index:
                continue
            slot = element.elts[index]
            if isinstance(slot, ast.Constant) and isinstance(slot.value, str):
                found.append((_where(path, slot.lineno), slot.value))
    return found


def _call_keyword(path: Path, callee: str, keyword: str) -> list[tuple[str, str]]:
    """Constant ``keyword=`` arguments passed to a named constructor."""
    found: list[tuple[str, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != callee:
            continue
        for kw in node.keywords:
            if kw.arg == keyword and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                found.append((_where(path, kw.value.lineno), kw.value.value))
    return found


def _dict_field(path: Path, field: str, companions: set[str]) -> list[tuple[str, str]]:
    """Constant ``field`` values from dict literals that also carry ``companions``.

    The companion keys are what identifies the record. ``category`` on its own
    is written all over the seed; a literal that also carries ``priority``,
    ``status``, ``title`` and ``trade`` is a punch item.
    """
    found: list[tuple[str, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        record = {
            key.value: value
            for key, value in zip(node.keys, node.values, strict=False)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        if not companions <= set(record):
            continue
        slot = record.get(field)
        if isinstance(slot, ast.Constant) and isinstance(slot.value, str):
            found.append((_where(path, slot.lineno), slot.value))
    return found


def _package_statuses() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for source in _sources():
        found += _tuple_field(source, {"tender_packages", "_PACKAGE_SPECS"}, index=2)
        found += _call_keyword(source, "TenderPackage", "status")
    return found


def _punch_categories() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for source in _sources():
        found += _dict_field(source, "category", {"priority", "status", "title", "trade"})
    return found


def _inspection_types() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for source in _sources():
        found += _dict_field(source, "inspection_type", {"status", "title"})
    return found


def test_seeded_tender_package_statuses_are_the_modules_own() -> None:
    """A package the register cannot label is a package the edit form cannot save.

    "open" reached the tendering register as the bare lowercase word, beside
    packages reading Draft, Closed and Evaluating, because there is no label
    for a status the product does not offer and no honest way to invent one.
    """
    allowed = _vocabulary(PackageUpdate, "status")
    seeded = _package_statuses()
    assert len(seeded) >= _MIN_PACKAGE_STATUSES, (
        f"only {len(seeded)} seeded package statuses were found, expected at least "
        f"{_MIN_PACKAGE_STATUSES}; the collector has broken and this test would pass "
        f"without reading a package"
    )
    refused = [f"{where} seeds status={value!r}" for where, value in seeded if value not in allowed]
    assert not refused, f"tendering accepts only {'|'.join(sorted(allowed))}:\n  " + "\n  ".join(refused)


def test_seeded_punch_categories_are_the_modules_own() -> None:
    """A category outside the eleven prints as a title-cased token.

    "mep" is not one of them, and the punch register showed it as "Mep" - the
    fallback doing exactly what it is for, on a value that should never have
    reached it. No caser can know that this particular token is an initialism,
    which is why the fix is the value and not the caser.
    """
    allowed = _vocabulary(PunchItemUpdate, "category")
    seeded = _punch_categories()
    assert len(seeded) >= _MIN_PUNCH_CATEGORIES, (
        f"only {len(seeded)} seeded punch categories were found, expected at least "
        f"{_MIN_PUNCH_CATEGORIES}; the collector has broken and this test would pass "
        f"without reading a punch item"
    )
    refused = [f"{where} seeds category={value!r}" for where, value in seeded if value not in allowed]
    assert not refused, f"punchlist accepts only {'|'.join(sorted(allowed))}:\n  " + "\n  ".join(refused)


def test_seeded_inspection_types_are_the_modules_own() -> None:
    """The type column printed a bare token beside a result column that read Pass.

    That contrast is what made it a defect rather than a rough edge: the
    inspection register already knew how to say Pass and Fail, so "concrete"
    next to it reads as a column nobody finished. Ten of the seeded types were
    also outside the eleven the module offers, which is a second fault in the
    same cell - a type no filter can select and no edit form can save. The
    module's own explainer names the eleven, so the schema is the product's
    intent and the seed is what drifted.
    """
    allowed = _vocabulary(InspectionUpdate, "inspection_type")
    seeded = _inspection_types()
    assert len(seeded) >= _MIN_INSPECTION_TYPES, (
        f"only {len(seeded)} seeded inspection types were found, expected at least "
        f"{_MIN_INSPECTION_TYPES}; the collector has broken and this test would pass "
        f"without reading an inspection"
    )
    refused = [f"{where} seeds inspection_type={value!r}" for where, value in seeded if value not in allowed]
    assert not refused, f"inspections accepts only {'|'.join(sorted(allowed))}:\n  " + "\n  ".join(refused)


def test_the_collectors_would_notice_a_refused_value(tmp_path: Path) -> None:
    """The green runs above have to mean the seed is right, not that nothing is read.

    Both collectors are pointed at a file written here that holds a bad value in
    each shape they read. If this stops failing, the tests above have stopped
    checking.
    """
    planted = tmp_path / "demo_planted.py"
    planted.write_text(
        "TEMPLATE = dict(\n"
        "    tender_packages=[('Package', 'Scope', 'open', [])],\n"
        ")\n"
        "_PACKAGE_SPECS = [('ELEC', 'Electrical works', 'open', '2026-07-15', '1')]\n"
        "PUNCH = [{'title': 'T', 'priority': 'high', 'status': 'open',\n"
        "          'trade': 'Plumbing', 'category': 'mep'}]\n"
        "INSPECTIONS = [{'title': 'T', 'status': 'completed', 'inspection_type': 'slab'}]\n",
        encoding="utf-8",
    )
    statuses = _tuple_field(planted, {"tender_packages", "_PACKAGE_SPECS"}, index=2)
    categories = _dict_field(planted, "category", {"priority", "status", "title", "trade"})
    types = _dict_field(planted, "inspection_type", {"status", "title"})

    assert [value for _, value in statuses] == ["open", "open"], (
        "the collector no longer reads a package status out of either shape"
    )
    assert [value for _, value in categories] == ["mep"], "the collector no longer reads a punch category"
    assert [value for _, value in types] == ["slab"], "the collector no longer reads an inspection type"
    assert "open" not in _vocabulary(PackageUpdate, "status")
    assert "mep" not in _vocabulary(PunchItemUpdate, "category")
    assert "slab" not in _vocabulary(InspectionUpdate, "inspection_type")
