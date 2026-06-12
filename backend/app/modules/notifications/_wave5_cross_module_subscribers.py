"""‌⁠‍Wave-5 cross-module subscribers - Resources / Contracts / CRM / Carbon.

Wires real cross-module side-effects emitted by the wave-5 deep-dive:

* ``resources.cert_expiring`` → notification per expiring certification.
* ``contracts.claim.certified`` → finance Invoice (AR direction, project-scoped).
* ``contracts.retention.released`` → notification for project owner.
* ``crm.opportunity.won`` → bid_management BidPackage (draft, pre-populated).
* ``crm.opportunity.scored`` → notification for opportunity owner.
* ``carbon.boq_position.assigned`` → notification for project sustainability lead.
* ``changeorder.approved`` → revise the linked contract's total_value (when
  the CO carries ``metadata.contract_id``).

All handlers are best-effort: they swallow exceptions so a downstream
failure never breaks the foreground request. Each subscriber gates on
PostgreSQL because cross-session writes on SQLite would deadlock the
single writer (dev-DB).
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
    """‌⁠‍Always True post-Epic-B - see :mod:`app.modules.notifications.events`."""
    return True


# ── Resources: certification expiry → notification ───────────────────────


async def _on_cert_expiring(event: Event) -> None:
    """‌⁠‍``resources.cert_expiring`` → notify the resource owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    resource_id = data.get("resource_id")
    cert_type = data.get("cert_type", "")
    valid_until = data.get("valid_until", "")
    window_days = data.get("window_days", 0)
    if not resource_id:
        return
    try:
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
    except Exception:
        logger.debug("notifications: _on_cert_expiring failed", exc_info=True)


# ── Contracts: claim certified → finance invoice ─────────────────────────


async def _on_claim_certified(event: Event) -> None:
    """``contracts.claim.certified`` → create a draft Invoice (AR direction).

    Reads the claim's net_due + contract's currency + counterparty, and
    spawns an Invoice referencing back to the claim through metadata.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    claim_id = data.get("claim_id")
    contract_id = data.get("contract_id")
    if not (claim_id and contract_id):
        return
    try:
        async with async_session_factory() as session:
            from app.modules.contracts.repository import (
                ContractRepository,
                ProgressClaimRepository,
            )
            from app.modules.finance.models import Invoice

            claim_repo = ProgressClaimRepository(session)
            contract_repo = ContractRepository(session)
            try:
                claim = await claim_repo.get_by_id(uuid.UUID(str(claim_id)))
                contract = await contract_repo.get_by_id(uuid.UUID(str(contract_id)))
            except (ValueError, TypeError):
                return
            if claim is None or contract is None:
                return
            # Dedupe: skip if metadata already records an auto-invoice.
            meta = dict(claim.metadata_ or {})
            if meta.get("auto_invoice_id"):
                logger.debug(
                    "claim %s already auto-invoiced (%s)",
                    claim_id,
                    meta["auto_invoice_id"],
                )
                return
            net_due = Decimal(str(claim.net_due or 0))
            if net_due <= 0:
                return
            from datetime import UTC, datetime, timedelta

            invoice = Invoice(
                project_id=contract.project_id,
                contact_id=str(contract.counterparty_id) if contract.counterparty_id else None,
                invoice_direction="receivable",
                invoice_number=f"PC-{claim.claim_number or claim.id}",
                invoice_date=datetime.now(UTC).date().isoformat(),
                due_date=(datetime.now(UTC).date() + timedelta(days=30)).isoformat(),
                currency_code=contract.currency or "",
                amount_subtotal=Decimal(str(claim.gross_amount or 0)) - Decimal(str(claim.retention_amount or 0)),
                tax_amount=Decimal("0"),
                retention_amount=Decimal(str(claim.retention_amount or 0)),
                amount_total=net_due,
                status="draft",
                payment_terms_days="30",
                notes=(
                    f"Auto-generated from certified progress claim {claim.claim_number} on contract {contract.code}"
                ),
            )
            invoice.metadata_ = {
                "source": "contracts.claim.certified",
                "contract_id": str(contract.id),
                "claim_id": str(claim.id),
                "claim_number": claim.claim_number,
            }
            session.add(invoice)
            await session.flush()
            # Stash the invoice id back into the claim metadata so we don't
            # double-issue on subsequent events.
            meta["auto_invoice_id"] = str(invoice.id)
            await claim_repo.update_fields(claim.id, metadata_=meta)
            await session.commit()
            event_bus.publish_detached(
                "finance.invoice.created",
                {
                    "invoice_id": str(invoice.id),
                    "source": "contracts.claim.certified",
                    "claim_id": str(claim.id),
                    "amount_total": str(net_due),
                    "currency": contract.currency or "",
                },
                source_module="finance",
            )
            logger.info(
                "Auto-created invoice %s from claim %s (net_due=%s)",
                invoice.id,
                claim.id,
                net_due,
            )
    except Exception:
        logger.debug("notifications: _on_claim_certified failed", exc_info=True)


# ── Contracts: retention released → notification ─────────────────────────


async def _on_retention_released(event: Event) -> None:
    """``contracts.retention.released`` → notify project owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    contract_id = data.get("contract_id")
    if not contract_id:
        return
    try:
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
    except Exception:
        logger.debug("notifications: _on_retention_released failed", exc_info=True)


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
    try:
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
    except Exception:
        logger.debug("notifications: _on_opportunity_won failed", exc_info=True)


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
    try:
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
    except Exception:
        logger.debug("notifications: _on_opportunity_scored failed", exc_info=True)


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
    try:
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
    except Exception:
        logger.debug(
            "notifications: _on_boq_position_assigned failed",
            exc_info=True,
        )


