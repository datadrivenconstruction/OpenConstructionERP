# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Wave-5 cross-module subscribers - Resources / Contracts / CRM / Carbon.

Wires real cross-module side-effects emitted by the wave-5 deep-dive:

* ``resources.cert_expiring`` → notification per expiring certification.
* ``contracts.retention.released`` → notification for project owner.
* ``crm.opportunity.won`` → bid_management BidPackage (draft, pre-populated).
* ``crm.opportunity.scored`` → notification for opportunity owner.
* ``carbon.boq_position.assigned`` → notification for project sustainability lead.
* ``changeorder.approved`` → revise the linked contract's total_value (when
  the CO carries ``metadata.contract_id``).

``contracts.claim.certified`` used to raise an invoice here as well. The
finance module already raises exactly one per claim, linked through
``source_claim_id`` and in the direction the contract calls for, so this
second, unlinked receivable (numbered ``PC-<claim>``) doubled every certified
claim and booked a subcontractor's bill as money owed to us. It was removed
rather than deduplicated: two writers for one invoice is the defect.

All handlers are best-effort, and the bus is what makes them so:
``EventBus.publish`` runs each handler in its own ``try``, logs a failure
at exception level and records it in ``EventResult.errors``, then carries
on to the next handler. A downstream failure therefore cannot break the
foreground request, and it also cannot pass unrecorded.

Handlers used to repeat that isolation with a body-wide ``except
Exception`` reporting at ``logger.debug``. It bought nothing the bus was
not already providing and cost the record: a subscriber that failed left
one debug line, and the caller holding the ``EventResult`` was told the
publish had succeeded. Narrow catches around parsing are a different
thing and remain - they turn a malformed field into a defined outcome
rather than hiding an unexpected one.

Each subscriber gates on PostgreSQL because cross-session writes on
SQLite would deadlock the single writer (dev-DB).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Callable

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)


async def _can_open_isolated_session() -> bool:
    """Always True post-Epic-B - see :mod:`app.modules.notifications.events`."""
    return True


# ── Resources: certification expiry → notification ───────────────────────


async def _on_cert_expiring(event: Event) -> None:
    """``resources.cert_expiring`` → notify the resource owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    resource_id = data.get("resource_id")
    cert_type = data.get("cert_type", "")
    valid_until = data.get("valid_until", "")
    window_days = data.get("window_days", 0)
    if not resource_id:
        return
    async with async_session_factory() as session:
        from app.modules.resources.repository import ResourceRepository

        res_repo = ResourceRepository(session)
        try:
            res = await res_repo.get_by_id(uuid.UUID(str(resource_id)))
        except (ValueError, TypeError):
            res = None
        if res is None or res.contact_id is None:
            return
        svc = NotificationService(session)
        await svc.create(
            user_id=str(res.contact_id),
            notification_type=("cert_critical" if window_days <= 7 else "cert_warning"),
            title_key="notifications.resources.cert_expiring.title",
            body_key="notifications.resources.cert_expiring.body",
            body_context={
                "cert_type": cert_type,
                "valid_until": valid_until,
                "days_left": str(window_days),
                "resource_code": res.code,
                "resource_name": res.name,
            },
            entity_type="resource_certification",
            entity_id=str(data.get("certification_id", "")),
            action_url=f"/resources/{resource_id}",
        )
        await session.commit()


# ── Contracts: retention released → notification ─────────────────────────


async def _on_retention_released(event: Event) -> None:
    """``contracts.retention.released`` → notify project owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    contract_id = data.get("contract_id")
    if not contract_id:
        return
    async with async_session_factory() as session:
        from app.modules.contracts.repository import ContractRepository

        repo = ContractRepository(session)
        try:
            contract = await repo.get_by_id(uuid.UUID(str(contract_id)))
        except (ValueError, TypeError):
            return
        if contract is None or contract.created_by is None:
            return
        svc = NotificationService(session)
        await svc.create(
            user_id=str(contract.created_by),
            notification_type="contracts_retention_released",
            title_key="notifications.contracts.retention_released.title",
            body_key="notifications.contracts.retention_released.body",
            body_context={
                "contract_code": contract.code,
                "event": data.get("event", ""),
                "amount_released": data.get("amount_released", "0"),
                "remaining": data.get("remaining", "0"),
            },
            entity_type="contract",
            entity_id=str(contract.id),
            action_url=f"/contracts/{contract.id}",
        )
        await session.commit()


# ── CRM: opportunity won → bid package ───────────────────────────────────


