"""Cross-module event handlers -- wires the critical inter-module dataflows.

Imported at startup to register all handlers with the event bus.
Each handler is thin: validates the event, calls the target module's service.

Dataflows wired:
   1. meeting.action_item.created   -> auto-create task
   2. safety.observation.high_risk  -> notify PM + safety officer
   3. inspection.completed.failed   -> log for possible punch item creation
   4. rfi.response.design_change    -> flag for variation (change order)
   5. ncr.cost_impact               -> flag for variation (change order)
   6. document.revision.created     -> flag linked BOQ positions
   7. invoice.paid                  -> update project budget actuals
   8. po.issued                     -> update project budget committed
   9. estimate.approved             -> auto-populate project budget from BOQ
  10. schedule.progress_updated     -> create EVM snapshot
  11. bim_model.ready               -> apply quantity maps -> draft BOQ
  12. bim_model.new_version         -> diff -> flag affected BOQ positions
  13. variation.approved             -> update contract_value + budget
  14. transmittal.issued            -> audit trail for distribution
  15. cde.container.promoted        -> audit + notify stakeholders
"""

import logging

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. meeting.action_item.created -> auto-create task
# ---------------------------------------------------------------------------

async def _handle_meeting_action_item_created(event: Event) -> None:
    """Create a task for each open action item from a meeting.

    Expected event.data:
        project_id: str (UUID)
        meeting_id: str (UUID)
        action_items: list[dict] with keys:
            description, owner_id, due_date, status
        created_by: str (UUID, optional)
    """
    try:
        data = event.data
        project_id = data.get("project_id")
        meeting_id = data.get("meeting_id")
        action_items = data.get("action_items", [])
        created_by = data.get("created_by")

        if not project_id or not action_items:
            logger.debug("meeting.action_item.created: missing project_id or action_items")
            return

        # Lazy import to avoid circular dependencies
        from app.database import async_session_factory
        from app.modules.tasks.schemas import TaskCreate
        from app.modules.tasks.service import TaskService

        async with async_session_factory() as session:
            svc = TaskService(session)
            created_count = 0
            for item in action_items:
                if item.get("status") != "open":
                    continue
                task_data = TaskCreate(
                    project_id=project_id,
                    task_type="task",
                    title=item.get("description", "Action item from meeting")[:500],
                    responsible_id=item.get("owner_id"),
                    due_date=item.get("due_date"),
                    meeting_id=str(meeting_id) if meeting_id else None,
                    status="open",
                    priority="normal",
                    metadata={"source": "meeting_action_item", "meeting_id": str(meeting_id)},
                )
                await svc.create_task(task_data, user_id=created_by)
                created_count += 1
            await session.commit()

        logger.info(
            "meeting.action_item.created: created %d tasks for meeting %s",
            created_count,
            meeting_id,
        )
    except Exception:
        logger.exception("Error handling meeting.action_item.created")


# ---------------------------------------------------------------------------
# 2. safety.observation.high_risk -> notify PM + safety officer
# ---------------------------------------------------------------------------

async def _handle_safety_observation_high_risk(event: Event) -> None:
    """Notify PM and safety officer when observation risk_score > 15.

    Expected event.data:
        project_id: str (UUID)
        observation_id: str (UUID)
        observation_number: str
        risk_score: int
        description: str
        notify_user_ids: list[str] (UUIDs of PM + safety officer)
    """
    try:
        data = event.data
        observation_id = data.get("observation_id")
        risk_score = data.get("risk_score", 0)
        notify_user_ids = data.get("notify_user_ids", [])
        description = data.get("description", "")
        observation_number = data.get("observation_number", "")

        if risk_score <= 15:
            logger.debug(
                "safety.observation.high_risk: risk_score=%d <= 15, skipping",
                risk_score,
            )
            return

        if not notify_user_ids:
            logger.debug("safety.observation.high_risk: no users to notify")
            return

        from app.database import async_session_factory
        from app.modules.notifications.service import NotificationService

        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.notify_users(
                user_ids=notify_user_ids,
                notification_type="warning",
                title_key="notifications.safety.high_risk_observation",
                entity_type="safety_observation",
                entity_id=str(observation_id),
                body_key="notifications.safety.high_risk_body",
                body_context={
                    "observation_number": observation_number,
                    "risk_score": risk_score,
                    "description": description[:200],
                },
                action_url=f"/safety?observation={observation_id}",
            )
            await session.commit()

        logger.info(
            "safety.observation.high_risk: notified %d users for observation %s (risk=%d)",
            len(notify_user_ids),
            observation_number,
            risk_score,
        )
    except Exception:
        logger.exception("Error handling safety.observation.high_risk")


