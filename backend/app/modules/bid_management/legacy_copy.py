# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Copy the old tender modules into the canonical ``oe_bid_management_*`` tables.

Three modules ran tenders: ``tendering`` (main contract, bill-priced bids),
``bid_management`` (subcontract and supply packages) and ``rfq_bidding``
(supplier quotes). The bid management tables are the canonical store; this
module copies the other two into them, one package at a time.

Rules the copy keeps:

* Nothing is deleted at the source. A copied package is a *mirror*: its
  ``legacy_source`` names the old module, which still owns and writes it.
* Every copied row is recorded in ``oe_tender_legacy_map``. A second run finds
  the mapping and refreshes the mirror in place under the same ids, so the copy
  is re-runnable and an old id always resolves to the same canonical id.
* Money moves as the stored decimal string, never through ``float``. Anything
  the canonical columns cannot hold (bid line JSON, an unreadable total, a
  status with no equivalent) is kept whole in the mirror's metadata or envelope.
* A tender package already linked to a bid package (``BidPackage.tender_id``)
  is mapped to that bid package and not copied a second time.

It runs on a synchronous ``Connection`` (Core, not ORM) so the same code serves
the alembic revision, the boot repair, the CLI and the write-through hook.

CLI::

    python -m app.modules.bid_management.legacy_copy --dry-run
    python -m app.modules.bid_management.legacy_copy --apply [--batch-size 200]

Both print a reconcile line per package; exit 1 when any package's bid count
or bid total differs between source and copy.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Connection, MetaData, Table, and_, delete, func, insert, inspect, select, true, update

logger = logging.getLogger(__name__)

TENDER_PACKAGE = "oe_tendering_package"
TENDER_BID = "oe_tendering_bid"
TENDER_INVITATION = "oe_tendering_bid_invitation"
TENDER_CLARIFICATION = "oe_tendering_clarification"
RFQ = "oe_rfq_rfq"
RFQ_LINE = "oe_rfq_line"
RFQ_BID = "oe_rfq_bid"
RFQ_BID_LINE = "oe_rfq_bid_line"
RFQ_ADJUSTMENT = "oe_rfq_bid_adjustment"
RFQ_AWARD = "oe_rfq_award"

PACKAGE = "oe_bid_management_package"
LINE_ITEM = "oe_bid_management_line_item"
INVITATION = "oe_bid_management_invitation"
BIDDER = "oe_bid_management_bidder"
SUBMISSION = "oe_bid_management_submission"
SUBMISSION_LINE = "oe_bid_management_submission_line"
ADJUSTMENT = "oe_bid_management_submission_adjustment"
QA = "oe_bid_management_qa"
COMPARISON = "oe_bid_management_comparison"
LEVELING = "oe_bid_management_leveling"
LEVELING_PLUG = "oe_bid_management_leveling_plug"
AWARD = "oe_bid_management_award"
REJECTION = "oe_bid_management_rejection"
LEGACY_MAP = "oe_tender_legacy_map"

#: Values of ``BidPackage.legacy_source``.
SOURCE_TENDERING = "tendering"
SOURCE_RFQ = "rfq_bidding"
SOURCES = (SOURCE_TENDERING, SOURCE_RFQ)

#: Synthetic source keys for rows the old modules never had as rows.
_K_TENDER_POSITION = "oe_tendering_package.position"
_K_TENDER_BIDDER = "oe_tendering_bid.bidder"
_K_TENDER_SYNTH_INV = "oe_tendering_bid.invitation"
_K_TENDER_AWARD = "oe_tendering_package.award"
_K_TENDER_REJECTION = "oe_tendering_bid.rejection"
_K_RFQ_CONTACT = "oe_rfq_rfq.contact"
_K_RFQ_BIDDER = "oe_rfq_bid.bidder"
_K_RFQ_SYNTH_INV = "oe_rfq_bid.invitation"
_K_RFQ_COMPARISON = "oe_rfq_rfq.comparison"
_K_RFQ_LEVELING = "oe_rfq_bid.leveling"

_TENDER_STATUS = {
    "draft": "draft",
    "issued": "published",
    "collecting": "open",
    "evaluating": "closed",
    "awarded": "awarded",
}
_RFQ_STATUS = {
    "draft": "draft",
    "published": "published",
    "issued": "published",
    "bids_received": "open",
    "awarded": "awarded",
    "po_issued": "awarded",
    "completed": "awarded",
    "cancelled": "cancelled",
}
_CENT = Decimal("0.01")
_NAMESPACE = uuid.UUID("6f1c4b7e-2a8d-5e3f-9b10-7c4d2e8a1f60")


def tender_status(status: str | None, *, awarded: bool) -> str:
    """Canonical package status for a tendering package status."""
    raw = (status or "").strip().lower()
    if raw == "closed":
        return "awarded" if awarded else "cancelled"
    return _TENDER_STATUS.get(raw, "closed")


def rfq_status(status: str | None) -> str:
    """Canonical package status for an RFQ status (a free string there)."""
    return _RFQ_STATUS.get((status or "").strip().lower(), "closed")


