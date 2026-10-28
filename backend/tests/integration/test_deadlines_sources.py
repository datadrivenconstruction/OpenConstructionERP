"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Per-source coverage for the cross-module deadline register.

``tests/integration/test_deadlines_integration.py`` proves the register, the
status filter, the project guard and the sweep. This file proves each individual
source adapter, one project per test so a row from another source can never make
an assertion pass by accident:

* an overdue row surfaces with the right classification, sign and severity;
* an approaching row surfaces inside the approaching window;
* a row in a terminal (closed) status is dropped while an open row in the same
  project still surfaces - the closed-row assertion alone would pass with the
  collector removed, so it is paired with a positive one that would not;
* the project filter keeps another project's row out while keeping this
  project's row in - same pairing, same reason;
* and the register survives one collector blowing up.

NOTE: this suite requires a database (it boots the embedded cluster via the
shared conftest).

Run:
    cd backend
    python -m pytest tests/integration/test_deadlines_sources.py -q
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        # Import every model this file seeds so create_all sees the tables (the
        # module loader already imports these at startup; belt-and-suspenders).
        from app.modules.bid_management import models as _bid  # noqa: F401
        from app.modules.compliance_docs import models as _compliance  # noqa: F401
        from app.modules.defects_liability import models as _dlp  # noqa: F401
        from app.modules.inspections import models as _inspections  # noqa: F401
        from app.modules.projects import models as _proj  # noqa: F401
        from app.modules.rfi import models as _rfi  # noqa: F401
        from app.modules.signing import models as _signing  # noqa: F401
        from app.modules.submittals import models as _submittals  # noqa: F401
        from app.modules.temporary_works import models as _tw  # noqa: F401
        from app.modules.users import models as _users  # noqa: F401
        from app.modules.variations import models as _variations  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Auth + project helpers (mirror test_deadlines_integration) ──────────────


