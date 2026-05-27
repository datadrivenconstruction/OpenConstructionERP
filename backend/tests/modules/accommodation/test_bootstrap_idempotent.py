"""Bootstrap PropDev block → Accommodation rooms.

Two runs in a row must produce the same final room set; ``rooms_created``
on the second pass must be zero.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def propdev_block_with_plots(project_id: str) -> tuple[str, list[str]]:
    """Seed a PropDev Development + Phase + Block + 3 Plots directly via ORM.

    Returns ``(block_id, [plot_number, ...])`` for assertions.
    """
    from app.database import async_session_factory
    from app.modules.property_dev.models import (
        Block,
        Development,
        Phase,
        Plot,
    )

    async with async_session_factory() as session:
        dev = Development(
            project_id=uuid.UUID(project_id),
            code=f"DEV-{uuid.uuid4().hex[:8].upper()}",
            name="Bootstrap Test Dev",
        )
        session.add(dev)
        await session.flush()

        phase = Phase(
            development_id=dev.id,
            code="P1",
            name="Phase 1",
        )
        session.add(phase)
        await session.flush()

        block = Block(
            phase_id=phase.id,
            code="B1",
            name="Block 1",
        )
        session.add(block)
        await session.flush()

        plot_numbers = ["U-001", "U-002", "U-003"]
        for pn in plot_numbers:
            session.add(
                Plot(
                    development_id=dev.id,
                    plot_number=pn,
                    block_id=block.id,
                    area_m2=Decimal("45.0"),
                    currency="EUR",
                    metadata_={"bim_element_id": f"elem-{pn}"},
                )
            )
        await session.commit()
        return str(block.id), plot_numbers


@pytest.mark.asyncio
async def test_bootstrap_creates_rooms_then_is_idempotent(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
    propdev_block_with_plots: tuple[str, list[str]],
):
    block_id, plot_numbers = propdev_block_with_plots
    _, header = admin_auth

    accom = await client.post(
        "/api/v1/accommodation/",
        json={
            "project_id": project_id,
            "name": "Bootstrap Camp",
            "kind": "worker_camp",
        },
        headers=header,
    )
    accom_id = accom.json()["id"]

    # First run.
    first = await client.post(
        f"/api/v1/accommodation/{accom_id}/bootstrap-from-propdev/{block_id}",
        headers=header,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["rooms_created"] == len(plot_numbers)
    assert body["rooms_skipped"] == 0
    assert body["total_rooms"] == len(plot_numbers)

    # Confirm rooms exist with the expected labels.
    rooms = await client.get(
        f"/api/v1/accommodation/{accom_id}/rooms",
        headers=header,
    )
    labels = {r["label"] for r in rooms.json()}
    assert labels == set(plot_numbers)
    # Check at least one room carries the bim_element_id we seeded.
    seeded_bim = [r for r in rooms.json() if r.get("bim_element_id")]
    assert seeded_bim, "bim_element_id not propagated from plot metadata"

    # Second run — must NOT duplicate.
    second = await client.post(
        f"/api/v1/accommodation/{accom_id}/bootstrap-from-propdev/{block_id}",
        headers=header,
    )
    assert second.status_code == 200, second.text
    body2 = second.json()
    assert body2["rooms_created"] == 0
    assert body2["rooms_skipped"] == len(plot_numbers)
    assert body2["total_rooms"] == len(plot_numbers)

    # The room count on the accommodation must equal the original plot count.
    rooms2 = await client.get(
        f"/api/v1/accommodation/{accom_id}/rooms",
        headers=header,
    )
    assert len({r["label"] for r in rooms2.json()}) == len(plot_numbers)


@pytest.mark.asyncio
async def test_bootstrap_missing_block_404(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    accom = await client.post(
        "/api/v1/accommodation/",
        json={
            "project_id": project_id,
            "name": "BootstrapMiss",
            "kind": "worker_camp",
        },
        headers=header,
    )
    accom_id = accom.json()["id"]

    bogus = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/accommodation/{accom_id}/bootstrap-from-propdev/{bogus}",
        headers=header,
    )
    assert resp.status_code == 404