async def _on_opportunity_won(event: Event) -> None:
    """``crm.opportunity.won`` → create a draft BidPackage pre-populated."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    opportunity_id = data.get("opportunity_id")
    project_payload = data.get("project_payload") or {}
    if not opportunity_id:
        return
    async with async_session_factory() as session:
        from app.modules.bid_management.models import BidPackage
        from app.modules.crm.repository import OpportunityRepository

        opp_repo = OpportunityRepository(session)
        try:
            opp = await opp_repo.get_by_id(uuid.UUID(str(opportunity_id)))
        except (ValueError, TypeError):
            return
        if opp is None:
            return
        # We don't have a project_id at this layer (the project may not
        # exist yet - projects auto-create on a separate subscriber).
        # When project_payload carries a project_id, use it; otherwise
        # skip creating the bid package and just emit a follow-up event.
        project_id_raw = project_payload.get("project_id")
        if not project_id_raw:
            # Persist a "pending bid package" memo onto the opportunity
            # notes; a downstream Projects-subscriber re-fires this
            # event after Project creation if needed.
            logger.info(
                "crm.opportunity.won: project not yet materialised - skipping auto bid package creation for opp %s",
                opportunity_id,
            )
            return
        try:
            project_id = uuid.UUID(str(project_id_raw))
        except (ValueError, TypeError):
            return

        # Build a deterministic code derived from opportunity id so we
        # don't double-create on event replay.
        code = f"BP-OPP-{str(opp.id)[:8].upper()}"
        existing_stmt = await session.execute(
            __import__(
                "sqlalchemy",
                fromlist=["select"],
            )
            .select(BidPackage)
            .where(BidPackage.code == code),
        )
        if existing_stmt.scalar_one_or_none() is not None:
            return
        package = BidPackage(
            project_id=project_id,
            code=code,
            title=opp.title or "New bid package",
            scope_description=opp.description or "",
            currency=opp.currency or "",
            total_budget_estimate=Decimal(str(opp.estimated_value or 0)),
            status="draft",
            confidentiality_level="limited",
            created_by=str(opp.owner_user_id) if opp.owner_user_id else None,
        )
        package.metadata_ = {
            "source": "crm.opportunity.won",
            "opportunity_id": str(opp.id),
            "account_id": str(opp.account_id),
        }
        session.add(package)
        await session.flush()
        await session.commit()
        event_bus.publish_detached(
            "bid_management.bid_package.created_from_opportunity",
            {
                "bid_package_id": str(package.id),
                "opportunity_id": str(opp.id),
                "project_id": str(project_id),
            },
            source_module="bid_management",
        )
        logger.info(
            "Auto-created bid package %s from opportunity %s",
            package.id,
            opp.id,
        )


# ── CRM: opportunity scored → notification ───────────────────────────────


async def _on_opportunity_scored(event: Event) -> None:
    """``crm.opportunity.scored`` → notify opportunity owner of the new band."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    opportunity_id = data.get("opportunity_id")
    score = data.get("score") or {}
    if not opportunity_id or not score:
        return
    async with async_session_factory() as session:
        from app.modules.crm.repository import OpportunityRepository

        opp_repo = OpportunityRepository(session)
        try:
            opp = await opp_repo.get_by_id(uuid.UUID(str(opportunity_id)))
        except (ValueError, TypeError):
            return
        if opp is None or opp.owner_user_id is None:
            return
        svc = NotificationService(session)
        band = score.get("band", "warm")
        await svc.create(
            user_id=str(opp.owner_user_id),
            notification_type=("crm_score_hot" if band == "hot" else "crm_score_updated"),
            title_key="notifications.crm.opportunity_scored.title",
            body_key="notifications.crm.opportunity_scored.body",
            body_context={
                "title": opp.title,
                "score": str(score.get("total", 0)),
                "band": band,
                "budget": str(score.get("budget", 0)),
                "authority": str(score.get("authority", 0)),
                "need": str(score.get("need", 0)),
                "timeline": str(score.get("timeline", 0)),
            },
            entity_type="crm_opportunity",
            entity_id=str(opp.id),
            action_url=f"/crm/opportunities/{opp.id}",
        )
        await session.commit()


# ── Carbon: BOQ position assigned → notification ─────────────────────────


