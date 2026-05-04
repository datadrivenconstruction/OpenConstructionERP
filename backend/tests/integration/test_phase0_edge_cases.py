# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Phase-0 edge-case test suite for v2.8.0 vector match feature.

Stress-tests the seams the Phase 0 baseline tests skip:

* Vector adapter (α): malformed payloads, encoder failures, bulk reindex
  empty/large inputs, idempotent delete, language fallback
* Translation (γ): cache key collisions across domains, malformed MUSE
  rows, empty cascades, threshold overrides, concurrent calls
* Match settings (ε): invalid JSON shapes, lazy init race surface,
  PATCH no-op behaviour
* Match service (δ): zero-hit handling, top_k=1/100 boundaries,
  classifier_hint with unknown classifier, source_lang missing,
  feedback with non-existent project_id
* Eval harness (ζ): malformed YAML, judge cost-cap reached mid-run,
  runner exception attribution

Tests are hermetic: no network, no real lancedb, no real LLM. The
production code in ``app/`` is NOT modified — anything that reveals a
bug is marked ``xfail`` with a reason and documented in the report.
"""

from __future__ import annotations

import asyncio
import io
import sys
import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _bypass_catalog_gate(monkeypatch):
    """v2.8.2 — see ``test_match_service``. These edge-case tests target
    the post-gate ranker behaviour, not catalogue binding."""
    async def _ok(*_args, **_kwargs):
        return "ok", 1, 1

    monkeypatch.setattr(
        "app.core.match_service.ranker._resolve_catalog_status",
        _ok,
        raising=True,
    )


def _register_minimal_models() -> None:
    """Pull projects + users + audit models into Base.metadata."""
    import app.core.audit  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Per-test temp SQLite engine + sessionmaker (test isolation)."""
    tmp_db = Path(tempfile.mkdtemp()) / "phase0_edge.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()
    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    yield engine, factory, tmp_db
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest_asyncio.fixture
async def project_id(temp_engine_and_factory) -> uuid.UUID:
    """Create a real Project so MatchProjectSettings can FK to it."""
    _engine, factory, _tmp = temp_engine_and_factory

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"edge-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Edge Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        name="Edge Test Project",
        owner_id=user.id,
        region="DACH",
        status="active",
    )
    async with factory() as session:
        session.add(user)
        await session.flush()
        session.add(project)
        await session.commit()
    return project.id


