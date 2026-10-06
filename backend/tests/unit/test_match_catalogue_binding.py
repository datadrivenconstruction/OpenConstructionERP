# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Which catalogue /match-elements searches for a project, on PostgreSQL.

Covers the three ways the choice reaches the ranker and the page:

* auto-bind reads the project's region label ("Italy") as its language,
  instead of reading every label as English;
* a binding people already confirmed matches against is not switched to
  another language behind their back;
* a catalogue picked in the wizard is the one the ranker searches;
* the readiness answer names what is missing before anything is uploaded.

Qdrant is replaced by an in-memory stand-in holding the named collections.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _make_project(s: AsyncSession, *, region: str, country_code: str | None = None) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"cb-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Catalogue Binding Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    s.add(user)
    await s.flush()
    pid = uuid.uuid4()
    s.add(
        Project(
            id=pid,
            name="t",
            region=region,
            country_code=country_code,
            status="active",
            owner_id=user.id,
        )
    )
    await s.commit()
    return pid


async def _bind(s: AsyncSession, project_id: uuid.UUID, catalogue_id: str) -> None:
    from app.modules.projects.models import MatchProjectSettings

    s.add(MatchProjectSettings(project_id=project_id, cost_database_id=catalogue_id))
    await s.commit()


async def _settle_a_match(s: AsyncSession, project_id: uuid.UUID, status: str = "confirmed") -> None:
    from app.modules.match_elements.models import MatchGroup, MatchSession

    ms = MatchSession(
        project_id=project_id,
        source="text",
        group_by=["raw_text"],
        filters={},
        excluded_categories=[],
        auto_confirm_threshold="0.88",
        use_net_quantities=True,
        metadata_={},
    )
    s.add(ms)
    await s.flush()
    s.add(
        MatchGroup(
            session_id=ms.id,
            group_key="raw_text:wall",
            element_ids=[],
            element_count=1,
            quantities={},
            methods={},
            status=status,
            metadata_={},
        )
    )
    await s.commit()


def _fake_qdrant(monkeypatch: pytest.MonkeyPatch, collections: dict[str, int]) -> None:
    from app.core import vector as core_vector
    from app.modules.costs import qdrant_adapter as qa

    class _Client:
        def get_collection(self, name: str):
            if name in collections:
                return SimpleNamespace(points_count=collections[name], vectors_count=collections[name])
            raise RuntimeError(f"collection {name} not found")

        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in collections])

    monkeypatch.setattr(qa, "_get_client", lambda: _Client())
    monkeypatch.setattr(qa, "_available_cwicr_collections", lambda: frozenset(collections))
    monkeypatch.setattr(core_vector, "vector_count_with_payload_substring", lambda *a, **k: 0)


IT_AND_EN = {"cwicr_it_v3": 50_000, "cwicr_en_v3": 60_000}


async def _auto_bind(s: AsyncSession, pid: uuid.UUID) -> str | None:
    from app.modules.projects.service import auto_bind_dominant_catalogue

    return await auto_bind_dominant_catalogue(s, pid)


# ── auto-bind reads the region label ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["Italy", "IT", "IT_ROME"])
async def test_italian_project_binds_italian_catalogue(session, monkeypatch, region) -> None:
    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region=region)
    assert await _auto_bind(session, pid) == "IT"


@pytest.mark.asyncio
async def test_country_code_steers_a_group_region(session, monkeypatch) -> None:
    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Nordics", country_code="IT")
    assert await _auto_bind(session, pid) == "IT"


@pytest.mark.asyncio
async def test_keeps_existing_italian_binding(session, monkeypatch) -> None:
    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "IT_ROME")
    assert await _auto_bind(session, pid) == "IT_ROME"


@pytest.mark.asyncio
async def test_multi_language_region_is_not_steered_to_english(session, monkeypatch) -> None:
    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Nordics")
    # No language to prefer and no SQL catalogue rows: nothing is bound,
    # rather than the English collection by default.
    assert await _auto_bind(session, pid) is None


