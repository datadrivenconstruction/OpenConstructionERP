# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sensor evidence on PostgreSQL: the export is filed as documents, hashed, listed in the claims pack, BIM-linked."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.register_export import ProjectHeader
from app.modules.claims_evidence.service import assemble_evidence
from app.modules.documents.models import DocumentFolder
from app.modules.projects.models import Project
from app.modules.site_sensors import evidence
from app.modules.site_sensors.schemas import DeviceCreate, StripCreate
from app.modules.site_sensors.service import SiteSensorsService
from app.modules.site_sensors.validators import run_rules
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 10, 20, 8, tzinfo=UTC)


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _project(session) -> Project:
    owner = User(id=uuid.uuid4(), email=f"ev-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Quay", owner_id=owner.id, currency="EUR", country_code="DE")
    session.add(project)
    await session.flush()
    return project


async def _vibration_device(session, project):
    service = SiteSensorsService(session)
    device = await service.create_device(DeviceCreate(project_id=project.id, code="VB-01", kind="vibration"))
    readings = [(T0 + timedelta(minutes=i), 1.0 + (i % 4)) for i in range(30)]
    await service.ingest(device, readings)
    return service, device


async def test_the_export_files_csv_and_pdf_in_monitoring_evidence_and_the_hash_matches_the_file(session) -> None:
    project = await _project(session)
    _, device = await _vibration_device(session, project)
    filed = await evidence.file_device_evidence(
        session,
        device,
        T0 - timedelta(hours=1),
        T0 + timedelta(hours=2),
        user_id=str(project.owner_id),
        claim_ref="NC-7",
        project=ProjectHeader(name="Quay", country="DE"),
        limit=8.0,
    )
    assert filed.reading_count == 30
    csv_bytes = Path(filed.csv_document.file_path).read_bytes()
    assert hashlib.sha256(csv_bytes).hexdigest() == filed.csv_sha256 == filed.csv_document.metadata_["sha256"]
    assert Path(filed.pdf_document.file_path).read_bytes().startswith(b"%PDF")

    folder = (
        await session.execute(select(DocumentFolder).where(DocumentFolder.code == "site_sensors.monitoring_evidence"))
    ).scalar_one()
    assert filed.csv_document.folder_id == filed.pdf_document.folder_id == folder.id
    assert filed.csv_document.name.endswith(".csv") and filed.pdf_document.name.endswith(".pdf")


async def test_the_claims_pack_lists_the_filing_with_its_integrity_code(session) -> None:
    project = await _project(session)
    _, device = await _vibration_device(session, project)
    filed = await evidence.file_device_evidence(
        session, device, T0, T0 + timedelta(hours=1), user_id=str(project.owner_id), claim_ref="NC-7"
    )
    pack = await assemble_evidence(session, project_id=project.id, subject_ref="NC-7")
    entries = [e for s in pack.sections for e in s.entries if e.source_module == "site_sensors"]
    assert len(entries) == 1 and filed.csv_sha256 in entries[0].summary


async def test_a_filed_export_passes_the_evidence_rule_and_an_empty_window_files_nothing(session) -> None:
    project = await _project(session)
    service, device = await _vibration_device(session, project)
    with pytest.raises(evidence.EvidenceError, match="no_readings"):
        await evidence.file_device_evidence(
            session, device, T0 + timedelta(days=5), T0 + timedelta(days=6), user_id=str(project.owner_id)
        )
    assert await evidence.evidence_rows(session, project.id) == []
    await evidence.file_device_evidence(session, device, T0, T0 + timedelta(hours=1), user_id=str(project.owner_id))
    rows = await run_rules(await service.validation_payload(project.id))
    assert [r["passed"] for r in rows if r["rule_id"] == "site_sensors.evidence_hashed"] == [True]


async def test_the_pour_record_helper_files_under_concrete_and_pour_records_once(session) -> None:
    project = await _project(session)
    first = await evidence.file_project_document(
        session,
        project_id=project.id,
        user_id=str(project.owner_id),
        filename="pour-A1.pdf",
        content=b"%PDF-1.4 pour record",
        folder_path=evidence.PATH_POUR_RECORDS,
    )
    second = await evidence.file_project_document(
        session,
        project_id=project.id,
        user_id=str(project.owner_id),
        filename="pour-A2.pdf",
        content=b"%PDF-1.4 pour record 2",
        folder_path=evidence.PATH_POUR_RECORDS,
    )
    folders = {
        f.code: f
        for f in (await session.execute(select(DocumentFolder).where(DocumentFolder.project_id == project.id)))
        .scalars()
        .all()
    }
    assert set(folders) == {"site_sensors.concrete", "site_sensors.concrete.pour_records"}
    pour = folders["site_sensors.concrete.pour_records"]
    assert pour.parent_id == folders["site_sensors.concrete"].id
    assert first.folder_id == second.folder_id == pour.id


async def test_a_bim_element_link_is_kept_on_the_device_and_inherited_by_its_strike(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    model_id, element_id = uuid.uuid4(), uuid.uuid4()
    device = await service.create_device(
        DeviceCreate(
            project_id=project.id,
            code="CM-1",
            kind="concrete_maturity",
            pour_ref="Slab L2",
            bim_model_id=model_id,
            bim_element_id=element_id,
        )
    )
    strip = await service.create_strip(StripCreate(device_id=device.id, target_strength_mpa=20))
    assert (strip.bim_model_id, strip.bim_element_id) == (model_id, element_id)
    assert await evidence.strike_status_by_element(session, project.id) == {str(element_id): "planned"}
    rows = await evidence.bim_link_rows(session, project.id)
    assert {r["element_id"] for r in rows} == {str(element_id)} and all(r["model_id"] == str(model_id) for r in rows)
