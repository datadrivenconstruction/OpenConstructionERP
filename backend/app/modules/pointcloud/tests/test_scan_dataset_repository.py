# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Tests for the Point Cloud ScanDataset repository + service register path.

Every test uses a transaction-isolated PostgreSQL session (rolled back on
teardown) from ``tests._pg`` - never the production / shared test DB.

Coverage
--------
* test_create_scan_roundtrips_bbox_numeric_and_json - a ScanDataset created via
  the repository round-trips its JSON bbox blob and its Numeric min/max lat/lon
  out of PostgreSQL with full precision.
* test_list_for_project_is_tenant_scoped - the tenant-scoped list query never
  returns a scan owned by another tenant, even within the same project id.
* test_register_upload_mints_tenant_namespaced_key - the service register path
  stamps the resolved tenant and a tenant-namespaced upload key, in
  status=uploading.
* test_register_upload_rejects_recap - a proprietary RCP/RCS upload is rejected
  with an explanatory reason.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from tests._pg import transactional_session

from app.modules.pointcloud.models import ScanDataset
from app.modules.pointcloud.repository import ScanDatasetRepository
from app.modules.pointcloud.schemas import (
    AccuracyTier,
    ScanDatasetCreate,
    SourceType,
)
from app.modules.pointcloud.service import PointCloudService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session with two projects pre-seeded.

    Two projects under two distinct owners (= two tenants) so the cross-tenant
    list test can probe the tenant scope without extra setup.
    """
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner_a = User(
            id=uuid.uuid4(),
            email=f"a-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="A",
        )
        owner_b = User(
            id=uuid.uuid4(),
            email=f"b-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="B",
        )
        s.add_all([owner_a, owner_b])
        await s.flush()
        project_a = Project(
            id=uuid.uuid4(),
            name="Reality Project A",
            owner_id=owner_a.id,
            currency="EUR",
        )
        project_b = Project(
            id=uuid.uuid4(),
            name="Reality Project B",
            owner_id=owner_b.id,
            currency="EUR",
        )
        s.add_all([project_a, project_b])
        await s.commit()
        s.info["project_a_id"] = project_a.id
        s.info["project_b_id"] = project_b.id
        s.info["owner_a_id"] = owner_a.id
        s.info["owner_b_id"] = owner_b.id
        yield s


# ── 1. bbox Numeric + JSON round-trip ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_scan_roundtrips_bbox_numeric_and_json(session: AsyncSession) -> None:
    """A scan persists and reloads its JSON bbox blob + Numeric lat/lon exactly."""
    project_id: uuid.UUID = session.info["project_a_id"]
    tenant_id: uuid.UUID = session.info["owner_a_id"]
    repo = ScanDatasetRepository(session)

    bbox_json = {
        "min": [12.5, 48.0, 110.25],
        "max": [42.0, 78.5, 145.75],
        "units": "m",
        "crs_epsg": 25832,
    }
    scan = ScanDataset(
        id=uuid.uuid4(),
        project_id=project_id,
        tenant_id=tenant_id,
        source_type="laser_scan",
        original_format="e57",
        accuracy_tier="survey",
        crs_epsg=25832,
        crs_confidence=Decimal("0.875"),
        point_count=123456789,
        bbox_json=bbox_json,
        bbox_min_lat=Decimal("48.1374210"),
        bbox_min_lon=Decimal("11.5754920"),
        bbox_max_lat=Decimal("48.1390050"),
        bbox_max_lon=Decimal("11.5781330"),
        upload_key="pointcloud/x/y/z/raw.e57",
        status="uploading",
        retention_policy="keep_raw",
    )
    await repo.create(scan)
    await session.commit()
    session.expire_all()

    reloaded = await repo.get_by_id(scan.id)
    assert reloaded is not None
    # JSON blob round-trips structurally.
    assert reloaded.bbox_json == bbox_json
    assert reloaded.bbox_json["crs_epsg"] == 25832
    # Numeric(10,7) keeps all 7 fractional digits, no float drift.
    assert reloaded.bbox_min_lat == Decimal("48.1374210")
    assert reloaded.bbox_min_lon == Decimal("11.5754920")
    assert reloaded.bbox_max_lat == Decimal("48.1390050")
    assert reloaded.bbox_max_lon == Decimal("11.5781330")
    assert reloaded.crs_confidence == Decimal("0.875")
    # point_count round-trips a large integer.
    assert int(reloaded.point_count) == 123456789


# ── 2. tenant scoping ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_for_project_is_tenant_scoped(session: AsyncSession) -> None:
    """list_for_project filters on tenant; another tenant's scan is invisible."""
    project_id: uuid.UUID = session.info["project_a_id"]
    tenant_a: uuid.UUID = session.info["owner_a_id"]
    tenant_b: uuid.UUID = session.info["owner_b_id"]
    repo = ScanDatasetRepository(session)

    mine = ScanDataset(
        id=uuid.uuid4(),
        project_id=project_id,
        tenant_id=tenant_a,
        original_format="las",
        accuracy_tier="standard",
        upload_key="pointcloud/a/raw.las",
        status="uploading",
    )
    # A row carrying the SAME project_id but a DIFFERENT tenant must never leak
    # into tenant A's list - this is the multi-tenant isolation guarantee.
    other_tenant = ScanDataset(
        id=uuid.uuid4(),
        project_id=project_id,
        tenant_id=tenant_b,
        original_format="laz",
        accuracy_tier="standard",
        upload_key="pointcloud/b/raw.laz",
        status="uploading",
    )
    session.add_all([mine, other_tenant])
    await session.commit()

    rows_a = await repo.list_for_project(project_id, tenant_id=tenant_a)
    ids_a = {r.id for r in rows_a}
    assert mine.id in ids_a
    assert other_tenant.id not in ids_a
    assert await repo.count_for_project(project_id, tenant_id=tenant_a) == 1

    rows_b = await repo.list_for_project(project_id, tenant_id=tenant_b)
    ids_b = {r.id for r in rows_b}
    assert other_tenant.id in ids_b
    assert mine.id not in ids_b

    # The tenant-scoped single-row read enforces the same boundary.
    assert await repo.get_for_tenant(mine.id, tenant_id=tenant_b) is None
    assert (await repo.get_for_tenant(mine.id, tenant_id=tenant_a)).id == mine.id