def money(value: Any) -> Decimal | None:
    """A finite decimal read from a stored money value, ``None`` when unreadable.

    Floats go through ``repr`` so ``0.1`` stays ``0.1``; strings are read as
    written. Grouping commas and spaces are dropped.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        if isinstance(value, float):
            out = Decimal(repr(value))
        else:
            text = str(value).strip().replace(",", "").replace(" ", "").replace(" ", "")
            if not text:
                return None
            out = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def money_2(value: Any) -> Decimal:
    """Money rounded half-up to cents, 0 when unreadable or out of column range."""
    out = money(value)
    if out is None:
        return Decimal("0.00")
    out = out.quantize(_CENT, rounding=ROUND_HALF_UP)
    return out if abs(out) < Decimal("1e16") else Decimal("0.00")


def _num(value: Any, places: int, limit: str = "1e14") -> Decimal:
    out = money(value)
    if out is None:
        return Decimal("0")
    out = out.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return out if abs(out) < Decimal(limit) else Decimal("0")


def _fit(value: Any, length: int) -> str | None:
    if value is None:
        return None
    text = value.isoformat() if isinstance(value, datetime | date) else str(value)
    return text[:length]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()[:40]
    return str(value)[:40] or None


def _uuid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        return None


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value


def _now() -> datetime:
    return datetime.now(UTC)


def synthetic_id(kind: str, *parts: Any) -> str:
    """Stable source id for a row the old module never stored as a row."""
    return str(uuid.uuid5(_NAMESPACE, "|".join([kind, *[str(p) for p in parts]])))


class Tables:
    """Table objects for one connection: the ORM metadata, or the live schema.

    ``reflect=True`` reads the database as it is (the alembic revision and the
    upgrade test, where the schema may predate the current models); otherwise
    the ORM's own tables are used. :meth:`get` returns ``None`` for a table that
    does not exist, and :meth:`has` tells whether a column does.
    """

    def __init__(self, conn: Connection, *, reflect: bool = False) -> None:
        self.conn = conn
        self.reflect = reflect
        self._meta = MetaData()
        self._cache: dict[str, Table | None] = {}
        self._present: set[str] | None = None

    def get(self, name: str) -> Table | None:
        if name in self._cache:
            return self._cache[name]
        if self._present is None:
            self._present = set(inspect(self.conn).get_table_names())
        table: Table | None = None
        if name in self._present:
            if self.reflect:
                table = Table(name, self._meta, autoload_with=self.conn)
            else:
                from app.database import Base  # noqa: PLC0415

                _import_models()
                table = Base.metadata.tables.get(name)
        self._cache[name] = table
        return table

    def need(self, name: str) -> Table:
        table = self.get(name)
        if table is None:
            raise LookupError(f"table {name} is missing")
        return table

    def has(self, name: str, column: str) -> bool:
        table = self.get(name)
        return table is not None and column in table.c

    def fit(self, name: str, values: Mapping[str, Any]) -> dict[str, Any]:
        """Only the values whose column exists in ``name``."""
        table = self.need(name)
        return {k: v for k, v in values.items() if k in table.c}

    def with_defaults(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        """Fill NOT NULL columns the row leaves out from the model's Python default (insert only).

        A reflected table knows server defaults only; the model's ``default=""`` or
        ``default=dict`` never reaches the database, so a Core insert would leave
        those columns NULL and fail.
        """
        if not self.reflect:
            return values
        from app.database import Base  # noqa: PLC0415

        _import_models()
        model = Base.metadata.tables.get(name)
        if model is None:
            return values
        for col in self.need(name).c:
            if col.primary_key or col.name in values or col.nullable or col.server_default is not None:
                continue
            if col.name not in model.c:
                continue
            default = model.c[col.name].default
            if default is None:
                continue
            try:
                values[col.name] = default.arg(None) if default.is_callable else default.arg
            except Exception:  # noqa: BLE001 - leave the column to the database
                continue
        return values


def _import_models() -> None:
    import importlib  # noqa: PLC0415

    for name in ("bid_management", "tendering", "rfq_bidding", "subcontractors", "contacts"):
        try:
            importlib.import_module(f"app.modules.{name}.models")
        except ModuleNotFoundError:
            continue


# ── Map ──────────────────────────────────────────────────────────────────


class LegacyMap:
    """Read and write ``oe_tender_legacy_map`` rows for one connection."""

    def __init__(self, tables: Tables) -> None:
        self.t = tables
        self.table = tables.need(LEGACY_MAP)

    def target(self, source_table: str, source_id: str) -> str | None:
        row = self.t.conn.execute(
            select(self.table.c.target_id).where(
                self.table.c.source_table == source_table, self.table.c.source_id == source_id
            )
        ).first()
        return str(row[0]) if row else None

    def for_package(self, package_id: str) -> dict[tuple[str, str], str]:
        rows = self.t.conn.execute(
            select(self.table.c.source_table, self.table.c.source_id, self.table.c.target_id).where(
                self.table.c.package_id == package_id
            )
        ).all()
        return {(r[0], str(r[1])): str(r[2]) for r in rows}

    def put(self, source_table: str, source_id: str, target_table: str, target_id: str, package_id: str) -> None:
        existing = self.target(source_table, source_id)
        if existing is not None:
            self.t.conn.execute(
                update(self.table)
                .where(self.table.c.source_table == source_table, self.table.c.source_id == source_id)
                .values(target_id=target_id, target_table=target_table, package_id=package_id, updated_at=_now())
            )
            return
        self.t.conn.execute(
            insert(self.table).values(
                id=str(uuid.uuid4()),
                source_table=source_table,
                source_id=source_id,
                target_table=target_table,
                target_id=target_id,
                package_id=package_id,
                copied_at=_now().isoformat(),
                created_at=_now(),
                updated_at=_now(),
            )
        )

    def drop_package_children(self, package_id: str, keep: set[tuple[str, str]]) -> None:
        """Forget child mappings of a package that the latest copy no longer produced."""
        for key in set(self.for_package(package_id)) - keep:
            self.t.conn.execute(
                delete(self.table).where(self.table.c.source_table == key[0], self.table.c.source_id == key[1])
            )


# ── Report ───────────────────────────────────────────────────────────────


@dataclass
class PackageReport:
    """Reconcile line for one source package."""

    source_table: str
    source_id: str
    target_id: str | None
    outcome: str  # copied | refreshed | linked | would_copy | failed
    bids_source: int = 0
    bids_target: int = 0
    total_source: Decimal = Decimal("0.00")
    total_target: Decimal = Decimal("0.00")
    error: str | None = None

    @property
    def ok(self) -> bool:
        if self.outcome in ("failed", "missing"):
            return False
        if self.outcome in ("linked", "would_copy"):
            return True
        return self.bids_source == self.bids_target and self.total_source == self.total_target

    def line(self) -> str:
        state = "OK" if self.ok else "MISMATCH"
        return (
            f"{state} {self.outcome:<10} {self.source_table}:{self.source_id} -> {self.target_id or '-'} "
            f"bids {self.bids_source}/{self.bids_target} total {self.total_source}/{self.total_target}"
            + (f" error {self.error}" if self.error else "")
        )


@dataclass
class CopyReport:
    """Everything one run did."""

    packages: list[PackageReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(p.ok for p in self.packages)

    @property
    def copied(self) -> int:
        return sum(1 for p in self.packages if p.outcome in ("copied", "refreshed"))

    @property
    def rows_changed(self) -> int:
        return sum(1 for p in self.packages if p.outcome == "copied")


# ── Copier ───────────────────────────────────────────────────────────────


class _PackageWriter:
    """Builds the canonical rows of one mirror package and writes them."""

    def __init__(self, tables: Tables, lmap: LegacyMap, package_id: str, previous: dict[tuple[str, str], str]):
        self.t = tables
        self.map = lmap
        self.package_id = package_id
        self.previous = previous
        self.keys: set[tuple[str, str]] = set()
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.mappings: list[tuple[str, str, str, str]] = []

    def id_for(self, source_table: str, source_id: str, target_table: str) -> str:
        key = (source_table, source_id)
        target = self.previous.get(key) or self.map.target(source_table, source_id) or str(uuid.uuid4())
        self.keys.add(key)
        self.mappings.append((source_table, source_id, target_table, target))
        return target

    def add(self, table: str, values: dict[str, Any]) -> None:
        now = _now()
        values.setdefault("created_at", now)
        values.setdefault("updated_at", now)
        self.rows.setdefault(table, []).append(self.t.with_defaults(table, self.t.fit(table, values)))

    def clear_children(self) -> None:
        """Delete the mirror's child rows; they are rebuilt from the source below."""
        conn = self.t.conn
        pid = self.package_id
        inv = self.t.need(INVITATION)
        sub = self.t.need(SUBMISSION)
        comp = self.t.need(COMPARISON)
        invitation_ids = select(inv.c.id).where(inv.c.package_id == pid)
        submission_ids = select(sub.c.id).where(sub.c.invitation_id.in_(invitation_ids))
        comparison_ids = select(comp.c.id).where(comp.c.package_id == pid)
        sub_line = self.t.need(SUBMISSION_LINE)
        conn.execute(delete(sub_line).where(sub_line.c.submission_id.in_(submission_ids)))
        adj = self.t.get(ADJUSTMENT)
        if adj is not None:
            conn.execute(delete(adj).where(adj.c.submission_id.in_(submission_ids)))
        plug = self.t.get(LEVELING_PLUG)
        if plug is not None:
            conn.execute(delete(plug).where(plug.c.comparison_id.in_(comparison_ids)))
        lev = self.t.need(LEVELING)
        conn.execute(delete(lev).where(lev.c.comparison_id.in_(comparison_ids)))
        conn.execute(delete(sub).where(sub.c.invitation_id.in_(invitation_ids)))
        for name in (AWARD, REJECTION, COMPARISON, QA, INVITATION, BIDDER):
            table = self.t.need(name)
            conn.execute(delete(table).where(table.c.package_id == pid))
        line = self.t.need(LINE_ITEM)
        conn.execute(update(line).where(line.c.package_id == pid).values(parent_line_id=None))
        conn.execute(delete(line).where(line.c.package_id == pid))

    def flush(self) -> None:
        order = (LINE_ITEM, BIDDER, INVITATION, SUBMISSION, SUBMISSION_LINE, ADJUSTMENT, QA, COMPARISON, LEVELING)
        for name in (*order, AWARD, REJECTION):
            rows = self.rows.get(name)
            # executemany binds every row with the first row's keys; rows differ, so group by key set.
            groups: dict[frozenset[str], list[dict[str, Any]]] = {}
            for row in rows or ():
                groups.setdefault(frozenset(row), []).append(row)
            for group in groups.values():
                self.t.conn.execute(insert(self.t.need(name)), group)
        for source_table, source_id, target_table, target in self.mappings:
            self.map.put(source_table, source_id, target_table, target, self.package_id)
        self.map.drop_package_children(self.package_id, self.keys)