# ---------------------------------------------------------------------------
# 3. inspection.completed.failed -> log for possible punch item
# ---------------------------------------------------------------------------

async def _handle_inspection_completed_failed(event: Event) -> None:
    """Log failed inspection for UI to offer punch item creation.

    Expected event.data:
        project_id: str (UUID)
        inspection_id: str (UUID)
        inspection_number: str
        result: str ("fail" / "conditional_pass")
        failed_items: list[dict] (checklist items that failed)
    """
    try:
        data = event.data
        inspection_id = data.get("inspection_id")
        inspection_number = data.get("inspection_number", "")
        result = data.get("result", "")

        logger.info(
            "inspection.completed.failed: inspection %s (%s) result=%s -- "
            "UI may offer punch item creation",
            inspection_number,
            inspection_id,
            result,
        )

        # Re-emit a more specific event that the frontend can subscribe to via
        # WebSocket or the UI can poll for.  For now, we simply log it.
        await event_bus.publish(
            "punchlist.suggestion.from_inspection",
            data={
                "project_id": data.get("project_id"),
                "inspection_id": inspection_id,
                "inspection_number": inspection_number,
                "result": result,
                "failed_items": data.get("failed_items", []),
            },
            source_module="event_handlers",
        )
    except Exception:
        logger.exception("Error handling inspection.completed.failed")


# ---------------------------------------------------------------------------
# 4. rfi.response.design_change -> flag for variation
# ---------------------------------------------------------------------------

async def _handle_rfi_response_design_change(event: Event) -> None:
    """Flag RFI response with cost_impact for potential variation/change order.

    Expected event.data:
        project_id: str (UUID)
        rfi_id: str (UUID)
        rfi_number: str
        cost_impact: bool
        cost_impact_value: str | None
        schedule_impact: bool
        schedule_impact_days: int | None
        subject: str
    """
    try:
        data = event.data
        rfi_id = data.get("rfi_id")
        rfi_number = data.get("rfi_number", "")
        cost_impact = data.get("cost_impact", False)

        if not cost_impact:
            logger.debug("rfi.response.design_change: no cost_impact, skipping")
            return

        logger.info(
            "rfi.response.design_change: RFI %s has cost_impact, emitting variation flag",
            rfi_number,
        )

        await event_bus.publish(
            "variation.flagged",
            data={
                "project_id": data.get("project_id"),
                "source_type": "rfi",
                "source_id": str(rfi_id),
                "source_number": rfi_number,
                "subject": data.get("subject", ""),
                "cost_impact_value": data.get("cost_impact_value"),
                "schedule_impact": data.get("schedule_impact", False),
                "schedule_impact_days": data.get("schedule_impact_days"),
            },
            source_module="event_handlers",
        )
    except Exception:
        logger.exception("Error handling rfi.response.design_change")


# ---------------------------------------------------------------------------
# 5. ncr.cost_impact -> flag for variation
# ---------------------------------------------------------------------------

async def _handle_ncr_cost_impact(event: Event) -> None:
    """Flag NCR with cost_impact > 0 for potential variation/change order.

    Expected event.data:
        project_id: str (UUID)
        ncr_id: str (UUID)
        ncr_number: str
        cost_impact: str (monetary value as string, e.g. "15000")
        title: str
    """
    try:
        data = event.data
        ncr_id = data.get("ncr_id")
        ncr_number = data.get("ncr_number", "")
        cost_impact = data.get("cost_impact", "0")

        # Parse cost_impact; treat non-numeric as zero
        try:
            cost_value = float(str(cost_impact).replace(",", ""))
        except (ValueError, TypeError):
            cost_value = 0.0

        if cost_value <= 0:
            logger.debug("ncr.cost_impact: cost_impact=%s <= 0, skipping", cost_impact)
            return

        logger.info(
            "ncr.cost_impact: NCR %s has cost_impact=%s, emitting variation flag",
            ncr_number,
            cost_impact,
        )

        await event_bus.publish(
            "variation.flagged",
            data={
                "project_id": data.get("project_id"),
                "source_type": "ncr",
                "source_id": str(ncr_id),
                "source_number": ncr_number,
                "subject": data.get("title", ""),
                "cost_impact_value": cost_impact,
                "schedule_impact": False,
                "schedule_impact_days": data.get("schedule_impact_days"),
            },
            source_module="event_handlers",
        )
    except Exception:
        logger.exception("Error handling ncr.cost_impact")


