# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Construction-control API routes.

Acceptance criteria:
    GET    /criteria                       - list criteria for a project
    POST   /criteria                       - create a criterion
    GET    /criteria/{criterion_id}        - get one
    PATCH  /criteria/{criterion_id}        - update
    DELETE /criteria/{criterion_id}        - delete

Inspections:
    GET    /inspections                    - list inspections for a project
    POST   /inspections                    - create an inspection (optional model link)
    GET    /inspections/{inspection_id}    - get one (with resolved element links)
    PATCH  /inspections/{inspection_id}    - update
    DELETE /inspections/{inspection_id}    - delete
    POST   /inspections/{inspection_id}/record-result - record pass/fail; a fail raises an NCR

As-built records (Pillar 3):
    GET    /asbuilt                        - list as-built records for a project
    POST   /asbuilt                        - create an as-built record (optional model link)
    POST   /asbuilt/import-from-scan       - create one from a point-cloud scan registration
    GET    /asbuilt/{record_id}            - get one (with resolved element links)
    PATCH  /asbuilt/{record_id}            - update (blocked once recorded/void)
    DELETE /asbuilt/{record_id}            - delete
    POST   /asbuilt/{record_id}/record-survey - record the captured value + tolerance
    POST   /asbuilt/{record_id}/verify     - verify; out-of-tolerance raises an NCR
    POST   /asbuilt/{record_id}/sign-validity - e-sign the legal-record attestation

Hold gates (Pillar 5):
    GET    /gates                          - list gates for a project
    POST   /gates                          - create a gate
    GET    /gates/can-proceed              - check if an attached entity is gated
    GET    /gates/{gate_id}                - get one
    PATCH  /gates/{gate_id}                - update (blocked once not pending)
    DELETE /gates/{gate_id}                - delete
    POST   /gates/{gate_id}/release        - release (party-role checked, e-signed)
    POST   /gates/{gate_id}/waive          - waive (witness/surveillance/review only)

Handover packages (Pillar 4):
    GET    /handover                       - list handover packages for a project
    POST   /handover                       - create a handover package (optional model link)
    GET    /handover/{package_id}          - get one (with resolved element links)
    PATCH  /handover/{package_id}          - update (blocked once issued/revoked)
    DELETE /handover/{package_id}          - delete
    GET    /handover/{package_id}/gates    - the computed completion gate
    POST   /handover/{package_id}/assemble - auto-assemble the acceptance-evidence manifest
    POST   /handover/{package_id}/override-gate - override a blocked gate (raises a doc NCR)
    POST   /handover/{package_id}/issue    - e-sign and issue the acceptance certificate
    POST   /handover/{package_id}/revoke   - revoke an issued certificate
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.construction_control.asbuilt_service import AsBuiltService
from app.modules.construction_control.gating_service import GatingService
from app.modules.construction_control.handover_service import HandoverService
from app.modules.construction_control.schemas import (
    AcceptanceCriterionCreate,
    AcceptanceCriterionResponse,
    AcceptanceCriterionUpdate,
    AsBuiltImportFromScanIn,
    AsBuiltRecordCreate,
    AsBuiltRecordResponse,
    AsBuiltRecordUpdate,
    AsBuiltSignIn,
    AsBuiltSurveyIn,
    AsBuiltVerifyIn,
    ElementRefResponse,
    GateProceedResponse,
    HandoverGateReport,
    HandoverIssueIn,
    HandoverOverrideIn,
    HandoverPackageCreate,
    HandoverPackageResponse,
    HandoverPackageUpdate,
    HoldGateCreate,
    HoldGateReleaseIn,
    HoldGateResponse,
    HoldGateUpdate,
    HoldGateWaiveIn,
    InspectionCreate,
    InspectionResponse,
    InspectionResultIn,
    InspectionUpdate,
    MaterialRecordCreate,
    MaterialRecordResponse,
    MaterialRecordUpdate,
    MaterialReviewIn,
    TestResultCreate,
    TestResultRecordIn,
    TestResultResponse,
    TestResultUpdate,
)
from app.modules.construction_control.service import ConstructionControlService, is_material_expired

