"""Contact list (offset vs cursor) and GAEB X31 parse benchmark.

Not collected by pytest (no ``test_`` prefix). Run from ``backend/``:

    py -3.14 -m tests.perf.bench_contacts_gaeb [--rows 10000] [--page 100] [--db-url URL]

Default DB is a local embedded PostgreSQL cluster (kept in the OS temp dir and
reused); pass --db-url to measure another server. The contacts table is
recreated on each run, so use a scratch database.
One JSON line per run is appended to ``tests/perf/ledger.jsonl``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

#: Reused between runs so repeated benchmarks do not pile up clusters on disk.
PG_DIR = Path(tempfile.gettempdir()) / "oe-bench-contacts-pg"

LEDGER = Path(__file__).with_name("ledger.jsonl")
TENANT = "00000000-0000-0000-0000-000000000529"


def _pct(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)


async def _bench_contacts(url: str, rows: int, page: int) -> dict:
    from app.modules.contacts.models import Contact
    from app.modules.contacts.repository import ContactRepository
    from app.modules.users.models import User
    from tests.perf.bench_fixtures import contact_rows

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Contact.__table__.drop(c, checkfirst=True))
        await conn.run_sync(lambda c: User.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: Contact.__table__.create(c))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await s.execute(Contact.__table__.insert(), contact_rows(rows, TENANT))
        await s.commit()

    offset_ms: list[float] = []
    async with maker() as s:
        repo = ContactRepository(s)
        for off in range(0, rows, page):
            t = time.perf_counter()
            await repo.list(owner_id=TENANT, offset=off, limit=page, sort_by="company_name", sort_order="asc")
            offset_ms.append((time.perf_counter() - t) * 1000)

    cursor_ms: list[float] = []
    seen = 0
    async with maker() as s:
        repo = ContactRepository(s)
        after = None
        while True:
            t = time.perf_counter()
            items, after = await repo.list_keyset(owner_id=TENANT, limit=page, after=after)
            cursor_ms.append((time.perf_counter() - t) * 1000)
            seen += len(items)
            if after is None:
                break
    await engine.dispose()
    assert seen == rows, f"cursor walk returned {seen} of {rows}"
    return {
        "offset_p50_ms": _pct(offset_ms, 0.5),
        "offset_p95_ms": _pct(offset_ms, 0.95),
        "cursor_p50_ms": _pct(cursor_ms, 0.5),
        "cursor_p95_ms": _pct(cursor_ms, 0.95),
        "pages": len(cursor_ms),
    }


def _bench_gaeb(lines: int) -> dict:
    from app.modules.boq.gaeb_x31 import parse_x31
    from tests.perf.bench_fixtures import gaeb_x31_bytes

    data = gaeb_x31_bytes(lines)
    runs = []
    for _ in range(3):
        t = time.perf_counter()
        parsed = parse_x31(data)
        runs.append((time.perf_counter() - t) * 1000)
    assert len(parsed.items) == lines
    return {"gaeb_lines": lines, "gaeb_bytes": len(data), "gaeb_parse_ms": round(statistics.median(runs), 1)}


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10_000)
    ap.add_argument("--page", type=int, default=100)
    ap.add_argument("--db-url", default="")
    args = ap.parse_args()

    url = args.db_url
    if not url:
        os.environ.pop("DATABASE_URL", None)
        from app.core import embedded_pg

        if not embedded_pg.boot(PG_DIR):
            raise SystemExit("could not boot embedded PostgreSQL; pass --db-url")
        url = os.environ["DATABASE_URL"]
    else:
        os.environ["DATABASE_URL"] = url
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    result = asyncio.run(_bench_contacts(url, args.rows, args.page))
    result.update(_bench_gaeb(args.rows))
    line = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "sha": _git_sha(),
        "db": url.split(":", 1)[0],
        "rows": args.rows,
        "page": args.page,
        "host": platform.node(),
        **result,
    }
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    print(json.dumps(line))


if __name__ == "__main__":
    main()
