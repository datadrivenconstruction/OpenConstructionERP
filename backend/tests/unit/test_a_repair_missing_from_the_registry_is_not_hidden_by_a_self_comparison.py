# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A repair that drops out of the registry has to be visible to something.

The assertion this replaces
---------------------------
``tests/pg/test_data_repairs.py`` guarded the completeness of a repair pass with
``assert report.attempted == len(DATA_REPAIRS)``. Read the two sides. The report
is what running the registry produced, so ``attempted`` counts registry entries;
``len(DATA_REPAIRS)`` counts the same registry. When a repair falls out of it -
its module stops importing, its registration is deleted, discovery is narrowed -
both sides fall by one together and the assertion holds. It was written to catch
a repair going missing and was the one shape of check that could not.

That is the same mistake as the one next door, where a module that failed to
import produced the health verdict of a flawless boot: a measurement that cannot
tell "nothing ran" from "everything is fine". The registry is not evidence about
itself.

What replaces it
----------------
``tests/_repair_registry_source.py`` reads the ``register_data_repair()`` calls
out of ``app/**/repairs.py`` as source text. That reading does not move when the
registry does, which is the whole property being bought: a module that will not
import still has its registration sitting in the file.

The first test below drops one repair and then asserts *both* comparisons, so
the vacuity is measured rather than asserted in a comment. The old one still
passes over the damaged registry. The new one names the repair that went
missing.
"""

from __future__ import annotations

import pytest

from app.core import data_repairs
from tests import _repair_registry_source as source


def _report_over(repairs) -> data_repairs.DataRepairReport:
    """The report a clean pass over exactly these repairs would produce."""
    return data_repairs.DataRepairReport(
        outcomes=tuple(
            data_repairs.DataRepairOutcome(repair_id=repair.repair_id, status="clean", rows_changed=0)
            for repair in repairs
        ),
        ledger_written=True,
    )


def test_a_dropped_repair_is_invisible_to_the_old_check_and_named_by_the_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One registry, one repair removed from it, both comparisons run over the result."""
    data_repairs.discover_data_repairs()
    live = dict(data_repairs._REGISTRY)
    declared = source.declared_repair_ids()
    shared = sorted(declared & set(live))
    assert shared, (
        f"nothing is both declared in source ({sorted(declared)}) and live in the registry "
        f"({sorted(live)}), so there is no repair to drop and this test would measure nothing"
    )
    dropped = shared[0]

    monkeypatch.setattr(data_repairs, "_REGISTRY", {k: v for k, v in live.items() if k != dropped})
    report = _report_over(data_repairs.registered_data_repairs())

    # The check that used to stand here, restated against the damaged registry.
    # It passes. Both of its sides lost the same entry, so it always will.
    assert report.attempted == len(data_repairs.registered_data_repairs())
    assert report.failed == ()
    assert report.discovery_failures == ()

    # The check that replaced it, over the same report.
    assert source.repairs_missing_from(report) == {dropped}


def test_a_pass_that_covered_every_declared_repair_reports_nothing_missing() -> None:
    """The control, or the check above would pass on a helper that always finds something."""
    data_repairs.discover_data_repairs()

    report = _report_over(data_repairs.registered_data_repairs())

    assert source.repairs_missing_from(report) == set()


def test_a_source_reading_that_comes_back_empty_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty expectation would make the replacement vacuous in its turn.

    ``declared - attempted`` over an empty ``declared`` is empty for any report
    at all, including one covering no repairs. That is the defect this whole
    file is about, one level up, so the helper refuses the empty read instead of
    reporting it as agreement.
    """
    source.declared_repair_ids()  # puts scripts/ on sys.path for the import below
    import check_data_rewrite_boot_repair as gate

    monkeypatch.setattr(gate, "registry_ids", set)

    with pytest.raises(AssertionError, match="source scan found 0"):
        source.declared_repair_ids()
