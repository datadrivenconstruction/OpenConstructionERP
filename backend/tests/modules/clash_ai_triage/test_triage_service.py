# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for :class:`ClashTriageService`.

The LLM client is mocked (``app.modules.clash_ai_triage.service.call_ai``)
so the suite is hermetic and fast. Per ``feedback_test_isolation.md``
each session uses a per-test temp SQLite file via the conftest-supplied
``DATABASE_URL`` override (so the batch test, which spawns workers via
``async_session_factory``, talks to the same DB the fixture seeded).

Coverage:

1.  Single triage produces + persists a verdict row.
2.  Repeated call returns the cached row — no second LLM call.
3.  ``force_refresh=True`` bypasses the cache.
4.  Invalid JSON on first try → retry → success on retry.
5.  Invalid JSON twice → persist with ``category="unclear"``.
6.  Batch of N with ``max_concurrent=K`` never exceeds K in flight.
7.  ``cost_usd_estimate`` is computed from tokens × per-1k rate.
8.  Missing LLM key → :class:`ClashTriageUnavailable`.
9.  ``replay_with_new_prompt`` writes a NEW row.
10. Subject-type polymorphism — default ``clash`` + ``clash_issue``
    promotion when the table is reachable.
11. Concurrent triage on the same clash deduplicates (one LLM call).
12. Prior-triage context is interpolated into the user prompt on re-run.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, async_session_factory, engine
from app.modules.clash.models import ClashIssue, ClashResult, ClashRun
from app.modules.clash_ai_triage.models import ClashTriageResult
from app.modules.clash_ai_triage.prompts import PROMPT_VERSION
from app.modules.clash_ai_triage.service import (
    DEFAULT_COST_PER_1K,
    MODEL_COSTS,
    ClashSubjectNotFound,
    ClashTriageService,
    ClashTriageUnavailable,
    _estimate_cost_usd,
)


def _register_models() -> None:
    """Eagerly register every ORM module referenced by the test DB."""
    import app.modules.ai.models  # noqa: F401
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.clash.models  # noqa: F401
    import app.modules.clash_ai_triage.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    """Per-test SQLite via the conftest-bound ``async_session_factory``.

    Uses the GLOBAL ``async_session_factory`` so the batch worker (which
    also spawns sessions via that factory) talks to the same DB the
    fixture seeded. Pre-test we drop+recreate ``Base.metadata`` to wipe
    rows that a previous test in the suite left behind.
    """
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as s:
        from app.modules.ai.models import AISettings
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"triage-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Triage Tester",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Triage Test Project",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.flush()
        # An AISettings row with a placeholder Anthropic key so the
        # provider resolver returns a valid key without us having to
        # plumb encrypt_secret here. The mocked ``call_ai`` never calls
        # the real API, so the literal string is fine.
        from app.core.crypto import encrypt_secret

        ai_settings = AISettings(
            id=uuid.uuid4(),
            user_id=owner.id,
            anthropic_api_key=encrypt_secret("sk-test-fake-key"),
            preferred_model="claude-haiku",
        )
        s.add(ai_settings)

        run = ClashRun(
            id=uuid.uuid4(),
            project_id=project.id,
            name="Triage Test Run",
            model_ids=[],
            clash_type="hard",
            tolerance_m=0.005,
            clearance_m=0.0,
            mode="cross_discipline",
            status="completed",
            element_count=0,
            total_clashes=0,
            summary={},
            rules=[],
            spatial_grid_mm=500,
            created_by=str(owner.id),
        )
        s.add(run)
        await s.flush()
        clash = ClashResult(
            id=uuid.uuid4(),
            run_id=run.id,
            a_element_id=uuid.uuid4(),
            b_element_id=uuid.uuid4(),
            a_stable_id="GUID-A-001",
            b_stable_id="GUID-B-001",
            a_name="Pipe DN200",
            b_name="HEB200 Beam",
            a_discipline="Mechanical",
            b_discipline="Structural",
            a_element_type="IfcPipeSegment",
            b_element_type="IfcBeam",
            a_model_id=uuid.uuid4(),
            b_model_id=uuid.uuid4(),
            clash_type="hard",
            penetration_m=0.05,
            distance_m=0.0,
            cx=12.5,
            cy=7.5,
            cz=3.0,
            status="new",
            severity="medium",
            signature="abc123",
            signature_hash="a" * 40,
            tolerance_at_signature_time_mm=5.0,
        )
        s.add(clash)
        await s.commit()
        s.info["project_id"] = project.id
        s.info["owner_id"] = owner.id
        s.info["clash_id"] = clash.id
        s.info["run_id"] = run.id
        yield s


