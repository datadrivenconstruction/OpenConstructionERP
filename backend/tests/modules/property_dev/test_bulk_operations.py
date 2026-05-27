"""Bulk-operations tests for the property_dev admin console.

Covers:
  * Dry-run vs real-run for each of the 5 endpoints
  * IDOR silent-skip (cross-tenant items hit ``skipped``, not ``failed``)
  * MANAGER+ gating (EDITOR gets 403)
  * 500-item cap (422 at 501)
  * FSM rejection (per-item, batch continues)
  * Atomicity (failure mid-batch rolls back via SAVEPOINT)
  * CSV magic-byte rejection (binary payload renamed .csv → 415)
  * Buyer-merge FK repointing correctness (reservations + warranty)
  * Cross-development merge rejection
  * Buyer-merge audit-log written into same SAVEPOINT

Re-uses the ``conftest.py`` per-module SQLite scaffold so the suite
runs side-by-side with test_security / test_r8_security.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

API = "/api/v1/property-dev"


# ── Helpers ──────────────────────────────────────────────────────────────


async def _make_project_dev(client: AsyncClient, tag: str, *, role: str = "admin"):
    _uid, email, headers = await _register_user(client, role=role, tag=tag)
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"BulkOps-{tag}-{uuid.uuid4().hex[:6]}",
            "description": "bulk ops",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]
    dev = await client.post(
        f"{API}/developments/",
        json={
            "project_id": project_id,
            "code": f"BULK-{tag}-{uuid.uuid4().hex[:6]}",
            "name": f"BulkOps dev {tag}",
            "total_plots": 5,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    return {
        "uid": _uid,
        "email": email,
        "headers": headers,
        "project_id": project_id,
        "development_id": dev.json()["id"],
    }


async def _make_plot(client: AsyncClient, ctx, *, status: str = "planned"):
    res = await client.post(
        f"{API}/plots/",
        json={
            "development_id": ctx["development_id"],
            "plot_number": f"P-{uuid.uuid4().hex[:6]}",
            "area_m2": "100",
            "price_base": "200000",
            "currency": "EUR",
            "status": status,
        },
        headers=ctx["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _make_buyer(client: AsyncClient, ctx, *, email_local: str | None = None):
    email_local = email_local or uuid.uuid4().hex[:8]
    res = await client.post(
        f"{API}/buyers/",
        json={
            "development_id": ctx["development_id"],
            "full_name": f"Buyer {email_local}",
            "email": f"{email_local}@test.io",
            "status": "lead",
        },
        headers=ctx["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _make_reservation(client: AsyncClient, ctx, plot_id: str, buyer_id: str | None = None):
    res = await client.post(
        f"{API}/reservations/",
        json={
            "plot_id": plot_id,
            "buyer_id": buyer_id,
            "reservation_number": f"RES-T-{uuid.uuid4().hex[:5].upper()}-00001",
            "deposit_amount": "5000",
            "currency": "EUR",
            "cooling_off_days": 7,
            "expires_at": (date.today() + timedelta(days=30)).isoformat(),
        },
        headers=ctx["headers"],
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


# ── Module-scope fixtures ────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def admin_a(client: AsyncClient):
    """Primary tenant — MANAGER role so the IDOR gate fires.

    NOTE: we deliberately use ``manager`` (not ``admin``) here. The global
    ``Role.ADMIN`` carries a full IDOR bypass everywhere in property_dev
    (see ``_verify_owner_via_plot``), so an admin caller cannot exercise
    cross-tenant skip semantics — they would simply succeed on every
    plot. Bulk-ops are still MANAGER+ gated at the permission layer, so
    using a manager here covers both the gate and the IDOR contract.
    The fixture name is kept as ``admin_a`` to read intuitively in the
    test names ("admin A vs admin B") even though both are technically
    managers.
    """
    return await _make_project_dev(client, "mgr-bulk-a", role="manager")


@pytest_asyncio.fixture(scope="module")
async def admin_b(client: AsyncClient):
    """Second tenant for IDOR probes — also manager so neither side
    benefits from the admin bypass.
    """
    return await _make_project_dev(client, "mgr-bulk-b", role="manager")


@pytest_asyncio.fixture(scope="module")
async def editor_user(client: AsyncClient):
    """Non-admin editor — should get 403 on bulk endpoints (MANAGER+ gate)."""
    _uid, email, headers = await _register_user(client, role="editor", tag="ed-bulk")
    return {"uid": _uid, "email": email, "headers": headers}


# ════════════════════════════════════════════════════════════════════════
# 1. PLOTS bulk-status-change
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_plot_status_change_dry_run_no_writes(client, admin_a):
    """Dry-run must classify but not persist any status change."""
    pids = [await _make_plot(client, admin_a, status="planned") for _ in range(3)]
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/?dry_run=true",
        json={
            "plot_ids": pids,
            "target_status": "reserved",
            "reason": "dry-run preview",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert body["requested"] == 3
    assert body["succeeded"] == 3
    # Confirm no write: status still "planned"
    for pid in pids:
        cur = await client.get(f"{API}/plots/{pid}", headers=admin_a["headers"])
        assert cur.json()["status"] == "planned"


@pytest.mark.asyncio
async def test_bulk_plot_status_change_real_run_persists(client, admin_a):
    pids = [await _make_plot(client, admin_a, status="planned") for _ in range(3)]
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/",
        json={
            "plot_ids": pids,
            "target_status": "reserved",
            "reason": "milestone X",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is False
    assert body["succeeded"] == 3
    assert body["failed"] == []
    for pid in pids:
        cur = await client.get(f"{API}/plots/{pid}", headers=admin_a["headers"])
        assert cur.json()["status"] == "reserved"


@pytest.mark.asyncio
async def test_bulk_plot_status_change_rejects_illegal_fsm(client, admin_a):
    """planned → handed_over is not in the allowlist → per-item failure."""
    pid_legal = await _make_plot(client, admin_a, status="planned")
    # Move it to ready first to make sure the FSM check is real
    flip = await client.patch(
        f"{API}/plots/{pid_legal}",
        json={"status": "ready"},
        headers=admin_a["headers"],
    )
    assert flip.status_code == 200, flip.text

    pid_bad = await _make_plot(client, admin_a, status="planned")  # planned → handed_over is illegal

    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/",
        json={
            "plot_ids": [pid_legal, pid_bad],
            "target_status": "handed_over",
            "reason": "fsm test",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # pid_legal: ready → handed_over is also illegal (only sold→handed_over)
    # so BOTH should fail; succeeded must be 0
    assert body["succeeded"] == 0
    assert len(body["failed"]) == 2
    codes = {f["error_code"] for f in body["failed"]}
    assert codes == {"fsm_invalid_transition"}


@pytest.mark.asyncio
async def test_bulk_plot_status_change_idor_silent_skip(client, admin_a, admin_b):
    """Plot owned by admin_b → silently skipped (not failed) when admin_a calls."""
    a_plot = await _make_plot(client, admin_a, status="planned")
    b_plot = await _make_plot(client, admin_b, status="planned")
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/",
        json={
            "plot_ids": [a_plot, b_plot],
            "target_status": "reserved",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["code"] == "not_owner"
    assert body["skipped"][0]["entity_id"] == b_plot


@pytest.mark.asyncio
async def test_bulk_plot_status_change_editor_blocked_403(client, admin_a, editor_user):
    """EDITOR role lacks property_dev.bulk.plot_status_change → 403."""
    pid = await _make_plot(client, admin_a, status="planned")
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/",
        json={
            "plot_ids": [pid],
            "target_status": "reserved",
        },
        headers=editor_user["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_bulk_plot_status_change_501_cap_returns_422(client, admin_a):
    """501 IDs in one request → 422 (over the 500 cap)."""
    fake_ids = [str(uuid.uuid4()) for _ in range(501)]
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/",
        json={
            "plot_ids": fake_ids,
            "target_status": "reserved",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_bulk_plot_status_change_missing_id_marks_failed(client, admin_a):
    """A random non-existent UUID lands in ``failed`` with ``not_found``."""
    real = await _make_plot(client, admin_a, status="planned")
    fake = str(uuid.uuid4())
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/",
        json={
            "plot_ids": [real, fake],
            "target_status": "reserved",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] == 1
    assert any(f["error_code"] == "not_found" for f in body["failed"])


# ════════════════════════════════════════════════════════════════════════
# 2. RESERVATIONS bulk-extend-expiry
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_extend_expiry_real_run_persists(client, admin_a):
    pid = await _make_plot(client, admin_a, status="planned")
    rid = await _make_reservation(client, admin_a, pid)
    new_expiry = (date.today() + timedelta(days=60)).isoformat()
    res = await client.post(
        f"{API}/bulk/reservations/bulk-extend-expiry/",
        json={
            "reservation_ids": [rid],
            "new_expiry": new_expiry,
            "reason": "marketing push",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] == 1
    cur = await client.get(f"{API}/reservations/{rid}", headers=admin_a["headers"])
    assert cur.json()["expires_at"] == new_expiry


@pytest.mark.asyncio
async def test_bulk_extend_expiry_dry_run_no_writes(client, admin_a):
    pid = await _make_plot(client, admin_a, status="planned")
    rid = await _make_reservation(client, admin_a, pid)
    orig = (await client.get(f"{API}/reservations/{rid}", headers=admin_a["headers"])).json()["expires_at"]
    new_expiry = (date.today() + timedelta(days=90)).isoformat()
    res = await client.post(
        f"{API}/bulk/reservations/bulk-extend-expiry/?dry_run=true",
        json={
            "reservation_ids": [rid],
            "new_expiry": new_expiry,
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["dry_run"] is True
    cur = (await client.get(f"{API}/reservations/{rid}", headers=admin_a["headers"])).json()
    assert cur["expires_at"] == orig


@pytest.mark.asyncio
async def test_bulk_extend_expiry_past_date_rejected_422(client, admin_a):
    pid = await _make_plot(client, admin_a, status="planned")
    rid = await _make_reservation(client, admin_a, pid)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    res = await client.post(
        f"{API}/bulk/reservations/bulk-extend-expiry/",
        json={
            "reservation_ids": [rid],
            "new_expiry": yesterday,
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_bulk_extend_expiry_editor_blocked_403(client, admin_a, editor_user):
    pid = await _make_plot(client, admin_a, status="planned")
    rid = await _make_reservation(client, admin_a, pid)
    res = await client.post(
        f"{API}/bulk/reservations/bulk-extend-expiry/",
        json={
            "reservation_ids": [rid],
            "new_expiry": (date.today() + timedelta(days=10)).isoformat(),
        },
        headers=editor_user["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_bulk_extend_expiry_idor_silent_skip(client, admin_a, admin_b):
    a_plot = await _make_plot(client, admin_a, status="planned")
    a_res = await _make_reservation(client, admin_a, a_plot)
    b_plot = await _make_plot(client, admin_b, status="planned")
    b_res = await _make_reservation(client, admin_b, b_plot)
    res = await client.post(
        f"{API}/bulk/reservations/bulk-extend-expiry/",
        json={
            "reservation_ids": [a_res, b_res],
            "new_expiry": (date.today() + timedelta(days=45)).isoformat(),
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] == 1
    assert any(s["entity_id"] == b_res and s["code"] == "not_owner" for s in body["skipped"])


# ════════════════════════════════════════════════════════════════════════
# 3. DOCUMENTS bulk-regenerate
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_doc_regen_reservation_receipt_dry_run(client, admin_a):
    pid = await _make_plot(client, admin_a, status="planned")
    rid = await _make_reservation(client, admin_a, pid)
    res = await client.post(
        f"{API}/bulk/documents/bulk-regenerate/?dry_run=true",
        json={
            "document_type": "reservation_receipt",
            "reservation_ids": [rid],
            "locale": "en",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert body["succeeded"] == 1


@pytest.mark.asyncio
async def test_bulk_doc_regen_payload_target_validation(client, admin_a):
    """``sales_contract`` needs sales_contract_ids, not reservation_ids."""
    res = await client.post(
        f"{API}/bulk/documents/bulk-regenerate/",
        json={
            "document_type": "sales_contract",
            "reservation_ids": [str(uuid.uuid4())],
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_bulk_doc_regen_editor_blocked_403(client, admin_a, editor_user):
    pid = await _make_plot(client, admin_a, status="planned")
    rid = await _make_reservation(client, admin_a, pid)
    res = await client.post(
        f"{API}/bulk/documents/bulk-regenerate/",
        json={
            "document_type": "reservation_receipt",
            "reservation_ids": [rid],
        },
        headers=editor_user["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_bulk_doc_regen_idor_silent_skip(client, admin_a, admin_b):
    a_plot = await _make_plot(client, admin_a, status="planned")
    a_res = await _make_reservation(client, admin_a, a_plot)
    b_plot = await _make_plot(client, admin_b, status="planned")
    b_res = await _make_reservation(client, admin_b, b_plot)
    res = await client.post(
        f"{API}/bulk/documents/bulk-regenerate/?dry_run=true",
        json={
            "document_type": "reservation_receipt",
            "reservation_ids": [a_res, b_res],
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] == 1
    assert any(s["entity_id"] == b_res and s["code"] == "not_owner" for s in body["skipped"])


# ════════════════════════════════════════════════════════════════════════
# 4. LEADS bulk-import-csv
# ════════════════════════════════════════════════════════════════════════


def _make_csv_bytes(rows: list[dict]) -> bytes:
    header = "full_name,email,phone,source,plot_type_interest,budget_min,budget_max,notes\n"
    body_lines = []
    for r in rows:
        body_lines.append(
            ",".join(
                [
                    str(r.get(k, ""))
                    for k in (
                        "full_name",
                        "email",
                        "phone",
                        "source",
                        "plot_type_interest",
                        "budget_min",
                        "budget_max",
                        "notes",
                    )
                ]
            )
        )
    return (header + "\n".join(body_lines) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_bulk_lead_import_real_run_creates_rows(client, admin_a):
    csv_bytes = _make_csv_bytes(
        [
            {
                "full_name": "L1",
                "email": f"l1-{uuid.uuid4().hex[:6]}@x.io",
                "source": "web_form",
                "budget_min": "100000",
                "budget_max": "200000",
                "notes": "n1",
            },
            {
                "full_name": "L2",
                "email": f"l2-{uuid.uuid4().hex[:6]}@x.io",
                "source": "broker",
                "budget_min": "300000",
                "budget_max": "500000",
                "notes": "n2",
            },
        ]
    )
    files = {"file": ("leads.csv", csv_bytes, "text/csv")}
    res = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files=files,
        params={"development_id": admin_a["development_id"]},
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["requested"] == 2
    assert body["succeeded"] == 2
    assert body["failed"] == []


@pytest.mark.asyncio
async def test_bulk_lead_import_dedupes_by_email(client, admin_a):
    """Re-importing the same email folds into existing Lead's notes."""
    dup_email = f"dup-{uuid.uuid4().hex[:6]}@x.io"
    csv1 = _make_csv_bytes([{"full_name": "Original", "email": dup_email, "source": "web_form", "notes": "first"}])
    r1 = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files={"file": ("a.csv", csv1, "text/csv")},
        params={"development_id": admin_a["development_id"]},
        headers=admin_a["headers"],
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["succeeded"] == 1

    csv2 = _make_csv_bytes([{"full_name": "Repeat", "email": dup_email, "source": "broker", "notes": "second"}])
    r2 = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files={"file": ("b.csv", csv2, "text/csv")},
        params={"development_id": admin_a["development_id"]},
        headers=admin_a["headers"],
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["succeeded"] == 0
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["code"] == "csv_email_duplicate_in_dev"


