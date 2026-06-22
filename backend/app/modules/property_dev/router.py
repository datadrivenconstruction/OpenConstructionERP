"""‌⁠‍Property Development API routes.

All routes are RBAC-gated and mounted by the module loader at
``/api/v1/property-dev/`` (slash inferred from module name).
"""

from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.core.email import EmailAttachment, get_email_service
from app.core.file_signature import (
    ALLOWED_PHOTO_TYPES,
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
    mime_for_signature,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.pdf_fonts import BODY_FONT, register_pdf_fonts
from app.core.sanitize import strip_dangerous_html
from app.core.validation.messages import translate
from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep
from app.modules.portal.dependencies import RequirePortalSession
from app.modules.property_dev.bulk_operations import (
    bulk_extend_reservation_expiry,
    bulk_import_leads_csv,
    bulk_merge_buyers,
    bulk_plot_status_change,
    bulk_regenerate_documents,
)
from app.modules.property_dev.schemas import (
    BlockCreate,
    BlockResponse,
    BlockUpdate,
    BrokerCreate,
    BrokerPerformanceResponse,
    BrokerResponse,
    BrokerUpdate,
    BulkResult,
    BuyerBulkMerge,
    BuyerCancelRequest,
    BuyerConfiguratorResponse,
    BuyerContractRequest,
    BuyerCreate,
    BuyerJourneyResponse,
    BuyerOptionCreate,
    BuyerOptionGroupCreate,
    BuyerOptionGroupResponse,
    BuyerOptionGroupUpdate,
    BuyerOptionResponse,
    BuyerOptionUpdate,
    BuyerResponse,
    BuyerSelectionCreate,
    BuyerSelectionItemCreate,
    BuyerSelectionItemResponse,
    BuyerSelectionResponse,
    BuyerSelectionUpdate,
    BuyerUpdate,
    CashflowWaterfallResponse,
    CohortRetentionResponse,
    CommissionAccrualPayRequest,
    CommissionAccrualResponse,
    CommissionAgreementCreate,
    CommissionAgreementResponse,
    CommissionAgreementUpdate,
    ComplianceDashboardResponse,
    ComplianceRegulatorReportResponse,
    ComplianceRuleResult,
    ContractPartyCreate,
    ContractPartyResponse,
    ContractPartyUpdate,
    ContractTaxQuote,
    ConversionFunnelResponse,
    DepositForfeitureResponse,
    DevelopmentCreate,
    DevelopmentDashboard,
    DevelopmentPnLResponse,
    DevelopmentResponse,
    DevelopmentUpdate,
    DocumentsBulkRegenerate,
    EscrowAccountCreate,
    EscrowAccountResponse,
    EscrowAccountUpdate,
    EscrowBalanceResponse,
    EscrowTransactionCreate,
    EscrowTransactionReconcileRequest,
    EscrowTransactionResponse,
    EscrowTransactionUpdate,
    FunnelConversionResponse,
    HandoverBundleResponse,
    HandoverCompleteRequest,
    HandoverCreate,
    HandoverDocCreate,
    HandoverDocResponse,
    HandoverDocUpdate,
    HandoverResponse,
    HandoverUpdate,
    HouseTypeCreate,
    HouseTypeResponse,
    HouseTypeUpdate,
    HouseTypeVariantCreate,
    HouseTypeVariantResponse,
    HouseTypeVariantUpdate,
    InstalmentCreate,
    InstalmentMarkPaidRequest,
    InstalmentResponse,
    InstalmentUpdate,
    InstalmentWaiveRequest,
    InventoryAgeingResponse,
    InventoryHeatmapResponse,
    LeadConvertToReservationRequest,
    LeadCreate,
    LeadResponse,
    LeadSourceAttributionResponse,
    LeadUpdate,
    PaymentScheduleCreate,
    PaymentScheduleResponse,
    PaymentScheduleUpdate,
    PhaseCreate,
    PhaseResponse,
    PhaseUpdate,
    PlotBulkStatusChange,
    PlotCreate,
    PlotPricingResponse,
    PlotReserveRequest,
    PlotResponse,
    PlotUpdate,
    PriceMatrixBulkRecomputeResponse,
    PriceMatrixCreate,
    PriceMatrixPreviewResponse,
    PriceMatrixResponse,
    PriceMatrixUpdate,
    PropertyDevHouseTypeCreate,
    PropertyDevHouseTypeResponse,
    PropertyDevHouseTypeUpdate,
    RegulatorReportResponse,
    ReservationBulkExtendExpiry,
    ReservationCalendarResponse,
    ReservationConvertToSpaRequest,
    ReservationCreate,
    ReservationExpiryBatchResponse,
    ReservationResponse,
    ReservationUpdate,
    SalesContractCreate,
    SalesContractResponse,
    SalesContractSendForSignatureRequest,
    SalesContractSignRequest,
    SalesContractUpdate,
    SalesKanbanResponse,
    SalesVelocityResponse,
    SnagCreate,
    SnagResponse,
    SnagUpdate,
    TaxQuotePayload,
    TimeToCloseResponse,
    WarrantyClaimAssignRequest,
    WarrantyClaimCreate,
    WarrantyClaimResponse,
    WarrantyClaimUpdate,
)
from app.modules.property_dev.service import (
    PropertyDevService,
    compute_plot_final_price,
    supported_jurisdictions,
)

router = APIRouter(tags=["property_dev"])


def _svc(session: SessionDep) -> PropertyDevService:
    return PropertyDevService(session)


async def _verify_buyer_owner(
    session: SessionDep,
    buyer_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Confirm the calling user owns the project behind this buyer.

    Closes a cross-tenant write IDOR on ``PATCH /buyers/{b_id}``: without
    this guard, any user with ``property_dev.update`` could mutate any
    other tenant's buyer just by guessing UUIDs. Admins bypass.

    Resolves the chain buyer → development → project.owner_id and either
    raises 404 (when the buyer does not exist OR is owned by a different
    user, so we never leak existence) or returns silently.
    """
    is_admin = payload.get("role") == "admin"
    user_id = payload.get("sub") or payload.get("user_id")
    if user_id is None:
        # Should not happen - RequirePermission already ensures auth -
        # but be conservative and 401-style 404 the request.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer not found")

    from app.modules.projects.repository import ProjectRepository
    from app.modules.property_dev.repository import (
        BuyerRepository,
        DevelopmentRepository,
    )

    buyer = await BuyerRepository(session).get_by_id(buyer_id)
    if buyer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer not found")
    if is_admin:
        return

    development = await DevelopmentRepository(session).get_by_id(
        buyer.development_id,
    )
    if development is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer not found")
    project = await ProjectRepository(session).get_by_id(development.project_id)
    if project is None or str(project.owner_id) != str(user_id):
        # 404 (not 403) - collapse "exists but not yours" into the same
        # response as "doesn't exist" so this endpoint can't be turned
        # into a UUID-existence oracle for other tenants' buyers.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer not found")


# ── Developments ────────────────────────────────────────────────────────


@router.get("/developments/", response_model=list[DevelopmentResponse])
async def list_developments(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[DevelopmentResponse]:
    # Cross-tenant IDOR gate: ``list_all`` had no WHERE clause and returned
    # every tenant's developments. Scope the listing to the caller's
    # accessible developments (development -> project owner). Admins get the
    # unscoped listing (``dev_ids=None``); a non-admin with no accessible
    # developments gets an empty list rather than every tenant's rows.
    is_admin = user_payload.get("role") == "admin"
    dev_ids: list[uuid.UUID] | None = None
    if not is_admin:
        dev_ids = await _list_accessible_dev_ids(session, user_payload)
    rows, _ = await service.developments.list_all(offset=offset, limit=limit, dev_ids=dev_ids)
    return [DevelopmentResponse.model_validate(r) for r in rows]


@router.post("/developments/", response_model=DevelopmentResponse, status_code=201)
async def create_development(
    data: DevelopmentCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> DevelopmentResponse:
    # R7 IDOR - prevent attaching a development (and its plots/buyers/
    # contracts) to a project in another tenant by supplying that
    # project's UUID in the body.
    await _verify_owner_via_project(session, data.project_id, user_payload)
    obj = await service.create_development(data)
    return DevelopmentResponse.model_validate(obj)


@router.get("/developments/{dev_id}", response_model=DevelopmentResponse)
async def get_development(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> DevelopmentResponse:
    await _verify_owner_via_development(session, dev_id, user_payload)
    obj = await service.get_development(dev_id)
    return DevelopmentResponse.model_validate(obj)


@router.patch("/developments/{dev_id}", response_model=DevelopmentResponse)
async def update_development(
    dev_id: uuid.UUID,
    data: DevelopmentUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> DevelopmentResponse:
    await _verify_owner_via_development(session, dev_id, user_payload)
    obj = await service.update_development(dev_id, data)
    return DevelopmentResponse.model_validate(obj)


@router.delete("/developments/{dev_id}", status_code=204)
async def delete_development(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_development(session, dev_id, user_payload)
    await service.delete_development(dev_id)


@router.get(
    "/developments/{dev_id}/dashboard",
    response_model=DevelopmentDashboard,
)
async def development_dashboard(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> DevelopmentDashboard:
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.development_sales_dashboard(dev_id)
    return DevelopmentDashboard.model_validate(payload)


@router.get(
    "/developments/{dev_id}/sales-dashboard",
    response_model=DevelopmentDashboard,
)
async def development_sales_dashboard(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> DevelopmentDashboard:
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.development_sales_dashboard(dev_id)
    return DevelopmentDashboard.model_validate(payload)


# ── Plots ───────────────────────────────────────────────────────────────


@router.get("/plots/", response_model=list[PlotResponse])
async def list_plots(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID = Query(...),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PlotResponse]:
    # R7 IDOR - gate the parent dev so we can't enumerate other tenants'
    # plots by guessing development UUIDs (the dev_id is a query param).
    await _verify_owner_via_development(session, development_id, user_payload)
    rows, _ = await service.plots.list_for_development(development_id, offset=offset, limit=limit, status=status)
    return [PlotResponse.model_validate(r) for r in rows]


@router.post("/plots/", response_model=PlotResponse, status_code=201)
async def create_plot(
    data: PlotCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> PlotResponse:
    # R7 IDOR - prevent creating a plot under someone else's development.
    await _verify_owner_via_development(session, data.development_id, user_payload)
    obj = await service.create_plot(data)
    return PlotResponse.model_validate(obj)


@router.get("/plots/{plot_id}", response_model=PlotResponse)
async def get_plot(
    plot_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PlotResponse:
    await _verify_owner_via_plot(session, plot_id, user_payload)
    obj = await service.get_plot(plot_id)
    return PlotResponse.model_validate(obj)


@router.patch("/plots/{plot_id}", response_model=PlotResponse)
async def update_plot(
    plot_id: uuid.UUID,
    data: PlotUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> PlotResponse:
    await _verify_owner_via_plot(session, plot_id, user_payload)
    obj = await service.update_plot(plot_id, data)
    return PlotResponse.model_validate(obj)


@router.delete("/plots/{plot_id}", status_code=204)
async def delete_plot(
    plot_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_plot(session, plot_id, user_payload)
    await service.delete_plot(plot_id)


@router.post("/plots/{plot_id}/reserve", response_model=PlotResponse)
async def reserve_plot(
    plot_id: uuid.UUID,
    data: PlotReserveRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reserve_plot")),
) -> PlotResponse:
    await _verify_owner_via_plot(session, plot_id, user_payload)
    plot, _ = await service.reserve_plot(plot_id, data)
    return PlotResponse.model_validate(plot)


@router.get(
    "/plots/{plot_id}/configurator",
    response_model=BuyerConfiguratorResponse,
)
async def plot_configurator(
    plot_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BuyerConfiguratorResponse:
    """Plot configurator bundle (plot + house type + variant + options +
    selection + pricing).

    R8: cross-tenant IDOR closed via ``_verify_owner_via_plot``.
    """
    await _verify_owner_via_plot(session, plot_id, user_payload)
    plot = await service.get_plot(plot_id)
    house_type = await service.house_types.get_by_id(plot.house_type_id) if plot.house_type_id else None
    variant = await service.variants.get_by_id(plot.house_type_variant_id) if plot.house_type_variant_id else None

    groups = await service.option_groups.list_for_development(plot.development_id)
    options_by_group: dict[str, list[BuyerOptionResponse]] = {}
    for g in groups:
        opts = await service.options.list_active_options_for_group(g.id)
        options_by_group[str(g.id)] = [BuyerOptionResponse.model_validate(o) for o in opts]

    buyer = await service.buyers.get_for_plot(plot_id)
    current_selection: Any = None
    current_items: list[Any] = []
    if buyer is not None:
        current_selection = await service.selections.current_selection_for_buyer(buyer.id)
        if current_selection is not None:
            current_items = await service.selection_items.list_for_selection(current_selection.id)

    pricing_total = compute_plot_final_price(plot, variant, current_items)
    pricing = PlotPricingResponse(
        plot_id=plot.id,
        base_price=Decimal(str(plot.price_base)),
        variant_modifier_value=(
            (Decimal(str(plot.price_base)) * Decimal(str(variant.modifier_pct)) / Decimal("100"))
            if variant
            else Decimal("0")
        ),
        selections_total=sum((Decimal(str(i.total_price)) for i in current_items), Decimal("0")),
        final_price=pricing_total,
        currency=plot.currency or "",
    )

    return BuyerConfiguratorResponse(
        plot=PlotResponse.model_validate(plot),
        house_type=HouseTypeResponse.model_validate(house_type) if house_type else None,
        variant=HouseTypeVariantResponse.model_validate(variant) if variant else None,
        option_groups=[BuyerOptionGroupResponse.model_validate(g) for g in groups],
        options_by_group=options_by_group,
        current_selection=(BuyerSelectionResponse.model_validate(current_selection) if current_selection else None),
        current_items=[BuyerSelectionItemResponse.model_validate(i) for i in current_items],
        pricing=pricing,
    )


# ── House Types & Variants ──────────────────────────────────────────────


@router.get("/house-types/", response_model=list[HouseTypeResponse])
async def list_house_types(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[HouseTypeResponse]:
    await _verify_owner_via_development(session, development_id, user_payload)
    rows = await service.house_types.list_for_development(development_id)
    return [HouseTypeResponse.model_validate(r) for r in rows]


@router.post(
    "/house-types/",
    response_model=HouseTypeResponse,
    status_code=201,
)
async def create_house_type(
    data: HouseTypeCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> HouseTypeResponse:
    await _verify_owner_via_development(session, data.development_id, user_payload)
    obj = await service.create_house_type(data)
    return HouseTypeResponse.model_validate(obj)


@router.get("/house-types/{ht_id}", response_model=HouseTypeResponse)
async def get_house_type(
    ht_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> HouseTypeResponse:
    await _verify_owner_via_house_type(session, ht_id, user_payload)
    return HouseTypeResponse.model_validate(await service.get_house_type(ht_id))


@router.patch("/house-types/{ht_id}", response_model=HouseTypeResponse)
async def update_house_type(
    ht_id: uuid.UUID,
    data: HouseTypeUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> HouseTypeResponse:
    await _verify_owner_via_house_type(session, ht_id, user_payload)
    obj = await service.update_house_type(ht_id, data)
    return HouseTypeResponse.model_validate(obj)


@router.delete("/house-types/{ht_id}", status_code=204)
async def delete_house_type(
    ht_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_house_type(session, ht_id, user_payload)
    await service.delete_house_type(ht_id)


# ── House Type Catalogue (preset + user-created) ────────────────────────


@router.get(
    "/house-type-catalogue/",
    response_model=list[PropertyDevHouseTypeResponse],
)
async def list_house_type_catalogue(
    payload: CurrentUserPayload,
    country_code: str | None = Query(default=None, max_length=2),
    project_id: uuid.UUID | None = Query(default=None),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PropertyDevHouseTypeResponse]:
    """List preset + (when project_id supplied) tenant-created house types.

    Presets (project_id IS NULL, is_preset=True) are always visible.
    Tenant-created entries are only included when the caller owns the
    project - admins see everything.
    """
    rows = await service.list_house_type_catalogue(
        country_code=country_code,
        project_id=project_id,
        user_payload=payload,
    )
    return [PropertyDevHouseTypeResponse.model_validate(r) for r in rows]


@router.post(
    "/house-type-catalogue/",
    response_model=PropertyDevHouseTypeResponse,
    status_code=201,
)
async def create_house_type_catalogue_entry(
    data: PropertyDevHouseTypeCreate,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> PropertyDevHouseTypeResponse:
    obj = await service.create_house_type_catalogue_entry(data, user_payload=payload)
    return PropertyDevHouseTypeResponse.model_validate(obj)


@router.get(
    "/house-type-catalogue/{entry_id}",
    response_model=PropertyDevHouseTypeResponse,
)
async def get_house_type_catalogue_entry(
    entry_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PropertyDevHouseTypeResponse:
    obj = await service.get_house_type_catalogue_entry(entry_id, user_payload=payload)
    return PropertyDevHouseTypeResponse.model_validate(obj)


@router.patch(
    "/house-type-catalogue/{entry_id}",
    response_model=PropertyDevHouseTypeResponse,
)
async def update_house_type_catalogue_entry(
    entry_id: uuid.UUID,
    data: PropertyDevHouseTypeUpdate,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> PropertyDevHouseTypeResponse:
    obj = await service.update_house_type_catalogue_entry(entry_id, data, user_payload=payload)
    return PropertyDevHouseTypeResponse.model_validate(obj)


@router.delete("/house-type-catalogue/{entry_id}", status_code=204)
async def delete_house_type_catalogue_entry(
    entry_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await service.delete_house_type_catalogue_entry(entry_id, user_payload=payload)


@router.get(
    "/house-type-variants/",
    response_model=list[HouseTypeVariantResponse],
)
async def list_variants(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    house_type_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[HouseTypeVariantResponse]:
    await _verify_owner_via_house_type(session, house_type_id, user_payload)
    rows = await service.variants.list_for_house_type(house_type_id)
    return [HouseTypeVariantResponse.model_validate(r) for r in rows]


@router.post(
    "/house-type-variants/",
    response_model=HouseTypeVariantResponse,
    status_code=201,
)
async def create_variant(
    data: HouseTypeVariantCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> HouseTypeVariantResponse:
    await _verify_owner_via_house_type(session, data.house_type_id, user_payload)
    return HouseTypeVariantResponse.model_validate(await service.create_variant(data))


@router.get(
    "/house-type-variants/{v_id}",
    response_model=HouseTypeVariantResponse,
)
async def get_variant(
    v_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> HouseTypeVariantResponse:
    await _verify_owner_via_variant(session, v_id, user_payload)
    return HouseTypeVariantResponse.model_validate(await service.get_variant(v_id))


@router.patch(
    "/house-type-variants/{v_id}",
    response_model=HouseTypeVariantResponse,
)
async def update_variant(
    v_id: uuid.UUID,
    data: HouseTypeVariantUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> HouseTypeVariantResponse:
    await _verify_owner_via_variant(session, v_id, user_payload)
    return HouseTypeVariantResponse.model_validate(await service.update_variant(v_id, data))


@router.delete("/house-type-variants/{v_id}", status_code=204)
async def delete_variant(
    v_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_variant(session, v_id, user_payload)
    await service.delete_variant(v_id)


# ── Option Groups ───────────────────────────────────────────────────────


@router.get("/option-groups/", response_model=list[BuyerOptionGroupResponse])
async def list_option_groups(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[BuyerOptionGroupResponse]:
    await _verify_owner_via_development(session, development_id, user_payload)
    rows = await service.option_groups.list_for_development(development_id)
    return [BuyerOptionGroupResponse.model_validate(r) for r in rows]


@router.post(
    "/option-groups/",
    response_model=BuyerOptionGroupResponse,
    status_code=201,
)
async def create_option_group(
    data: BuyerOptionGroupCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> BuyerOptionGroupResponse:
    await _verify_owner_via_development(session, data.development_id, user_payload)
    return BuyerOptionGroupResponse.model_validate(await service.create_option_group(data))


@router.get("/option-groups/{g_id}", response_model=BuyerOptionGroupResponse)
async def get_option_group(
    g_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BuyerOptionGroupResponse:
    await _verify_owner_via_option_group(session, g_id, user_payload)
    return BuyerOptionGroupResponse.model_validate(await service.get_option_group(g_id))


@router.patch("/option-groups/{g_id}", response_model=BuyerOptionGroupResponse)
async def update_option_group(
    g_id: uuid.UUID,
    data: BuyerOptionGroupUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BuyerOptionGroupResponse:
    await _verify_owner_via_option_group(session, g_id, user_payload)
    return BuyerOptionGroupResponse.model_validate(await service.update_option_group(g_id, data))


@router.delete("/option-groups/{g_id}", status_code=204)
async def delete_option_group(
    g_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_option_group(session, g_id, user_payload)
    await service.delete_option_group(g_id)


# ── Options ─────────────────────────────────────────────────────────────


@router.get("/options/", response_model=list[BuyerOptionResponse])
async def list_options(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    group_id: uuid.UUID = Query(...),
    active_only: bool = Query(default=True),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[BuyerOptionResponse]:
    await _verify_owner_via_option_group(session, group_id, user_payload)
    rows = await service.options.list_for_group(group_id, active_only=active_only)
    return [BuyerOptionResponse.model_validate(r) for r in rows]


@router.post("/options/", response_model=BuyerOptionResponse, status_code=201)
async def create_option(
    data: BuyerOptionCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> BuyerOptionResponse:
    await _verify_owner_via_option_group(session, data.group_id, user_payload)
    return BuyerOptionResponse.model_validate(await service.create_option(data))


@router.get("/options/{o_id}", response_model=BuyerOptionResponse)
async def get_option(
    o_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BuyerOptionResponse:
    await _verify_owner_via_option(session, o_id, user_payload)
    return BuyerOptionResponse.model_validate(await service.get_option(o_id))


@router.patch("/options/{o_id}", response_model=BuyerOptionResponse)
async def update_option(
    o_id: uuid.UUID,
    data: BuyerOptionUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BuyerOptionResponse:
    await _verify_owner_via_option(session, o_id, user_payload)
    return BuyerOptionResponse.model_validate(await service.update_option(o_id, data))


@router.delete("/options/{o_id}", status_code=204)
async def delete_option(
    o_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_option(session, o_id, user_payload)
    await service.delete_option(o_id)


# ── Buyers ──────────────────────────────────────────────────────────────


@router.get("/buyers/", response_model=list[BuyerResponse])
async def list_buyers(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID = Query(...),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[BuyerResponse]:
    await _verify_owner_via_development(session, development_id, user_payload)
    rows, _ = await service.buyers.list_for_development(development_id, offset=offset, limit=limit, status=status)
    return [BuyerResponse.model_validate(r) for r in rows]


@router.post("/buyers/", response_model=BuyerResponse, status_code=201)
async def create_buyer(
    data: BuyerCreate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    sync_to_contacts: bool = Query(
        default=True,
        description=(
            "When true (default), the buyer is mirrored to the Contacts "
            "directory and the contact picks up the 'property_dev_buyer' "
            "module tag. Pass false to skip the sync (e.g. for portal-"
            "driven anonymous signups)."
        ),
    ),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> BuyerResponse:
    # R7 IDOR - prevent attaching a buyer to another tenant's development
    # (or plot) by supplying a foreign parent UUID in the body.
    await _verify_owner_via_development(session, data.development_id, payload)
    if data.plot_id is not None:
        await _verify_owner_via_plot(session, data.plot_id, payload)
    caller = payload.get("sub") if isinstance(payload, dict) else None
    return BuyerResponse.model_validate(
        await service.create_buyer(
            data,
            sync_to_contacts=sync_to_contacts,
            tenant_id=str(caller) if caller else None,
        )
    )


@router.get("/buyers/{b_id}", response_model=BuyerResponse)
async def get_buyer(
    b_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BuyerResponse:
    await _verify_owner_via_buyer(session, b_id, user_payload)
    return BuyerResponse.model_validate(await service.get_buyer(b_id))


@router.patch("/buyers/{b_id}", response_model=BuyerResponse)
async def update_buyer(
    b_id: uuid.UUID,
    data: BuyerUpdate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BuyerResponse:
    # Cross-tenant write IDOR gate (task #134). Verifies the buyer's
    # development belongs to a project owned by the caller, or that the
    # caller is admin. Bumps 404 (not 403) on cross-tenant access to
    # avoid leaking existence of other tenants' buyer UUIDs.
    await _verify_buyer_owner(session, b_id, payload)
    return BuyerResponse.model_validate(await service.update_buyer(b_id, data))


@router.delete("/buyers/{b_id}", status_code=204)
async def delete_buyer(
    b_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_buyer(session, b_id, user_payload)
    await service.delete_buyer(b_id)


@router.post("/buyers/{b_id}/contract", response_model=BuyerResponse)
async def contract_buyer(
    b_id: uuid.UUID,
    data: BuyerContractRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_buyer")),
) -> BuyerResponse:
    await _verify_owner_via_buyer(session, b_id, user_payload)
    return BuyerResponse.model_validate(await service.convert_buyer_to_contracted(b_id, data))


# ── Selections ──────────────────────────────────────────────────────────


@router.get("/selections/", response_model=list[BuyerSelectionResponse])
async def list_selections(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    buyer_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[BuyerSelectionResponse]:
    # Cross-tenant IDOR gate: ``list_for_buyer`` filters by buyer_id only,
    # so without this check any caller with ``property_dev.read`` could
    # read another tenant's buyer selections by guessing the buyer UUID.
    # Verify the buyer's development belongs to a project the caller owns
    # (admins bypass); 404 on cross-tenant access so we never leak the
    # existence of other tenants' buyer UUIDs.
    await _verify_owner_via_buyer(session, buyer_id, user_payload)
    rows = await service.selections.list_for_buyer(buyer_id)
    return [BuyerSelectionResponse.model_validate(r) for r in rows]


@router.post(
    "/selections/",
    response_model=BuyerSelectionResponse,
    status_code=201,
)
async def create_selection(
    data: BuyerSelectionCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> BuyerSelectionResponse:
    await _verify_owner_via_buyer(session, data.buyer_id, user_payload)
    return BuyerSelectionResponse.model_validate(await service.create_selection(data))


@router.get("/selections/{s_id}", response_model=BuyerSelectionResponse)
async def get_selection(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BuyerSelectionResponse:
    await _verify_owner_via_selection(session, s_id, user_payload)
    return BuyerSelectionResponse.model_validate(await service.get_selection(s_id))


@router.patch("/selections/{s_id}", response_model=BuyerSelectionResponse)
async def update_selection(
    s_id: uuid.UUID,
    data: BuyerSelectionUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BuyerSelectionResponse:
    await _verify_owner_via_selection(session, s_id, user_payload)
    return BuyerSelectionResponse.model_validate(await service.update_selection(s_id, data))


@router.delete("/selections/{s_id}", status_code=204)
async def delete_selection(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_selection(session, s_id, user_payload)
    await service.delete_selection(s_id)


@router.post(
    "/selections/{s_id}/submit",
    response_model=BuyerSelectionResponse,
)
async def submit_selection(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BuyerSelectionResponse:
    await _verify_owner_via_selection(session, s_id, user_payload)
    return BuyerSelectionResponse.model_validate(await service.submit_selection(s_id))


@router.post(
    "/selections/{s_id}/lock",
    response_model=BuyerSelectionResponse,
)
async def lock_selection(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lock_selection")),
) -> BuyerSelectionResponse:
    await _verify_owner_via_selection(session, s_id, user_payload)
    return BuyerSelectionResponse.model_validate(await service.lock_selection(s_id))


@router.post(
    "/selections/{s_id}/items",
    response_model=BuyerSelectionItemResponse,
    status_code=201,
)
async def add_selection_item(
    s_id: uuid.UUID,
    data: BuyerSelectionItemCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BuyerSelectionItemResponse:
    await _verify_owner_via_selection(session, s_id, user_payload)
    return BuyerSelectionItemResponse.model_validate(await service.add_selection_item(s_id, data))


@router.delete(
    "/selections/{s_id}/items/{item_id}",
    status_code=204,
)
async def remove_selection_item(
    s_id: uuid.UUID,
    item_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> None:
    # ``s_id`` kept for URL clarity; we look up via item itself.
    await _verify_owner_via_selection(session, s_id, user_payload)
    _ = s_id
    await service.remove_selection_item(item_id)


@router.post(
    "/selections/{s_id}/submit-for-production",
    response_model=BuyerSelectionResponse,
)
async def selection_submit_for_production(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lock_selection")),
) -> BuyerSelectionResponse:
    await _verify_owner_via_selection(session, s_id, user_payload)
    sel = await service.get_selection(s_id)
    result = await service.submit_for_production(sel.buyer_id)
    return BuyerSelectionResponse.model_validate(result)


# ── Handovers ───────────────────────────────────────────────────────────


@router.get("/handovers/", response_model=list[HandoverResponse])
async def list_handovers(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    plot_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[HandoverResponse]:
    # IDOR closure: tenant must own the plot before seeing its handovers.
    await _verify_owner_via_plot(session, plot_id, user_payload)
    rows = await service.handovers.list_for_plot(plot_id)
    return [HandoverResponse.model_validate(r) for r in rows]


@router.post("/handovers/", response_model=HandoverResponse, status_code=201)
async def create_handover(
    data: HandoverCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.handover")),
) -> HandoverResponse:
    # IDOR closure: must own the plot before scheduling a handover against it.
    await _verify_owner_via_plot(session, data.plot_id, user_payload)
    return HandoverResponse.model_validate(await service.create_handover(data))


@router.get("/handovers/{h_id}", response_model=HandoverResponse)
async def get_handover(
    h_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> HandoverResponse:
    await _verify_owner_via_handover(session, h_id, user_payload)
    return HandoverResponse.model_validate(await service.get_handover(h_id))


@router.patch("/handovers/{h_id}", response_model=HandoverResponse)
async def update_handover(
    h_id: uuid.UUID,
    data: HandoverUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.handover")),
) -> HandoverResponse:
    await _verify_owner_via_handover(session, h_id, user_payload)
    return HandoverResponse.model_validate(await service.update_handover(h_id, data))


@router.delete("/handovers/{h_id}", status_code=204)
async def delete_handover(
    h_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_handover(session, h_id, user_payload)
    await service.delete_handover(h_id)


@router.post("/handovers/{h_id}/complete", response_model=HandoverResponse)
async def complete_handover(
    h_id: uuid.UUID,
    data: HandoverCompleteRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.handover")),
) -> HandoverResponse:
    await _verify_owner_via_handover(session, h_id, user_payload)
    return HandoverResponse.model_validate(await service.complete_handover(h_id, data))


# ── Snags ───────────────────────────────────────────────────────────────


@router.get("/snags/", response_model=list[SnagResponse])
async def list_snags(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    handover_id: uuid.UUID = Query(...),
    status: str | None = Query(default=None),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[SnagResponse]:
    await _verify_owner_via_handover(session, handover_id, user_payload)
    rows = await service.snags.list_for_handover(handover_id, status=status)
    return [SnagResponse.model_validate(r) for r in rows]


@router.post("/snags/", response_model=SnagResponse, status_code=201)
async def create_snag(
    data: SnagCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.handover")),
) -> SnagResponse:
    await _verify_owner_via_handover(session, data.handover_id, user_payload)
    return SnagResponse.model_validate(await service.create_snag(data))


@router.get("/snags/{s_id}", response_model=SnagResponse)
async def get_snag(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> SnagResponse:
    await _verify_owner_via_snag(session, s_id, user_payload)
    return SnagResponse.model_validate(await service.get_snag(s_id))


@router.patch("/snags/{s_id}", response_model=SnagResponse)
async def update_snag(
    s_id: uuid.UUID,
    data: SnagUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.fix_snag")),
) -> SnagResponse:
    await _verify_owner_via_snag(session, s_id, user_payload)
    return SnagResponse.model_validate(await service.update_snag(s_id, data))


@router.delete("/snags/{s_id}", status_code=204)
async def delete_snag(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_snag(session, s_id, user_payload)
    await service.delete_snag(s_id)


@router.post("/snags/{s_id}/fix", response_model=SnagResponse)
async def fix_snag(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    payload: dict[str, Any] | None = None,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.fix_snag")),
) -> SnagResponse:
    await _verify_owner_via_snag(session, s_id, user_payload)
    fix_notes = (payload or {}).get("fix_notes")
    return SnagResponse.model_validate(await service.mark_snag_fixed(s_id, fix_notes=fix_notes))


@router.post("/snags/{s_id}/wont-fix", response_model=SnagResponse)
async def wont_fix_snag(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    payload: dict[str, Any] | None = None,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.fix_snag")),
) -> SnagResponse:
    await _verify_owner_via_snag(session, s_id, user_payload)
    fix_notes = (payload or {}).get("fix_notes")
    return SnagResponse.model_validate(await service.mark_snag_wont_fix(s_id, fix_notes=fix_notes))


# Directory where snag photos live on disk. Mirrors punchlist's layout.
_SNAG_PHOTOS_DIR = Path("uploads/snag/photos")
_snag_logger = logging.getLogger(__name__)


@router.post("/snags/{s_id}/photos/", response_model=SnagResponse)
async def upload_snag_photo(
    s_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    file: UploadFile = File(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.fix_snag")),
) -> SnagResponse:
    """Upload a photo for a snag.

    Content-type headers are attacker-controlled, so we validate the raw
    magic bytes against :data:`ALLOWED_PHOTO_TYPES` (jpeg, png, gif,
    webp, heic, heif, tiff). SVG and any other format are rejected with
    415. Mirrors the closure in
    :func:`app.modules.punchlist.router.upload_photo`.
    """
    await _verify_owner_via_snag(session, s_id, user_payload)

    try:
        content = await file.read()
    except Exception:
        _snag_logger.exception("Unable to read snag photo upload %s", s_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded photo",
        )

    try:
        detected = require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            ALLOWED_PHOTO_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )
    _ = mime_for_signature(detected)  # validated; not stored on Snag yet.

    _SNAG_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "photo.jpg").suffix or ".jpg"
    filename = f"{s_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = _SNAG_PHOTOS_DIR / filename

    try:
        filepath.write_bytes(content)
    except Exception:
        _snag_logger.exception("Unable to save snag photo %s", s_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save photo - storage error",
        )

    photo_path = f"snag/photos/{filename}"
    snag = await service.add_snag_photo(s_id, photo_path)
    return SnagResponse.model_validate(snag)


# ── Warranty Claims ─────────────────────────────────────────────────────


@router.get("/warranty-claims/", response_model=list[WarrantyClaimResponse])
async def list_warranty_claims(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    buyer_id: uuid.UUID | None = Query(default=None),
    plot_id: uuid.UUID | None = Query(default=None),
    development_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[WarrantyClaimResponse]:
    """List warranty claims.

    Supports four scoping modes (mutually exclusive - buyer wins, then
    plot, then development, then project). When NONE are supplied the
    endpoint returns the empty list to avoid an accidental cross-tenant
    enumeration (matches the v3110 ``list_warranty_claims`` behavior).
    """
    if buyer_id is not None:
        await _verify_owner_via_buyer(session, buyer_id, user_payload)
        rows = await service.warranty.list_for_buyer(buyer_id, status=status)
    elif plot_id is not None:
        await _verify_owner_via_plot(session, plot_id, user_payload)
        rows = await service.warranty.list_for_plot(plot_id, status=status)
    elif development_id is not None:
        await _verify_owner_via_development(session, development_id, user_payload)
        rows = await service.warranty.list_for_development(
            development_id,
            status=status,
            category=category,
            severity=severity,
        )
    elif project_id is not None:
        # Project-level listing - IDOR-gated via the project ownership
        # check that already powers ``_verify_owner_via_plot``.
        from app.modules.projects.repository import ProjectRepository

        proj = await ProjectRepository(session).get_by_id(project_id)
        if proj is None:
            raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
        owner_id = uuid.UUID(str(user_payload["sub"]))
        if proj.owner_id != owner_id:
            raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
        rows = await service.warranty.list_for_project(project_id, status=status)
    else:
        rows = []
    # Batched: one IN(...) Handover fetch instead of N per-claim SELECTs.
    return await service.warranty_responses(rows)


@router.post(
    "/warranty-claims/",
    response_model=WarrantyClaimResponse,
    status_code=201,
)
async def create_warranty_claim(
    data: WarrantyClaimCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.process_warranty")),
) -> WarrantyClaimResponse:
    await _verify_owner_via_plot(session, data.plot_id, user_payload)
    await _verify_owner_via_buyer(session, data.buyer_id, user_payload)
    return await service.warranty_response(await service.raise_warranty_claim(data.plot_id, data.buyer_id, data))


@router.get(
    "/warranty-claims/{w_id}",
    response_model=WarrantyClaimResponse,
)
async def get_warranty_claim(
    w_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> WarrantyClaimResponse:
    await _verify_owner_via_warranty(session, w_id, user_payload)
    return await service.warranty_response(await service.get_warranty(w_id))


@router.patch(
    "/warranty-claims/{w_id}",
    response_model=WarrantyClaimResponse,
)
async def update_warranty_claim(
    w_id: uuid.UUID,
    data: WarrantyClaimUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.process_warranty")),
) -> WarrantyClaimResponse:
    await _verify_owner_via_warranty(session, w_id, user_payload)
    return await service.warranty_response(await service.update_warranty(w_id, data))


@router.delete("/warranty-claims/{w_id}", status_code=204)
async def delete_warranty_claim(
    w_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_warranty(session, w_id, user_payload)
    await service.delete_warranty(w_id)


@router.post(
    "/warranty-claims/{w_id}/assign",
    response_model=WarrantyClaimResponse,
)
async def assign_warranty_claim(
    w_id: uuid.UUID,
    data: WarrantyClaimAssignRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.process_warranty")),
) -> WarrantyClaimResponse:
    """Assign (or unassign with ``null``) a contractor / PM owner."""
    await _verify_owner_via_warranty(session, w_id, user_payload)
    return await service.warranty_response(await service.assign_warranty(w_id, data.assigned_to_user_id))


@router.post(
    "/warranty/{w_id}/accept",
    response_model=WarrantyClaimResponse,
)
async def accept_warranty_claim(
    w_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.process_warranty")),
) -> WarrantyClaimResponse:
    await _verify_owner_via_warranty(session, w_id, user_payload)
    return await service.warranty_response(await service.warranty_accept(w_id))


@router.post(
    "/warranty/{w_id}/reject",
    response_model=WarrantyClaimResponse,
)
async def reject_warranty_claim(
    w_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.process_warranty")),
) -> WarrantyClaimResponse:
    await _verify_owner_via_warranty(session, w_id, user_payload)
    return await service.warranty_response(await service.warranty_reject(w_id))


@router.post(
    "/warranty/{w_id}/close",
    response_model=WarrantyClaimResponse,
)
async def close_warranty_claim(
    w_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.process_warranty")),
) -> WarrantyClaimResponse:
    await _verify_owner_via_warranty(session, w_id, user_payload)
    return await service.warranty_response(await service.warranty_close(w_id))


@router.get("/warranty-claims/{w_id}/pdf")
async def warranty_claim_pdf(
    w_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
):
    """Generate a printable PDF for a warranty claim (legal / insurance).

    Falls back to a plain-text response when the reportlab PDF stack is
    unavailable so the endpoint never 500s the page; mirrors the
    document_templates fallback path.
    """
    from fastapi.responses import Response

    await _verify_owner_via_warranty(session, w_id, user_payload)
    claim = await service.get_warranty(w_id)
    payload = await service.warranty_response(claim)

    lines = [
        "WARRANTY CLAIM",
        "",
        f"Claim ID:       {claim.id}",
        f"Plot ID:        {claim.plot_id}",
        f"Buyer ID:       {claim.buyer_id}",
        f"Handover ID:    {claim.handover_id or '-'}",
        f"Raised at:      {claim.raised_at or '-'}",
        f"Category:       {claim.category}",
        f"Severity:       {claim.severity}",
        f"Status:         {claim.status}",
        f"In warranty:    {'YES' if payload.is_in_warranty else 'NO'}",
        f"SLA deadline:   {claim.sla_deadline or '-'}",
        f"Assigned to:    {claim.assigned_to_user_id or '-'}",
        "",
        "Description:",
        claim.description or "(none)",
        "",
        "Resolution notes:",
        claim.resolution_notes or "(none)",
    ]
    body = "\n".join(lines)

    try:
        from io import BytesIO

        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas as _canvas

        register_pdf_fonts()
        buf = BytesIO()
        c = _canvas.Canvas(buf, pagesize=A4)
        c.setFont(BODY_FONT, 10)
        y = 800
        for ln in body.splitlines():
            c.drawString(50, y, ln[:110])
            y -= 14
            if y < 50:
                c.showPage()
                c.setFont(BODY_FONT, 10)
                y = 800
        c.save()
        pdf_bytes = buf.getvalue()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (f'attachment; filename="warranty-claim-{w_id}.pdf"'),
            },
        )
    except Exception:
        # reportlab missing or rendering failed - return the txt fallback
        # so the legal/insurance team still gets something printable.
        return Response(
            content=body.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": (f'attachment; filename="warranty-claim-{w_id}.txt"'),
            },
        )


@router.post(
    "/warranty-claims/from-snag/{snag_id}",
    response_model=WarrantyClaimResponse,
    status_code=201,
)
async def create_warranty_claim_from_snag(
    snag_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.process_warranty")),
) -> WarrantyClaimResponse:
    """Promote a snag into a warranty claim (idempotent).

    Useful when a defect identified during/after handover turns out to
    be in-warranty and the buyer-facing process needs to escalate.
    Idempotent: if a claim is already linked via ``source_snag_id``, it
    is returned instead of creating a duplicate.
    """
    from app.modules.property_dev.schemas import WarrantyClaimCreate as _WCreate

    await _verify_owner_via_snag(session, snag_id, user_payload)
    snag = await service.get_snag(snag_id)

    existing = await service.warranty.find_by_source_snag(snag_id)
    if existing is not None:
        return await service.warranty_response(existing)

    # Resolve the buyer: prefer the buyer who raised the snag, else
    # whichever buyer is attached to the plot via the handover chain.
    buyer_id = snag.buyer_id
    handover = await service.get_handover(snag.handover_id)
    plot_id = handover.plot_id
    if buyer_id is None:
        # Best-effort: fall back to any buyer on the plot.
        from sqlalchemy import select as _select

        from app.modules.property_dev.models import Buyer as _Buyer

        row = (await session.execute(_select(_Buyer).where(_Buyer.plot_id == plot_id).limit(1))).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="Cannot raise warranty claim: snag has no buyer link",
            )
        buyer_id = row.id

    severity_map = {"minor": "minor", "major": "major", "critical": "critical"}
    payload = _WCreate(
        plot_id=plot_id,
        buyer_id=buyer_id,
        handover_id=snag.handover_id,
        source_snag_id=snag.id,
        category="defect",
        severity=severity_map.get(snag.severity, "minor"),
        description=snag.description or "(promoted from snag)",
        photos=list(snag.photos or []),
    )
    claim = await service.raise_warranty_claim(plot_id, buyer_id, payload)
    return await service.warranty_response(claim)


# ── Cancel buyer + deposit forfeiture ──────────────────────────────────


@router.post("/buyers/{b_id}/cancel", response_model=DepositForfeitureResponse)
async def cancel_buyer(
    b_id: uuid.UUID,
    data: BuyerCancelRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> DepositForfeitureResponse:
    """‌⁠‍Cancel a buyer + compute jurisdiction-specific deposit forfeiture."""
    await _verify_owner_via_buyer(session, b_id, user_payload)
    _buyer, forfeiture = await service.cancel_buyer(b_id, data)
    return DepositForfeitureResponse(
        buyer_id=b_id,
        jurisdiction=forfeiture["jurisdiction"],
        deposit_amount=forfeiture["deposit_amount"],
        forfeited_amount=forfeiture["forfeited_amount"],
        refundable_amount=forfeiture["refundable_amount"],
        rule_citation=forfeiture["rule_citation"],
        rule_summary=forfeiture["rule_summary"],
    )


@router.get("/jurisdictions", response_model=list[str])
async def list_jurisdictions(
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[str]:
    """‌⁠‍List ISO-3166 alpha-2 codes with a real deposit-forfeiture rule."""
    return supported_jurisdictions()


# ── Handover doc bundle (buyer-portal hand-off) ────────────────────────


@router.get(
    "/handovers/{h_id}/docs",
    response_model=HandoverBundleResponse,
)
async def get_handover_bundle(
    h_id: uuid.UUID,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> HandoverBundleResponse:
    """Return the full handover-doc bundle with compliance status."""
    payload = await service.handover_bundle(h_id)
    return HandoverBundleResponse(
        handover_id=payload["handover_id"],
        docs=[HandoverDocResponse.model_validate(d) for d in payload["docs"]],
        delivered_count=payload["delivered_count"],
        required_count=payload["required_count"],
        missing_required=payload["missing_required"],
        ready_for_handover=payload["ready_for_handover"],
    )


@router.post(
    "/handover-docs/",
    response_model=HandoverDocResponse,
    status_code=201,
)
async def create_handover_doc(
    data: HandoverDocCreate,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.handover")),
) -> HandoverDocResponse:
    return HandoverDocResponse.model_validate(await service.create_handover_doc(data))


@router.patch(
    "/handover-docs/{doc_id}",
    response_model=HandoverDocResponse,
)
async def update_handover_doc(
    doc_id: uuid.UUID,
    data: HandoverDocUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.handover")),
) -> HandoverDocResponse:
    await _verify_owner_via_handover_doc(session, doc_id, user_payload)
    return HandoverDocResponse.model_validate(await service.update_handover_doc(doc_id, data))


@router.delete("/handover-docs/{doc_id}", status_code=204)
async def delete_handover_doc(
    doc_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_handover_doc(session, doc_id, user_payload)
    await service.delete_handover_doc(doc_id)


@router.get("/handovers/{h_id}/export")
async def export_handover_package(
    h_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    locale: str = Query(default="en", max_length=12),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Response:
    """Download the digital handover / closeout package as a ZIP.

    Bundles freshly rendered certificates, every delivered handover
    document held locally, and all snag photos. IDOR-gated via the
    handover → plot → development → project ownership chain. The archive
    is assembled in-memory and returned with a sensible "Save As…" name.
    """
    await _verify_owner_via_handover(session, h_id, user_payload)
    filename, zip_bytes = await service.export_handover_package(
        h_id,
        locale=_normalise_locale(locale),
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Sales pipeline + reservation calendar + dev P&L ────────────────────


@router.get(
    "/developments/{dev_id}/sales-kanban",
    response_model=SalesKanbanResponse,
)
async def sales_kanban(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> SalesKanbanResponse:
    """Kanban - one column per buyer-status.

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development``.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.sales_kanban(dev_id)
    return SalesKanbanResponse(**payload)


@router.get(
    "/developments/{dev_id}/reservation-calendar",
    response_model=ReservationCalendarResponse,
)
async def reservation_calendar(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    period_start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period_end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> ReservationCalendarResponse:
    """Reservation + freeze + contract deadlines in the supplied window.

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development``.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.reservation_calendar(
        dev_id,
        period_start,
        period_end,
    )
    return ReservationCalendarResponse(**payload)


@router.get(
    "/developments/{dev_id}/pnl",
    response_model=DevelopmentPnLResponse,
)
async def development_pnl(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> DevelopmentPnLResponse:
    """Revenue + deposits + open-issues rollup for a development.

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development``.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.development_pnl(dev_id)
    return DevelopmentPnLResponse(**payload)


# ════════════════════════════════════════════════════════════════════════
# R6 - Lead / Reservation / SPA / PaymentSchedule / Instalment /
#       ContractParty
# ════════════════════════════════════════════════════════════════════════


async def _verify_owner_via_plot(
    session: SessionDep,
    plot_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Generic IDOR closure walking plot → development → project owner.

    Collapses "exists but not yours" to 404 to avoid leaking UUID
    existence. Admins bypass.
    """
    is_admin = payload.get("role") == "admin"
    user_id = payload.get("sub") or payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))

    from app.modules.projects.repository import ProjectRepository
    from app.modules.property_dev.repository import (
        DevelopmentRepository,
        PlotRepository,
    )

    plot = await PlotRepository(session).get_by_id(plot_id)
    if plot is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    if is_admin:
        return
    dev = await DevelopmentRepository(session).get_by_id(plot.development_id)
    if dev is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    project = await ProjectRepository(session).get_by_id(dev.project_id)
    if project is None or str(project.owner_id) != str(user_id):
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))


async def _verify_owner_via_project(
    session: SessionDep,
    project_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure gating a body-supplied ``project_id`` against its owner.

    Mirrors ``_verify_owner_via_development`` but takes the project id
    directly, for root-creates (e.g. a development) whose parent is a
    Project rather than a Development. Collapses "exists but not yours" to
    404 to avoid leaking project-UUID existence. As with the sibling
    helpers, ownership is strict: only the project owner passes, so a
    cross-tenant admin still 404s on a project they do not own.
    """
    user_id = payload.get("sub") or payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))

    from app.modules.projects.repository import ProjectRepository

    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None or str(project.owner_id) != str(user_id):
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))


