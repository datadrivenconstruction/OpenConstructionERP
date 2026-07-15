# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Placeholder — the real Schedule Intelligence tests moved to backend/tests/.

The substantive suites live under ``backend/tests/unit/`` so the repo's test
runner (``make test-backend`` / ``make module-test NAME=oe_schedule_intelligence``,
which runs ``pytest tests/``) collects them:

    * test_oe_schedule_intelligence_locked_guard.py  — E5.2 negative-injection
    * test_oe_schedule_intelligence_confidence.py    — E5.3 confidence gating
    * test_oe_schedule_intelligence_manifest.py       — manifest + schemas + perms

This module-local file is retained only so the package's ``tests/`` dir is not
empty; it intentionally contains no ``Item``-era assertions.
"""

from __future__ import annotations


def test_module_imports_cleanly() -> None:
    """The package and its manifest import without side effects."""
    from app.modules.schedule_intelligence import manifest as manifest_mod

    assert manifest_mod.manifest.name == "oe_schedule_intelligence"