# ── Test data helpers ──────────────────────────────────────────────────────


_VALID_VERDICT_JSON = json.dumps(
    {
        "category": "real_design_flaw",
        "confidence": 0.85,
        "severity_suggested": "high",
        "explanation": "Pipe penetrates beam; reroute or add sleeve.",
        "suggested_action": "add_sleeve",
        "model_evidence_used": ["material_a=DN200", "material_b=HEB200"],
    }
)


def _mock_call_ai_factory(
    response: str = _VALID_VERDICT_JSON,
    tokens: int = 250,
    call_counter: dict[str, int] | None = None,
):
    """Build an AsyncMock that records calls and returns a fixed response."""

    async def _mock(*args, **kwargs):
        if call_counter is not None:
            call_counter["count"] = call_counter.get("count", 0) + 1
        return response, tokens

    return _mock


# ── 1. Single triage persisted ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_triage_persists_row(session: AsyncSession) -> None:
    svc = ClashTriageService(session)
    user_id: uuid.UUID = session.info["owner_id"]
    clash_id: uuid.UUID = session.info["clash_id"]

    with patch(
        "app.modules.clash_ai_triage.service.call_ai",
        new=_mock_call_ai_factory(),
    ):
        row = await svc.triage_clash(clash_id, user_id=user_id)

    assert isinstance(row, ClashTriageResult)
    assert row.category == "real_design_flaw"
    assert row.confidence == pytest.approx(0.85)
    assert row.severity_suggested == "high"
    assert row.suggested_action == "add_sleeve"
    assert "material_a=DN200" in row.model_evidence_used
    assert row.prompt_version == PROMPT_VERSION
    assert row.tokens_used == 250
    assert row.cost_usd_estimate > 0
    assert row.raw_prompt  # captured for audit
    assert row.raw_response  # captured for audit


# ── 2. Cache hit on repeat ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repeat_call_uses_cache(session: AsyncSession) -> None:
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]
    counter: dict[str, int] = {"count": 0}

    with patch(
        "app.modules.clash_ai_triage.service.call_ai",
        new=_mock_call_ai_factory(call_counter=counter),
    ):
        row1 = await svc.triage_clash(clash_id, user_id=user_id)
        row2 = await svc.triage_clash(clash_id, user_id=user_id)

    assert row1.id == row2.id
    assert counter["count"] == 1  # second call was a cache hit


# ── 3. force_refresh bypasses the cache ────────────────────────────────────


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(session: AsyncSession) -> None:
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]
    counter: dict[str, int] = {"count": 0}

    with patch(
        "app.modules.clash_ai_triage.service.call_ai",
        new=_mock_call_ai_factory(call_counter=counter),
    ):
        row1 = await svc.triage_clash(clash_id, user_id=user_id)
        row2 = await svc.triage_clash(clash_id, user_id=user_id, force_refresh=True)

    assert row1.id != row2.id
    assert counter["count"] == 2


# ── 4. Invalid JSON then valid JSON ────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_json_then_valid_on_retry(session: AsyncSession) -> None:
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]

    responses = ["not json at all, sorry", _VALID_VERDICT_JSON]
    tokens = [100, 200]

    async def _mock(*args, **kwargs):
        return responses.pop(0), tokens.pop(0)

    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock):
        row = await svc.triage_clash(clash_id, user_id=user_id)

    assert row.category == "real_design_flaw"
    assert row.tokens_used == 300  # sum of both attempts


# ── 5. Invalid JSON twice persists "unclear" ───────────────────────────────


@pytest.mark.asyncio
async def test_invalid_json_twice_persists_unclear(session: AsyncSession) -> None:
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]

    async def _mock(*args, **kwargs):
        return "still not JSON I'm afraid", 100

    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock):
        row = await svc.triage_clash(clash_id, user_id=user_id)

    assert row.category == "unclear"
    assert row.confidence == pytest.approx(0.0)
    assert row.raw_response == "still not JSON I'm afraid"