# ── Bid management: package awarded → contract draft ────────────────────


async def _on_bid_package_awarded(event: Event) -> None:
    """``bid_management.package.awarded`` → auto-create a ContractDraft.

    Reads the awarded bid + package, then spawns a draft Contract with
    schedule-of-values lines mirroring the winning bid submission lines.
    The contract.metadata back-references the bid package + award so the
    audit trail is unbroken.
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
    try:
        async with async_session_factory() as session:
            from sqlalchemy import select

            from app.modules.bid_management.models import (
                Bidder,
                BidInvitation,
                BidPackage,
                BidPackageLineItem,
                BidSubmission,
                BidSubmissionLine,
            )
            from app.modules.contracts.models import Contract, ContractLine

            package = await session.get(BidPackage, package_id)
            if package is None:
                return
            bidder = await session.get(Bidder, awarded_bidder_id)
            if bidder is None:
                return

            # Don't double-create: deterministic code keyed on package id.
            code = f"CONTRACT-{package.code}"
            existing = await session.execute(
                select(Contract).where(Contract.code == code),
            )
            if existing.scalar_one_or_none() is not None:
                return

            # Locate the awarded submission so we can mirror lines.
            sub_stmt = (
                select(BidSubmission)
                .join(BidInvitation, BidInvitation.id == BidSubmission.invitation_id)
                .where(
                    BidInvitation.package_id == package_id,
                    BidSubmission.bidder_id == awarded_bidder_id,
                )
            )
            sub_row = (await session.execute(sub_stmt)).scalar_one_or_none()

            contract = Contract(
                code=code,
                title=package.title or f"Contract - {package.code}",
                contract_type="lump_sum",
                counterparty_type="subcontractor",
                counterparty_id=awarded_bidder_id,
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
            session.add(contract)
            await session.flush()

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
    except Exception:
        logger.debug(
            "notifications: _on_bid_package_awarded failed",
            exc_info=True,
        )


# ── Variations: VO completed → contract sum bump ─────────────────────────


async def _on_variation_completed(event: Event) -> None:
    """``variations.contract_sum.updated`` → bump Contract.total_value.

    When a VO is completed against an affected contract, this subscriber
    adjusts the contract's running ``total_value`` by the VO's
    ``delta_amount`` (positive = additive variation, negative = deductive).
    Idempotency is keyed on the VO id stored in ``contract.metadata.variation_ids``.
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
    except (ValueError, TypeError):
        return
    try:
        async with async_session_factory() as session:
            from app.modules.contracts.repository import ContractRepository

            repo = ContractRepository(session)
            contract = await repo.get_by_id(contract_id)
            if contract is None:
                return
            md = dict(contract.metadata_ or {})
            applied = list(md.get("variation_ids") or [])
            if str(vo_id_raw) in {str(v) for v in applied}:
                # Already applied - idempotent skip.
                return
            applied.append(str(vo_id_raw))
            md["variation_ids"] = applied
            md["variation_total"] = str(Decimal(str(md.get("variation_total") or 0)) + delta)
            contract.metadata_ = md
            contract.total_value = Decimal(str(contract.total_value or 0)) + delta
            await session.commit()
            logger.info(
                "Contract %s total_value bumped by %s (VO=%s)",
                contract.code,
                delta,
                vo_id_raw,
            )
    except Exception:
        logger.debug(
            "notifications: _on_variation_completed failed",
            exc_info=True,
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
    try:
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
            contract.metadata_ = md
            # Atomic increment - no read-modify-write on the money column,
            # so a concurrent bump can never be lost.
            await session.execute(
                sa_update(Contract).where(Contract.id == contract_id).values(total_value=Contract.total_value + delta)
            )
            await session.commit()
            logger.info(
                "Contract %s total_value bumped by %s (CO=%s)",
                contract.code,
                delta,
                co_id_raw,
            )
    except Exception:
        logger.debug(
            "notifications: _on_changeorder_approved_contract failed",
            exc_info=True,
        )


# ── QMS: HSE→QMS NCR mirror → notification ───────────────────────────────


async def _on_qms_ncr_mirrored_from_hse(event: Event) -> None:
    """‌⁠‍``qms.ncr.mirrored_from_hse`` → notify HSE incident owner + QMS owner.

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
    try:
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
    except Exception:
        logger.debug(
            "notifications: _on_qms_ncr_mirrored_from_hse failed",
            exc_info=True,
        )


# ── Registration ─────────────────────────────────────────────────────────


_SUBSCRIPTIONS: tuple[tuple[str, Callable[[Event], object]], ...] = (
    ("resources.cert_expiring", _on_cert_expiring),
    ("contracts.claim.certified", _on_claim_certified),
    ("contracts.retention.released", _on_retention_released),
    ("crm.opportunity.won", _on_opportunity_won),
    ("crm.opportunity.scored", _on_opportunity_scored),
    ("carbon.boq_position.assigned", _on_boq_position_assigned),
    ("bid_management.package.awarded", _on_bid_package_awarded),
    ("variations.contract_sum.updated", _on_variation_completed),
    ("changeorder.approved", _on_changeorder_approved_contract),
    ("qms.ncr.mirrored_from_hse", _on_qms_ncr_mirrored_from_hse),
)


def register_wave5_notification_subscribers() -> None:
    """Idempotently register every wave-5 cross-module subscriber."""
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    logger.info(
        "Notifications: subscribed to %d wave-5 cross-module event(s)",
        len(_SUBSCRIPTIONS),
    )