router = APIRouter(tags=["construction-control"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ConstructionControlService:
    return ConstructionControlService(session)


def _get_asbuilt_service(session: SessionDep) -> AsBuiltService:
    return AsBuiltService(session)


def _get_gating_service(session: SessionDep) -> GatingService:
    return GatingService(session)


def _get_handover_service(session: SessionDep) -> HandoverService:
    return HandoverService(session)


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP for signature non-repudiation context (never authorisation).

    ``X-Forwarded-For`` is believed only from a configured trusted proxy; any other
    caller is recorded by its socket peer (``app.core.rate_limiter.client_ip``).
    """
    from app.core.rate_limiter import client_ip

    ip = client_ip(request)
    return ip[:64] if ip else None


def _asbuilt_response(record, elements) -> AsBuiltRecordResponse:
    resp = AsBuiltRecordResponse.model_validate(record)
    resp.elements = [ElementRefResponse.model_validate(e) for e in elements]
    return resp


def _gate_response(gate) -> HoldGateResponse:
    return HoldGateResponse.model_validate(gate)


def _handover_response(package, elements) -> HandoverPackageResponse:
    resp = HandoverPackageResponse.model_validate(package)
    resp.elements = [ElementRefResponse.model_validate(e) for e in elements]
    return resp


def _criterion_response(criterion) -> AcceptanceCriterionResponse:
    return AcceptanceCriterionResponse.model_validate(criterion)


def _inspection_response(inspection, elements) -> InspectionResponse:
    resp = InspectionResponse.model_validate(inspection)
    resp.elements = [ElementRefResponse.model_validate(e) for e in elements]
    return resp


def _material_response(material, elements) -> MaterialRecordResponse:
    resp = MaterialRecordResponse.model_validate(material)
    resp.is_expired = is_material_expired(material)
    resp.elements = [ElementRefResponse.model_validate(e) for e in elements]
    return resp


def _test_response(test, elements) -> TestResultResponse:
    resp = TestResultResponse.model_validate(test)
    resp.elements = [ElementRefResponse.model_validate(e) for e in elements]
    return resp


# ── Acceptance criteria ───────────────────────────────────────────────────────


@router.get("/criteria", response_model=list[AcceptanceCriterionResponse])
async def list_criteria(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    category: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    service: ConstructionControlService = Depends(_get_service),
) -> list[AcceptanceCriterionResponse]:
    """List the acceptance criteria for a project: the pass/fail rules every inspection,
    test and survey is judged against (what is measured, the standard, and the tolerance)."""
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_criteria(
        project_id, offset=offset, limit=limit, category=category, is_active=is_active
    )
    return [_criterion_response(c) for c in items]


@router.post("/criteria", response_model=AcceptanceCriterionResponse, status_code=201)
async def create_criterion(
    data: AcceptanceCriterionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.criterion.create")),
    service: ConstructionControlService = Depends(_get_service),
) -> AcceptanceCriterionResponse:
    """Create an acceptance criterion: a reusable pass/fail rule (characteristic, standard,
    tolerance) that inspections, tests and as-built surveys are then checked against."""
    await verify_project_access(data.project_id, user_id, session)
    criterion = await service.create_criterion(data, user_id=user_id)
    return _criterion_response(criterion)


@router.get("/criteria/{criterion_id}", response_model=AcceptanceCriterionResponse)
async def get_criterion(
    criterion_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ConstructionControlService = Depends(_get_service),
) -> AcceptanceCriterionResponse:
    criterion = await service.get_criterion(criterion_id)
    await verify_project_access(criterion.project_id, str(user_id), session)
    return _criterion_response(criterion)


@router.patch("/criteria/{criterion_id}", response_model=AcceptanceCriterionResponse)
async def update_criterion(
    criterion_id: uuid.UUID,
    data: AcceptanceCriterionUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.criterion.update")),
    service: ConstructionControlService = Depends(_get_service),
) -> AcceptanceCriterionResponse:
    existing = await service.get_criterion(criterion_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    criterion = await service.update_criterion(criterion_id, data)
    return _criterion_response(criterion)


@router.delete("/criteria/{criterion_id}", status_code=204)
async def delete_criterion(
    criterion_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.criterion.delete")),
    service: ConstructionControlService = Depends(_get_service),
) -> None:
    existing = await service.get_criterion(criterion_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_criterion(criterion_id)


# ── Inspections ───────────────────────────────────────────────────────────────


@router.get("/inspections", response_model=list[InspectionResponse])
async def list_inspections(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    party_role: str | None = Query(default=None),
    service: ConstructionControlService = Depends(_get_service),
) -> list[InspectionResponse]:
    """List inspection and acceptance records for a project, with their model links and
    recorded pass/fail result. Filter by type, status or the party who carried them out."""
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_inspections(
        project_id,
        offset=offset,
        limit=limit,
        inspection_type=type_filter,
        status_filter=status_filter,
        party_role=party_role,
    )
    elements_by_owner = await service.elements_for_many([i.id for i in items])
    return [_inspection_response(i, elements_by_owner.get(str(i.id), [])) for i in items]


@router.post("/inspections", response_model=InspectionResponse, status_code=201)
async def create_inspection(
    data: InspectionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.inspection.create")),
    service: ConstructionControlService = Depends(_get_service),
) -> InspectionResponse:
    await verify_project_access(data.project_id, user_id, session)
    inspection = await service.create_inspection(data, user_id=user_id)
    elements = await service.elements_for(inspection.id)
    return _inspection_response(inspection, elements)


@router.get("/inspections/{inspection_id}", response_model=InspectionResponse)
async def get_inspection(
    inspection_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ConstructionControlService = Depends(_get_service),
) -> InspectionResponse:
    inspection = await service.get_inspection(inspection_id)
    await verify_project_access(inspection.project_id, str(user_id), session)
    elements = await service.elements_for(inspection.id)
    return _inspection_response(inspection, elements)


@router.patch("/inspections/{inspection_id}", response_model=InspectionResponse)
async def update_inspection(
    inspection_id: uuid.UUID,
    data: InspectionUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.inspection.update")),
    service: ConstructionControlService = Depends(_get_service),
) -> InspectionResponse:
    existing = await service.get_inspection(inspection_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    inspection = await service.update_inspection(inspection_id, data)
    elements = await service.elements_for(inspection.id)
    return _inspection_response(inspection, elements)


@router.delete("/inspections/{inspection_id}", status_code=204)
async def delete_inspection(
    inspection_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.inspection.delete")),
    service: ConstructionControlService = Depends(_get_service),
) -> None:
    existing = await service.get_inspection(inspection_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_inspection(inspection_id)


@router.post("/inspections/{inspection_id}/record-result", response_model=InspectionResponse)
async def record_inspection_result(
    inspection_id: uuid.UUID,
    data: InspectionResultIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.inspection.record_result")),
    service: ConstructionControlService = Depends(_get_service),
) -> InspectionResponse:
    """Record the outcome. A fail (or conditional) raises a linked NCR."""
    inspection = await service.get_inspection(inspection_id)
    await verify_project_access(inspection.project_id, user_id, session)
    inspection = await service.record_result(inspection_id, data, user_id=user_id)
    elements = await service.elements_for(inspection.id)
    return _inspection_response(inspection, elements)


# ── Material records (digital passport, EN 10204) ─────────────────────────────


@router.get("/materials", response_model=list[MaterialRecordResponse])
async def list_materials(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    material_type: str | None = Query(default=None),
    gr_id: str | None = Query(default=None),
    service: ConstructionControlService = Depends(_get_service),
) -> list[MaterialRecordResponse]:
    """List material records (the digital material passport) for a project: certificate,
    traceability and review status. Each record flags whether its certificate has expired."""
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_materials(
        project_id, offset=offset, limit=limit, status_filter=status_filter, material_type=material_type, gr_id=gr_id
    )
    elements_by_owner = await service.elements_for_owners("material_record", [m.id for m in items])
    return [_material_response(m, elements_by_owner.get(str(m.id), [])) for m in items]


@router.post("/materials", response_model=MaterialRecordResponse, status_code=201)
async def create_material(
    data: MaterialRecordCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.material.create")),
    service: ConstructionControlService = Depends(_get_service),
) -> MaterialRecordResponse:
    await verify_project_access(data.project_id, user_id, session)
    material = await service.create_material(data, user_id=user_id)
    elements = await service.elements_for_owner("material_record", material.id)
    return _material_response(material, elements)


@router.get("/materials/{material_id}", response_model=MaterialRecordResponse)
async def get_material(
    material_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ConstructionControlService = Depends(_get_service),
) -> MaterialRecordResponse:
    material = await service.get_material(material_id)
    await verify_project_access(material.project_id, str(user_id), session)
    elements = await service.elements_for_owner("material_record", material.id)
    return _material_response(material, elements)


@router.patch("/materials/{material_id}", response_model=MaterialRecordResponse)
async def update_material(
    material_id: uuid.UUID,
    data: MaterialRecordUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.material.update")),
    service: ConstructionControlService = Depends(_get_service),
) -> MaterialRecordResponse:
    existing = await service.get_material(material_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    material = await service.update_material(material_id, data)
    elements = await service.elements_for_owner("material_record", material.id)
    return _material_response(material, elements)


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(
    material_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.material.delete")),
    service: ConstructionControlService = Depends(_get_service),
) -> None:
    existing = await service.get_material(material_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_material(material_id)


@router.post("/materials/{material_id}/review", response_model=MaterialRecordResponse)
async def review_material(
    material_id: uuid.UUID,
    data: MaterialReviewIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.material.review")),
    service: ConstructionControlService = Depends(_get_service),
) -> MaterialRecordResponse:
    """Record a conformity decision. A reject (or conditional) raises a material NCR."""
    material = await service.get_material(material_id)
    await verify_project_access(material.project_id, user_id, session)
    material = await service.review_material(material_id, data, user_id=user_id)
    elements = await service.elements_for_owner("material_record", material.id)
    return _material_response(material, elements)


# ── Test results (ISO/IEC 17025 lab) ──────────────────────────────────────────


@router.get("/test-results", response_model=list[TestResultResponse])
async def list_test_results(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    result: str | None = Query(default=None),
    material_record_id: str | None = Query(default=None),
    service: ConstructionControlService = Depends(_get_service),
) -> list[TestResultResponse]:
    """List material and field test results for a project, each judged against a criterion
    and carrying its laboratory and accreditation. Filter by status, outcome or material."""
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_test_results(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        result=result,
        material_record_id=material_record_id,
    )
    elements_by_owner = await service.elements_for_owners("test_result", [t.id for t in items])
    return [_test_response(t, elements_by_owner.get(str(t.id), [])) for t in items]


@router.post("/test-results", response_model=TestResultResponse, status_code=201)
async def create_test_result(
    data: TestResultCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.test.create")),
    service: ConstructionControlService = Depends(_get_service),
) -> TestResultResponse:
    await verify_project_access(data.project_id, user_id, session)
    test = await service.create_test_result(data, user_id=user_id)
    elements = await service.elements_for_owner("test_result", test.id)
    return _test_response(test, elements)


@router.get("/test-results/{result_id}", response_model=TestResultResponse)
async def get_test_result(
    result_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ConstructionControlService = Depends(_get_service),
) -> TestResultResponse:
    test = await service.get_test_result(result_id)
    await verify_project_access(test.project_id, str(user_id), session)
    elements = await service.elements_for_owner("test_result", test.id)
    return _test_response(test, elements)


@router.patch("/test-results/{result_id}", response_model=TestResultResponse)
async def update_test_result(
    result_id: uuid.UUID,
    data: TestResultUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.test.update")),
    service: ConstructionControlService = Depends(_get_service),
) -> TestResultResponse:
    existing = await service.get_test_result(result_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    test = await service.update_test_result(result_id, data)
    elements = await service.elements_for_owner("test_result", test.id)
    return _test_response(test, elements)


@router.delete("/test-results/{result_id}", status_code=204)
async def delete_test_result(
    result_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.test.delete")),
    service: ConstructionControlService = Depends(_get_service),
) -> None:
    existing = await service.get_test_result(result_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_test_result(result_id)


@router.post("/test-results/{result_id}/record-result", response_model=TestResultResponse)
async def record_test_result(
    result_id: uuid.UUID,
    data: TestResultRecordIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.test.record_result")),
    service: ConstructionControlService = Depends(_get_service),
) -> TestResultResponse:
    """Record a test outcome. A fail (or conditional) raises a linked NCR."""
    test = await service.get_test_result(result_id)
    await verify_project_access(test.project_id, user_id, session)
    test = await service.record_test_result(result_id, data, user_id=user_id)
    elements = await service.elements_for_owner("test_result", test.id)
    return _test_response(test, elements)


# ── As-built records (Pillar 3) ───────────────────────────────────────────────


@router.get("/asbuilt", response_model=list[AsBuiltRecordResponse])
async def list_asbuilt(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    discipline: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> list[AsBuiltRecordResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_asbuilt(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        discipline=discipline,
        source_kind=source_kind,
    )
    elements_by_owner = await service.elements_for_many([r.id for r in items])
    return [_asbuilt_response(r, elements_by_owner.get(str(r.id), [])) for r in items]


@router.post("/asbuilt", response_model=AsBuiltRecordResponse, status_code=201)
async def create_asbuilt(
    data: AsBuiltRecordCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.asbuilt.create")),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> AsBuiltRecordResponse:
    await verify_project_access(data.project_id, user_id, session)
    record = await service.create_asbuilt(data, user_id=user_id)
    elements = await service.elements_for(record.id)
    return _asbuilt_response(record, elements)


@router.post("/asbuilt/import-from-scan", response_model=AsBuiltRecordResponse, status_code=201)
async def import_asbuilt_from_scan(
    data: AsBuiltImportFromScanIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.asbuilt.create")),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> AsBuiltRecordResponse:
    """Create an as-built from a point-cloud scan registration (deviation result)."""
    await verify_project_access(data.project_id, user_id, session)
    record = await service.import_from_scan(data, user_id=user_id)
    elements = await service.elements_for(record.id)
    return _asbuilt_response(record, elements)


@router.get("/asbuilt/{record_id}", response_model=AsBuiltRecordResponse)
async def get_asbuilt(
    record_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> AsBuiltRecordResponse:
    record = await service.get_asbuilt(record_id)
    await verify_project_access(record.project_id, str(user_id), session)
    elements = await service.elements_for(record.id)
    return _asbuilt_response(record, elements)


@router.patch("/asbuilt/{record_id}", response_model=AsBuiltRecordResponse)
async def update_asbuilt(
    record_id: uuid.UUID,
    data: AsBuiltRecordUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.asbuilt.update")),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> AsBuiltRecordResponse:
    existing = await service.get_asbuilt(record_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    record = await service.update_asbuilt(record_id, data)
    elements = await service.elements_for(record.id)
    return _asbuilt_response(record, elements)


@router.delete("/asbuilt/{record_id}", status_code=204)
async def delete_asbuilt(
    record_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.asbuilt.delete")),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> None:
    existing = await service.get_asbuilt(record_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_asbuilt(record_id)


@router.post("/asbuilt/{record_id}/record-survey", response_model=AsBuiltRecordResponse)
async def record_asbuilt_survey(
    record_id: uuid.UUID,
    data: AsBuiltSurveyIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.asbuilt.update")),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> AsBuiltRecordResponse:
    """Record the captured value and compute the tolerance result against the criterion."""
    record = await service.get_asbuilt(record_id)
    await verify_project_access(record.project_id, user_id, session)
    record = await service.record_survey(record_id, data, user_id=user_id)
    elements = await service.elements_for(record.id)
    return _asbuilt_response(record, elements)


@router.post("/asbuilt/{record_id}/verify", response_model=AsBuiltRecordResponse)
async def verify_asbuilt(
    record_id: uuid.UUID,
    data: AsBuiltVerifyIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.asbuilt.verify")),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> AsBuiltRecordResponse:
    """Verify a surveyed as-built. An out-of-tolerance record raises a workmanship NCR."""
    record = await service.get_asbuilt(record_id)
    await verify_project_access(record.project_id, user_id, session)
    record = await service.verify_asbuilt(record_id, data, user_id=user_id)
    elements = await service.elements_for(record.id)
    return _asbuilt_response(record, elements)


@router.post("/asbuilt/{record_id}/sign-validity", response_model=AsBuiltRecordResponse)
async def sign_asbuilt_validity(
    record_id: uuid.UUID,
    data: AsBuiltSignIn,
    request: Request,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.asbuilt.sign")),
    service: AsBuiltService = Depends(_get_asbuilt_service),
) -> AsBuiltRecordResponse:
    """E-sign the legal-record attestation. Only a verified record can be signed valid."""
    record = await service.get_asbuilt(record_id)
    await verify_project_access(record.project_id, user_id, session)
    record = await service.sign_legal_validity(record_id, data, user_id=user_id, signature_ip=_client_ip(request))
    elements = await service.elements_for(record.id)
    return _asbuilt_response(record, elements)


# ── Hold gates (Pillar 5) ──────────────────────────────────────────────────────


@router.get("/gates", response_model=list[HoldGateResponse])
async def list_gates(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    point_type: str | None = Query(default=None),
    attached_kind: str | None = Query(default=None),
    attached_id: str | None = Query(default=None),
    service: GatingService = Depends(_get_gating_service),
) -> list[HoldGateResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_gates(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        point_type=point_type,
        attached_kind=attached_kind,
        attached_id=attached_id,
    )
    return [_gate_response(g) for g in items]


@router.post("/gates", response_model=HoldGateResponse, status_code=201)
async def create_gate(
    data: HoldGateCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.gate.create")),
    service: GatingService = Depends(_get_gating_service),
) -> HoldGateResponse:
    await verify_project_access(data.project_id, user_id, session)
    gate = await service.create_gate(data, user_id=user_id)
    return _gate_response(gate)


@router.get("/gates/can-proceed", response_model=GateProceedResponse)
async def gate_can_proceed(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    kind: str = Query(...),
    id: str = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: GatingService = Depends(_get_gating_service),
) -> GateProceedResponse:
    """Whether an attached entity (activity / handover_package / inspection) may proceed."""
    await verify_project_access(project_id, user_id, session)
    blocking = await service.blocking_gates_for(project_id, kind, id)
    return GateProceedResponse(
        project_id=project_id,
        attached_kind=kind,
        attached_id=id,
        can_proceed=not blocking,
        blocking_gate_numbers=[g.gate_number for g in blocking],
        blocking_gate_ids=[str(g.id) for g in blocking],
    )


@router.get("/gates/{gate_id}", response_model=HoldGateResponse)
async def get_gate(
    gate_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: GatingService = Depends(_get_gating_service),
) -> HoldGateResponse:
    gate = await service.get_gate(gate_id)
    await verify_project_access(gate.project_id, str(user_id), session)
    return _gate_response(gate)


@router.patch("/gates/{gate_id}", response_model=HoldGateResponse)
async def update_gate(
    gate_id: uuid.UUID,
    data: HoldGateUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.gate.update")),
    service: GatingService = Depends(_get_gating_service),
) -> HoldGateResponse:
    existing = await service.get_gate(gate_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    gate = await service.update_gate(gate_id, data)
    return _gate_response(gate)


@router.delete("/gates/{gate_id}", status_code=204)
async def delete_gate(
    gate_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.gate.delete")),
    service: GatingService = Depends(_get_gating_service),
) -> None:
    existing = await service.get_gate(gate_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_gate(gate_id)


@router.post("/gates/{gate_id}/release", response_model=HoldGateResponse)
async def release_gate(
    gate_id: uuid.UUID,
    data: HoldGateReleaseIn,
    request: Request,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.gate.release")),
    service: GatingService = Depends(_get_gating_service),
) -> HoldGateResponse:
    """Release a gate. The asserted party role must satisfy the gate's required role."""
    gate = await service.get_gate(gate_id)
    await verify_project_access(gate.project_id, user_id, session)
    gate = await service.release_gate(gate_id, data, user_id=user_id, signature_ip=_client_ip(request))
    return _gate_response(gate)


@router.post("/gates/{gate_id}/waive", response_model=HoldGateResponse)
async def waive_gate(
    gate_id: uuid.UUID,
    data: HoldGateWaiveIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.gate.release")),
    service: GatingService = Depends(_get_gating_service),
) -> HoldGateResponse:
    """Waive a gate. Only witness / surveillance / review gates may be waived."""
    gate = await service.get_gate(gate_id)
    await verify_project_access(gate.project_id, user_id, session)
    gate = await service.waive_gate(gate_id, data, user_id=user_id)
    return _gate_response(gate)


# ── Handover packages (Pillar 4) ───────────────────────────────────────────────


@router.get("/handover", response_model=list[HandoverPackageResponse])
async def list_handover_packages(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    completion_regime: str | None = Query(default=None),
    completion_type: str | None = Query(default=None),
    service: HandoverService = Depends(_get_handover_service),
) -> list[HandoverPackageResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_packages(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        completion_regime=completion_regime,
        completion_type=completion_type,
    )
    elements_by_owner = await service.elements_for_many([p.id for p in items])
    return [_handover_response(p, elements_by_owner.get(str(p.id), [])) for p in items]


@router.post("/handover", response_model=HandoverPackageResponse, status_code=201)
async def create_handover_package(
    data: HandoverPackageCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.handover.create")),
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverPackageResponse:
    await verify_project_access(data.project_id, user_id, session)
    package = await service.create_package(data, user_id=user_id)
    elements = await service.elements_for(package.id)
    return _handover_response(package, elements)


@router.get("/handover/{package_id}", response_model=HandoverPackageResponse)
async def get_handover_package(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverPackageResponse:
    package = await service.get_package(package_id)
    await verify_project_access(package.project_id, str(user_id), session)
    elements = await service.elements_for(package.id)
    return _handover_response(package, elements)


@router.patch("/handover/{package_id}", response_model=HandoverPackageResponse)
async def update_handover_package(
    package_id: uuid.UUID,
    data: HandoverPackageUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.handover.update")),
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverPackageResponse:
    existing = await service.get_package(package_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    package = await service.update_package(package_id, data)
    elements = await service.elements_for(package.id)
    return _handover_response(package, elements)


@router.delete("/handover/{package_id}", status_code=204)
async def delete_handover_package(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cc.handover.delete")),
    service: HandoverService = Depends(_get_handover_service),
) -> None:
    existing = await service.get_package(package_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_package(package_id)


@router.get("/handover/{package_id}/gates", response_model=HandoverGateReport)
async def handover_gates(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverGateReport:
    """The computed completion gate: open NCRs + unreleased hold gates on the project."""
    package = await service.get_package(package_id)
    await verify_project_access(package.project_id, str(user_id), session)
    package, blocking_numbers = await service.validate_gates(package_id)
    return HandoverGateReport(
        package_id=package.id,
        project_id=package.project_id,
        gating_state=package.gating_state,
        can_issue=service.can_issue(package),
        open_ncr_count=package.open_ncr_count,
        unreleased_hold_count=package.unreleased_hold_count,
        completeness_pct=package.completeness_pct,
        blocking_gate_numbers=blocking_numbers,
    )


@router.post("/handover/{package_id}/assemble", response_model=HandoverPackageResponse)
async def assemble_handover_package(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.handover.build")),
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverPackageResponse:
    """Auto-assemble the acceptance-evidence manifest and recompute the completion gate."""
    package = await service.get_package(package_id)
    await verify_project_access(package.project_id, user_id, session)
    package, _ = await service.assemble(package_id, user_id=user_id)
    elements = await service.elements_for(package.id)
    return _handover_response(package, elements)


@router.post("/handover/{package_id}/override-gate", response_model=HandoverPackageResponse)
async def override_handover_gate(
    package_id: uuid.UUID,
    data: HandoverOverrideIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.handover.override")),
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverPackageResponse:
    """Override a blocked completion gate (manager only; recorded as a documentation NCR)."""
    package = await service.get_package(package_id)
    await verify_project_access(package.project_id, user_id, session)
    package = await service.override_gate(package_id, data, user_id=user_id)
    elements = await service.elements_for(package.id)
    return _handover_response(package, elements)


@router.post("/handover/{package_id}/issue", response_model=HandoverPackageResponse)
async def issue_handover_certificate(
    package_id: uuid.UUID,
    data: HandoverIssueIn,
    request: Request,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.handover.issue")),
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverPackageResponse:
    """E-sign and issue the acceptance certificate. Refused unless the gate is clear or overridden."""
    package = await service.get_package(package_id)
    await verify_project_access(package.project_id, user_id, session)
    package = await service.issue_certificate(package_id, data, user_id=user_id, signature_ip=_client_ip(request))
    elements = await service.elements_for(package.id)
    return _handover_response(package, elements)


@router.post("/handover/{package_id}/revoke", response_model=HandoverPackageResponse)
async def revoke_handover_package(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("cc.handover.issue")),
    service: HandoverService = Depends(_get_handover_service),
) -> HandoverPackageResponse:
    """Revoke an issued acceptance certificate (a defect emerges post-handover)."""
    package = await service.get_package(package_id)
    await verify_project_access(package.project_id, user_id, session)
    package = await service.revoke(package_id, user_id=user_id)
    elements = await service.elements_for(package.id)
    return _handover_response(package, elements)