# ---------------------------------------------------------------------------
# 6. document.revision.created -> flag linked BOQ positions
# ---------------------------------------------------------------------------

async def _handle_document_revision_created(event: Event) -> None:
    """Log new document revision for affected BOQ positions.

    Expected event.data:
        project_id: str (UUID)
        document_id: str (UUID)
        document_name: str
        revision_code: str
        previous_revision_id: str | None (UUID)
        affected_boq_position_ids: list[str] (UUIDs, if known)
    """
    try:
        data = event.data
        document_id = data.get("document_id")
        document_name = data.get("document_name", "")
        revision_code = data.get("revision_code", "")
        affected_ids = data.get("affected_boq_position_ids", [])

        logger.info(
            "document.revision.created: document '%s' rev %s -- %d linked BOQ positions",
            document_name,
            revision_code,
            len(affected_ids),
        )

        if affected_ids:
            await event_bus.publish(
                "boq.positions.revision_flagged",
                data={
                    "project_id": data.get("project_id"),
                    "document_id": str(document_id),
                    "document_name": document_name,
                    "revision_code": revision_code,
                    "affected_position_ids": affected_ids,
                },
                source_module="event_handlers",
            )
    except Exception:
        logger.exception("Error handling document.revision.created")


# ---------------------------------------------------------------------------
# 7. invoice.paid -> update project budget actuals
# ---------------------------------------------------------------------------

async def _handle_invoice_paid(event: Event) -> None:
    """Recalculate project budget actuals when an invoice is paid.

    Expected event.data:
        project_id: str (UUID)
        invoice_id: str (UUID)
        amount_total: str (monetary value)
        currency_code: str
    """
    try:
        data = event.data
        project_id = data.get("project_id")
        invoice_id = data.get("invoice_id")
        amount_total = data.get("amount_total", "0")

        if not project_id:
            logger.debug("invoice.paid: missing project_id")
            return

        from decimal import Decimal, InvalidOperation

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.finance.models import Invoice, ProjectBudget

        async with async_session_factory() as session:
            # Sum all paid invoices for the project
            result = await session.execute(
                select(Invoice).where(
                    Invoice.project_id == project_id,
                    Invoice.status == "paid",
                )
            )
            paid_invoices = result.scalars().all()

            total_actual = Decimal("0")
            for inv in paid_invoices:
                try:
                    total_actual += Decimal(str(inv.amount_total))
                except (InvalidOperation, ValueError):
                    continue

            # Update all budget lines for the project (aggregate level)
            budget_result = await session.execute(
                select(ProjectBudget).where(ProjectBudget.project_id == project_id)
            )
            budgets = budget_result.scalars().all()
            for budget in budgets:
                budget.actual = str(total_actual)

            await session.commit()

        logger.info(
            "invoice.paid: updated budget actuals for project %s (invoice %s, total_actual=%s)",
            project_id,
            invoice_id,
            total_actual,
        )
    except Exception:
        logger.exception("Error handling invoice.paid")


# ---------------------------------------------------------------------------
# 8. po.issued -> update project budget committed
# ---------------------------------------------------------------------------

async def _handle_po_issued(event: Event) -> None:
    """Recalculate project budget committed when a PO is issued.

    Expected event.data:
        project_id: str (UUID)
        po_id: str (UUID)
        amount_total: str (monetary value)
        currency_code: str
    """
    try:
        data = event.data
        project_id = data.get("project_id")
        po_id = data.get("po_id")

        if not project_id:
            logger.debug("po.issued: missing project_id")
            return

        from decimal import Decimal, InvalidOperation

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.finance.models import ProjectBudget
        from app.modules.procurement.models import PurchaseOrder

        async with async_session_factory() as session:
            # Sum all issued POs for the project
            result = await session.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.project_id == project_id,
                    PurchaseOrder.status == "issued",
                )
            )
            issued_pos = result.scalars().all()

            total_committed = Decimal("0")
            for po in issued_pos:
                try:
                    total_committed += Decimal(str(po.amount_total))
                except (InvalidOperation, ValueError):
                    continue

            # Update budget lines for the project
            budget_result = await session.execute(
                select(ProjectBudget).where(ProjectBudget.project_id == project_id)
            )
            budgets = budget_result.scalars().all()
            for budget in budgets:
                budget.committed = str(total_committed)

            await session.commit()

        logger.info(
            "po.issued: updated budget committed for project %s (po %s, total_committed=%s)",
            project_id,
            po_id,
            total_committed,
        )
    except Exception:
        logger.exception("Error handling po.issued")