# ── 6. Batch concurrency cap ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_concurrency_cap(session: AsyncSession) -> None:
    """A batch of 10 with max_concurrent=4 keeps at most 4 calls in flight."""
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    run_id = session.info["run_id"]

    # Build 9 more clash rows so we have 10 distinct subjects.
    extra_ids: list[uuid.UUID] = [session.info["clash_id"]]
    for i in range(9):
        c = ClashResult(
            id=uuid.uuid4(),
            run_id=run_id,
            a_element_id=uuid.uuid4(),
            b_element_id=uuid.uuid4(),
            a_stable_id=f"GUID-A-{i:03d}",
            b_stable_id=f"GUID-B-{i:03d}",
            a_name=f"PipeA{i}",
            b_name=f"BeamB{i}",
            a_discipline="Mechanical",
            b_discipline="Structural",
            a_element_type="IfcPipeSegment",
            b_element_type="IfcBeam",
            a_model_id=uuid.uuid4(),
            b_model_id=uuid.uuid4(),
            clash_type="hard",
            penetration_m=0.05,
            distance_m=0.0,
            cx=float(i),
            cy=float(i),
            cz=float(i),
            status="new",
            severity="medium",
            signature=f"sig{i:03d}",
            signature_hash=f"{i:040d}",
            tolerance_at_signature_time_mm=5.0,
        )
        session.add(c)
        extra_ids.append(c.id)
    await session.commit()

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def _mock(*args, **kwargs):
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        # Yield to the loop so other coroutines accumulate.
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        return _VALID_VERDICT_JSON, 100

    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock):
        rows = await svc.triage_batch(extra_ids, user_id=user_id, max_concurrent=4)

    assert len(rows) == 10
    assert peak <= 4, f"observed peak in-flight LLM calls = {peak}, want ≤ 4"


# ── 7. Cost estimate computed from tokens ──────────────────────────────────


@pytest.mark.asyncio
async def test_cost_usd_computed_from_tokens(session: AsyncSession) -> None:
    """cost_usd = tokens/1000 * per-1k rate for the chosen model."""
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]

    async def _mock(*args, **kwargs):
        return _VALID_VERDICT_JSON, 1000  # exactly 1k tokens

    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock):
        row = await svc.triage_clash(clash_id, user_id=user_id)

    # Whatever the model name we recorded, the rate must be in the table
    # or DEFAULT_COST_PER_1K. The persisted cost ≈ rate.
    expected_rate = float(MODEL_COSTS.get(row.model_name, DEFAULT_COST_PER_1K))
    assert float(row.cost_usd_estimate) == pytest.approx(expected_rate, rel=0.01)


def test_cost_helper_unit() -> None:
    """Direct unit check on the _estimate_cost_usd helper."""
    assert _estimate_cost_usd("claude-haiku-4-5", 1000) == MODEL_COSTS["claude-haiku-4-5"]
    assert _estimate_cost_usd("claude-haiku-4-5", 0) == 0
    # Unknown model uses the conservative fallback.
    assert _estimate_cost_usd("totally-unknown", 1000) == DEFAULT_COST_PER_1K


# ── 8. No LLM key → ClashTriageUnavailable ─────────────────────────────────


@pytest.mark.asyncio
async def test_missing_llm_key_raises_unavailable(session: AsyncSession) -> None:
    """Strip the placeholder API key so the provider resolver fails."""
    from sqlalchemy import update

    from app.modules.ai.models import AISettings

    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]

    await session.execute(
        update(AISettings)
        .where(AISettings.user_id == user_id)
        .values(
            anthropic_api_key=None,
            openai_api_key=None,
            gemini_api_key=None,
        )
    )
    await session.commit()

    svc = ClashTriageService(session)
    with pytest.raises(ClashTriageUnavailable):
        await svc.triage_clash(clash_id, user_id=user_id)


# ── 9. Replay with new prompt creates a new row ────────────────────────────


@pytest.mark.asyncio
async def test_replay_creates_new_row(session: AsyncSession) -> None:
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]

    with patch(
        "app.modules.clash_ai_triage.service.call_ai",
        new=_mock_call_ai_factory(),
    ):
        original = await svc.triage_clash(clash_id, user_id=user_id)
        replayed = await svc.replay_with_new_prompt(
            original.id,
            new_prompt_version="v1.1-tuned",
            user_id=user_id,
        )

    assert replayed.id != original.id
    assert replayed.prompt_version == "v1.1-tuned"
    assert replayed.clash_id == original.clash_id


