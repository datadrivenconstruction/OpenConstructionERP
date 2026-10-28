# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The set of data repairs, read from source instead of from the registry.

Why a second reading exists at all
----------------------------------
``tests/pg/test_data_repairs.py`` used to check a repair pass with
``assert report.attempted == len(DATA_REPAIRS)``. Both sides of that comparison
come out of ``app.core.data_repairs._REGISTRY``: the report is built by running
what the registry holds, and the length is the registry's own length. A repair
that drops out of the registry - its module failed to import, its registration
was deleted, discovery was narrowed - takes both sides down together and the
assertion still holds. It could not fail for the reason it was written for, and
"every repair ran" and "no repair ran" were the same green.

So the count has to come from somewhere the registry cannot move. This module
reads the ``register_data_repair()`` calls out of ``app/**/repairs.py`` as text,
which is what ``scripts/check_data_rewrite_boot_repair.py`` already does for the
migration gate. It reuses that scan rather than repeating it, so the gate and
the tests cannot end up disagreeing about which repairs exist, and it is
independent in the way that matters: a module that fails to import still has its
registration sitting in the file, so the source reading keeps the id the runtime
just lost.

The floor below is not decoration. A source scan that comes back empty makes
every comparison built on it vacuously true, which is the same defect one level
up, so an empty read is refused rather than reported as agreement.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.data_repairs import DataRepairReport

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

#: Same floor, and the same reasoning, as ``_MIN_EXPECTED_REGISTRATIONS`` in the
#: gate script. Deliberately not today's count: a number that has to be edited
#: whenever a repair is added gets edited without being read, and this only has
#: to tell "the scan works" from "the scan found nothing".
_MIN_EXPECTED_REGISTRATIONS = 1


def declared_repair_ids() -> set[str]:
    """Every repair id registered in ``backend/app/**/repairs.py``, read as source.

    Returns:
        The ids the code registers, whether or not the owning module can be
        imported right now.

    Raises:
        AssertionError: If the scan found fewer registrations than the floor,
            which means it is no longer reading the registrations rather than
            that there are none.
    """
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import check_data_rewrite_boot_repair as gate

    ids = gate.registry_ids()
    assert len(ids) >= _MIN_EXPECTED_REGISTRATIONS, (
        f"the source scan found {len(ids)} register_data_repair() call(s) under "
        f"{gate.APP_DIR}/**/repairs.py. Nothing registers a repair any more, or this scan has "
        "stopped reading them - and an empty expectation makes every check built on it pass over "
        "nothing, which is the defect it was written to remove."
    )
    return ids


def repairs_missing_from(report: DataRepairReport) -> set[str]:
    """Repair ids the source registers that this pass never attempted.

    The question ``report.attempted`` cannot answer. A repair absent from the
    registry is absent from the outcomes and absent from ``report.failed``, so
    every number the report carries agrees that the pass was complete. Only a
    count from outside the registry disagrees.

    Args:
        report: What a repair pass returned.

    Returns:
        The ids that are declared in source and missing from the report, empty
        when the pass covered every declared repair. Ids the report carries and
        the source does not are not reported: tests register throwaway repairs
        of their own, and a leftover one is not this function's business.
    """
    return declared_repair_ids() - {outcome.repair_id for outcome in report.outcomes}