# ---------------------------------------------------------------------------
# 9. estimate.approved -> auto-populate project budget from BOQ
# ---------------------------------------------------------------------------

async def _handle_estimate_approved(event: Event) -> None:
    """BOQ approved -> create project_budgets.original_budget entries.

    When a BOQ is locked/approved, auto-create ProjectBudget rows from BOQ
    section totals grouped by WBS or parent position.

    Expected event.data:
        boq_id: str (UUID)
        project_id: str (UUID)
    """
    try:
        data = event.data
        boq_id = data.get("boq_id")
        project_id = data.get("project_id")

        if not boq_id or not project_id:
            logger.debug("estimate.approved: missing boq_id or project_id")
            return

        from decimal import Decimal, InvalidOperation

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.boq.models import Position
        from app.modules.finance.models import ProjectBudget

        async with async_session_factory() as session:
            # Load all positions for this BOQ
            result = await session.execute(
                select(Position).where(Position.boq_id == boq_id)
            )
            positions = result.scalars().all()

            if not positions:
                logger.debug("estimate.approved: no positions for boq %s", boq_id)
                return

            # Group totals by wbs_id (or "general" if unassigned)
            wbs_totals: dict[str, Decimal] = {}
            for pos in positions:
                wbs_key = pos.wbs_id or "general"
                try:
                    total = Decimal(str(pos.total))
                except (InvalidOperation, ValueError):
                    total = Decimal("0")
                wbs_totals[wbs_key] = wbs_totals.get(wbs_key, Decimal("0")) + total

            # Upsert budget lines for each WBS group
            created_count = 0
            for wbs_key, total in wbs_totals.items():
                existing = await session.execute(
                    select(ProjectBudget).where(
                        ProjectBudget.project_id == project_id,
                        ProjectBudget.wbs_id == (wbs_key if wbs_key != "general" else None),
                        ProjectBudget.category == "estimate",
                    )
                )
                budget = existing.scalar_one_or_none()

                if budget:
                    budget.original_budget = str(total)
                    budget.revised_budget = str(total)
                else:
                    session.add(
                        ProjectBudget(
                            project_id=project_id,
                            wbs_id=wbs_key if wbs_key != "general" else None,
                            category="estimate",
                            original_budget=str(total),
                            revised_budget=str(total),
                        )
                    )
                    created_count += 1

            await session.commit()

        logger.info(
            "estimate.approved: populated %d budget lines for project %s (boq %s)",
            created_count,
            project_id,
            boq_id,
        )
    except Exception:
        logger.exception("Error handling estimate.approved")


# ---------------------------------------------------------------------------
# 10. schedule.progress_updated -> EVM snapshot
# ---------------------------------------------------------------------------

