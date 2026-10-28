# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠P1 — Backend ``group_by`` validation regression suite.

The /match-elements pipeline's Group stage used to silently skip a
``rebuild_groups`` call when the user-supplied ``group_by`` keys didn't
match the adapter's attribute set. The stage then stamped ``done`` with
the previous (stale) groups — the user got no error toast, no
indication that their reconfigure didn't take effect, and only noticed
the bug two stages later when Match returned empty candidates.

The fix wires ``_run_group`` to validate the keys against the adapter's
``list_attribute_keys`` output + a small whitelist of structural keys
(``ifc_class``, ``type_name``, ``level``, etc) that the grouper handles
natively even though the adapter doesn't surface them as element
attributes. A bad key now raises ``ValueError("invalid_group_by_keys",
<bad_keys>)``; ``run_stage`` catches that, writes it to ``stage.error``
and flips status to "error" — exactly the UX a user expects.

Every test uses a transaction-isolated PostgreSQL session (rolled back
on teardown by ``tests._pg.transactional_session``) — never the
production / shared test DB.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements import pipeline
from app.modules.match_elements.models import (
    MatchSession,
    MatchStageState,
)
from app.modules.match_elements.service import get_service
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session seeded with a User + Project."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"grp-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Grp Owner",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Group Validation Project",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.commit()
        s.info["project_id"] = project.id
        yield s


async def _seed_session(s: AsyncSession) -> MatchSession:
    """Insert a minimal MatchSession + persist it."""
    ms = MatchSession(
        id=uuid.uuid4(),
        project_id=s.info["project_id"],
        source="bim",
        name="grp-test",
        group_by=["ifc_class"],
        filters={},
        excluded_categories=[],
    )
    s.add(ms)
    await s.commit()
    return ms


async def _seed_stage(
    s: AsyncSession,
    session_id: uuid.UUID,
    inputs: dict[str, Any],
) -> MatchStageState:
    """Insert a MatchStageState row for the Group stage with the given inputs."""
    row = MatchStageState(
        id=uuid.uuid4(),
        session_id=session_id,
        stage_name="group",
        status="pending",
        inputs=inputs,
        output={},
    )
    s.add(row)
    await s.commit()
    return row


class _FakeAdapter:
    """Mimics the source-adapter contract used by ``_run_group``.

    Only ``list_attribute_keys`` is exercised — the bad-key branch
    bails before ``rebuild_groups`` is ever called, and the good-key
    branch is covered by a monkeypatch on ``rebuild_groups`` itself.
    """

    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    async def list_attribute_keys(self, _project_id: uuid.UUID, _bim_model_id: Any) -> list[str]:
        return list(self._keys)


@pytest.mark.asyncio
async def test_invalid_group_by_keys_raises_value_error(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad key → ValueError("invalid_group_by_keys", [bad_keys])."""
    ms = await _seed_session(session)
    stage = await _seed_stage(session, ms.id, {"group_by": ["does_not_exist"]})

    service = get_service()
    # ``does_not_exist`` is neither in the adapter's exposed keys nor in
    # the structural whitelist — must reject.
    monkeypatch.setattr(
        service,
        "_adapter",
        lambda _src, _db, _ms: _FakeAdapter(["material", "thickness_mm"]),
    )

    with pytest.raises(ValueError) as excinfo:
        await pipeline._run_group(session, ms, stage)

    # The exception MUST be a structured 2-arg ValueError so the FE can
    # parse the error code from ``str(exc)`` reliably.
    assert excinfo.value.args[0] == "invalid_group_by_keys"
    assert "does_not_exist" in excinfo.value.args[1]


@pytest.mark.asyncio
async def test_structural_keys_are_whitelisted(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ifc_class`` / ``level`` aren't adapter attrs but must validate.

    The grouper handles those keys natively (they live on every
    element regardless of source) — a regression that dropped them
    from the structural whitelist would break the default BIM preset.
    """
    ms = await _seed_session(session)
    stage = await _seed_stage(session, ms.id, {"group_by": ["ifc_class", "level"]})

    service = get_service()
    monkeypatch.setattr(
        service,
        "_adapter",
        lambda _src, _db, _ms: _FakeAdapter([]),  # empty adapter set
    )

    # rebuild_groups would otherwise try to scan real BIM rows; stub it.
    async def _noop_rebuild(_db: AsyncSession, _sid: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(service, "rebuild_groups", _noop_rebuild)

    # Should NOT raise — both keys are in the structural whitelist.
    out = await pipeline._run_group(session, ms, stage)
    assert out["group_by"] == ["ifc_class", "level"]


@pytest.mark.asyncio
async def test_run_stage_writes_error_status_for_bad_group_by(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: ``run_stage("group")`` with bad keys must flip the row to status='error'.

    This is the user-visible contract — the stage card shows red
    instead of green-with-stale-output. Without this guard the bug
    would surface as silently-empty Match candidates two stages later.
    """
    ms = await _seed_session(session)
    # Stage row is created by ``run_stage`` itself; we only pre-seed
    # the inputs override on the call below.

    service = get_service()
    monkeypatch.setattr(
        service,
        "_adapter",
        lambda _src, _db, _ms: _FakeAdapter(["material"]),
    )

    result = await pipeline.run_stage(
        session,
        ms.id,
        "group",
        inputs_override={"group_by": ["bogus_attr"]},
    )
    assert result["status"] == "error"
    assert "invalid_group_by_keys" in str(result["error"])
    assert "bogus_attr" in str(result["error"])