async def _on_boq_position_assigned(event: Event) -> None:
    """``carbon.boq_position.assigned`` → notify sustainability lead."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    inventory_id = data.get("inventory_id")
    boq_position_id = data.get("boq_position_id")
    carbon_kg = data.get("carbon_kg", "0")
    stage = data.get("stage", "a1a3")
    if not inventory_id:
        return
    async with async_session_factory() as session:
        from app.modules.carbon.repository import InventoryRepository

        inv_repo = InventoryRepository(session)
        try:
            inv = await inv_repo.get_by_id(uuid.UUID(str(inventory_id)))
        except (ValueError, TypeError):
            return
        if inv is None or inv.created_by is None:
            return
        svc = NotificationService(session)
        await svc.create(
            user_id=str(inv.created_by),
            notification_type="carbon_boq_assigned",
            title_key="notifications.carbon.boq_position_assigned.title",
            body_key="notifications.carbon.boq_position_assigned.body",
            body_context={
                "boq_position_id": str(boq_position_id or ""),
                "carbon_kg": str(carbon_kg),
                "stage": stage,
            },
            entity_type="carbon_inventory",
            entity_id=str(inv.id),
            action_url=f"/carbon/inventories/{inv.id}",
        )
        await session.commit()


# ── Bid management: package awarded → contract draft ────────────────────


async def _on_bid_package_awarded(event: Event) -> None:
    """``bid_management.package.awarded`` → auto-create a ContractDraft.

    Reads the awarded bid + package, then spawns a draft Contract with
    schedule-of-values lines mirroring the winning bid submission lines.
    The contract.metadata back-references the bid package + award so the
    audit trail is unbroken.

    Idempotency is keyed on ``metadata.bid_package_id`` and, when the package
    is linked to a tender package, ``metadata.tender_package_id``, which the
    tender award path writes too, so one logical award drafts one contract
    whichever path fires first. The contract code is only a label: a
    hand-made contract that already uses ``CONTRACT-{code}`` gets a warning
    and the draft a free code, where it used to swallow the award silently.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    package_id_raw = data.get("package_id")
    awarded_bidder_id_raw = data.get("awarded_bidder_id")
    if not (package_id_raw and awarded_bidder_id_raw):
        return
    try:
        package_id = uuid.UUID(str(package_id_raw))
        awarded_bidder_id = uuid.UUID(str(awarded_bidder_id_raw))
    except (ValueError, TypeError):
        return
    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.modules.bid_management.award_contract import (
            add_award_party,
            find_award_contract,
            free_contract_code,
            resolve_award_counterparty,
        )
        from app.modules.bid_management.award_selection import select_awarded_submission
        from app.modules.bid_management.models import (
            Bidder,
            BidPackage,
            BidPackageLineItem,
            BidSubmissionLine,
        )
        from app.modules.contracts.models import Contract, ContractLine

        package = await session.get(BidPackage, package_id)
        if package is None:
            return
        bidder = await session.get(Bidder, awarded_bidder_id)
        if bidder is None:
            return

        # Don't double-create. The key is the award, not the code: a person
        # may have typed CONTRACT-{code} on a contract of their own.
        tender_package_id = str(package.tender_id) if package.tender_id else None
        existing = await find_award_contract(
            session,
            package.project_id,
            keys={"bid_package_id": str(package.id), "tender_package_id": tender_package_id},
        )
        if existing is not None:
            logger.info(
                "bid_management.awarded: contract %s already drafted for package %s (idempotent skip)",
                existing.code,
                package.code,
            )
            return
        code = await free_contract_code(session, f"CONTRACT-{package.code}")

        # The bidder row is a snapshot nobody else can resolve, so it is
        # never the counterparty. The directory entry it was invited from
        # is, and a bidder typed in by hand has none: the contract then
        # names no counterparty and its party carries the company name.
        counterparty = await resolve_award_counterparty(
            session,
            subcontractor_id=bidder.subcontractor_id,
            contact_id=bidder.contact_id,
            company_name=bidder.company_name,
        )

        # Locate the awarded submission so we can mirror lines.
        #
        # This read an unbounded query with ``scalar_one_or_none``, which
        # raises as soon as a bidder holds two submissions in a package -
        # an ordinary shape, since nothing forbids inviting the same
        # company twice. A handler-wide ``except Exception`` reporting at
        # debug level then hid it, so the award created no contract at all
        # and reported nothing. Both halves of that are now gone: the read
        # is bounded, and a failure here reaches the bus. The selector
        # returns one row by a
        # stated precedence and shares it with the purchase-order
        # subscriber, which used to pick a different row.
        sub_row = await select_awarded_submission(session, bidder_id=awarded_bidder_id)

        contract = Contract(
            code=code,
            title=package.title or f"Contract - {package.code}",
            contract_type="lump_sum",
            counterparty_type="subcontractor",
            counterparty_id=counterparty.counterparty_id,
            project_id=package.project_id,
            total_value=Decimal(str(data.get("awarded_amount", "0"))),
            currency=str(data.get("currency", "")) or package.currency,
            status="draft",
            terms={},
            created_by=package.created_by,
        )
        contract.metadata_ = {
            "source": "bid_management.package.awarded",
            "bid_package_id": str(package.id),
            "bid_package_code": package.code,
            "awarded_bidder_id": str(awarded_bidder_id),
            "awarded_bidder_name": bidder.company_name,
        }
        if tender_package_id:
            contract.metadata_["tender_package_id"] = tender_package_id
        if counterparty.contact_id is not None:
            contract.metadata_["counterparty_contact_id"] = str(counterparty.contact_id)
        session.add(contract)
        await session.flush()
        add_award_party(session, contract.id, counterparty)

        # Mirror the package's line items → contract lines, copying
        # the awarded bidder's priced totals when present.
        line_stmt = (
            select(BidPackageLineItem)
            .where(BidPackageLineItem.package_id == package_id)
            .order_by(
                BidPackageLineItem.order_index,
                BidPackageLineItem.code,
            )
        )
        pkg_lines = (await session.execute(line_stmt)).scalars().all()
        priced_by_line: dict[uuid.UUID, BidSubmissionLine] = {}
        if sub_row is not None:
            priced_stmt = select(BidSubmissionLine).where(
                BidSubmissionLine.submission_id == sub_row.id,
            )
            for sl in (await session.execute(priced_stmt)).scalars().all():
                priced_by_line[sl.line_item_id] = sl

        for pkg_line in pkg_lines:
            priced = priced_by_line.get(pkg_line.id)
            if priced is not None:
                qty = Decimal(str(priced.quantity_priced))
                rate = Decimal(str(priced.unit_price))
                total = Decimal(str(priced.total_price))
            else:
                qty = Decimal(str(pkg_line.quantity))
                rate = Decimal("0")
                total = Decimal("0")
            cl = ContractLine(
                contract_id=contract.id,
                code=pkg_line.code,
                description=pkg_line.description,
                scope_section=None,
                line_type="work",
                unit=pkg_line.unit,
                quantity=qty,
                unit_rate=rate,
                total_value=total,
                order_index=pkg_line.order_index,
            )
            cl.metadata_ = {"bid_package_line_id": str(pkg_line.id)}
            if pkg_line.boq_position_id is not None:
                # The key the contracts progress bridge reads, see
                # contracts.service.BOQ_POSITION_META_KEY.
                cl.metadata_["boq_position_id"] = str(pkg_line.boq_position_id)
            session.add(cl)

        await session.commit()

        event_bus.publish_detached(
            "contracts.contract.drafted_from_bid_award",
            {
                "contract_id": str(contract.id),
                "contract_code": contract.code,
                "bid_package_id": str(package.id),
                "awarded_bidder_id": str(awarded_bidder_id),
                "total_value": str(contract.total_value),
                "project_id": str(package.project_id),
            },
            source_module="contracts",
        )
        logger.info(
            "Auto-created contract draft %s from bid award (package=%s)",
            contract.code,
            package.code,
        )