@pytest.mark.asyncio
async def test_custom_catalogue_of_unknown_language_is_kept(session, monkeypatch) -> None:
    """A catalogue id we cannot place is not "English" and is not re-bound."""
    from app.modules.costs.models import CostItem

    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="DACH")
    session.add(
        CostItem(
            code=f"CUST-{uuid.uuid4().hex[:6]}",
            description="Custom wall",
            unit="m2",
            rate="10",
            region="ACME-RATES-2026",
            is_active=True,
        )
    )
    await session.commit()
    await _bind(session, pid, "ACME-RATES-2026")
    assert await _auto_bind(session, pid) == "ACME-RATES-2026"


# ── an English binding with confirmed matches is not switched silently ──


@pytest.mark.asyncio
async def test_english_binding_switches_when_nothing_is_confirmed(session, monkeypatch) -> None:
    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "USA_USD")
    await _settle_a_match(session, pid, status="suggested")
    assert await _auto_bind(session, pid) == "IT"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["confirmed", "overridden", "applied"])
async def test_english_binding_is_kept_when_matches_are_confirmed(session, monkeypatch, status) -> None:
    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "USA_USD")
    await _settle_a_match(session, pid, status=status)
    assert await _auto_bind(session, pid) == "USA_USD"


# ── the language-mismatch probe ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_mismatch_probe_reads_region_label(session) -> None:
    from app.modules.costs.router import _detect_language_mismatch

    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "IT_ROME")
    out = await _detect_language_mismatch(session, pid)
    assert out["status"] == "ok"
    assert out["project_language"] == "it"


@pytest.mark.asyncio
async def test_mismatch_probe_flags_english_binding_on_italian_project(session) -> None:
    from app.modules.costs.router import _detect_language_mismatch

    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "USA_USD")
    out = await _detect_language_mismatch(session, pid)
    assert out["status"] == "mismatch"
    assert (out["project_language"], out["bound_language"]) == ("it", "en")


@pytest.mark.asyncio
async def test_mismatch_probe_custom_catalogue_is_unknown(session) -> None:
    from app.modules.costs.router import _detect_language_mismatch

    pid = await _make_project(session, region="DACH")
    await _bind(session, pid, "ACME-RATES-2026")
    out = await _detect_language_mismatch(session, pid)
    assert out["status"] == "unknown"
    assert out["bound_language"] == ""


@pytest.mark.asyncio
async def test_mismatch_probe_multi_language_region_is_unknown(session) -> None:
    from app.modules.costs.router import _detect_language_mismatch

    pid = await _make_project(session, region="Nordics")
    await _bind(session, pid, "IT_ROME")
    assert (await _detect_language_mismatch(session, pid))["status"] == "unknown"


# ── the wizard's pick reaches the ranker ─────────────────────────────────


async def _text_session(s: AsyncSession, pid: uuid.UUID, catalogue_id: str | None) -> uuid.UUID:
    from app.modules.match_elements import schemas
    from app.modules.match_elements.service import get_service

    created = await get_service().create_session(
        s,
        schemas.SessionCreate(
            project_id=pid,
            source="text",
            text_inputs=["Muratura in laterizio forato", "Massetto in calcestruzzo"],
            catalogue_id=catalogue_id,
        ),
    )
    await s.commit()
    return created.id