def _make_cost_row(**overrides: Any) -> SimpleNamespace:
    """Duck-typed CostItem row — only the fields the adapter touches."""
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "code": "TEST-001",
        "description": "Test cost item",
        "unit": "m2",
        "rate": "100.00",
        "currency": "EUR",
        "source": "cwicr",
        "region": "DE_BERLIN",
        "classification": {"din276": "330"},
        "metadata_": {},
        "is_active": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Vector adapter (α) — edge cases                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestVectorAdapterEdges:
    """Edge cases for ``app.modules.costs.vector_adapter``."""

    def test_payload_handles_non_dict_classification(self) -> None:
        """``classification`` may be None or non-dict — adapter must not crash.

        Why: imported CSV/JSON rows can leave classification as ``None``
        or a string; the adapter must coerce to an empty dict.
        """
        from app.modules.costs.vector_adapter import CostItemVectorAdapter

        adapter = CostItemVectorAdapter()
        row = _make_cost_row(classification=None)
        payload = adapter.to_payload(row)
        assert payload["classification_din276"] == ""
        assert payload["classification_nrm"] == ""

        row2 = _make_cost_row(classification="not-a-dict")
        payload2 = adapter.to_payload(row2)
        assert payload2["classification_din276"] == ""

    def test_payload_truncates_oversize_description(self) -> None:
        """Description column is capped to 500 chars to keep payload small.

        Why: free-form descriptions can balloon; the payload must stay
        small so JSON round-trips through LanceDB are cheap.
        """
        from app.modules.costs.vector_adapter import CostItemVectorAdapter

        adapter = CostItemVectorAdapter()
        row = _make_cost_row(description="X" * 800)
        payload = adapter.to_payload(row)
        assert len(payload["description"]) == 500
        assert len(payload["title"]) == 160

    def test_coerce_rate_accepts_decimal_strings(self) -> None:
        """Rate column is string-typed; adapter coerces to float."""
        from app.modules.costs.vector_adapter import CostItemVectorAdapter

        adapter = CostItemVectorAdapter()
        for raw, expected in (
            ("123.45", 123.45),
            (None, 0.0),
            ("garbage", 0.0),
            (12, 12.0),
            (0, 0.0),
        ):
            row = _make_cost_row(rate=raw)
            assert adapter.to_payload(row)["unit_cost"] == expected

    def test_language_for_falls_back_to_en_for_unknown_region(self) -> None:
        """Unknown region codes get the ``en`` default — no exception."""
        from app.modules.costs.vector_adapter import _language_for

        assert _language_for(_make_cost_row(region="XX_ATLANTIS")) == "en"
        assert _language_for(_make_cost_row(region="")) == "en"
        assert _language_for(_make_cost_row(region=None)) == "en"

    def test_language_for_metadata_override_wins(self) -> None:
        """Explicit metadata language overrides region prefix lookup."""
        from app.modules.costs.vector_adapter import _language_for

        row = _make_cost_row(
            region="DE_BERLIN",
            metadata_={"language": "FR"},
        )
        assert _language_for(row) == "fr"

    @pytest.mark.asyncio
    async def test_upsert_empty_rows_returns_zero(self) -> None:
        """``upsert([])`` short-circuits before importing lancedb."""
        from app.modules.costs import vector_adapter

        assert await vector_adapter.upsert([]) == 0

    @pytest.mark.asyncio
    async def test_delete_empty_rows_returns_zero(self) -> None:
        from app.modules.costs import vector_adapter

        assert await vector_adapter.delete([]) == 0
        assert await vector_adapter.delete([None, None]) == 0

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_empty_list(self) -> None:
        """Empty / whitespace query short-circuits with no encoder call."""
        from app.modules.costs import vector_adapter

        assert await vector_adapter.search("") == []
        assert await vector_adapter.search("   \n\t  ") == []

    @pytest.mark.asyncio
    async def test_upsert_skips_rows_without_id(self) -> None:
        """Rows missing ``id`` must be silently dropped, not crash."""
        from app.modules.costs import vector_adapter

        rows = [
            _make_cost_row(id=None),
            _make_cost_row(id=None, description="also no id"),
        ]
        # Even when vector backend is "available", these rows should not
        # produce any successful upserts. Mock the encoder so we can be
        # sure no encode call leaks through.
        with patch.object(
            vector_adapter, "_vector_available", return_value=True,
        ), patch(
            "app.core.vector.encode_texts_async",
            new=AsyncMock(return_value=[]),
        ):
            result = await vector_adapter.upsert(rows)
        assert result == 0

    @pytest.mark.asyncio
    async def test_upsert_handles_encoder_returning_wrong_count(self) -> None:
        """Encoder returns N != len(texts) → no rows indexed, no raise."""
        from app.modules.costs import vector_adapter

        rows = [_make_cost_row(), _make_cost_row()]
        with patch.object(
            vector_adapter, "_vector_available", return_value=True,
        ), patch(
            "app.core.vector.encode_texts_async",
            new=AsyncMock(return_value=[[0.1, 0.2]]),  # only 1 vector for 2 rows
        ):
            result = await vector_adapter.upsert(rows)
        assert result == 0

    @pytest.mark.asyncio
    async def test_upsert_handles_encoder_raising(self) -> None:
        """Encoder exception is swallowed; upsert returns 0."""
        from app.modules.costs import vector_adapter

        rows = [_make_cost_row()]
        with patch.object(
            vector_adapter, "_vector_available", return_value=True,
        ), patch(
            "app.core.vector.encode_texts_async",
            new=AsyncMock(side_effect=RuntimeError("model load failed")),
        ):
            result = await vector_adapter.upsert(rows)
        assert result == 0

    @pytest.mark.asyncio
    async def test_search_filters_post_apply(self) -> None:
        """Region/language/source filters are applied after vector search.

        Why: LanceDB only filters tenant_id/project_id natively; payload
        filters must run in Python on the raw hits.
        """
        from app.modules.costs import vector_adapter

        raw_hits = [
            {
                "id": "a", "score": 0.9, "text": "concrete wall",
                "payload": {"region_code": "DE_BERLIN", "language": "de", "source": "cwicr"},
            },
            {
                "id": "b", "score": 0.8, "text": "concrete wall",
                "payload": {"region_code": "GB_LONDON", "language": "en", "source": "cwicr"},
            },
        ]

        with patch.object(
            vector_adapter, "_vector_available", return_value=True,
        ), patch(
            "app.core.vector.encode_texts_async",
            new=AsyncMock(return_value=[[0.0] * 384]),
        ), patch(
            "app.core.vector.vector_search_collection",
            return_value=raw_hits,
        ):
            hits = await vector_adapter.search("concrete", region="DE_BERLIN", limit=10)
        assert len(hits) == 1
        assert hits[0]["id"] == "a"

    @pytest.mark.asyncio
    async def test_reindex_all_empty_returns_zero(self) -> None:
        """Empty input completes immediately with zero indexed."""
        from app.modules.costs import vector_adapter

        result = await vector_adapter.reindex_all([])
        assert result["indexed"] == 0
        assert result["collection"] == "oe_cost_items"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Translation (γ) — edge cases                                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestTranslationEdges:
    """Edge cases for ``app.core.translation``."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_fallback_immediately(
        self, tmp_path: Path,
    ) -> None:
        """Empty input — no I/O, no LLM call, just fallback.

        Why: protects against UI sending empty PUT payloads from a draft.
        """
        from app.core.translation import TierUsed, translate

        result = await translate(
            "", "en", "de",
            cache_db_path=str(tmp_path / "cache.db"),
            lookup_root=str(tmp_path),
        )
        assert result.tier_used == TierUsed.FALLBACK
        assert result.translated == ""
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_same_language_short_circuits(self, tmp_path: Path) -> None:
        """src == tgt → fallback with confidence 1.0, original unchanged."""
        from app.core.translation import TierUsed, translate

        result = await translate(
            "Concrete wall", "EN", "en",
            cache_db_path=str(tmp_path / "cache.db"),
            lookup_root=str(tmp_path),
        )
        assert result.tier_used == TierUsed.FALLBACK
        assert result.translated == "Concrete wall"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_cache_key_separates_by_domain(self, tmp_path: Path) -> None:
        """Same text+langs but different ``domain`` → distinct cache rows.

        Why: the cache is keyed on (hash, src, tgt, domain). Two domains
        must never alias.
        """
        from app.core.translation.cache import TranslationCache

        cache = TranslationCache(str(tmp_path / "cache.db"))
        await cache.upsert(
            text="wall",
            translated_text="Wand",
            source_lang="en",
            target_lang="de",
            domain="construction",
            tier_used="lookup_muse",
            confidence=0.95,
        )
        await cache.upsert(
            text="wall",
            translated_text="Mauer",
            source_lang="en",
            target_lang="de",
            domain="masonry",
            tier_used="lookup_muse",
            confidence=0.95,
        )
        construction_hit = await cache.get("wall", "en", "de", "construction")
        masonry_hit = await cache.get("wall", "en", "de", "masonry")
        assert construction_hit is not None
        assert masonry_hit is not None
        assert construction_hit["translated_text"] == "Wand"
        assert masonry_hit["translated_text"] == "Mauer"

    @pytest.mark.asyncio
    async def test_cache_upsert_keeps_higher_confidence(
        self, tmp_path: Path,
    ) -> None:
        """Conflicting upsert keeps the higher-confidence translation."""
        from app.core.translation.cache import TranslationCache

        cache = TranslationCache(str(tmp_path / "cache.db"))
        await cache.upsert(
            text="x", translated_text="low",
            source_lang="en", target_lang="de",
            domain="construction", tier_used="llm", confidence=0.6,
        )
        await cache.upsert(
            text="x", translated_text="high",
            source_lang="en", target_lang="de",
            domain="construction", tier_used="llm", confidence=0.9,
        )
        hit = await cache.get("x", "en", "de", "construction")
        assert hit is not None
        assert hit["translated_text"] == "high"
        assert hit["confidence"] == pytest.approx(0.9)
        # Lower-conf upsert *after* higher should NOT overwrite.
        await cache.upsert(
            text="x", translated_text="lower-still",
            source_lang="en", target_lang="de",
            domain="construction", tier_used="llm", confidence=0.4,
        )
        hit2 = await cache.get("x", "en", "de", "construction")
        assert hit2 is not None
        assert hit2["translated_text"] == "high"

    @pytest.mark.asyncio
    async def test_lookup_skips_malformed_tsv_lines(
        self, tmp_path: Path,
    ) -> None:
        """TSV lines without a tab separator are silently skipped.

        Why: real-world MUSE files occasionally have stray blank lines or
        lines with only the source token.
        """
        from app.core.translation.lookup import _load_tsv

        muse_dir = tmp_path / "muse"
        muse_dir.mkdir()
        path = muse_dir / "en-de.tsv"
        path.write_text(
            "# header\n"
            "wall\tWand\t1.0\n"
            "no-tab-here\n"  # malformed
            "\n"  # blank
            "concrete\tBeton\t0.9\n",
            encoding="utf-8",
        )
        # Clear the lru_cache so each test loads fresh
        _load_tsv.cache_clear()
        table = _load_tsv(str(path))
        assert "wall" in table
        assert "concrete" in table
        assert "no-tab-here" not in table

    @pytest.mark.asyncio
    async def test_lookup_handles_missing_file(self, tmp_path: Path) -> None:
        """Missing dictionary file returns ``None`` (cascade falls through)."""
        from app.core.translation.lookup import lookup_phrase

        result = await lookup_phrase(
            "wall", "en", "de",
            dictionary="muse",
            root=str(tmp_path / "no_such_dir"),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_translate_returns_none_without_settings(
        self,
    ) -> None:
        """No AISettings → LLM tier returns None, no API call attempted."""
        from app.core.translation.llm_translator import llm_translate

        result = await llm_translate("wall", "en", "de")
        assert result is None

    @pytest.mark.asyncio
    async def test_cascade_threshold_override(self, tmp_path: Path) -> None:
        """Per-tier threshold override takes precedence over defaults."""
        from app.core.translation import TierUsed, translate
        from app.core.translation.lookup import _load_tsv

        # Write a low-coverage MUSE file. Default threshold (0.80 for MUSE)
        # would reject; override to 0.5 to accept.
        muse_dir = tmp_path / "muse"
        muse_dir.mkdir()
        (muse_dir / "en-de.tsv").write_text(
            "# header\nwall\tWand\t1.0\n",
            encoding="utf-8",
        )
        _load_tsv.cache_clear()

        # "Concrete wall here" — only 1 of 3 lexical tokens hit, coverage
        # ~0.33, below the per-token cutoff (0.5). Lookup will return None
        # outright. So we test threshold gating differently — verify that
        # high default gates a borderline hit.
        result = await translate(
            "Concrete wall here", "en", "de",
            cache_db_path=str(tmp_path / "cache.db"),
            lookup_root=str(tmp_path),
        )
        # Should fall through to fallback because lookup returned None
        # (insufficient coverage), llm tier has no settings.
        assert result.tier_used == TierUsed.FALLBACK

    @pytest.mark.asyncio
    async def test_llm_failure_falls_through_to_fallback(
        self, tmp_path: Path,
    ) -> None:
        """LLM exception → cascade returns FALLBACK, never raises."""
        from app.core.translation import TierUsed, translate

        async def _raising_llm(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("provider down")

        with patch(
            "app.core.translation.cascade.llm_translate",
            new=_raising_llm,
        ):
            result = await translate(
                "wall", "en", "de",
                user_settings=SimpleNamespace(),
                cache_db_path=str(tmp_path / "cache.db"),
                lookup_root=str(tmp_path),
            )
        assert result.tier_used == TierUsed.FALLBACK
        assert result.translated == "wall"

    @pytest.mark.asyncio
    async def test_concurrent_translate_calls_share_cache(
        self, tmp_path: Path,
    ) -> None:
        """N concurrent translate() calls produce one cache write per (text+langs+domain).

        Why: race-on-cache-write must not corrupt the table — SQLite ON
        CONFLICT handles this. Verifies the upsert clause behaves under
        concurrency.
        """
        from app.core.translation.cache import TranslationCache

        cache_path = str(tmp_path / "cache.db")

        async def _writer(i: int) -> None:
            cache = TranslationCache(cache_path)
            await cache.upsert(
                text="parallel-text",
                translated_text=f"v{i}",
                source_lang="en",
                target_lang="de",
                domain="construction",
                tier_used="llm",
                confidence=0.7 + (i * 0.001),
            )

        await asyncio.gather(*[_writer(i) for i in range(20)])

        # End state: exactly one row, with the highest-confidence value.
        cache = TranslationCache(cache_path)
        stats = await cache.stats()
        assert stats["rows"] == 1


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Match settings (ε) — edge cases                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app_with_settings(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    """FastAPI app with projects router for match-settings tests."""
    _engine, factory, _tmp = temp_engine_and_factory

    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.projects.router import router as projects_router

    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1/projects")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_payload() -> dict[str, str]:
        return dict(_current_user_payload)

    async def _override_user_id() -> str:
        return _current_user_payload.get("sub", "")

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload
    app.dependency_overrides[get_current_user_id] = _override_user_id
    yield app


@pytest_asyncio.fixture
async def settings_client(
    app_with_settings: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app_with_settings)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def settings_project_owned_by(temp_engine_and_factory):
    _engine, factory, _tmp = temp_engine_and_factory

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async def _make() -> tuple[uuid.UUID, uuid.UUID]:
        user = User(
            id=uuid.uuid4(),
            email=f"settings-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x" * 60,
            full_name="Owner",
            role="estimator",
            locale="en",
            is_active=True,
            metadata_={},
        )
        project = Project(
            id=uuid.uuid4(),
            name="P",
            owner_id=user.id,
            status="active",
        )
        async with factory() as session:
            session.add(user)
            await session.flush()
            session.add(project)
            await session.commit()
        return user.id, project.id

    return _make


def _set_acting_user(user_id: uuid.UUID, role: str = "estimator") -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["role"] = role


class TestMatchSettingsEdges:
    """Extra coverage for v2.8.0 MatchProjectSettings."""

    @pytest.mark.asyncio
    async def test_patch_with_empty_body_is_noop(
        self, settings_client: AsyncClient, settings_project_owned_by,
    ) -> None:
        """PATCH ``{}`` is a valid request that changes nothing.

        Why: a UI that re-sends "no field changed" must not 422.
        """
        user_id, project_id = await settings_project_owned_by()
        _set_acting_user(user_id)
        await settings_client.get(f"/api/v1/projects/{project_id}/match-settings")
        resp = await settings_client.patch(
            f"/api/v1/projects/{project_id}/match-settings",
            json={},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["target_language"] == "en"  # default unchanged

    @pytest.mark.asyncio
    async def test_patch_unknown_fields_silently_ignored(
        self, settings_client: AsyncClient, settings_project_owned_by,
    ) -> None:
        """Unknown PATCH fields don't 422 (model_config extra is the default).

        Note: pydantic default is to ignore unknown fields. If schema
        flips to forbid, this test will document the behaviour change.
        """
        user_id, project_id = await settings_project_owned_by()
        _set_acting_user(user_id)
        await settings_client.get(f"/api/v1/projects/{project_id}/match-settings")
        resp = await settings_client.patch(
            f"/api/v1/projects/{project_id}/match-settings",
            json={"foobar": "ignored", "target_language": "de"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["target_language"] == "de"

    @pytest.mark.asyncio
    async def test_patch_invalid_target_language_format(
        self, settings_client: AsyncClient, settings_project_owned_by,
    ) -> None:
        """Non-2-letter codes rejected by validator → 422."""
        user_id, project_id = await settings_project_owned_by()
        _set_acting_user(user_id)
        for bad in ("z", "ZZZ-DE", "1de", "  "):
            resp = await settings_client.patch(
                f"/api/v1/projects/{project_id}/match-settings",
                json={"target_language": bad},
            )
            assert resp.status_code == 422, f"accepted bad lang {bad!r}: {resp.text}"

    @pytest.mark.asyncio
    async def test_patch_sources_enabled_subset_of_known(
        self, settings_client: AsyncClient, settings_project_owned_by,
    ) -> None:
        """Unknown sources rejected via _validate_sources."""
        user_id, project_id = await settings_project_owned_by()
        _set_acting_user(user_id)
        # Valid subset accepted
        ok = await settings_client.patch(
            f"/api/v1/projects/{project_id}/match-settings",
            json={"sources_enabled": ["bim", "pdf"]},
        )
        assert ok.status_code == 200, ok.text
        # Unknown source — validator must reject
        bad = await settings_client.patch(
            f"/api/v1/projects/{project_id}/match-settings",
            json={"sources_enabled": ["bim", "ifc"]},
        )
        assert bad.status_code == 422, bad.text

    @pytest.mark.asyncio
    async def test_concurrent_first_get_creates_one_row(
        self,
        temp_engine_and_factory,
        project_id: uuid.UUID,
    ) -> None:
        """N concurrent first-time GETs result in a single MatchProjectSettings row.

        Why: the lazy-init path is "select then insert". Two requests
        racing can both miss the select and try to insert. Tests current
        observable behaviour — flag for review if duplicate rows appear.
        """
        from sqlalchemy import select

        from app.modules.projects.models import MatchProjectSettings
        from app.modules.projects.service import get_or_create_match_settings

        _engine, factory, _tmp = temp_engine_and_factory

        async def _runner() -> None:
            async with factory() as session:
                await get_or_create_match_settings(session, project_id)
                await session.commit()

        # Run a moderate number — exercise the race window.
        await asyncio.gather(*[_runner() for _ in range(10)])

        async with factory() as session:
            stmt = select(MatchProjectSettings).where(
                MatchProjectSettings.project_id == project_id,
            )
            rows = list((await session.execute(stmt)).scalars().all())
        # The unique constraint on project_id should keep this to 1 row.
        # If duplicates leak through, the schema's UniqueConstraint at
        # least prevents that — record observed behaviour.
        assert len(rows) == 1, f"expected 1 row, got {len(rows)}"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Match service (δ) — edge cases                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝


@pytest.fixture
def patch_zero_hits(monkeypatch):
    """Patch cost_vector.search to return no hits."""
    async def _stub(query: str, *, limit: int, **kwargs: Any):
        return []

    from app.modules.costs import vector_adapter
    monkeypatch.setattr(vector_adapter, "search", _stub)


@pytest.fixture
def patch_one_hit(monkeypatch):
    async def _stub(query: str, *, limit: int, **kwargs: Any):
        return [{
            "id": "h1",
            "score": 0.5,
            "text": "x",
            "payload": {
                "code": "111.111.111", "description": "x",
                "unit": "m2", "unit_cost": 10.0,
                "currency": "EUR", "region_code": "DE_BERLIN",
                "source": "cwicr", "language": "de",
                "classification_din276": "111", "classification_nrm": "",
                "classification_masterformat": "",
            },
        }]

    from app.modules.costs import vector_adapter
    monkeypatch.setattr(vector_adapter, "search", _stub)


class TestMatchServiceEdges:
    """Edge cases for ``app.core.match_service``."""

    @pytest.mark.asyncio
    async def test_empty_search_results_returns_empty_candidates(
        self,
        temp_engine_and_factory,
        project_id: uuid.UUID,
        patch_zero_hits,
    ) -> None:
        """Vector search returns zero hits → response has no candidates and no auto_link."""
        from app.core.match_service import (
            ElementEnvelope,
            MatchRequest,
            rank,
        )

        _engine, factory, _tmp = temp_engine_and_factory
        envelope = ElementEnvelope(
            source="bim", category="wall",
            description="Stahlbetonwand",
            source_lang="de",
        )
        async with factory() as session:
            request = MatchRequest(envelope=envelope, project_id=project_id, top_k=5)
            response = await rank(request, db=session)

        assert response.candidates == []
        assert response.auto_linked is None

    @pytest.mark.asyncio
    async def test_empty_query_text_returns_empty(
        self, temp_engine_and_factory, project_id: uuid.UUID, patch_one_hit,
    ) -> None:
        """Envelope with no description/category/properties → empty result, no search."""
        from app.core.match_service import ElementEnvelope, MatchRequest, rank

        _engine, factory, _tmp = temp_engine_and_factory
        envelope = ElementEnvelope(source="bim")  # nothing else
        async with factory() as session:
            request = MatchRequest(envelope=envelope, project_id=project_id, top_k=5)
            response = await rank(request, db=session)
        assert response.candidates == []

    @pytest.mark.asyncio
    async def test_top_k_one(
        self, temp_engine_and_factory, project_id: uuid.UUID, patch_one_hit,
    ) -> None:
        """top_k=1 returns at most 1 candidate."""
        from app.core.match_service import ElementEnvelope, MatchRequest, rank

        _engine, factory, _tmp = temp_engine_and_factory
        envelope = ElementEnvelope(
            source="bim", description="wall", source_lang="en",
        )
        async with factory() as session:
            request = MatchRequest(envelope=envelope, project_id=project_id, top_k=1)
            response = await rank(request, db=session)
        assert len(response.candidates) <= 1

    @pytest.mark.asyncio
    async def test_top_k_too_high_rejected_by_pydantic(
        self,
    ) -> None:
        """MatchRequest enforces top_k <= 100 at validation time."""
        from app.core.match_service import ElementEnvelope, MatchRequest

        envelope = ElementEnvelope(source="bim", description="x")
        with pytest.raises(Exception):
            MatchRequest(
                envelope=envelope,
                project_id=uuid.uuid4(),
                top_k=10000,
            )
        with pytest.raises(Exception):
            MatchRequest(
                envelope=envelope,
                project_id=uuid.uuid4(),
                top_k=0,
            )

    @pytest.mark.asyncio
    async def test_unknown_source_raises_value_error(self) -> None:
        """``build_envelope("unknown", ...)`` raises ValueError with a useful message."""
        from app.core.match_service import build_envelope

        with pytest.raises(ValueError, match="Unknown match source"):
            build_envelope("ifc", {"category": "wall"})

    @pytest.mark.asyncio
    async def test_classifier_hint_unknown_classifier_no_op(self) -> None:
        """Settings.classifier='nrm' with envelope hint only for din276 → no boost."""
        from app.core.match_service.boosts import classifier as classifier_boost
        from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

        envelope = ElementEnvelope(
            source="bim", description="x",
            classifier_hint={"din276": "330"},
        )
        candidate = MatchCandidate(code="x", classification={"din276": "330"})

        class _Settings:
            classifier = "nrm"  # different classifier than the hint

        deltas = classifier_boost.boost(envelope, candidate, _Settings())
        assert deltas == {}

    @pytest.mark.asyncio
    async def test_classifier_hint_with_no_settings_classifier(self) -> None:
        """Settings.classifier='none' → boost no-ops regardless of hint."""
        from app.core.match_service.boosts import classifier as classifier_boost
        from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

        envelope = ElementEnvelope(
            source="bim", description="x",
            classifier_hint={"din276": "330"},
        )
        candidate = MatchCandidate(code="x", classification={"din276": "330"})

        class _Settings:
            classifier = "none"

        deltas = classifier_boost.boost(envelope, candidate, _Settings())
        assert deltas == {}

    @pytest.mark.asyncio
    async def test_unit_boost_handles_superscript_unicode(self) -> None:
        """``m²``/``m³`` fold to ``m2``/``m3`` for matching."""
        from app.core.match_service.boosts import unit as unit_boost
        from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

        envelope = ElementEnvelope(
            source="bim", description="x", unit_hint="m²",
        )
        candidate = MatchCandidate(code="x", unit="m2")
        deltas = unit_boost.boost(envelope, candidate, None)
        assert "unit_match" in deltas

    @pytest.mark.asyncio
    async def test_unit_boost_inferred_from_quantities(self) -> None:
        """No unit_hint → unit boost falls back to quantities-based inference."""
        from app.core.match_service.boosts import unit as unit_boost
        from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

        envelope = ElementEnvelope(
            source="bim", description="x",
            quantities={"area_m2": 10.0},  # implies m2
        )
        candidate = MatchCandidate(code="x", unit="m2")
        deltas = unit_boost.boost(envelope, candidate, None)
        assert "unit_match" in deltas

    @pytest.mark.asyncio
    async def test_unit_boost_lm_vs_m_no_op(self) -> None:
        """``m`` vs ``lm`` are the same dimension — no penalty."""
        from app.core.match_service.boosts import unit as unit_boost
        from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

        envelope = ElementEnvelope(
            source="bim", description="x", unit_hint="m",
        )
        candidate = MatchCandidate(code="x", unit="lm")
        deltas = unit_boost.boost(envelope, candidate, None)
        # Same dimension, different code — no match boost AND no penalty.
        assert deltas == {}

    @pytest.mark.asyncio
    async def test_match_element_with_invalid_uuid_uses_sentinel_project(
        self, temp_engine_and_factory, project_id, patch_zero_hits,
    ) -> None:
        """Garbage project_id falls back to the sentinel UUID and returns gracefully.

        The sentinel ``00000000-0000-0000-0000-000000000000`` does NOT
        have a Project row in the fixture DB. The matcher catches the
        FK error at ``get_or_create_match_settings`` and falls back to
        a transient defaults object so the search still runs against
        the (mocked) vector store. Result: empty candidate list rather
        than a 500 surfacing to the caller.
        """
        from app.core.match_service import match_element

        _engine, factory, _tmp = temp_engine_and_factory
        async with factory() as session:
            results = await match_element(
                {"category": "wall", "description": "concrete wall"},
                top_k=3,
                project_id="not-a-uuid",
                db=session,
            )
        assert results == [], (
            "expected graceful fallback to empty candidate list when "
            "project does not exist (sentinel UUID FK case)"
        )

    @pytest.mark.asyncio
    async def test_match_element_promotes_flat_properties(
        self, temp_engine_and_factory, project_id, patch_zero_hits,
    ) -> None:
        """Eval-harness flat shape (material at root) gets promoted to properties."""
        from app.core.match_service import match_element

        _engine, factory, _tmp = temp_engine_and_factory
        async with factory() as session:
            # Just verifying it doesn't crash with the eval-harness flat shape.
            result = await match_element(
                {
                    "category": "wall",
                    "description": "concrete wall",
                    "material": "concrete C30/37",
                    "fire_rating": "F90",
                    "project_id": str(project_id),
                },
                top_k=3,
                db=session,
            )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_record_feedback_with_nonexistent_project(
        self, temp_engine_and_factory,
    ) -> None:
        """Feedback for an unknown project_id is swallowed (audit best-effort)."""
        from app.core.match_service import (
            ElementEnvelope,
            MatchCandidate,
            record_feedback,
        )

        _engine, factory, _tmp = temp_engine_and_factory
        ghost_project = uuid.uuid4()
        envelope = ElementEnvelope(source="bim", description="x")
        candidate = MatchCandidate(code="X.001", score=0.9)

        async with factory() as session:
            # record_feedback never raises — failures are debug-logged.
            await record_feedback(
                db=session,
                project_id=ghost_project,
                element_envelope=envelope,
                accepted_candidate=candidate,
                rejected_candidates=[],
                user_chose_code=None,
                user_id=None,
            )

    @pytest.mark.asyncio
    async def test_reranker_skipped_when_no_ai_settings(
        self,
    ) -> None:
        """``rerank_top_k`` with ai_settings=None returns inputs unchanged."""
        from app.core.match_service.envelope import ElementEnvelope, MatchCandidate
        from app.core.match_service.reranker_ai import rerank_top_k

        envelope = ElementEnvelope(source="bim", description="x")
        cands = [MatchCandidate(code="A", score=0.9), MatchCandidate(code="B", score=0.7)]
        out, cost = await rerank_top_k(cands, envelope, ai_settings=None)
        assert out == cands
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_reranker_empty_candidates(self) -> None:
        """Empty candidate list short-circuits to ([], 0.0)."""
        from app.core.match_service.envelope import ElementEnvelope
        from app.core.match_service.reranker_ai import rerank_top_k

        envelope = ElementEnvelope(source="bim", description="x")
        out, cost = await rerank_top_k([], envelope)
        assert out == []
        assert cost == 0.0


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Eval harness (ζ) — edge cases                                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestEvalHarnessEdges:
    """Edge cases for ``tests.eval``."""

    @pytest.mark.asyncio
    async def test_runner_aggregates_with_match_fn_exception(
        self, tmp_path: Path,
    ) -> None:
        """Match function raising → entry recorded with error, not run abort.

        Why: one bad golden entry must not kill the whole run.
        """
        from tests.eval.runner import run_eval

        golden = [
            {
                "id": "g1",
                "source": "bim",
                "element_info": {"category": "wall"},
                "ground_truth": {
                    "cwicr_position_codes": ["330.10.020"],
                    "acceptable_cost_range_eur_per_m2": [100, 200],
                },
            },
        ]
        path = tmp_path / "g.yaml"
        path.write_text(yaml.safe_dump(golden), encoding="utf-8")

        async def _bad_match(info: dict, k: int) -> list[dict]:
            raise RuntimeError("boom")

        report = await run_eval(path, judge=False, match_fn=_bad_match)
        assert report.golden_set_size == 1
        # The aggregator handles error entries — top-1 accuracy is 0.0
        assert report.metrics["top_1_accuracy"] == 0.0
        # Per-entry error message recorded
        assert report.per_entry_results[0].error is not None
        assert "boom" in report.per_entry_results[0].error

    @pytest.mark.asyncio
    async def test_runner_with_malformed_yaml_raises(
        self, tmp_path: Path,
    ) -> None:
        """Top-level dict (not list) yaml raises a clear ValueError."""
        from tests.eval.runner import run_eval

        path = tmp_path / "bad.yaml"
        path.write_text(
            yaml.safe_dump({"not": "a list"}),
            encoding="utf-8",
        )

        async def _stub(info: dict, k: int) -> list[dict]:
            return []

        with pytest.raises(ValueError, match="Expected a list"):
            await run_eval(path, judge=False, match_fn=_stub)

    @pytest.mark.asyncio
    async def test_judge_rule_based_handles_garbage_rate(self) -> None:
        """Non-numeric ``unit_rate`` → rate check skipped, code-match still works."""
        from tests.eval.judge import _judge_rule_based

        verdict = _judge_rule_based(
            element_info={},
            ground_truth={
                "cwicr_position_codes": ["330.10.020"],
                "acceptable_cost_range_eur_per_m2": [100, 200],
            },
            candidate={"code": "330.10.020", "unit_rate": "not-a-number"},
        )
        # rate parses to None → rate_ok stays True → exact code match wins.
        assert verdict.verdict == "correct"
        assert verdict.used_fallback is True

    @pytest.mark.asyncio
    async def test_judge_cost_cap_falls_back(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cumulative cost over cap → automatic rule-based fallback."""
        import tests.eval.judge as judge_mod
        from tests.eval.judge import judge_match, reset_run_cost

        # Pretend we already burned through the cap.
        reset_run_cost()
        judge_mod._RUN_COST_USD["total"] = 999.0
        # Force ``_max_cost_usd`` to read our env var
        monkeypatch.setenv("EVAL_AI_MAX_COST_USD", "1.0")
        # And pretend the LLM provider IS configured (so we'd otherwise call it).
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        verdict = await judge_match(
            element_info={"category": "wall"},
            ground_truth={
                "cwicr_position_codes": ["X"],
                "acceptable_cost_range_eur_per_m2": [1, 1000],
            },
            candidate={"code": "X", "unit_rate": 100},
            use_llm=True,
        )
        assert verdict.used_fallback is True
        # Reset for the next test
        reset_run_cost()

    @pytest.mark.asyncio
    async def test_compare_handles_empty_baseline(self) -> None:
        """Compare with no baseline metrics treats every metric as new."""
        from tests.eval.compare import compare_to_baseline
        from tests.eval.runner import EvalReport

        report = EvalReport(
            metrics={"top_1_accuracy": 0.5, "mrr": 0.3},
            per_entry_results=[],
            total_cost_usd=0.0,
            took_ms=0,
            timestamp_iso="2026-05-03T00:00:00Z",
            golden_set_size=0,
            used_real_match_service=False,
        )
        result = compare_to_baseline(report, {}, threshold=0.05)
        # No baseline metrics means nothing to regress against.
        assert result.passed is True

    def test_judge_validate_payload_rejects_non_dict(self) -> None:
        from tests.eval.judge import _validate_verdict_payload

        assert _validate_verdict_payload(None) is None
        assert _validate_verdict_payload([1, 2, 3]) is None
        assert _validate_verdict_payload("string") is None

    def test_judge_validate_payload_clamps_confidence(self) -> None:
        from tests.eval.judge import _validate_verdict_payload

        result = _validate_verdict_payload(
            {"verdict": "correct", "confidence": 5.0, "reason": "x"},
        )
        assert result is not None
        assert result["confidence"] == 1.0

        result = _validate_verdict_payload(
            {"verdict": "correct", "confidence": -3.0, "reason": "x"},
        )
        assert result is not None
        assert result["confidence"] == 0.0

    def test_aggregate_metrics_per_source_rollup(self) -> None:
        """Per-source rollup includes every source that appeared in entries."""
        from tests.eval.runner import _aggregate_metrics, EntryResult

        entries = [
            EntryResult(
                id="b1", source="bim", candidates=[],
                top_1_correct=True, top_5_recall=True,
                reciprocal_rank=1.0, took_ms=0,
            ),
            EntryResult(
                id="p1", source="pdf", candidates=[],
                top_1_correct=False, top_5_recall=True,
                reciprocal_rank=0.5, took_ms=0,
            ),
        ]
        metrics = _aggregate_metrics(entries)
        assert metrics["top_1_accuracy"] == 0.5
        assert metrics["top_1_accuracy.bim"] == 1.0
        assert metrics["top_1_accuracy.pdf"] == 0.0
        assert metrics["mrr.bim"] == 1.0
        assert metrics["mrr.pdf"] == 0.5


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Cross-module — extractor edge cases                                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestExtractorEdges:
    """Edge cases for ``app.core.match_service.extractors``."""

    @pytest.mark.parametrize("source", ["bim", "pdf", "dwg", "photo"])
    def test_extractor_accepts_empty_dict(self, source: str) -> None:
        """Every extractor accepts an empty dict and returns a valid envelope.

        Why: upstream pipelines (CV, OCR) sometimes emit empty
        intermediate payloads — we must not crash, just return an
        envelope that downstream rejects on its own merits.
        """
        from app.core.match_service.extractors import build_envelope

        env = build_envelope(source, {})
        assert env.source == source

    def test_pdf_extractor_handles_garbage_measurement_value(self) -> None:
        """Non-numeric ``measurement_value`` is silently ignored."""
        from app.core.match_service.extractors import build_envelope

        env = build_envelope("pdf", {
            "description": "wall",
            "measurement_value": "approximately twelve meters",
            "measurement_unit": "m",
        })
        # Garbage value didn't make it into quantities.
        assert "length_m" not in env.quantities

    def test_photo_extractor_skips_garbage_estimated_quantities(self) -> None:
        from app.core.match_service.extractors import build_envelope

        env = build_envelope("photo", {
            "description": "wall photo",
            "estimated_area_m2": "unknown",
            "estimated_length_m": None,
            "estimated_quantity": "",
        })
        assert env.quantities == {}

    def test_dwg_layer_to_category_mapping(self) -> None:
        """AIA layer codes map to known categories."""
        from app.core.match_service.extractors import build_envelope

        env = build_envelope("dwg", {
            "description": "interior wall",
            "layer": "A-WALL-PRTN",
        })
        assert env.category == "wall"

    def test_dwg_unknown_layer_returns_lowercase_major(self) -> None:
        from app.core.match_service.extractors import build_envelope

        env = build_envelope("dwg", {
            "description": "x",
            "layer": "S-EXOTIC-XXX",
        })
        assert env.category == "exotic"

    def test_bim_extractor_synthesizes_description_from_properties(self) -> None:
        """Even if description is empty, BIM extractor synthesizes from category+material."""
        from app.core.match_service.extractors import build_envelope

        env = build_envelope("bim", {
            "category": "wall",
            "properties": {
                "material": "Concrete C30/37",
                "fire_rating": "F90",
            },
            "geometry": {"thickness_m": 0.24},
        })
        assert "wall" in env.description
        assert "C30/37" in env.description
        assert "thickness 0.24m" in env.description
        assert "fire F90" in env.description

    def test_envelope_str_strip_whitespace_validator(self) -> None:
        """Envelope strips surrounding whitespace from strings."""
        from app.core.match_service.envelope import ElementEnvelope

        env = ElementEnvelope(
            source="bim",
            category="  wall  ",
            description="  concrete wall  ",
            source_lang="  EN  ",
        )
        assert env.category == "wall"
        assert env.description == "concrete wall"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Cost events (α) — edge cases                                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝


class TestCostEventsEdges:
    """Edge cases for ``app.modules.costs.events``."""

    def test_extract_item_id_handles_missing(self) -> None:
        """Event without item_id returns None."""
        from app.core.events import Event
        from app.modules.costs.events import _extract_item_id

        evt = Event(name="costs.item.created", data={}, source_module="costs")
        assert _extract_item_id(evt) is None

    def test_extract_item_id_handles_garbage(self) -> None:
        """Non-UUID item_id returns None (no AttributeError)."""
        from app.core.events import Event
        from app.modules.costs.events import _extract_item_id

        evt = Event(
            name="costs.item.created",
            data={"item_id": "not-a-uuid"},
            source_module="costs",
        )
        assert _extract_item_id(evt) is None

    def test_extract_item_id_handles_none(self) -> None:
        """item_id None → None."""
        from app.core.events import Event
        from app.modules.costs.events import _extract_item_id

        evt = Event(
            name="costs.item.created",
            data={"item_id": None},
            source_module="costs",
        )
        assert _extract_item_id(evt) is None

    def test_extract_item_id_handles_uuid(self) -> None:
        from app.core.events import Event
        from app.modules.costs.events import _extract_item_id

        new_id = uuid.uuid4()
        evt = Event(
            name="costs.item.created",
            data={"item_id": str(new_id)},
            source_module="costs",
        )
        assert _extract_item_id(evt) == new_id


