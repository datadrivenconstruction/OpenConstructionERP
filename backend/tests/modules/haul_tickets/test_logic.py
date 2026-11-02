"""Haul ticket arithmetic, status machine, reconciliation and import dedupe (pure)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.modules.haul_tickets import importer, logic

D = Decimal


@pytest.mark.parametrize(
    ("gross", "tare", "net", "expected", "ok"),
    [
        ("32.5", "14.2", None, ("32.5", "14.2", "18.3"), True),
        ("32.5", None, "18.3", ("32.5", "14.2", "18.3"), True),
        (None, "14.2", "18.3", ("32.5", "14.2", "18.3"), True),
        ("32.5", "14.2", "18.3", ("32.5", "14.2", "18.3"), True),
        ("32.5", "14.2", "19.0", ("32.5", "14.2", "19.0"), False),
        ("10", "14", None, ("10", "14", "-4"), False),
        ("32,5", "14,2", None, ("32.5", "14.2", "18.3"), True),
    ],
)
def test_resolve_weights(gross, tare, net, expected, ok):
    w = logic.resolve_weights(gross, tare, net)
    assert (w.gross, w.tare, w.net) == tuple(D(x) for x in expected)
    assert w.consistent is ok


def test_quantity_in_unit_and_density():
    assert logic.quantity_in_unit("t", net_t=D("18.3"), volume_m3=None, loads=1) == D("18.300")
    assert logic.quantity_in_unit("load", net_t=D("18.3"), volume_m3=None, loads=3) == D("3")
    assert logic.quantity_in_unit("m3", net_t=D("18"), volume_m3=None, loads=1, density=D("1.8")) == D("10.000")
    assert logic.quantity_in_unit("m3", net_t=None, volume_m3=D("8"), loads=1) == D("8.000")
    assert logic.quantity_in_unit("t", net_t=None, volume_m3=None, loads=1) == D("0")


def test_amount_per_basis():
    qty = logic.billable_quantity("t", net_t=D("18.3"), volume_m3=None, loads=1, hours=None)
    assert logic.amount(D("7.25"), qty) == D("132.68")
    assert logic.amount(D("95"), logic.billable_quantity("load", net_t=None, volume_m3=None, loads=2, hours=None)) == D(
        "190.00"
    )
    assert logic.amount(
        D("80"), logic.billable_quantity("hour", net_t=None, volume_m3=None, loads=1, hours=D("1.5"))
    ) == D("120.00")
    assert logic.amount(None, D("10")) == D("0")


def test_status_machine():
    assert logic.can_transition("issued", "loaded")
    assert logic.can_transition("delivered", "verified")
    assert logic.can_transition("verified", "invoiced")
    assert logic.can_transition("rejected", "issued")
    assert not logic.can_transition("issued", "verified")
    assert not logic.can_transition("invoiced", "rejected")
    assert not logic.can_transition("invoiced", "delivered")


def _tickets():
    return [
        {
            "id": "a",
            "ticket_number": "1001",
            "status": "verified",
            "quantity": D("18"),
            "rate": D("7"),
            "amount": D("126"),
        },
        {
            "id": "b",
            "ticket_number": "1002",
            "status": "verified",
            "quantity": D("20"),
            "rate": D("7"),
            "amount": D("140"),
        },
        {
            "id": "c",
            "ticket_number": "1003",
            "status": "verified",
            "quantity": D("19"),
            "rate": D("7"),
            "amount": D("133"),
        },
        {
            "id": "d",
            "ticket_number": "1004",
            "status": "rejected",
            "quantity": D("19"),
            "rate": D("7"),
            "amount": D("133"),
        },
    ]


def test_reconcile_flags_missing_extra_overpriced():
    lines = [
        {"ticket_number": "1001", "quantity": "18", "rate": "7", "amount": "126"},
        {"ticket_number": "01002", "quantity": "20", "rate": "7.5", "amount": "150"},
        {"ticket_number": "9999", "quantity": "18", "rate": "7", "amount": "126"},
        {"ticket_number": "1001", "quantity": "18", "rate": "7", "amount": "126"},
        {"ticket_number": "1004", "quantity": "19", "rate": "7", "amount": "133"},
    ]
    r = logic.reconcile(lines, _tickets())
    statuses = [x.status for x in r.lines]
    assert statuses == ["matched", "overpriced", "missing_ticket", "duplicate_line", "rejected_ticket"]
    assert [e["ticket_number"] for e in r.extra_tickets] == ["1003"]
    assert r.invoiced_total == D("661.00")
    assert r.expected_total == D("399.00")
    assert not r.clean
    assert r.as_dict()["difference"] == "262.00"


def test_reconcile_clean_and_quantity_mismatch():
    tickets = _tickets()[:1]
    assert logic.reconcile([{"ticket_number": "1001", "quantity": "18", "rate": "7"}], tickets).clean
    r = logic.reconcile([{"ticket_number": "1001", "quantity": "21", "rate": "7"}], tickets)
    assert r.lines[0].status == "quantity_mismatch"


def test_waste_catalogue_hook():
    logic.register_waste_catalogue("test_pack", "Test pack", lambda: [{"code": "17 05 04", "hazardous": False}])
    assert "test_pack" in logic.waste_catalogues()
    assert logic.waste_entry("test_pack", "17 05 04") == {"code": "17 05 04", "hazardous": False}
    assert logic.waste_entry("generic", "HAZ")["hazardous"] is True


def test_import_mapping_and_dedupe():
    csv_bytes = (
        b"Ticket No;Date;Haulier;Registration;Material;Gross kg;Tare kg;Net kg;Time out\n"
        b"A1;2026-10-30;Kies AG;AB 123;Gravel;32500;14200;18300;2026-10-30 07:15\n"
        b"A1;2026-10-30;Kies AG;AB 123;Gravel;32500;14200;18300;2026-10-30 07:15\n"
        b"A2;30.10.2026;Kies AG;AB 124;Gravel;31000;14000;17000;30.10.2026 08:05\n"
        b"A3;2026-10-30;Kies AG;AB 125;Gravel;30000;14000;16000;2026-10-30 09:00\n"
    )
    headers, rows = importer.read_table(csv_bytes, "wb.csv")
    mapping = importer.suggest_mapping(headers)
    assert mapping["ticket_number"] == 0
    assert mapping["plate"] == 3
    assert mapping["gross_t"] == 5 and mapping["tare_t"] == 6 and mapping["net_t"] == 7
    drafts = importer.map_rows(headers, rows, mapping, weights_in_kg=True)
    assert drafts[0]["net_t"] == D("18.3")
    assert drafts[2]["ticket_date"].isoformat() == "2026-10-30"
    existing = [
        {
            "haulier_name": "Kies AG",
            "ticket_number": "X9",
            "plate": "AB125",
            "time_out": datetime(2026, 10, 30, 9, 0),
            "net_t": D("16"),
        }
    ]
    importer.mark_duplicates(drafts, existing)
    assert [d["duplicate"] for d in drafts] == [None, "in_file", None, "existing"]