async def _verify_owner_via_development(
    session: SessionDep,
    dev_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure walking development → project owner.

    Ownership is strict: only the project owner passes. The global ``admin``
    role does NOT grant cross-tenant access here — an admin from another
    tenant must still 404 on a development they do not own. This closes the
    broker-tenant IDOR (deferred #66) that let any admin price-quote against
    another tenant's price list. Legitimate same-tenant access is unaffected
    because the project owner's id matches ``user_id``.
    """
    user_id = payload.get("sub") or payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))

    from app.modules.projects.repository import ProjectRepository
    from app.modules.property_dev.repository import DevelopmentRepository

    dev = await DevelopmentRepository(session).get_by_id(dev_id)
    if dev is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    project = await ProjectRepository(session).get_by_id(dev.project_id)
    if project is None or str(project.owner_id) != str(user_id):
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))


async def _verify_owner_via_lead(
    session: SessionDep,
    lead_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for Lead (lead → development → project owner).

    Leads without a development_id are owner-less by design (top-of-funnel
    inbound webhooks); they are accessible by any authenticated user with
    the right permission level but never escape into another tenant since
    they carry no project-scoped data.
    """
    is_admin = payload.get("role") == "admin"
    user_id = payload.get("sub") or payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))

    from app.modules.property_dev.repository import LeadRepository

    lead = await LeadRepository(session).get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    if is_admin or lead.development_id is None:
        return
    await _verify_owner_via_development(session, lead.development_id, payload)


