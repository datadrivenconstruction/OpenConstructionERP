# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The setting-out sheet renders the lesson 4 content: one pass, one fail, who measured them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.setting_out.schemas import Finding, RecordOut, RequestDetail, StakeOut
from app.modules.setting_out.sheet_pdf import build_setting_out_sheet


def _stake(pid: str, e: float, me: float, mn: float, d: float, verdict: str) -> StakeOut:
    sid = uuid.uuid4()
    rec = RecordOut(
        id=uuid.uuid4(),
        point_id=sid,
        measured_e=me,
        measured_n=mn,
        measured_z=None,
        de_mm=0,
        dn_mm=0,
        d_mm=d,
        dz_mm=None,
        tol_h_mm=10,
        tol_v_mm=10,
        verdict=verdict,  # type: ignore[arg-type]
        instrument="Demo total station",
        control_ref="CP1, CP2",
        measured_by="Demo surveyor",
        measured_at=datetime(2026, 10, 12, tzinfo=UTC),
        note="",
        ncr_id=None,
    )
    return StakeOut(
        id=sid,
        point_id=pid,
        design_e=e,
        design_n=5819030.0,
        design_z=34.3,
        chainage=None,
        offset_m=None,
        code="",
        verdict=verdict,  # type: ignore[arg-type]
        latest=rec,
        record_count=1,
    )


def test_sheet_renders_a_pdf() -> None:
    detail = RequestDetail(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        code="SO-001",
        name="Columns axis C",
        item_type="column",
        tolerance_key="demo",
        tolerance_label="Demo 10 mm",
        tolerance_source="demo",
        tol_h_mm=10,
        tol_v_mm=10,
        element_ref_type="boq",
        element_ref_id="",
        element_ref_label="Columns axis C",
        alignment=None,
        instrument="Demo total station",
        control_ref="CP1, CP2",
        source_filename="stakeout_design.csv",
        note="",
        created_at=datetime.now(UTC),
        point_count=2,
        pass_count=1,
        fail_count=1,
        stakes=[
            _stake("C-03", 389060.0, 389060.012, 5819029.991, 15, "fail"),
            _stake("C-04", 389080.0, 389080.004, 5819029.997, 5, "pass"),
        ],
    )
    pdf = build_setting_out_sheet(
        detail,
        project_name="Riverside Yard (survey demo)",
        crs_label="EPSG 32633 · WGS 84 / UTM zone 33N",
        findings=[Finding(rule_id="SET-001", severity="error", message="Stake C-03 off by 15 mm, tolerance 10 mm")],
        locale="en",
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000