# ── Contract value: one commercial change, one posting identity ──────────

# Shared bucket naming every commercial change this contract has been posted
# for, written by both money subscribers below and read by both.
_POSTED_SOURCES_KEY = "posted_sources"


def _contract_source_key(variation_order_id: object = None, change_order_id: object = None) -> str:
    """Name the commercial change a contract post is made *for*.

    A variation order and the change order that mirrors it
    (``VariationsService.convert_vr_to_vo``) are one commercial change, so
    both resolve to the same key and only the first of them posts.

    Keying on the source rather than on whether the money has already landed
    is what makes the guard independent of the order the two events arrive
    in. "Have I posted for this source" can be answered before either side
    has posted; "is the money already there" can only be answered afterwards,
    so a guard shaped that way is order-dependent by construction and lets
    the pair through whenever the mirror is approved first. The cost spine
    (``CostSpineService.post_actual_to_budget_line``, keyed on
    ``(source_kind, source_ref)``) and the purchase-order commitment markers
    (``committed_from_po:<po_id>``) use this shape for the same reason.
    """
    if variation_order_id:
        return f"variation_order:{variation_order_id}"
    return f"change_order:{change_order_id}"


def _posted_source_keys(md: dict) -> set[str]:
    """Every commercial change this contract has already moved money for.

    Reads the shared bucket and also derives keys from the two legacy per-path
    id lists, so a contract whose metadata was written before the shared
    bucket existed stays guarded without a migration: ``variation_ids``
    derives exactly the key a mirroring change order computes for itself.

    Those legacy lists record the ids a handler *saw*, not the ids it paid, so
    anything the currency guard stopped is subtracted back out. Without that a
    variation order raised in a foreign currency would sit in ``variation_ids``
    having moved nothing, and still silence its mirror - whose currency can be
    corrected on its own (``ChangeOrderUpdate.currency``), so the mirror is
    exactly the half that could have posted. Both would stand down and the
    amount would be lost. The shared bucket needs no such correction because it
    is stamped only where the money moves.
    """
    keys = {str(s) for s in (md.get(_POSTED_SOURCES_KEY) or [])}
    unpaid: set[str] = set()
    for entry in md.get("skipped_currency_mismatch") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("variation_id"):
            unpaid.add(_contract_source_key(variation_order_id=entry["variation_id"]))
        if entry.get("change_order_id"):
            unpaid.add(_contract_source_key(change_order_id=entry["change_order_id"]))
    derived = {_contract_source_key(variation_order_id=v) for v in (md.get("variation_ids") or [])}
    derived |= {_contract_source_key(change_order_id=c) for c in (md.get("change_order_ids") or [])}
    return keys | (derived - unpaid)


def _record_posted_source(md: dict, source_key: str) -> None:
    """Stamp *source_key* into the shared bucket, once."""
    posted = list(md.get(_POSTED_SOURCES_KEY) or [])
    if source_key not in {str(s) for s in posted}:
        posted.append(source_key)
    md[_POSTED_SOURCES_KEY] = posted