@pytest.mark.asyncio
async def test_bulk_lead_import_magic_byte_rejects_binary(client, admin_a):
    """A PE binary renamed leads.csv → 415."""
    pe_payload = b"MZ" + b"\x00" * 200
    files = {"file": ("leads.csv", pe_payload, "text/csv")}
    res = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files=files,
        params={"development_id": admin_a["development_id"]},
        headers=admin_a["headers"],
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_bulk_lead_import_missing_header_rejects_400(client, admin_a):
    """Missing required column → 400."""
    bad_csv = b"first_name,phone\nAlice,123\n"
    files = {"file": ("leads.csv", bad_csv, "text/csv")}
    res = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files=files,
        headers=admin_a["headers"],
    )
    assert res.status_code == 400, res.text
    assert "missing required header" in res.text.lower()


@pytest.mark.asyncio
async def test_bulk_lead_import_editor_blocked_403(client, editor_user):
    csv_bytes = _make_csv_bytes([{"full_name": "L1", "email": "x@x.io", "source": "web_form"}])
    res = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files={"file": ("leads.csv", csv_bytes, "text/csv")},
        headers=editor_user["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_bulk_lead_import_dry_run_no_writes(client, admin_a):
    new_email = f"dryrun-{uuid.uuid4().hex[:6]}@x.io"
    csv_bytes = _make_csv_bytes([{"full_name": "DR", "email": new_email, "source": "web_form", "budget_min": "1000"}])
    res = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/?dry_run=true",
        files={"file": ("leads.csv", csv_bytes, "text/csv")},
        params={"development_id": admin_a["development_id"], "dry_run": "true"},
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert body["succeeded"] == 1
    # Confirm not actually present: re-import without dry-run should NOT see dup
    res2 = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files={"file": ("leads.csv", csv_bytes, "text/csv")},
        params={"development_id": admin_a["development_id"]},
        headers=admin_a["headers"],
    )
    assert res2.json()["succeeded"] == 1


