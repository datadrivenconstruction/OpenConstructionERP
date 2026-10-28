# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The gate reads the repair registry as source text, so the two must not drift.

``scripts/check_data_rewrite_boot_repair.py`` validates a revision's
``# boot-repair: registry=<id>`` line against the ``register_data_repair()``
calls in every ``app/**/repairs.py``, and it parses those files with ``ast``
rather than importing them: importing pulls in SQLAlchemy and ``app.database``,
which builds an engine from the environment, so a source-text gate would
otherwise need a configured database to answer a question about source text.

The shortcut has the failure mode every shortcut of that shape has. A
registration written in a form the parser does not recognise - built in a loop,
given a computed id - reads back as fewer entries, or as none, and the gate
then rejects a ``registry=`` line that names a repair that really is
registered. Or, worse, the parser keeps working while the runner is handed a
different set.

Since the registry became dynamic there is a second, sharper failure mode, and
it is the one this file exists for. Registration happens when a module's
``repairs.py`` is imported. **A module that is not imported registers nothing,
and a repair that is not registered does not run** - silently, with the boot
reporting success, which is the exact defect the whole data-repair mechanism
was written to remove. Reintroducing it through the fix would be the worst
possible outcome, so the static reading and the post-discovery registry are
compared here in both directions.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"


def _gate_module():
    """Import the gate script by path, without putting it on the import graph."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import check_data_rewrite_boot_repair as gate

    return gate


def test_the_gate_reads_exactly_the_registry_the_application_runs() -> None:
    """Both directions, because each way of being wrong has its own cause.

    An id the gate sees and the runtime does not means a module failed to
    import - the silent-skip case. An id the runtime has and the gate does not
    means the registration is written in a form ``ast`` cannot read, and the
    gate would then reject a valid ``registry=`` declaration.
    """
    from app.core.data_repairs import discover_data_repairs

    gate = _gate_module()
    static_ids = gate.registry_ids()
    runtime_ids = {r.repair_id for r in discover_data_repairs()}

    assert static_ids - runtime_ids == set(), (
        f"registered in source but missing from the live registry: {sorted(static_ids - runtime_ids)}. "
        "The owning module's repairs.py did not import, so these repairs would not run on boot."
    )
    assert runtime_ids - static_ids == set(), (
        f"live but invisible to the gate: {sorted(runtime_ids - static_ids)}. "
        "The gate would reject a registry= declaration naming one of these."
    )


def test_every_revision_declaration_resolves_in_the_live_registry() -> None:
    """The end-to-end claim: a revision that says ``registry=x`` really does run ``x``.

    The gate already checks this against source text. Doing it again against the
    registry the application actually builds is what closes the gap between "the
    declaration is spelled right" and "the repair is reachable at runtime".
    """
    from app.core.data_repairs import discover_data_repairs

    gate = _gate_module()
    runtime_ids = {r.repair_id for r in discover_data_repairs()}

    declared: set[str] = set()
    for path in sorted(gate.VERSIONS_DIR.glob("*.py")):
        for decl in gate.parse_declarations(path.read_text(encoding="utf-8")):
            if decl.kind == "registry":
                declared.add(decl.value)

    assert declared, "no revision declares registry= at all - this check would be vacuous"
    assert declared <= runtime_ids, (
        f"revisions point at repair ids that are not registered at runtime: {sorted(declared - runtime_ids)}"
    )


def test_the_registry_is_not_empty() -> None:
    """A registry with nothing in it makes every check above vacuously true.

    It is also the shape the defect would take if discovery were ever quietly
    broken: the runner would keep running, the health field would keep
    answering ``false``, and nothing would be repaired.
    """
    from app.core.data_repairs import discover_data_repairs

    assert discover_data_repairs(), "the registry is empty - every registry= declaration would now be rejected"


def test_the_gate_points_at_files_that_actually_exist() -> None:
    """A path that no longer resolves reads back as an empty registry.

    ``registry_ids`` globs for ``repairs.py`` and returns whatever it finds, so
    a wrong root directory looks exactly like a codebase with no repairs. The
    gate's own ``main`` refuses a too-small read for that reason; this asserts
    the paths are right in the first place.
    """
    gate = _gate_module()

    assert gate.REGISTRY_CORE_FILE.is_file(), f"{gate.REGISTRY_CORE_FILE} does not exist"
    assert gate.APP_DIR.is_dir(), f"{gate.APP_DIR} does not exist"
    assert list(gate.APP_DIR.rglob("repairs.py")), "no app/**/repairs.py found at all"


def test_registering_two_repairs_under_one_id_is_refused() -> None:
    """Two repairs sharing an id would share a ledger row and report each other's counts."""
    import pytest

    from app.core.data_repairs import DataRepair, register_data_repair

    async def _noop(session: object) -> int:
        return 0

    first = DataRepair(
        repair_id="duplicate_id_probe",
        revision="",
        summary="probe",
        run=_noop,
        nature="always_wrong",
    )
    second = DataRepair(
        repair_id="duplicate_id_probe",
        revision="",
        summary="a different repair claiming the same id",
        run=_noop,
        nature="always_wrong",
    )
    register_data_repair(first)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_data_repair(second)
    finally:
        from app.core.data_repairs import _REGISTRY

        _REGISTRY.pop("duplicate_id_probe", None)


def test_a_superseded_repair_without_its_declaration_is_refused() -> None:
    """The nature field is only worth having if a wrong declaration cannot be constructed."""
    import pytest

    from app.core.data_repairs import DataRepair

    async def _noop(session: object) -> int:
        return 0

    with pytest.raises(ValueError, match="no SupersededBy"):
        DataRepair(
            repair_id="superseded_without_block",
            revision="",
            summary="claims to supersede but says nothing about how",
            run=_noop,
            nature="superseded",
        )


def test_a_supersede_block_on_an_always_wrong_repair_is_refused() -> None:
    """The other direction: a block that nothing will check is a comment pretending to be a contract."""
    import pytest

    from app.core.data_repairs import DataRepair, SupersededBy

    async def _noop(session: object) -> int:
        return 0

    with pytest.raises(ValueError, match="only meaningful for 'superseded'"):
        DataRepair(
            repair_id="always_wrong_with_block",
            revision="",
            summary="carries a block it does not need",
            run=_noop,
            nature="always_wrong",
            superseded=SupersededBy(effective_from="2025-01-01", table="t", closes_column="c"),
        )


def test_every_registered_repair_can_be_imported() -> None:
    """The runner calls these on the boot path, where a bad import is a logged error.

    Each entry imports its target lazily so importing a ``repairs.py`` costs
    only the registration, which means a typo in that import surfaces only when
    the repair runs. Calling nothing and importing everything is the cheap half
    of that check.
    """
    import importlib
    import inspect

    from app.core.data_repairs import discover_data_repairs

    for repair in discover_data_repairs():
        source = inspect.getsource(repair.run)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("from app.") and " import " in stripped:
                module = stripped.split()[1]
                names = stripped.split(" import ", 1)[1]
                imported = importlib.import_module(module)
                for name in (n.strip() for n in names.split(",")):
                    assert hasattr(imported, name), f"{repair.repair_id}: {module} has no {name!r}"
