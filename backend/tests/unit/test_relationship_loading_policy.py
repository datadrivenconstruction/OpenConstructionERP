# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every relationship() must declare an explicit lazy= strategy.

A ``relationship()`` with no ``lazy=`` gets SQLAlchemy's default ``select``.
Touched on an instance that came back from the identity map inside an async
session, that fires a lazy load from async context and raises
``MissingGreenlet``. The call chain reads the same whether the strategy is safe
or not, so this cannot be caught by reviewing call sites - only by the model.

This is a ratchet, not a clean gate: the tree still carries the entries in
``KNOWN_DEFAULT_LAZY`` below. The list may only shrink. Adding a new
default-lazy relationship fails the test; converting one and forgetting to
delete its line also fails, so the backlog cannot silently stall.

Which strategy to pick:

===============================================  ===============
Relationship                                     Strategy
===============================================  ===============
Collection the parent is defined by              ``selectin``
Collection that may be large or is rarely read   ``raise_on_sql``
Scalar ``child.parent`` back-reference           ``raise_on_sql``
Self-reference                                   ``selectin`` down, ``raise_on_sql`` up
===============================================  ===============

``raise_on_sql`` rather than ``raise``: plain ``raise`` throws even when the
attribute is already populated, for instance when ``back_populates`` filled it
while loading the parent's collection, so it breaks code that works today.
``raise_on_sql`` permits that free read and only objects when SQL would be
emitted. ``joined`` is not used, it multiplies parent rows across a collection.
``noload`` is not a safe middle either: it answers empty instead of raising,
which is a silent wrong result rather than an error.

Two results worth not rediscovering. Neither ``raise`` nor ``raise_on_sql``
breaks ``delete-orphan`` cascade, because ``session.delete()`` loads the
collection through a path they do not intercept. And a green test run does not
verify a strategy change: the boq PG lane passed all 47 tests with the
strictest ``raise`` on ``Position.boq``, because it never walks that
relationship. Before converting a module, grep the readers of the attribute and
confirm each already orders it eager; if you want a real gate, write a test that
touches the relationship and watch it fail under ``raise`` first.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parents[2] / "app" / "modules"