def _record_mirror_skip(
    md: dict, *, change_order_id: object, variation_order_id: object, delta: object, skipped: str
) -> bool:
    """Record that one half of a mirrored pair declined to post. True if newly recorded.

    Kept out of ``variation_ids`` / ``change_order_ids`` because the dashboard
    rollup counts those lists, and a skipped post there would inflate the
    count with no matching value.
    """
    entries = list(md.get("skipped_variation_mirror") or [])
    already = any(
        isinstance(e, dict)
        and str(e.get("variation_order_id")) == str(variation_order_id)
        and str(e.get("skipped")) == skipped
        for e in entries
    )
    if already:
        return False
    entries.append(
        {
            "change_order_id": str(change_order_id) if change_order_id else None,
            "variation_order_id": str(variation_order_id),
            "cost_impact": str(delta),
            # Which half declined; the other half carried the money.
            "skipped": skipped,
        }
    )
    md["skipped_variation_mirror"] = entries
    return True


async def _post_to_sov(session, contract, source_key: str, kind: str, source_id: object, data: dict, delta) -> None:
    """Put the change on the schedule of values in the transaction that moved the sum.

    See ``app.modules.contracts.sov_posting``: one pooled line and one
    adjustment under the same source key, nothing on a replay.
    """
    from datetime import UTC, datetime

    from app.modules.contracts.sov_posting import post_source_to_sov

    try:
        parsed_id = uuid.UUID(str(source_id))
    except (ValueError, TypeError):
        parsed_id = None
    code = str(data.get("code") or "")
    await post_source_to_sov(
        session,
        contract,
        key=source_key,
        kind=kind,
        source_id=parsed_id,
        code=code,
        title=code,
        amount=delta,
        currency=str(data.get("currency") or contract.currency or ""),
        approved_on=datetime.now(UTC).date(),
    )


# ── Variations: VO completed → contract sum bump ─────────────────────────