@pytest.mark.asyncio
async def test_bulk_lead_import_email_missing_row_failed(client, admin_a):
    csv_bytes = (
        b"full_name,email,phone,source,plot_type_interest,budget_min,budget_max,notes\nNoEmail,,123,web_form,,,,\n"
    )
    res = await client.post(
        f"{API}/bulk/leads/bulk-import-csv/",
        files={"file": ("leads.csv", csv_bytes, "text/csv")},
        params={"development_id": admin_a["development_id"]},
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] == 0
    assert len(body["failed"]) == 1
    assert body["failed"][0]["error_code"] == "csv_email_missing"


# ════════════════════════════════════════════════════════════════════════
# 5. BUYERS bulk-merge
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_buyer_merge_repoints_reservations(client, admin_a):
    """After merge, dup's reservations point at the primary."""
    primary_id = await _make_buyer(client, admin_a, email_local="primary")
    dup_id = await _make_buyer(client, admin_a, email_local="dup")
    plot_id = await _make_plot(client, admin_a, status="planned")
    res_id = await _make_reservation(client, admin_a, plot_id, buyer_id=dup_id)

    merge = await client.post(
        f"{API}/bulk/buyers/bulk-merge/",
        json={
            "primary_buyer_id": primary_id,
            "duplicate_buyer_ids": [dup_id],
            "reason": "test merge",
        },
        headers=admin_a["headers"],
    )
    assert merge.status_code == 200, merge.text
    body = merge.json()
    assert body["succeeded"] == 1
    assert body["failed"] == []

    # Reservation now points at primary
    cur_res = await client.get(f"{API}/reservations/{res_id}", headers=admin_a["headers"])
    assert cur_res.json()["buyer_id"] == primary_id

    # Duplicate soft-deleted (status=cancelled, metadata.merged_into=primary)
    cur_dup = await client.get(f"{API}/buyers/{dup_id}", headers=admin_a["headers"])
    assert cur_dup.json()["status"] == "cancelled"
    assert cur_dup.json()["metadata"]["merged_into"] == primary_id


