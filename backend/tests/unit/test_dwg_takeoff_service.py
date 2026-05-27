# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Baseline service tests for the dwg_takeoff module.

Three small scenarios covering the three correctness properties we
care about most for v4.3 Round-3 Wave-A:

1. **Magic-byte rejection** — a renamed PDF / ZIP uploaded as ``.dwg``
   (and a renamed PDF uploaded as ``.dxf``) is rejected with HTTP 400
   BEFORE the bytes hit disk or a drawing row is created.

2. **Auth-required on every endpoint** — every drawing/annotation route
   on the router carries either a ``RequirePermission`` dependency or
   a ``CurrentUserId`` dependency, so an unauthenticated request
   cannot reach the service. Validated by inspecting the router's
   dependency graph (no live DB required, no FastAPI client startup).

3. **Decimal round-trip happy-path** — a fresh ``DwgAnnotation`` ORM
   row persists ``measurement_value`` / ``scale_override`` exactly as
   ``Decimal`` (no float drift). Guards the Float -> Numeric migration
   added in ``v3097_dwg_takeoff_decimal_quantities``.

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-dwg-takeoff-"))
_TMP_DB = _TMP_DIR / "dwg.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
os.environ["DATA_DIR"] = str(_TMP_DIR)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import HTTPException, UploadFile  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

import app.modules.documents.models  # noqa: E402, F401
import app.modules.dwg_takeoff.models  # noqa: E402, F401

# Ensure ORM registration before create_all().
import app.modules.projects.models  # noqa: E402, F401
import app.modules.users.models  # noqa: E402, F401
from app.modules.dwg_takeoff import router as dwg_router  # noqa: E402
from app.modules.dwg_takeoff.models import DwgAnnotation, DwgDrawing  # noqa: E402
from app.modules.dwg_takeoff.service import (  # noqa: E402
    DwgTakeoffService,
    _looks_like_dxf,
    _validate_cad_magic_bytes,
)

# ── Helpers ───────────────────────────────────────────────────────────────


_MINIMAL_DXF = b"  0\r\nSECTION\r\n  2\r\nHEADER\r\n  0\r\nENDSEC\r\n  0\r\nEOF\r\n"


def _make_upload(payload: bytes, filename: str) -> UploadFile:
    """Build a Starlette UploadFile around an in-memory bytes payload."""
    return UploadFile(
        file=io.BytesIO(payload),
        filename=filename,
        size=len(payload),
        headers=Headers({"content-type": "application/octet-stream"}),
    )