async def _on_variation_completed(event: Event) -> None:
    """``variations.contract_sum.updated`` → bump Contract.total_value.

    When a VO is completed against an affected contract, this subscriber
    adjusts the contract's running ``total_value`` by the VO's
    ``delta_amount`` (positive = additive variation, negative = deductive).
    Redelivery of the same VO is keyed on its own id in
    ``contract.metadata.variation_ids``. The *commercial change* is keyed
    separately on ``_contract_source_key``, so a variation whose mirrored
    change order has already been approved against this contract stands down
    rather than posting the amount a second time.

    Money safety (mirrors ``_on_changeorder_approved_contract``):
    * Lost-update guard - the contract row is loaded with ``SELECT ... FOR
      UPDATE`` and the value bump is an atomic ``UPDATE ... SET total_value =
      total_value + delta`` so a concurrent VO/CO bump can never be lost.
    * Project guard - the contract link rides on VO data, so a VO in project A
      could name a contract in project B. Apply only when both agree.
    * Currency guard - never blend currencies into ``total_value``; a mismatch
      is recorded in metadata instead of silently dropped.
    * Amendability guard - terminated / completed contracts are skipped with a
      log, never raising (a background subscriber must not break the VO flow).
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    contract_id_raw = data.get("contract_id")
    vo_id_raw = data.get("vo_id")
    delta_raw = data.get("delta_amount", "0")
    if not (contract_id_raw and vo_id_raw):
        return
    try:
        contract_id = uuid.UUID(str(contract_id_raw))
        delta = Decimal(str(delta_raw))
    except (ValueError, TypeError, InvalidOperation):
        return
    async with async_session_factory() as session:
        from sqlalchemy import select as sa_select
        from sqlalchemy import update as sa_update

        from app.modules.contracts.models import Contract

        stmt = sa_select(Contract).where(Contract.id == contract_id).with_for_update()
        contract = (await session.execute(stmt)).scalar_one_or_none()
        if contract is None:
            return
        # Project guard: the contract link arrives via VO data, so a VO in
        # project A could name a contract that belongs to project B. Only
        # apply when both sides agree.
        event_project = data.get("project_id")
        if not event_project or str(contract.project_id) != str(event_project):
            logger.warning(
                "VO %s completed in project %s but linked contract %s belongs to project %s - not applied",
                vo_id_raw,
                event_project,
                contract_id,
                contract.project_id,
            )
            return
        md = dict(contract.metadata_ or {})
        applied = list(md.get("variation_ids") or [])
        if str(vo_id_raw) in {str(v) for v in applied}:
            # Already applied - idempotent skip.
            return
        # Mirror guard, the other half of the one in the CO subscriber: the
        # change order mirroring this VO may have been approved first, in
        # which case it has already posted this commercial change under the
        # same source key and this VO must not post it again.
        source_key = _contract_source_key(variation_order_id=vo_id_raw)
        if source_key in _posted_source_keys(md):
            if _record_mirror_skip(
                md,
                change_order_id=None,
                variation_order_id=vo_id_raw,
                delta=delta,
                skipped="variation_order",
            ):
                contract.metadata_ = md
                await session.commit()
            logger.info(
                "VO %s is already on contract %s via its mirrored change order - "
                "total_value not bumped again (recorded in skipped_variation_mirror)",
                vo_id_raw,
                contract.code,
            )
            return
        if contract.status in ("terminated", "completed"):
            # A VO must not rewrite the final agreed value of a closed
            # contract - same amendability guard as the CO subscriber.
            logger.info(
                "Contract %s is %s - VO %s value not applied (use the final-account amendment workflow)",
                contract.code,
                contract.status,
                vo_id_raw,
            )
            return
        applied.append(str(vo_id_raw))
        md["variation_ids"] = applied

        # Currency guard: never blend currencies into total_value. The VO
        # is still recorded so it is not silently lost - the project team
        # resolves the mismatch manually.
        event_currency = str(data.get("currency") or "").strip().upper()
        contract_currency = str(contract.currency or "").strip().upper()
        if event_currency and event_currency != contract_currency:
            skipped = list(md.get("skipped_currency_mismatch") or [])
            skipped.append(
                {
                    "variation_id": str(vo_id_raw),
                    "delta_amount": str(delta),
                    "currency": event_currency,
                }
            )
            md["skipped_currency_mismatch"] = skipped
            contract.metadata_ = md
            await session.commit()
            logger.warning(
                "VO %s completed with currency %s but contract %s is in %s - "
                "total_value not bumped (recorded in skipped_currency_mismatch)",
                vo_id_raw,
                event_currency,
                contract.code,
                contract_currency or "(unset)",
            )
            return

        md["variation_total"] = str(Decimal(str(md.get("variation_total") or 0)) + delta)
        # Stamped only on the path that actually moves the money, so a
        # currency mismatch above never silences the other half.
        _record_posted_source(md, source_key)
        contract.metadata_ = md
        # Atomic increment - no read-modify-write on the money column,
        # so a concurrent bump can never be lost.
        await session.execute(
            sa_update(Contract).where(Contract.id == contract_id).values(total_value=Contract.total_value + delta)
        )
        await _post_to_sov(session, contract, source_key, "variation_order", vo_id_raw, data, delta)
        await session.commit()
        logger.info(
            "Contract %s total_value bumped by %s (VO=%s)",
            contract.code,
            delta,
            vo_id_raw,
        )


# ── Change orders: CO approved → contract sum bump ───────────────────────


async def _on_changeorder_approved_contract(event: Event) -> None:
    """``changeorder.approved`` → bump the linked Contract.total_value.

    A change order can carry an optional ``metadata.contract_id`` link to
    the commercial contract it amends (stamped by the create form; no
    dedicated column). On approval the CO's ``cost_impact`` is applied to
    the contract's running ``total_value`` - previously only the project
    budget and BOQ moved, leaving the contract value silently stale.

    Most COs have no contract link: skip silently when ``contract_id`` is
    absent or unparseable. Idempotency is keyed on the CO id stored in
    ``contract.metadata.change_order_ids`` (mirrors the variation
    subscriber above). Terminated / completed contracts are skipped with a
    log instead of raising - same amendability guard as
    ``ContractsService.apply_change_order_to_contract``, but a background
    subscriber must never break the foreground approval.

    Money safety (audit M3):
    * Currency guard - when the event carries a ``currency`` that differs
      from the contract currency, the value bump is skipped with a warning
      (never blend currencies). The CO is still recorded in metadata
      (``change_order_ids`` + a ``skipped_currency_mismatch`` entry with its
      currency) so it is not silently lost.
    * Lost-update guard - the contract row is loaded with
      ``SELECT ... FOR UPDATE`` so the metadata read-modify-write cannot
      race a concurrent approval, and the value bump itself is an atomic
      ``UPDATE ... SET total_value = total_value + delta``.
    * Mirror guard - a CO that mirrors a variation order (created by
      ``VariationsService.convert_vr_to_vo``, carrying
      ``metadata.variation_order_id``) posts under that variation order's
      source key rather than its own, so the pair posts once whichever half
      is approved first. See ``_contract_source_key`` for why the key names
      the source instead of asking whether the money has already landed, and
      ``tests/integration/test_variation_mirror_contract_double_post.py``
      for both orderings.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    contract_id_raw = data.get("contract_id")
    co_id_raw = data.get("change_order_id")
    delta_raw = data.get("cost_impact", "0")
    if not (contract_id_raw and co_id_raw):
        return
    try:
        contract_id = uuid.UUID(str(contract_id_raw))
        delta = Decimal(str(delta_raw))
    except (ValueError, TypeError, InvalidOperation):
        return
    async with async_session_factory() as session:
        from sqlalchemy import select as sa_select
        from sqlalchemy import update as sa_update

        from app.modules.contracts.models import Contract

        stmt = sa_select(Contract).where(Contract.id == contract_id).with_for_update()
        contract = (await session.execute(stmt)).scalar_one_or_none()
        if contract is None:
            return
        # Project guard: the contract link arrives via client-supplied
        # CO metadata, so a CO in project A could name a contract that
        # belongs to project B. Only apply when both sides agree.
        event_project = data.get("project_id")
        if not event_project or str(contract.project_id) != str(event_project):
            logger.warning(
                "CO %s approved in project %s but linked contract %s belongs to project %s - not applied",
                co_id_raw,
                event_project,
                contract_id,
                contract.project_id,
            )
            return
        md = dict(contract.metadata_ or {})
        applied = list(md.get("change_order_ids") or [])
        if str(co_id_raw) in {str(v) for v in applied}:
            # Already applied - idempotent skip.
            return
        if contract.status in ("terminated", "completed"):
            # Same guard as apply_change_order_to_contract: a CO must
            # not rewrite the final agreed value of a closed contract.
            logger.info(
                "Contract %s is %s - CO %s value not applied (use the final-account amendment workflow)",
                contract.code,
                contract.status,
                co_id_raw,
            )
            return

        # Mirror guard: promoting a variation request auto-creates a change
        # order that mirrors the variation order's money and carries its id
        # (``metadata.variation_order_id``). Both rows are commercially the
        # same change, and both have a subscriber that adds to this
        # contract, so once the VO has posted here the mirror must not post
        # again. Keyed on the mirror link, never on the contract: a change
        # order a user raised against the same contract carries no variation
        # link and still posts. Recorded rather than dropped, and kept out
        # of ``change_order_ids`` because the dashboard rollup counts that
        # list - a skipped post there would inflate the count with no
        # matching value.
        mirrored_vo_id = data.get("variation_order_id")
        source_key = _contract_source_key(
            variation_order_id=mirrored_vo_id,
            change_order_id=co_id_raw,
        )
        if mirrored_vo_id and source_key in _posted_source_keys(md):
            if _record_mirror_skip(
                md,
                change_order_id=co_id_raw,
                variation_order_id=mirrored_vo_id,
                delta=delta,
                skipped="change_order",
            ):
                contract.metadata_ = md
                await session.commit()
            logger.info(
                "CO %s mirrors variation order %s, which is already on contract %s - "
                "total_value not bumped again (recorded in skipped_variation_mirror)",
                co_id_raw,
                mirrored_vo_id,
                contract.code,
            )
            return

        applied.append(str(co_id_raw))
        md["change_order_ids"] = applied

        # Currency guard: never blend currencies into total_value. The
        # CO is still recorded so it is not silently lost - the project
        # team resolves the mismatch manually.
        event_currency = str(data.get("currency") or "").strip().upper()
        contract_currency = str(contract.currency or "").strip().upper()
        if event_currency and event_currency != contract_currency:
            skipped = list(md.get("skipped_currency_mismatch") or [])
            skipped.append(
                {
                    "change_order_id": str(co_id_raw),
                    "cost_impact": str(delta),
                    "currency": event_currency,
                }
            )
            md["skipped_currency_mismatch"] = skipped
            contract.metadata_ = md
            await session.commit()
            logger.warning(
                "CO %s approved with currency %s but contract %s is in %s - "
                "total_value not bumped (recorded in skipped_currency_mismatch)",
                co_id_raw,
                event_currency,
                contract.code,
                contract_currency or "(unset)",
            )
            return

        md["change_order_total"] = str(Decimal(str(md.get("change_order_total") or 0)) + delta)
        # Stamped only on the path that actually moves the money. For a
        # mirror this is the variation order's key, so the VO that follows
        # recognises its own change as posted whichever half arrived first.
        _record_posted_source(md, source_key)
        contract.metadata_ = md
        # Atomic increment - no read-modify-write on the money column,
        # so a concurrent bump can never be lost.
        await session.execute(
            sa_update(Contract).where(Contract.id == contract_id).values(total_value=Contract.total_value + delta)
        )
        await _post_to_sov(session, contract, source_key, "change_order", co_id_raw, data, delta)
        await session.commit()
        logger.info(
            "Contract %s total_value bumped by %s (CO=%s)",
            contract.code,
            delta,
            co_id_raw,
        )