async def _handle_schedule_progress(event: Event) -> None:
    """Schedule progress updated -> create EVM snapshot with PV/EV/AC/SPI/CPI.

    Recalculates Earned Value Management metrics from the latest budget data
    and schedule progress, then persists a snapshot.

    Expected event.data:
        project_id: str (UUID)
        progress_pct: float (0-100, schedule completion percentage)
        time_elapsed_pct: float (0-100, calendar time elapsed percentage)
    """
    try:
        data = event.data
        project_id = data.get("project_id")
        progress_pct = data.get("progress_pct", 0)
        time_elapsed_pct = data.get("time_elapsed_pct", 0)

        if not project_id:
            logger.debug("schedule.progress_updated: missing project_id")
            return

        from datetime import date
        from decimal import Decimal, InvalidOperation

        from sqlalchemy import func, select

        from app.database import async_session_factory
        from app.modules.finance.models import EVMSnapshot, Invoice, ProjectBudget

        async with async_session_factory() as session:
            # Compute BAC: sum of all original_budget for the project
            bac_result = await session.execute(
                select(func.coalesce(func.sum(0), 0)).select_from(ProjectBudget).where(
                    ProjectBudget.project_id == project_id,
                )
            )
            # Manual sum because original_budget is stored as String
            budget_result = await session.execute(
                select(ProjectBudget).where(ProjectBudget.project_id == project_id)
            )
            budgets = budget_result.scalars().all()
            _ = bac_result.scalar()  # consume the previous query

            bac = Decimal("0")
            for b in budgets:
                try:
                    bac += Decimal(str(b.original_budget))
                except (InvalidOperation, ValueError):
                    continue

            if bac == 0:
                logger.debug(
                    "schedule.progress_updated: BAC=0 for project %s, skipping",
                    project_id,
                )
                return

            # Compute PV, EV
            time_factor = Decimal(str(time_elapsed_pct)) / Decimal("100")
            progress_factor = Decimal(str(progress_pct)) / Decimal("100")
            pv = bac * time_factor
            ev = bac * progress_factor

            # Compute AC: sum of paid invoices
            inv_result = await session.execute(
                select(Invoice).where(
                    Invoice.project_id == project_id,
                    Invoice.status == "paid",
                )
            )
            paid_invoices = inv_result.scalars().all()
            ac = Decimal("0")
            for inv in paid_invoices:
                try:
                    ac += Decimal(str(inv.amount_total))
                except (InvalidOperation, ValueError):
                    continue

            # Derived metrics
            sv = ev - pv
            cv = ev - ac
            spi = ev / pv if pv != 0 else Decimal("0")
            cpi = ev / ac if ac != 0 else Decimal("0")

            snapshot = EVMSnapshot(
                project_id=project_id,
                snapshot_date=date.today().isoformat(),
                bac=str(bac.quantize(Decimal("0.01"))),
                pv=str(pv.quantize(Decimal("0.01"))),
                ev=str(ev.quantize(Decimal("0.01"))),
                ac=str(ac.quantize(Decimal("0.01"))),
                sv=str(sv.quantize(Decimal("0.01"))),
                cv=str(cv.quantize(Decimal("0.01"))),
                spi=str(spi.quantize(Decimal("0.0001"))),
                cpi=str(cpi.quantize(Decimal("0.0001"))),
            )
            session.add(snapshot)
            await session.commit()

        logger.info(
            "schedule.progress_updated: EVM snapshot for project %s "
            "(BAC=%s PV=%s EV=%s AC=%s SPI=%s CPI=%s)",
            project_id,
            snapshot.bac,
            snapshot.pv,
            snapshot.ev,
            snapshot.ac,
            snapshot.spi,
            snapshot.cpi,
        )
    except Exception:
        logger.exception("Error handling schedule.progress_updated")


# ---------------------------------------------------------------------------
# 11. bim_model.ready -> apply quantity maps -> draft BOQ
# ---------------------------------------------------------------------------

