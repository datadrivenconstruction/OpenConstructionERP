"""An unprofiled project must open on the read-only demo without a write."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.projects import profile_service


@pytest.mark.asyncio
async def test_default_profile_is_answered_unsaved_on_the_read_only_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.demo_read_only.demo_read_only_enabled", lambda: True)
    db = MagicMock()
    lookup = MagicMock()
    lookup.first.return_value = None
    db.execute = AsyncMock(return_value=lookup)
    project_id = uuid.uuid4()

    result = await profile_service.ensure_default_profile(db, project_id)

    db.add.assert_not_called()
    assert result.profile.project_id == project_id
    assert result.profile.focus_mode_enabled is False
    assert result.enabled_count == len(result.modules) == len(profile_service.discover_module_names())


def test_default_profile_result_enables_every_module() -> None:
    result = profile_service.default_profile_result(uuid.uuid4())
    assert all(m.enabled and m.tier == "must" for m in result.modules)
    assert [m.ordinal for m in result.modules] == list(range(1, len(result.modules) + 1))
