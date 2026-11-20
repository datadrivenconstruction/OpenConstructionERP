# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Keep the canonical copy of tendering and RFQ packages current, and out of the way.

Two listeners on the process-wide ``Session`` class:

* **Write-through.** A transaction that writes a tendering package, bid,
  invitation or clarification, or an RFQ, its lines, bids or award, refreshes
  the canonical mirror of that package before it commits, through
  :mod:`legacy_copy`. The old modules stay the writers until they are retired;
  the mirror never emits an award event, so one award still drafts one
  purchase order and one contract.
* **Visibility.** Mirror packages and their rows are left out of every ORM read
  unless the statement asks for them with the execution option
  ``include_tender_mirrors=True``. Every reader written before the merge (the
  bid management list, analytics, dashboards, deadlines) therefore keeps the
  numbers it had, and a write to a mirror through the bid management API finds
  no package and is refused: the old module owns it.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria

logger = logging.getLogger(__name__)

#: Execution option that lets a statement see mirror packages.
INCLUDE_MIRRORS = "include_tender_mirrors"
_TOUCHED = "tender_legacy_touched"
_SYNCING = "tender_legacy_syncing"


def _touch(session: Session, kind: str, value: Any) -> None:
    if value is None:
        return
    session.info.setdefault(_TOUCHED, set()).add((kind, str(value)))


def _collect(session: Session, obj: Any, *, deleted: bool) -> None:
    from app.modules.rfq_bidding import models as rq  # noqa: PLC0415
    from app.modules.tendering import models as tm  # noqa: PLC0415

    if isinstance(obj, tm.TenderPackage):
        _touch(session, "tp_deleted" if deleted else "tp", obj.id)
    elif isinstance(obj, tm.TenderBid | tm.TenderBidInvitation | tm.TenderClarification):
        _touch(session, "tp", obj.package_id)
    elif isinstance(obj, rq.RFQ):
        _touch(session, "rfq_deleted" if deleted else "rfq", obj.id)
    elif isinstance(obj, rq.RFQLine | rq.RFQBid | rq.RFQAward):
        _touch(session, "rfq", obj.rfq_id)
    elif isinstance(obj, rq.RFQBidLine | rq.RFQBidAdjustment):
        _touch(session, "rbid", obj.bid_id)


def _after_flush(session: Session, _flush_context: Any) -> None:
    if session.info.get(_SYNCING):
        return
    for obj in session.new:
        _collect(session, obj, deleted=False)
    for obj in session.dirty:
        _collect(session, obj, deleted=False)
    for obj in session.deleted:
        _collect(session, obj, deleted=True)


def _bound_ids(statement: Any, column: str) -> list[Any]:
    """Literal values compared to ``column`` with ``==`` in a statement's WHERE."""
    out: list[Any] = []
    where = getattr(statement, "whereclause", None)
    if where is None:
        return out
    from sqlalchemy.sql.elements import BinaryExpression, BindParameter  # noqa: PLC0415
    from sqlalchemy.sql.visitors import iterate  # noqa: PLC0415

    for node in iterate(where):
        if isinstance(node, BinaryExpression) and getattr(node.left, "name", None) == column:
            right = node.right
            if isinstance(right, BindParameter) and right.value is not None:
                out.append(right.value)
    return out


def _do_orm_execute(state: Any) -> None:
    if state.is_select:
        if not state.execution_options.get(INCLUDE_MIRRORS):
            state.statement = state.statement.options(*_hide_mirrors())
        return
    if state.session.info.get(_SYNCING) or not (state.is_update or state.is_delete):
        return
    mapper = state.bind_mapper
    table = getattr(getattr(mapper, "local_table", None), "name", None)
    kind = {"oe_tendering_package": "tp", "oe_tendering_bid": "tbid", "oe_rfq_rfq": "rfq", "oe_rfq_bid": "rbid"}.get(
        table or ""
    )
    if kind is None:
        return
    if state.is_delete and kind in ("tp", "rfq"):
        kind = f"{kind}_deleted"
    for value in _bound_ids(state.statement, "id"):
        _touch(state.session, kind, value)


_HIDE: tuple[Any, ...] | None = None


def _hide_mirrors() -> tuple[Any, ...]:
    """Loader criteria that leave mirror packages and their rows out; built once."""
    global _HIDE  # noqa: PLW0603
    if _HIDE is None:
        _HIDE = _build_hide()
    return _HIDE