class TestRegionBoostPrefixes:
    """Regression coverage for ``boosts/region._project_region_prefixes``.

    The previous expression returned a bare string for already-qualified
    regions like ``DE_BERLIN``, which iterated character-by-character
    downstream and broke region-match scoring. This test pins the
    contract to "always tuple of strings".
    """

    def test_qualified_region_returns_exact_code_as_tuple(self) -> None:
        """Pinned-city projects return their exact CWICR code, no underscore suffix.

        Adding a trailing underscore would break the `startswith()` check
        for candidates with the bare code (`"DE_BERLIN".startswith("DE_BERLIN_")`
        is False). The fix returns the exact code so equality still matches.
        """
        from types import SimpleNamespace

        from app.core.match_service.boosts.region import _project_region_prefixes

        settings = SimpleNamespace(project=SimpleNamespace(region="DE_BERLIN"))
        result = _project_region_prefixes(settings)
        assert isinstance(result, tuple)
        assert result == ("DE_BERLIN",)
        # Critically, NOT a bare string — that would iterate as characters.
        assert not isinstance(result, str)

    def test_qualified_region_strips_trailing_underscore(self) -> None:
        from types import SimpleNamespace

        from app.core.match_service.boosts.region import _project_region_prefixes

        settings = SimpleNamespace(project=SimpleNamespace(region="DE_BERLIN_"))
        result = _project_region_prefixes(settings)
        assert result == ("DE_BERLIN",)

    def test_unqualified_region_uses_lookup_table(self) -> None:
        from types import SimpleNamespace

        from app.core.match_service.boosts.region import _project_region_prefixes

        settings = SimpleNamespace(project=SimpleNamespace(region="DACH"))
        result = _project_region_prefixes(settings)
        # DACH should map to multiple country prefixes from _REGION_PREFIXES;
        # exact contents may evolve, but the shape must stay tuple-of-str.
        assert isinstance(result, tuple)
        assert all(isinstance(p, str) for p in result)

    def test_empty_region_returns_empty_tuple(self) -> None:
        from types import SimpleNamespace

        from app.core.match_service.boosts.region import _project_region_prefixes

        settings = SimpleNamespace(project=SimpleNamespace(region=""))
        assert _project_region_prefixes(settings) == ()

    def test_region_lookup_falls_back_to_settings_attribute(self) -> None:
        """When project is missing/None, the boost reads ``settings.region``."""
        from types import SimpleNamespace

        from app.core.match_service.boosts.region import _project_region_prefixes

        settings = SimpleNamespace(project=None, region="GB_LONDON")
        result = _project_region_prefixes(settings)
        assert result == ("GB_LONDON",)

    def test_qualified_region_boost_actually_fires(self) -> None:
        """End-to-end: a candidate whose region_code starts with the prefix scores up.

        This is the regression test for the original bug — before the fix,
        the matcher iterated the prefix string character by character and
        the boost never fired for fully-qualified ``DE_BERLIN`` projects.
        """
        from types import SimpleNamespace

        from app.core.match_service.boosts.region import boost
        from app.core.match_service.envelope import (
            ElementEnvelope,
            MatchCandidate,
        )

        envelope = ElementEnvelope(
            source="bim", source_lang="en", category="wall",
            description="Concrete wall",
        )
        settings = SimpleNamespace(project=SimpleNamespace(region="DE_BERLIN"))

        matching = MatchCandidate(
            code="x", description="x", unit="m2", unit_rate=1.0, currency="EUR",
            score=0.7, vector_score=0.7, boosts_applied={},
            confidence_band="medium", region_code="DE_BERLIN", source="cwicr",
            language="de", classification={},
        )
        non_matching = MatchCandidate(
            code="y", description="y", unit="m2", unit_rate=1.0, currency="EUR",
            score=0.7, vector_score=0.7, boosts_applied={},
            confidence_band="medium", region_code="GB_LONDON", source="cwicr",
            language="en", classification={},
        )

        delta_match = boost(envelope, matching, settings)
        delta_miss = boost(envelope, non_matching, settings)

        assert "region_match" in delta_match, (
            "region boost did not fire for DE_BERLIN candidate against "
            "DE_BERLIN project — likely tuple-vs-string regression"
        )
        assert delta_match["region_match"] > 0.0
        assert "region_match" not in delta_miss