# ── 3. service register path ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_upload_mints_tenant_namespaced_key(session: AsyncSession) -> None:
    """register_upload resolves the tenant and mints a tenant-namespaced key."""
    project_id: uuid.UUID = session.info["project_a_id"]
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = PointCloudService(session)
    payload = {"sub": str(owner_a), "role": "editor"}

    scan = await service.register_upload(
        ScanDatasetCreate(
            project_id=project_id,
            name="Site scan day 1",
            source_type=SourceType.lidar,
            original_format="laz",
            accuracy_tier=AccuracyTier.standard,
        ),
        payload=payload,
    )
    await session.commit()

    assert scan.tenant_id == owner_a
    assert scan.status == "uploading"
    assert scan.original_format == "laz"
    assert scan.accuracy_tier == "standard"
    assert scan.created_by == owner_a
    # Tenant-namespaced key: tenant id is the leading path segment.
    assert scan.upload_key.startswith(f"pointcloud/{owner_a}/{project_id}/{scan.id}/")
    assert scan.upload_key.endswith("raw.laz")


@pytest.mark.asyncio
async def test_register_upload_rejects_recap(session: AsyncSession) -> None:
    """A proprietary ReCap container is rejected with an explanatory reason."""
    project_id: uuid.UUID = session.info["project_a_id"]
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = PointCloudService(session)
    payload = {"sub": str(owner_a), "role": "editor"}

    # ``rcp`` / ``rcs`` are not in the schema enum, so build the create model
    # with a bypass to prove the SERVICE-layer gate also rejects them (defence
    # in depth - the format reason code drives the explanatory UI error).
    create = ScanDatasetCreate(
        project_id=project_id,
        name="ReCap import",
        original_format="e57",
    )
    object.__setattr__(create, "original_format", "rcp")

    with pytest.raises(HTTPException) as exc:
        await service.register_upload(create, payload=payload)
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "format_proprietary_recap"
