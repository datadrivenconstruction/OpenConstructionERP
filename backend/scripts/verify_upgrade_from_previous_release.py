# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run the CURRENT code against a database the PREVIOUS release built.

Half two of the upgrade lane. ``age_database_to_previous_release.py`` runs
first, in an interpreter holding the previous release, and leaves behind a
database with that release's schema and a few rows in it. This script runs in
an interpreter holding the current code, against that same database.

What it is for
--------------
Every other lane starts from an empty database, so the only thing they have
ever tested is a fresh install. Nothing in this codebase calls
``alembic upgrade``: the schema moves at boot by a helper that only issues
``ADD COLUMN`` and ``CREATE INDEX IF NOT EXISTS``, plus ``create_all`` for
tables that are wholly absent. That is enough for a revision made of nullable
columns and is not enough for a NOT NULL, a rename, a type change or a
backfill - and until this lane existed, nothing said so.

The five things it proves, in order
-----------------------------------
1. The database really is old. The set of tables and columns the current
   metadata declares and the database does not have is computed BEFORE the
   current code runs, and it has to be non-empty. Without that, the whole
   lane could pass on a database that was never aged - and a lane that passes
   vacuously is worse than no lane, because it reports coverage that is not
   there. An empty set here means the pin in the workflow has been moved
   forward to a release that carries no schema change, and the lane says so
   rather than going green.
2. The database is at an older migration revision than the code. Pre-15.4.0
   wheels ship no ``alembic.ini``, so a real install of one records no
   revision at all; that reads as ``None`` here and is equally acceptable.
   What is not acceptable is a database already sitting at the current head.
3. The schema actually moved. After the current code has booted once, that
   same missing set has to be empty. This is the check a NOT NULL column with
   no default fails, because the auto-migrate helper cannot add one to a table
   that has rows in it.
4. The health signal agrees. ``schema_heal_failed`` and ``schema_heal_incomplete``
   must both read false, not null.
   What ``alembic_head_matches`` has to read depends on which cohort the aged
   database belongs to, because the two have genuinely different honest answers
   and a single expectation would make one of them unsatisfiable.

   A database that arrives already carrying a revision - 15.4.0 and later - must
   read true. A database that arrives with none at all - pre-15.4.0, whose wheels
   ship no revision tree - must read unknown, and must still be carrying no
   revision afterwards. That is not a lowered bar. Stamping such a database head
   would claim a position nothing verified and would erase the only durable
   record that it is behind, permanently, so the boot refuses and the refusal is
   what is being checked here. This check used to demand true from both, which
   the second cohort could only ever satisfy by being lied about.
5. A real read path answers. The NCR register is reached over HTTP with a
   token, because an authenticated endpoint answers 401 to an anonymous
   caller and a 401 would satisfy any assertion written as "not a 500".

Every mapped column of every table that was missing something is also selected
directly, because that is the exact query shape an ORM read issues and the
exact one that raises UndefinedColumn on a half-migrated database.

What this does not see
----------------------
Presence and nullability, not types: a column whose type a revision widens or
narrows reads as unchanged here. A rename is indistinguishable from an
addition, because the new name gets added and the old one keeps the data, so
the comparison goes green on a database that lost the mapping. And a revision
whose work is a data backfill leaves no schema signal at all. Those three
shapes are outside this script and still need a test of their own.

Environment:
    DATABASE_URL           Required. Async URL of the aged database.
    DATABASE_SYNC_URL      Required. Sync URL of the same database.
    OE_UPGRADE_AGED_STATE  Required. The handover JSON the aging half wrote.