def _record_catalogue_lookups(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Record every catalogue the run and the ranker resolve.

    The stand-in reports vectors present (so the run's pre-check lets the
    groups through) but a non-ok status (so the ranker returns right after
    resolving its catalogue, without a Qdrant search).
    """
    from app.core.match_service import ranker_qdrant

    seen: list[str | None] = []

    async def _status(_db, catalog_id):
        seen.append(catalog_id)
        return "no_catalogs_loaded", 0, 5

    monkeypatch.setattr(ranker_qdrant, "_resolve_catalog_status", _status)
    return seen


@pytest.mark.asyncio
async def test_wizard_pick_reaches_the_ranker(session, monkeypatch) -> None:
    from app.modules.match_elements import schemas
    from app.modules.match_elements.service import get_service
    from app.modules.projects import service as project_service

    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Nordics")
    sid = await _text_session(session, pid, "IT_ROME")

    async def _no_auto_bind(*_a, **_k):
        raise AssertionError("auto-bind ran although the user picked a catalogue")

    monkeypatch.setattr(project_service, "auto_bind_dominant_catalogue", _no_auto_bind)
    seen = _record_catalogue_lookups(monkeypatch)

    await get_service().run_match(session, sid, schemas.RunMatchRequest(method="vector"))

    # One lookup from the run's pre-check, then one per group from the ranker.
    assert len(seen) >= 3
    assert set(seen) == {"IT_ROME"}


@pytest.mark.asyncio
async def test_auto_session_still_uses_the_project_binding(session, monkeypatch) -> None:
    from app.modules.match_elements import schemas
    from app.modules.match_elements.service import get_service

    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Italy")
    sid = await _text_session(session, pid, None)
    seen = _record_catalogue_lookups(monkeypatch)

    await get_service().run_match(session, sid, schemas.RunMatchRequest(method="vector"))

    assert len(seen) >= 3
    assert set(seen) == {"IT"}


# ── readiness: what the page says before an upload ──────────────────────


def _store(
    monkeypatch,
    *,
    mode="server",
    status="ok",
    collections=(),
    demo=False,
    embedder=True,
    location="",
    binary=False,
):
    from app.modules.match_elements import readiness

    probe = readiness.StoreProbe(mode, status, frozenset(collections), location)
    monkeypatch.setattr(readiness, "ensure_local_server", lambda: binary)
    monkeypatch.setattr(readiness, "probe_store", lambda: probe)
    monkeypatch.setattr(readiness, "demo_mode", lambda: demo)
    monkeypatch.setattr(readiness, "embedder_installed", lambda: embedder)


async def _readiness(s: AsyncSession, pid: uuid.UUID):
    from app.modules.match_elements.readiness import compute_readiness

    return await compute_readiness(s, pid)


def _codes(items) -> list[str]:
    return [i.code for i in items]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store", "blocker"),
    [
        ({"mode": "embedded", "demo": True}, "demo_mode"),
        ({"status": "client_missing"}, "search_client_missing"),
        ({"status": "unreachable"}, "search_unreachable"),
        ({"mode": "embedded"}, "search_not_configured"),
        ({"mode": "server"}, "no_catalogue_installed"),
    ],
)
async def test_readiness_blockers(session, monkeypatch, store, blocker) -> None:
    _store(monkeypatch, **store)
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert out.can_match is False
    assert _codes(out.blockers) == [blocker]
    assert out.project_language == "it"
    assert out.recommended_catalogue is not None
    assert out.recommended_catalogue.region == "IT_ROME"


@pytest.mark.asyncio
async def test_readiness_names_the_catalogue_to_install(session, monkeypatch) -> None:
    _store(monkeypatch, mode="server")
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert out.blockers[0].params == {"catalogue": "IT_ROME"}


@pytest.mark.asyncio
async def test_demo_with_catalogues_is_not_blocked(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_it_v3"}, demo=True)
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert out.can_match is True
    assert out.blockers == []


@pytest.mark.asyncio
async def test_readiness_ready_for_italian_catalogue(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_it_v3", "cwicr_en_v3"})
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert out.can_match is True
    assert out.blockers == [] and out.warnings == []
    assert out.installed_languages == ["en", "it"]
    assert out.recommended_catalogue is not None
    assert (out.recommended_catalogue.region, out.recommended_catalogue.installed) == ("IT_ROME", True)


@pytest.mark.asyncio
async def test_readiness_warns_when_only_other_languages_are_installed(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_en_v3"})
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert out.can_match is True
    assert _codes(out.warnings) == ["no_catalogue_for_language"]
    assert out.warnings[0].params == {"language": "it", "catalogue": "IT_ROME"}
    assert out.recommended_catalogue is not None
    assert out.recommended_catalogue.installed is False


@pytest.mark.asyncio
async def test_readiness_warns_without_language_model(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_it_v3"}, embedder=False)
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert out.can_match is True
    assert _codes(out.warnings) == ["embedder_missing"]


@pytest.mark.asyncio
async def test_readiness_multi_language_region(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_sv_v3"})
    pid = await _make_project(session, region="Nordics")
    out = await _readiness(session, pid)
    assert _codes(out.warnings) == ["region_language_unknown"]
    assert out.warnings[0].params == {"region": "Nordics"}
    assert out.project_language is None
    # A group still points at a catalogue from inside it; the wizard does
    # not pre-select it, because the language is the user's call.
    assert out.recommended_catalogue is not None
    assert out.recommended_catalogue.region == "SV_STOCKHOLM"


@pytest.mark.asyncio
async def test_readiness_offers_switch_when_binding_is_kept(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_it_v3", "cwicr_en_v3"})
    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "USA_USD")
    await _settle_a_match(session, pid)
    out = await _readiness(session, pid)
    assert _codes(out.warnings) == ["binding_language_differs"]
    assert out.warnings[0].params == {
        "bound": "USA_USD",
        "bound_language": "en",
        "language": "it",
        "catalogue": "IT_ROME",
    }
    assert out.bound_catalogue == "USA_USD"


@pytest.mark.asyncio
async def test_readiness_no_switch_notice_before_anything_is_confirmed(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_it_v3", "cwicr_en_v3"})
    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "USA_USD")
    out = await _readiness(session, pid)
    # Auto-bind switches this one on the next run by itself.
    assert out.warnings == []


# ── the store probe itself ───────────────────────────────────────────────


def test_probe_store_reports_unreachable_server(monkeypatch) -> None:
    from app.modules.match_elements import readiness

    class _Down:
        def get_collections(self):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(readiness, "_client_available", lambda: True)
    monkeypatch.setattr(readiness, "_probe_client", lambda **_k: _Down())
    assert readiness.probe_store().status == "unreachable"


def test_probe_store_reports_missing_client(monkeypatch) -> None:
    from app.modules.match_elements import readiness

    monkeypatch.setattr(readiness, "_client_available", lambda: False)
    assert readiness.probe_store().status == "client_missing"


def test_probe_store_lists_cwicr_collections_only(monkeypatch) -> None:
    from app.modules.match_elements import readiness

    class _Up:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in ("cwicr_it_v3", "oe_memory")])

    monkeypatch.setattr(readiness, "_client_available", lambda: True)
    monkeypatch.setattr(readiness, "_probe_client", lambda **_k: _Up())
    probe = readiness.probe_store()
    assert (probe.status, probe.collections) == ("ok", frozenset({"cwicr_it_v3"}))


# ── one card speaks: the local search server ─────────────────────────────
#
# The page used to carry a second card that probed the GENERAL Qdrant
# (``qdrant_url``) and showed "Vector database is running" while the store
# the ranker reads was empty or down. Readiness now owns the two things that
# card did: starting an installed-but-stopped native server, and offering the
# one-click install - but only where the install changes what the ranker reads.


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://localhost:6333", "http://127.0.0.1:6333/"])
async def test_readiness_offers_local_install_when_it_would_serve_the_catalogue_store(
    session, monkeypatch, url
) -> None:
    _store(monkeypatch, status="unreachable", location=url, binary=False)
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert _codes(out.blockers) == ["search_unreachable"]
    assert out.blockers[0].params == {"local_install": "available"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store", "why"),
    [
        ({"status": "unreachable", "location": "http://qdrant.internal:6333"}, "remote server"),
        ({"status": "unreachable", "location": "http://localhost:7333"}, "other port"),
        ({"status": "unreachable", "location": "http://localhost:6333", "binary": True}, "already installed"),
        ({"mode": "embedded", "status": "unreachable", "location": "/tmp/qdrant_cwicr"}, "embedded store"),
    ],
)
async def test_readiness_does_not_offer_an_install_that_changes_nothing(session, monkeypatch, store, why) -> None:
    _store(monkeypatch, **store)
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert _codes(out.blockers) == ["search_unreachable"], why
    assert out.blockers[0].params == {}, why


@pytest.mark.asyncio
async def test_readiness_starts_the_local_server_before_probing(session, monkeypatch) -> None:
    from app.modules.match_elements import readiness

    order: list[str] = []
    monkeypatch.setattr(readiness, "ensure_local_server", lambda: order.append("start") or True)
    monkeypatch.setattr(
        readiness,
        "probe_store",
        lambda: order.append("probe") or readiness.StoreProbe("server", "ok", frozenset({"cwicr_it_v3"})),
    )
    monkeypatch.setattr(readiness, "demo_mode", lambda: False)
    monkeypatch.setattr(readiness, "embedder_installed", lambda: True)
    pid = await _make_project(session, region="Italy")
    out = await _readiness(session, pid)
    assert order == ["start", "probe"]
    assert out.can_match is True


def _supervisor_spy(monkeypatch, *, binary, reachable=True, spawned=True):
    from app.core import vector
    from app.modules.match_elements import qdrant_supervisor as sup

    calls: dict[str, list] = {"ensure": [], "reset": []}

    def _ensure(url, *, spawn_if_installed=True):
        calls["ensure"].append(url)
        return SimpleNamespace(reachable=reachable, spawn_attempted=spawned)

    monkeypatch.setattr(sup, "find_qdrant_binary", lambda: binary)
    monkeypatch.setattr(sup, "ensure_qdrant_running", _ensure)
    monkeypatch.setattr(vector, "reset_qdrant_client", lambda: calls["reset"].append(True))
    return calls


def test_local_server_is_started_on_the_url_it_serves_not_qdrant_url(monkeypatch) -> None:
    from app.config import get_settings
    from app.modules.match_elements import qdrant_supervisor as sup
    from app.modules.match_elements import readiness

    monkeypatch.setattr(get_settings(), "qdrant_url", "http://general-vectors.example:6333")
    calls = _supervisor_spy(monkeypatch, binary="/opt/qdrant/qdrant")
    assert readiness.ensure_local_server() is True
    assert calls["ensure"] == [sup.LOCAL_URL]
    # A fresh spawn drops the general vector client's cached failure, as the
    # old health route did.
    assert calls["reset"] == [True]


def test_local_server_already_running_is_left_alone(monkeypatch) -> None:
    from app.modules.match_elements import readiness

    calls = _supervisor_spy(monkeypatch, binary="/opt/qdrant/qdrant", spawned=False)
    assert readiness.ensure_local_server() is True
    assert calls["reset"] == []


def test_no_local_binary_means_no_spawn(monkeypatch) -> None:
    from app.modules.match_elements import readiness

    calls = _supervisor_spy(monkeypatch, binary=None)
    assert readiness.ensure_local_server() is False
    assert calls["ensure"] == []


@pytest.mark.parametrize(
    ("url", "served"),
    [
        ("http://localhost:6333", True),
        ("http://127.0.0.1:6333/", True),
        ("http://[::1]:6333", True),
        ("http://localhost:6334", False),
        ("http://localhost", False),
        ("http://qdrant.internal:6333", False),
        ("", False),
        (None, False),
    ],
)
def test_serves_url(url, served) -> None:
    from app.modules.match_elements.qdrant_supervisor import serves_url

    assert serves_url(url) is served


def test_the_served_port_is_the_one_the_config_writes(monkeypatch, tmp_path) -> None:
    from app.modules.match_elements import qdrant_supervisor as sup

    monkeypatch.setattr(sup, "QDRANT_HOME", tmp_path)
    monkeypatch.setattr(sup, "QDRANT_STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(sup, "QDRANT_SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(sup, "QDRANT_CONFIG_DIR", tmp_path / "config")
    text = sup._write_default_config().read_text(encoding="utf-8")
    assert f"http_port: {sup.LOCAL_HTTP_PORT}\n" in text
    assert sup.serves_url(sup.LOCAL_URL)


# ── review round: countries the general table cannot place ───────────────

SV_AND_EN = {"cwicr_sv_v3": 10_000, "cwicr_en_v3": 60_000}
EN_ONLY = {"cwicr_en_v3": 60_000}


@pytest.mark.asyncio
async def test_swedish_address_under_nordics_binds_the_swedish_catalogue(session, monkeypatch) -> None:
    _fake_qdrant(monkeypatch, SV_AND_EN)
    pid = await _make_project(session, region="Nordics", country_code="SE")
    assert await _auto_bind(session, pid) == "SV_STOCKHOLM"


@pytest.mark.asyncio
@pytest.mark.parametrize(("region", "country_code"), [("INTL", "US"), ("United States", None)])
async def test_united_states_is_english(session, monkeypatch, region, country_code) -> None:
    _fake_qdrant(monkeypatch, EN_ONLY)
    pid = await _make_project(session, region=region, country_code=country_code)
    assert await _auto_bind(session, pid) == "US"


# ── a region we cannot read is said so, not guessed ──────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["INTL", "Somewhere far", ""])
async def test_readiness_says_when_the_region_tells_no_language(session, monkeypatch, region) -> None:
    _store(monkeypatch, collections={"cwicr_en_v3", "cwicr_it_v3"})
    pid = await _make_project(session, region=region)
    out = await _readiness(session, pid)
    assert out.project_language is None
    assert _codes(out.warnings) == ["region_unknown"]
    assert out.warnings[0].params == {"region": region}


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["Nordics", "SoutheastAsia", "WestAfrica"])
async def test_readiness_keeps_several_languages_for_real_groups(session, monkeypatch, region) -> None:
    _store(monkeypatch, collections={"cwicr_en_v3"})
    pid = await _make_project(session, region=region)
    out = await _readiness(session, pid)
    assert _codes(out.warnings) == ["region_language_unknown"]


@pytest.mark.asyncio
async def test_readiness_group_label_recommends_inside_the_group(session, monkeypatch) -> None:
    _store(monkeypatch, collections={"cwicr_en_v3"})
    pid = await _make_project(session, region="EastAfrica")
    out = await _readiness(session, pid)
    assert out.recommended_catalogue is not None
    assert out.recommended_catalogue.country_iso == "KE"


# ── readiness answers within its budget ──────────────────────────────────


@pytest.mark.asyncio
async def test_readiness_does_not_wait_for_a_hanging_store(session, monkeypatch) -> None:
    import time

    from app.modules.match_elements import readiness

    def _hang():
        time.sleep(2.0)
        return readiness.StoreProbe("server", "ok", frozenset({"cwicr_it_v3"}))

    monkeypatch.setattr(readiness, "ensure_local_server", lambda: False)
    monkeypatch.setattr(readiness, "probe_store", _hang)
    monkeypatch.setattr(readiness, "demo_mode", lambda: False)
    monkeypatch.setattr(readiness, "embedder_installed", lambda: True)
    monkeypatch.setattr(readiness, "PROBE_BUDGET_S", 0.3)
    pid = await _make_project(session, region="Italy")
    started = time.perf_counter()
    out = await _readiness(session, pid)
    assert time.perf_counter() - started < 1.5
    assert _codes(out.blockers) == ["search_unreachable"]
    assert out.blockers[0].params == {}


def test_store_client_is_opened_with_a_short_timeout(monkeypatch) -> None:
    from app.modules.costs import qdrant_adapter as qa
    from app.modules.match_elements import readiness

    seen: dict[str, object] = {}

    class _Up:
        def get_collections(self):
            return SimpleNamespace(collections=[])

    def _client(*, timeout=None):
        seen["timeout"] = timeout
        return _Up()

    monkeypatch.setattr(readiness, "_client_available", lambda: True)
    monkeypatch.setattr(qa, "_get_client", lambda: _Up())
    monkeypatch.setattr(readiness, "_probe_client", _client)
    readiness.probe_store()
    assert seen["timeout"] == readiness.CLIENT_TIMEOUT_S


# ── who may switch the catalogue ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_only_owner_or_admin_may_change_the_catalogue(session) -> None:
    from app.modules.match_elements.readiness import can_change_catalogue
    from app.modules.projects.models import Project

    pid = await _make_project(session, region="Italy")
    owner = str((await session.get(Project, pid)).owner_id)
    stranger = str(uuid.uuid4())
    assert await can_change_catalogue(session, pid, owner, {"role": "estimator"}) is True
    assert await can_change_catalogue(session, pid, stranger, {"role": "estimator"}) is False
    assert await can_change_catalogue(session, pid, stranger, {"role": "admin"}) is True


@pytest.mark.asyncio
async def test_choosing_auto_after_a_pick_runs_on_the_project_binding(session, monkeypatch) -> None:
    # The wizard sends "" for Auto: null means "not sent" to the PATCH and
    # would keep the earlier pick.
    from app.modules.match_elements import schemas
    from app.modules.match_elements.service import get_service

    _fake_qdrant(monkeypatch, IT_AND_EN)
    pid = await _make_project(session, region="Italy")
    await _bind(session, pid, "ACME-RATES-2026")
    sid = await _text_session(session, pid, "IT_ROME")
    await get_service().update_session(session, sid, schemas.SessionUpdate(catalogue_id=""))
    await session.commit()
    seen = _record_catalogue_lookups(monkeypatch)

    await get_service().run_match(session, sid, schemas.RunMatchRequest(method="vector"))

    assert "IT_ROME" not in seen