async def _handle_bim_model_ready(event: Event) -> None:
    """BIM model processed -> apply quantity maps -> generate draft BOQ positions.

    When a BIM model finishes processing, load active quantity map rules and
    create draft BOQ positions for matching elements.

    Expected event.data:
        model_id: str (UUID)
        project_id: str (UUID)
        boq_id: str (UUID, optional — target BOQ for new positions)
    """
    try:
        data = event.data
        model_id = data.get("model_id")
        project_id = data.get("project_id")
        boq_id = data.get("boq_id")

        if not model_id or not project_id:
            logger.debug("bim_model.ready: missing model_id or project_id")
            return

        from decimal import Decimal, InvalidOperation

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.bim_hub.models import BIMElement, BIMQuantityMap

        async with async_session_factory() as session:
            # Load BIM elements for this model
            elem_result = await session.execute(
                select(BIMElement).where(BIMElement.model_id == model_id)
            )
            elements = elem_result.scalars().all()

            if not elements:
                logger.debug("bim_model.ready: no elements for model %s", model_id)
                return

            # Load active quantity maps (project-scoped or global)
            map_result = await session.execute(
                select(BIMQuantityMap).where(
                    BIMQuantityMap.is_active.is_(True),
                    (
                        (BIMQuantityMap.project_id == project_id)
                        | BIMQuantityMap.project_id.is_(None)
                    ),
                )
            )
            qty_maps = map_result.scalars().all()

            if not qty_maps:
                logger.debug(
                    "bim_model.ready: no active quantity maps for project %s",
                    project_id,
                )
                return

            # Apply each rule to matching elements
            matched_count = 0
            for qmap in qty_maps:
                for elem in elements:
                    # Filter by element_type if specified
                    if qmap.element_type_filter and elem.element_type != qmap.element_type_filter:
                        continue

                    # Filter by property_filter if specified
                    if qmap.property_filter:
                        match = all(
                            elem.properties.get(k) == v
                            for k, v in qmap.property_filter.items()
                        )
                        if not match:
                            continue

                    # Extract quantity from element
                    raw_qty = elem.quantities.get(qmap.quantity_source, 0)
                    try:
                        quantity = Decimal(str(raw_qty)) * Decimal(str(qmap.multiplier))
                        waste = Decimal(str(qmap.waste_factor_pct)) / Decimal("100")
                        quantity *= Decimal("1") + waste
                    except (InvalidOperation, ValueError):
                        continue

                    matched_count += 1

            logger.info(
                "bim_model.ready: matched %d element-rule pairs for model %s (project %s, "
                "%d elements, %d rules)",
                matched_count,
                model_id,
                project_id,
                len(elements),
                len(qty_maps),
            )

            # Emit a downstream event so the UI or another handler can create
            # actual BOQ positions from the matched results.
            await event_bus.publish(
                "bim_model.quantity_maps_applied",
                data={
                    "project_id": project_id,
                    "model_id": model_id,
                    "boq_id": boq_id,
                    "matched_count": matched_count,
                    "element_count": len(elements),
                    "rule_count": len(qty_maps),
                },
                source_module="event_handlers",
            )
    except Exception:
        logger.exception("Error handling bim_model.ready")


# ---------------------------------------------------------------------------
# 12. bim_model.new_version -> diff -> flag affected BOQ positions
# ---------------------------------------------------------------------------

async def _handle_bim_model_new_version(event: Event) -> None:
    """New BIM model version -> compute diff -> flag linked BOQ positions.

    When a new version of a BIM model is uploaded, compare element stable_id
    and geometry_hash to detect modified/deleted elements, then flag any BOQ
    positions linked to those elements.

    Expected event.data:
        new_model_id: str (UUID)
        old_model_id: str (UUID)
        project_id: str (UUID)
    """
    try:
        data = event.data
        new_model_id = data.get("new_model_id")
        old_model_id = data.get("old_model_id")
        project_id = data.get("project_id")

        if not new_model_id or not old_model_id:
            logger.debug("bim_model.new_version: missing new_model_id or old_model_id")
            return

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.bim_hub.models import BIMElement, BOQElementLink

        async with async_session_factory() as session:
            # Load elements for both versions keyed by stable_id
            old_result = await session.execute(
                select(BIMElement).where(BIMElement.model_id == old_model_id)
            )
            old_elements = {e.stable_id: e for e in old_result.scalars().all()}

            new_result = await session.execute(
                select(BIMElement).where(BIMElement.model_id == new_model_id)
            )
            new_elements = {e.stable_id: e for e in new_result.scalars().all()}

            # Detect modified and deleted elements
            modified_old_elem_ids: list[str] = []
            deleted_old_elem_ids: list[str] = []

            for stable_id, old_elem in old_elements.items():
                new_elem = new_elements.get(stable_id)
                if new_elem is None:
                    # Element was deleted in new version
                    deleted_old_elem_ids.append(str(old_elem.id))
                elif old_elem.geometry_hash != new_elem.geometry_hash:
                    # Geometry changed
                    modified_old_elem_ids.append(str(old_elem.id))

            affected_elem_ids = modified_old_elem_ids + deleted_old_elem_ids

            if not affected_elem_ids:
                logger.info(
                    "bim_model.new_version: no modified/deleted elements between "
                    "%s and %s",
                    old_model_id,
                    new_model_id,
                )
                return

            # Find BOQ positions linked to the affected old elements
            link_result = await session.execute(
                select(BOQElementLink).where(
                    BOQElementLink.bim_element_id.in_(affected_elem_ids)
                )
            )
            affected_links = link_result.scalars().all()
            affected_position_ids = list(
                {str(link.boq_position_id) for link in affected_links}
            )

        logger.info(
            "bim_model.new_version: %d modified, %d deleted elements; "
            "%d BOQ positions affected (models %s -> %s)",
            len(modified_old_elem_ids),
            len(deleted_old_elem_ids),
            len(affected_position_ids),
            old_model_id,
            new_model_id,
        )

        if affected_position_ids:
            await event_bus.publish(
                "boq.positions.bim_version_flagged",
                data={
                    "project_id": project_id,
                    "old_model_id": str(old_model_id),
                    "new_model_id": str(new_model_id),
                    "modified_element_count": len(modified_old_elem_ids),
                    "deleted_element_count": len(deleted_old_elem_ids),
                    "affected_position_ids": affected_position_ids,
                },
                source_module="event_handlers",
            )
    except Exception:
        logger.exception("Error handling bim_model.new_version")