class LegacyCopier:
    """Copies tendering and rfq_bidding packages into the canonical tables."""

    def __init__(self, conn: Connection, *, reflect: bool = False) -> None:
        self.t = Tables(conn, reflect=reflect)
        self.conn = conn
        self._codes: set[str] | None = None
        self._tnd_next: int | None = None

    # -- discovery

    def available(self) -> bool:
        return self.t.get(LEGACY_MAP) is not None and self.t.get(PACKAGE) is not None

    def source_ids(self, source: str, ids: Iterable[str] | None = None) -> list[str]:
        name = TENDER_PACKAGE if source == SOURCE_TENDERING else RFQ
        table = self.t.get(name)
        if table is None:
            return []
        stmt = select(table.c.id).order_by(table.c.created_at, table.c.id)
        if ids is not None:
            wanted = [i for i in (str(x) for x in ids)]
            if not wanted:
                return []
            stmt = stmt.where(table.c.id.in_(wanted))
        return [str(r[0]) for r in self.conn.execute(stmt).all()]

    def unmapped_ids(self, source: str) -> list[str]:
        name = TENDER_PACKAGE if source == SOURCE_TENDERING else RFQ
        table = self.t.get(name)
        if table is None:
            return []
        lm = self.t.need(LEGACY_MAP)
        mapped = select(lm.c.source_id).where(lm.c.source_table == name)
        rows = self.conn.execute(
            select(table.c.id).where(table.c.id.not_in(mapped)).order_by(table.c.created_at, table.c.id)
        ).all()
        return [str(r[0]) for r in rows]

    # -- codes

    def _code_taken(self, code: str) -> bool:
        if self._codes is None:
            pkg = self.t.need(PACKAGE)
            self._codes = {str(r[0]) for r in self.conn.execute(select(pkg.c.code)).all()}
        return code in self._codes

    def _claim(self, code: str) -> str:
        assert self._codes is not None
        self._codes.add(code)
        return code

    def _next_tnd(self) -> str:
        if self._tnd_next is None:
            self._code_taken("")
            numbers = [int(m.group(1)) for c in self._codes or () if (m := re.fullmatch(r"TND-(\d+)", c))]
            self._tnd_next = max(numbers, default=0) + 1
        while True:
            code = f"TND-{self._tnd_next:04d}"
            self._tnd_next += 1
            if not self._code_taken(code):
                return self._claim(code)

    def _rfq_code(self, number: str) -> str:
        base = (number or "").strip()[:60] or "RFQ"
        for candidate in (base, f"RFQ-{base}"[:64]):
            if not self._code_taken(candidate):
                return self._claim(candidate)
        n = 2
        while self._code_taken(f"RFQ-{base}-{n}"[:64]):
            n += 1
        return self._claim(f"RFQ-{base}-{n}"[:64])

    # -- shared

    def _existing_code(self, package_id: str) -> str | None:
        pkg = self.t.need(PACKAGE)
        row = self.conn.execute(select(pkg.c.code).where(pkg.c.id == package_id)).first()
        return str(row[0]) if row else None

    def _upsert_package(self, package_id: str, values: dict[str, Any]) -> bool:
        pkg = self.t.need(PACKAGE)
        values = self.t.fit(PACKAGE, values)
        exists = self.conn.execute(select(pkg.c.id).where(pkg.c.id == package_id)).first() is not None
        if exists:
            values.pop("code", None)
            values.pop("created_at", None)
            self.conn.execute(update(pkg).where(pkg.c.id == package_id).values(**values))
        else:
            self.conn.execute(insert(pkg).values(id=package_id, **self.t.with_defaults(PACKAGE, values)))
        return not exists

    def _resolve_subcontractor(self, company: str) -> str | None:
        table = self.t.get("oe_subcontractors_subcontractor")
        name = (company or "").strip()
        if table is None or not name or "legal_name" not in table.c:
            return None
        rows = self.conn.execute(
            select(table.c.id).where(func.lower(table.c.legal_name) == name.lower()).limit(2)
        ).all()
        return str(rows[0][0]) if len(rows) == 1 else None

    def _contact(self, contact_id: Any) -> tuple[str, str, str]:
        """Company label, person name and email of a contacts row; blanks when there is none."""
        table = self.t.get("oe_contacts_contact")
        cid = _uuid(contact_id)
        if table is None or cid is None:
            return "", "", ""
        row = self.conn.execute(select(table).where(table.c.id == cid)).mappings().first()
        if row is None:
            return "", "", ""
        person = " ".join(str(row.get(k) or "").strip() for k in ("first_name", "last_name")).strip()
        company = str(row.get("company_name") or row.get("legal_name") or "").strip() or person
        return company, person, str(row.get("primary_email") or "").strip()

    def _rfq_comparison(self, rfq: dict[str, Any], lines: list[dict[str, Any]], bids: list[dict[str, Any]]) -> Any:
        """Rank the RFQ's quotes with the RFQ module's own comparison, read from the stored rows."""
        from app.modules.rfq_bidding.comparison import compare  # noqa: PLC0415

        def _s(value: Any) -> str | None:
            if value is None:
                return None
            return format(value, "f") if isinstance(value, Decimal) else str(value)

        bid_payload = []
        for bid in bids:
            bid_id = str(bid["id"])
            meta = _json(bid.get("metadata"), {}) or {}
            keys = ("bidder_contact_id", "bid_amount", "currency_code", "status", "submitted_at", "validity_days")
            keys += ("is_awarded", "is_late", "admitted_at", "technical_score", "commercial_score")
            bid_payload.append(
                {
                    **{k: bid.get(k) for k in keys},
                    "id": bid_id,
                    "exchange_rate": _s(bid.get("exchange_rate")),
                    "exchange_rate_date": bid.get("exchange_rate_date"),
                    "scope_confirmed": bool(meta.get("scope_confirmed")) if isinstance(meta, dict) else False,
                    "lines": [
                        {
                            "id": str(bl["id"]),
                            "rfq_line_id": _uuid(bl.get("rfq_line_id")),
                            "description": bl.get("description"),
                            "unit": bl.get("unit"),
                            "quantity": _s(bl.get("quantity")),
                            "unit_rate": _s(bl.get("unit_rate")),
                            "amount": _s(bl.get("amount")),
                            "unit_conversion_factor": _s(bl.get("unit_conversion_factor")),
                            "is_excluded": bl.get("is_excluded"),
                        }
                        for bl in self._rows(self.t.get(RFQ_BID_LINE), "bid_id", bid_id)
                    ],
                    "adjustments": [
                        {
                            "id": str(adj["id"]),
                            **{k: adj.get(k) for k in ("kind", "description", "currency_code", "source")},
                            "amount": _s(adj.get("amount")),
                            "included_in_bid": adj.get("included_in_bid"),
                        }
                        for adj in self._rows(self.t.get(RFQ_ADJUSTMENT), "bid_id", bid_id)
                    ],
                }
            )
        scope = []
        for ln in lines:
            line_meta = _json(ln.get("metadata"), {}) or {}
            if not isinstance(line_meta, dict):
                line_meta = {}
            scope.append(
                {
                    "id": str(ln["id"]),
                    **{k: ln.get(k) for k in ("line_no", "code", "description", "unit", "is_optional")},
                    "quantity": _s(ln.get("quantity")),
                    "estimate_rate": line_meta.get("estimate_rate"),
                    "estimate_currency": line_meta.get("estimate_currency"),
                }
            )
        payload = {
            "currency_code": rfq.get("currency_code") or "",
            "evaluation_method": rfq.get("evaluation_method"),
            "technical_weight": _s(rfq.get("technical_weight")),
            "require_full_scope": rfq.get("require_full_scope"),
            "as_of": _now().date().isoformat(),
            "lines": scope,
            "bids": bid_payload,
        }
        return compare(payload)

    def _row(self, table: Table, row_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(select(table).where(table.c.id == row_id)).mappings().first()
        return dict(row) if row else None

    def _rows(self, table: Table | None, column: str, value: str, order: tuple[str, ...] = ("created_at",)):
        if table is None:
            return []
        stmt = select(table).where(table.c[column] == value)
        stmt = stmt.order_by(*[table.c[c] for c in order if c in table.c], table.c.id)
        return [dict(r) for r in self.conn.execute(stmt).mappings().all()]

    def _target_totals(self, package_id: str) -> tuple[int, Decimal]:
        inv = self.t.need(INVITATION)
        sub = self.t.need(SUBMISSION)
        rows = self.conn.execute(
            select(sub.c.total_amount)
            .select_from(sub.join(inv, sub.c.invitation_id == inv.c.id))
            .where(inv.c.package_id == package_id)
        ).all()
        return len(rows), sum((money_2(r[0]) for r in rows), Decimal("0.00"))

    # -- tendering

    def copy_tender_package(self, source_id: str, *, apply: bool = True) -> PackageReport:
        src = self.t.need(TENDER_PACKAGE)
        tp = self._row(src, source_id)
        if tp is None:
            return PackageReport(TENDER_PACKAGE, source_id, None, "failed", error="source row missing")
        bids = self._rows(self.t.get(TENDER_BID), "package_id", source_id)
        total_source = sum((money_2(b.get("total_amount")) for b in bids), Decimal("0.00"))
        report = PackageReport(TENDER_PACKAGE, source_id, None, "copied", len(bids), 0, total_source)
        lmap = LegacyMap(self.t)
        mapped = lmap.target(TENDER_PACKAGE, source_id)

        pkg = self.t.need(PACKAGE)
        linked = self.conn.execute(
            select(pkg.c.id)
            .where(pkg.c.tender_id == source_id, pkg.c.legacy_source.is_(None) if "legacy_source" in pkg.c else true())
            .order_by(pkg.c.created_at)
            .limit(1)
        ).first()
        if linked is not None and (mapped is None or mapped == str(linked[0])):
            report.outcome, report.target_id = "linked", str(linked[0])
            if apply:
                lmap.put(TENDER_PACKAGE, source_id, PACKAGE, str(linked[0]), str(linked[0]))
            return report
        if not apply:
            report.outcome, report.target_id = "would_copy", mapped
            return report

        package_id = mapped or str(uuid.uuid4())
        metadata = dict(_json(tp.get("metadata"), {}) or {})
        awarded_bid_id = _uuid(metadata.get("awarded_bid_id"))
        legacy = {
            "source_table": TENDER_PACKAGE,
            "source_id": source_id,
            "status": tp.get("status"),
            "deadline": tp.get("deadline"),
        }
        for key in (
            "trade",
            "cost_line_id",
            "issue_date",
            "questions_until",
            "bids_due",
            "award_planned",
            "buyer_id",
            "estimator_id",
            "site_manager_id",
            "approver_id",
        ):
            if tp.get(key) is not None:
                legacy[key] = _iso(tp.get(key)) if isinstance(tp.get(key), date) else str(tp.get(key))
        metadata["legacy"] = legacy
        currency = str(metadata.get("currency") or (bids[0].get("currency") if bids else "") or "")[:10]
        status = tender_status(tp.get("status"), awarded=awarded_bid_id is not None)
        values = {
            "project_id": str(tp["project_id"]),
            "code": self._existing_code(package_id) or self._next_tnd(),
            "title": _fit(tp.get("name"), 500) or "",
            "scope_description": tp.get("description") or "",
            "submission_deadline": _fit(tp.get("deadline"), 40),
            "currency": currency,
            "status": status,
            "package_type": "supply" if metadata.get("package_type") == "supply" else "subcontract",
            "published_at": _fit(metadata.get("issued_at") or metadata.get("published_at"), 40),
            "closed_at": _fit(metadata.get("closed_at"), 40),
            "awarded_at": _fit(metadata.get("awarded_at"), 40) if awarded_bid_id else None,
            "created_by": _fit(metadata.get("created_by"), 36),
            "metadata": metadata,
            "legacy_source": SOURCE_TENDERING,
            "boq_id": _uuid(tp.get("boq_id")),
            "legal_entity_id": _uuid(tp.get("legal_entity_id")),
            "created_at": tp.get("created_at") or _now(),
            "updated_at": _now(),
        }
        created = self._upsert_package(package_id, values)
        w = _PackageWriter(self.t, lmap, package_id, lmap.for_package(package_id))
        if not created:
            w.clear_children()

        # Scope lines: the bill positions the bids priced, in first-seen order.
        line_ids: dict[str, str] = {}
        order = 0
        for bid in bids:
            for item in _json(bid.get("line_items"), []) or []:
                if not isinstance(item, Mapping):
                    continue
                pos = _uuid(item.get("position_id"))
                if pos is None or pos in line_ids:
                    continue
                key_id = synthetic_id(_K_TENDER_POSITION, source_id, pos)
                lid = w.id_for(_K_TENDER_POSITION, key_id, LINE_ITEM)
                line_ids[pos] = lid
                w.add(
                    LINE_ITEM,
                    {
                        "id": lid,
                        "package_id": package_id,
                        "code": "",
                        "description": str(item.get("description") or ""),
                        "unit": str(item.get("unit") or "")[:20],
                        "quantity": _num(item.get("quantity"), 4),
                        "order_index": order,
                        "is_mandatory": True,
                        "boq_position_id": pos,
                    },
                )
                order += 1

        invitations = self._rows(self.t.get(TENDER_INVITATION), "package_id", source_id)
        invitation_by_bid: dict[str, str] = {}
        for ti in invitations:
            iid = w.id_for(TENDER_INVITATION, str(ti["id"]), INVITATION)
            bid_ref = _uuid(ti.get("bid_id"))
            if bid_ref and bid_ref not in invitation_by_bid:
                invitation_by_bid[bid_ref] = iid
            if ti.get("revoked_at"):
                inv_status = "expired"
            elif ti.get("submitted_at") or bid_ref:
                inv_status = "submitted"
            elif ti.get("declined_at"):
                inv_status = "declined"
            elif ti.get("opened_at"):
                inv_status = "opened"
            else:
                inv_status = "sent"
            w.add(
                INVITATION,
                {
                    "id": iid,
                    "package_id": package_id,
                    "bidder_ref_id": _uuid(ti.get("contact_id")),
                    "invitee_email": _fit(ti.get("email"), 255) or "",
                    "invitee_company_name": _fit(ti.get("company_name"), 255) or "",
                    "sent_at": _iso(ti.get("created_at")),
                    "opened_at": _iso(ti.get("opened_at")),
                    "submission_received_at": _iso(ti.get("submitted_at")),
                    "declined_at": _iso(ti.get("declined_at")),
                    "decline_reason": ti.get("decline_reason"),
                    "status": inv_status,
                    "token_hash": ti.get("token_hash"),
                    "expires_at": _iso(ti.get("expires_at")),
                    "revoked_at": _iso(ti.get("revoked_at")),
                    "draft_saved_at": _iso(ti.get("draft_saved_at")),
                    "draft": _json(ti.get("draft"), None),
                    "created_at": ti.get("created_at") or _now(),
                },
            )

        bidder_by_bid: dict[str, str] = {}
        for bid in bids:
            bid_id = str(bid["id"])
            bidder_id = w.id_for(_K_TENDER_BIDDER, bid_id, BIDDER)
            bidder_by_bid[bid_id] = bidder_id
            company = str(bid.get("company_name") or "")
            w.add(
                BIDDER,
                {
                    "id": bidder_id,
                    "package_id": package_id,
                    "company_name": company[:255],
                    "contact_email": _fit(bid.get("contact_email"), 255) or "",
                    "contact_id": _uuid(bid.get("contact_id")),
                    "subcontractor_id": self._resolve_subcontractor(company),
                    "status": "active",
                    "notes": bid.get("notes") or "",
                    "created_at": bid.get("created_at") or _now(),
                },
            )
            invitation_id = invitation_by_bid.get(bid_id)
            if invitation_id is None:
                invitation_id = w.id_for(_K_TENDER_SYNTH_INV, bid_id, INVITATION)
                w.add(
                    INVITATION,
                    {
                        "id": invitation_id,
                        "package_id": package_id,
                        "bidder_ref_id": _uuid(bid.get("contact_id")),
                        "invitee_email": _fit(bid.get("contact_email"), 255) or "",
                        "invitee_company_name": company[:255],
                        "submission_received_at": _fit(bid.get("submitted_at"), 40),
                        "status": "submitted",
                        "created_at": bid.get("created_at") or _now(),
                    },
                )
            sub_id = w.id_for(TENDER_BID, bid_id, SUBMISSION)
            items = _json(bid.get("line_items"), []) or []
            raw_total = bid.get("total_amount")
            w.add(
                SUBMISSION,
                {
                    "id": sub_id,
                    "invitation_id": invitation_id,
                    "bidder_id": bidder_id,
                    "submitted_at": _fit(bid.get("submitted_at"), 40),
                    "total_amount": money_2(raw_total),
                    "currency": str(bid.get("currency") or "")[:10],
                    "is_valid": str(bid.get("status") or "") in ("submitted", "accepted"),
                    "envelope_payload": {
                        "legacy_status": bid.get("status"),
                        "legacy_total": raw_total,
                        "legacy_line_items": items,
                        "legacy_metadata": _json(bid.get("metadata"), {}),
                    },
                    "created_at": bid.get("created_at") or _now(),
                },
            )
            for idx, item in enumerate(items):
                if not isinstance(item, Mapping):
                    continue
                pos = _uuid(item.get("position_id"))
                line_item_id = line_ids.get(pos) if pos else None
                w.add(
                    SUBMISSION_LINE,
                    {
                        "id": str(uuid.uuid5(uuid.UUID(sub_id), str(idx))),
                        "submission_id": sub_id,
                        "line_item_id": line_item_id,
                        "description": None if line_item_id else str(item.get("description") or ""),
                        "unit": None if line_item_id else str(item.get("unit") or "")[:20],
                        "unit_price": _num(item.get("unit_rate"), 4),
                        "quantity_priced": _num(item.get("quantity"), 4),
                        "total_price": _num(item.get("total"), 2, "1e16"),
                        "inclusion_status": "included",
                    },
                )
            if str(bid.get("status") or "") == "rejected" and awarded_bid_id:
                w.add(
                    REJECTION,
                    {
                        "id": w.id_for(_K_TENDER_REJECTION, bid_id, REJECTION),
                        "package_id": package_id,
                        "bidder_id": bidder_id,
                        "rejection_code": "other",
                        "rejection_reason": "",
                    },
                )

        if awarded_bid_id and awarded_bid_id in bidder_by_bid:
            winner = next(b for b in bids if str(b["id"]) == awarded_bid_id)
            w.add(
                AWARD,
                {
                    "id": w.id_for(_K_TENDER_AWARD, source_id, AWARD),
                    "package_id": package_id,
                    "awarded_bidder_id": bidder_by_bid[awarded_bid_id],
                    "awarded_amount": money_2(winner.get("total_amount")),
                    "currency": str(winner.get("currency") or currency)[:10],
                    "decision_summary": str(metadata.get("award_reason") or ""),
                    "decision_signed_by": _fit(metadata.get("awarded_by"), 36),
                    "decision_signed_at": _fit(metadata.get("awarded_at"), 40),
                },
            )

        for cl in self._rows(self.t.get(TENDER_CLARIFICATION), "package_id", source_id, ("number", "created_at")):
            w.add(
                QA,
                {
                    "id": w.id_for(TENDER_CLARIFICATION, str(cl["id"]), QA),
                    "package_id": package_id,
                    "question": cl.get("question") or "",
                    "asked_at": _iso(cl.get("asked_at")),
                    "asked_by_email": _fit(cl.get("asked_by_email"), 255) or "",
                    "answer": cl.get("answer") or "",
                    "answered_at": _iso(cl.get("answered_at")),
                    "answered_by": _fit(cl.get("answered_by"), 36),
                    "is_public": cl.get("published_at") is not None,
                    "visible_to_bidder_ids": [],
                },
            )

        w.flush()
        lmap.put(TENDER_PACKAGE, source_id, PACKAGE, package_id, package_id)
        report.outcome = "copied" if created else "refreshed"
        report.target_id = package_id
        report.bids_target, report.total_target = self._target_totals(package_id)
        return report

    # -- rfq

    def copy_rfq(self, source_id: str, *, apply: bool = True) -> PackageReport:
        src = self.t.need(RFQ)
        rfq = self._row(src, source_id)
        if rfq is None:
            return PackageReport(RFQ, source_id, None, "failed", error="source row missing")
        bids = self._rows(self.t.get(RFQ_BID), "rfq_id", source_id, ("submitted_at", "created_at"))
        total_source = sum((money_2(b.get("bid_amount")) for b in bids), Decimal("0.00"))
        report = PackageReport(RFQ, source_id, None, "copied", len(bids), 0, total_source)
        lmap = LegacyMap(self.t)
        mapped = lmap.target(RFQ, source_id)
        if not apply:
            report.outcome, report.target_id = "would_copy", mapped
            return report

        package_id = mapped or str(uuid.uuid4())
        metadata = dict(_json(rfq.get("metadata"), {}) or {})
        lines = self._rows(self.t.get(RFQ_LINE), "rfq_id", source_id, ("line_no",))
        metadata["legacy"] = {
            "source_table": RFQ,
            "source_id": source_id,
            "status": rfq.get("status"),
            "rfq_number": rfq.get("rfq_number"),
            "technical_weight": str(rfq.get("technical_weight") or "0"),
            "line_notes": {str(ln["id"]): ln.get("notes") for ln in lines if ln.get("notes")},
            "line_metadata": {str(ln["id"]): _json(ln.get("metadata"), {}) for ln in lines if ln.get("metadata")},
        }
        scope = "\n\n".join(p for p in (rfq.get("description"), rfq.get("scope_of_work")) if p)
        status = rfq_status(rfq.get("status"))
        currency = str(rfq.get("currency_code") or "")[:10]
        values = {
            "project_id": str(rfq["project_id"]),
            "code": self._existing_code(package_id) or self._rfq_code(str(rfq.get("rfq_number") or "")),
            "title": _fit(rfq.get("title"), 500) or "",
            "scope_description": scope,
            "submission_deadline": _fit(rfq.get("submission_deadline"), 40),
            "currency": currency,
            "status": status,
            "package_type": "supply",
            "created_by": _fit(rfq.get("created_by"), 36),
            "metadata": metadata,
            "legacy_source": SOURCE_RFQ,
            "cost_line_ids": list(_json(rfq.get("cost_line_ids"), []) or []),
            "evaluation_method": _fit(rfq.get("evaluation_method"), 30),
            "require_full_scope": rfq.get("require_full_scope"),
            "created_at": rfq.get("created_at") or _now(),
            "updated_at": _now(),
        }
        created = self._upsert_package(package_id, values)
        w = _PackageWriter(self.t, lmap, package_id, lmap.for_package(package_id))
        if not created:
            w.clear_children()

        line_ids: dict[str, str] = {}
        for ln in lines:
            lid = w.id_for(RFQ_LINE, str(ln["id"]), LINE_ITEM)
            line_ids[str(ln["id"])] = lid
            w.add(
                LINE_ITEM,
                {
                    "id": lid,
                    "package_id": package_id,
                    "code": _fit(ln.get("code"), 64) or "",
                    "description": ln.get("description") or "",
                    "unit": _fit(ln.get("unit"), 20) or "",
                    "quantity": _num(ln.get("quantity"), 4),
                    "order_index": int(ln.get("line_no") or 0),
                    "is_mandatory": not bool(ln.get("is_optional")),
                    "cost_line_id": _uuid(ln.get("cost_line_id")),
                },
            )

        contacts = [str(c) for c in (_json(rfq.get("issued_to_contacts"), []) or []) if c]
        invitation_by_contact: dict[str, str] = {}
        for contact in contacts:
            if contact in invitation_by_contact:
                continue
            iid = w.id_for(_K_RFQ_CONTACT, synthetic_id(_K_RFQ_CONTACT, source_id, contact), INVITATION)
            invitation_by_contact[contact] = iid
            w.add(
                INVITATION,
                {
                    "id": iid,
                    "package_id": package_id,
                    "bidder_ref_id": _uuid(contact),
                    "status": "sent",
                    "sent_at": _iso(rfq.get("created_at")),
                },
            )

        tech_weight = money(rfq.get("technical_weight")) or Decimal("0")
        tech_pct = int(max(Decimal(0), min(Decimal(100), tech_weight)).to_integral_value(ROUND_HALF_UP))
        bidder_by_bid: dict[str, str] = {}
        bidder_ok: dict[str, bool] = {}
        submitted_invitations: set[str] = set()
        for bid in bids:
            bid_id = str(bid["id"])
            meta = dict(_json(bid.get("metadata"), {}) or {})
            # The RFQ module keeps the bidder as a contact; metadata names it only on imported quotes.
            contact_company, contact_person, contact_email = self._contact(bid.get("bidder_contact_id"))
            company = str(meta.get("company_name") or meta.get("bidder_name") or "") or contact_company
            email = str(meta.get("contact_email") or "") or contact_email
            bidder_id = w.id_for(_K_RFQ_BIDDER, bid_id, BIDDER)
            bidder_by_bid[bid_id] = bidder_id
            raw_status = str(bid.get("status") or "")
            if bid.get("withdrawn_at") or raw_status == "withdrawn":
                bidder_status = "withdrawn"
            elif bid.get("disqualified_reason") or raw_status == "disqualified":
                bidder_status = "disqualified"
            else:
                bidder_status = "active"
            bidder_ok[bid_id] = bidder_status == "active"
            w.add(
                BIDDER,
                {
                    "id": bidder_id,
                    "package_id": package_id,
                    "company_name": company[:255],
                    "contact_name": contact_person[:255],
                    "contact_email": email[:255],
                    "contact_id": _uuid(bid.get("bidder_contact_id")),
                    "subcontractor_id": self._resolve_subcontractor(company),
                    "status": bidder_status,
                    "disqualification_reason": bid.get("disqualified_reason"),
                    "withdrawn_at": _fit(bid.get("withdrawn_at"), 40),
                    "withdrawn_reason": bid.get("withdrawn_reason"),
                    "notes": bid.get("notes") or "",
                    "created_at": bid.get("created_at") or _now(),
                },
            )
            contact = str(bid.get("bidder_contact_id") or "")
            invitation_id = invitation_by_contact.get(contact)
            if invitation_id is None or invitation_id in submitted_invitations:
                invitation_id = w.id_for(_K_RFQ_SYNTH_INV, bid_id, INVITATION)
                w.add(
                    INVITATION,
                    {
                        "id": invitation_id,
                        "package_id": package_id,
                        "bidder_ref_id": _uuid(contact),
                        "invitee_company_name": company[:255],
                        "invitee_email": email[:255],
                        "status": "submitted",
                        "submission_received_at": _fit(bid.get("submitted_at"), 40),
                        "created_at": bid.get("created_at") or _now(),
                    },
                )
            else:
                for row in w.rows[INVITATION]:
                    if row["id"] == invitation_id:
                        row["status"] = "submitted"
                        for col, value in (("invitee_company_name", company), ("invitee_email", email)):
                            if col in row:
                                row[col] = value[:255]
                        row["submission_received_at"] = _fit(bid.get("submitted_at"), 40)
            submitted_invitations.add(invitation_id)
            sub_id = w.id_for(RFQ_BID, bid_id, SUBMISSION)
            rate = money(bid.get("exchange_rate"))
            w.add(
                SUBMISSION,
                {
                    "id": sub_id,
                    "invitation_id": invitation_id,
                    "bidder_id": bidder_id,
                    "submitted_at": _fit(bid.get("submitted_at"), 40),
                    "total_amount": money_2(bid.get("bid_amount")),
                    "currency": str(bid.get("currency_code") or "")[:10],
                    "notes_to_owner": bid.get("notes") or "",
                    "is_valid": bidder_status == "active",
                    "open_after_deadline": bool(bid.get("is_late")),
                    "validity_days": bid.get("validity_days"),
                    "exchange_rate": rate,
                    "exchange_rate_date": _fit(bid.get("exchange_rate_date"), 20),
                    "exchange_rate_source": _fit(bid.get("exchange_rate_source"), 60),
                    "admitted_by": _fit(bid.get("admitted_by"), 36),
                    "admitted_at": _fit(bid.get("admitted_at"), 40),
                    "admission_reason": bid.get("admission_reason"),
                    "late_reason": bid.get("late_reason"),
                    "envelope_payload": {
                        "legacy_status": raw_status,
                        "legacy_total": bid.get("bid_amount"),
                        "is_awarded": bool(bid.get("is_awarded")),
                        "technical_score": bid.get("technical_score"),
                        "commercial_score": bid.get("commercial_score"),
                        "legacy_metadata": meta,
                    },
                    "created_at": bid.get("created_at") or _now(),
                },
            )
            for bl in self._rows(self.t.get(RFQ_BID_LINE), "bid_id", bid_id):
                line_item_id = line_ids.get(str(bl.get("rfq_line_id"))) if bl.get("rfq_line_id") else None
                w.add(
                    SUBMISSION_LINE,
                    {
                        "id": w.id_for(RFQ_BID_LINE, str(bl["id"]), SUBMISSION_LINE),
                        "submission_id": sub_id,
                        "line_item_id": line_item_id,
                        "description": bl.get("description"),
                        "unit": _fit(bl.get("unit"), 20),
                        "unit_price": _num(bl.get("unit_rate"), 4),
                        "quantity_priced": _num(bl.get("quantity"), 4),
                        "total_price": _num(bl.get("amount"), 2, "1e16"),
                        "unit_conversion_factor": money(bl.get("unit_conversion_factor")),
                        "inclusion_status": "excluded" if bl.get("is_excluded") else "included",
                        "comment": bl.get("notes") or "",
                    },
                )
            for adj in self._rows(self.t.get(RFQ_ADJUSTMENT), "bid_id", bid_id):
                w.add(
                    ADJUSTMENT,
                    {
                        "id": w.id_for(RFQ_ADJUSTMENT, str(adj["id"]), ADJUSTMENT),
                        "submission_id": sub_id,
                        "kind": str(adj.get("kind") or "other")[:40],
                        "description": adj.get("description"),
                        "amount": money_2(adj.get("amount")),
                        "currency": str(adj.get("currency_code") or "")[:10],
                        "included_in_bid": bool(adj.get("included_in_bid")),
                        "source": str(adj.get("source") or "bidder")[:20],
                    },
                )

        if bids:
            # The header holds the levelled range and the recommendation the tender card shows.
            result = self._rfq_comparison(rfq, lines, bids)
            levelled = [money_2(q.normalised_amount) for q in result.ranked if q.normalised_amount is not None]
            if not levelled:
                levelled = [
                    money_2(b.get("bid_amount"))
                    for b in bids
                    if bidder_ok.get(str(b["id"])) and money_2(b.get("bid_amount")) > 0
                ]
            recommended = bidder_by_bid.get(str(result.recommended_bid_id)) if result.recommended_bid_id else None
            comparison_id = w.id_for(_K_RFQ_COMPARISON, source_id, COMPARISON)
            w.add(
                COMPARISON,
                {
                    "id": comparison_id,
                    "package_id": package_id,
                    "computed_at": _now().isoformat(timespec="seconds"),
                    "normalized_low": min(levelled) if levelled else Decimal("0.00"),
                    "normalized_high": max(levelled) if levelled else Decimal("0.00"),
                    "recommended_bidder_id": recommended,
                    "recommended_reason": "leveling.top_rank" if recommended else "",
                    "commercial_weight_pct": 100 - tech_pct,
                    "technical_weight_pct": tech_pct,
                    "technical_scoring_rule": {"method": rfq.get("evaluation_method")},
                },
            )
            for bid in bids:
                bid_id = str(bid["id"])
                quote = result.get(bid_id)
                normalised = quote.normalised_amount if quote is not None else None
                w.add(
                    LEVELING,
                    {
                        "id": w.id_for(_K_RFQ_LEVELING, bid_id, LEVELING),
                        "comparison_id": comparison_id,
                        "bidder_id": bidder_by_bid[bid_id],
                        "raw_total": money_2(bid.get("bid_amount")),
                        "normalized_total": money_2(bid.get("bid_amount") if normalised is None else normalised),
                        "total_score": _num(quote.total_score, 4, "1e6") if quote and quote.total_score else Decimal(0),
                        "rank": (quote.rank or 0) if quote is not None else 0,
                        "commercial_score": _num(bid.get("commercial_score"), 2, "1e6"),
                        "technical_score": _num(bid.get("technical_score"), 2, "1e6"),
                    },
                )

        awards = self._rows(self.t.get(RFQ_AWARD), "rfq_id", source_id, ("awarded_at", "created_at"))
        awards = [a for a in awards if str(a.get("bid_id")) in bidder_by_bid]
        if awards:
            award = awards[-1]
            if len(awards) > 1:
                metadata["legacy"]["earlier_awards"] = [str(a["id"]) for a in awards[:-1]]
                self.conn.execute(
                    update(self.t.need(PACKAGE))
                    .where(self.t.need(PACKAGE).c.id == package_id)
                    .values(metadata=metadata)
                )
            recommended = _uuid(award.get("recommended_bid_id"))
            w.add(
                AWARD,
                {
                    "id": w.id_for(RFQ_AWARD, str(award["id"]), AWARD),
                    "package_id": package_id,
                    "awarded_bidder_id": bidder_by_bid[str(award["bid_id"])],
                    "awarded_amount": money_2(award.get("awarded_amount")),
                    "currency": str(award.get("awarded_currency") or currency)[:10],
                    "decision_summary": award.get("reason") or "",
                    "decision_signed_by": _fit(award.get("awarded_by"), 36),
                    "decision_signed_at": _fit(award.get("awarded_at"), 40),
                    "method": _fit(award.get("method"), 30),
                    "is_override": award.get("is_override"),
                    "recommended_bidder_id": bidder_by_bid.get(recommended) if recommended else None,
                    "basis": _json(award.get("basis"), {}),
                },
            )

        w.flush()
        lmap.put(RFQ, source_id, PACKAGE, package_id, package_id)
        report.outcome = "copied" if created else "refreshed"
        report.target_id = package_id
        report.bids_target, report.total_target = self._target_totals(package_id)
        return report

    # -- lifecycle

    def copy(self, source: str, source_id: str, *, apply: bool = True) -> PackageReport:
        """Copy or refresh one package inside a savepoint; a failure is reported, not raised."""
        fn = self.copy_tender_package if source == SOURCE_TENDERING else self.copy_rfq
        source_table = TENDER_PACKAGE if source == SOURCE_TENDERING else RFQ
        savepoint = self.conn.begin_nested()
        try:
            report = fn(source_id, apply=apply)
        except Exception as exc:  # noqa: BLE001 - one bad package must not stop the batch
            savepoint.rollback()
            self._codes = None
            self._tnd_next = None
            logger.warning("tender legacy copy failed for %s:%s: %s", source_table, source_id, exc)
            return PackageReport(source_table, source_id, None, "failed", error=type(exc).__name__)
        savepoint.commit()
        return report

    def remove(self, source: str, source_id: str) -> bool:
        """Drop the mirror of a deleted source package and its map rows."""
        source_table = TENDER_PACKAGE if source == SOURCE_TENDERING else RFQ
        lmap = LegacyMap(self.t)
        target = lmap.target(source_table, source_id)
        if target is None:
            return False
        pkg = self.t.need(PACKAGE)
        row = self.conn.execute(select(pkg.c.legacy_source).where(pkg.c.id == target)).first()
        if row is not None and row[0] == source:
            w = _PackageWriter(self.t, lmap, target, {})
            w.clear_children()
            self.conn.execute(delete(pkg).where(pkg.c.id == target))
            lm = self.t.need(LEGACY_MAP)
            self.conn.execute(delete(lm).where(lm.c.package_id == target))
        lm = self.t.need(LEGACY_MAP)
        self.conn.execute(delete(lm).where(and_(lm.c.source_table == source_table, lm.c.source_id == source_id)))
        return True


def stale_rfq_mirrors(conn: Connection, *, reflect: bool = False) -> list[str]:
    """RFQ ids whose mirror lacks what an earlier copy left out: the bidder's firm and email, the levelled range.

    A mirror qualifies when one of its bidders names no firm or email although the linked contact has one,
    or when its comparison reads a high of 0 while a valid bid carries a positive total. A refreshed mirror
    no longer qualifies, so refreshing what this returns is idempotent.
    """
    t = Tables(conn, reflect=reflect)
    if t.get(PACKAGE) is None or t.get(LEGACY_MAP) is None or not t.has(PACKAGE, "legacy_source"):
        return []
    pkg, bidder, comp = t.need(PACKAGE), t.need(BIDDER), t.need(COMPARISON)
    inv, sub = t.need(INVITATION), t.need(SUBMISSION)
    rfq_pkgs = select(pkg.c.id).where(pkg.c.legacy_source == SOURCE_RFQ)
    stale: set[str] = set()
    contact = t.get("oe_contacts_contact")
    if contact is not None:
        label = func.coalesce(contact.c.company_name, contact.c.legal_name, contact.c.first_name, contact.c.last_name)
        rows = conn.execute(
            select(bidder.c.package_id)
            .select_from(bidder.join(contact, bidder.c.contact_id == contact.c.id))
            .where(bidder.c.package_id.in_(rfq_pkgs))
            .where(
                ((bidder.c.company_name == "") & (func.coalesce(label, "") != ""))
                | ((bidder.c.contact_email == "") & (func.coalesce(contact.c.primary_email, "") != ""))
            )
        ).all()
        stale.update(str(r[0]) for r in rows)
    priced = (
        select(inv.c.package_id)
        .select_from(sub.join(inv, sub.c.invitation_id == inv.c.id))
        .where(sub.c.is_valid.is_(true()), sub.c.total_amount > 0)
    )
    rows = conn.execute(
        select(comp.c.package_id).where(
            comp.c.package_id.in_(rfq_pkgs), comp.c.normalized_high == 0, comp.c.package_id.in_(priced)
        )
    ).all()
    stale.update(str(r[0]) for r in rows)
    if not stale:
        return []
    lm = t.need(LEGACY_MAP)
    found = conn.execute(
        select(lm.c.source_id, lm.c.target_id).where(lm.c.source_table == RFQ, lm.c.target_table == PACKAGE)
    ).all()
    wanted = {s.replace("-", "").lower() for s in stale}
    return sorted(str(r[0]) for r in found if str(r[1]).replace("-", "").lower() in wanted)


def refresh_stale_rfq_mirrors(conn: Connection, *, reflect: bool = False) -> int:
    """Re-copy the RFQ mirrors :func:`stale_rfq_mirrors` names. Returns the packages refreshed."""
    ids = stale_rfq_mirrors(conn, reflect=reflect)
    if not ids:
        return 0
    copier = LegacyCopier(conn, reflect=reflect)
    return sum(1 for source_id in ids if copier.copy(SOURCE_RFQ, source_id).outcome in ("copied", "refreshed"))


def copy_all(
    conn: Connection,
    *,
    apply: bool = True,
    only_unmapped: bool = False,
    reflect: bool = False,
    batch_size: int = 200,
    on_batch: Any = None,
) -> CopyReport:
    """Copy every tendering package and RFQ. Re-runnable.

    Args:
        conn: Synchronous connection inside a transaction.
        apply: ``False`` reports what would be copied and writes nothing.
        only_unmapped: Skip packages already in the map (the boot repair).
        reflect: Read the live schema instead of the ORM metadata.
        batch_size: Packages per batch; ``on_batch`` is called after each.
        on_batch: Optional callable, e.g. a commit for the CLI.

    Returns:
        A report with one reconcile line per package.
    """
    copier = LegacyCopier(conn, reflect=reflect)
    report = CopyReport()
    if not copier.available():
        return report
    for source in SOURCES:
        ids = copier.unmapped_ids(source) if only_unmapped else copier.source_ids(source)
        for start in range(0, len(ids), max(1, batch_size)):
            for source_id in ids[start : start + batch_size]:
                report.packages.append(copier.copy(source, source_id, apply=apply))
            if on_batch is not None:
                on_batch()
    return report


def reconcile_one(
    conn: Connection, source_table: str, source_id: str, *, copier: LegacyCopier | None = None
) -> PackageReport:
    """Reconcile line for one old package (``oe_tendering_package`` or ``oe_rfq_rfq``)."""
    copier = copier or LegacyCopier(conn)
    if source_table == TENDER_PACKAGE:
        bid_table, fk, amount, source = TENDER_BID, "package_id", "total_amount", SOURCE_TENDERING
    else:
        bid_table, fk, amount, source = RFQ_BID, "rfq_id", "bid_amount", SOURCE_RFQ
    rows = copier._rows(copier.t.get(bid_table), fk, source_id)
    total = sum((money_2(r.get(amount)) for r in rows), Decimal("0.00"))
    target = LegacyMap(copier.t).target(source_table, source_id) if copier.available() else None
    if target is None:
        return PackageReport(source_table, source_id, None, "missing", len(rows), 0, total)
    pkg = copier.t.need(PACKAGE)
    if copier.conn.execute(select(pkg.c.legacy_source).where(pkg.c.id == target)).scalar() != source:
        return PackageReport(source_table, source_id, target, "linked", len(rows), 0, total)
    count, target_total = copier._target_totals(target)
    return PackageReport(source_table, source_id, target, "mapped", len(rows), count, total, target_total)


def reconcile(conn: Connection, *, reflect: bool = False) -> CopyReport:
    """Compare every old package with its copy without writing anything."""
    copier = LegacyCopier(conn, reflect=reflect)
    report = CopyReport()
    if not copier.available():
        return report
    for source, source_table in ((SOURCE_TENDERING, TENDER_PACKAGE), (SOURCE_RFQ, RFQ)):
        for source_id in copier.source_ids(source):
            report.packages.append(reconcile_one(conn, source_table, source_id, copier=copier))
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    mode.add_argument("--apply", action="store_true", help="copy and refresh every package")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine  # noqa: PLC0415

    from app.config import get_settings  # noqa: PLC0415

    url = get_settings().database_sync_url
    engine = create_engine(url)
    with engine.connect() as conn:
        trans = conn.begin()

        def _commit() -> None:
            nonlocal trans
            if args.apply:
                trans.commit()
                trans = conn.begin()

        copied = copy_all(conn, apply=args.apply, batch_size=args.batch_size, on_batch=_commit)
        if args.apply:
            trans.commit()
            trans = conn.begin()
        check = reconcile(conn) if args.apply else copied
        trans.rollback()
    engine.dispose()
    for line in check.packages:
        print(line.line())
    print(
        f"packages {len(check.packages)} ok {sum(1 for p in check.packages if p.ok)} mismatched "
        f"{sum(1 for p in check.packages if not p.ok)}"
    )
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
