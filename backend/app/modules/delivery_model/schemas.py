# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request and response schemas of the delivery model API.

Weights, shares and scores travel as strings or ints, never floats. Vocabulary
fields are closed literals where the platform owns the vocabulary; catalogue
codes (forms, categories, parties, criteria) are open strings checked against
the pinned catalogue by the service, because a tenant catalogue may add codes.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PackageKind = Literal[
    "design",
    "construction",
    "design_and_construction",
    "supply",
    "supply_and_install",
    "management_services",
    "operation",
    "project_agreement",
]
PriceBasis = Literal["remeasure", "lump_sum", "gmp", "target_cost", "cost_reimbursable", "availability_payment"]
PackageLinkKind = Literal["bid_package", "tender_package", "rfq", "subcontract_agreement", "contract"]
OfiLinkKind = Literal["rfq", "purchase_order", "requisition"]
OfiRoute = Literal["rfq", "purchase_order", "requisition", "framework", "existing_stock", "none_yet"]
OfiKind = Literal["equipment", "material", "design", "service", "utility"]
Basis = Literal["contract", "insurance", "shared_pain_gain", "statute", "ground_baseline"]
Disposition = Literal["keep", "re_scope", "cancel"]
_CODE = r"^[a-z0-9][a-z0-9_]*$"
_PKG_CODE = r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send decimals as strings")
    return value


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


class OwnerCapability(_In):
    owner_has_design_team: bool | None = None
    owner_has_cm_capacity: bool | None = None
    public_client: bool | None = None
    funding_source: str = Field(default="", max_length=120)


class ModelSet(_In):
    catalogue_source: Literal["shipped", "tenant"] = "shipped"
    catalogue_id: str | None = Field(default=None, max_length=64)
    catalogue_version: int | None = None


def _refuse_nulls(model: BaseModel, nullable: tuple[str, ...] = ()) -> None:
    """An explicit null on a field that cannot be cleared is a 422, never a silent no-op or a 500."""
    bad = sorted(k for k in model.model_fields_set if getattr(model, k) is None and k not in nullable)
    if bad:
        raise ValueError(f"cannot be null: {', '.join(bad)}")


class ModelPatch(_In):
    underground_risk_sharing: bool | None = None
    owner_capability: OwnerCapability | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> ModelPatch:
        _refuse_nulls(self)
        return self


class CatalogueChange(_In):
    catalogue_source: Literal["shipped", "tenant"]
    catalogue_id: str = Field(max_length=64)
    catalogue_version: int | None = None
    form_mapping: dict[str, str] = Field(default_factory=dict)
    category_mapping: dict[str, str] = Field(default_factory=dict)


class OptionIn(_In):
    form_code: str = Field(pattern=_CODE, max_length=64)
    overrides: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=5000)


class OptionPatch(_In):
    overrides: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    sort_order: int | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> OptionPatch:
        _refuse_nulls(self)
        return self


class WeightsPatch(_In):
    weights: dict[str, str]

    @field_validator("weights", mode="before")
    @classmethod
    def _decimal_strings(cls, v: Any) -> Any:
        return {k: _no_float(x) for k, x in (v or {}).items()}


class ScoreIn(_In):
    option_id: uuid.UUID
    criterion_code: str = Field(max_length=64)
    score: int = Field(ge=1, le=5)
    rationale: str = Field(default="", max_length=2000)


class ScoresPut(_In):
    scores: list[ScoreIn]


class ProposeIn(_In):
    option_id: uuid.UUID
    rationale: str = Field(min_length=1, max_length=10000)
    owner_capability: OwnerCapability | None = None
    dispositions: dict[str, Disposition] = Field(default_factory=dict)


class AllocationPut(_In):
    party: str | None = Field(default=None, max_length=40)
    basis: Basis = "contract"
    shares: dict[str, str] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=5000)
    not_applicable: bool = False

    @field_validator("shares", mode="before")
    @classmethod
    def _decimal_strings(cls, v: Any) -> Any:
        return {k: _no_float(x) for k, x in (v or {}).items()}


class ConfirmIn(_In):
    categories: list[str] | None = None


class SeedRisksIn(_In):
    categories: list[str] | None = None
    preview: bool = True


