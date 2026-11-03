"""The survey tables migration: one head, chained on vai01, and it upgrades and downgrades cleanly."""

from __future__ import annotations

import importlib.util
import pathlib

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

BACKEND = pathlib.Path(__file__).resolve().parents[3]
REV = "vdro01_site_survey_captures"


def test_single_head_chained_on_vai01() -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    assert script.get_revision(REV).down_revision == "vai01_doc_assistant_agent_catalogue"


def _load():
    spec = importlib.util.spec_from_file_location(
        "vdro01", BACKEND / "alembic" / "versions" / "vdro01_site_survey_captures.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upgrade_creates_and_downgrade_drops_both_tables() -> None:
    mod = _load()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        mod.upgrade()
        insp = sa.inspect(conn)
        assert {"oe_geo_survey_capture", "oe_geo_survey_observation"} <= set(insp.get_table_names())
        cols = {c["name"] for c in insp.get_columns("oe_geo_survey_capture")}
        assert {"captured_on", "overlay_id", "scan_id", "gsd_cm", "bbox_min_lat", "metadata"} <= cols
        uniques = insp.get_unique_constraints("oe_geo_survey_observation")
        assert any(u["column_names"] == ["capture_id", "activity_id"] for u in uniques)
        mod.upgrade()  # idempotent
        mod.downgrade()
        assert not {"oe_geo_survey_capture", "oe_geo_survey_observation"} & set(sa.inspect(conn).get_table_names())


def test_source_check_constraint_rejects_a_capture_with_both_sources() -> None:
    mod = _load()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        mod.upgrade()
        stmt = sa.text(
            "INSERT INTO oe_geo_survey_capture (id, project_id, tenant_id, kind, captured_on, overlay_id, scan_id)"
            " VALUES (:id, 'p', 't', :kind, '2026-01-01', :overlay, :scan)"
        )

        def insert(kind: str, overlay: str | None, scan: str | None) -> None:
            conn.execute(stmt, {"id": f"{kind}-{overlay}-{scan}", "kind": kind, "overlay": overlay, "scan": scan})

        insert("orthophoto", "ov1", None)
        insert("point_cloud", None, "sc1")
        for bad in (("orthophoto", "ov2", "sc2"), ("point_cloud", None, None), ("orthophoto", None, "sc3")):
            try:
                with conn.begin_nested():
                    insert(*bad)
            except sa.exc.IntegrityError:
                continue
            raise AssertionError(f"constraint let {bad} through")