def _build_hide() -> tuple[Any, ...]:
    from app.modules.bid_management import models as bm  # noqa: PLC0415

    pkg = bm.BidPackage
    # Core tables inside the criteria, so the criteria never apply to themselves.
    # Aliased and uncorrelated: a query that already joins the package table must not swallow the subquery's FROM.
    pkg_t = bm.BidPackage.__table__.alias("oe_mirror_pkg")
    inv_t = bm.BidInvitation.__table__.alias("oe_mirror_inv")
    mirror_ids = select(pkg_t.c.id).where(pkg_t.c.legacy_source.is_not(None)).correlate(None)
    mirror_invitations = select(inv_t.c.id).where(inv_t.c.package_id.in_(mirror_ids)).correlate(None)

    def _not_mirror_child(cls: type) -> Any:
        return cls.package_id.not_in(mirror_ids)

    opts: list[Any] = [with_loader_criteria(pkg, pkg.legacy_source.is_(None), propagate_to_loaders=True)]
    for cls in (bm.BidPackageLineItem, bm.BidInvitation, bm.Bidder, bm.BidQA, bm.BidComparison, bm.BidAward):
        opts.append(with_loader_criteria(cls, _not_mirror_child(cls)))
    opts.append(with_loader_criteria(bm.BidRejection, _not_mirror_child(bm.BidRejection)))
    opts.append(with_loader_criteria(bm.BidSubmission, bm.BidSubmission.invitation_id.not_in(mirror_invitations)))
    return tuple(opts)


def _before_commit(session: Session) -> None:
    if session.info.get(_SYNCING):
        return
    session.flush()
    touched = session.info.pop(_TOUCHED, None)
    if not touched:
        return
    session.info[_SYNCING] = True
    try:
        sync_touched(session.connection(), touched)
    except Exception:  # noqa: BLE001 - the old module's write must land even if the mirror cannot
        logger.exception("tender mirror refresh failed; the next copy run repairs it")
    finally:
        session.info.pop(_SYNCING, None)


def _after_rollback(session: Session) -> None:
    session.info.pop(_TOUCHED, None)


def sync_touched(conn: Any, touched: set[tuple[str, str]]) -> int:
    """Refresh or remove the mirrors of the touched source packages. Returns packages handled."""
    from app.modules.bid_management.legacy_copy import (  # noqa: PLC0415
        RFQ_BID,
        SOURCE_RFQ,
        SOURCE_TENDERING,
        TENDER_BID,
        LegacyCopier,
    )

    copier = LegacyCopier(conn)
    if not copier.available() or not copier.t.has("oe_bid_management_package", "legacy_source"):
        return 0
    tenders: set[str] = set()
    rfqs: set[str] = set()
    removed: list[tuple[str, str]] = []
    for kind, value in touched:
        if kind == "tp":
            tenders.add(value)
        elif kind == "rfq":
            rfqs.add(value)
        elif kind == "tp_deleted":
            removed.append((SOURCE_TENDERING, value))
        elif kind == "rfq_deleted":
            removed.append((SOURCE_RFQ, value))
        elif kind in ("tbid", "rbid"):
            table = copier.t.get(TENDER_BID if kind == "tbid" else RFQ_BID)
            if table is None:
                continue
            fk = table.c.package_id if kind == "tbid" else table.c.rfq_id
            row = conn.execute(select(fk).where(table.c.id == value)).first()
            if row is not None:
                (tenders if kind == "tbid" else rfqs).add(str(row[0]))
    handled = 0
    for source, source_id in removed:
        tenders.discard(source_id)
        rfqs.discard(source_id)
        handled += int(copier.remove(source, source_id))
    for source, ids in ((SOURCE_TENDERING, tenders), (SOURCE_RFQ, rfqs)):
        present = set(copier.source_ids(source, ids))
        for source_id in sorted(ids):
            if source_id in present:
                copier.copy(source, source_id)
            else:
                copier.remove(source, source_id)
            handled += 1
    return handled


def install(session_class: type[Session] = Session) -> None:
    """Attach both listeners to ``session_class``. Idempotent."""
    for name, fn in (
        ("after_flush", _after_flush),
        ("before_commit", _before_commit),
        ("after_rollback", _after_rollback),
        ("do_orm_execute", _do_orm_execute),
    ):
        if not event.contains(session_class, name, fn):
            event.listen(session_class, name, fn)


def is_installed(session_class: type[Session] = Session) -> bool:
    """Whether the listeners are attached to ``session_class``."""
    return event.contains(session_class, "do_orm_execute", _do_orm_execute)


def uninstall(session_class: type[Session] = Session) -> None:
    """Detach the listeners (tests)."""
    for name, fn in (
        ("after_flush", _after_flush),
        ("before_commit", _before_commit),
        ("after_rollback", _after_rollback),
        ("do_orm_execute", _do_orm_execute),
    ):
        if event.contains(session_class, name, fn):
            event.remove(session_class, name, fn)