# ── QMS: HSE→QMS NCR mirror → notification ───────────────────────────────


async def _on_qms_ncr_mirrored_from_hse(event: Event) -> None:
    """``qms.ncr.mirrored_from_hse`` → notify HSE incident owner + QMS owner.

    Closes the visibility gap: when an HSE incident's CAPA spawns a
    mirrored QMS NCR (see ``qms/events.py::_on_hse_incident_root_cause``),
    both the originating HSE incident reporter and the QMS NCR owner
    should see the cross-module hand-off in their notification inbox.

    Payload (from publisher):
        - hse_incident_id (may be empty if CAPA had no source_ref)
        - ncr_id
        - project_id
        - severity
        - ncr_owner_user_id (may be empty)
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    ncr_id = data.get("ncr_id")
    hse_incident_id = data.get("hse_incident_id") or ""
    severity = data.get("severity") or "minor"
    if not ncr_id:
        return
    async with async_session_factory() as session:
        recipients: set[str] = set()

        # Resolve HSE incident owner via the linked SafetyIncident row.
        if hse_incident_id:
            try:
                incident_uuid = uuid.UUID(str(hse_incident_id))
            except (ValueError, TypeError):
                incident_uuid = None
            if incident_uuid is not None:
                from app.modules.safety.models import (  # noqa: PLC0415
                    SafetyIncident,
                )

                incident = await session.get(SafetyIncident, incident_uuid)
                if incident is not None and incident.created_by:
                    recipients.add(str(incident.created_by))

        # Resolve QMS owner (best-effort; payload may carry it directly,
        # else fall back to QMSNCR.raised_by).
        qms_owner = data.get("ncr_owner_user_id") or ""
        if qms_owner:
            recipients.add(str(qms_owner))
        else:
            try:
                ncr_uuid = uuid.UUID(str(ncr_id))
            except (ValueError, TypeError):
                ncr_uuid = None
            if ncr_uuid is not None:
                from app.modules.qms.models import QMSNCR  # noqa: PLC0415

                ncr = await session.get(QMSNCR, ncr_uuid)
                if ncr is not None and ncr.raised_by:
                    recipients.add(str(ncr.raised_by))

        if not recipients:
            return

        svc = NotificationService(session)
        for uid in recipients:
            await svc.create(
                user_id=uid,
                notification_type=(
                    "qms_ncr_mirrored_critical" if severity in {"critical", "major"} else "qms_ncr_mirrored"
                ),
                title_key="notifications.qms.ncr_mirrored_from_hse.title",
                body_key="notifications.qms.ncr_mirrored_from_hse.body",
                body_context={
                    "hse_incident_id": str(hse_incident_id),
                    "ncr_id": str(ncr_id),
                    "severity": severity,
                },
                entity_type="qms_ncr",
                entity_id=str(ncr_id),
                action_url=f"/qms/ncrs/{ncr_id}",
            )
        await session.commit()


# ── Change orders: CO approved → extend master schedule ────────────────


async def _on_changeorder_approved_schedule(event: Event) -> None:
    """``changeorder.approved`` → extend the master schedule end date.

    When a CO carries ``schedule_impact_days > 0``, the project's master
    schedule end date is pushed forward by that many calendar days (OC-33).
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    days = int(data.get("schedule_impact_days") or 0)
    project_id_raw = data.get("project_id")
    if days <= 0 or not project_id_raw:
        return
    try:
        from datetime import date, timedelta
        from uuid import UUID

        from sqlalchemy import select

        pid = UUID(str(project_id_raw))
        async with async_session_factory() as session:
            from app.modules.schedule.models import Schedule

            rows = (
                (
                    await session.execute(
                        select(Schedule).where(Schedule.project_id == pid, Schedule.schedule_type == "master")
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return
            sched = rows[0]
            if not sched.end_date:
                return
            old_end = date.fromisoformat(str(sched.end_date)[:10])
            new_end = old_end + timedelta(days=days)
            sched.end_date = new_end.isoformat()
            await session.commit()
            logger.info(
                "CO %s extended master schedule %s end date by %d days: %s -> %s",
                data.get("change_order_id"),
                sched.id,
                days,
                old_end.isoformat(),
                new_end.isoformat(),
            )
    except Exception:
        logger.warning("Schedule extension failed for CO %s", data.get("change_order_id"), exc_info=True)


# ── Registration ─────────────────────────────────────────────────────────


_SUBSCRIPTIONS: tuple[tuple[str, Callable[[Event], object]], ...] = (
    ("resources.cert_expiring", _on_cert_expiring),
    ("contracts.retention.released", _on_retention_released),
    ("crm.opportunity.won", _on_opportunity_won),
    ("crm.opportunity.scored", _on_opportunity_scored),
    ("carbon.boq_position.assigned", _on_boq_position_assigned),
    ("bid_management.package.awarded", _on_bid_package_awarded),
    ("variations.contract_sum.updated", _on_variation_completed),
    ("changeorder.approved", _on_changeorder_approved_contract),
    ("changeorder.approved", _on_changeorder_approved_schedule),
    ("qms.ncr.mirrored_from_hse", _on_qms_ncr_mirrored_from_hse),
)


def register_wave5_notification_subscribers() -> None:
    """Idempotently register every wave-5 cross-module subscriber."""
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe_once(event_name, handler)
    logger.info(
        "Notifications: subscribed to %d wave-5 cross-module event(s)",
        len(_SUBSCRIPTIONS),
    )
