# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rule V19 on real PostgreSQL: an Egyptian payment waits for the social insurance clearance.

Builds on the invented subcontract of ``test_payment_release_pg``. The project
is moved to Egypt and the contract's counterparty is a subcontractor record;
the clearance is a certificate on that record. Gated by ``OE_TEST_DB=pg``.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.contracts.models import Contract
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Certificate, Subcontractor
from tests.pg.test_payment_release_pg import BASE, TERMS, World, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _to_egypt(world: World) -> Subcontractor:  # noqa: F811
    project = await world.session.get(Project, world.project_id)
    project.country_code = "EG"
    sub = Subcontractor(legal_name="Masonry Contractor SAE")
    world.session.add(sub)
    await world.session.flush()
    contract = await world.session.get(Contract, world.contract_id)
    contract.counterparty_id = sub.id
    await world.session.flush()
    return sub


def _missing(findings: dict) -> list[dict]:
    return [f for f in findings["findings"] if f["rule_id"] == "payment_release.release_certificates"]


async def test_a_contract_set_to_block_refuses_the_release_until_the_clearance_is_shown(world: World) -> None:  # noqa: F811
    sub = await _to_egypt(world)
    invoice = world.invoices["i1"]
    async with world.client() as client:
        put = await client.put(
            f"{BASE}/contracts/{world.contract_id}/terms/", json={**TERMS, "release_certificates_enforcement": "block"}
        )
        assert put.status_code == 200, put.text
        assert put.json()["release_certificates_enforcement"] == "block"
        refused = await client.post(f"{BASE}/invoices/{invoice.id}/release/")
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["problem"] == "release_blocked_by_findings"
        world.session.add(
            Certificate(
                subcontractor_id=sub.id,
                cert_type="social_security_clearance",
                issue_date=date(2026, 1, 1),
                valid_until=date(2099, 12, 31),
            )
        )
        await world.session.flush()
        released = await client.post(f"{BASE}/invoices/{invoice.id}/release/")
        assert released.status_code == 200, released.text


async def test_the_egyptian_pack_alone_warns_and_lets_the_payment_through(world: World) -> None:  # noqa: F811
    await _to_egypt(world)
    async with world.client() as client:
        put = await client.put(f"{BASE}/contracts/{world.contract_id}/terms/", json=TERMS)
        assert put.json()["release_certificates_enforcement"] == "pack"
        found = (await client.get(f"{BASE}/projects/{world.project_id}/findings/")).json()
        warnings = _missing(found)
        assert {f["element_ref"] for f in warnings} == {str(i.id) for i in world.invoices.values()}
        assert {f["severity"] for f in warnings} == {"warning"}
        released = await client.post(f"{BASE}/invoices/{world.invoices['i1'].id}/release/")
        assert released.status_code == 200, released.text


async def test_a_project_outside_egypt_never_asks_for_the_clearance(world: World) -> None:  # noqa: F811
    async with world.client() as client:
        await client.put(
            f"{BASE}/contracts/{world.contract_id}/terms/", json={**TERMS, "release_certificates_enforcement": "block"}
        )
        found = (await client.get(f"{BASE}/projects/{world.project_id}/findings/")).json()
        assert _missing(found) == []
        released = await client.post(f"{BASE}/invoices/{world.invoices['i1'].id}/release/")
        assert released.status_code == 200, released.text
