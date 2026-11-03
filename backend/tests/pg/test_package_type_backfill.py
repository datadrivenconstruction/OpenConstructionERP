# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision vcc01 backfills ``package_type`` so live awards keep their route.

Packages whose award already produced a purchase order, or that carry a supply
or procurement link, become ``supply``; every other package stays ``subcontract``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio


def _load():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "vcc01_change_chain_award.py"
    spec = importlib.util.spec_from_file_location("vcc01_change_chain_award", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load()

_PACKAGES = {
    "p-po-bid": ("t-none", {}),
    "p-po-tender": ("t-po", {}),
    "p-tender-supply": ("t-supply", {}),
    "p-own-supply": (None, {"package_type": "supply"}),
    "p-requisition": (None, {"requisition_id": "r1"}),
    "p-plain": ("t-plain", {}),
    "p-none": (None, {}),
}


async def test_existing_packages_get_the_route_their_award_already_took() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            for table in ("oe_bid_management_package", "oe_procurement_po", "oe_tendering_package"):
                await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            await conn.execute(
                sa.text(
                    "CREATE TABLE oe_bid_management_package "
                    "(id varchar(36) primary key, tender_id varchar(36), metadata json not null default '{}', "
                    "package_type varchar(16) not null default 'subcontract')"
                )
            )
            await conn.execute(sa.text("CREATE TABLE oe_procurement_po (id varchar(36) primary key, metadata json)"))
            await conn.execute(sa.text("CREATE TABLE oe_tendering_package (id varchar(36) primary key, metadata json)"))
            for pid, (tid, meta) in _PACKAGES.items():
                await conn.execute(
                    sa.text("INSERT INTO oe_bid_management_package (id, tender_id, metadata) VALUES (:i, :t, :m)"),
                    {"i": pid, "t": tid, "m": json.dumps(meta)},
                )
            for tid, meta in (("t-supply", {"package_type": "supply"}), ("t-plain", {}), ("t-po", None)):
                await conn.execute(
                    sa.text("INSERT INTO oe_tendering_package (id, metadata) VALUES (:i, :m)"),
                    {"i": tid, "m": json.dumps(meta) if meta is not None else None},
                )
            for poid, meta in (("po1", {"bid_package_id": "p-po-bid"}), ("po2", {"tender_package_id": "t-po"})):
                await conn.execute(
                    sa.text("INSERT INTO oe_procurement_po (id, metadata) VALUES (:i, :m)"),
                    {"i": poid, "m": json.dumps(meta)},
                )

            changed = await conn.run_sync(_rev.backfill_package_type)
            rows = dict((await conn.execute(sa.text("SELECT id, package_type FROM oe_bid_management_package"))).all())

    assert changed == 5
    assert rows == {
        "p-po-bid": "supply",
        "p-po-tender": "supply",
        "p-tender-supply": "supply",
        "p-own-supply": "supply",
        "p-requisition": "supply",
        "p-plain": "subcontract",
        "p-none": "subcontract",
    }