Exit code 0 when every check passed, 1 otherwise.
"""

from __future__ import annotations

import importlib
import json
import os
import pkgutil
import sys
from pathlib import Path

_FAILURES: list[str] = []


def check(passed: bool, message: str) -> bool:
    """Record one check and print its verdict. Never raises, never exits."""
    print(f"{'OK  ' if passed else 'FAIL'}  {message}")
    if not passed:
        _FAILURES.append(message)
    return passed


def load_current_metadata():
    """Populate ``Base.metadata`` the way ``app/main.py`` does at boot.

    The hand-written import list in ``alembic/env.py`` omits dozens of newer
    modules, so anything that reads the metadata has to walk the package the
    way the boot path walks it or it measures a smaller schema than the one
    that ships.
    """
    from app import modules as modules_pkg
    from app.core import audit as _audit  # noqa: F401
    from app.core import audit_log as _audit_log  # noqa: F401
    from app.database import Base

    for entry in pkgutil.iter_modules(modules_pkg.__path__):
        if not entry.ispkg:
            continue
        models_module = f"app.modules.{entry.name}.models"
        try:
            importlib.import_module(models_module)
        except ModuleNotFoundError as exc:
            # No models.py in this module is fine. A different missing import
            # inside one is not, and must not be swallowed here: swallowing it
            # would shrink the declared schema and shrink the drift set with
            # it, which is the one number this lane cannot afford to get wrong.
            if exc.name != models_module:
                raise
    return Base


def schema_gap(engine, base) -> tuple[list[str], list[str], list[str], list[str]]:
    """Where the database disagrees with what the current metadata declares.

    Returns missing tables, missing columns, and then nullability disagreements
    split by DIRECTION, because the two directions are different defects with
    different repairs and one shared list would blur them:

    ``model_notnull_db_nullable``
        The model promises NOT NULL and the database accepts NULL.
        ``postgres_migrator`` writes NOT NULL into its ``ADD COLUMN`` only when
        the column also carries a server default to backfill the rows already
        there::

            not_null = " NOT NULL" if (not col.nullable and default) else ""

        A NOT NULL column with no default - the textbook change an additive
        heal cannot make - is therefore added NULLABLE instead of failing. The
        column name appears, so a check that only compares names reports the
        upgrade as complete while the constraint the model promises is simply
        absent.

    ``db_notnull_model_nullable``
        The database insists on NOT NULL and the model does not. This is what a
        revision that WIDENS a column leaves behind when it never runs: the
        heal only ever adds columns and indexes, it has no ``DROP NOT NULL``,
        so the old constraint survives. Application code that assigns ``None``
        into such a column then raises NotNullViolation on an ordinary write,
        which is a live 500 rather than a latent gap.

    Checking only the first direction is what let an upgrade ship with two
    columns NOT NULL that the models declare nullable: the lane compared one
    way, found nothing, and called the schema healed.
    """
    import sqlalchemy as sa

    inspector = sa.inspect(engine)
    # One round trip for the whole schema. ``get_columns`` per table is 600+
    # catalogue queries against a database this size and turns a check that
    # should take a second into minutes, which is how a gate stops being run.
    by_table = {key[1]: columns for key, columns in inspector.get_multi_columns().items()}
    missing_tables: list[str] = []
    missing_columns: list[str] = []
    model_notnull_db_nullable: list[str] = []
    db_notnull_model_nullable: list[str] = []
    for table in base.metadata.sorted_tables:
        if table.name not in by_table:
            missing_tables.append(table.name)
            continue
        reflected = {column["name"]: column for column in by_table[table.name]}
        for col in table.columns:
            found = reflected.get(col.name)
            if found is None:
                missing_columns.append(f"{table.name}.{col.name}")
            elif not col.nullable and found.get("nullable"):
                model_notnull_db_nullable.append(f"{table.name}.{col.name}")
            elif col.nullable and not found.get("nullable"):
                db_notnull_model_nullable.append(f"{table.name}.{col.name}")
    return (
        sorted(missing_tables),
        sorted(missing_columns),
        sorted(model_notnull_db_nullable),
        sorted(db_notnull_model_nullable),
    )


def main() -> int:
    sync_url = os.environ.get("DATABASE_SYNC_URL", "").strip()
    state_path = os.environ.get("OE_UPGRADE_AGED_STATE", "").strip()
    if not sync_url or not state_path:
        print("FAIL  DATABASE_SYNC_URL and OE_UPGRADE_AGED_STATE are both required")
        return 1

    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    print(f"..    aged database was built by openconstructionerp {state['aged_from_version']}")

    import sqlalchemy as sa

    base = load_current_metadata()
    engine = sa.create_engine(sync_url, poolclass=sa.pool.NullPool)

    # ── 1 & 2. Before the current code runs: is this database actually old? ──
    missing_tables, missing_columns, nullable_gaps, overtight_gaps = schema_gap(engine, base)
    print(
        f"..    the aged database is missing {len(missing_tables)} table(s) and {len(missing_columns)} column(s), "
        f"accepts NULL in {len(nullable_gaps)} column(s) the model marks NOT NULL, "
        f"and insists on NOT NULL in {len(overtight_gaps)} column(s) the model marks nullable"
    )
    for name in (missing_tables + missing_columns + nullable_gaps + overtight_gaps)[:20]:
        print(f"        - {name}")

    check(
        bool(missing_tables or missing_columns or nullable_gaps or overtight_gaps),
        "the aged database is missing something the current code declares, so there is an upgrade to test "
        f"(release {state['aged_from_version']}); an empty gap means the pin has been moved forward to a "
        "release with no schema change and this lane would prove nothing",
    )

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    current_head = ScriptDirectory.from_config(Config(str(ini))).get_current_head()
    aged_revision = state["aged_revision"]
    check(
        aged_revision != current_head,
        f"the aged database records revision {aged_revision!r}, which is not the current head {current_head!r}",
    )

    # ── 3. Boot the current code once, exactly as a user's upgrade does ─────
    from fastapi.testclient import TestClient

    from app.main import create_app

    print("..    booting the current code against the aged database")
    with TestClient(create_app()) as client:
        healed_tables, healed_columns, healed_nullable, healed_overtight = schema_gap(engine, base)
        residue = healed_tables + healed_columns
        check(
            not residue,
            "the schema moved: every table and column the current code declares is present after boot"
            + ("" if not residue else f" - still missing {residue}"),
        )
        check(
            not healed_nullable,
            "every column the current code declares NOT NULL is NOT NULL in the database after boot"
            + (
                ""
                if not healed_nullable
                else f" - {healed_nullable} accept NULL, which is what an ADD COLUMN with no default to "
                "backfill leaves behind"
            ),
        )
        check(
            not healed_overtight,
            "every column the current code declares nullable accepts NULL in the database after boot"
            + (
                ""
                if not healed_overtight
                else f" - {healed_overtight} are still NOT NULL, which is what a revision that WIDENS a "
                "column leaves behind when it never runs; the heal has no DROP NOT NULL, so application "
                "code assigning None into these raises NotNullViolation on an ordinary write"
            ),
        )

        # The query shape an ORM read issues, on exactly the tables that were
        # behind. A missing column raises UndefinedColumn here and nowhere in
        # a checkfirst=True create_all.
        touched = {name.split(".")[0] for name in missing_columns + nullable_gaps + overtight_gaps} | set(
            missing_tables
        )
        unreadable: list[str] = []
        for table_name in sorted(touched):
            table = base.metadata.tables.get(table_name)
            if table is None:
                continue
            columns = ", ".join(f'"{col.name}"' for col in table.columns)
            try:
                with engine.connect() as conn:
                    conn.execute(sa.text(f'SELECT {columns} FROM "{table_name}" LIMIT 1'))
            except Exception as exc:  # noqa: BLE001 - the message is the finding
                unreadable.append(f"{table_name}: {type(exc).__name__}")
        check(
            not unreadable,
            f"every mapped column of the {len(touched)} table(s) this upgrade touched can be selected"
            + ("" if not unreadable else f" - {unreadable}"),
        )

        # ── 4. The health signal ────────────────────────────────────────────
        health = client.get("/api/health")
        check(health.status_code == 200, f"/api/health answered {health.status_code}")
        body = health.json() if health.status_code == 200 else {}
        heal_failed = body.get("schema_heal_failed")
        check(
            heal_failed is False,
            f"schema_heal_failed reads {heal_failed!r}; false is the only healthy value, and null means the "
            "heal never ran at all",
        )
        # Failed only says the heal did not raise. A heal whose statements the
        # database refused one by one returns normally, so failed reads false
        # while the column it could not add answers 500. Incomplete is the
        # field that sees that, with the same polarity and the same rule: false
        # is the only pass, and null means the heal never ran.
        heal_incomplete = body.get("schema_heal_incomplete")
        check(
            heal_incomplete is False,
            f"schema_heal_incomplete reads {heal_incomplete!r} with "
            f"{body.get('schema_heal_skipped_count')!r} statement(s) skipped; false is the only healthy value, "
            "and null means the heal never ran at all",
        )
        head_matches = body.get("alembic_head_matches")
        with engine.connect() as conn:
            if sa.inspect(conn).has_table("alembic_version"):
                stamped_after = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
            else:
                stamped_after = None

        if aged_revision is None:
            # The pre-15.4.0 shape: a real install of one of those releases records
            # no revision at all. Stamping it head would claim a position nothing
            # verified and would destroy the only durable evidence the database is
            # behind, so the boot deliberately refuses. "Cannot be told" is then the
            # honest reading and the one this lane has to require - demanding true
            # here would demand the product resume lying, and no aged database of
            # this cohort could ever satisfy it.
            check(
                head_matches is None,
                f"alembic_head_matches reads {head_matches!r}; a database that arrived with no revision has "
                "nothing to compare, so anything other than unknown means it was stamped at a position "
                "nothing checked",
            )
            check(
                stamped_after is None,
                f"the database was stamped at {stamped_after!r} despite arriving with no revision at all; "
                "that is the write the refusal exists to prevent, and it cannot be undone",
            )
        else:
            check(
                head_matches is True,
                f"alembic_head_matches reads {head_matches!r}; null means the migration head cannot be told "
                "and false means the database is not at it",
            )

        # ── 5. A real read path, authenticated ──────────────────────────────
        login = client.post(
            "/api/v1/users/auth/login",
            json={"email": state["user_email"], "password": state["user_password"]},
        )
        if not check(
            login.status_code == 200,
            f"the account the previous release created can still log in (got {login.status_code})",
        ):
            engine.dispose()
            return 1
        token = login.json()["access_token"]

        register = client.get(
            "/api/v1/ncr/",
            params={"project_id": state["project_id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        check(
            register.status_code == 200,
            f"GET /api/v1/ncr/ on the aged project answered {register.status_code}",
        )
        if register.status_code == 200:
            payload = register.json()
            check(
                payload.get("total", 0) >= 1,
                f"the register returned the row the previous release wrote (total={payload.get('total')})",
            )

    engine.dispose()

    print()
    if _FAILURES:
        print(f"UPGRADE LANE FAILED - {len(_FAILURES)} check(s):")
        for failure in _FAILURES:
            print(f"  - {failure}")
        return 1
    print("UPGRADE LANE PASSED - the current code healed a database built by the previous release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
