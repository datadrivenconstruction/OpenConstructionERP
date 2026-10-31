# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day service: the board, its edits, the change log and the submitted snapshots.

Quotes are not stored twice. Opening a board reads the quotes already received in
bid management (submissions to the bid packages of the tender) and in tendering
(bids on the tender package itself) and links each by ``source_ref``; later opens
pick up quotes that arrived since. What the board keeps of its own is what bid
day adds: the edited figure, the scope plugs, the choice, late phone and email
quotes, markups and the log.

Every edit names the revision it was made on. A stale revision answers 409 with
the current state and who changed it, so two estimators never overwrite each
other silently. Every edit bumps the board ``version`` the clients poll.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bid_day import logic
from app.modules.bid_day.logic import Markups, QuoteData, RowData, fmt, to_decimal
from app.modules.bid_day.models import BidDayBoard, BidDayEvent, BidDayQuote, BidDayRow, BidDaySnapshot
from app.modules.bid_day.repository import BidDayRepository
from app.modules.bid_day.validators import DEFAULT_DEVIATION_PCT, DEFAULT_STALE_DAYS, evaluate

logger = logging.getLogger(__name__)

EDITABLE_SOURCES = frozenset({"late", "manual"})


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=UTC)


def _conflict(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message, **extra})


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def quote_data(q: BidDayQuote) -> QuoteData:
    return QuoteData(
        id=str(q.id),
        vendor=q.vendor,
        amount=to_decimal(q.amount),
        fx_rate=to_decimal(q.fx_rate, Decimal("1")),
        exclusions=list(q.exclusions or []),
        received_at=_parse_dt(q.received_at),
    )


def row_data(r: BidDayRow) -> RowData:
    return RowData(
        id=str(r.id),
        name=r.name,
        plug=to_decimal(r.plug_amount),
        quotes=[quote_data(q) for q in r.quotes],
        chosen_id=str(r.chosen_quote_id) if r.chosen_quote_id else None,
    )


def markups(b: BidDayBoard) -> Markups:
    return Markups(to_decimal(b.overhead_pct), to_decimal(b.risk_pct), to_decimal(b.profit_pct))