# ── 10. Subject-type polymorphism ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_subject_type_defaults_to_clash(session: AsyncSession) -> None:
    """No ClashIssue link → subject_type='clash'."""
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]

    with patch(
        "app.modules.clash_ai_triage.service.call_ai",
        new=_mock_call_ai_factory(),
    ):
        row = await svc.triage_clash(clash_id, user_id=user_id)

    assert row.subject_type == "clash"
    assert row.subject_id == clash_id


@pytest.mark.asyncio
async def test_subject_type_promotes_to_clash_issue(session: AsyncSession) -> None:
    """When ClashResult.issue_id is set + ClashIssue table reachable, promote."""
    project_id = session.info["project_id"]
    clash_id = session.info["clash_id"]
    user_id = session.info["owner_id"]
    run_id = session.info["run_id"]

    # Seed a matching ClashIssue and link the clash to it.
    issue = ClashIssue(
        id=uuid.uuid4(),
        project_id=project_id,
        signature_hash="a" * 40,
        status="new",
        first_seen_run_id=run_id,
        last_seen_run_id=run_id,
        missing_run_count=0,
        priority="high",
        server_assigned_id="CLASH-001",
        tags=[],
        signature_quality="strong",
    )
    session.add(issue)
    from sqlalchemy import update

    await session.execute(update(ClashResult).where(ClashResult.id == clash_id).values(issue_id=issue.id))
    await session.commit()

    svc = ClashTriageService(session)
    with patch(
        "app.modules.clash_ai_triage.service.call_ai",
        new=_mock_call_ai_factory(),
    ):
        row = await svc.triage_clash(clash_id, user_id=user_id)

    assert row.subject_type == "clash_issue"
    assert row.subject_id == issue.id
    # The originating clash_id is still recorded for history navigation.
    assert row.clash_id == clash_id


# ── 11. Concurrent triage on same clash deduplicates ───────────────────────


@pytest.mark.asyncio
async def test_concurrent_calls_deduplicate(session: AsyncSession) -> None:
    """Two coroutines hit the same clash simultaneously → one LLM call."""
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]
    counter: dict[str, int] = {"count": 0}

    async def _slow_mock(*args, **kwargs):
        counter["count"] += 1
        # Hold the call open so the second coroutine is forced to wait
        # on the per-subject lock and find the persisted row instead.
        await asyncio.sleep(0.05)
        return _VALID_VERDICT_JSON, 150

    with patch("app.modules.clash_ai_triage.service.call_ai", new=_slow_mock):
        results = await asyncio.gather(
            svc.triage_clash(clash_id, user_id=user_id),
            svc.triage_clash(clash_id, user_id=user_id),
        )

    assert results[0].id == results[1].id
    assert counter["count"] == 1  # second call hit the lock + cache


# ── 12. Prior triage interpolated on re-run ────────────────────────────────


@pytest.mark.asyncio
async def test_prior_triage_interpolated_on_rerun(session: AsyncSession) -> None:
    """Forced re-run sees the previous verdict in the user prompt."""
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    clash_id = session.info["clash_id"]

    captured_prompts: list[str] = []

    async def _capture_mock(*args, **kwargs):
        captured_prompts.append(kwargs.get("prompt", "") or (args[3] if len(args) > 3 else ""))
        return _VALID_VERDICT_JSON, 200

    with patch("app.modules.clash_ai_triage.service.call_ai", new=_capture_mock):
        first = await svc.triage_clash(clash_id, user_id=user_id)
        # Forced re-run after the first verdict landed.
        await svc.triage_clash(clash_id, user_id=user_id, force_refresh=True)

    # First prompt has NO prior triage section; second one does.
    assert "previously triaged" not in captured_prompts[0]
    assert "previously triaged" in captured_prompts[1]
    assert first.category in captured_prompts[1]


# ── Bonus: ClashSubjectNotFound on bogus id ────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_clash_id_raises_not_found(session: AsyncSession) -> None:
    svc = ClashTriageService(session)
    user_id = session.info["owner_id"]
    bogus = uuid.uuid4()
    with pytest.raises(ClashSubjectNotFound):
        await svc.triage_clash(bogus, user_id=user_id)
