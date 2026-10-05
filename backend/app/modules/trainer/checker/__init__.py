# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The trainer's deterministic checker.

* :mod:`.units` - the unit of every probed field, and money/percent normalisation.
* :mod:`.matching` - tolerance compare, ``also_accepted``, diagnosis matching (pure).
* :mod:`.registry` - the probe registry, ``ProbeContext``, ``run_probe``.
* :mod:`.probes` - one class per probe type; each reads ERP state through the
  owning module's service or repository.
* :mod:`.grading` - ``grade_task`` (pure), ``readback_values`` and
  ``run_task_probes``.

The service (Wave 2) calls ``run_task_probes`` with the enrolment's
``ProbeContext``, then ``grade_task`` with the stored answers, and builds the
``AttemptResult`` around the returned ``GradeOutcome``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Exports resolve on first use (PEP 562). ``validators`` imports
# ``checker.matching`` for the one comparison (decision 37) and ``grading``
# imports ``validators``; importing ``grading`` here eagerly would close that
# loop while ``validators`` is half initialised.
_EXPORTS = {
    "Expectation": "matching",
    "values_match": "matching",
    "GradeOutcome": "grading",
    "PanelAnswer": "grading",
    "grade_task": "grading",
    "readback_values": "grading",
    "run_task_probes": "grading",
    "ProbeContext": "registry",
    "ProbeResult": "registry",
    "get_probe": "registry",
    "run_probe": "registry",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    return getattr(import_module(f"{__name__}.{module}"), name)