class BidDayService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BidDayRepository(session)

    # ── Loading ──────────────────────────────────────────────────────────

    async def tender(self, tender_id: uuid.UUID) -> Any:
        from app.modules.tendering.models import TenderPackage

        tender = await self.session.get(TenderPackage, tender_id)
        if tender is None:
            raise _not_found("Tender")
        return tender

    async def board(self, board_id: uuid.UUID) -> BidDayBoard:
        board = await self.repo.board(board_id)
        if board is None:
            raise _not_found("Board")
        return board

    async def open_board(self, tender_id: uuid.UUID, user_id: str | None) -> BidDayBoard:
        """The tender's board, created on first open and topped up with quotes received since."""
        tender = await self.tender(tender_id)
        board = await self.repo.board_for_tender(tender_id)
        if board is None:
            from app.modules.projects.models import Project

            project = await self.session.get(Project, tender.project_id)
            board = BidDayBoard(
                project_id=tender.project_id,
                tender_id=tender_id,
                currency=(getattr(project, "currency", "") or "").upper(),
                created_by=user_id,
            )
            await self.repo.add(board)
            await self.session.refresh(board, ["rows"])
        if board.status == "open" and await self._sync_sources(board, tender):
            board.version += 1
            await self.session.flush()
            await self.session.refresh(board, ["rows"])
        return board

    async def _sync_sources(self, board: BidDayBoard, tender: Any) -> bool:
        """Add rows and quotes for bid packages and bids not on the board yet."""
        from app.modules.bid_management.models import Bidder, BidInvitation, BidPackage, BidSubmission
        from app.modules.tendering.models import TenderBid

        rows_by_pkg = {r.bid_package_id: r for r in board.rows if r.bid_package_id}
        known = {q.source_ref for r in board.rows for q in r.quotes if q.source_ref}
        changed = False
        order = max((r.sort_order for r in board.rows), default=0)

        pkgs = list(
            (await self.session.execute(select(BidPackage).where(BidPackage.tender_id == tender.id))).scalars().all()
        )
        for pkg in pkgs:
            row = rows_by_pkg.get(pkg.id)
            if row is None:
                order += 1
                row = BidDayRow(
                    board_id=board.id,
                    bid_package_id=pkg.id,
                    name=pkg.title or pkg.code,
                    kind="subcontract",
                    plug_amount=fmt(to_decimal(pkg.total_budget_estimate)),
                    sort_order=order,
                )
                await self.repo.add(row)
                await self.session.refresh(row, ["quotes"])
                rows_by_pkg[pkg.id] = row
                changed = True
            stmt = (
                select(BidSubmission, Bidder.company_name, BidInvitation.invitee_company_name)
                .join(BidInvitation, BidInvitation.id == BidSubmission.invitation_id)
                .join(Bidder, Bidder.id == BidSubmission.bidder_id)
                .where(BidInvitation.package_id == pkg.id)
            )
            for sub, bidder_name, invitee in (await self.session.execute(stmt)).all():
                if sub.id in known:
                    continue
                await self._add_source_quote(
                    board, row, "submission", sub.id, bidder_name or invitee or "",
                    sub.total_amount, sub.currency or pkg.currency, sub.submitted_at, sub.notes_to_owner, sub.exclusions,
                )  # fmt: skip
                known.add(sub.id)
                changed = True

        if not pkgs:
            # A tender without bid packages is one package: its own bids are the quotes.
            row = next((r for r in board.rows if r.bid_package_id is None and r.kind == "subcontract"), None)
            bids = list(
                (await self.session.execute(select(TenderBid).where(TenderBid.package_id == tender.id))).scalars().all()
            )
            if row is None and (bids or not board.rows):
                row = BidDayRow(board_id=board.id, name=tender.name, kind="subcontract", sort_order=order + 1)
                await self.repo.add(row)
                await self.session.refresh(row, ["quotes"])
                changed = True
            for bid in bids:
                if bid.id in known or row is None:
                    continue
                await self._add_source_quote(
                    board, row, "tender_bid", bid.id, bid.company_name, bid.total_amount, bid.currency,
                    bid.submitted_at, bid.notes, [],
                )  # fmt: skip
                changed = True
        return changed

    async def _add_source_quote(
        self,
        board: BidDayBoard,
        row: BidDayRow,
        source: str,
        ref: uuid.UUID,
        vendor: str,
        amount: Any,
        currency: str | None,
        received: Any,
        note: str | None,
        exclusions: Any,
    ) -> None:
        ccy = (currency or board.currency or "").upper()
        amt = fmt(to_decimal(amount))
        q = BidDayQuote(
            row_id=row.id,
            source=source,
            source_ref=ref,
            channel="portal",
            vendor=vendor[:255],
            amount=amt,
            source_amount=amt,
            currency=ccy,
            fx_rate=str(await self._fx_rate(board, ccy, strict=False)),
            received_at=_parse_dt(received),
            note=(note or "")[:4000],
            exclusions=logic.clean_exclusions(exclusions),
        )
        await self.repo.add(q)
        row.quotes.append(q)

    async def _fx_rate(self, board: BidDayBoard, currency: str, *, strict: bool = True) -> Decimal:
        """Board-currency units per one unit of ``currency``: project rates first, then the FX module."""
        ccy = (currency or "").upper()
        if not ccy or not board.currency or ccy == board.currency:
            return Decimal("1")
        from app.modules.projects.models import Project

        project = await self.session.get(Project, board.project_id)
        for entry in getattr(project, "fx_rates", None) or []:
            if isinstance(entry, dict) and str(entry.get("code", "")).upper() == ccy:
                rate = to_decimal(entry.get("rate"))
                if rate > 0:
                    return rate
        try:
            from app.modules.fx.service import FxService

            res = await FxService(self.session).convert(Decimal("1"), ccy, board.currency, project_id=board.project_id)
            rate = to_decimal(res.get("rate"))
            if rate > 0:
                return rate
        except Exception:  # noqa: BLE001 - an unknown rate is reported below, never guessed
            logger.info("no FX rate %s->%s for bid day board %s", ccy, board.currency, board.id, exc_info=True)
        if strict:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "no_fx_rate", "message": f"No exchange rate from {ccy} to {board.currency}."},
            )
        return Decimal("1")

    # ── Reading ──────────────────────────────────────────────────────────

    def compute(self, board: BidDayBoard, last_total: Decimal | None) -> dict[str, Any]:
        rows = [row_data(r) for r in board.rows]
        return logic.totals(rows, markups(board), last_snapshot_total=last_total)

    async def last_snapshot_total(self, board: BidDayBoard) -> Decimal | None:
        snaps = await self.repo.snapshots(board.id)
        return to_decimal(snaps[0].bid_total) if snaps else None

    def validation_input(self, board: BidDayBoard, totals: dict[str, Any]) -> dict[str, Any]:
        s = board.settings or {}
        return {
            "now": _now(),
            "stale_days": int(s.get("stale_days") or DEFAULT_STALE_DAYS),
            "deviation_pct_limit": s.get("deviation_pct_limit") or str(DEFAULT_DEVIATION_PCT),
            "direct": totals["direct"],
            "estimate": totals["estimate_direct"],
            "rows": [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "chosen_id": str(r.chosen_quote_id) if r.chosen_quote_id else None,
                    "quotes": [
                        {
                            "id": str(q.id),
                            "vendor": q.vendor,
                            "received_at": _parse_dt(q.received_at),
                            "exclusions": q.exclusions or [],
                        }
                        for q in r.quotes
                    ],
                }
                for r in board.rows
            ],
        }

    async def findings(self, board: BidDayBoard, totals: dict[str, Any]) -> list[Any]:
        return await evaluate(self.validation_input(board, totals), target_id=str(board.id))

    async def view(self, board: BidDayBoard) -> dict[str, Any]:
        """The full board as the API returns it."""
        tender = await self.tender(board.tender_id)
        snaps = await self.repo.snapshots(board.id)
        last = to_decimal(snaps[0].bid_total) if snaps else None
        totals = self.compute(board, last)
        rows_out = []
        for r in board.rows:
            rd = row_data(r)
            value = logic.row_value(rd)
            quotes_out = []
            for q, qd in zip(r.quotes, rd.quotes, strict=True):
                quotes_out.append(
                    {
                        "id": q.id, "source": q.source, "channel": q.channel, "vendor": q.vendor,
                        "amount": q.amount, "source_amount": q.source_amount, "currency": q.currency,
                        "fx_rate": q.fx_rate, "received_at": _parse_dt(q.received_at), "note": q.note,
                        "exclusions": q.exclusions or [], "as_quoted": fmt(logic.as_quoted(qd)),
                        "adjusted": fmt(logic.adjusted(qd)), "open_exclusions": logic.open_exclusions(qd),
                        "is_chosen": q.id == r.chosen_quote_id, "rev": q.rev,
                    }
                )  # fmt: skip
            rows_out.append(
                {
                    "id": r.id, "bid_package_id": r.bid_package_id, "name": r.name, "kind": r.kind,
                    "plug_amount": r.plug_amount, "chosen_quote_id": r.chosen_quote_id, "value": fmt(value),
                    "delta_vs_plug": fmt(value - logic.money(rd.plug)), "suggestion": logic.suggest(rd),
                    "quotes": quotes_out, "rev": r.rev,
                }
            )  # fmt: skip
        s = board.settings or {}
        findings = await self.findings(board, totals)
        return {
            "id": board.id,
            "project_id": board.project_id,
            "tender_id": board.tender_id,
            "tender_name": tender.name,
            "deadline": tender.deadline,
            "currency": board.currency,
            "status": board.status,
            "version": board.version,
            "markup_rev": board.markup_rev,
            "overhead_pct": board.overhead_pct,
            "risk_pct": board.risk_pct,
            "profit_pct": board.profit_pct,
            "stale_days": int(s.get("stale_days") or DEFAULT_STALE_DAYS),
            "deviation_pct_limit": str(s.get("deviation_pct_limit") or DEFAULT_DEVIATION_PCT),
            "totals": totals,
            "rows": rows_out,
            "events": await self.repo.events(board.id),
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": getattr(f.severity, "value", str(f.severity)),
                    "message": f.message,
                    "element_ref": f.element_ref,
                    "details": f.details or {},
                }
                for f in findings
            ],
            "snapshots": snaps,
        }

    # ── Editing ──────────────────────────────────────────────────────────

    def _editable(self, board: BidDayBoard) -> None:
        if board.status != "open":
            raise _conflict("board_frozen", "The bid was submitted; reopen the board to change it.")

    async def _check_rev(self, board: BidDayBoard, current: int, sent: int | None, what: str) -> None:
        if sent is None or sent == current:
            return
        events = await self.repo.events(board.id, limit=1)
        last = events[0] if events else None
        raise _conflict(
            "stale_revision",
            f"{what} was changed by someone else since you loaded it.",
            current_rev=current,
            changed_by=last.user_name if last else "",
            change=last.message if last else "",
        )

    async def _user_name(self, user_id: str | None) -> str:
        if not user_id:
            return ""
        from app.modules.users.models import User

        try:
            user = await self.session.get(User, uuid.UUID(str(user_id)))
        except ValueError:
            return ""
        return (user.full_name or user.email) if user else ""

    async def _log(
        self, board: BidDayBoard, user_id: str | None, kind: str, before: Decimal, message: str, **params: Any
    ) -> None:
        """Bump the board version and write one change-log line with the delta it caused."""
        board.version += 1
        await self.session.flush()
        after = to_decimal(self.compute(board, None)["bid_total"])
        delta = after - before
        name = await self._user_name(user_id)
        text = f"{message}; bid total now {fmt(after)} {board.currency}".strip()
        await self.repo.add(
            BidDayEvent(
                board_id=board.id,
                user_id=user_id,
                user_name=name,
                kind=kind,
                message=text,
                delta=fmt(delta),
                total_after=fmt(after),
                params={k: (str(v) if isinstance(v, Decimal | uuid.UUID) else v) for k, v in params.items()},
            )
        )

    def _total(self, board: BidDayBoard) -> Decimal:
        return to_decimal(self.compute(board, None)["bid_total"])

    async def _row_of(self, board: BidDayBoard, row_id: uuid.UUID) -> BidDayRow:
        row = next((r for r in board.rows if r.id == row_id), None)
        if row is None:
            raise _not_found("Row")
        return row

    async def _quote_of(self, board: BidDayBoard, quote_id: uuid.UUID) -> tuple[BidDayRow, BidDayQuote]:
        for r in board.rows:
            for q in r.quotes:
                if q.id == quote_id:
                    return r, q
        raise _not_found("Quote")

    async def add_row(self, board: BidDayBoard, data: Any, user_id: str | None) -> None:
        self._editable(board)
        before = self._total(board)
        row = BidDayRow(
            board_id=board.id,
            name=data.name.strip(),
            kind=data.kind,
            plug_amount=fmt(to_decimal(data.plug_amount)),
            sort_order=max((r.sort_order for r in board.rows), default=0) + 1,
        )
        await self.repo.add(row)
        await self.session.refresh(row, ["quotes"])
        board.rows.append(row)
        await self._log(board, user_id, "row_added", before, f"{row.name} added", row=row.name)

    async def update_row(self, board: BidDayBoard, row_id: uuid.UUID, data: Any, user_id: str | None) -> None:
        self._editable(board)
        row = await self._row_of(board, row_id)
        await self._check_rev(board, row.rev, data.rev, row.name)
        before = self._total(board)
        if data.name is not None and data.name.strip():
            row.name = data.name.strip()
        if data.kind is not None:
            row.kind = data.kind
        old_plug = row.plug_amount
        if data.plug_amount is not None:
            row.plug_amount = fmt(to_decimal(data.plug_amount))
        row.rev += 1
        msg = (
            f"{row.name} estimate figure {old_plug} -> {row.plug_amount}"
            if old_plug != row.plug_amount
            else f"{row.name} edited"
        )
        await self._log(board, user_id, "row_updated", before, msg, row=row.name, old=old_plug, new=row.plug_amount)

    async def delete_row(self, board: BidDayBoard, row_id: uuid.UUID, user_id: str | None) -> None:
        self._editable(board)
        row = await self._row_of(board, row_id)
        if row.bid_package_id is not None:
            raise _conflict("row_from_package", "This row is a bid package; remove the package in bid management.")
        before = self._total(board)
        board.rows.remove(row)
        await self.repo.delete(row)
        await self._log(board, user_id, "row_removed", before, f"{row.name} removed", row=row.name)

    async def add_quote(self, board: BidDayBoard, row_id: uuid.UUID, data: Any, user_id: str | None) -> BidDayQuote:
        self._editable(board)
        row = await self._row_of(board, row_id)
        before = self._total(board)
        ccy = (data.currency or board.currency or "").upper()
        q = BidDayQuote(
            row_id=row.id,
            source="late",
            channel=data.channel,
            vendor=data.vendor.strip(),
            amount=fmt(to_decimal(data.amount)),
            currency=ccy,
            fx_rate=str(await self._fx_rate(board, ccy)),
            received_at=data.received_at or _now(),
            note=data.note,
            exclusions=logic.clean_exclusions([x.model_dump() for x in data.exclusions]),
            created_by=user_id,
        )
        await self.repo.add(q)
        row.quotes.append(q)
        row.rev += 1
        await self._log(
            board, user_id, "quote_added", before,
            f"{row.name}: {data.channel} quote from {q.vendor} {q.amount} {ccy}",
            row=row.name, vendor=q.vendor, amount=q.amount, currency=ccy, channel=data.channel,
        )  # fmt: skip
        return q

    async def update_quote(self, board: BidDayBoard, quote_id: uuid.UUID, data: Any, user_id: str | None) -> None:
        self._editable(board)
        row, q = await self._quote_of(board, quote_id)
        await self._check_rev(board, q.rev, data.rev, f"{q.vendor} ({row.name})")
        before = self._total(board)
        old_adjusted = logic.adjusted(quote_data(q))
        if data.vendor is not None and data.vendor.strip():
            q.vendor = data.vendor.strip()
        if data.amount is not None:
            q.amount = fmt(to_decimal(data.amount))
        if data.currency is not None and data.currency.upper() != q.currency:
            q.currency = data.currency.upper()
            q.fx_rate = str(await self._fx_rate(board, q.currency))
        if data.received_at is not None:
            q.received_at = data.received_at
        if data.note is not None:
            q.note = data.note
        if data.exclusions is not None:
            q.exclusions = logic.clean_exclusions([x.model_dump() for x in data.exclusions])
        q.rev += 1
        await self.repo.save(q, "exclusions")
        new_adjusted = logic.adjusted(quote_data(q))
        diff = new_adjusted - old_adjusted
        verb = "cut by" if diff < 0 else "raised by"
        msg = f"{row.name}: {q.vendor} {verb} {fmt(abs(diff))}" if diff else f"{row.name}: {q.vendor} edited"
        await self._log(
            board, user_id, "quote_updated", before, msg,
            row=row.name, vendor=q.vendor, change=fmt(diff), adjusted=fmt(new_adjusted),
        )  # fmt: skip

    async def delete_quote(self, board: BidDayBoard, quote_id: uuid.UUID, user_id: str | None) -> None:
        self._editable(board)
        row, q = await self._quote_of(board, quote_id)
        if q.source not in EDITABLE_SOURCES:
            raise _conflict("quote_from_source", "This quote came from bid management; withdraw it there.")
        before = self._total(board)
        if row.chosen_quote_id == q.id:
            row.chosen_quote_id = None
        row.quotes.remove(q)
        row.rev += 1
        await self.repo.delete(q)
        await self._log(
            board, user_id, "quote_removed", before, f"{row.name}: {q.vendor} removed", row=row.name, vendor=q.vendor
        )

    async def choose(self, board: BidDayBoard, row_id: uuid.UUID, data: Any, user_id: str | None) -> None:
        self._editable(board)
        row = await self._row_of(board, row_id)
        await self._check_rev(board, row.rev, data.rev, row.name)
        before = self._total(board)
        vendor = ""
        if data.quote_id is not None:
            q = next((x for x in row.quotes if x.id == data.quote_id), None)
            if q is None:
                raise _not_found("Quote")
            vendor = q.vendor
        row.chosen_quote_id = data.quote_id
        row.rev += 1
        msg = f"{row.name}: {vendor} chosen" if vendor else f"{row.name}: back to the estimate figure"
        await self._log(board, user_id, "quote_chosen", before, msg, row=row.name, vendor=vendor)

    async def set_markups(self, board: BidDayBoard, data: Any, user_id: str | None) -> None:
        self._editable(board)
        await self._check_rev(board, board.markup_rev, data.rev, "Markups")
        before = self._total(board)
        parts = []
        for name in ("overhead_pct", "risk_pct", "profit_pct"):
            value = getattr(data, name)
            if value is not None and to_decimal(value) != to_decimal(getattr(board, name)):
                setattr(board, name, str(to_decimal(value).normalize()))
                parts.append(f"{name.removesuffix('_pct')} {getattr(board, name)}%")
        settings = dict(board.settings or {})
        if data.stale_days is not None:
            settings["stale_days"] = data.stale_days
        if data.deviation_pct_limit is not None:
            settings["deviation_pct_limit"] = data.deviation_pct_limit
        board.settings = settings
        board.markup_rev += 1
        await self.repo.save(board, "settings")
        await self._log(board, user_id, "markups", before, "Markups: " + (", ".join(parts) or "settings"), parts=parts)

    # ── Submitting ───────────────────────────────────────────────────────

    async def freeze(self, board: BidDayBoard, note: str, user_id: str | None) -> BidDaySnapshot:
        """Store what is submitted, immutably, and lock the board."""
        self._editable(board)
        totals = self.compute(board, None)
        errors = [
            f
            for f in await self.findings(board, totals)
            if getattr(f.severity, "value", str(f.severity)).lower().endswith("error")
        ]
        if errors:
            raise _conflict(
                "validation_errors",
                "Resolve the errors before submitting.",
                findings=[{"rule_id": f.rule_id, "message": f.message, "element_ref": f.element_ref} for f in errors],
            )
        tender = await self.tender(board.tender_id)
        name = await self._user_name(user_id)
        at = _now()
        payload = {
            "tender": {"id": str(tender.id), "name": tender.name, "deadline": tender.deadline},
            "submitted_at": at.isoformat(),
            "submitted_by": name,
            "currency": board.currency,
            "markups": {"overhead_pct": board.overhead_pct, "risk_pct": board.risk_pct, "profit_pct": board.profit_pct},
            "totals": totals,
            "rows": [self._snapshot_row(r) for r in board.rows],
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        snap = BidDaySnapshot(
            board_id=board.id,
            project_id=board.project_id,
            tender_id=board.tender_id,
            submitted_by=user_id,
            submitted_by_name=name,
            currency=board.currency,
            bid_total=totals["bid_total"],
            note=note,
            content_sha256=digest,
            payload=payload,
        )
        await self.repo.add(snap)
        board.status = "frozen"
        board.version += 1
        await self.repo.add(
            BidDayEvent(
                board_id=board.id, user_id=user_id, user_name=name, kind="submitted",
                message=f"Bid submitted at {totals['bid_total']} {board.currency}", delta="0",
                total_after=totals["bid_total"], params={"snapshot_id": str(snap.id)},
            )
        )  # fmt: skip
        return snap

    def _snapshot_row(self, r: BidDayRow) -> dict[str, Any]:
        rd = row_data(r)
        q = logic.chosen(rd)
        chosen_orm = next((x for x in r.quotes if x.id == r.chosen_quote_id), None)
        return {
            "row_id": str(r.id),
            "bid_package_id": str(r.bid_package_id) if r.bid_package_id else None,
            "name": r.name,
            "kind": r.kind,
            "plug_amount": r.plug_amount,
            "value": fmt(logic.row_value(rd)),
            "chosen": None
            if q is None or chosen_orm is None
            else {
                "quote_id": q.id,
                "vendor": q.vendor,
                "source": chosen_orm.source,
                "amount": chosen_orm.amount,
                "currency": chosen_orm.currency,
                "fx_rate": chosen_orm.fx_rate,
                "as_quoted": fmt(logic.as_quoted(q)),
                "adjusted": fmt(logic.adjusted(q)),
                "exclusions": q.exclusions,
            },
            "quotes": [
                {"vendor": x.vendor, "as_quoted": fmt(logic.as_quoted(x)), "adjusted": fmt(logic.adjusted(x))}
                for x in rd.quotes
            ],
        }

    async def reopen(self, board: BidDayBoard, user_id: str | None) -> None:
        if board.status == "open":
            return
        board.status = "open"
        await self._log(board, user_id, "reopened", self._total(board), "Board reopened after submission")

    async def snapshot(self, board: BidDayBoard, snapshot_id: uuid.UUID) -> BidDaySnapshot:
        snap = await self.repo.snapshot(snapshot_id)
        if snap is None or snap.board_id != board.id:
            raise _not_found("Snapshot")
        return snap

    async def push_to_estimate(self, board: BidDayBoard, snap: BidDaySnapshot, *, dry_run: bool) -> dict[str, Any]:
        """Spread each chosen quote's adjusted figure over the BOQ positions of its bid package.

        Positions share the amount in proportion to their current totals (by
        quantity when they are all zero); the last one takes the rounding rest so
        the package adds up exactly. ``dry_run`` shows the plan and writes nothing.
        """
        from app.modules.bid_management.models import BidPackageLineItem
        from app.modules.boq.models import Position

        lines: list[dict[str, str]] = []
        skipped: list[str] = []
        writes: list[tuple[Any, Decimal, Decimal]] = []
        for row in snap.payload.get("rows") or []:
            chosen = row.get("chosen")
            if not chosen or not row.get("bid_package_id"):
                skipped.append(row.get("name") or "")
                continue
            stmt = select(BidPackageLineItem.boq_position_id).where(
                BidPackageLineItem.package_id == uuid.UUID(row["bid_package_id"]),
                BidPackageLineItem.boq_position_id.is_not(None),
            )
            pos_ids = [p for p in (await self.session.execute(stmt)).scalars().all() if p]
            positions = (
                list((await self.session.execute(select(Position).where(Position.id.in_(pos_ids)))).scalars().all())
                if pos_ids
                else []
            )
            if not positions:
                skipped.append(row.get("name") or "")
                continue
            target = to_decimal(chosen.get("adjusted"))
            weights = [to_decimal(p.total) for p in positions]
            if sum(weights, Decimal("0")) <= 0:
                weights = [to_decimal(p.quantity) for p in positions]
            wsum = sum(weights, Decimal("0"))
            if wsum <= 0:
                weights, wsum = [Decimal("1")] * len(positions), Decimal(len(positions))
            rest = target
            for i, (p, w) in enumerate(zip(positions, weights, strict=True)):
                share = rest if i == len(positions) - 1 else logic.money(target * w / wsum)
                rest -= share
                qty = to_decimal(p.quantity)
                rate = (share / qty).quantize(Decimal("0.0001")) if qty else share
                writes.append((p, share, rate))
                lines.append(
                    {
                        "row": row.get("name") or "", "position_id": str(p.id), "ordinal": p.ordinal,
                        "description": (p.description or "")[:200], "quantity": p.quantity, "old_total": p.total,
                        "new_total": fmt(share), "new_unit_rate": f"{rate:f}",
                    }
                )  # fmt: skip
        if not dry_run and writes:
            for p, share, rate in writes:
                p.unit_rate = f"{rate:f}"
                p.total = fmt(share)
            snap.pushed_at = _now()
            await self.session.flush()
        return {"applied": not dry_run and bool(writes), "lines": lines, "skipped": skipped}
