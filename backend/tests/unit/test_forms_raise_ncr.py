"""Raising an NCR from a failed form: content, severity, idempotency and guards."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.forms import router as forms_router


def _submission(**over):
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "status": "completed",
        "result": "fail",
        "linked_ncr_id": None,
        "linked_inspection_id": None,
        "submission_number": "FRM-0001",
        "template_name": "Rebar check",
        "template_category": "quality",
        "location": "Level 2",
        "answers_data": {"a": "fail", "b": "pass", "c": "fail"},
        "template_snapshot": [
            {"key": "a", "type": "pass_fail_na", "label": "Cover depth", "required": True},
            {"key": "b", "type": "pass_fail_na", "label": "Spacing", "required": True},
            {"key": "c", "type": "pass_fail_na", "label": "Tie wire", "required": False},
        ],
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def wired(monkeypatch):
    sub = _submission()
    svc = MagicMock()
    svc.get_submission = AsyncMock(return_value=sub)
    svc.repo.update_submission_fields = AsyncMock()
    monkeypatch.setattr(forms_router, "_service", lambda _s: svc)
    monkeypatch.setattr(forms_router, "verify_project_access", AsyncMock())
    created = {}

    class _NCR:
        def __init__(self, _session):
            pass

        async def create_ncr(self, data, user_id=None):
            created["data"] = data
            return SimpleNamespace(id=uuid.uuid4(), ncr_number="NCR-001")

    monkeypatch.setattr("app.modules.ncr.service.NCRService", _NCR)
    return sub, svc, created


@pytest.mark.asyncio
async def test_failed_form_raises_ncr_listing_failed_items(wired) -> None:
    sub, svc, created = wired
    out = await forms_router.raise_ncr_from_submission(sub.id, MagicMock(), "u1")
    assert out["created"] is True
    data = created["data"]
    assert "Cover depth" in data.description
    assert "Tie wire" in data.description
    assert "Spacing" not in data.description
    assert data.severity == "major"  # a mandatory item failed
    assert data.ncr_type == "workmanship"
    svc.repo.update_submission_fields.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_call_returns_same_ncr(wired) -> None:
    sub, _svc, created = wired
    sub.linked_ncr_id = "existing"
    out = await forms_router.raise_ncr_from_submission(sub.id, MagicMock(), "u1")
    assert out == {"ncr_id": "existing", "submission_id": str(sub.id), "created": False}
    assert not created


@pytest.mark.asyncio
@pytest.mark.parametrize("over", [{"status": "draft"}, {"result": "pass"}, {"result": None}])
async def test_only_completed_failed_forms_raise(wired, over) -> None:
    sub, _svc, _c = wired
    for k, v in over.items():
        setattr(sub, k, v)
    with pytest.raises(HTTPException) as exc:
        await forms_router.raise_ncr_from_submission(sub.id, MagicMock(), "u1")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_safety_category_and_optional_items_only_is_minor_safety_ncr(wired) -> None:
    sub, _svc, created = wired
    sub.template_category = "safety"
    sub.answers_data = {"a": "pass", "b": "pass", "c": "fail"}
    await forms_router.raise_ncr_from_submission(sub.id, MagicMock(), "u1")
    assert created["data"].ncr_type == "safety"
    assert created["data"].severity == "minor"