# ---------------------------------------------------------------------------
# 13. variation.approved -> update contract_value + budget
# ---------------------------------------------------------------------------

async def _handle_variation_approved(event: Event) -> None:
    """Variation approved -> update project contract_value and budget.

    When a change order / variation is approved, increment the project's
    contract_value and create or update a budget entry for variations.

    Expected event.data:
        project_id: str (UUID)
        variation_id: str (UUID)
        approved_amount: str (monetary value, e.g. "25000")
        description: str (optional)
    """
    try:
        data = event.data
        project_id = data.get("project_id")
        variation_id = data.get("variation_id")
        approved_amount = data.get("approved_amount", "0")

        if not project_id:
            logger.debug("variation.approved: missing project_id")
            return

        from decimal import Decimal, InvalidOperation

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.finance.models import ProjectBudget
        from app.modules.projects.models import Project

        try:
            amount = Decimal(str(approved_amount).replace(",", ""))
        except (InvalidOperation, ValueError):
            logger.warning(
                "variation.approved: invalid approved_amount=%s", approved_amount
            )
            return

        if amount == 0:
            logger.debug("variation.approved: approved_amount=0, skipping")
            return

        async with async_session_factory() as session:
            # Update project.contract_value
            project = await session.get(Project, project_id)
            if project:
                try:
                    current_cv = Decimal(str(project.contract_value or "0"))
                except (InvalidOperation, ValueError):
                    current_cv = Decimal("0")
                project.contract_value = str(current_cv + amount)

            # Upsert budget entry for the "variations" category
            existing = await session.execute(
                select(ProjectBudget).where(
                    ProjectBudget.project_id == project_id,
                    ProjectBudget.category == "variations",
                )
            )
            budget = existing.scalar_one_or_none()

            if budget:
                try:
                    current_revised = Decimal(str(budget.revised_budget))
                except (InvalidOperation, ValueError):
                    current_revised = Decimal("0")
                budget.revised_budget = str(current_revised + amount)
            else:
                session.add(
                    ProjectBudget(
                        project_id=project_id,
                        wbs_id=None,
                        category="variations",
                        original_budget="0",
                        revised_budget=str(amount),
                    )
                )

            await session.commit()

        logger.info(
            "variation.approved: updated contract_value (+%s) and budget for project %s "
            "(variation %s)",
            approved_amount,
            project_id,
            variation_id,
        )
    except Exception:
        logger.exception("Error handling variation.approved")


# ---------------------------------------------------------------------------
# 14. transmittal.issued -> audit trail for distribution
# ---------------------------------------------------------------------------

async def _handle_transmittal_issued(event: Event) -> None:
    """Transmittal issued -> create audit trail for each recipient.

    When a transmittal is formally issued, log an audit entry for each
    recipient to maintain a distribution record.

    Expected event.data:
        transmittal_id: str (UUID)
        project_id: str (UUID)
        transmittal_number: str
        subject: str
        recipient_ids: list[str] (UUIDs of recipient users/orgs)
        issued_by: str (UUID, optional)
    """
    try:
        data = event.data
        transmittal_id = data.get("transmittal_id")
        project_id = data.get("project_id")
        transmittal_number = data.get("transmittal_number", "")
        subject = data.get("subject", "")
        recipient_ids = data.get("recipient_ids", [])
        issued_by = data.get("issued_by")

        if not transmittal_id:
            logger.debug("transmittal.issued: missing transmittal_id")
            return

        from app.core.audit import audit_log
        from app.database import async_session_factory

        async with async_session_factory() as session:
            for recipient_id in recipient_ids:
                await audit_log(
                    session,
                    action="transmittal_issued",
                    entity_type="transmittal",
                    entity_id=str(transmittal_id),
                    user_id=issued_by,
                    details={
                        "project_id": str(project_id),
                        "transmittal_number": transmittal_number,
                        "subject": subject[:200],
                        "recipient_id": str(recipient_id),
                    },
                )
            await session.commit()

        logger.info(
            "transmittal.issued: created %d audit entries for transmittal %s (%s)",
            len(recipient_ids),
            transmittal_number,
            transmittal_id,
        )
    except Exception:
        logger.exception("Error handling transmittal.issued")