class PackageIn(_In):
    code: str = Field(pattern=_PKG_CODE, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    kind: PackageKind
    designs: bool = False
    builds: bool = False
    supplies: bool = False
    manages: bool = False
    party: str = Field(default="contractor", max_length=40)
    contracting_party: Literal["owner", "manager"] = "owner"
    price_basis: PriceBasis | None = None
    standard_form: str = Field(default="", max_length=120)
    parent_id: uuid.UUID | None = None
    scope: str = Field(default="", max_length=10000)
    wbs_ref: str = Field(default="", max_length=120)
    boq_ref: str = Field(default="", max_length=120)
    need_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class PackagePatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    kind: PackageKind | None = None
    designs: bool | None = None
    builds: bool | None = None
    supplies: bool | None = None
    manages: bool | None = None
    party: str | None = Field(default=None, max_length=40)
    contracting_party: Literal["owner", "manager"] | None = None
    price_basis: PriceBasis | None = None
    standard_form: str | None = Field(default=None, max_length=120)
    parent_id: uuid.UUID | None = None
    scope: str | None = Field(default=None, max_length=10000)
    wbs_ref: str | None = Field(default=None, max_length=120)
    boq_ref: str | None = Field(default=None, max_length=120)
    need_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sort_order: int | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> PackagePatch:
        # parent_id, price_basis and need_date can be cleared; everything else is a NOT NULL column.
        _refuse_nulls(self, ("parent_id", "price_basis", "need_date"))
        return self


class PackageLinkIn(_In):
    link_kind: PackageLinkKind
    link_id: uuid.UUID


class PackageStatusIn(_In):
    status: Literal["planned", "closed", "cancelled"]


class ReopenIn(_In):
    """Why a binding decision is opened again. Needed on a project without gates, where no change request says it."""

    reason: str | None = Field(default=None, max_length=2000)


class OfiIn(_In):
    code: str = Field(pattern=_PKG_CODE, max_length=64)
    description: str = Field(min_length=1, max_length=5000)
    item_kind: OfiKind = "equipment"
    install_by: Literal["owner", "package"] = "package"
    package_id: uuid.UUID | None = None
    need_by_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expected_delivery_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    enquiry_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    schedule_activity_id: uuid.UUID | None = None
    plant_item_id: uuid.UUID | None = None


class OfiPatch(_In):
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    item_kind: OfiKind | None = None
    install_by: Literal["owner", "package"] | None = None
    package_id: uuid.UUID | None = None
    need_by_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expected_delivery_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    enquiry_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    schedule_activity_id: uuid.UUID | None = None
    plant_item_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> OfiPatch:
        _refuse_nulls(
            self,
            (
                "package_id",
                "need_by_date",
                "expected_delivery_date",
                "enquiry_date",
                "lead_time_days",
                "schedule_activity_id",
                "plant_item_id",
            ),
        )
        return self


class OfiRouteIn(_In):
    procurement_route: OfiRoute
    link_kind: OfiLinkKind | None = None
    link_id: uuid.UUID | None = None


class OfiStatusIn(_In):
    status: Literal["identified", "route_set", "ordered", "delivered", "handed_to_installer"]


ContractGroup = Literal["contract_form", "land_tenure", "utility_contract", "user_agreement", "partner_structure"]
ContractItemStatus = Literal["draft", "negotiating", "agreed", "signed", "terminated"]
_DAY = r"^\d{4}-\d{2}-\d{2}$"
_PERCENT = r"^(100(\.0{1,4})?|\d{1,2}(\.\d{1,4})?)$"


class ContractItemIn(_In):
    code: str = Field(pattern=_PKG_CODE, max_length=64)
    group_code: ContractGroup
    kind_code: str = Field(pattern=_CODE, max_length=64)
    title: str = Field(default="", max_length=500)
    counterparty: str = Field(default="", max_length=255)
    package_id: uuid.UUID | None = None
    status: ContractItemStatus = "draft"
    reference: str = Field(default="", max_length=120)
    start_date: str | None = Field(default=None, pattern=_DAY)
    end_date: str | None = Field(default=None, pattern=_DAY)
    price_basis: PriceBasis | None = None
    share_percent: str | None = Field(default=None, pattern=_PERCENT)
    notes: str = Field(default="", max_length=5000)

    @field_validator("share_percent", mode="before")
    @classmethod
    def _share_not_float(cls, value: Any) -> Any:
        return _no_float(value)

    @model_validator(mode="after")
    def _group_fields(self) -> ContractItemIn:
        if self.price_basis is not None and self.group_code != "contract_form":
            raise ValueError("price_basis belongs to a contract form")
        if self.share_percent is not None and self.group_code != "partner_structure":
            raise ValueError("share_percent belongs to a partner structure")
        return self


class ContractItemPatch(_In):
    kind_code: str | None = Field(default=None, pattern=_CODE, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    counterparty: str | None = Field(default=None, max_length=255)
    package_id: uuid.UUID | None = None
    status: ContractItemStatus | None = None
    reference: str | None = Field(default=None, max_length=120)
    start_date: str | None = Field(default=None, pattern=_DAY)
    end_date: str | None = Field(default=None, pattern=_DAY)
    price_basis: PriceBasis | None = None
    share_percent: str | None = Field(default=None, pattern=_PERCENT)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("share_percent", mode="before")
    @classmethod
    def _share_not_float(cls, value: Any) -> Any:
        return _no_float(value)

    @model_validator(mode="after")
    def _no_nulls(self) -> ContractItemPatch:
        _refuse_nulls(self, ("package_id", "start_date", "end_date", "price_basis", "share_percent"))
        return self


class FindingOut(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
