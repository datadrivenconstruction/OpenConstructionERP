# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Counter registry: module key -> object counters.

Models are referenced by dotted path and imported lazily, so a module that is
absent from a build (or whose table is missing) never breaks the others.
``via_model`` joins through a parent for objects that carry no ``project_id``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CounterSpec:
    """One countable object: ``model`` is ``"package.module:Class"``."""

    object: str
    model: str
    fk: str = "project_id"
    via_model: str | None = None  # parent model carrying project_id
    via_fk: str | None = None  # column on ``model`` pointing at the parent id


def _m(module: str, cls: str) -> str:
    return f"app.modules.{module}.models:{cls}"


REGISTRY: dict[str, list[CounterSpec]] = {
    "boq": [
        CounterSpec("boq", _m("boq", "BOQ")),
        CounterSpec("position", _m("boq", "Position"), via_model=_m("boq", "BOQ"), via_fk="boq_id"),
    ],
    "takeoff": [
        CounterSpec("document", _m("takeoff", "TakeoffDocument")),
        CounterSpec("measurement", _m("takeoff", "TakeoffMeasurement")),
    ],
    "bim_hub": [
        CounterSpec("model", _m("bim_hub", "BIMModel")),
        CounterSpec("element_group", _m("bim_hub", "BIMElementGroup")),
    ],
    "costs": [CounterSpec("cost_item_usage", _m("costs", "CostItemUsage"))],
    "assemblies": [CounterSpec("assembly", _m("assemblies", "Assembly"))],
    "schedule": [CounterSpec("schedule", _m("schedule", "Schedule"))],
    "changeorders": [CounterSpec("change_order", _m("changeorders", "ChangeOrder"))],
    "rfi": [CounterSpec("rfi", _m("rfi", "RFI"))],
    "submittals": [CounterSpec("submittal", _m("submittals", "Submittal"))],
    "documents": [
        CounterSpec("document", _m("documents", "Document")),
        CounterSpec("photo", _m("documents", "ProjectPhoto")),
        CounterSpec("sheet", _m("documents", "Sheet")),
    ],
    "procurement": [
        CounterSpec("purchase_order", _m("procurement", "PurchaseOrder")),
        CounterSpec("requisition", _m("procurement", "MaterialRequisition")),
    ],
    "tendering": [CounterSpec("tender_package", _m("tendering", "TenderPackage"))],
    "contracts": [CounterSpec("contract", _m("contracts", "Contract"))],
    "subcontractors": [CounterSpec("agreement", _m("subcontractors", "SubcontractAgreement"))],
    "finance": [
        CounterSpec("invoice", _m("finance", "Invoice")),
        CounterSpec("payment", _m("finance", "Payment"), via_model=_m("finance", "Invoice"), via_fk="invoice_id"),
    ],
    "inspections": [CounterSpec("inspection", _m("inspections", "QualityInspection"))],
    "safety": [
        CounterSpec("incident", _m("safety", "SafetyIncident")),
        CounterSpec("observation", _m("safety", "SafetyObservation")),
    ],
    "risk": [CounterSpec("risk", _m("risk", "RiskItem"))],
    "carbon": [CounterSpec("inventory", _m("carbon", "CarbonInventory"))],
    "resources": [
        CounterSpec("assignment", _m("resources", "Assignment")),
        CounterSpec("resource_request", _m("resources", "ResourceRequest")),
    ],
    "daily_diary": [CounterSpec("diary", _m("daily_diary", "DailyDiary"))],
    "field_diary": [CounterSpec("entry", _m("field_diary", "DiaryEntry"))],
    "punchlist": [CounterSpec("punch_item", _m("punchlist", "PunchItem"))],
    "meetings": [
        CounterSpec("meeting", _m("meetings", "Meeting")),
        CounterSpec("action_item", _m("meetings", "MeetingActionItem")),
    ],
}


def register_counters(module: str, specs: list[CounterSpec]) -> None:
    """Let a module contribute (or extend) its counters."""
    REGISTRY.setdefault(module, []).extend(specs)
