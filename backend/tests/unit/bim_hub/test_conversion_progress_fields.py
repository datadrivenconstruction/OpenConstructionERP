"""The model payload carries the running conversion step only while it is processing."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.modules.bim_hub.schemas import BIMModelResponse


def _model(status: str, meta: dict) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(), project_id=uuid4(), name="m", discipline=None, model_format="rvt", version="1",
        import_date=None, status=status, element_count=0, storey_count=0, bounding_box=None,
        original_file_id=None, canonical_file_path=None, parent_model_id=None, error_message=None,
        created_by=None, metadata_=meta, created_at=now, updated_at=now,
    )  # fmt: skip


def test_processing_model_exposes_stage_and_limit() -> None:
    meta = {
        "conversion_stage": "converting",
        "conversion_started_at": "2026-10-21T10:00:00+00:00",
        "conversion_timeout_s": 1800,
    }
    resp = BIMModelResponse.model_validate(_model("processing", meta))
    assert resp.conversion_stage == "converting"
    assert resp.conversion_started_at == "2026-10-21T10:00:00+00:00"
    assert resp.conversion_timeout_s == 1800


def test_finished_model_hides_stage() -> None:
    resp = BIMModelResponse.model_validate(_model("ready", {"conversion_stage": "reading_elements"}))
    assert resp.conversion_stage is None
