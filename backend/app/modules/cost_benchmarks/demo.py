# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks: the demo projects, six synthetic completed offices, one estimate.

The demo projects are captured as they stand (their BOQ by element group). Six synthetic
completed office buildings in three countries and three currencies give the cohort enough
history for an own band, and one office estimate carries two outlier elements (external
walls far above P90, heating far below P10) so the comparison has something to show.
Idempotent per tenant.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cost_benchmarks.models import BenchmarkRecord
from app.modules.cost_benchmarks.service import CostBenchmarksService

logger = logging.getLogger(__name__)

_SOURCE = "demo_synthetic"
_PER_M2_EUR = {
    "330": ("External walls", Decimal("420")),
    "340": ("Internal walls", Decimal("150")),
    "350": ("Floors and ceilings", Decimal("240")),
    "360": ("Roofs", Decimal("120")),
    "410": ("Plumbing", Decimal("70")),
    "420": ("Heating", Decimal("130")),
    "440": ("Electrical", Decimal("170")),
}
# name, country, region, currency, fx per EUR, cost date, GFA, spread
_SYNTHETIC = (
    (
        "Office Riverside, completed",
        "DE",
        "BER",
        "EUR",
        Decimal("1"),
        date(2022, 9, 30),
        Decimal("5200"),
        Decimal("0.92"),
    ),
    (
        "Office Parkview, completed",
        "DE",
        "MUC",
        "EUR",
        Decimal("1"),
        date(2024, 3, 31),
        Decimal("7400"),
        Decimal("1.08"),
    ),
    (
        "Office Canal Street, completed",
        "GB",
        "",
        "GBP",
        Decimal("0.85"),
        date(2023, 6, 30),
        Decimal("4600"),
        Decimal("1.00"),
    ),
    (
        "Office Northgate, completed",
        "GB",
        "",
        "GBP",
        Decimal("0.85"),
        date(2025, 1, 31),
        Decimal("9100"),
        Decimal("1.12"),
    ),
    (
        "Office Lakefront, completed",
        "US",
        "",
        "USD",
        Decimal("1.10"),
        date(2021, 11, 30),
        Decimal("6300"),
        Decimal("0.95"),
    ),
    (
        "Office Midtown, completed",
        "US",
        "",
        "USD",
        Decimal("1.10"),
        date(2024, 10, 31),
        Decimal("8200"),
        Decimal("1.04"),
    ),
)
_NOISE = (
    Decimal("1.00"),
    Decimal("0.96"),
    Decimal("1.05"),
    Decimal("0.98"),
    Decimal("1.03"),
    Decimal("1.01"),
    Decimal("0.97"),
)


def _elements(gfa: Decimal, fx: Decimal, spread: Decimal, overrides: dict[str, Decimal] | None = None) -> list[dict]:
    out = []
    for i, (code, (label, per_m2)) in enumerate(_PER_M2_EUR.items()):
        rate = (overrides or {}).get(code, per_m2 * spread * _NOISE[i % len(_NOISE)])
        out.append({"code": code, "label": label, "amount": (rate * gfa * fx).quantize(Decimal("0.01"))})
    return out


async def seed_cost_benchmarks_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the benchmark records for the tenants that own the demo projects."""
    from app.modules.projects.models import Project

    ids = list(project_ids)
    counts = {"captured": 0, "synthetic": 0, "estimates": 0}
    if not ids:
        return counts
    rows = (await session.execute(select(Project.id, Project.owner_id).where(Project.id.in_(ids)))).all()
    by_tenant: dict[str, list[uuid.UUID]] = {}
    for pid, owner in rows:
        if owner is not None:
            by_tenant.setdefault(str(owner), []).append(pid)
    for tenant, pids in by_tenant.items():
        done = (
            await session.execute(
                select(BenchmarkRecord.id).where(BenchmarkRecord.tenant_id == tenant, BenchmarkRecord.source == _SOURCE)
            )
        ).first()
        if done is not None:
            continue
        service = CostBenchmarksService(session, tenant)
        for pid in pids:
            try:
                async with session.begin_nested():
                    await service.capture_project(pid)
                counts["captured"] += 1
            except Exception:  # noqa: BLE001 - one project never stops the seed
                logger.debug("benchmark capture skipped for %s", pid, exc_info=True)
        for name, country, region, currency, fx, cost_date, gfa, spread in _SYNTHETIC:
            await service.create(
                {
                    "kind": "completed",
                    "name": name,
                    "project_type": "office",
                    "country": country,
                    "region": region,
                    "currency": currency,
                    "cost_date": cost_date,
                    "standard": "din276",
                    "gfa_m2": gfa,
                    "functional_unit": "parking_space",
                    "functional_units": (gfa / Decimal("60")).quantize(Decimal("1")),
                    "is_synthetic": True,
                    "source": _SOURCE,
                    "notes": "Synthetic completed project for the demo.",
                    "elements": _elements(gfa, fx, spread),
                }
            )
            counts["synthetic"] += 1
        await service.create(
            {
                "kind": "estimate",
                "name": "Office Harbour Gate, cost plan",
                "project_type": "office",
                "country": "DE",
                "region": "BER",
                "currency": "EUR",
                "cost_date": date.today(),
                "standard": "din276",
                "gfa_m2": Decimal("6000"),
                "functional_unit": "parking_space",
                "functional_units": Decimal("100"),
                "is_synthetic": True,
                "source": _SOURCE,
                "notes": "Demo estimate: external walls far above the band, heating far below it.",
                "elements": _elements(
                    Decimal("6000"), Decimal("1"), Decimal("1"), {"330": Decimal("900"), "420": Decimal("35")}
                ),
            }
        )
        counts["estimates"] += 1
    await session.flush()
    return counts
