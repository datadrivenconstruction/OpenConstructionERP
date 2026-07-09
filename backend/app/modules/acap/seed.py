"""Idempotent AHSP coefficient database seed.

Loads the YAML data via :mod:`app.modules.acap.loader` and upserts every
coefficient by its unique ``kode``.  Child resources are **replaced** (delete old
rows, insert new ones) per coefficient so the seed is idempotent — running it
twice yields the same row counts.

Runnable from the container: ``python -m app.modules.acap.seed``
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def seed_ahsp(
    session: AsyncSession,
    data_dir: str | Path | None = None,
) -> int:
    """Upsert all AHSP coefficients and their resources from YAML data.

    *data_dir* defaults to :data:`app.modules.acap.loader.DEFAULT_DATA_DIR`.

    Returns the total number of coefficients upserted.
    """
    from sqlalchemy import delete, select

    from app.modules.acap.loader import DEFAULT_DATA_DIR, load_ahsp_dir
    from app.modules.acap.models.coefficients import AhspCoefficient, AhspResource

    path = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    items = load_ahsp_dir(path)

    count = 0
    for item in items:
        # ── Find or create coefficient ──────────────────────────────
        stmt = select(AhspCoefficient).where(AhspCoefficient.kode == item["kode"])
        result = await session.execute(stmt)
        coeff = result.scalar_one_or_none()

        is_new = coeff is None

        if is_new:
            coeff = AhspCoefficient(
                kode=item["kode"],
                uraian=item["uraian"],
                satuan=item["satuan"],
                kategori=item["kategori"],
                referensi=item["referensi"],
                referensi_kode=item.get("referensi_kode"),
                sumber=item["sumber"],
            )
            session.add(coeff)
        else:
            coeff.uraian = item["uraian"]
            coeff.satuan = item["satuan"]
            coeff.kategori = item["kategori"]
            coeff.referensi = item["referensi"]
            coeff.referensi_kode = item.get("referensi_kode")
            coeff.sumber = item["sumber"]

        # Flush so coeff.id is populated (needed for FK on resources)
        await session.flush()

        # ── Replace resources (delete old, insert new) ───────────────
        if not is_new:
            await session.execute(
                delete(AhspResource).where(AhspResource.coefficient_id == coeff.id)
            )

        for res in item["bahan"]:
            session.add(
                AhspResource(
                    coefficient_id=coeff.id,
                    tipe="bahan",
                    nama=res["nama"],
                    satuan=res.get("satuan"),
                    koef=Decimal(str(res["koef"])),
                )
            )

        for res in item["tenaga"]:
            session.add(
                AhspResource(
                    coefficient_id=coeff.id,
                    tipe="tenaga",
                    nama=res["jabatan"],
                    satuan="OH",
                    koef=Decimal(str(res["koef_oh"])),
                )
            )

        for res in item["alat"]:
            session.add(
                AhspResource(
                    coefficient_id=coeff.id,
                    tipe="alat",
                    nama=res["nama"],
                    satuan=res.get("satuan"),
                    koef=Decimal(str(res["koef"])),
                )
            )

        count += 1

    await session.commit()
    logger.info("AHSP seed: upserted %d coefficients", count)
    return count


# ── Runnable entrypoint ────────────────────────────────────────────────────
async def _main() -> None:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        count = await seed_ahsp(session)
        print(f"Seeded {count} AHSP coefficients")


if __name__ == "__main__":
    asyncio.run(_main())