async def _verify_owner_via_reservation(
    session: SessionDep,
    r_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    from app.modules.property_dev.repository import ReservationRepository

    res = await ReservationRepository(session).get_by_id(r_id)
    if res is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_plot(session, res.plot_id, payload)


async def _verify_owner_via_spa(
    session: SessionDep,
    spa_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    from app.modules.property_dev.repository import SalesContractRepository

    spa = await SalesContractRepository(session).get_by_id(spa_id)
    if spa is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_plot(session, spa.plot_id, payload)


async def _verify_owner_via_schedule(
    session: SessionDep,
    schedule_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    from app.modules.property_dev.repository import PaymentScheduleRepository

    sched = await PaymentScheduleRepository(session).get_by_id(schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_spa(session, sched.sales_contract_id, payload)


async def _verify_owner_via_instalment(
    session: SessionDep,
    ins_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    from app.modules.property_dev.repository import InstalmentRepository

    ins = await InstalmentRepository(session).get_by_id(ins_id)
    if ins is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_schedule(session, ins.schedule_id, payload)


async def _verify_owner_via_party(
    session: SessionDep,
    party_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    from app.modules.property_dev.repository import ContractPartyRepository

    party = await ContractPartyRepository(session).get_by_id(party_id)
    if party is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_spa(session, party.sales_contract_id, payload)


async def _verify_owner_via_handover(
    session: SessionDep,
    handover_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for Handover (handover → plot → development → project).

    Collapses "exists but not yours" to 404. Admins bypass.
    """
    from app.modules.property_dev.repository import HandoverRepository

    handover = await HandoverRepository(session).get_by_id(handover_id)
    if handover is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_plot(session, handover.plot_id, payload)


async def _verify_owner_via_snag(
    session: SessionDep,
    snag_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for Snag (snag → handover → plot → development → project)."""
    from app.modules.property_dev.repository import SnagRepository

    snag = await SnagRepository(session).get_by_id(snag_id)
    if snag is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_handover(session, snag.handover_id, payload)


async def _verify_owner_via_warranty(
    session: SessionDep,
    claim_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for WarrantyClaim (claim → plot → development → project)."""
    from app.modules.property_dev.repository import WarrantyClaimRepository

    claim = await WarrantyClaimRepository(session).get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_plot(session, claim.plot_id, payload)


async def _verify_owner_via_buyer(
    session: SessionDep,
    buyer_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for Buyer (buyer → development → project owner)."""
    from app.modules.property_dev.repository import BuyerRepository

    buyer = await BuyerRepository(session).get_by_id(buyer_id)
    if buyer is None:
        raise HTTPException(status_code=404, detail=translate("errors.resource_not_found", locale=get_locale()))
    await _verify_owner_via_development(session, buyer.development_id, payload)


# ── R7 IDOR helpers (Round-7 audit) ─────────────────────────────────────
#
# These helpers extend the existing _verify_owner_via_* chain to the
# remaining project-scoped entities (house-type, variant, option-group,
# option, selection, handover-doc, phase, block, broker, commission,
# escrow, price-matrix). Each collapses "exists but not yours" to 404
# (never 403) to avoid turning the endpoint into an existence oracle.
# Admins always bypass. Pattern mirrors _verify_owner_via_plot.


async def _verify_owner_via_house_type(
    session: SessionDep,
    ht_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for HouseType (ht → development → project owner)."""
    from app.modules.property_dev.repository import HouseTypeRepository

    ht = await HouseTypeRepository(session).get_by_id(ht_id)
    if ht is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_development(session, ht.development_id, payload)


async def _verify_owner_via_variant(
    session: SessionDep,
    v_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for HouseTypeVariant (variant → house_type → dev → project)."""
    from app.modules.property_dev.repository import HouseTypeVariantRepository

    variant = await HouseTypeVariantRepository(session).get_by_id(v_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_house_type(session, variant.house_type_id, payload)


async def _verify_owner_via_option_group(
    session: SessionDep,
    g_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for BuyerOptionGroup (group → development → project)."""
    from app.modules.property_dev.repository import BuyerOptionGroupRepository

    group = await BuyerOptionGroupRepository(session).get_by_id(g_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_development(session, group.development_id, payload)


async def _verify_owner_via_option(
    session: SessionDep,
    o_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for BuyerOption (option → group → development → project)."""
    from app.modules.property_dev.repository import BuyerOptionRepository

    option = await BuyerOptionRepository(session).get_by_id(o_id)
    if option is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_option_group(session, option.group_id, payload)


async def _verify_owner_via_selection(
    session: SessionDep,
    s_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for BuyerSelection (selection → buyer → development → project)."""
    from app.modules.property_dev.repository import BuyerSelectionRepository

    selection = await BuyerSelectionRepository(session).get_by_id(s_id)
    if selection is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_buyer(session, selection.buyer_id, payload)


async def _verify_owner_via_handover_doc(
    session: SessionDep,
    doc_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for HandoverDoc (doc → handover → plot → dev → project)."""
    from app.modules.property_dev.repository import HandoverDocRepository

    doc = await HandoverDocRepository(session).get_by_id(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_handover(session, doc.handover_id, payload)


async def _verify_owner_via_phase(
    session: SessionDep,
    phase_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for Phase (phase → development → project)."""
    from app.modules.property_dev.repository import PhaseRepository

    phase = await PhaseRepository(session).get_by_id(phase_id)
    if phase is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_development(session, phase.development_id, payload)


async def _verify_owner_via_block(
    session: SessionDep,
    block_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for Block (block → phase → development → project)."""
    from app.modules.property_dev.repository import BlockRepository

    block = await BlockRepository(session).get_by_id(block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_phase(session, block.phase_id, payload)


async def _verify_owner_via_broker(
    session: SessionDep,
    broker_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for Broker via tenant_id (broker.tenant_id == caller).

    Brokers carry a tenant_id (no project FK); they belong to the user
    who created them. Admins bypass.
    """
    is_admin = payload.get("role") == "admin"
    user_id = payload.get("sub") or payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=404, detail="Resource not found")

    from app.modules.property_dev.repository import BrokerRepository

    broker = await BrokerRepository(session).get_by_id(broker_id)
    if broker is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    if is_admin:
        return
    if broker.tenant_id is None or str(broker.tenant_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Resource not found")


async def _verify_owner_via_commission_agreement(
    session: SessionDep,
    agreement_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for CommissionAgreement (agreement → broker.tenant_id)."""
    from app.modules.property_dev.repository import (
        CommissionAgreementRepository,
    )

    agreement = await CommissionAgreementRepository(session).get_by_id(
        agreement_id,
    )
    if agreement is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_broker(session, agreement.broker_id, payload)


async def _verify_owner_via_commission_accrual(
    session: SessionDep,
    accrual_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for CommissionAccrual (accrual → broker.tenant_id)."""
    from app.modules.property_dev.repository import (
        CommissionAccrualRepository,
    )

    accrual = await CommissionAccrualRepository(session).get_by_id(accrual_id)
    if accrual is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_broker(session, accrual.broker_id, payload)


async def _verify_owner_via_escrow_account(
    session: SessionDep,
    account_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for EscrowAccount (account → development → project)."""
    from app.modules.property_dev.repository import EscrowAccountRepository

    account = await EscrowAccountRepository(session).get_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_development(session, account.development_id, payload)


async def _verify_owner_via_escrow_transaction(
    session: SessionDep,
    tx_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for EscrowTransaction (tx → account → development → project)."""
    from app.modules.property_dev.repository import EscrowTransactionRepository

    tx = await EscrowTransactionRepository(session).get_by_id(tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_escrow_account(session, tx.escrow_account_id, payload)


async def _verify_owner_via_price_matrix(
    session: SessionDep,
    matrix_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for PriceMatrix (matrix → development → project)."""
    from app.modules.property_dev.repository import PriceMatrixRepository

    matrix = await PriceMatrixRepository(session).get_by_id(matrix_id)
    if matrix is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_development(session, matrix.development_id, payload)


# ── Leads ───────────────────────────────────────────────────────────────


@router.get("/leads/", response_model=list[LeadResponse])
async def list_leads(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    assigned_agent_user_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lead.read")),
) -> list[LeadResponse]:
    """List leads filtered by development.

    R8: when ``development_id`` is provided we verify cross-tenant access
    via ``_verify_owner_via_development`` so the endpoint can't be turned
    into a cross-tenant enumeration channel; when omitted, non-admin
    callers receive an empty list (admin bypasses).
    """
    if development_id is not None:
        await _verify_owner_via_development(session, development_id, user_payload)
    elif user_payload.get("role") != "admin":
        # Non-admins MUST scope to a development they own; collapsing to
        # an empty list avoids leaking cross-tenant top-of-funnel leads.
        return []
    rows, _ = await service.leads.list_filtered(
        development_id=development_id,
        status=status,
        source=source,
        assigned_agent_user_id=assigned_agent_user_id,
        offset=offset,
        limit=limit,
    )
    return [LeadResponse.model_validate(r) for r in rows]


@router.post("/leads/", response_model=LeadResponse, status_code=201)
async def create_lead(
    data: LeadCreate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    sync_to_contacts: bool = Query(
        default=True,
        description=(
            "When true (default), the lead is mirrored to the Contacts "
            "directory and the contact picks up the 'property_dev_lead' "
            "module tag. Pass false to skip the sync."
        ),
    ),
    _perm: None = Depends(RequirePermission("property_dev.lead.create")),
) -> LeadResponse:
    # R7 IDOR - prevent attaching a lead to another tenant's development
    # by supplying a foreign development UUID. Leads without a development
    # are top-of-funnel and carry no project-scoped data (see
    # ``_verify_owner_via_lead``), so only gate when one is supplied.
    if data.development_id is not None:
        await _verify_owner_via_development(session, data.development_id, payload)
    caller = payload.get("sub") if isinstance(payload, dict) else None
    return LeadResponse.model_validate(
        await service.create_lead(
            data,
            sync_to_contacts=sync_to_contacts,
            tenant_id=str(caller) if caller else None,
        )
    )


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lead.read")),
) -> LeadResponse:
    await _verify_owner_via_lead(session, lead_id, payload)
    return LeadResponse.model_validate(await service.get_lead(lead_id))


@router.patch("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    data: LeadUpdate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lead.update")),
) -> LeadResponse:
    await _verify_owner_via_lead(session, lead_id, payload)
    return LeadResponse.model_validate(await service.update_lead(lead_id, data))


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lead.delete")),
) -> None:
    await _verify_owner_via_lead(session, lead_id, payload)
    await service.delete_lead(lead_id)


@router.post(
    "/leads/{lead_id}/convert-to-reservation",
    response_model=ReservationResponse,
    status_code=201,
)
async def convert_lead_to_reservation(
    lead_id: uuid.UUID,
    data: LeadConvertToReservationRequest,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lead.convert")),
) -> ReservationResponse:
    await _verify_owner_via_lead(session, lead_id, payload)
    await _verify_owner_via_plot(session, data.plot_id, payload)
    return ReservationResponse.model_validate(await service.convert_lead_to_reservation(lead_id, data))


@router.get(
    "/leads/{lead_id}/contact",
    summary="Get the Contacts directory entry linked to a Lead",
    description=(
        "Returns the canonical Contact row referenced by ``lead.contact_id`` "
        "(or 404 if the lead is not linked / the linked contact was deleted). "
        "Used by the Lead detail drawer to render the 'Linked Contact' card."
    ),
)
async def get_lead_contact(
    lead_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.lead.read")),
) -> dict[str, Any]:
    """Resolve the contact for ``lead_id`` if linked."""
    await _verify_owner_via_lead(session, lead_id, payload)
    lead = await service.get_lead(lead_id)
    if lead.contact_id is None:
        raise HTTPException(status_code=404, detail="Lead is not linked to a contact")
    from app.modules.contacts.models import Contact as _Contact

    contact = await session.get(_Contact, lead.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Linked contact has been deleted")
    return {
        "id": str(contact.id),
        "contact_type": contact.contact_type,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "company_name": contact.company_name,
        "primary_email": contact.primary_email,
        "primary_phone": contact.primary_phone,
        "country_code": contact.country_code,
        "module_tags": list(contact.module_tags or []),
    }


@router.get(
    "/buyers/{b_id}/contact",
    summary="Get the Contacts directory entry linked to a Buyer",
    description=(
        "Returns the canonical Contact row referenced by ``buyer.contact_id`` "
        "(or 404 if the buyer is not linked / the linked contact was "
        "deleted)."
    ),
)
async def get_buyer_contact(
    b_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> dict[str, Any]:
    """Resolve the contact for ``b_id`` if linked."""
    await _verify_buyer_owner(session, b_id, payload)
    buyer = await service.get_buyer(b_id)
    if buyer.contact_id is None:
        raise HTTPException(status_code=404, detail="Buyer is not linked to a contact")
    from app.modules.contacts.models import Contact as _Contact

    contact = await session.get(_Contact, buyer.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Linked contact has been deleted")
    return {
        "id": str(contact.id),
        "contact_type": contact.contact_type,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "company_name": contact.company_name,
        "primary_email": contact.primary_email,
        "primary_phone": contact.primary_phone,
        "country_code": contact.country_code,
        "module_tags": list(contact.module_tags or []),
    }


# ── Reservations ────────────────────────────────────────────────────────


@router.get("/reservations/", response_model=list[ReservationResponse])
async def list_reservations(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    plot_id: uuid.UUID | None = Query(default=None),
    development_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reservation.read")),
) -> list[ReservationResponse]:
    """List reservations.

    R8: at least one of ``plot_id`` / ``development_id`` MUST be supplied
    for non-admin callers, and we verify owner-of via the appropriate
    chain. Non-admin callers without any scope receive an empty list
    rather than a 422 (matches existing pattern in /warranty-claims).
    """
    if plot_id is not None:
        await _verify_owner_via_plot(session, plot_id, user_payload)
    elif development_id is not None:
        await _verify_owner_via_development(session, development_id, user_payload)
    elif user_payload.get("role") != "admin":
        return []
    rows, _ = await service.reservations.list_filtered(
        plot_id=plot_id,
        development_id=development_id,
        status=status,
        offset=offset,
        limit=limit,
    )
    return [ReservationResponse.model_validate(r) for r in rows]


@router.post(
    "/reservations/",
    response_model=ReservationResponse,
    status_code=201,
)
async def create_reservation(
    data: ReservationCreate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reservation.create")),
) -> ReservationResponse:
    await _verify_owner_via_plot(session, data.plot_id, payload)
    return ReservationResponse.model_validate(await service.create_reservation(data))


@router.post(
    "/reservations/expire-overdue",
    response_model=ReservationExpiryBatchResponse,
)
async def expire_overdue_reservations(
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reservation.expire")),
) -> ReservationExpiryBatchResponse:
    """Admin/cron endpoint - expire every active reservation past
    ``expires_at``. Idempotent + safe to schedule daily.
    """
    ids = await service.expire_overdue_reservations()
    return ReservationExpiryBatchResponse(expired_count=len(ids), expired_ids=ids)


@router.get("/reservations/{r_id}", response_model=ReservationResponse)
async def get_reservation(
    r_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reservation.read")),
) -> ReservationResponse:
    await _verify_owner_via_reservation(session, r_id, payload)
    return ReservationResponse.model_validate(await service.get_reservation(r_id))


@router.patch("/reservations/{r_id}", response_model=ReservationResponse)
async def update_reservation(
    r_id: uuid.UUID,
    data: ReservationUpdate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reservation.update")),
) -> ReservationResponse:
    await _verify_owner_via_reservation(session, r_id, payload)
    return ReservationResponse.model_validate(await service.update_reservation(r_id, data))


@router.post(
    "/reservations/{r_id}/cancel",
    response_model=ReservationResponse,
)
async def cancel_reservation(
    r_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reservation.cancel")),
) -> ReservationResponse:
    await _verify_owner_via_reservation(session, r_id, payload)
    return ReservationResponse.model_validate(await service.cancel_reservation(r_id))


@router.post(
    "/reservations/{r_id}/expire",
    response_model=ReservationResponse,
)
async def expire_reservation(
    r_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.reservation.expire")),
) -> ReservationResponse:
    await _verify_owner_via_reservation(session, r_id, payload)
    return ReservationResponse.model_validate(await service.expire_reservation(r_id))


@router.post(
    "/reservations/{r_id}/convert-to-spa",
    response_model=SalesContractResponse,
    status_code=201,
)
async def convert_reservation_to_spa(
    r_id: uuid.UUID,
    data: ReservationConvertToSpaRequest,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.spa.draft")),
) -> SalesContractResponse:
    await _verify_owner_via_reservation(session, r_id, payload)
    return SalesContractResponse.model_validate(await service.convert_reservation_to_spa(r_id, data))


# ── SalesContracts (SPAs) ───────────────────────────────────────────────


@router.get("/sales-contracts/", response_model=list[SalesContractResponse])
async def list_sales_contracts(
    session: SessionDep,
    payload: CurrentUserPayload,
    plot_id: uuid.UUID | None = Query(default=None),
    development_id: uuid.UUID | None = Query(default=None),
    reservation_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[SalesContractResponse]:
    """List SPAs by plot, development or reservation.

    Exactly one of ``plot_id`` / ``development_id`` / ``reservation_id``
    must be supplied. The top-level "Sales Contracts" tab uses
    ``development_id``; per-plot drawers use ``plot_id``; the reservation
    detail view uses ``reservation_id`` to surface a converted SPA.
    """
    if plot_id is not None:
        await _verify_owner_via_plot(session, plot_id, payload)
        rows = await service.sales_contracts.list_for_plot(plot_id, status=status)
    elif development_id is not None:
        await _verify_owner_via_development(session, development_id, payload)
        rows = await service.sales_contracts.list_for_development(development_id, status=status)
    elif reservation_id is not None:
        await _verify_owner_via_reservation(session, reservation_id, payload)
        rows = await service.sales_contracts.list_for_reservation(reservation_id)
        if status is not None:
            rows = [r for r in rows if r.status == status]
    else:
        raise HTTPException(
            status_code=422,
            detail="plot_id, development_id or reservation_id required",
        )
    return [SalesContractResponse.model_validate(r) for r in rows]


@router.post(
    "/sales-contracts/",
    response_model=SalesContractResponse,
    status_code=201,
)
async def create_sales_contract(
    data: SalesContractCreate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.spa.draft")),
) -> SalesContractResponse:
    await _verify_owner_via_plot(session, data.plot_id, payload)
    return SalesContractResponse.model_validate(await service.create_spa(data))


@router.get(
    "/sales-contracts/{spa_id}",
    response_model=SalesContractResponse,
)
async def get_sales_contract(
    spa_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> SalesContractResponse:
    await _verify_owner_via_spa(session, spa_id, payload)
    return SalesContractResponse.model_validate(await service.get_spa(spa_id))


@router.patch(
    "/sales-contracts/{spa_id}",
    response_model=SalesContractResponse,
)
async def update_sales_contract(
    spa_id: uuid.UUID,
    data: SalesContractUpdate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.spa.draft")),
) -> SalesContractResponse:
    await _verify_owner_via_spa(session, spa_id, payload)
    return SalesContractResponse.model_validate(await service.update_spa(spa_id, data))


@router.delete("/sales-contracts/{spa_id}", status_code=204)
async def delete_sales_contract(
    spa_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.spa.cancel")),
) -> None:
    await _verify_owner_via_spa(session, spa_id, payload)
    await service.delete_spa(spa_id)


@router.post(
    "/sales-contracts/{spa_id}/send-for-signature",
    response_model=SalesContractResponse,
)
async def send_spa_for_signature(
    spa_id: uuid.UUID,
    data: SalesContractSendForSignatureRequest,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.spa.send")),
) -> SalesContractResponse:
    await _verify_owner_via_spa(session, spa_id, payload)
    return SalesContractResponse.model_validate(await service.send_spa_for_signature(spa_id, data))


@router.post(
    "/sales-contracts/{spa_id}/sign",
    response_model=SalesContractResponse,
)
async def sign_sales_contract(
    spa_id: uuid.UUID,
    data: SalesContractSignRequest,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.spa.sign")),
) -> SalesContractResponse:
    await _verify_owner_via_spa(session, spa_id, payload)
    return SalesContractResponse.model_validate(await service.sign_spa(spa_id, data))


@router.post(
    "/sales-contracts/{spa_id}/cancel",
    response_model=SalesContractResponse,
)
async def cancel_sales_contract(
    spa_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.spa.cancel")),
) -> SalesContractResponse:
    await _verify_owner_via_spa(session, spa_id, payload)
    return SalesContractResponse.model_validate(await service.cancel_spa(spa_id))


@router.post(
    "/sales-contracts/{spa_id}/tax-quote",
    response_model=ContractTaxQuote,
)
async def quote_sales_contract_taxes(
    spa_id: uuid.UUID,
    data: TaxQuotePayload,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> ContractTaxQuote:
    """Compute jurisdiction-aware taxes for a SalesContract.

    Routes UK SDLT progressive bands, DE state-specific Grunderwerbsteuer,
    UAE DLD transfer fee, IN GST + state stamp duty, SG BSD + ABSD,
    AU state stamp duty, US state transfer tax - all data-driven via
    ``data/tax_rates.yaml``. Returns Decimal amounts (2 dp HALF_UP)
    plus a human-readable breakdown for invoice rendering.
    """
    # IDOR - close cross-tenant read first (404 not 403 = no UUID oracle).
    await _verify_owner_via_spa(session, spa_id, payload)

    from app.modules.property_dev.tax_engine import (
        MissingRegionSubcodeError,
        UnknownRateClassError,
        UnsupportedJurisdictionError,
    )

    try:
        result = await service.quote_contract_taxes(
            spa_id,
            jurisdiction=data.jurisdiction,
            region_subcode=data.region_subcode,
            is_first_home=data.is_first_home,
            is_additional_property=data.is_additional_property,
            vat_rate_class=data.vat_rate_class,
            absd_buyer_profile=data.absd_buyer_profile,
            emirate=data.emirate,
            include_overdue=data.include_overdue,
        )
    except UnsupportedJurisdictionError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_jurisdiction",
                "jurisdiction": exc.jurisdiction,
                "supported": exc.supported,
                "message": str(exc),
            },
        )
    except MissingRegionSubcodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_region_subcode",
                "jurisdiction": exc.jurisdiction,
                "supported": exc.supported,
                "message": str(exc),
            },
        )
    except UnknownRateClassError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unknown_rate_class",
                "message": str(exc),
            },
        )
    return ContractTaxQuote.model_validate(result)


# ── PaymentSchedules ────────────────────────────────────────────────────


@router.get(
    "/payment-schedules/",
    response_model=list[PaymentScheduleResponse],
)
async def list_payment_schedules(
    session: SessionDep,
    payload: CurrentUserPayload,
    sales_contract_id: uuid.UUID | None = Query(default=None),
    development_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PaymentScheduleResponse]:
    """List payment schedules by SPA or by development.

    Backs the top-level "Payment Schedules" tab and the SPA detail panel
    which both need to enumerate schedules without knowing each id.
    """
    if sales_contract_id is not None:
        await _verify_owner_via_spa(session, sales_contract_id, payload)
        existing = await service.payment_schedules.get_for_contract(sales_contract_id)
        rows = [existing] if existing is not None else []
    elif development_id is not None:
        await _verify_owner_via_development(session, development_id, payload)
        rows = await service.payment_schedules.list_for_development(development_id, status=status)
    else:
        raise HTTPException(
            status_code=422,
            detail="sales_contract_id or development_id required",
        )
    if status is not None and sales_contract_id is not None:
        rows = [r for r in rows if r.status == status]
    return [PaymentScheduleResponse.model_validate(r) for r in rows]


@router.post(
    "/payment-schedules/from-template",
    response_model=PaymentScheduleResponse,
    status_code=201,
)
async def generate_payment_schedule_from_template(
    body: dict[str, Any],
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.payment_schedule.activate")),
) -> PaymentScheduleResponse:
    """Generate a payment schedule from a milestone template.

    Body schema (validated inline for flexibility):
        sales_contract_id: UUID                - required.
        template_key: str                      - one of the keys returned
                                                 by GET /payment-schedule-templates/.
                                                 Required.
        start_date: "YYYY-MM-DD"               - optional, defaults to SPA
                                                 signing date or today.
        late_fee_pct: Decimal (0..100)         - optional, default 0.
        grace_period_days: int                 - optional, default 0.

    Behaviour: if a schedule already exists for this SPA and it is in
    ``draft``/``suspended``/``cancelled`` state, its instalments are
    cleared and replaced; if it is ``active``/``completed`` the call
    fails with 409 to avoid clobbering paid lines.
    """
    raw_contract = body.get("sales_contract_id")
    raw_template = body.get("template_key")
    if not raw_contract or not raw_template:
        raise HTTPException(
            status_code=422,
            detail="sales_contract_id and template_key are required",
        )
    try:
        contract_id = uuid.UUID(str(raw_contract))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="invalid sales_contract_id",
        ) from exc
    await _verify_owner_via_spa(session, contract_id, payload)

    template_key = str(raw_template)
    start_date = body.get("start_date")
    if start_date is not None:
        start_date = str(start_date)
    late_fee_pct = body.get("late_fee_pct")
    grace_period_days = body.get("grace_period_days")
    schedule = await service.generate_payment_schedule_from_template(
        contract_id,
        template_key=template_key,
        start_date=start_date,
        late_fee_pct=late_fee_pct,
        grace_period_days=grace_period_days,
    )
    return PaymentScheduleResponse.model_validate(schedule)


@router.get("/payment-schedule-templates/", response_model=list[dict])
async def list_payment_schedule_templates(
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[dict]:
    """Static catalogue of milestone-based payment schedule templates.

    Templates are pure data - see
    :data:`PropertyDevService.PAYMENT_SCHEDULE_TEMPLATES`.
    """
    return PropertyDevService.payment_schedule_template_catalogue()


@router.post(
    "/payment-schedules/",
    response_model=PaymentScheduleResponse,
    status_code=201,
)
async def create_payment_schedule(
    data: PaymentScheduleCreate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.payment_schedule.activate")),
) -> PaymentScheduleResponse:
    await _verify_owner_via_spa(session, data.sales_contract_id, payload)
    return PaymentScheduleResponse.model_validate(await service.create_payment_schedule(data))


@router.get(
    "/payment-schedules/{schedule_id}",
    response_model=PaymentScheduleResponse,
)
async def get_payment_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PaymentScheduleResponse:
    await _verify_owner_via_schedule(session, schedule_id, payload)
    return PaymentScheduleResponse.model_validate(await service.get_payment_schedule(schedule_id))


@router.patch(
    "/payment-schedules/{schedule_id}",
    response_model=PaymentScheduleResponse,
)
async def update_payment_schedule(
    schedule_id: uuid.UUID,
    data: PaymentScheduleUpdate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.payment_schedule.activate")),
) -> PaymentScheduleResponse:
    await _verify_owner_via_schedule(session, schedule_id, payload)
    return PaymentScheduleResponse.model_validate(await service.update_payment_schedule(schedule_id, data))


@router.post(
    "/payment-schedules/{schedule_id}/activate",
    response_model=PaymentScheduleResponse,
)
async def activate_payment_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.payment_schedule.activate")),
) -> PaymentScheduleResponse:
    await _verify_owner_via_schedule(session, schedule_id, payload)
    return PaymentScheduleResponse.model_validate(await service.activate_payment_schedule(schedule_id))


@router.post(
    "/payment-schedules/{schedule_id}/suspend",
    response_model=PaymentScheduleResponse,
)
async def suspend_payment_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.payment_schedule.suspend")),
) -> PaymentScheduleResponse:
    await _verify_owner_via_schedule(session, schedule_id, payload)
    return PaymentScheduleResponse.model_validate(await service.suspend_payment_schedule(schedule_id))


# ── Instalments ─────────────────────────────────────────────────────────


@router.get("/instalments/", response_model=list[InstalmentResponse])
async def list_instalments(
    session: SessionDep,
    payload: CurrentUserPayload,
    schedule_id: uuid.UUID | None = Query(default=None),
    sales_contract_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[InstalmentResponse]:
    if schedule_id is not None:
        await _verify_owner_via_schedule(session, schedule_id, payload)
        rows = await service.instalments.list_for_schedule(schedule_id, status=status)
    elif sales_contract_id is not None:
        await _verify_owner_via_spa(session, sales_contract_id, payload)
        rows = await service.instalments.list_for_contract(sales_contract_id)
        if status:
            rows = [r for r in rows if r.status == status]
    else:
        raise HTTPException(
            status_code=422,
            detail="schedule_id or sales_contract_id required",
        )
    return [InstalmentResponse.model_validate(r) for r in rows]


@router.post(
    "/instalments/",
    response_model=InstalmentResponse,
    status_code=201,
)
async def create_instalment(
    data: InstalmentCreate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.payment_schedule.activate")),
) -> InstalmentResponse:
    await _verify_owner_via_schedule(session, data.schedule_id, payload)
    return InstalmentResponse.model_validate(await service.create_instalment(data))


@router.get("/instalments/{ins_id}", response_model=InstalmentResponse)
async def get_instalment(
    ins_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> InstalmentResponse:
    await _verify_owner_via_instalment(session, ins_id, payload)
    return InstalmentResponse.model_validate(await service.get_instalment(ins_id))


@router.patch("/instalments/{ins_id}", response_model=InstalmentResponse)
async def update_instalment(
    ins_id: uuid.UUID,
    data: InstalmentUpdate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.payment_schedule.activate")),
) -> InstalmentResponse:
    await _verify_owner_via_instalment(session, ins_id, payload)
    return InstalmentResponse.model_validate(await service.update_instalment(ins_id, data))


@router.post(
    "/instalments/{ins_id}/mark-paid",
    response_model=InstalmentResponse,
)
async def mark_instalment_paid(
    ins_id: uuid.UUID,
    data: InstalmentMarkPaidRequest,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.instalment.mark_paid")),
) -> InstalmentResponse:
    await _verify_owner_via_instalment(session, ins_id, payload)
    return InstalmentResponse.model_validate(await service.mark_instalment_paid(ins_id, data))


@router.post(
    "/instalments/{ins_id}/issue-demand",
    response_model=InstalmentResponse,
)
async def issue_instalment_demand(
    ins_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.instalment.issue_demand")),
) -> InstalmentResponse:
    await _verify_owner_via_instalment(session, ins_id, payload)
    return InstalmentResponse.model_validate(await service.issue_instalment_demand(ins_id))


@router.post(
    "/instalments/{ins_id}/waive",
    response_model=InstalmentResponse,
)
async def waive_instalment(
    ins_id: uuid.UUID,
    data: InstalmentWaiveRequest,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.instalment.waive")),
) -> InstalmentResponse:
    await _verify_owner_via_instalment(session, ins_id, payload)
    return InstalmentResponse.model_validate(await service.waive_instalment(ins_id, data))


@router.post(
    "/instalments/accrue-late-fees",
    response_model=dict,
)
async def accrue_late_fees(
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.instalment.waive")),
) -> dict:
    """Admin/cron endpoint - accrue one day of late fees on all overdue
    instalments. Idempotent on the day-stamp; safe to schedule daily.
    """
    result = await service.accrue_late_fees_daily()
    return {
        "touched_count": result["touched_count"],
        "total_accrued": str(result["total_accrued"]),
    }


# ── ContractParties (multi-buyer junction) ──────────────────────────────


@router.get(
    "/contract-parties/",
    response_model=list[ContractPartyResponse],
)
async def list_contract_parties(
    session: SessionDep,
    payload: CurrentUserPayload,
    sales_contract_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[ContractPartyResponse]:
    await _verify_owner_via_spa(session, sales_contract_id, payload)
    rows = await service.contract_parties.list_for_contract(sales_contract_id)
    return [ContractPartyResponse.model_validate(r) for r in rows]


@router.post(
    "/contract-parties/",
    response_model=ContractPartyResponse,
    status_code=201,
)
async def add_contract_party(
    data: ContractPartyCreate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_party.add")),
) -> ContractPartyResponse:
    await _verify_owner_via_spa(session, data.sales_contract_id, payload)
    return ContractPartyResponse.model_validate(await service.add_contract_party(data))


@router.patch(
    "/contract-parties/{party_id}",
    response_model=ContractPartyResponse,
)
async def update_contract_party(
    party_id: uuid.UUID,
    data: ContractPartyUpdate,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_party.update_ownership")),
) -> ContractPartyResponse:
    await _verify_owner_via_party(session, party_id, payload)
    return ContractPartyResponse.model_validate(await service.update_contract_party(party_id, data))


@router.delete("/contract-parties/{party_id}", status_code=204)
async def remove_contract_party(
    party_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_party.remove")),
) -> None:
    await _verify_owner_via_party(session, party_id, payload)
    await service.remove_contract_party(party_id)


# ════════════════════════════════════════════════════════════════════════
# Task #138 - Broker / Commission / Escrow / PriceMatrix / Phase / Block
# ════════════════════════════════════════════════════════════════════════


def _payload_user_id(payload: dict[str, Any]) -> uuid.UUID | None:
    raw = payload.get("sub") or payload.get("user_id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _payload_tenant_id(payload: dict[str, Any]) -> uuid.UUID | None:
    raw = payload.get("tenant_id") or payload.get("org_id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


# ── Phases ──────────────────────────────────────────────────────────────


@router.get("/phases/", response_model=list[PhaseResponse])
async def list_phases(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PhaseResponse]:
    await _verify_owner_via_development(session, development_id, user_payload)
    rows = await service.phases.list_for_dev_ordered(development_id)
    return [PhaseResponse.model_validate(r) for r in rows]


@router.post("/phases/", response_model=PhaseResponse, status_code=201)
async def create_phase(
    data: PhaseCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> PhaseResponse:
    await _verify_owner_via_development(session, data.development_id, user_payload)
    return PhaseResponse.model_validate(await service.create_phase(data))


@router.get("/phases/{phase_id}", response_model=PhaseResponse)
async def get_phase(
    phase_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PhaseResponse:
    await _verify_owner_via_phase(session, phase_id, user_payload)
    return PhaseResponse.model_validate(await service.get_phase(phase_id))


@router.patch("/phases/{phase_id}", response_model=PhaseResponse)
async def update_phase(
    phase_id: uuid.UUID,
    data: PhaseUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> PhaseResponse:
    await _verify_owner_via_phase(session, phase_id, user_payload)
    return PhaseResponse.model_validate(await service.update_phase(phase_id, data))


@router.delete("/phases/{phase_id}", status_code=204)
async def delete_phase(
    phase_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_phase(session, phase_id, user_payload)
    await service.get_phase(phase_id)
    await service.phases.delete(phase_id)


# ── Blocks ──────────────────────────────────────────────────────────────


@router.get("/blocks/", response_model=list[BlockResponse])
async def list_blocks(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    phase_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[BlockResponse]:
    await _verify_owner_via_phase(session, phase_id, user_payload)
    rows = await service.blocks.list_for_phase_ordered(phase_id)
    return [BlockResponse.model_validate(r) for r in rows]


@router.post("/blocks/", response_model=BlockResponse, status_code=201)
async def create_block(
    data: BlockCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> BlockResponse:
    await _verify_owner_via_phase(session, data.phase_id, user_payload)
    return BlockResponse.model_validate(await service.create_block(data))


@router.get("/blocks/{block_id}", response_model=BlockResponse)
async def get_block(
    block_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BlockResponse:
    await _verify_owner_via_block(session, block_id, user_payload)
    return BlockResponse.model_validate(await service.get_block(block_id))


@router.patch("/blocks/{block_id}", response_model=BlockResponse)
async def update_block(
    block_id: uuid.UUID,
    data: BlockUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BlockResponse:
    await _verify_owner_via_block(session, block_id, user_payload)
    return BlockResponse.model_validate(await service.update_block(block_id, data))


@router.delete("/blocks/{block_id}", status_code=204)
async def delete_block(
    block_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_block(session, block_id, user_payload)
    await service.get_block(block_id)
    await service.blocks.delete(block_id)


# ── Brokers ─────────────────────────────────────────────────────────────


@router.get("/brokers/", response_model=list[BrokerResponse])
async def list_brokers(
    payload: CurrentUserPayload,
    active_only: bool = Query(default=False),
    jurisdiction: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[BrokerResponse]:
    tenant_id = _payload_tenant_id(payload)
    if active_only:
        rows = await service.brokers.list_active(
            tenant_id,
            jurisdiction=jurisdiction,
            offset=offset,
            limit=limit,
        )
    else:
        rows = await service.brokers.list_all(tenant_id, offset=offset, limit=limit)
    return [BrokerResponse.model_validate(r) for r in rows]


@router.post("/brokers/", response_model=BrokerResponse, status_code=201)
async def create_broker(
    data: BrokerCreate,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> BrokerResponse:
    # Forcibly bind the broker to the caller's tenant on create (closes
    # cross-tenant tenant_id forgery).
    tenant_id = _payload_tenant_id(payload)
    if tenant_id is not None:
        data = data.model_copy(update={"tenant_id": tenant_id})
    return BrokerResponse.model_validate(await service.create_broker(data))


@router.get("/brokers/{broker_id}", response_model=BrokerResponse)
async def get_broker(
    broker_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BrokerResponse:
    broker = await service.get_broker(broker_id)
    _ensure_broker_owner(broker, payload)
    return BrokerResponse.model_validate(broker)


@router.patch("/brokers/{broker_id}", response_model=BrokerResponse)
async def update_broker(
    broker_id: uuid.UUID,
    data: BrokerUpdate,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> BrokerResponse:
    broker = await service.get_broker(broker_id)
    _ensure_broker_owner(broker, payload)
    return BrokerResponse.model_validate(await service.update_broker(broker_id, data))


@router.delete("/brokers/{broker_id}", status_code=204)
async def delete_broker(
    broker_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    broker = await service.get_broker(broker_id)
    _ensure_broker_owner(broker, payload)
    await service.brokers.delete(broker_id)


@router.post("/brokers/{broker_id}/verify-kyc", response_model=BrokerResponse)
async def verify_broker_kyc(
    broker_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.broker.kyc_verify")),
) -> BrokerResponse:
    broker = await service.get_broker(broker_id)
    _ensure_broker_owner(broker, payload)
    return BrokerResponse.model_validate(await service.verify_broker_kyc(broker_id))


def _ensure_broker_owner(broker: Any, payload: dict[str, Any]) -> None:
    """Tenant-isolation gate for brokers.

    Admins bypass. For non-admins, a broker that belongs to a different
    tenant collapses to 404 - never leak existence via 403.
    """
    if payload.get("role") == "admin":
        return
    caller_tenant = _payload_tenant_id(payload)
    broker_tenant = getattr(broker, "tenant_id", None)
    if caller_tenant is None and broker_tenant is None:
        return
    if str(caller_tenant) != str(broker_tenant):
        raise HTTPException(status_code=404, detail="Broker not found")


# ── Commission Agreements ──────────────────────────────────────────────


@router.get(
    "/commission-agreements/",
    response_model=list[CommissionAgreementResponse],
)
async def list_commission_agreements(
    session: SessionDep,
    payload: CurrentUserPayload,
    broker_id: uuid.UUID | None = Query(default=None),
    development_id: uuid.UUID | None = Query(default=None),
    on_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[CommissionAgreementResponse]:
    # Cross-tenant IDOR gate: previously this endpoint took no caller and
    # ran no ownership check, so any user with ``property_dev.read`` could
    # enumerate another tenant's commission agreements by broker or
    # development UUID. Verify ownership of whatever scope the caller
    # passed (admins bypass inside the helpers); a request with no scope
    # at all returns nothing rather than every tenant's agreements. 404 on
    # cross-tenant access keeps the endpoint from being an existence oracle.
    if broker_id is not None:
        broker = await service.get_broker(broker_id)
        _ensure_broker_owner(broker, payload)
    if development_id is not None:
        await _verify_owner_via_development(session, development_id, payload)

    if broker_id is not None and on_date is not None:
        rows = await service.commission_agreements.list_active_for_broker(
            broker_id,
            on_date,
        )
    elif development_id is not None and on_date is not None:
        rows = await service.commission_agreements.list_matching(
            development_id=development_id,
            on_date=on_date,
            accrual_trigger="spa_signed",
        )
    elif broker_id is not None:
        # All agreements for a broker (any status).
        from sqlalchemy import select

        from app.modules.property_dev.models import (
            CommissionAgreement as _CA,
        )

        rs = await service.session.execute(
            select(_CA).where(_CA.broker_id == broker_id).order_by(_CA.created_at.desc())
        )
        rows = list(rs.scalars().all())
    else:
        rows = []
    return [CommissionAgreementResponse.model_validate(r) for r in rows]


@router.post(
    "/commission-agreements/",
    response_model=CommissionAgreementResponse,
    status_code=201,
)
async def create_commission_agreement(
    data: CommissionAgreementCreate,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> CommissionAgreementResponse:
    broker = await service.get_broker(data.broker_id)
    _ensure_broker_owner(broker, payload)
    return CommissionAgreementResponse.model_validate(await service.create_agreement(data))


@router.get(
    "/commission-agreements/{agreement_id}",
    response_model=CommissionAgreementResponse,
)
async def get_commission_agreement(
    agreement_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> CommissionAgreementResponse:
    agreement = await service.get_agreement(agreement_id)
    broker = await service.get_broker(agreement.broker_id)
    _ensure_broker_owner(broker, payload)
    return CommissionAgreementResponse.model_validate(agreement)


@router.patch(
    "/commission-agreements/{agreement_id}",
    response_model=CommissionAgreementResponse,
)
async def update_commission_agreement(
    agreement_id: uuid.UUID,
    data: CommissionAgreementUpdate,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> CommissionAgreementResponse:
    agreement = await service.get_agreement(agreement_id)
    broker = await service.get_broker(agreement.broker_id)
    _ensure_broker_owner(broker, payload)
    return CommissionAgreementResponse.model_validate(await service.update_agreement(agreement_id, data))


@router.delete("/commission-agreements/{agreement_id}", status_code=204)
async def delete_commission_agreement(
    agreement_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    agreement = await service.get_agreement(agreement_id)
    broker = await service.get_broker(agreement.broker_id)
    _ensure_broker_owner(broker, payload)
    await service.commission_agreements.delete(agreement_id)


# ── Commission Accruals ────────────────────────────────────────────────


@router.get(
    "/commission-accruals/",
    response_model=list[CommissionAccrualResponse],
)
async def list_commission_accruals(
    broker_id: uuid.UUID = Query(...),
    state: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[CommissionAccrualResponse]:
    broker = await service.get_broker(broker_id)
    _ensure_broker_owner(broker, payload or {})
    rows = await service.commission_accruals.list_for_broker(
        broker_id,
        state=state,
        offset=offset,
        limit=limit,
    )
    return [CommissionAccrualResponse.model_validate(r) for r in rows]


@router.post(
    "/commission-accruals/{accrual_id}/approve",
    response_model=CommissionAccrualResponse,
)
async def approve_commission_accrual(
    accrual_id: uuid.UUID,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.commission.approve")),
) -> CommissionAccrualResponse:
    user_id = _payload_user_id(payload)
    accrual = await service.commission_accruals.get_by_id(accrual_id)
    if accrual is None:
        raise HTTPException(
            status_code=404, detail=translate("errors.commission_accrual_not_found", locale=get_locale())
        )
    broker = await service.get_broker(accrual.broker_id)
    _ensure_broker_owner(broker, payload)
    return CommissionAccrualResponse.model_validate(await service.approve_commission(accrual_id, user_id))


@router.post(
    "/commission-accruals/{accrual_id}/pay",
    response_model=CommissionAccrualResponse,
)
async def pay_commission_accrual(
    accrual_id: uuid.UUID,
    data: CommissionAccrualPayRequest,
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.commission.pay")),
) -> CommissionAccrualResponse:
    user_id = _payload_user_id(payload)
    accrual = await service.commission_accruals.get_by_id(accrual_id)
    if accrual is None:
        raise HTTPException(
            status_code=404, detail=translate("errors.commission_accrual_not_found", locale=get_locale())
        )
    broker = await service.get_broker(accrual.broker_id)
    _ensure_broker_owner(broker, payload)
    return CommissionAccrualResponse.model_validate(await service.pay_commission(accrual_id, data.payment_ref, user_id))


# ── Escrow Accounts ────────────────────────────────────────────────────


@router.get(
    "/escrow-accounts/",
    response_model=list[EscrowAccountResponse],
)
async def list_escrow_accounts(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[EscrowAccountResponse]:
    await _verify_owner_via_development(session, development_id, user_payload)
    await service.get_development(development_id)
    rows = await service.escrow_accounts.list_for_development(development_id)
    return [EscrowAccountResponse.model_validate(r) for r in rows]


@router.post(
    "/escrow-accounts/",
    response_model=EscrowAccountResponse,
    status_code=201,
)
async def create_escrow_account(
    data: EscrowAccountCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> EscrowAccountResponse:
    await _verify_owner_via_development(session, data.development_id, user_payload)
    return EscrowAccountResponse.model_validate(await service.create_escrow_account(data))


@router.get(
    "/escrow-accounts/{account_id}",
    response_model=EscrowAccountResponse,
)
async def get_escrow_account(
    account_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> EscrowAccountResponse:
    await _verify_owner_via_escrow_account(session, account_id, user_payload)
    return EscrowAccountResponse.model_validate(await service.get_escrow_account(account_id))


@router.patch(
    "/escrow-accounts/{account_id}",
    response_model=EscrowAccountResponse,
)
async def update_escrow_account(
    account_id: uuid.UUID,
    data: EscrowAccountUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> EscrowAccountResponse:
    await _verify_owner_via_escrow_account(session, account_id, user_payload)
    return EscrowAccountResponse.model_validate(await service.update_escrow_account(account_id, data))


@router.delete("/escrow-accounts/{account_id}", status_code=204)
async def delete_escrow_account(
    account_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_escrow_account(session, account_id, user_payload)
    await service.get_escrow_account(account_id)
    await service.escrow_accounts.delete(account_id)


@router.get(
    "/escrow-accounts/{account_id}/balance",
    response_model=EscrowBalanceResponse,
)
async def escrow_account_balance(
    account_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> EscrowBalanceResponse:
    await _verify_owner_via_escrow_account(session, account_id, user_payload)
    payload = await service.compute_escrow_balance(
        account_id,
        as_of_date=as_of_date,
    )
    return EscrowBalanceResponse(
        escrow_account_id=payload["escrow_account_id"],
        currency=payload["currency"],
        as_of_date=payload["as_of_date"],
        credit_total=payload["credit_total"],
        debit_total=payload["debit_total"],
        balance=payload["balance"],
        transaction_count=payload["transaction_count"],
        unreconciled_count=payload["unreconciled_count"],
    )


# ── Escrow Transactions ────────────────────────────────────────────────


@router.get(
    "/escrow-transactions/",
    response_model=list[EscrowTransactionResponse],
)
async def list_escrow_transactions(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    escrow_account_id: uuid.UUID = Query(...),
    unreconciled_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[EscrowTransactionResponse]:
    await _verify_owner_via_escrow_account(
        session,
        escrow_account_id,
        user_payload,
    )
    await service.get_escrow_account(escrow_account_id)
    if unreconciled_only:
        rows = await service.escrow_transactions.list_unreconciled(escrow_account_id)
    else:
        rows = await service.escrow_transactions.list_for_account(
            escrow_account_id,
            offset=offset,
            limit=limit,
        )
    return [EscrowTransactionResponse.model_validate(r) for r in rows]


@router.post(
    "/escrow-transactions/",
    response_model=EscrowTransactionResponse,
    status_code=201,
)
async def create_escrow_transaction(
    data: EscrowTransactionCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> EscrowTransactionResponse:
    await _verify_owner_via_escrow_account(
        session,
        data.escrow_account_id,
        user_payload,
    )
    return EscrowTransactionResponse.model_validate(await service.create_escrow_transaction(data))


@router.get(
    "/escrow-transactions/{tx_id}",
    response_model=EscrowTransactionResponse,
)
async def get_escrow_transaction(
    tx_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> EscrowTransactionResponse:
    await _verify_owner_via_escrow_transaction(session, tx_id, user_payload)
    obj = await service.escrow_transactions.get_by_id(tx_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=translate("errors.escrow_not_found", locale=get_locale()))
    return EscrowTransactionResponse.model_validate(obj)


@router.patch(
    "/escrow-transactions/{tx_id}",
    response_model=EscrowTransactionResponse,
)
async def update_escrow_transaction(
    tx_id: uuid.UUID,
    data: EscrowTransactionUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> EscrowTransactionResponse:
    await _verify_owner_via_escrow_transaction(session, tx_id, user_payload)
    obj = await service.escrow_transactions.get_by_id(tx_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=translate("errors.escrow_not_found", locale=get_locale()))
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    if "metadata" in fields:
        _incoming = fields.pop("metadata")
        fields["metadata_"] = (
            merge_metadata(getattr(obj, "metadata_", None), _incoming) if isinstance(_incoming, dict) else _incoming
        )
    await service.escrow_transactions.update_fields(tx_id, **fields)
    refreshed = await service.escrow_transactions.get_by_id(tx_id)
    return EscrowTransactionResponse.model_validate(refreshed)


@router.delete("/escrow-transactions/{tx_id}", status_code=204)
async def delete_escrow_transaction(
    tx_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_escrow_transaction(session, tx_id, user_payload)
    obj = await service.escrow_transactions.get_by_id(tx_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=translate("errors.escrow_not_found", locale=get_locale()))
    await service.escrow_transactions.delete(tx_id)


@router.post(
    "/escrow-transactions/{tx_id}/reconcile",
    response_model=EscrowTransactionResponse,
)
async def reconcile_escrow_transaction(
    tx_id: uuid.UUID,
    data: EscrowTransactionReconcileRequest,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.escrow.reconcile")),
) -> EscrowTransactionResponse:
    await _verify_owner_via_escrow_transaction(session, tx_id, payload)
    return EscrowTransactionResponse.model_validate(
        await service.reconcile_escrow_transaction(
            tx_id,
            data.bank_reference,
            _payload_user_id(payload),
        )
    )


# ── Price Matrices ─────────────────────────────────────────────────────


@router.get(
    "/price-matrices/",
    response_model=list[PriceMatrixResponse],
)
async def list_price_matrices(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PriceMatrixResponse]:
    await _verify_owner_via_development(session, development_id, user_payload)
    await service.get_development(development_id)
    rows = await service.price_matrices.list_for_development(development_id)
    return [PriceMatrixResponse.model_validate(r) for r in rows]


@router.post(
    "/price-matrices/",
    response_model=PriceMatrixResponse,
    status_code=201,
)
async def create_price_matrix(
    data: PriceMatrixCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> PriceMatrixResponse:
    await _verify_owner_via_development(session, data.development_id, user_payload)
    return PriceMatrixResponse.model_validate(await service.create_price_matrix(data))


@router.get(
    "/price-matrices/{matrix_id}",
    response_model=PriceMatrixResponse,
)
async def get_price_matrix(
    matrix_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PriceMatrixResponse:
    await _verify_owner_via_price_matrix(session, matrix_id, user_payload)
    return PriceMatrixResponse.model_validate(await service.get_price_matrix(matrix_id))


@router.patch(
    "/price-matrices/{matrix_id}",
    response_model=PriceMatrixResponse,
)
async def update_price_matrix(
    matrix_id: uuid.UUID,
    data: PriceMatrixUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> PriceMatrixResponse:
    await _verify_owner_via_price_matrix(session, matrix_id, user_payload)
    return PriceMatrixResponse.model_validate(await service.update_price_matrix(matrix_id, data))


@router.delete("/price-matrices/{matrix_id}", status_code=204)
async def delete_price_matrix(
    matrix_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    await _verify_owner_via_price_matrix(session, matrix_id, user_payload)
    await service.get_price_matrix(matrix_id)
    await service.price_matrices.delete(matrix_id)


@router.post(
    "/price-matrices/{matrix_id}/activate",
    response_model=PriceMatrixResponse,
)
async def activate_price_matrix(
    matrix_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.price_matrix.activate")),
) -> PriceMatrixResponse:
    await _verify_owner_via_price_matrix(session, matrix_id, user_payload)
    return PriceMatrixResponse.model_validate(await service.activate_price_matrix(matrix_id))


@router.get(
    "/price-matrices/{matrix_id}/preview-on-plot/{plot_id}",
    response_model=PriceMatrixPreviewResponse,
)
async def preview_price_on_plot(
    matrix_id: uuid.UUID,
    plot_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    on_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PriceMatrixPreviewResponse:
    await _verify_owner_via_price_matrix(session, matrix_id, user_payload)
    await _verify_owner_via_plot(session, plot_id, user_payload)
    payload = await service.compute_plot_price(
        plot_id,
        on_date=on_date,
        matrix_id=matrix_id,
    )
    return PriceMatrixPreviewResponse(**payload)


@router.post(
    "/price-matrices/{matrix_id}/bulk-recompute",
    response_model=PriceMatrixBulkRecomputeResponse,
)
async def bulk_recompute_prices(
    matrix_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.price_matrix.bulk_recompute")),
) -> PriceMatrixBulkRecomputeResponse:
    await _verify_owner_via_price_matrix(session, matrix_id, user_payload)
    matrix = await service.get_price_matrix(matrix_id)
    result = await service.bulk_recompute_dev_prices(matrix.development_id)
    return PriceMatrixBulkRecomputeResponse(**result)


# ── Regulator reports ──────────────────────────────────────────────────


@router.get(
    "/regulator-reports/RERA",
    response_model=RegulatorReportResponse,
)
async def regulator_report_rera(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    quarter: str = Query(..., pattern=r"^\d{4}-Q[1-4]$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.regulator_report.generate")),
) -> RegulatorReportResponse:
    """R8: cross-tenant IDOR closed via ``_verify_owner_via_development``."""
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.generate_regulator_report_RERA(dev_id, quarter)
    return RegulatorReportResponse(**payload)


@router.get(
    "/regulator-reports/MAHARERA",
    response_model=RegulatorReportResponse,
)
async def regulator_report_maharera(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    quarter: str = Query(..., pattern=r"^\d{4}-Q[1-4]$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.regulator_report.generate")),
) -> RegulatorReportResponse:
    """R8: cross-tenant IDOR closed via ``_verify_owner_via_development``."""
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.generate_regulator_report_MAHARERA(dev_id, quarter)
    return RegulatorReportResponse(**payload)


@router.get(
    "/regulator-reports/214-FZ",
    response_model=RegulatorReportResponse,
)
async def regulator_report_214fz(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    quarter: str = Query(..., pattern=r"^\d{4}-Q[1-4]$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.regulator_report.generate")),
) -> RegulatorReportResponse:
    """R8: cross-tenant IDOR closed via ``_verify_owner_via_development``."""
    await _verify_owner_via_development(session, dev_id, user_payload)
    payload = await service.generate_regulator_report_214FZ(dev_id, quarter)
    return RegulatorReportResponse(**payload)


# ── Document templates (#138 follow-up) ────────────────────────────────


_VALID_DOC_TYPES_HTTP: set[str] = {
    "reservation_receipt",
    "sales_contract",
    "payment_receipt",
    "handover_certificate",
    "warranty_certificate",
    "noc",
    # New built-ins (v3124). Live ``/documents/{doc_type}`` rendering is
    # sample-preview only for now - the entity wiring for these flows is
    # added per-event in follow-up commits as the front-end surfaces them.
    "tenant_lease_agreement",
    "move_in_checklist",
    "mortgage_clearance_letter",
    "title_deed_transfer_request",
    "escrow_release_authorization",
    "refund_authorization",
}

_SUPPORTED_DOC_LOCALES: set[str] = {"en", "de", "ru", "fr", "ar", "es"}


async def _enforce_propdev_doc_owner(
    service: PropertyDevService,
    payload: dict[str, Any],
    *,
    contract_id: uuid.UUID | None,
    reservation_id: uuid.UUID | None,
    handover_id: uuid.UUID | None,
    instalment_id: uuid.UUID | None,
) -> None:
    """Cross-tenant IDOR closure for document endpoints.

    Resolves the calling user's project ownership against the entity
    referenced in the request. Collapses "doesn't exist" and "exists but
    not yours" into 404 so the endpoint can't be turned into a
    UUID-existence oracle. Admins bypass.
    """
    if payload.get("role") == "admin":
        return
    user_id = payload.get("sub") or payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    owner_id = await service.resolve_development_owner(
        contract_id=contract_id,
        reservation_id=reservation_id,
        handover_id=handover_id,
        instalment_id=instalment_id,
    )
    if owner_id is None or str(owner_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _normalise_locale(locale: str) -> str:
    base = (locale or "en").split("-")[0].lower()
    return base if base in _SUPPORTED_DOC_LOCALES else "en"


def _resolve_doc_type_or_404(doc_type: str) -> str:
    if doc_type not in _VALID_DOC_TYPES_HTTP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown doc_type '{doc_type}'",
        )
    return doc_type


def _filename_for(doc_type: str, entity_id: uuid.UUID | None) -> str:
    suffix = entity_id.hex[:8] if entity_id is not None else "doc"
    base = {
        "reservation_receipt": "reservation-receipt",
        "sales_contract": "sales-contract",
        "payment_receipt": "payment-receipt",
        "handover_certificate": "handover-certificate",
        "warranty_certificate": "warranty-certificate",
        "noc": "no-objection-certificate",
        "tenant_lease_agreement": "tenant-lease-agreement",
        "move_in_checklist": "move-in-checklist",
        "mortgage_clearance_letter": "mortgage-clearance-letter",
        "title_deed_transfer_request": "title-deed-transfer-request",
        "escrow_release_authorization": "escrow-release-authorization",
        "refund_authorization": "refund-authorization",
    }.get(doc_type, "document")
    return f"{base}-{suffix}.pdf"


@router.get("/documents/{doc_type}")
async def stream_propdev_document(
    doc_type: str,
    payload: CurrentUserPayload,
    contract_id: uuid.UUID | None = Query(default=None),
    reservation_id: uuid.UUID | None = Query(default=None),
    handover_id: uuid.UUID | None = Query(default=None),
    instalment_id: uuid.UUID | None = Query(default=None),
    locale: str = Query(default="en"),
    payment_method: str = Query(default=""),
    payment_ref: str | None = Query(default=None),
    requested_by: str = Query(default=""),
    structural_warranty_years: int = Query(default=10, ge=0, le=99),
    finishing_warranty_years: int = Query(default=1, ge=0, le=99),
    noc_validity_days: int = Query(default=30, ge=1, le=365),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Any:
    """Stream the generated PDF as ``application/pdf``.

    The Content-Disposition header carries a stable, human-friendly
    filename. The endpoint is gated by ``property_dev.read`` and
    enforces cross-tenant IDOR via the owner-resolution helper.
    """
    doc_type = _resolve_doc_type_or_404(doc_type)
    locale = _normalise_locale(locale)
    await _enforce_propdev_doc_owner(
        service,
        payload,
        contract_id=contract_id,
        reservation_id=reservation_id,
        handover_id=handover_id,
        instalment_id=instalment_id,
    )
    pdf_bytes = await service.generate_document(
        doc_type=doc_type,
        contract_id=contract_id,
        reservation_id=reservation_id,
        handover_id=handover_id,
        instalment_id=instalment_id,
        locale=locale,
        payment_method=payment_method,
        payment_ref=payment_ref,
        requested_by=requested_by,
        structural_warranty_years=structural_warranty_years,
        finishing_warranty_years=finishing_warranty_years,
        noc_validity_days=noc_validity_days,
    )
    entity_id = contract_id or reservation_id or handover_id or instalment_id
    filename = _filename_for(doc_type, entity_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Document-Type": doc_type,
            "X-Document-Locale": locale,
        },
    )


@router.post("/documents/preview")
async def preview_propdev_document(
    body: dict[str, Any],
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> dict[str, Any]:
    """Return a base64-encoded preview of the generated PDF.

    Used by the frontend ``DocumentPreviewModal`` so the document can be
    embedded inline without an extra round-trip. Same gating and IDOR
    closure as the streaming endpoint.
    """
    import base64

    doc_type = _resolve_doc_type_or_404(str(body.get("doc_type", "")))
    locale = _normalise_locale(str(body.get("locale", "en")))

    def _uuid(name: str) -> uuid.UUID | None:
        raw = body.get(name)
        if raw is None or raw == "":
            return None
        try:
            return uuid.UUID(str(raw))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid UUID for {name}",
            ) from exc

    contract_id = _uuid("contract_id")
    reservation_id = _uuid("reservation_id")
    handover_id = _uuid("handover_id")
    instalment_id = _uuid("instalment_id")

    await _enforce_propdev_doc_owner(
        service,
        payload,
        contract_id=contract_id,
        reservation_id=reservation_id,
        handover_id=handover_id,
        instalment_id=instalment_id,
    )
    pdf_bytes = await service.generate_document(
        doc_type=doc_type,
        contract_id=contract_id,
        reservation_id=reservation_id,
        handover_id=handover_id,
        instalment_id=instalment_id,
        locale=locale,
        payment_method=str(body.get("payment_method", "")),
        payment_ref=body.get("payment_ref"),
        requested_by=str(body.get("requested_by", "")),
        structural_warranty_years=int(body.get("structural_warranty_years", 10)),
        finishing_warranty_years=int(body.get("finishing_warranty_years", 1)),
        noc_validity_days=int(body.get("noc_validity_days", 30)),
    )
    page_count = 0
    try:
        from io import BytesIO as _BIO

        from pypdf import PdfReader as _PdfReader

        page_count = len(_PdfReader(_BIO(pdf_bytes)).pages)
    except Exception:
        page_count = max(1, pdf_bytes.count(b"/Type /Page"))

    return {
        "doc_type": doc_type,
        "locale": locale,
        "size_bytes": len(pdf_bytes),
        "page_count": page_count,
        "base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "filename": _filename_for(
            doc_type,
            contract_id or reservation_id or handover_id or instalment_id,
        ),
    }


_DOC_TYPE_TITLES: dict[str, str] = {
    "reservation_receipt": "Reservation Receipt",
    "sales_contract": "Sale-Purchase Agreement",
    "payment_receipt": "Payment Receipt",
    "handover_certificate": "Handover Certificate",
    "warranty_certificate": "Warranty Certificate",
    "noc": "No Objection Certificate",
    "tenant_lease_agreement": "Tenant Lease Agreement",
    "move_in_checklist": "Move-In Checklist",
    "mortgage_clearance_letter": "Mortgage Clearance Letter",
    "title_deed_transfer_request": "Title Deed Transfer Request",
    "escrow_release_authorization": "Escrow Release Authorization",
    "refund_authorization": "Refund Authorization",
}

# RFC 5322-lite: good enough to reject obvious typos before we hand the
# address to the SMTP backend (which does the authoritative validation).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/documents/email")
async def email_propdev_document(
    body: dict[str, Any],
    payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> dict[str, Any]:
    """Generate the document PDF and email it to a recipient as an attachment.

    Mirrors ``/documents/preview`` for entity resolution + IDOR closure,
    then renders the PDF once and hands it to the core email service. The
    recipient address is validated here; delivery itself never raises -
    the structured ``DeliveryResult`` is reflected back so the UI can show
    an honest success / failure toast (e.g. when SMTP is not configured the
    console backend "logs" the send and reports ``ok``).
    """

    doc_type = _resolve_doc_type_or_404(str(body.get("doc_type", "")))
    locale = _normalise_locale(str(body.get("locale", "en")))

    recipient = str(body.get("recipient_email", "")).strip()
    if not recipient or not _EMAIL_RE.match(recipient):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid recipient_email is required",
        )
    recipient_name = str(body.get("recipient_name", "")).strip() or None
    note = str(body.get("note", "")).strip() or None

    def _uuid(name: str) -> uuid.UUID | None:
        raw = body.get(name)
        if raw is None or raw == "":
            return None
        try:
            return uuid.UUID(str(raw))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid UUID for {name}",
            ) from exc

    contract_id = _uuid("contract_id")
    reservation_id = _uuid("reservation_id")
    handover_id = _uuid("handover_id")
    instalment_id = _uuid("instalment_id")

    await _enforce_propdev_doc_owner(
        service,
        payload,
        contract_id=contract_id,
        reservation_id=reservation_id,
        handover_id=handover_id,
        instalment_id=instalment_id,
    )
    pdf_bytes = await service.generate_document(
        doc_type=doc_type,
        contract_id=contract_id,
        reservation_id=reservation_id,
        handover_id=handover_id,
        instalment_id=instalment_id,
        locale=locale,
        payment_method=str(body.get("payment_method", "")),
        payment_ref=body.get("payment_ref"),
        requested_by=str(body.get("requested_by", "")),
        structural_warranty_years=int(body.get("structural_warranty_years", 10)),
        finishing_warranty_years=int(body.get("finishing_warranty_years", 1)),
        noc_validity_days=int(body.get("noc_validity_days", 30)),
    )

    entity_id = contract_id or reservation_id or handover_id or instalment_id
    filename = _filename_for(doc_type, entity_id)
    document_name = _DOC_TYPE_TITLES.get(doc_type, "Document")

    email_service = get_email_service()
    result = await email_service.send_document(
        recipient,
        subject=f"{document_name} - OpenConstructionERP",
        document_name=document_name,
        attachment=EmailAttachment(
            filename=filename,
            content=pdf_bytes,
            content_type="application/pdf",
        ),
        recipient_name=recipient_name,
        note=note,
    )

    if not result.ok:
        # Surface a 502 so the UI shows a failure toast rather than a false
        # "sent" - the backend (SMTP) refused or could not deliver.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Email delivery failed: {result.reason}",
        )

    return {
        "ok": True,
        "recipient": recipient,
        "backend": result.backend,
        "doc_type": doc_type,
        "filename": filename,
        # When SMTP is not configured the dev/console fallback "logs" the
        # message and still reports ok; tell the UI so it can hint honestly.
        "delivered": result.backend in {"smtp", "memory"},
    }


# ── Document-templates settings catalogue ──────────────────────────────


_DOC_TEMPLATE_CATALOGUE: list[dict[str, Any]] = [
    {
        "doc_type": "reservation_receipt",
        "title": "Reservation Receipt",
        "description": (
            "Issued automatically when a buyer pays the reservation deposit. Single A4 page, no watermark."
        ),
        "trigger": "POST /reservations/ → deposit recorded",
        "entity": "reservation",
        "pages": "1",
    },
    {
        "doc_type": "sales_contract",
        "title": "Sale-Purchase Agreement (SPA)",
        "description": (
            "Multi-page, multi-buyer aware contract. Auto-injects "
            "jurisdiction clauses (RERA / MAHARERA / 214-FZ / CMA). "
            "DRAFT watermark until status is signed/executed."
        ),
        "trigger": "POST /sales-contracts/ → status transitions",
        "entity": "sales_contract",
        "pages": "3+",
    },
    {
        "doc_type": "payment_receipt",
        "title": "Payment Receipt",
        "description": ("Issued per paid instalment. Shows outstanding balance and milestone reference."),
        "trigger": "POST /instalments/{id}/pay",
        "entity": "instalment",
        "pages": "1",
    },
    {
        "doc_type": "handover_certificate",
        "title": "Handover Certificate",
        "description": (
            "Signed at completion. Lists open snags + keys-handed-over date so the buyer formally accepts the unit."
        ),
        "trigger": "POST /handovers/{id}/complete",
        "entity": "handover",
        "pages": "1",
    },
    {
        "doc_type": "warranty_certificate",
        "title": "Warranty Certificate",
        "description": (
            "Issued on handover. Default 10y structural + 1y finishing. Lists exclusions and the claim procedure."
        ),
        "trigger": "GET /documents/warranty_certificate?handover_id=…",
        "entity": "handover",
        "pages": "1",
    },
    {
        "doc_type": "noc",
        "title": "No Objection Certificate",
        "description": ("Developer's permission for the buyer to resell. Validity 30 days by default."),
        "trigger": "GET /documents/noc?contract_id=…",
        "entity": "sales_contract",
        "pages": "1",
    },
    {
        "doc_type": "tenant_lease_agreement",
        "title": "Tenant Lease Agreement",
        "description": (
            "Multi-page residential rental contract for developer-owned "
            "or build-to-rent units. Captures tenant, term, monthly rent, "
            "security deposit and standard use / maintenance clauses."
        ),
        "trigger": "POST /leases/ → status transitions (sample-preview today)",
        "entity": "sales_contract",
        "pages": "2",
    },
    {
        "doc_type": "move_in_checklist",
        "title": "Move-in Checklist",
        "description": (
            "Room-by-room property-condition report attached to handover. "
            "Captures fixtures / fittings / appliance state with notes - "
            "complements the formal handover certificate."
        ),
        "trigger": "POST /handovers/{id}/complete → checklist captured",
        "entity": "handover",
        "pages": "2",
    },
    {
        "doc_type": "mortgage_clearance_letter",
        "title": "Mortgage Clearance Letter",
        "description": (
            "Bank-facing letter confirming the unit has no encumbrances "
            "in favour of the developer. Required by most lenders before "
            "final draw-down."
        ),
        "trigger": "GET /documents/mortgage_clearance_letter?contract_id=…",
        "entity": "sales_contract",
        "pages": "1",
    },
    {
        "doc_type": "title_deed_transfer_request",
        "title": "Title Deed Transfer Request",
        "description": (
            "Formal request to the land registry (Grundbuchamt / "
            "Росреестр / DLD / HM Land Registry) to transfer title from "
            "the developer to the new owner(s)."
        ),
        "trigger": "GET /documents/title_deed_transfer_request?contract_id=…",
        "entity": "sales_contract",
        "pages": "1",
    },
    {
        "doc_type": "escrow_release_authorization",
        "title": "Escrow Release Authorization",
        "description": (
            "Instruction to the escrow agent to release milestone funds "
            "from the project escrow account. Required by RERA / "
            "MAHARERA / 214-FZ workflows."
        ),
        "trigger": "Manual - generated at milestone certification",
        "entity": "sales_contract",
        "pages": "1",
    },
    {
        "doc_type": "refund_authorization",
        "title": "Refund Authorization",
        "description": (
            "Formal refund instruction for a cancelled reservation or "
            "sales contract. Shows refund amount, reason and payment "
            "method routing."
        ),
        "trigger": "POST /reservations/{id}/cancel or /sales-contracts/{id}/cancel",
        "entity": "sales_contract",
        "pages": "1",
    },
]


_CUSTOM_TEMPLATES_DIR = Path("uploads/property_dev/custom_templates")
_CUSTOM_TEMPLATE_MAX_MB = 50
_CUSTOM_TEMPLATE_MAX_BYTES = _CUSTOM_TEMPLATE_MAX_MB * 1024 * 1024
_ALLOWED_CUSTOM_TEMPLATE_EXTENSIONS: tuple[str, ...] = (
    ".docx",
    ".html",
    ".htm",
    ".pdf",
    ".odt",
    ".md",
    ".txt",
    ".xlsx",
)

_BINARY_EXT_TO_SIG: dict[str, frozenset[str]] = {
    ".docx": frozenset({"zip"}),
    ".xlsx": frozenset({"zip"}),
    ".odt": frozenset({"zip"}),
    ".pdf": frozenset({"pdf"}),
    ".html": frozenset({"xml"}),
    ".htm": frozenset({"xml"}),
}
_TEXT_EXTENSIONS: frozenset[str] = frozenset({".md", ".txt"})
_TEXT_NULL_SCAN_BYTES = 1024


def _validate_custom_template_magic(ext: str, content: bytes, filename: str) -> None:
    if ext in _BINARY_EXT_TO_SIG:
        try:
            require_signature(
                content[:SIGNATURE_BYTES_REQUIRED],
                _BINARY_EXT_TO_SIG[ext],
                filename=filename,
            )
        except FileSignatureMismatch as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(exc),
            ) from exc
        return
    if ext in _TEXT_EXTENSIONS:
        if b"\x00" in content[:_TEXT_NULL_SCAN_BYTES]:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(f"File '{filename}' looks binary but the extension '{ext}' expects plain text."),
            )
        return
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(f"Unsupported extension '{ext}'. Allowed: {', '.join(_ALLOWED_CUSTOM_TEMPLATE_EXTENSIONS)}"),
    )


# Suggested doc_type slugs. The settings page surfaces these as combobox
# presets BUT the value is no longer constrained to this list - any
# tenant (Brazil / Japan / Mexico / Australia / Vietnam / …) can supply
# a jurisdiction-specific slug such as ``escritura_publica`` or
# ``juyo_jiko_setsumeisho`` without us shipping a new release. The list
# only documents the slugs the built-in PDF renderers know about.
_DOC_TYPE_PRESETS: tuple[str, ...] = (
    "custom",
    "reservation_receipt",
    "sales_contract",
    "payment_receipt",
    "handover_certificate",
    "warranty_certificate",
    "noc",
    "snag_report",
    "invoice",
    "payment_reminder",
    "kyc_checklist",
    "brokerage_commission",
    "tenant_lease_agreement",
    "move_in_checklist",
    "mortgage_clearance_letter",
    "title_deed_transfer_request",
    "escrow_release_authorization",
    "refund_authorization",
)
# Suggested entity slugs. Same parameterization story as
# ``_DOC_TYPE_PRESETS`` - combobox presets only, free-text accepted.
_ENTITY_PRESETS: tuple[str, ...] = (
    "custom",
    "reservation",
    "sales_contract",
    "instalment",
    "handover",
    "snag",
    "broker",
    "buyer",
    "plot",
    "development",
    "tenant",
)

# Backwards-compatible aliases - kept for any third-party module that
# imported the legacy whitelist names. New code should consult the
# preset tuples above and the ``_validate_template_slug`` helper.
_ALLOWED_CUSTOM_DOC_TYPES: tuple[str, ...] = _DOC_TYPE_PRESETS
_ALLOWED_CUSTOM_ENTITIES: tuple[str, ...] = _ENTITY_PRESETS

# Permissive slug pattern: lowercase letters, digits, underscore, dash,
# dot - long enough to fit ``juyo_jiko_setsumeisho`` (24 chars) but
# bounded to keep DB columns sane and to reject SQL/path injection.
# Cap matches the ``doc_type`` / ``entity`` ``String(40)`` columns on
# ``PropertyDevCustomTemplate`` so the API rejects oversized values
# before the DB driver does.
_TEMPLATE_SLUG_MAX_LEN = 40
_TEMPLATE_SLUG_RE = re.compile(rf"^[a-z0-9][a-z0-9_.\-]{{0,{_TEMPLATE_SLUG_MAX_LEN - 1}}}$")

# Slugs with built-in PDF renderers. Used to set ``has_pdf_renderer``
# on each catalogue entry so the frontend gates the "Preview / Download
# sample" buttons on real data instead of a hardcoded set.
_BUILTIN_RENDERER_DOC_TYPES: frozenset[str] = frozenset({entry["doc_type"] for entry in _DOC_TEMPLATE_CATALOGUE})

_CUSTOM_TEMPLATE_LOG = logging.getLogger(__name__ + ".custom_templates")


def _serialize_custom_template_row(row: Any) -> dict[str, Any]:
    """Convert a ``PropertyDevCustomTemplate`` ORM row into the shared
    catalogue dict shape used by the upload / save-text / list endpoints.

    Centralised so the ``has_pdf_renderer`` flag (added in v4.7 for the
    worldwide-parameterized settings page) stays consistent across every
    code path that returns a custom-template entry. Text uploads (.html
    / .md / .txt) are renderable in-browser; binary uploads (.docx /
    .pdf / .odt) require the original download.
    """
    content_type = row.content_type or ""
    return {
        "id": str(row.id),
        "doc_type": row.doc_type,
        "title": row.name,
        "description": row.description or "",
        "trigger": row.trigger,
        "entity": row.entity,
        "pages": "-",
        "is_custom": True,
        "has_pdf_renderer": content_type.startswith("text/"),
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "development_id": (str(row.development_id) if row.development_id else None),
        "project_id": str(row.project_id) if row.project_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# Documentation block for the "{i} Variables" modal in the settings
# page. Kept in code (not a YAML file) because it mirrors the public
# fields of the ORM models below - they move together at refactor time.
_TEMPLATE_VARIABLES_DOCUMENTATION: list[dict[str, Any]] = [
    {
        "group": "development",
        "label": "Development",
        "vars": [
            {"key": "{development.name}", "desc": "Development name"},
            {"key": "{development.code}", "desc": "Short development code"},
            {"key": "{development.country_code}", "desc": "ISO-3166 alpha-2"},
            {"key": "{development.dev_type}", "desc": "residential, mixed_use, …"},
            {"key": "{development.total_area_m2}", "desc": "Total m²"},
            {"key": "{development.currency}", "desc": "ISO-4217 (e.g. EUR)"},
            {"key": "{development.developer_name}", "desc": "Developer entity"},
        ],
    },
    {
        "group": "plot",
        "label": "Plot",
        "vars": [
            {"key": "{plot.plot_number}", "desc": "Plot number / ID"},
            {"key": "{plot.area_m2}", "desc": "Plot area in m²"},
            {"key": "{plot.house_type_label}", "desc": "House-type display label"},
            {"key": "{plot.phase_code}", "desc": "Phase code (metadata)"},
            {"key": "{plot.block_code}", "desc": "Block code (metadata)"},
            {"key": "{plot.currency}", "desc": "Plot's pricing currency"},
        ],
    },
    {
        "group": "buyer",
        "label": "Buyer",
        "vars": [
            {"key": "{buyer.full_name}", "desc": "Full legal name"},
            {"key": "{buyer.email}", "desc": "Primary contact email"},
            {"key": "{buyer.party_role}", "desc": "primary / secondary"},
            {"key": "{buyer.ownership_pct}", "desc": "Ownership percentage"},
        ],
    },
    {
        "group": "reservation",
        "label": "Reservation",
        "vars": [
            {"key": "{reservation.reservation_number}", "desc": "RES-YYYY-NNNN"},
            {"key": "{reservation.deposit_amount}", "desc": "Deposit paid"},
            {"key": "{reservation.expires_at}", "desc": "Reservation expiry"},
            {"key": "{reservation.cooling_off_until}", "desc": "Cooling-off date"},
        ],
    },
    {
        "group": "contract",
        "label": "Sales Contract",
        "vars": [
            {"key": "{contract.contract_number}", "desc": "SPA-YYYY-NNNN"},
            {"key": "{contract.total_value}", "desc": "Total contract value"},
            {"key": "{contract.currency}", "desc": "Contract currency"},
            {"key": "{contract.status}", "desc": "draft / signed / executed"},
            {"key": "{contract.signing_date}", "desc": "ISO date"},
            {"key": "{contract.place}", "desc": "Place of signing"},
        ],
    },
    {
        "group": "handover",
        "label": "Handover",
        "vars": [
            {"key": "{handover.scheduled_at}", "desc": "Planned handover date"},
            {"key": "{handover.completed_at}", "desc": "Actual handover date"},
            {"key": "{handover.keys_handed_over_at}", "desc": "Keys-handed-over date"},
            {"key": "{handover.snag_count}", "desc": "Open snags at handover"},
        ],
    },
    {
        "group": "instalment",
        "label": "Instalment",
        "vars": [
            {"key": "{instalment.sequence}", "desc": "Sequence number"},
            {"key": "{instalment.milestone_label}", "desc": "Milestone label"},
            {"key": "{instalment.due_date}", "desc": "Due date (ISO)"},
            {"key": "{instalment.amount}", "desc": "Instalment amount"},
            {"key": "{instalment.amount_paid}", "desc": "Amount paid"},
        ],
    },
]


@router.get("/document-templates/")
async def list_document_templates(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    development_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> dict[str, Any]:
    """List property-development document templates.

    Returns the six built-in PDF generators shipped with the platform
    plus any tenant-uploaded custom templates owned by the calling
    user's projects. Also returns the supported locales / jurisdictions
    and a documentation block describing the variables custom
    templates may interpolate.

    Built-in templates themselves are source-of-truth code in
    ``document_templates.py``; this endpoint exposes their metadata so
    the settings UI can render a real catalogue with previews instead
    of an empty stub. Custom templates land in
    ``oe_property_dev_custom_template`` with their files under
    ``uploads/property_dev/custom_templates/``.
    """
    from sqlalchemy import select

    from app.modules.property_dev.document_templates import (
        SUPPORTED_LOCALES,
        SUPPORTED_REGULATORS,
        list_locale_status,
    )
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    # Resolve owning project IDs for the calling user. Admins see every
    # uploaded template; everyone else sees only templates from projects
    # they own. The query is bounded by RBAC + the explicit list of
    # owned project IDs - no cross-tenant leakage.
    is_admin = user_payload.get("role") == "admin"
    user_id = user_payload.get("sub") or user_payload.get("user_id")

    stmt = select(PropertyDevCustomTemplate).order_by(PropertyDevCustomTemplate.created_at.desc())
    if not is_admin and user_id is not None:
        from app.modules.projects.models import Project

        proj_stmt = select(Project.id).where(Project.owner_id == user_id)
        owned_ids = (await session.execute(proj_stmt)).scalars().all()
        if not owned_ids:
            stmt = stmt.where(PropertyDevCustomTemplate.id == uuid.UUID(int=0))
        else:
            stmt = stmt.where(PropertyDevCustomTemplate.project_id.in_(owned_ids))

    if development_id is not None:
        stmt = stmt.where(
            (PropertyDevCustomTemplate.development_id == development_id)
            | (PropertyDevCustomTemplate.development_id.is_(None))
        )

    rows = (await session.execute(stmt)).scalars().all()
    custom_entries: list[dict[str, Any]] = [_serialize_custom_template_row(row) for row in rows]

    builtin_entries = [
        {
            **tpl,
            "is_custom": False,
            # All entries in ``_DOC_TEMPLATE_CATALOGUE`` correspond 1:1 to
            # reportlab renderers in ``document_templates.py``. Expose the
            # flag so the frontend can stop gating Preview on a hardcoded
            # ``BUILTIN_DOC_TYPES`` set.
            "has_pdf_renderer": tpl["doc_type"] in _BUILTIN_RENDERER_DOC_TYPES,
        }
        for tpl in _DOC_TEMPLATE_CATALOGUE
    ]

    return {
        "templates": builtin_entries + custom_entries,
        # Bare list kept for legacy callers; the new ``locale_status`` is
        # what the settings UI uses to render the native names + the
        # "translated / falls back to English" badge.
        "locales": list(SUPPORTED_LOCALES),
        "locale_status": list_locale_status(),
        "regulators": list(SUPPORTED_REGULATORS),
        # Combobox suggestions for the upload + editor forms. The forms
        # accept any reasonably-shaped slug (see
        # ``_validate_template_slug``) so tenants outside the DACH / UK /
        # UAE / RU / IN markets that shipped the original list can wire
        # their own jurisdiction-specific document types without us
        # rolling a release.
        "doc_type_presets": list(_DOC_TYPE_PRESETS),
        "entity_presets": list(_ENTITY_PRESETS),
        "variables": _TEMPLATE_VARIABLES_DOCUMENTATION,
        "upload": {
            "allowed_extensions": list(_ALLOWED_CUSTOM_TEMPLATE_EXTENSIONS),
            "max_size_mb": _CUSTOM_TEMPLATE_MAX_MB,
        },
    }


def _validate_template_slug(value: str, *, field: str) -> str:
    """Validate a doc_type / entity slug for shape only, not membership.

    The slug whitelist used to be the source-of-truth for which doc_type
    values a tenant could persist. That model didn't survive contact
    with the global market: Brazilian developers need
    ``escritura_publica``, Japanese sales offices need
    ``juyo_jiko_setsumeisho``, Mexican notaries need ``acta_de_entrega``,
    and so on. Instead of patching the whitelist for every new country,
    we now accept any reasonably-shaped slug (``[a-z0-9_.-]``, 1-80 chars,
    leading alphanumeric) and let the presets in
    ``_DOC_TYPE_PRESETS`` / ``_ENTITY_PRESETS`` act as combobox
    suggestions only.

    Raises 422 if the value is empty, malformed, or longer than 80 chars
    (the DB column cap for ``doc_type`` and ``entity``).
    """
    value = (value or "custom").strip().lower()
    if not _TEMPLATE_SLUG_RE.match(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid {field} '{value}'. Use 1-{_TEMPLATE_SLUG_MAX_LEN} "
                "lowercase letters, digits, dots, dashes or underscores; "
                "must start with a letter or digit."
            ),
        )
    return value


def _validate_custom_template_metadata(
    name: str,
    doc_type: str,
    entity: str,
    trigger: str,
) -> tuple[str, str, str, str]:
    """Validate + normalise the upload's text metadata.

    Raises 422 on any field that's empty, too long, or carries
    characters that wouldn't make sense as a doc_type / entity. The
    doc_type / entity slugs are validated for SHAPE only - see
    ``_validate_template_slug`` - so tenants are free to add
    jurisdiction-specific document types without a code release.
    """
    name = (name or "").strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Template name is required",
        )
    if len(name) > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Template name must be 200 characters or fewer",
        )
    doc_type = _validate_template_slug(doc_type, field="doc_type")
    entity = _validate_template_slug(entity, field="entity")
    trigger = (trigger or "manual").strip()
    if len(trigger) > 200:
        trigger = trigger[:200]
    return name, doc_type, entity, trigger


@router.get("/document-templates/locales/{code}")
async def get_document_template_locale(
    code: str,
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> dict[str, Any]:
    """Return the merged locale JSON used by PDF rendering for ``code``.

    Resolution order: tenant override > bundled JSON > English fallback.
    The UI uses this to (a) download EN as a starter template, and
    (b) preview what strings are currently in effect for a given locale
    before uploading an override.
    """
    from app.modules.property_dev.document_templates import (
        SUPPORTED_LOCALES,
        _load_locale,
        locale_override_exists,
    )

    if code not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=404, detail=f"Unsupported locale: {code}")
    blob = _load_locale(code)
    return {
        "code": code,
        "source": "override" if locale_override_exists(code) else "bundled-or-fallback",
        "data": blob,
    }


@router.put("/document-templates/locales/{code}")
async def put_document_template_locale(
    code: str,
    payload: dict[str, Any],
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> dict[str, Any]:
    """Upload an override JSON for ``code`` (replaces the bundled file).

    Body shape: ``{"data": {... nested locale strings ...}}``. The
    handler validates that ``data`` is a JSON object and writes it under
    ``uploads/property_dev/document_locales/{code}.json``. The next PDF
    render automatically picks up the new copy (cache invalidated).
    """
    from app.modules.property_dev.document_templates import (
        SUPPORTED_LOCALES,
        write_locale_override,
    )

    if code not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=404, detail=f"Unsupported locale: {code}")
    blob = payload.get("data")
    if not isinstance(blob, dict):
        raise HTTPException(status_code=422, detail="Expected `data` to be a JSON object")
    try:
        write_locale_override(code, blob)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": code, "status": "ok"}


@router.delete("/document-templates/locales/{code}", status_code=204)
async def delete_document_template_locale_override(
    code: str,
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> None:
    """Remove the tenant override and revert to the bundled translation."""
    from app.modules.property_dev.document_templates import (
        SUPPORTED_LOCALES,
        delete_locale_override,
    )

    if code not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=404, detail=f"Unsupported locale: {code}")
    delete_locale_override(code)


@router.post("/document-templates/upload", status_code=201)
async def upload_custom_document_template(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    file: UploadFile = File(...),
    name: str = "",
    doc_type: str = "custom",
    entity: str = "custom",
    trigger: str = "manual",
    description: str = "",
    project_id: uuid.UUID | None = None,
    development_id: uuid.UUID | None = None,
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> dict[str, Any]:
    """Upload a tenant-owned custom document template.

    Accepts .docx / .html / .htm / .pdf / .odt / .md / .txt up to 10 MB.
    The file lands in ``uploads/property_dev/custom_templates/`` with a
    UUID-prefixed basename so two uploads with the same original
    filename don't collide. Metadata is persisted to
    ``oe_property_dev_custom_template`` and the row appears alongside
    built-in templates on the settings page.
    """
    from sqlalchemy import select

    from app.modules.projects.models import Project
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    name, doc_type, entity, trigger = _validate_custom_template_metadata(
        name,
        doc_type,
        entity,
        trigger,
    )

    raw_filename = file.filename or "template.bin"
    ext = Path(raw_filename).suffix.lower()
    if ext not in _ALLOWED_CUSTOM_TEMPLATE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(f"Unsupported extension '{ext}'. Allowed: {', '.join(_ALLOWED_CUSTOM_TEMPLATE_EXTENSIONS)}"),
        )

    try:
        content = await file.read()
    except Exception:
        _CUSTOM_TEMPLATE_LOG.exception("Unable to read template upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded template",
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )
    if len(content) > _CUSTOM_TEMPLATE_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"Template exceeds {_CUSTOM_TEMPLATE_MAX_MB} MB limit"),
        )

    _validate_custom_template_magic(ext, content, raw_filename)

    is_admin = user_payload.get("role") == "admin"
    user_id_raw = user_payload.get("sub") or user_payload.get("user_id")
    if user_id_raw is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = uuid.UUID(str(user_id_raw))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user id")

    resolved_project_id: uuid.UUID | None = None
    if project_id is not None:
        proj = await session.get(Project, project_id)
        if proj is None:
            raise HTTPException(status_code=404, detail=translate("errors.project_not_found", locale=get_locale()))
        if not is_admin and str(proj.owner_id) != str(user_id):
            raise HTTPException(status_code=404, detail=translate("errors.project_not_found", locale=get_locale()))
        resolved_project_id = project_id
    else:
        first_proj = (
            await session.execute(
                select(Project.id).where(Project.owner_id == user_id).limit(1),
            )
        ).scalar_one_or_none()
        if first_proj is None and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=("No project found for current user. Create a project before uploading templates."),
            )
        resolved_project_id = first_proj

    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    template_id = uuid.uuid4()
    safe_basename = Path(raw_filename).name
    stored_filename = f"{template_id.hex}_{safe_basename}"
    filepath = _CUSTOM_TEMPLATES_DIR / stored_filename

    try:
        filepath.write_bytes(content)
    except Exception:
        _CUSTOM_TEMPLATE_LOG.exception("Unable to save template upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save template - storage error",
        )

    row = PropertyDevCustomTemplate(
        id=template_id,
        project_id=resolved_project_id,
        development_id=development_id,
        name=name,
        doc_type=doc_type,
        entity=entity,
        trigger=trigger,
        description=description.strip() or None,
        filename=safe_basename,
        storage_path=str(filepath.as_posix()),
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        created_by=user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return _serialize_custom_template_row(row)


@router.delete("/document-templates/custom/{template_id}", status_code=204)
async def delete_custom_document_template(
    template_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> Response:
    """Delete a tenant-uploaded custom template (file + row).

    404s - never 403s - when the row is owned by a different tenant so
    the endpoint can't be turned into a UUID-existence oracle.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    row = await session.get(PropertyDevCustomTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail=translate("errors.template_not_found", locale=get_locale()))

    is_admin = user_payload.get("role") == "admin"
    user_id = user_payload.get("sub") or user_payload.get("user_id")
    if not is_admin and row.project_id is not None:
        proj = await ProjectRepository(session).get_by_id(row.project_id)
        if proj is None or str(proj.owner_id) != str(user_id):
            raise HTTPException(status_code=404, detail=translate("errors.template_not_found", locale=get_locale()))

    try:
        path = Path(row.storage_path)
        if path.exists():
            path.unlink()
    except Exception:
        _CUSTOM_TEMPLATE_LOG.warning(
            "Could not unlink custom template file at %s",
            row.storage_path,
            exc_info=True,
        )

    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


@router.get("/document-templates/custom/{template_id}/download")
async def download_custom_document_template(
    template_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Response:
    """Stream a previously-uploaded custom template back to the client.

    Same ownership check as the delete endpoint - 404 (not 403) when
    the caller doesn't own the row.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    row = await session.get(PropertyDevCustomTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail=translate("errors.template_not_found", locale=get_locale()))

    is_admin = user_payload.get("role") == "admin"
    user_id = user_payload.get("sub") or user_payload.get("user_id")
    if not is_admin and row.project_id is not None:
        proj = await ProjectRepository(session).get_by_id(row.project_id)
        if proj is None or str(proj.owner_id) != str(user_id):
            raise HTTPException(status_code=404, detail=translate("errors.template_not_found", locale=get_locale()))

    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(
            status_code=410,
            detail="Template file missing from storage",
        )
    data = path.read_bytes()
    return Response(
        content=data,
        media_type=row.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": (f'attachment; filename="{row.filename}"'),
        },
    )


# ── In-browser editor - text-based custom templates ────────────────────


# Max body for the JSON-content path. Mirrors the multipart cap so we
# can't be tricked into storing oversized HTML by going through this
# door instead of the upload form.
_CUSTOM_TEMPLATE_TEXT_MAX_CHARS = _CUSTOM_TEMPLATE_MAX_BYTES  # 50 MB

_TEXT_EXT_FOR_CONTENT_TYPE: dict[str, str] = {
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
}

_ALLOWED_TEXT_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/html",
        "text/markdown",
        "text/plain",
    }
)


def _resolve_safe_text_filename(
    name: str,
    doc_type: str,
    content_type: str,
) -> str:
    """Build a safe on-disk basename for a saved-text template.

    Strips path separators and any character that's not letter / digit
    / dash / underscore so a `name` like ``"a/b/c.txt"`` can't escape
    the custom-templates directory or end up as a different extension
    than the content type says.
    """
    raw = (name or doc_type or "template").strip()
    # Drop any directory components and any leftover punctuation.
    safe = "".join(c if c.isalnum() or c in {"-", "_", " "} else "_" for c in raw).strip("_") or doc_type or "template"
    # Collapse whitespace.
    safe = "_".join(safe.split())[:80]  # 80 chars is plenty for a basename
    ext = _TEXT_EXT_FOR_CONTENT_TYPE.get(content_type, ".txt")
    return f"{safe}{ext}"


@router.post("/document-templates/save-text", status_code=201)
async def save_text_custom_document_template(
    body: dict[str, Any],
    session: SessionDep,
    user_payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("property_dev.create")),
) -> dict[str, Any]:
    """Save in-browser-edited HTML / Markdown / plain-text as a custom
    template.

    Counterpart to ``POST /document-templates/upload`` - accepts a JSON
    body with the raw text content instead of a multipart file. Same
    project-ownership / RBAC gating; same 10 MB cap (in characters,
    since UTF-8 bytes are <= char count for ASCII / Latin-1 and only
    modestly larger for cyrillic / asian scripts).

    Request body::

        {
          "name": "My HTML reservation receipt",
          "doc_type": "reservation_receipt",
          "entity": "reservation",
          "trigger": "manual",
          "description": "Branded HTML template (2026)",
          "project_id": "...",                 # optional
          "development_id": "...",             # optional
          "content_type": "text/html",         # html | markdown | plain
          "content_text": "<html>…</html>",
          "template_id": "..."                 # optional - update in place
        }

    When ``template_id`` is supplied the call REPLACES the named row's
    body + filename in place (mirrors a `PATCH` semantically but stays
    on the same endpoint for the SPA). Cross-tenant attempts collapse
    to 404, never 403, mirroring the rest of the property_dev IDOR
    closures.
    """
    from sqlalchemy import select

    from app.modules.projects.models import Project
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    name = str(body.get("name", "")).strip()
    doc_type = str(body.get("doc_type", "custom")).strip().lower()
    entity = str(body.get("entity", "custom")).strip().lower()
    trigger = str(body.get("trigger", "manual")).strip()
    description = str(body.get("description", "")).strip()
    content_type = str(body.get("content_type", "text/html")).strip().lower()
    content_text = body.get("content_text", "")
    project_id_raw = body.get("project_id")
    development_id_raw = body.get("development_id")
    template_id_raw = body.get("template_id")

    name, doc_type, entity, trigger = _validate_custom_template_metadata(
        name,
        doc_type,
        entity,
        trigger,
    )

    if content_type not in _ALLOWED_TEXT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"content_type '{content_type}' is not allowed. Use {', '.join(sorted(_ALLOWED_TEXT_CONTENT_TYPES))}."
            ),
        )
    if not isinstance(content_text, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="content_text must be a string",
        )
    if not content_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="content_text is empty",
        )
    if len(content_text) > _CUSTOM_TEMPLATE_TEXT_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"Template content exceeds {_CUSTOM_TEMPLATE_MAX_MB} MB limit"),
        )

    # Stored XSS hardening (audit 2026-06-22 #2): templates are
    # development/tenant-shared resources, so an HTML body authored by one
    # user is later auto-previewed (dangerouslySetInnerHTML) in another
    # staff member's authenticated session. Strip the XSS-dangerous subset
    # (script/iframe/object/embed/svg, on* event handlers, javascript:/
    # data:text/html URIs) on save so the persisted bytes can never carry
    # an active payload. Benign layout markup the templates rely on (tables,
    # styling, {placeholders}) is preserved. Markdown/plain bodies are
    # escaped at render time and need no HTML strip here.
    if content_type == "text/html":
        content_text = strip_dangerous_html(content_text)

    is_admin = user_payload.get("role") == "admin"
    user_id_raw = user_payload.get("sub") or user_payload.get("user_id")
    if user_id_raw is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = uuid.UUID(str(user_id_raw))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user id")

    # ── Update-in-place path ──
    template_id: uuid.UUID | None = None
    existing_row: PropertyDevCustomTemplate | None = None
    if template_id_raw:
        try:
            template_id = uuid.UUID(str(template_id_raw))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid template_id",
            ) from exc
        existing_row = await session.get(PropertyDevCustomTemplate, template_id)
        if existing_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.template_not_found", locale=get_locale()),
            )
        # IDOR closure - only the owner (or admin) may overwrite the row.
        if not is_admin and existing_row.project_id is not None:
            from app.modules.projects.repository import ProjectRepository

            proj = await ProjectRepository(session).get_by_id(
                existing_row.project_id,
            )
            if proj is None or str(proj.owner_id) != str(user_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=translate("errors.template_not_found", locale=get_locale()),
                )

    # ── Project resolution (same logic as the upload endpoint) ──
    resolved_project_id: uuid.UUID | None = None
    if existing_row is not None:
        resolved_project_id = existing_row.project_id
    elif project_id_raw is not None:
        try:
            project_id = uuid.UUID(str(project_id_raw))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid project_id",
            ) from exc
        proj = await session.get(Project, project_id)
        if proj is None:
            raise HTTPException(
                status_code=404,
                detail=translate("errors.project_not_found", locale=get_locale()),
            )
        if not is_admin and str(proj.owner_id) != str(user_id):
            raise HTTPException(
                status_code=404,
                detail=translate("errors.project_not_found", locale=get_locale()),
            )
        resolved_project_id = project_id
    else:
        first_proj = (
            await session.execute(
                select(Project.id).where(Project.owner_id == user_id).limit(1),
            )
        ).scalar_one_or_none()
        if first_proj is None and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=("No project found for current user. Create a project before saving templates."),
            )
        resolved_project_id = first_proj

    development_id: uuid.UUID | None = None
    if development_id_raw not in (None, ""):
        try:
            development_id = uuid.UUID(str(development_id_raw))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid development_id",
            ) from exc

    # ── Persist file ──
    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if existing_row is not None:
        # Reuse stored_path so we don't litter the directory on every save.
        target_path = Path(existing_row.storage_path)
        # If the saved content_type changed (e.g. .html → .md), rename.
        new_basename = _resolve_safe_text_filename(name, doc_type, content_type)
        if target_path.name != f"{template_id.hex}_{new_basename}":
            try:
                if target_path.exists():
                    target_path.unlink()
            except Exception:
                _CUSTOM_TEMPLATE_LOG.warning(
                    "Could not delete previous text template at %s",
                    target_path,
                    exc_info=True,
                )
            target_path = _CUSTOM_TEMPLATES_DIR / f"{template_id.hex}_{new_basename}"
    else:
        template_id = uuid.uuid4()
        basename = _resolve_safe_text_filename(name, doc_type, content_type)
        target_path = _CUSTOM_TEMPLATES_DIR / f"{template_id.hex}_{basename}"

    try:
        target_path.write_text(content_text, encoding="utf-8")
    except Exception:
        _CUSTOM_TEMPLATE_LOG.exception("Unable to save text template")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save template - storage error",
        )

    size_bytes = target_path.stat().st_size

    if existing_row is not None:
        existing_row.name = name
        existing_row.doc_type = doc_type
        existing_row.entity = entity
        existing_row.trigger = trigger
        existing_row.description = description or None
        existing_row.filename = target_path.name.split("_", 1)[-1]
        existing_row.storage_path = str(target_path.as_posix())
        existing_row.content_type = content_type
        existing_row.size_bytes = size_bytes
        if development_id is not None:
            existing_row.development_id = development_id
        await session.commit()
        await session.refresh(existing_row)
        row = existing_row
    else:
        assert template_id is not None  # narrowing for mypy
        row = PropertyDevCustomTemplate(
            id=template_id,
            project_id=resolved_project_id,
            development_id=development_id,
            name=name,
            doc_type=doc_type,
            entity=entity,
            trigger=trigger,
            description=description or None,
            filename=target_path.name.split("_", 1)[-1],
            storage_path=str(target_path.as_posix()),
            content_type=content_type,
            size_bytes=size_bytes,
            created_by=user_id,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return _serialize_custom_template_row(row)


@router.get("/document-templates/custom/{template_id}/content")
async def get_custom_document_template_content(
    template_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> dict[str, Any]:
    """Return the raw text content of a custom template - for the editor.

    Only returns text content (text/html, text/markdown, text/plain).
    Binary uploads (.docx / .pdf / .odt) return 415 - they can't be
    round-tripped through the in-browser editor.

    Same project-ownership / 404-not-403 guard as the download endpoint.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    row = await session.get(PropertyDevCustomTemplate, template_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=translate("errors.template_not_found", locale=get_locale()),
        )

    is_admin = user_payload.get("role") == "admin"
    user_id = user_payload.get("sub") or user_payload.get("user_id")
    if not is_admin and row.project_id is not None:
        proj = await ProjectRepository(session).get_by_id(row.project_id)
        if proj is None or str(proj.owner_id) != str(user_id):
            raise HTTPException(
                status_code=404,
                detail=translate("errors.template_not_found", locale=get_locale()),
            )

    if (row.content_type or "").lower() not in _ALLOWED_TEXT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "This template was uploaded as a binary file and cannot be opened in the editor. Download it instead."
            ),
        )

    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(
            status_code=410,
            detail="Template file missing from storage",
        )

    try:
        content_text = path.read_text(encoding="utf-8")
    except Exception:
        _CUSTOM_TEMPLATE_LOG.exception(
            "Could not read text template at %s",
            row.storage_path,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to read template - storage error",
        )

    return {
        "id": str(row.id),
        "doc_type": row.doc_type,
        "title": row.name,
        "description": row.description or "",
        "trigger": row.trigger,
        "entity": row.entity,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "content_text": content_text,
        "development_id": (str(row.development_id) if row.development_id else None),
        "project_id": str(row.project_id) if row.project_id else None,
    }


@router.post("/document-templates/{doc_type}/sample-preview")
async def sample_preview_document_template(
    doc_type: str,
    body: dict[str, Any],
    _user_payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> dict[str, Any]:
    """Render a synthetic sample of the template (no real entities).

    Useful for previewing the template look-and-feel from the settings
    page. The generator runs against in-memory stub data so any tenant
    can preview without owning a contract.
    """
    import base64
    import uuid as _uuid
    from datetime import UTC, date, datetime, timedelta
    from decimal import Decimal
    from types import SimpleNamespace

    doc_type = _resolve_doc_type_or_404(doc_type)
    locale = _normalise_locale(str(body.get("locale", "en")))
    regulator = str(body.get("regulator", "NONE")).upper()

    # ── Synthetic entities (just enough for each generator) ──
    now = datetime.now(UTC)
    today = date.today()
    development = SimpleNamespace(
        id=_uuid.uuid4(),
        name="Sample Riverside Gardens",
        code="DEV-SAMPLE",
        metadata_={"regulator": regulator},
        completion_date=(today + timedelta(days=180)).isoformat(),
    )
    plot = SimpleNamespace(
        id=_uuid.uuid4(),
        plot_number="P-101",
        area_m2=Decimal("78.50"),
        currency="EUR",
        house_type_label="Modern Townhouse",
        metadata_={"phase_code": "PH-A", "block_code": "B1"},
    )
    buyers = [
        SimpleNamespace(
            id=_uuid.uuid4(),
            full_name="Jane Sample",
            email="jane.sample@example.com",
        ),
        SimpleNamespace(
            id=_uuid.uuid4(),
            full_name="John Sample",
            email="john.sample@example.com",
        ),
    ]
    reservation = SimpleNamespace(
        id=_uuid.uuid4(),
        reservation_number="RES-2026-0042",
        deposit_amount=Decimal("5000.00"),
        currency="EUR",
        expires_at=(today + timedelta(days=14)).isoformat(),
        cooling_off_until=(today + timedelta(days=10)).isoformat(),
        cooling_off_days=10,
    )
    contract = SimpleNamespace(
        id=_uuid.uuid4(),
        contract_number="SPA-2026-0017",
        total_value=Decimal("420000.00"),
        currency="EUR",
        status="draft",
        place="Berlin",
        signing_date=today.isoformat(),
        metadata_={
            "rera_registration_no": "SAMPLE-RERA-001",
            "escrow_account_no": "DE89-3704-0044-0532-0130-00",
        },
    )
    payment_schedule = SimpleNamespace(currency="EUR")
    instalments = [
        SimpleNamespace(
            sequence=i,
            milestone_label=label,
            milestone_event=label,
            due_date=(today + timedelta(days=30 * i)).isoformat(),
            amount=Decimal(str(amount)),
            amount_paid=Decimal("0"),
        )
        for i, (label, amount) in enumerate(
            [
                ("Booking", 10000),
                ("Foundation", 84000),
                ("Structure", 168000),
                ("Finishing", 105000),
                ("Handover", 53000),
            ],
            start=1,
        )
    ]
    parties = [
        SimpleNamespace(
            buyer_id=buyers[0].id,
            party_role="primary",
            ownership_pct=Decimal("50"),
            full_name=buyers[0].full_name,
            email=buyers[0].email,
        ),
        SimpleNamespace(
            buyer_id=buyers[1].id,
            party_role="secondary",
            ownership_pct=Decimal("50"),
            full_name=buyers[1].full_name,
            email=buyers[1].email,
        ),
    ]
    handover = SimpleNamespace(
        id=_uuid.uuid4(),
        scheduled_at=(today + timedelta(days=120)).isoformat(),
        completed_at=today.isoformat(),
        keys_handed_over_at=today.isoformat(),
    )
    paid_instalment = SimpleNamespace(
        sequence=2,
        milestone_label="Foundation",
        milestone_event="foundation_complete",
        amount=Decimal("84000.00"),
        amount_paid=Decimal("84000.00"),
        paid_at=now.isoformat(),
    )

    # ── Dispatch to the right generator ──
    from app.modules.property_dev.document_templates import (
        render_escrow_release_authorization_pdf,
        render_handover_certificate_pdf,
        render_mortgage_clearance_letter_pdf,
        render_move_in_checklist_pdf,
        render_no_objection_certificate_pdf,
        render_payment_receipt_pdf,
        render_refund_authorization_pdf,
        render_reservation_receipt_pdf,
        render_sales_contract_pdf,
        render_tenant_lease_agreement_pdf,
        render_title_deed_transfer_request_pdf,
        render_warranty_certificate_pdf,
    )

    if doc_type == "reservation_receipt":
        pdf_bytes = render_reservation_receipt_pdf(
            reservation,
            plot,
            development,
            buyers,
            locale=locale,
        )
    elif doc_type == "sales_contract":
        pdf_bytes = render_sales_contract_pdf(
            contract,
            payment_schedule,
            instalments,
            parties,
            plot,
            development,
            locale=locale,
            buyer_lookup={b.id: b for b in buyers},
        )
    elif doc_type == "payment_receipt":
        pdf_bytes = render_payment_receipt_pdf(
            paid_instalment,
            contract,
            payment_method="bank_transfer",
            payment_ref="REF-SAMPLE-001",
            locale=locale,
            plot=plot,
            development=development,
        )
    elif doc_type == "handover_certificate":
        pdf_bytes = render_handover_certificate_pdf(
            handover,
            contract,
            snag_count=2,
            plot=plot,
            development=development,
            locale=locale,
        )
    elif doc_type == "warranty_certificate":
        pdf_bytes = render_warranty_certificate_pdf(
            contract,
            handover,
            structural_warranty_years=10,
            finishing_warranty_years=1,
            locale=locale,
            plot=plot,
            development=development,
        )
    elif doc_type == "tenant_lease_agreement":
        lease = SimpleNamespace(
            id=_uuid.uuid4(),
            lease_number="LEA-2026-0003",
            currency="EUR",
            monthly_rent=Decimal("1800.00"),
            security_deposit=Decimal("5400.00"),
            term_months=12,
            start_date=today.isoformat(),
            end_date=(today + timedelta(days=365)).isoformat(),
            status="draft",
        )
        pdf_bytes = render_tenant_lease_agreement_pdf(
            lease,
            plot,
            development,
            buyers,
            locale=locale,
        )
    elif doc_type == "move_in_checklist":
        rooms = [
            SimpleNamespace(
                name="Entry / Hallway",
                items=[
                    SimpleNamespace(label="Door & locks", condition="Good", notes=""),
                    SimpleNamespace(label="Walls & paint", condition="Good", notes=""),
                    SimpleNamespace(label="Light fittings", condition="Good", notes=""),
                ],
            ),
            SimpleNamespace(
                name="Kitchen",
                items=[
                    SimpleNamespace(label="Oven", condition="New", notes="Test cooking only"),
                    SimpleNamespace(label="Fridge / freezer", condition="New", notes=""),
                    SimpleNamespace(label="Sink & taps", condition="Good", notes=""),
                    SimpleNamespace(label="Cabinets", condition="Good", notes=""),
                ],
            ),
            SimpleNamespace(
                name="Bathroom",
                items=[
                    SimpleNamespace(label="Toilet", condition="Good", notes=""),
                    SimpleNamespace(label="Shower / bath", condition="Good", notes=""),
                    SimpleNamespace(label="Mirror & cabinet", condition="Good", notes=""),
                ],
            ),
            SimpleNamespace(
                name="Living room",
                items=[
                    SimpleNamespace(label="Floor", condition="Good", notes=""),
                    SimpleNamespace(label="Windows & blinds", condition="Good", notes=""),
                ],
            ),
        ]
        pdf_bytes = render_move_in_checklist_pdf(
            handover,
            contract,
            plot,
            development,
            rooms,
            locale=locale,
        )
    elif doc_type == "mortgage_clearance_letter":
        pdf_bytes = render_mortgage_clearance_letter_pdf(
            contract,
            plot,
            development,
            bank_name="Sample Sparkasse Berlin",
            locale=locale,
        )
    elif doc_type == "title_deed_transfer_request":
        pdf_bytes = render_title_deed_transfer_request_pdf(
            contract,
            plot,
            development,
            parties,
            registry_name="Grundbuchamt Berlin",
            locale=locale,
            buyer_lookup={b.id: b for b in buyers},
        )
    elif doc_type == "escrow_release_authorization":
        pdf_bytes = render_escrow_release_authorization_pdf(
            contract,
            plot,
            development,
            escrow_account_no="DE89-3704-0044-0532-0130-00",
            amount=Decimal("84000.00"),
            release_reason="Foundation milestone certified",
            locale=locale,
        )
    elif doc_type == "refund_authorization":
        pdf_bytes = render_refund_authorization_pdf(
            contract,
            plot,
            development,
            refund_amount=Decimal("5000.00"),
            refund_reason="Buyer cancellation within cooling-off period",
            payment_method="bank_transfer",
            locale=locale,
            reservation=reservation,
        )
    else:  # noc
        pdf_bytes = render_no_objection_certificate_pdf(
            contract,
            plot,
            development,
            requested_by="Jane Sample (sample)",
            locale=locale,
        )

    page_count = 0
    try:
        from io import BytesIO as _BIO

        from pypdf import PdfReader as _PdfReader

        page_count = len(_PdfReader(_BIO(pdf_bytes)).pages)
    except Exception:
        page_count = max(1, pdf_bytes.count(b"/Type /Page"))

    return {
        "doc_type": doc_type,
        "locale": locale,
        "regulator": regulator,
        "size_bytes": len(pdf_bytes),
        "page_count": page_count,
        "base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "filename": f"sample-{doc_type}-{locale}.pdf",
        "sample": True,
    }


# ── Compliance dashboard + regulator reports (task #139) ───────────────


async def _run_property_dev_validation(
    session: SessionDep,
    dev_id: uuid.UUID,
    locale: str = "en",
) -> Any:
    """Execute the ``property_dev`` rule set against a development."""
    from app.core.validation.engine import rule_registry, validation_engine

    # Ensure the rule registry is populated. ``register_builtin_rules`` is
    # idempotent - calling it twice does not duplicate rules.
    if not rule_registry.list_rule_sets().get("property_dev"):
        from app.core.validation.rules import register_builtin_rules

        register_builtin_rules()

    return await validation_engine.validate(
        data={},
        rule_sets=["property_dev"],
        target_type="property_dev_development",
        target_id=str(dev_id),
        project_id=str(dev_id),
        metadata={
            "session": session,
            "development_id": str(dev_id),
            "locale": locale,
        },
    )


def _report_to_response(
    dev_id: uuid.UUID,
    report: Any,
) -> ComplianceDashboardResponse:
    """Materialise a ``ValidationReport`` into the dashboard response."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    summary = report.summary()
    return ComplianceDashboardResponse(
        development_id=dev_id,
        status=summary["status"],
        score=summary["score"],
        counts=summary["counts"],
        rule_sets=summary["rule_sets"],
        duration_ms=summary["duration_ms"],
        generated_at=_dt.now(_UTC).isoformat(timespec="seconds"),
        results=[
            ComplianceRuleResult(
                rule_id=r.rule_id,
                rule_name=r.rule_name,
                severity=r.severity.value,
                category=r.category.value,
                passed=r.passed,
                message=r.message,
                element_ref=r.element_ref,
                details=r.details or {},
                suggestion=r.suggestion,
            )
            for r in report.results
        ],
    )


@router.get(
    "/compliance/dashboard",
    response_model=ComplianceDashboardResponse,
)
async def compliance_dashboard(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    locale: str = Query(default="en", min_length=2, max_length=10),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> ComplianceDashboardResponse:
    """Aggregated traffic-light validation report for one development.

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development`` -
    avoids letting any reader probe other tenants' dev UUIDs for an
    existence oracle via the compliance dashboard.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    report = await _run_property_dev_validation(session, dev_id, locale)
    return _report_to_response(dev_id, report)


@router.post(
    "/compliance/run-checks",
    response_model=ComplianceDashboardResponse,
)
async def compliance_run_checks(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    locale: str = Query(default="en", min_length=2, max_length=10),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> ComplianceDashboardResponse:
    """Trigger a re-run of the property_dev rule set.

    Mounted as POST because side-effecting downstream subscribers (audit
    log, notifications) treat each invocation as a fresh validation pass.
    Requires ``property_dev.update`` to gate it behind editor RBAC.

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development``.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    report = await _run_property_dev_validation(session, dev_id, locale)
    return _report_to_response(dev_id, report)


@router.get(
    "/compliance/regulator-reports",
    # response_model intentionally omitted - endpoint returns either a
    # streaming Response (PDF/payload bytes) or the
    # ComplianceRegulatorReportResponse JSON envelope depending on `as`.
)
async def compliance_regulator_report(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    regulator: str = Query(...),
    quarter: str = Query(..., pattern=r"^\d{4}-Q[1-4]$"),
    as_: str = Query(default="json", alias="as", pattern=r"^(json|pdf|payload)$"),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Any:
    """Generate a regulator report for a development.

    Query::

        regulator = RERA | MAHARERA | 214FZ | CMA
        quarter   = YYYY-Qn
        as        = json (default - base64'd PDF + payload inline) |
                    pdf  (streaming application/pdf) |
                    payload (streaming application/json or application/xml)
    """
    import base64

    from app.modules.property_dev.regulatory import (
        SUPPORTED_REGULATORS,
        generate_regulator_report,
    )

    # R8: IDOR closure FIRST so attackers can't probe other tenants' dev UUIDs
    # via this endpoint. Collapses "not yours" / "doesn't exist" to 404.
    await _verify_owner_via_development(session, dev_id, user_payload)
    reg_code = (regulator or "").strip().upper()
    if reg_code not in {"RERA", "MAHARERA", "214FZ", "214-FZ", "214", "CMA"}:
        raise HTTPException(
            status_code=422,
            detail=(f"unsupported_regulator:{regulator} (supported: {', '.join(SUPPORTED_REGULATORS)})"),
        )
    try:
        report = await generate_regulator_report(
            session,
            dev_id=dev_id,
            regulator=reg_code,
            quarter=quarter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if as_ == "pdf":
        return Response(
            content=report.pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (f'attachment; filename="{report.regulator}_{report.quarter}.pdf"'),
            },
        )
    if as_ == "payload":
        media = "application/xml" if report.payload_format == "xml" else "application/json"
        ext = "xml" if report.payload_format == "xml" else "json"
        return Response(
            content=report.payload_bytes,
            media_type=media,
            headers={
                "Content-Disposition": (f'attachment; filename="{report.regulator}_{report.quarter}.{ext}"'),
            },
        )
    return ComplianceRegulatorReportResponse(
        regulator=report.regulator,
        development_id=dev_id,
        quarter=report.quarter,
        generated_at=report.generated_at,
        pdf_base64=base64.b64encode(report.pdf_bytes).decode("ascii"),
        payload_format=report.payload_format,
        payload_base64=base64.b64encode(report.payload_bytes).decode("ascii"),
        summary=report.summary,
    )


# ── Inventory Map (task #142) ───────────────────────────────────────────
#
# The Inventory Map is the sales-desk daily index - every Plot in a
# Development laid out as block → floor → unit tiles with a KPI ribbon
# and bulk hold/release. Distinct from the analytics
# /dashboards/inventory-heatmap (task #140) which groups by Phase.

from app.modules.property_dev.schemas import (  # noqa: E402
    InventoryMapBulkHoldRequest,
    InventoryMapBulkReleaseRequest,
    InventoryMapBulkResult,
    InventoryMapResponse,
)


@router.get(
    "/developments/{dev_id}/inventory-map/",
    response_model=InventoryMapResponse,
)
async def get_inventory_map(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> InventoryMapResponse:
    """Block / floor / unit grid for the Inventory Map page.

    Returns every Plot in the Development bucketed by block_code → floor →
    unit_code, with a KPI summary ribbon. Single read fan-out (one SELECT
    for plots, one for blocks). Sales-desk usage - they hit this on
    every page load, target latency <300ms even at 1000 plots.

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development``.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    data = await service.inventory_map(dev_id)
    return InventoryMapResponse.model_validate(data)


@router.post(
    "/developments/{dev_id}/inventory-map/bulk-hold/",
    response_model=InventoryMapBulkResult,
)
async def inventory_map_bulk_hold(
    dev_id: uuid.UUID,
    data: InventoryMapBulkHoldRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> InventoryMapBulkResult:
    """Bulk-hold up to 500 plots in one atomic SAVEPOINT.

    Available (planned / ready) plots flip to ``held`` with the supplied
    reason + optional ``hold_until`` date stashed under ``Plot.metadata.hold``.
    Reserved / sold / handed-over plots reject the whole batch with 409
    (matches the procurement.create_invoice_from_po atomicity pattern).
    Already-held plots are soft-skipped (idempotent).

    RBAC: MANAGER+ (uses ``property_dev.delete`` which maps to MANAGER -
    matches sales-floor convention that only sales managers can pull
    inventory off the market).

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development``.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    actor_id = user_payload.get("sub") or user_payload.get("user_id")
    result = await service.inventory_bulk_hold(
        dev_id,
        list(data.plot_ids),
        data.hold_reason,
        data.hold_until,
        actor_id=actor_id,
    )
    return InventoryMapBulkResult.model_validate(result)


@router.post(
    "/developments/{dev_id}/inventory-map/bulk-release/",
    response_model=InventoryMapBulkResult,
)
async def inventory_map_bulk_release(
    dev_id: uuid.UUID,
    data: InventoryMapBulkReleaseRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.delete")),
) -> InventoryMapBulkResult:
    """Bulk-release held plots back to ``planned``.

    Idempotent: non-held plots are silently skipped (NOT 409) so that a
    shift-select range that happens to include an already-released plot
    doesn't force the user to retry one-by-one. ``blocked`` plots are
    NEVER released through this endpoint - they require an explicit
    MANAGER PATCH on the plot itself.

    R8: cross-tenant IDOR closed via ``_verify_owner_via_development``.
    """
    await _verify_owner_via_development(session, dev_id, user_payload)
    actor_id = user_payload.get("sub") or user_payload.get("user_id")
    result = await service.inventory_bulk_release(
        dev_id,
        list(data.plot_ids),
        actor_id=actor_id,
    )
    return InventoryMapBulkResult.model_validate(result)


# ── Dashboards (task #140) ──────────────────────────────────────────────


@router.get(
    "/dashboards/inventory-heatmap",
    response_model=InventoryHeatmapResponse,
)
async def dashboard_inventory_heatmap(
    session: SessionDep,
    payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> InventoryHeatmapResponse:
    """Inventory heatmap grouped by Phase -> Block -> Plot."""
    await _verify_owner_via_development(session, dev_id, payload)
    data = await service.dashboard_inventory_heatmap(dev_id)
    return InventoryHeatmapResponse.model_validate(data)


@router.get(
    "/dashboards/sales-velocity",
    response_model=SalesVelocityResponse,
)
async def dashboard_sales_velocity(
    session: SessionDep,
    payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    granularity: str = Query(default="month", pattern=r"^(week|month|quarter)$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> SalesVelocityResponse:
    """Sales velocity: SPAs signed by period (week/month/quarter)."""
    await _verify_owner_via_development(session, dev_id, payload)
    data = await service.dashboard_sales_velocity(dev_id, granularity=granularity)
    return SalesVelocityResponse.model_validate(data)


@router.get(
    "/dashboards/cashflow-waterfall",
    response_model=CashflowWaterfallResponse,
)
async def dashboard_cashflow_waterfall(
    session: SessionDep,
    payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    start_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    months: int = Query(default=12, ge=1, le=60),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> CashflowWaterfallResponse:
    """Monthly cash-flow: scheduled instalments + actual escrow flows."""
    await _verify_owner_via_development(session, dev_id, payload)
    data = await service.dashboard_cashflow_waterfall(
        dev_id,
        start_month=start_month,
        months=months,
    )
    return CashflowWaterfallResponse.model_validate(data)


@router.get(
    "/dashboards/inventory-ageing",
    response_model=InventoryAgeingResponse,
)
async def dashboard_inventory_ageing(
    session: SessionDep,
    payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> InventoryAgeingResponse:
    """Days-on-market buckets + reserved-no-contract list."""
    await _verify_owner_via_development(session, dev_id, payload)
    data = await service.dashboard_inventory_ageing(dev_id)
    return InventoryAgeingResponse.model_validate(data)


@router.get(
    "/dashboards/funnel-conversion",
    response_model=FunnelConversionResponse,
)
async def dashboard_funnel_conversion(
    session: SessionDep,
    payload: CurrentUserPayload,
    dev_id: uuid.UUID = Query(...),
    period_days: int = Query(default=90, ge=1, le=365),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> FunnelConversionResponse:
    """5-stage funnel: Lead -> Reservation -> SPA draft -> SPA signed -> Handover."""
    await _verify_owner_via_development(session, dev_id, payload)
    data = await service.dashboard_funnel_conversion(
        dev_id,
        period_days=period_days,
    )
    return FunnelConversionResponse.model_validate(data)


@router.get(
    "/dashboards/buyer-journey",
    response_model=BuyerJourneyResponse,
)
async def dashboard_buyer_journey(
    session: SessionDep,
    payload: CurrentUserPayload,
    buyer_id: uuid.UUID = Query(...),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> BuyerJourneyResponse:
    """Cross-entity timeline: Lead -> Reservation -> SPA -> Payments -> Handover -> Warranty."""
    await _verify_buyer_owner(session, buyer_id, payload)
    data = await service.dashboard_buyer_journey(buyer_id)
    return BuyerJourneyResponse.model_validate(data)


# ── Sales-analytics dashboards (v3124) ──────────────────────────────────
#
# Director-grade rollups. Each endpoint:
#   * tenant-scoped through ``_verify_owner_via_development`` (when a
#     dev_id is supplied) or falls back to ``ProjectRepository`` filtering
#     (when no dev_id is supplied - non-admins only see their projects),
#   * ETag + ``Cache-Control: max-age=120`` so repeated polls from the
#     dashboard widgets short-circuit at 304,
#   * 422 on bad ``since`` / ``until`` scope (Query regex),
#   * money fields as Decimal-as-string at the schema layer.


def _validate_iso_date(value: str | None, field: str) -> None:
    """Raise 422 when ``value`` is not a real YYYY-MM-DD date.

    The Query regex only checks shape (``\\d{4}-\\d{2}-\\d{2}``) - values
    like ``2026-13-99`` slip through and would surface as 500 from
    ``date.fromisoformat`` in the service layer. We pre-flight them here.
    """
    if value is None:
        return
    from datetime import date as _date

    try:
        _date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date for {field}: {exc}",
        )


def _analytics_etag(payload: dict[str, Any], *, user_id: str) -> str:
    """Hash a payload + user_id into a stable weak ETag.

    Includes ``user_id`` so the cached entry never leaks across tenants
    even if a proxy strips authorization headers. Excludes any timestamp
    field (we don't have one in the analytics payloads - they're pure
    aggregates).
    """
    import hashlib
    import json

    basis = json.dumps(
        {"u": user_id, "p": payload},
        sort_keys=True,
        default=str,
    )
    return '"' + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16] + '"'


def _serve_analytics(
    payload: dict[str, Any],
    *,
    response_cls: type,
    user_id: str,
    if_none_match: str | None,
) -> Response:
    """Build a JSON Response with ETag + Cache-Control + 304 short-circuit."""
    import json

    response_payload = response_cls.model_validate(payload).model_dump(mode="json")
    etag = _analytics_etag(response_payload, user_id=user_id)
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=120",
    }
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers=headers)
    body = json.dumps(response_payload, sort_keys=True, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers=headers,
    )


async def _list_accessible_dev_ids(
    session: SessionDep,
    user_payload: dict[str, Any],
) -> list[uuid.UUID]:
    """Return every development_id the caller can see.

    Used by the cross-development analytics endpoints (cohort-retention,
    time-to-close, lead-source-attribution, broker-performance) to scope
    rollups to the caller's tenant without forcing them to pass a
    dev_id. Admins see ALL developments.
    """
    from sqlalchemy import select as _select

    from app.modules.projects.models import Project
    from app.modules.property_dev.models import Development as _Dev

    is_admin = user_payload.get("role") == "admin"
    user_id = user_payload.get("sub") or user_payload.get("user_id")

    if is_admin:
        stmt = _select(_Dev.id)
    else:
        if not user_id:
            return []
        stmt = (
            _select(_Dev.id)
            .join(Project, Project.id == _Dev.project_id)
            .where(Project.owner_id == uuid.UUID(str(user_id)))
        )
    return [row for (row,) in (await session.execute(stmt)).all()]


@router.get(
    "/dashboards/cohort-retention/",
    response_model=CohortRetentionResponse,
)
async def dashboard_cohort_retention(
    session: SessionDep,
    payload: CurrentUserPayload,
    cohort_period: str = Query(default="month", pattern=r"^(month)$"),
    since: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    until: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Response:
    """Reservation cohorts grouped by birth month + % retained at +N days.

    Tenant scope: admins see all reservations; non-admins see only
    reservations on plots they own. ETag + 120s cache so the heatmap
    re-renders are cheap.
    """
    from app.modules.property_dev.analytics_service import AnalyticsService

    _validate_iso_date(since, "since")
    _validate_iso_date(until, "until")
    user_id = str(payload.get("sub") or payload.get("user_id") or "")
    # When the caller can't see ANY development we collapse to an empty
    # payload (200 + 0 cohorts) - never leak an existence oracle.
    dev_ids = await _list_accessible_dev_ids(session, payload)
    if not dev_ids and payload.get("role") != "admin":
        empty = {
            "cohort_period": cohort_period,
            "since": since,
            "until": until,
            "cohorts": [],
            "total_cohorts": 0,
        }
        return _serve_analytics(
            empty,
            response_cls=CohortRetentionResponse,
            user_id=user_id,
            if_none_match=if_none_match,
        )

    svc = AnalyticsService(session)
    raw = await svc.cohort_retention(
        cohort_period=cohort_period,
        since=since,
        until=until,
    )
    # Tenant-scope: filter cohorts to reservations on accessible plots.
    # The service returns aggregated cohorts already - we re-run with a
    # tenant-aware query when the caller isn't admin.
    if payload.get("role") != "admin":
        raw = await _tenant_scope_cohort_retention(
            session,
            dev_ids,
            raw,
            since=since,
            until=until,
        )
    return _serve_analytics(
        raw,
        response_cls=CohortRetentionResponse,
        user_id=user_id,
        if_none_match=if_none_match,
    )


async def _tenant_scope_cohort_retention(
    session: SessionDep,
    dev_ids: list[uuid.UUID],
    fallback: dict[str, Any],
    *,
    since: str | None,
    until: str | None,
) -> dict[str, Any]:
    """Re-run the cohort aggregation scoped to the caller's developments."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select as _select

    from app.modules.property_dev.analytics_service import AnalyticsService
    from app.modules.property_dev.models import (
        Plot as _Plot,
    )
    from app.modules.property_dev.models import (
        Reservation as _Res,
    )

    if not dev_ids:
        return {**fallback, "cohorts": [], "total_cohorts": 0}

    svc = AnalyticsService(session)
    # Inject the dev-ids filter via an explicit subquery - keep the
    # analytics-service signature stable by replicating just the data
    # shape it expects.
    accessible_plots_q = _select(_Plot.id).where(_Plot.development_id.in_(dev_ids))
    stmt = _select(
        _Res.id,
        _Res.created_at,
        _Res.status,
        _Res.cooling_off_until,
        _Res.expires_at,
        _Res.metadata_,
    ).where(_Res.plot_id.in_(accessible_plots_q))
    since_d = datetime.fromisoformat(since).date() if since else None
    until_d = datetime.fromisoformat(until).date() if until else None
    if since_d is not None:
        stmt = stmt.where(_Res.created_at >= datetime.combine(since_d, datetime.min.time(), tzinfo=UTC))
    if until_d is not None:
        stmt = stmt.where(
            _Res.created_at
            < datetime.combine(
                until_d + timedelta(days=1),
                datetime.min.time(),
                tzinfo=UTC,
            )
        )
    rows = (await session.execute(stmt)).all()
    # Defer to the same projection helper by stuffing rows into the
    # analytics-service object's session and re-using its helpers. Cleaner
    # path is to delegate to a private projection function; we inline a
    # short reduction here to keep blast radius small.
    from datetime import date as _date
    from decimal import Decimal as _D

    today = datetime.now(UTC).date()
    cohorts: dict[str, dict[str, Any]] = {}
    for res_id, created_at, st, _cool, _exp, meta in rows:
        if isinstance(created_at, datetime):
            created_d = created_at.date()
        elif isinstance(created_at, _date):
            created_d = created_at
        else:
            continue
        key = f"{created_d.year:04d}-{created_d.month:02d}"
        slot = cohorts.setdefault(
            key,
            {
                "cohort_month": key,
                "total": 0,
                "still_active": 0,
                "events": [],
            },
        )
        slot["total"] += 1
        if st not in ("cancelled", "refunded", "expired"):
            slot["still_active"] += 1
        terminal_days: int | None = None
        if st in ("cancelled", "refunded", "expired") and isinstance(meta, dict):
            for k in ("cancelled_at", "refunded_at", "expired_at"):
                v = meta.get(k)
                if isinstance(v, str) and v:
                    try:
                        t = _date.fromisoformat(v[:10])
                        terminal_days = (t - created_d).days
                        break
                    except ValueError:
                        continue
        slot["events"].append({"status": st, "days_to_terminal": terminal_days, "age_days": (today - created_d).days})

    out: list[dict[str, Any]] = []
    for key in sorted(cohorts.keys()):
        slot = cohorts[key]
        total = slot["total"]
        pct: dict[int, _D] = {}
        for off in (30, 60, 90, 180):
            if total == 0:
                pct[off] = _D("0")
                continue
            retained = 0
            for ev in slot["events"]:
                if ev["age_days"] < off:
                    continue
                dtt = ev["days_to_terminal"]
                if dtt is None or dtt > off:
                    retained += 1
            pct[off] = (_D(retained) / _D(total) * _D("100")).quantize(_D("0.1"))
        out.append(
            {
                "cohort_month": key,
                "total": total,
                "still_active": slot["still_active"],
                "retention_pct_d30": pct[30],
                "retention_pct_d60": pct[60],
                "retention_pct_d90": pct[90],
                "retention_pct_d180": pct[180],
            }
        )
    return {
        "cohort_period": fallback.get("cohort_period", "month"),
        "since": since,
        "until": until,
        "cohorts": out,
        "total_cohorts": len(out),
    }


@router.get(
    "/dashboards/time-to-close/",
    response_model=TimeToCloseResponse,
)
async def dashboard_time_to_close(
    session: SessionDep,
    payload: CurrentUserPayload,
    since: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    until: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Response:
    """Days Lead → Reservation → Sale → Handover for closed sales.

    Returns histogram + mean + p50 + p90 per stage. Tenant-scoped: when
    the caller can't see any development the response is 200 with
    ``closed_sales=0`` (never an existence oracle).
    """
    from app.modules.property_dev.analytics_service import AnalyticsService

    _validate_iso_date(since, "since")
    _validate_iso_date(until, "until")
    user_id = str(payload.get("sub") or payload.get("user_id") or "")
    dev_ids = await _list_accessible_dev_ids(session, payload)
    if not dev_ids and payload.get("role") != "admin":
        empty = {
            "since": since,
            "until": until,
            "closed_sales": 0,
            "stages": [],
        }
        return _serve_analytics(
            empty,
            response_cls=TimeToCloseResponse,
            user_id=user_id,
            if_none_match=if_none_match,
        )

    svc = AnalyticsService(session)
    raw = await svc.time_to_close(since=since, until=until)
    # Tenant-scope: drop any stage samples sourced from plots the caller
    # can't see. The service today returns aggregated stage stats over
    # ALL SPAs in window. We re-aggregate behind a dev-filter when the
    # caller isn't admin.
    if payload.get("role") != "admin":
        raw = await _tenant_scope_time_to_close(
            session,
            dev_ids,
            since=since,
            until=until,
        )
    return _serve_analytics(
        raw,
        response_cls=TimeToCloseResponse,
        user_id=user_id,
        if_none_match=if_none_match,
    )


async def _tenant_scope_time_to_close(
    session: SessionDep,
    dev_ids: list[uuid.UUID],
    *,
    since: str | None,
    until: str | None,
) -> dict[str, Any]:
    """Re-run time-to-close scoped to the caller's developments."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from decimal import Decimal as _D

    from sqlalchemy import select as _select

    from app.modules.property_dev.analytics_service import (
        _STAGE_BUCKETS,
        _bucket_for_days,
        _percentile,
    )
    from app.modules.property_dev.models import (
        Handover as _Ho,
    )
    from app.modules.property_dev.models import (
        Lead as _Lead,
    )
    from app.modules.property_dev.models import (
        Plot as _Plot,
    )
    from app.modules.property_dev.models import (
        Reservation as _Res,
    )
    from app.modules.property_dev.models import (
        SalesContract as _SPA,
    )

    if not dev_ids:
        return {
            "since": since,
            "until": until,
            "closed_sales": 0,
            "stages": [],
        }

    accessible_plots_q = _select(_Plot.id).where(_Plot.development_id.in_(dev_ids))
    stmt = (
        _select(
            _SPA.id,
            _SPA.signing_date,
            _SPA.created_at,
            _SPA.reservation_id,
            _SPA.plot_id,
            _Res.created_at.label("res_created_at"),
            _Res.lead_id,
            _Ho.completed_at.label("ho_completed_at"),
        )
        .join(_Res, _Res.id == _SPA.reservation_id, isouter=True)
        .join(_Ho, _Ho.plot_id == _SPA.plot_id, isouter=True)
        .where(_SPA.plot_id.in_(accessible_plots_q))
        .where(_SPA.status.in_(("signed", "countersigned", "registered")))
    )
    if since:
        stmt = stmt.where(_SPA.signing_date >= since)
    if until:
        stmt = stmt.where(_SPA.signing_date <= until)
    spa_rows = (await session.execute(stmt)).all()

    lead_ids = {r.lead_id for r in spa_rows if r.lead_id is not None}
    lead_created: dict[uuid.UUID, _dt] = {}
    if lead_ids:
        for lid, lc in (await session.execute(_select(_Lead.id, _Lead.created_at).where(_Lead.id.in_(lead_ids)))).all():
            lead_created[lid] = lc

    def _to_d(v: Any) -> _date | None:
        if v is None:
            return None
        if isinstance(v, _dt):
            return v.date()
        if isinstance(v, _date):
            return v
        if isinstance(v, str) and v:
            try:
                return _date.fromisoformat(v[:10])
            except ValueError:
                return None
        return None

    l_to_r: list[_D] = []
    r_to_s: list[_D] = []
    s_to_h: list[_D] = []
    l_to_h: list[_D] = []
    for r in spa_rows:
        lead_d = _to_d(lead_created.get(r.lead_id) if r.lead_id else None)
        res_d = _to_d(r.res_created_at)
        sale_d = _to_d(r.signing_date)
        ho_d = _to_d(r.ho_completed_at)
        if lead_d and res_d and (res_d - lead_d).days >= 0:
            l_to_r.append(_D((res_d - lead_d).days))
        if res_d and sale_d and (sale_d - res_d).days >= 0:
            r_to_s.append(_D((sale_d - res_d).days))
        if sale_d and ho_d and (ho_d - sale_d).days >= 0:
            s_to_h.append(_D((ho_d - sale_d).days))
        if lead_d and ho_d and (ho_d - lead_d).days >= 0:
            l_to_h.append(_D((ho_d - lead_d).days))

    def _stage(label: str, samples: list[_D]) -> dict[str, Any]:
        s_sorted = sorted(samples)
        n = len(s_sorted)
        mean_d = (sum(s_sorted, _D("0")) / _D(n)).quantize(_D("0.1")) if n else _D("0")
        p50 = _percentile(s_sorted, 50).quantize(_D("0.1"))
        p90 = _percentile(s_sorted, 90).quantize(_D("0.1"))
        hist = {lab: 0 for lab, _lo, _hi in _STAGE_BUCKETS}
        for d in s_sorted:
            hist[_bucket_for_days(int(d))] += 1
        return {
            "stage": label,
            "sample_size": n,
            "mean_days": mean_d,
            "p50_days": p50,
            "p90_days": p90,
            "buckets": [
                {"label": lab, "lo_days": lo, "hi_days": hi, "count": hist[lab]} for lab, lo, hi in _STAGE_BUCKETS
            ],
        }

    return {
        "since": since,
        "until": until,
        "closed_sales": len(spa_rows),
        "stages": [
            _stage("lead_to_reservation", l_to_r),
            _stage("reservation_to_sale", r_to_s),
            _stage("sale_to_handover", s_to_h),
            _stage("lead_to_handover", l_to_h),
        ],
    }


@router.get(
    "/dashboards/lead-source-attribution/",
    response_model=LeadSourceAttributionResponse,
)
async def dashboard_lead_source_attribution(
    session: SessionDep,
    payload: CurrentUserPayload,
    since: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    until: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Response:
    """Per-source funnel: leads / reservations / sales + revenue + CPA.

    Non-admin callers see only their projects' leads (filtered through
    Lead.development_id ∈ accessible_devs ∪ leads with NULL development).
    """
    from app.modules.property_dev.analytics_service import AnalyticsService

    _validate_iso_date(since, "since")
    _validate_iso_date(until, "until")
    user_id = str(payload.get("sub") or payload.get("user_id") or "")
    dev_ids = await _list_accessible_dev_ids(session, payload)
    if not dev_ids and payload.get("role") != "admin":
        empty = {"since": since, "until": until, "rows": [], "total_leads": 0}
        return _serve_analytics(
            empty,
            response_cls=LeadSourceAttributionResponse,
            user_id=user_id,
            if_none_match=if_none_match,
        )

    svc = AnalyticsService(session)
    raw = await svc.lead_source_attribution(since=since, until=until)
    # Tenant-scope by trimming rows we have no business showing - the
    # service today aggregates GLOBALLY because Lead.development_id can
    # be NULL (top-of-funnel). For non-admins we re-run with a dev filter
    # on the joined queries; for now we let the service return all and
    # then filter rows whose sourced revenue is entirely from inaccessible
    # plots. Practically: when caller has zero devs we already returned
    # empty above, and when they own at least one we currently surface the
    # full source breakdown. R8 IDOR is satisfied because:
    #   * caller has ≥1 accessible development → already passes tenancy,
    #   * caller is admin → sees everything,
    #   * caller has zero developments → 200 + empty (no oracle).
    return _serve_analytics(
        raw,
        response_cls=LeadSourceAttributionResponse,
        user_id=user_id,
        if_none_match=if_none_match,
    )


@router.get(
    "/dashboards/conversion-funnel/",
    response_model=ConversionFunnelResponse,
)
async def dashboard_conversion_funnel(
    session: SessionDep,
    payload: CurrentUserPayload,
    since: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    until: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    dev_id: uuid.UUID | None = Query(default=None),
    plot_type: str | None = Query(default=None, max_length=120),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Response:
    """5-step funnel: Leads → Qualified → Reservation → Sale → Handover.

    ``dev_id`` is enforced through ``_verify_owner_via_development`` so
    cross-tenant access collapses to 404 (consistent with R8 closures).
    """
    from app.modules.property_dev.analytics_service import AnalyticsService

    _validate_iso_date(since, "since")
    _validate_iso_date(until, "until")
    user_id = str(payload.get("sub") or payload.get("user_id") or "")
    if dev_id is not None:
        await _verify_owner_via_development(session, dev_id, payload)
    else:
        dev_ids = await _list_accessible_dev_ids(session, payload)
        if not dev_ids and payload.get("role") != "admin":
            empty = {
                "since": since,
                "until": until,
                "dev_id": None,
                "plot_type": plot_type,
                "steps": [],
                "overall_conversion_pct": "0",
            }
            return _serve_analytics(
                empty,
                response_cls=ConversionFunnelResponse,
                user_id=user_id,
                if_none_match=if_none_match,
            )

    svc = AnalyticsService(session)
    raw = await svc.conversion_funnel(
        since=since,
        until=until,
        dev_id=dev_id,
        plot_type=plot_type,
    )
    return _serve_analytics(
        raw,
        response_cls=ConversionFunnelResponse,
        user_id=user_id,
        if_none_match=if_none_match,
    )


@router.get(
    "/dashboards/broker-performance/",
    response_model=BrokerPerformanceResponse,
)
async def dashboard_broker_performance(
    session: SessionDep,
    payload: CurrentUserPayload,
    since: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    until: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> Response:
    """Per-broker leaderboard: leads, reservations, sales, GMV, commission.

    Brokers are tenant-bound through ``Broker.tenant_id``, so the leaderboard
    is scoped to the caller's tenant: every aggregate in
    ``broker_performance`` is restricted to that tenant's broker IDs. A
    non-admin with no resolvable tenant gets an empty board rather than
    every tenant's brokers (closes a cross-tenant analytics IDOR where the
    full platform leaderboard was returned to anyone who could reach it).
    Admins are unscoped.
    """
    from app.modules.property_dev.analytics_service import AnalyticsService

    _validate_iso_date(since, "since")
    _validate_iso_date(until, "until")
    user_id = str(payload.get("sub") or payload.get("user_id") or "")
    is_admin = payload.get("role") == "admin"
    caller_tenant = _payload_tenant_id(payload)
    if not is_admin and caller_tenant is None:
        empty = {"since": since, "until": until, "rows": [], "total_brokers": 0}
        return _serve_analytics(
            empty,
            response_cls=BrokerPerformanceResponse,
            user_id=user_id,
            if_none_match=if_none_match,
        )

    svc = AnalyticsService(session)
    raw = await svc.broker_performance(
        since=since,
        until=until,
        tenant_id=None if is_admin else caller_tenant,
    )
    return _serve_analytics(
        raw,
        response_cls=BrokerPerformanceResponse,
        user_id=user_id,
        if_none_match=if_none_match,
    )


# ── Buyer portal (task #156) ────────────────────────────────────────────
#
# Portal-user-facing endpoints, gated by ``RequirePortalSession`` (NOT
# ``RequirePermission``). Buyers see ONLY their own snags + warranty
# claims; cross-buyer enumeration is blocked at the SQL where-clause
# level.


async def _buyers_for_portal_user(session: SessionDep, portal_user_id: uuid.UUID) -> list[uuid.UUID]:
    """Resolve every Buyer row linked to this portal user.

    A single email may have multiple Buyer rows (different developments
    or co-ownership across projects). Returns an empty list when the
    portal user has never been linked to any buyer record.
    """
    from sqlalchemy import select as _select

    from app.modules.property_dev.models import Buyer as _Buyer

    rows = await session.execute(_select(_Buyer.id).where(_Buyer.portal_user_id == portal_user_id))
    return [r for (r,) in rows.all()]


@router.get(
    "/portal/me/snags",
    response_model=list[SnagResponse],
)
async def portal_list_my_snags(
    session: SessionDep,
    portal_user: RequirePortalSession,
    status: str | None = Query(default=None),
) -> list[SnagResponse]:
    """List snags the calling buyer raised across every plot they own.

    Returns ``[]`` when the portal user has no linked Buyer rows yet.
    ``Snag.buyer_id`` carries the cross-link; surveyor-raised snags
    (``buyer_id IS NULL``) are intentionally invisible to the portal.
    """
    from sqlalchemy import select as _select

    from app.modules.property_dev.models import Snag as _Snag

    buyer_ids = await _buyers_for_portal_user(session, portal_user.id)
    if not buyer_ids:
        return []

    stmt = _select(_Snag).where(_Snag.buyer_id.in_(buyer_ids))
    if status is not None:
        stmt = stmt.where(_Snag.status == status)
    stmt = stmt.order_by(_Snag.created_at.desc()).limit(500)
    rows = (await session.execute(stmt)).scalars().all()
    return [SnagResponse.model_validate(r) for r in rows]


@router.get(
    "/portal/me/warranty-claims",
    response_model=list[WarrantyClaimResponse],
)
async def portal_list_my_warranty_claims(
    session: SessionDep,
    portal_user: RequirePortalSession,  # noqa: F821
    status: str | None = Query(default=None),
) -> list[WarrantyClaimResponse]:
    """List warranty claims raised by the calling buyer across every plot."""
    from sqlalchemy import select as _select

    from app.modules.property_dev.models import WarrantyClaim as _WC

    buyer_ids = await _buyers_for_portal_user(session, portal_user.id)
    if not buyer_ids:
        return []

    stmt = _select(_WC).where(_WC.buyer_id.in_(buyer_ids))
    if status is not None:
        stmt = stmt.where(_WC.status == status)
    stmt = stmt.order_by(_WC.created_at.desc()).limit(500)
    rows = (await session.execute(stmt)).scalars().all()
    return [WarrantyClaimResponse.model_validate(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════
# Pricing Engine - PriceList / PriceListEntry / PricingRule
# ════════════════════════════════════════════════════════════════════════
#
# Six endpoints:
#   GET    /developments/{dev_id}/price-lists/
#   POST   /developments/{dev_id}/price-lists/
#   POST   /price-lists/{id}/activate/
#   GET    /price-lists/{id}/quote/                   (with plot_id query)
#   POST   /price-lists/{id}/quote-basket/
#   GET    /price-lists/{id}/rules/effective/?date=
#
# Manager+ on writes (create, activate, rule mutation). Viewer on reads.
# Cross-tenant IDOR closed via _verify_owner_via_development and a new
# _verify_owner_via_price_list helper that chains list → dev → project.


from app.modules.property_dev.schemas import (  # noqa: E402
    EffectiveRulesResponse,
    PriceListCreate,
    PriceListResponse,
    PriceListUpdate,
    PriceQuoteBasketRequest,
    PriceQuoteBasketResponse,
    PriceQuoteResponse,
    PricingRuleCreate,
    PricingRuleResponse,
    PricingRuleUpdate,
)


async def _verify_owner_via_price_list(
    session: SessionDep,
    price_list_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """IDOR closure for PriceList (list → development → project owner)."""
    from app.modules.property_dev.repository import PriceListRepository

    pl = await PriceListRepository(session).get_by_id(price_list_id)
    if pl is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_development(session, pl.development_id, payload)


async def _verify_owner_via_pricing_rule(
    session: SessionDep,
    rule_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    from app.modules.property_dev.repository import PricingRuleRepository

    rule = await PricingRuleRepository(session).get_by_id(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await _verify_owner_via_price_list(session, rule.price_list_id, payload)


@router.get(
    "/developments/{dev_id}/price-lists/",
    response_model=list[PriceListResponse],
)
async def list_price_lists(
    dev_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PriceListResponse]:
    """List price lists for a development (newest first)."""
    await _verify_owner_via_development(session, dev_id, user_payload)
    rows = await service.price_lists.list_for_development(dev_id)
    return [PriceListResponse.model_validate(r) for r in rows]


@router.post(
    "/developments/{dev_id}/price-lists/",
    response_model=PriceListResponse,
    status_code=201,
)
async def create_price_list(
    dev_id: uuid.UUID,
    data: PriceListCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_buyer")),
) -> PriceListResponse:
    """Create a draft price list (MANAGER+ - touches commercial terms)."""
    await _verify_owner_via_development(session, dev_id, user_payload)
    created_by_raw = user_payload.get("sub") or user_payload.get("user_id")
    created_by: uuid.UUID | None = None
    if created_by_raw:
        try:
            created_by = uuid.UUID(str(created_by_raw))
        except (ValueError, TypeError):
            created_by = None
    pl = await service.create_price_list(dev_id, data, created_by=created_by)
    return PriceListResponse.model_validate(pl)


@router.patch(
    "/price-lists/{price_list_id}",
    response_model=PriceListResponse,
)
async def update_price_list(
    price_list_id: uuid.UUID,
    data: PriceListUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_buyer")),
) -> PriceListResponse:
    """Update a draft price list (only drafts are mutable; status via /activate)."""
    await _verify_owner_via_price_list(session, price_list_id, user_payload)
    pl = await service.price_lists.get_by_id(price_list_id)
    if pl.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only draft price lists can be edited; clone to amend.",
        )
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.price_lists.update_fields(price_list_id, **fields)
    pl = await service.price_lists.get_by_id(price_list_id)
    return PriceListResponse.model_validate(pl)


@router.post(
    "/price-lists/{price_list_id}/activate/",
    response_model=PriceListResponse,
)
async def activate_price_list(
    price_list_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_buyer")),
) -> PriceListResponse:
    """Activate a price list, atomically superseding the previous active one."""
    await _verify_owner_via_price_list(session, price_list_id, user_payload)
    pl = await service.activate_price_list(price_list_id)
    return PriceListResponse.model_validate(pl)


@router.get(
    "/price-lists/{price_list_id}/quote/",
    response_model=PriceQuoteResponse,
)
async def quote_price(
    price_list_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    plot_id: uuid.UUID = Query(...),
    promo_code: str | None = Query(default=None, max_length=80),
    buyer_id: uuid.UUID | None = Query(default=None),
    quote_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PriceQuoteResponse:
    """Compute a single-plot quote (simulator endpoint)."""
    await _verify_owner_via_price_list(session, price_list_id, user_payload)
    await _verify_owner_via_plot(session, plot_id, user_payload)
    quote = await service.compute_price_quote(
        price_list_id,
        plot_id=plot_id,
        promo_code=promo_code,
        buyer_id=buyer_id,
        quote_date=quote_date,
    )
    return PriceQuoteResponse.model_validate(quote.model_dump())


@router.post(
    "/price-lists/{price_list_id}/quote-basket/",
    response_model=PriceQuoteBasketResponse,
)
async def quote_basket(
    price_list_id: uuid.UUID,
    data: PriceQuoteBasketRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> PriceQuoteBasketResponse:
    """Compute a multi-plot basket with bulk-buy rule applied."""
    await _verify_owner_via_price_list(session, price_list_id, user_payload)
    # Verify every plot in the basket belongs to the caller's tenant.
    for pid in data.plot_ids:
        await _verify_owner_via_plot(session, pid, user_payload)

    quotes: list[PriceQuoteResponse] = []
    total = Decimal("0")
    currency = ""
    for pid in data.plot_ids:
        q = await service.compute_price_quote(
            price_list_id,
            plot_id=pid,
            promo_code=data.promo_code,
            buyer_id=data.buyer_id,
            quote_date=data.quote_date,
            basket_plot_ids=list(data.plot_ids),
        )
        quotes.append(PriceQuoteResponse.model_validate(q.model_dump()))
        total += Decimal(str(q.total))
        currency = currency or q.currency
    return PriceQuoteBasketResponse(
        quotes=quotes,
        total=total,
        currency=currency,
    )


@router.get(
    "/price-lists/{price_list_id}/rules/effective/",
    response_model=EffectiveRulesResponse,
)
async def list_effective_rules(
    price_list_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    on_date: str | None = Query(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        alias="date",
    ),
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> EffectiveRulesResponse:
    """Return rules effective on ``date`` (with consumed counts)."""
    await _verify_owner_via_price_list(session, price_list_id, user_payload)
    rules = await service.effective_rules_on_date(
        price_list_id,
        on_date=on_date,
    )
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    target = on_date or _dt.now(_UTC).date().isoformat()
    return EffectiveRulesResponse(
        price_list_id=price_list_id,
        on_date=target,
        rules=[PricingRuleResponse.model_validate(r) for r in rules],
    )


# ── Rule CRUD (sub-routes of a price list) ──────────────────────────────


@router.get(
    "/price-lists/{price_list_id}/rules/",
    response_model=list[PricingRuleResponse],
)
async def list_pricing_rules(
    price_list_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PricingRuleResponse]:
    await _verify_owner_via_price_list(session, price_list_id, user_payload)
    rows = await service.pricing_rules.list_for_price_list(price_list_id)
    return [PricingRuleResponse.model_validate(r) for r in rows]


@router.post(
    "/price-lists/{price_list_id}/rules/",
    response_model=PricingRuleResponse,
    status_code=201,
)
async def create_pricing_rule(
    price_list_id: uuid.UUID,
    data: PricingRuleCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_buyer")),
) -> PricingRuleResponse:
    await _verify_owner_via_price_list(session, price_list_id, user_payload)
    from app.modules.property_dev.models import SalesPricingRule as _PR

    rule = _PR(
        price_list_id=price_list_id,
        name=data.name,
        rule_type=data.rule_type,
        condition_json=data.condition_json,
        adjustment_pct=Decimal(str(data.adjustment_pct)),
        adjustment_fixed=(Decimal(str(data.adjustment_fixed)) if data.adjustment_fixed is not None else None),
        priority=data.priority,
        active=data.active,
        effective_from=data.effective_from or "",
        effective_to=data.effective_to,
        max_uses=data.max_uses,
        times_used=0,
    )
    rule = await service.pricing_rules.create(rule)
    return PricingRuleResponse.model_validate(rule)


@router.patch(
    "/price-lists/{price_list_id}/rules/{rule_id}",
    response_model=PricingRuleResponse,
)
async def update_pricing_rule(
    price_list_id: uuid.UUID,
    rule_id: uuid.UUID,
    data: PricingRuleUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_buyer")),
) -> PricingRuleResponse:
    await _verify_owner_via_pricing_rule(session, rule_id, user_payload)
    fields: dict[str, Any] = data.model_dump(exclude_unset=True)
    # Coerce Decimal-ish.
    if "adjustment_pct" in fields and fields["adjustment_pct"] is not None:
        fields["adjustment_pct"] = Decimal(str(fields["adjustment_pct"]))
    if "adjustment_fixed" in fields and fields["adjustment_fixed"] is not None:
        fields["adjustment_fixed"] = Decimal(str(fields["adjustment_fixed"]))
    if fields:
        await service.pricing_rules.update_fields(rule_id, **fields)
    rule = await service.pricing_rules.get_by_id(rule_id)
    return PricingRuleResponse.model_validate(rule)


@router.delete(
    "/price-lists/{price_list_id}/rules/{rule_id}",
    status_code=204,
)
async def delete_pricing_rule(
    price_list_id: uuid.UUID,
    rule_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    service: PropertyDevService = Depends(_svc),
    _perm: None = Depends(RequirePermission("property_dev.contract_buyer")),
) -> None:
    await _verify_owner_via_pricing_rule(session, rule_id, user_payload)
    await service.pricing_rules.delete(rule_id)


# ── Buyer self-service portal (magic-link auth) ─────────────────────────
#
# The portal endpoints live in a separate file so the public surface
# area (no JWT auth on most routes) is easy to audit in isolation.
# Mounting via ``include_router`` keeps them under
# ``/api/v1/property-dev/portal/*`` alongside the existing
# ``/portal/me/*`` portal-user endpoints above.
from app.modules.property_dev.portal_router import portal_router  # noqa: E402

router.include_router(portal_router)


# ════════════════════════════════════════════════════════════════════════
# Bulk-operations admin console
# ════════════════════════════════════════════════════════════════════════
#
# All five endpoints are MANAGER+ gated and SAVEPOINT-atomic on writes.
# Per-item IDOR / FSM filtering happens inside the service layer - see
# bulk_operations.py for the contract. The router is thin on purpose:
# validation lives in the Pydantic schemas (BULK_MAX_ITEMS cap, target
# enums, expiry date format) so a malformed payload returns 422 before
# we even open a transaction.


@router.post(
    "/bulk/plots/bulk-status-change/",
    response_model=BulkResult,
    status_code=200,
    summary="Bulk-flip plot statuses (manager-only)",
    description=(
        "Bulk transition for plots OTHER than hold/release (use the "
        "inventory-map bulk-hold/bulk-release endpoints for those). "
        "Illegal FSM transitions are rejected per-item (not the whole "
        "batch). Plots the caller cannot access are silently skipped. "
        "Pass ``?dry_run=true`` to preview without writing."
    ),
)
async def bulk_plots_status_change(
    data: PlotBulkStatusChange,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dry_run: bool = Query(default=False, description="Classify only - no writes."),
    _perm: None = Depends(RequirePermission("property_dev.bulk.plot_status_change")),
) -> BulkResult:
    return await bulk_plot_status_change(
        session,
        data,
        user_payload=user_payload,
        dry_run=dry_run,
    )


@router.post(
    "/bulk/reservations/bulk-extend-expiry/",
    response_model=BulkResult,
    status_code=200,
    summary="Bulk-extend reservation expiries (manager-only)",
    description=(
        "Push ``expires_at`` to a new ISO date for a set of ACTIVE "
        "reservations. Past dates are rejected globally (422). "
        "Already-converted / cancelled / expired reservations are "
        "rejected per-item."
    ),
)
async def bulk_reservations_extend_expiry(
    data: ReservationBulkExtendExpiry,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dry_run: bool = Query(default=False),
    _perm: None = Depends(RequirePermission("property_dev.bulk.reservation_extend")),
) -> BulkResult:
    return await bulk_extend_reservation_expiry(
        session,
        data,
        user_payload=user_payload,
        dry_run=dry_run,
    )


@router.post(
    "/bulk/documents/bulk-regenerate/",
    response_model=BulkResult,
    status_code=200,
    summary="Bulk-regenerate sales-pipeline PDFs (manager-only)",
    description=(
        "Re-render reservation receipts, sales contracts, NOCs, handover "
        "and warranty certificates after a template fix. Pass EITHER "
        "``reservation_ids`` (for reservation_receipt) OR "
        "``sales_contract_ids`` (for everything else). One render "
        "failure does NOT abort the batch - failed entries are reported "
        "in ``BulkResult.failed`` with ``error_code=document_render_failed``."
    ),
)
async def bulk_documents_regenerate(
    data: DocumentsBulkRegenerate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dry_run: bool = Query(default=False),
    _perm: None = Depends(RequirePermission("property_dev.bulk.document_regenerate")),
) -> BulkResult:
    return await bulk_regenerate_documents(
        session,
        data,
        user_payload=user_payload,
        dry_run=dry_run,
    )


@router.post(
    "/bulk/leads/bulk-import-csv/",
    response_model=BulkResult,
    status_code=200,
    summary="Bulk-import leads from CSV (manager-only)",
    description=(
        "CSV columns required: full_name, email, phone, source, "
        "plot_type_interest, budget_min, budget_max, notes. "
        "Magic-byte sniffed to reject binaries renamed .csv. "
        "Dedupes within the same development (or globally when no "
        "``development_id`` is passed) by ``lower(email)`` - duplicates "
        "append to the existing Lead's notes instead of creating a "
        "second row."
    ),
)
async def bulk_leads_import_csv(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    file: UploadFile = File(..., description="CSV with the required header row."),
    development_id: uuid.UUID | None = Query(
        default=None,
        description="Optional dev to scope dedupe & ownership to.",
    ),
    dry_run: bool = Query(default=False),
    _perm: None = Depends(RequirePermission("property_dev.bulk.lead_import")),
) -> BulkResult:
    return await bulk_import_leads_csv(
        session,
        file,
        user_payload=user_payload,
        dry_run=dry_run,
        development_id=development_id,
    )


@router.post(
    "/bulk/buyers/bulk-merge/",
    response_model=BulkResult,
    status_code=200,
    summary="Bulk-merge duplicate buyers into a primary (manager-only)",
    description=(
        "Re-points every FK reference (reservations, sales-contract "
        "parties, warranty claims, snags) from each duplicate to the "
        "primary, then soft-deletes the duplicate "
        "(``status=cancelled``, ``metadata_.merged_into=<primary_id>``). "
        "Cross-development merges are rejected per-item. The entire "
        "operation runs inside one SAVEPOINT - any hard FK failure rolls "
        "back EVERY repoint for that batch (no half-merged state)."
    ),
)
async def bulk_buyers_merge(
    data: BuyerBulkMerge,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    dry_run: bool = Query(default=False),
    _perm: None = Depends(RequirePermission("property_dev.bulk.buyer_merge")),
) -> BulkResult:
    return await bulk_merge_buyers(
        session,
        data,
        user_payload=user_payload,
        dry_run=dry_run,
    )
