"""Haul ticket API: create, weights, statuses, verify gate, scan, import, summary, invoice, actuals."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient

BASE = "/api/v1/haul-tickets"
SIG = "data:image/png;base64,iVBORw0KGgo="


async def _create(client, header, project_id, **extra):
    body = {
        "project_id": project_id,
        "ticket_number": extra.pop("ticket_number", uuid.uuid4().hex[:6]),
        "haul_type": "aggregates",
        "ticket_date": "2026-10-30",
        "material_code": "gravel",
        "material_name": "Gravel",
        "unit": "t",
        "gross_t": "32.5",
        "tare_t": "14.2",
        "haulier_name": "Kies AG",
        "plate": "AB 123",
        "rate_basis": "t",
        "rate": "7.25",
        "cost_code": "EW-01",
        **extra,
    }
    resp = await client.post(f"{BASE}/tickets/", json=body, headers=header)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_ticket_lifecycle_and_verify_gate(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    t = await _create(client, header, project_id, ticket_number="T-100")
    assert t["net_t"] == "18.300"
    assert t["quantity"] == "18.300"
    assert t["amount"] == "132.68"
    assert t["status"] == "issued"

    # Same client op id twice creates one ticket.
    op = uuid.uuid4().hex
    a = await _create(client, header, project_id, client_op_id=op)
    b = await _create(client, header, project_id, client_op_id=op)
    assert a["id"] == b["id"]

    tid = t["id"]
    bad = await client.post(f"{BASE}/tickets/{tid}/status", json={"status": "verified"}, headers=header)
    assert bad.status_code == 409
    r = await client.post(f"{BASE}/tickets/{tid}/status", json={"status": "delivered"}, headers=header)
    assert r.status_code == 200, r.text
    rule_ids = {f["rule_id"] for f in r.json()["findings"]}
    assert "haul_tickets.delivered_signed" in rule_ids
    blocked = await client.post(f"{BASE}/tickets/{tid}/status", json={"status": "verified"}, headers=header)
    assert blocked.status_code == 422
    signed = await client.patch(
        f"{BASE}/tickets/{tid}", json={"receiver_name": "Foreman", "signature": SIG}, headers=header
    )
    assert signed.status_code == 200 and signed.json()["has_signature"]
    ok = await client.post(f"{BASE}/tickets/{tid}/status", json={"status": "verified"}, headers=header)
    assert ok.status_code == 200, ok.text
    locked = await client.patch(f"{BASE}/tickets/{tid}", json={"gross_t": "40"}, headers=header)
    assert locked.status_code == 409

    no_reason = await client.post(f"{BASE}/tickets/{a['id']}/status", json={"status": "rejected"}, headers=header)
    assert no_reason.status_code == 422
    rej = await client.post(
        f"{BASE}/tickets/{a['id']}/status", json={"status": "rejected", "reason": "Wrong grade"}, headers=header
    )
    assert rej.json()["reject_reason"] == "Wrong grade"

    pdf = await client.get(f"{BASE}/tickets/{tid}/pdf", headers=header)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"

    scan = await client.get(f"{BASE}/projects/{project_id}/scan", params={"code": t["qr_token"]}, headers=header)
    assert scan.json() == {"kind": "ticket", "ticket_id": tid}
    truck = await client.get(f"{BASE}/projects/{project_id}/scan", params={"code": "TRUCK:ab 123"}, headers=header)
    assert truck.json()["kind"] == "truck" and truck.json()["prefill"]["haulier_name"] == "Kies AG"


@pytest.mark.asyncio
async def test_duplicate_number_overweight_and_settings(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    put = await client.put(
        f"{BASE}/projects/{project_id}/settings",
        json={"mandatory_fields": ["driver_name"], "max_gross_t": "30"},
        headers=header,
    )
    assert put.status_code == 200, put.text
    await _create(client, header, project_id, ticket_number="DUP-1")
    second = await _create(client, header, project_id, ticket_number="DUP-1")
    ids = {f["rule_id"] for f in second["findings"]}
    assert {"haul_tickets.unique_number_per_haulier", "haul_tickets.overweight", "haul_tickets.mandatory_fields"} <= ids
    bad = await client.put(
        f"{BASE}/projects/{project_id}/settings", json={"mandatory_fields": ["nonsense"]}, headers=header
    )
    assert bad.status_code == 422
    await client.put(f"{BASE}/projects/{project_id}/settings", json={}, headers=header)


@pytest.mark.asyncio
async def test_import_preview_commit_dedupes(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    csv_text = (
        "Ticket No,Date,Haulier,Plate,Material,Net\n"
        "W-1,2026-10-29,Haul Co,XY 1,Sand,12.5\n"
        "W-1,2026-10-29,Haul Co,XY 1,Sand,12.5\n"
        "W-2,2026-10-29,Haul Co,XY 2,Sand,11\n"
    )
    files = {"file": ("wb.csv", csv_text.encode(), "text/csv")}
    prev = await client.post(f"{BASE}/projects/{project_id}/import/preview", files=files, headers=header)
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["total"] == 3 and body["duplicates"] == 1
    commit = await client.post(
        f"{BASE}/projects/{project_id}/import/commit",
        files={"file": ("wb.csv", csv_text.encode(), "text/csv")},
        data={"mapping": json.dumps(body["mapping"]), "defaults": json.dumps({"haul_type": "aggregates"})},
        headers=header,
    )
    assert commit.status_code == 200, commit.text
    assert commit.json()["created"] == 2 and commit.json()["skipped_duplicates"] == 1
    again = await client.post(
        f"{BASE}/projects/{project_id}/import/commit",
        files={"file": ("wb.csv", csv_text.encode(), "text/csv")},
        data={"mapping": json.dumps(body["mapping"])},
        headers=header,
    )
    assert again.json()["created"] == 0


@pytest.mark.asyncio
async def test_invoice_reconcile_accept_and_summary(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    hauler = "Recon Haul " + uuid.uuid4().hex[:4]
    made = []
    for n in ("R-1", "R-2", "R-3"):
        t = await _create(
            client, header, project_id, ticket_number=n, haulier_name=hauler, receiver_name="Gate", signature=SIG
        )
        await client.post(f"{BASE}/tickets/{t['id']}/status", json={"status": "delivered"}, headers=header)
        v = await client.post(f"{BASE}/tickets/{t['id']}/status", json={"status": "verified"}, headers=header)
        assert v.status_code == 200, v.text
        made.append(t)
    inv = await client.post(
        f"{BASE}/invoices/",
        json={
            "project_id": project_id,
            "haulier_name": hauler,
            "invoice_number": "INV-1",
            "lines": [
                {"ticket_number": "R-1", "quantity": "18.3", "rate": "7.25", "amount": "132.68"},
                {"ticket_number": "R-2", "quantity": "18.3", "rate": "8.00", "amount": "146.40"},
                {"ticket_number": "R-9", "quantity": "18.3", "rate": "7.25", "amount": "132.68"},
            ],
        },
        headers=header,
    )
    assert inv.status_code == 201, inv.text
    body = inv.json()
    assert body["status"] == "discrepancies"
    assert [ln["status"] for ln in body["result"]["lines"]] == ["matched", "overpriced", "missing_ticket"]
    assert [e["ticket_number"] for e in body["result"]["extra_tickets"]] == ["R-3"]
    assert {f["rule_id"] for f in body["findings"]} == {"haul_invoice.line_has_ticket"}
    refused = await client.post(f"{BASE}/invoices/{body['id']}/accept", headers=header)
    assert refused.status_code == 422

    page = await client.get(f"{BASE}/projects/{project_id}/invoices", params={"limit": 1}, headers=header)
    assert page.status_code == 200 and page.json()["total"] >= 1
    assert page.json()["items"][0]["id"] == body["id"]
    cut = await client.get(f"{BASE}/projects/{project_id}/materials", params={"limit": 2}, headers=header)
    assert cut.status_code == 200 and len(cut.json()["items"]) == 2 and cut.json()["total"] > 2

    summary = await client.get(
        f"{BASE}/projects/{project_id}/summary", params={"group_by": "haulier", "verified_only": True}, headers=header
    )
    row = next(r for r in summary.json()["rows"] if r["key"] == hauler)
    assert row["tickets"] == 3 and row["amount"] == "398.04"

    reg = await client.get(f"{BASE}/projects/{project_id}/disposal-register", params={"format": "csv"}, headers=header)
    assert reg.status_code == 200


@pytest.mark.asyncio
async def test_project_isolation(client: AsyncClient, admin_auth, project_id, outsider_auth):
    _, header = admin_auth
    _, other = outsider_auth
    t = await _create(client, header, project_id)
    resp = await client.get(f"{BASE}/tickets/{t['id']}", headers=other)
    assert resp.status_code in (403, 404)