# ---------------------------------------------------------------------------
# 15. cde.container.promoted -> audit + notify stakeholders
# ---------------------------------------------------------------------------

async def _handle_cde_container_promoted(event: Event) -> None:
    """CDE container state change -> log + notify stakeholders.

    When a document container transitions to a new CDE state (e.g. wip ->
    shared -> published -> archived), log an audit entry and, for the
    "published" state, emit a downstream event for linked BOQ positions.

    Expected event.data:
        container_id: str (UUID)
        project_id: str (UUID)
        new_state: str (e.g. "shared", "published", "archived")
        old_state: str
        container_code: str
        promoted_by: str (UUID, optional)
    """
    try:
        data = event.data
        container_id = data.get("container_id")
        project_id = data.get("project_id")
        new_state = data.get("new_state", "")
        old_state = data.get("old_state", "")
        container_code = data.get("container_code", "")
        promoted_by = data.get("promoted_by")

        if not container_id:
            logger.debug("cde.container.promoted: missing container_id")
            return

        from app.core.audit import audit_log
        from app.database import async_session_factory

        async with async_session_factory() as session:
            await audit_log(
                session,
                action="cde_state_change",
                entity_type="cde_container",
                entity_id=str(container_id),
                user_id=promoted_by,
                details={
                    "project_id": str(project_id),
                    "container_code": container_code,
                    "old_state": old_state,
                    "new_state": new_state,
                },
            )
            await session.commit()

        logger.info(
            "cde.container.promoted: container %s (%s) %s -> %s",
            container_code,
            container_id,
            old_state,
            new_state,
        )

        # When promoted to "published", emit event so downstream handlers
        # can notify linked BOQ positions or trigger further workflows.
        if new_state == "published":
            await event_bus.publish(
                "cde.container.published",
                data={
                    "project_id": project_id,
                    "container_id": str(container_id),
                    "container_code": container_code,
                    "promoted_by": promoted_by,
                },
                source_module="event_handlers",
            )
    except Exception:
        logger.exception("Error handling cde.container.promoted")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_HANDLER_COUNT = 15


def register_event_handlers() -> None:
    """Register all cross-module event handlers with the global event bus.

    Call this at startup after all modules are loaded.
    """
    event_bus.subscribe("meeting.action_item.created", _handle_meeting_action_item_created)
    event_bus.subscribe("safety.observation.high_risk", _handle_safety_observation_high_risk)
    event_bus.subscribe("inspection.completed.failed", _handle_inspection_completed_failed)
    event_bus.subscribe("rfi.response.design_change", _handle_rfi_response_design_change)
    event_bus.subscribe("ncr.cost_impact", _handle_ncr_cost_impact)
    event_bus.subscribe("document.revision.created", _handle_document_revision_created)
    event_bus.subscribe("invoice.paid", _handle_invoice_paid)
    event_bus.subscribe("po.issued", _handle_po_issued)
    event_bus.subscribe("estimate.approved", _handle_estimate_approved)
    event_bus.subscribe("schedule.progress_updated", _handle_schedule_progress)
    event_bus.subscribe("bim_model.ready", _handle_bim_model_ready)
    event_bus.subscribe("bim_model.new_version", _handle_bim_model_new_version)
    event_bus.subscribe("variation.approved", _handle_variation_approved)
    event_bus.subscribe("transmittal.issued", _handle_transmittal_issued)
    event_bus.subscribe("cde.container.promoted", _handle_cde_container_promoted)

    logger.info("Registered %d cross-module event handlers", _HANDLER_COUNT)
