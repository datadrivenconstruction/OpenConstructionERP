"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Transparent one-time SQLite -> embedded-PostgreSQL data migration.

Builds a legacy ``openestimate.db`` with a couple of rows, boots an embedded PG
at the same data dir, runs the auto-migration, and verifies the rows landed in
PostgreSQL and the SQLite file was retired so it cannot migrate twice.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def test_auto_migrate_moves_sqlite_data_to_embedded_pg(tmp_path, monkeypatch) -> None:
    saved_url = os.environ.get("DATABASE_URL")
    saved_sync = os.environ.get("DATABASE_SYNC_URL")
    monkeypatch.setenv("OE_USE_EMBEDDED_PG", "1")

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from app.modules.projects.models import Project
    from app.modules.users.models import User
    from app.scripts import migrate_sqlite_to_postgres as migrator

    base = migrator._load_metadata()

    # 1) Legacy SQLite DB with one user + one project.
    data_dir = tmp_path
    sqlite_path = data_dir / "openestimate.db"
    src_engine = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
    base.metadata.create_all(src_engine)
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    with Session(src_engine) as s:
        s.add(User(id=uid, email="legacy@test.io", hashed_password="x", full_name="Legacy User"))
        s.flush()
        s.add(Project(id=pid, name="Legacy Project", owner_id=uid, currency="EUR"))
        s.commit()
    src_engine.dispose()
    assert sqlite_path.exists()

    # 2) Boot embedded PG at the same data dir and migrate.
    from app.core import embedded_pg

    assert embedded_pg.boot(data_dir) is True
    try:
        status = embedded_pg.auto_migrate_legacy_sqlite(data_dir)
        assert status.startswith("migrated"), status

        # 3) The rows are in PostgreSQL.
        pg_engine = create_engine(os.environ["DATABASE_SYNC_URL"])
        try:
            with Session(pg_engine) as ps:
                user_count = ps.execute(select(func.count()).select_from(User)).scalar_one()
                project_name = ps.execute(select(Project.name)).scalar_one()
            assert user_count == 1
            assert project_name == "Legacy Project"
        finally:
            pg_engine.dispose()

        # 4) The SQLite file was retired so it cannot migrate again.
        assert not sqlite_path.exists()
        assert (data_dir / "openestimate.db.migrated").exists()

        # 5) Re-running is a safe no-op.
        again = embedded_pg.auto_migrate_legacy_sqlite(data_dir)
        assert again.startswith("skip"), again
    finally:
        embedded_pg.shutdown()
        if saved_url is not None:
            os.environ["DATABASE_URL"] = saved_url
        if saved_sync is not None:
            os.environ["DATABASE_SYNC_URL"] = saved_sync