# Relationships that still ride the default. Delete a line when you give that
# relationship an explicit lazy=. Never add one.
KNOWN_DEFAULT_LAZY: frozenset[str] = frozenset(
    {
        "ai_estimator.AiEstimatorGroup.run",
        "allowances.AllowanceDrawdown.allowance",
        "assemblies.Component.assembly",
        "bcf.BCFComment.topic",
        "bcf.BCFViewpoint.topic",
        "bid_management.BidInvitation.package",
        "bid_management.BidPackageLineItem.package",
        "bid_management.Bidder.package",
        "bim_hub.BIMElement.model",
        "bim_hub.BIMFederationModel.federation",
        "bim_hub.BOQElementLink.bim_element",
        "bim_requirements.BIMRequirement.requirement_set",
        "changeorders.ChangeOrderApproval.change_order",
        "changeorders.ChangeOrderItem.change_order",
        "clash.ClashResult.run",
        "clash.ClashRun.results",
        "collaboration.CommentMention.comment",
        "collaboration.Viewpoint.comment",
        "cvr.CvrLine.report",
        "defects_liability.DlpDefect.warranty",
        "documents.DocumentBIMLink.document",
        "eac.EacAliasSynonym.alias",
        "eac.EacRule.ruleset",
        "eac.EacRuleVersion.rule",
        "eac.EacRun.ruleset",
        "eac.EacRunResultItem.run",
        "enterprise_workflows.ApprovalRequest.workflow",
        "erp_chat.ChatMessage.session",
        "erp_chat.ChatTurnFeedback.message",
        "field_time.FieldTimesheetLine.timesheet",
        "file_approvals.FileApprovalStep.workflow",
        "file_approvals.FileApprovalWorkflow.steps",
        "file_distribution.FileDistributionMember.distribution_list",
        "file_tags.FileTagAssignment.tag",
        "file_transmittals.FileTransmittal.items",
        "file_transmittals.FileTransmittal.recipients",
        "file_transmittals.FileTransmittalItem.transmittal",
        "file_transmittals.FileTransmittalRecipient.transmittal",
        "finance.InvoiceLineItem.invoice",
        "finance.Payment.invoice",
        "interface_management.InterfaceAction.interface",
        "labor_rates.OnCostComponent.template",
        "match_elements.MatchGroup.session",
        "meetings.MeetingAttendance.meeting",
        "methodology.AnalyticDimensionValue.dimension",
        "moc.MoCImpact.moc_entry",
        "norm_expansion.NormMaterial.norm",
        "pointcloud.ScanRegistration.scan",
        "price_index.CostIndexPoint.series",
        "procurement.GoodsReceipt.purchase_order",
        "procurement.GoodsReceiptItem.goods_receipt",
        "procurement.MaterialRequisitionItem.requisition",
        "procurement.PurchaseOrderItem.purchase_order",
        "projects.ProjectMilestone.project",
        "projects.ProjectWBS.project",
        "schedule.Activity.schedule",
        "schedule.WorkOrder.activity",
        "service.DebriefReport.work_order",
        "service.ServiceAsset.contract",
        "service.ServiceTicket.contract",
        "service.ServiceWorkOrder.ticket",
        "service.ServiceWorkOrderItem.work_order",
        "site_inventory.StockMovement.item",
        "supplier_catalogs.CatalogEntry.price_list",
        "supplier_catalogs.GRLine.gr",
        "supplier_catalogs.POLine.po",
        "supplier_catalogs.PRLine.pr",
        "supplier_catalogs.PriceList.vendor",
        "supplier_catalogs.SupplierGoodsReceipt.po",
        "supplier_catalogs.VendorInvoiceLine.invoice",
        "temporary_works.TemporaryWorksPermit.item",
        "tendering.TenderBid.package",
        "transmittals.TransmittalItem.transmittal",
        "transmittals.TransmittalRecipient.transmittal",
        "users.APIKey.user",
        "variations.DayworkSheetLine.sheet",
        "variations.VariationCostImpact.variation_order",
        "variations.VariationScheduleImpact.variation_order",
    }
)


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def collect_default_lazy() -> set[str]:
    """Return ``module.Class.attr`` for every relationship() with no lazy=."""
    found: set[str] = set()
    for path in sorted(MODULES_DIR.rglob("models.py")):
        if "__pycache__" in path.parts:
            continue
        module = path.relative_to(MODULES_DIR).parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign):
                    target, value = stmt.target, stmt.value
                elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target, value = stmt.targets[0], stmt.value
                else:
                    continue
                if not isinstance(value, ast.Call) or _call_name(value) != "relationship":
                    continue
                if any(kw.arg == "lazy" for kw in value.keywords):
                    continue
                if isinstance(target, ast.Name):
                    found.add(f"{module}.{cls.name}.{target.id}")
    return found


def test_no_new_default_lazy_relationship() -> None:
    """A relationship without an explicit lazy= is a latent MissingGreenlet."""
    added = sorted(collect_default_lazy() - KNOWN_DEFAULT_LAZY)
    assert not added, (
        "These relationships have no explicit lazy= strategy:\n  "
        + "\n  ".join(added)
        + "\n\nPick one per the table in this module's docstring: selectin for "
        "a collection the parent is defined by, raise_on_sql for a child.parent "
        "back-reference. Do not add them to KNOWN_DEFAULT_LAZY."
    )


def test_known_default_lazy_list_has_no_stale_entries() -> None:
    """Converted relationships must be struck off, so the backlog keeps shrinking."""
    stale = sorted(KNOWN_DEFAULT_LAZY - collect_default_lazy())
    assert not stale, (
        "These now declare an explicit lazy= and must be removed from KNOWN_DEFAULT_LAZY:\n  " + "\n  ".join(stale)
    )


def test_the_scanner_actually_finds_relationships() -> None:
    """Guard the guard: an AST change that silently matches nothing must fail.

    Without this, a scanner that returns an empty set would make both tests
    above pass for the wrong reason.
    """
    assert len(collect_default_lazy()) > 50