async def _register(client: AsyncClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@deadlines.io"
    password = f"Deadl{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _make_project(client: AsyncClient, headers: dict[str, str], label: str) -> str:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"{label}-{uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def admin(http_client):
    email, password = await _register(http_client, "srcowner")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, password)
    return {"email": email, "headers": headers}


# ── Seeders, one per source ─────────────────────────────────────────────────
#
# Every seeder takes the project, how many days from today the deadline sits
# (negative = in the past) and whether the row should be in a terminal status,
# and returns the entity id the register is expected to key on.

Seeder = Callable[[str, int, bool], Awaitable[str]]


def _iso_date(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


def _date(days: int):
    return (datetime.now(UTC) + timedelta(days=days)).date()


async def _seed_rfi(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.rfi.models import RFI

    async with async_session_factory() as s:
        row = RFI(
            project_id=uuid.UUID(project_id),
            rfi_number=f"RFI-{uuid.uuid4().hex[:6]}",
            subject="Confirm slab edge detail at grid C",
            question="Which detail governs?",
            raised_by=uuid.uuid4(),
            status="closed" if closed else "open",
            response_due_date=_iso_date(due_days),
        )
        s.add(row)
        await s.commit()
        return str(row.id)


async def _seed_submittal(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.submittals.models import Submittal

    async with async_session_factory() as s:
        row = Submittal(
            project_id=uuid.UUID(project_id),
            submittal_number=f"SUB-{uuid.uuid4().hex[:6]}",
            title="Precast stair shop drawings",
            submittal_type="shop_drawing",
            status="approved" if closed else "under_review",
            date_required=_iso_date(due_days),
        )
        s.add(row)
        await s.commit()
        return str(row.id)


async def _seed_variation_request(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.variations.models import VariationRequest

    async with async_session_factory() as s:
        row = VariationRequest(
            project_id=uuid.UUID(project_id),
            code=f"VR-{uuid.uuid4().hex[:6]}",
            title="Additional ground beam to grid F",
            status="approved" if closed else "submitted",
            response_due_date=_iso_date(due_days),
        )
        s.add(row)
        await s.commit()
        return str(row.id)


async def _seed_temp_works_item(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.temporary_works.models import TemporaryWorksItem

    async with async_session_factory() as s:
        row = TemporaryWorksItem(
            project_id=uuid.UUID(project_id),
            reference=f"TW-{uuid.uuid4().hex[:6]}",
            title="Falsework to transfer slab",
            tw_type="falsework",
            status="design_checked" if closed else "design_brief",
            design_due_date=_date(due_days),
        )
        s.add(row)
        await s.commit()
        return str(row.id)


async def _seed_temp_works_permit(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.temporary_works.models import TemporaryWorksItem, TemporaryWorksPermit

    async with async_session_factory() as s:
        item = TemporaryWorksItem(
            project_id=uuid.UUID(project_id),
            reference=f"TW-{uuid.uuid4().hex[:6]}",
            title="Propping to podium deck",
            tw_type="propping",
            status="in_use",
        )
        s.add(item)
        await s.flush()
        permit = TemporaryWorksPermit(
            project_id=uuid.UUID(project_id),
            item_id=item.id,
            permit_number=f"PTL-{uuid.uuid4().hex[:6]}",
            permit_type="permit_to_load",
            status="closed" if closed else "issued",
            valid_to=_date(due_days),
        )
        s.add(permit)
        await s.commit()
        return str(permit.id)


async def _seed_dlp_defect(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.defects_liability.models import DlpDefect, DlpWarranty

    async with async_session_factory() as s:
        warranty = DlpWarranty(
            project_id=uuid.UUID(project_id),
            reference=f"WTY-{uuid.uuid4().hex[:6]}",
            title="Roof membrane",
            status="in_dlp",
        )
        s.add(warranty)
        await s.flush()
        defect = DlpDefect(
            project_id=uuid.UUID(project_id),
            warranty_id=warranty.id,
            reference=f"DEF-{uuid.uuid4().hex[:6]}",
            description="Ponding at outlet 3",
            status="closed" if closed else "open",
            due_date=_date(due_days),
        )
        s.add(defect)
        await s.commit()
        return str(defect.id)


async def _seed_inspection(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.inspections.models import QualityInspection

    async with async_session_factory() as s:
        row = QualityInspection(
            project_id=uuid.UUID(project_id),
            inspection_number=f"INS-{uuid.uuid4().hex[:6]}",
            inspection_type="pre_pour",
            title="Rebar inspection, core wall lift 4",
            status="completed" if closed else "scheduled",
            inspection_date=_iso_date(due_days),
        )
        s.add(row)
        await s.commit()
        return str(row.id)


async def _seed_compliance_doc(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.compliance_docs.models import ComplianceDoc

    async with async_session_factory() as s:
        row = ComplianceDoc(
            project_id=uuid.UUID(project_id),
            doc_type="insurance_liability",
            name="Public liability certificate",
            effective_date=_date(-365),
            expires_at=_date(due_days),
            status="cancelled" if closed else "active",
        )
        s.add(row)
        await s.commit()
        return str(row.id)


async def _seed_bid_package(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.bid_management.models import BidPackage

    async with async_session_factory() as s:
        row = BidPackage(
            project_id=uuid.UUID(project_id),
            code=f"BID-{uuid.uuid4().hex[:10]}",
            title="Groundworks package",
            status="awarded" if closed else "published",
            submission_deadline=_iso_date(due_days),
        )
        s.add(row)
        await s.commit()
        return str(row.id)


async def _seed_signing_session(project_id: str, due_days: int, closed: bool) -> str:
    from app.database import async_session_factory
    from app.modules.signing.models import SigningSession

    async with async_session_factory() as s:
        row = SigningSession(
            project_id=uuid.UUID(project_id),
            document_ref=f"contract/{uuid.uuid4().hex[:8]}.pdf",
            document_content_hash="0" * 64,
            provider_capability="advanced_electronic",
            signatory_map=[{"name": "Contractor", "role": "contractor", "required": True}],
            status="fully_signed" if closed else "awaiting_signatures",
            expires_at=datetime.now(UTC) + timedelta(days=due_days),
        )
        s.add(row)
        await s.commit()
        return str(row.id)


# The sources this file covers. Keys must match ``service._COLLECTORS``; the
# three pre-existing sources keep their coverage in test_deadlines_integration.
_SEEDERS: dict[str, Seeder] = {
    "rfi": _seed_rfi,
    "submittals": _seed_submittal,
    "variations": _seed_variation_request,
    "temporary_works": _seed_temp_works_item,
    "temporary_works_permit": _seed_temp_works_permit,
    "defects_liability": _seed_dlp_defect,
    "inspections": _seed_inspection,
    "compliance_docs": _seed_compliance_doc,
    "bid_management": _seed_bid_package,
    "signing": _seed_signing_session,
}

_SOURCE_KEYS = sorted(_SEEDERS)


def test_every_new_source_is_registered() -> None:
    """The seeder table and the collector registry must not drift apart."""
    from app.modules.deadlines.service import _COLLECTORS

    registered = {m for m, _c, _o in _COLLECTORS}
    assert set(_SEEDERS).issubset(registered), sorted(set(_SEEDERS) - registered)


async def _register_rows(client: AsyncClient, headers: dict[str, str], project_id: str, **params: object) -> list[dict]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/v1/deadlines/?project_id={project_id}"
    if query:
        url = f"{url}&{query}"
    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _row_for(rows: list[dict], module: str, entity_id: str) -> dict | None:
    for row in rows:
        if row["module"] == module and row["entity_id"] == entity_id:
            return row
    return None


# ── Per-source: overdue ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module_key", _SOURCE_KEYS)
async def test_source_surfaces_an_overdue_row(http_client, admin, module_key: str) -> None:
    project_id = await _make_project(http_client, admin["headers"], f"od-{module_key}")
    entity_id = await _SEEDERS[module_key](project_id, -4, False)

    rows = await _register_rows(http_client, admin["headers"], project_id)
    row = _row_for(rows, module_key, entity_id)
    assert row is not None, f"{module_key} row missing from {[(r['module'], r['entity_id']) for r in rows]}"
    assert row["classification"] == "overdue"
    assert row["days_overdue"] == 4
    assert row["severity"] == "critical"
    assert row["due_date"] is not None
    assert row["title"]
    # The deep link must be a real relative app route, not an empty string.
    assert row["action_url"].startswith("/")
    assert row["project_id"] == project_id


# ── Per-source: approaching ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module_key", _SOURCE_KEYS)
async def test_source_surfaces_an_approaching_row(http_client, admin, module_key: str) -> None:
    project_id = await _make_project(http_client, admin["headers"], f"ap-{module_key}")
    entity_id = await _SEEDERS[module_key](project_id, 2, False)

    rows = await _register_rows(http_client, admin["headers"], project_id)
    row = _row_for(rows, module_key, entity_id)
    assert row is not None, f"{module_key} approaching row missing"
    assert row["classification"] == "approaching"
    assert row["severity"] == "warning"
    # Signed: negative means days still to run.
    assert row["days_overdue"] == -2

    # And a row well outside the window is not on the register at all.
    far_id = await _SEEDERS[module_key](project_id, 90, False)
    rows = await _register_rows(http_client, admin["headers"], project_id)
    assert _row_for(rows, module_key, far_id) is None


# ── Per-source: a closed row must not appear ────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module_key", _SOURCE_KEYS)
async def test_source_drops_a_terminal_row_but_keeps_an_open_one(http_client, admin, module_key: str) -> None:
    """A closed row is dropped - proven next to an open row that is not.

    The negative half alone would pass with the collector deleted, so the open
    row is seeded in the same project and asserted present in the same call.
    """
    project_id = await _make_project(http_client, admin["headers"], f"cl-{module_key}")
    closed_id = await _SEEDERS[module_key](project_id, -6, True)
    open_id = await _SEEDERS[module_key](project_id, -6, False)

    rows = await _register_rows(http_client, admin["headers"], project_id)
    assert _row_for(rows, module_key, open_id) is not None, f"{module_key} open row missing"
    assert _row_for(rows, module_key, closed_id) is None, f"{module_key} terminal row leaked onto the register"


# ── Per-source: project filter ──────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
@pytest.mark.parametrize("module_key", _SOURCE_KEYS)
async def test_source_is_project_scoped(http_client, admin, module_key: str) -> None:
    """Another project's row stays out while this project's row stays in."""
    project_a = await _make_project(http_client, admin["headers"], f"sa-{module_key}")
    project_b = await _make_project(http_client, admin["headers"], f"sb-{module_key}")
    id_a = await _SEEDERS[module_key](project_a, -3, False)
    id_b = await _SEEDERS[module_key](project_b, -3, False)

    rows = await _register_rows(http_client, admin["headers"], project_a)
    assert _row_for(rows, module_key, id_a) is not None, f"{module_key} row missing from its own project"
    assert _row_for(rows, module_key, id_b) is None, f"{module_key} leaked another project's row"


# ── Per-source: the ?module= filter names the same key ──────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module_key", _SOURCE_KEYS)
async def test_source_can_be_filtered_by_module(http_client, admin, module_key: str) -> None:
    project_id = await _make_project(http_client, admin["headers"], f"mf-{module_key}")
    entity_id = await _SEEDERS[module_key](project_id, -5, False)
    # A second source in the same project that the filter must exclude.
    other_key = next(k for k in _SOURCE_KEYS if k != module_key)
    other_id = await _SEEDERS[other_key](project_id, -5, False)

    rows = await _register_rows(http_client, admin["headers"], project_id, module=module_key)
    assert _row_for(rows, module_key, entity_id) is not None
    assert _row_for(rows, other_key, other_id) is None
    assert {r["module"] for r in rows} == {module_key}


# ── Fail-soft ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_survives_one_collector_raising(http_client, admin, monkeypatch) -> None:
    """One exploding source blanks its own rows only - never the register."""
    from app.modules.deadlines import service

    project_id = await _make_project(http_client, admin["headers"], "failsoft")
    rfi_id = await _seed_rfi(project_id, -7, False)
    inspection_id = await _seed_inspection(project_id, -7, False)

    async def _boom(_session, _project_ids, _now_date, _approaching_days):
        raise RuntimeError("source is on fire")

    patched = [(m, _boom if m == "rfi" else c, o) for m, c, o in service._COLLECTORS]
    monkeypatch.setattr(service, "_COLLECTORS", patched)

    rows = await _register_rows(http_client, admin["headers"], project_id)
    assert _row_for(rows, "rfi", rfi_id) is None
    assert _row_for(rows, "inspections", inspection_id) is not None


@pytest.mark.asyncio
async def test_register_survives_an_uninstalled_source(http_client, admin, monkeypatch) -> None:
    """A module that is not deployed must not break the register.

    Modules are plugins, so a collector's deferred model import can raise
    ``ModuleNotFoundError`` on a deployment that never installed it. That is the
    same fail-soft path as any other collector error, and this pins it.
    """
    from app.modules.deadlines import service

    project_id = await _make_project(http_client, admin["headers"], "uninstalled")
    inspection_id = await _seed_inspection(project_id, -7, False)

    async def _missing(_session, _project_ids, _now_date, _approaching_days):
        raise ModuleNotFoundError("No module named 'app.modules.rfi'")

    patched = [(m, _missing if m == "rfi" else c, o) for m, c, o in service._COLLECTORS]
    monkeypatch.setattr(service, "_COLLECTORS", patched)

    rows = await _register_rows(http_client, admin["headers"], project_id)
    assert _row_for(rows, "inspections", inspection_id) is not None
