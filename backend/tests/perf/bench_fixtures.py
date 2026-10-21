"""Deterministic fixtures for the contacts and GAEB benchmarks (not a test module)."""

from __future__ import annotations

import random
import uuid
from datetime import date
from decimal import Decimal

_WORDS = ("Nord", "Bau", "Stahl", "Beton", "Tief", "Hoch", "Ost", "West", "Alpha", "Terra", "Metro", "Prime")
_KINDS = ("GmbH", "Ltd", "LLC", "SA", "BV", "AG", "Inc")
_TYPES = ("client", "subcontractor", "supplier", "consultant")


def contact_rows(n: int, tenant_id: str, seed: int = 529) -> list[dict]:
    """``n`` contact column dicts; names repeat on purpose so the id tiebreak is exercised."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        name = f"{rng.choice(_WORDS)} {rng.choice(_WORDS)} {rng.randrange(n // 4 or 1):05d} {rng.choice(_KINDS)}"
        rows.append(
            {
                "id": uuid.UUID(int=rng.getrandbits(128), version=4),
                "contact_type": rng.choice(_TYPES),
                "company_name": name if i % 5 else name.lower(),
                "primary_email": f"c{i}@bench.example",
                "country_code": rng.choice(("DE", "GB", "US", "FR")),
                "is_active": True,
                "tenant_id": tenant_id,
                "created_by": tenant_id,
            }
        )
    return rows


def gaeb_x31_bytes(lines: int = 10_000) -> bytes:
    """A schema-shaped GAEB X31 file with ``lines`` measured positions."""
    from app.modules.boq.gaeb_x31 import build_x31_xml

    rng = random.Random(529)
    entries = [
        (f"{i // 100 + 1:02d}.{(i % 100 + 1) * 10:04d}", Decimal(rng.randrange(1, 10**6)) / Decimal(100))
        for i in range(lines)
    ]
    export = build_x31_xml(entries, boq_name="BENCH", project_name="Benchmark", today=date(2026, 1, 1))
    if export.skipped:
        raise RuntimeError(f"{len(export.skipped)} generated ordinals were rejected")
    return export.xml.encode("utf-8")