@pytest_asyncio.fixture
async def db_session():
    """A real AsyncSession over a freshly create_all'd temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.database import Base, async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        yield session


async def _seed_project(session) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"dwg-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="DWG Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="DWG Takeoff Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


# ── 1. Magic-byte validation ──────────────────────────────────────────────


def test_looks_like_dxf_accepts_ascii_dxf() -> None:
    """A minimal ASCII DXF header is recognised."""
    assert _looks_like_dxf(_MINIMAL_DXF) is True


def test_looks_like_dxf_accepts_binary_dxf() -> None:
    """The 'AutoCAD Binary DXF' sentinel is recognised."""
    binary = b"AutoCAD Binary DXF\r\n\x1a\x00" + b"\x00" * 32
    assert _looks_like_dxf(binary) is True


def test_looks_like_dxf_rejects_pdf() -> None:
    """A PDF header is not a DXF."""
    assert _looks_like_dxf(b"%PDF-1.7\n" + b"\x00" * 60) is False


def test_looks_like_dxf_rejects_zip() -> None:
    """A ZIP central-directory header is not a DXF."""
    assert _looks_like_dxf(b"PK\x03\x04" + b"\x00" * 60) is False


def test_validate_magic_rejects_renamed_pdf_as_dwg() -> None:
    ok, reason = _validate_cad_magic_bytes(b"%PDF-1.7\n" + b"\x00" * 100, "dwg")
    assert ok is False
    assert "DWG" in reason


def test_validate_magic_rejects_renamed_zip_as_dxf() -> None:
    ok, reason = _validate_cad_magic_bytes(b"PK\x03\x04" + b"\x00" * 100, "dxf")
    assert ok is False
    assert "DXF" in reason


def test_validate_magic_accepts_real_dxf() -> None:
    ok, reason = _validate_cad_magic_bytes(_MINIMAL_DXF, "dxf")
    assert ok is True
    assert reason == ""


def test_validate_magic_accepts_real_dwg_prefix() -> None:
    ok, reason = _validate_cad_magic_bytes(b"AC1032" + b"\x00" * 100, "dwg")
    assert ok is True
    assert reason == ""


# ── 2. Auth-required on every endpoint ────────────────────────────────────


def test_every_router_endpoint_has_auth_or_permission() -> None:
    """Every dwg_takeoff route is wired through CurrentUserId or
    RequirePermission. Without this guarantee an unauthenticated caller
    could reach the service layer.

    The single intentional exception is ``/offline-readiness/`` — it
    reports binary-on-disk availability and exposes no project data, so
    it is whitelisted here to keep the assertion strict for the rest.
    """
    from fastapi.routing import APIRoute

    auth_dep_names = {
        "get_current_user_id",  # CurrentUserId annotation
        "get_current_user_payload",  # JWT decode (transitive)
        "RequirePermission",  # class name
    }
    # Routes that legitimately do not need auth.
    public_paths = {"/offline-readiness/"}

    routes = [r for r in dwg_router.router.routes if isinstance(r, APIRoute)]
    assert routes, "router has no APIRoute entries — fixture is broken"

    def collect_dep_names(dependant: object) -> list[str]:
        """Recursively walk the FastAPI Dependant tree and return every
        callable's ``__name__`` / class name we encounter.
        """
        out: list[str] = []
        stack = [dependant]
        while stack:
            d = stack.pop()
            for sub in getattr(d, "dependencies", []) or []:
                call = getattr(sub, "call", None)
                if call is not None:
                    out.append(getattr(call, "__name__", ""))
                    out.append(call.__class__.__name__)
                stack.append(sub)
        return out

    missing: list[str] = []
    for route in routes:
        if route.path in public_paths:
            continue
        deps = collect_dep_names(route.dependant)
        if not any(token in dep for dep in deps for token in auth_dep_names):
            missing.append(f"{route.methods} {route.path} deps={deps}")
    assert not missing, "Endpoints missing auth: " + "; ".join(missing)


# ── 3. Decimal round-trip happy-path ──────────────────────────────────────


@pytest.mark.asyncio
async def test_annotation_persists_decimal_measurement(db_session) -> None:
    """``measurement_value`` and ``scale_override`` survive the round-trip
    through SQLite as exact Decimals — no Float drift.

    Guards the v3097 Float -> Numeric migration: regressing the column
    type would surface here as ``Decimal != float`` or a precision-loss
    mismatch on the last digit.
    """
    project_id = await _seed_project(db_session)

    drawing = DwgDrawing(
        project_id=project_id,
        name="test.dxf",
        filename="test.dxf",
        file_format="dxf",
        file_path="/tmp/test.dxf",
        size_bytes=64,
        status="ready",
        scale_denominator=Decimal("50.000000"),
        scale_mode="preset",
        metadata_={},
        created_by="tester",
    )
    db_session.add(drawing)
    await db_session.flush()

    ann = DwgAnnotation(
        project_id=project_id,
        drawing_id=drawing.id,
        annotation_type="distance",
        geometry={"x1": 0, "y1": 0, "x2": 100, "y2": 0},
        text=None,
        color="#3b82f6",
        line_width=2,
        thickness=Decimal("1.500000"),
        layer_name="USER_MARKUP",
        measurement_value=Decimal("12.345678"),
        measurement_unit="m",
        scale_override=Decimal("100.000000"),
        created_by="tester",
        metadata_={},
    )
    db_session.add(ann)
    await db_session.commit()

    # Round-trip via a fresh query so we exercise the column type.
    from sqlalchemy import select

    fetched = (
        await db_session.execute(
            select(DwgAnnotation).where(DwgAnnotation.id == ann.id),
        )
    ).scalar_one()

    # The values come back as Decimal on the Numeric columns. We compare
    # via Decimal equality, which is exact (no epsilon needed).
    assert isinstance(fetched.measurement_value, Decimal)
    assert fetched.measurement_value == Decimal("12.345678")
    assert isinstance(fetched.scale_override, Decimal)
    assert fetched.scale_override == Decimal("100.000000")
    assert isinstance(fetched.thickness, Decimal)
    assert fetched.thickness == Decimal("1.500000")

    # And the drawing's scale_denominator too.
    fetched_dr = (
        await db_session.execute(
            select(DwgDrawing).where(DwgDrawing.id == drawing.id),
        )
    ).scalar_one()
    assert isinstance(fetched_dr.scale_denominator, Decimal)
    assert fetched_dr.scale_denominator == Decimal("50.000000")


@pytest.mark.asyncio
async def test_upload_drawing_rejects_renamed_pdf(db_session) -> None:
    """End-to-end: a PDF uploaded as ``.dwg`` raises HTTP 400 in the
    service layer — no DB row, no file on disk.
    """
    project_id = await _seed_project(db_session)
    svc = DwgTakeoffService(db_session)

    upload = _make_upload(b"%PDF-1.7\n" + b"\x00" * 200, "renamed.dwg")

    with pytest.raises(HTTPException) as excinfo:
        await svc.upload_drawing(project_id, upload, "tester")
    assert excinfo.value.status_code == 400
    assert "valid DWG" in excinfo.value.detail

    # No drawing row should have been created.
    from sqlalchemy import select

    rows = (
        (
            await db_session.execute(
                select(DwgDrawing).where(DwgDrawing.project_id == project_id),
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