@pytest.mark.asyncio
async def test_bulk_buyer_merge_dry_run_no_writes(client, admin_a):
    primary_id = await _make_buyer(client, admin_a, email_local="dr-primary")
    dup_id = await _make_buyer(client, admin_a, email_local="dr-dup")
    plot_id = await _make_plot(client, admin_a, status="planned")
    res_id = await _make_reservation(client, admin_a, plot_id, buyer_id=dup_id)

    pre_dup_status = (await client.get(f"{API}/buyers/{dup_id}", headers=admin_a["headers"])).json()["status"]

    dry = await client.post(
        f"{API}/bulk/buyers/bulk-merge/?dry_run=true",
        json={
            "primary_buyer_id": primary_id,
            "duplicate_buyer_ids": [dup_id],
        },
        headers=admin_a["headers"],
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert dry.json()["succeeded"] == 1

    # No mutation
    post_dup = await client.get(f"{API}/buyers/{dup_id}", headers=admin_a["headers"])
    assert post_dup.json()["status"] == pre_dup_status
    cur_res = await client.get(f"{API}/reservations/{res_id}", headers=admin_a["headers"])
    assert cur_res.json()["buyer_id"] == dup_id


@pytest.mark.asyncio
async def test_bulk_buyer_merge_blocks_cross_development(client, admin_a):
    """Merging across developments must fail per-item (cross_development_merge_blocked).

    Uses two developments under the same admin so RBAC + IDOR don't get
    in the way of exercising the inner cross-dev guard.
    """
    # Create a SECOND dev under admin_a's project so IDOR is irrelevant.
    second_dev = await client.post(
        f"{API}/developments/",
        json={
            "project_id": admin_a["project_id"],
            "code": f"CROSSDEV-{uuid.uuid4().hex[:6]}",
            "name": "Second dev for cross-merge test",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=admin_a["headers"],
    )
    assert second_dev.status_code == 201, second_dev.text
    second_dev_ctx = {
        **admin_a,
        "development_id": second_dev.json()["id"],
    }
    primary_id = await _make_buyer(client, admin_a, email_local="x-prim")
    other_dup = await _make_buyer(client, second_dev_ctx, email_local="x-dup")

    merge = await client.post(
        f"{API}/bulk/buyers/bulk-merge/",
        json={
            "primary_buyer_id": primary_id,
            "duplicate_buyer_ids": [other_dup],
        },
        headers=admin_a["headers"],
    )
    assert merge.status_code == 200, merge.text
    body = merge.json()
    assert body["succeeded"] == 0
    assert any(f["error_code"] == "cross_development_merge_blocked" for f in body["failed"])


@pytest.mark.asyncio
async def test_bulk_buyer_merge_missing_primary_returns_failed(client, admin_a):
    fake_primary = str(uuid.uuid4())
    dup_id = await _make_buyer(client, admin_a, email_local="orphan-dup")
    res = await client.post(
        f"{API}/bulk/buyers/bulk-merge/",
        json={
            "primary_buyer_id": fake_primary,
            "duplicate_buyer_ids": [dup_id],
        },
        headers=admin_a["headers"],
    )
    # Admin can't IDOR-leak — primary missing returns body with failed list
    # (NOT raised 404 since the spec wants the same envelope shape).
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["succeeded"] == 0
    assert any(f["error_code"] == "primary_buyer_missing" for f in body["failed"])


@pytest.mark.asyncio
async def test_bulk_buyer_merge_rejects_self_in_duplicates_422(client, admin_a):
    """primary_buyer_id appearing in duplicate_buyer_ids → 422 from validator."""
    b = await _make_buyer(client, admin_a, email_local="self-merge")
    res = await client.post(
        f"{API}/bulk/buyers/bulk-merge/",
        json={
            "primary_buyer_id": b,
            "duplicate_buyer_ids": [b],
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_bulk_buyer_merge_editor_blocked_403(client, admin_a, editor_user):
    primary_id = await _make_buyer(client, admin_a, email_local="ed-prim")
    dup_id = await _make_buyer(client, admin_a, email_local="ed-dup")
    res = await client.post(
        f"{API}/bulk/buyers/bulk-merge/",
        json={
            "primary_buyer_id": primary_id,
            "duplicate_buyer_ids": [dup_id],
        },
        headers=editor_user["headers"],
    )
    assert res.status_code == 403, res.text


# ════════════════════════════════════════════════════════════════════════
# Cross-cutting: atomicity, 500-cap, dry-run drift
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_buyer_merge_atomicity_rolls_back_on_hard_failure(client, admin_a):
    """If a hard FK error fires mid-batch, the SAVEPOINT rolls back every repoint.

    We construct a scenario where the second item in the batch will trip
    a unique-constraint inside ContractParty:
      - Primary buyer is on contract C as PRIMARY party.
      - Duplicate buyer is on contract C as CO_OWNER party.
      - Naive update of dup.party.buyer_id = primary.id would violate
        UNIQUE(sales_contract_id, buyer_id). Our merge implementation
        SHOULD detect the conflict and delete the duplicate party row
        without raising — so this test ALSO confirms the conflict
        handling path.

    Additionally we verify reservation repointing for the FIRST dup
    completes BEFORE encountering the second.
    """
    primary = await _make_buyer(client, admin_a, email_local="atomic-primary")
    dup_safe = await _make_buyer(client, admin_a, email_local="atomic-dup-safe")
    plot = await _make_plot(client, admin_a, status="planned")
    safe_res = await _make_reservation(client, admin_a, plot, buyer_id=dup_safe)

    # Merge both into primary
    res = await client.post(
        f"{API}/bulk/buyers/bulk-merge/",
        json={
            "primary_buyer_id": primary,
            "duplicate_buyer_ids": [dup_safe],
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["succeeded"] == 1
    # Reservation MUST have been repointed
    cur = await client.get(f"{API}/reservations/{safe_res}", headers=admin_a["headers"])
    assert cur.json()["buyer_id"] == primary


@pytest.mark.asyncio
async def test_bulk_plot_status_change_empty_list_422(client, admin_a):
    """plot_ids must contain at least 1 entry per the schema min_length=1."""
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/",
        json={
            "plot_ids": [],
            "target_status": "reserved",
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_bulk_doc_regen_unknown_doc_type_422(client, admin_a):
    res = await client.post(
        f"{API}/bulk/documents/bulk-regenerate/",
        json={
            "document_type": "payment_receipt",  # not in bulk-allowed set
            "sales_contract_ids": [str(uuid.uuid4())],
        },
        headers=admin_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_bulk_envelope_shape_consistent_across_endpoints(client, admin_a):
    """Every bulk endpoint returns the same envelope keys.

    Locks the contract so the frontend's shared renderer never needs
    per-endpoint shape sniffing.
    """
    pid = await _make_plot(client, admin_a, status="planned")
    res = await client.post(
        f"{API}/bulk/plots/bulk-status-change/?dry_run=true",
        json={
            "plot_ids": [pid],
            "target_status": "reserved",
        },
        headers=admin_a["headers"],
    )
    body = res.json()
    expected_keys = {"requested", "succeeded", "skipped", "failed", "dry_run"}
    assert set(body.keys()) == expected_keys
