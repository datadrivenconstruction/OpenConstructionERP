# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Schedule Intelligence manifest + governance-schema sanity checks."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_manifest_is_well_formed() -> None:
    from app.modules.schedule_intelligence import manifest as manifest_mod

    m = manifest_mod.manifest
    assert m.name == "oe_schedule_intelligence"
    assert m.version
    assert m.display_name
    assert m.category == "business"
    # Thin orchestration layer — must depend on the modules it composes.
    assert "oe_schedule_advanced" in m.depends


def test_permission_set_covers_the_pipeline() -> None:
    """The registered verbs cover Watch→Score→Attribute→Quantify→Decide + governance."""
    from app.core.permissions import permission_registry
    from app.modules.schedule_intelligence.permissions import (
        register_schedule_intelligence_permissions,
    )

    register_schedule_intelligence_permissions()
    expected = {
        "schedule_intelligence.read",
        "schedule_intelligence.score",
        "schedule_intelligence.attribute",
        "schedule_intelligence.quantify",
        "schedule_intelligence.decide",
        "schedule_intelligence.apply",
        "schedule_intelligence.configure",
        "schedule_intelligence.lock",
    }
    registered = set(permission_registry.list_all().keys())
    assert expected <= registered


def test_lock_request_requires_path_and_type() -> None:
    from app.modules.schedule_intelligence.schemas import LockFigureRequest

    with pytest.raises(ValidationError):
        LockFigureRequest(value=42)  # type: ignore[call-arg]


def test_lock_request_accepts_valid_payload() -> None:
    from app.modules.schedule_intelligence.enums import LockedFigureType
    from app.modules.schedule_intelligence.schemas import LockFigureRequest

    req = LockFigureRequest(
        path="decision.1.impact_days",
        figure_type=LockedFigureType.IMPACT_DAYS,
        value=42,
    )
    assert req.figure_type == LockedFigureType.IMPACT_DAYS


def test_confidence_preview_bounds_base_score() -> None:
    from app.modules.schedule_intelligence.schemas import ConfidencePreviewRequest

    ConfidencePreviewRequest(base_score=0.5)  # ok
    with pytest.raises(ValidationError):
        ConfidencePreviewRequest(base_score=1.5)
    with pytest.raises(ValidationError):
        ConfidencePreviewRequest(base_score=-0.1)


def test_confidence_config_upsert_project_id_not_required() -> None:
    from app.modules.schedule_intelligence.schemas import ConfidenceConfigUpsert

    cfg = ConfidenceConfigUpsert(schedule_quality_caps={"poor": 0.3})
    assert cfg.band_thresholds is None  # omitted facets stay unset → engine default
    assert cfg.schedule_quality_caps == {"poor": 0.3}
    _ = uuid4  # keep import parity with sibling tests
