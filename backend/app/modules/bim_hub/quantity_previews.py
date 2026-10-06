"""Transactional preview binding for quantity-map writes, not another rule engine.

Preview itself writes nothing. Only a successful Apply records a small receipt
on its model. Receipts are checked against the *post-apply* live state, so retrying
a request is harmless but an old receipt never authorises newly changed data.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy import inspect, or_, select, text
from sqlalchemy.orm import raiseload

from app.core.boq_target import BOQTargetRefused, require_project_boq
from app.modules.bim_hub.models import BIMElement, BIMModel, BIMQuantityMap, BOQElementLink
from app.modules.bim_hub.schemas import QuantityMapApplyRequest, QuantityMapApplyResult
from app.modules.boq.models import BOQ, Position

if TYPE_CHECKING:
    from app.modules.bim_hub.service import BIMHubService

RECEIPTS_KEY = "quantity_map_apply_receipts"
_MAX_RECEIPTS = 16


def _refuse(code: str) -> None:
    raise HTTPException(status_code=409, detail={"code": code})


def _columns(row: Any, *, model: bool = False) -> dict[str, Any]:
    values = {prop.key: getattr(row, prop.key) for prop in inspect(type(row)).column_attrs}
    if model:
        # The receipt's own write must not invalidate it. Import-relevant
        # metadata remains part of the snapshot, unlike this reserved key.
        values.pop("updated_at", None)
        values["metadata_"] = {k: v for k, v in (values.get("metadata_") or {}).items() if k != RECEIPTS_KEY}
    return values


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


async def _load(service: BIMHubService, request: QuantityMapApplyRequest, *, lock: bool):
    session = service.session
    initial = await service.get_model(request.model_id)
    if lock:
        # The project key also serialises two different models writing the
        # same bill. Transaction-scoped: rollback/commit always releases it.
        key = int.from_bytes(
            hashlib.sha256(f"quantity-preview:{initial.project_id}".encode()).digest()[:8], "big", signed=True
        )
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    async def rows(kind, predicate):
        stmt = (
            select(kind)
            .where(predicate)
            .order_by(kind.id)
            .options(raiseload("*", sql_only=True))
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update(read=kind is BIMQuantityMap)
        return list((await session.execute(stmt)).scalars().all())

    models = await rows(BIMModel, BIMModel.project_id == initial.project_id)
    model = next((row for row in models if row.id == request.model_id), None)
    if model is None:
        raise HTTPException(status_code=404, detail="BIM model not found")
    # Existing row edits wait until this transaction ends. The frozen inputs
    # below are used both for the digest and the actual evaluation, including
    # one materialisation of sidecar-only properties (not file timestamps).
    elements = await rows(BIMElement, BIMElement.model_id == model.id)
    rules = await rows(
        BIMQuantityMap, or_(BIMQuantityMap.project_id == model.project_id, BIMQuantityMap.project_id.is_(None))
    )
    rules = sorted((rule for rule in rules if rule.is_active), key=lambda rule: (rule.created_at, str(rule.id)))
    boqs = await rows(BOQ, BOQ.project_id == model.project_id)
    positions = await rows(Position, Position.boq_id.in_([boq.id for boq in boqs]))
    links = await rows(BOQElementLink, BOQElementLink.boq_position_id.in_([position.id for position in positions]))
    subjects = await service._rule_subjects(elements, rules)
    snapshot = {
        "contract": 1,
        "model_id": str(model.id),
        "target_boq_id": str(request.target_boq_id) if request.target_boq_id else None,
        "models": [_columns(row, model=True) for row in models],
        "elements": [_columns(row) for row in elements],
        "resolved_properties": {str(row.id): subjects.get(row.id, row).properties for row in elements},
        "rules": [_columns(row) for row in rules],
        "boqs": [_columns(row) for row in boqs],
        "positions": [_columns(row) for row in positions],
        "links": [_columns(row) for row in links],
    }
    source = {key: snapshot[key] for key in ("models", "elements", "resolved_properties", "rules")}
    return (model, elements, rules, subjects), _digest(snapshot), _digest(source)


async def _effects(service: BIMHubService, request: QuantityMapApplyRequest, prepared, preview: QuantityMapApplyResult):
    """Validate every write destination before either a write or receipt replay."""
    model, _elements, rules, _subjects = prepared
    try:
        if request.target_boq_id is not None:
            await require_project_boq(service.session, model.project_id, request.target_boq_id, writable=True)
        by_rule: dict[str, set] = {}
        for row in preview.results:
            by_rule.setdefault(row["rule_id"], set()).add(row["element_id"])
        would_link: set[tuple[str, str]] = set()
        creates = 0
        for rule in rules:
            element_ids = by_rule.get(str(rule.id), set())
            if not element_ids:
                continue
            target = rule.boq_target if isinstance(rule.boq_target, dict) else {}
            position = await service._resolve_boq_target_position(target=target, project_id=model.project_id)
            if position is None and target.get("auto_create") and not preview.target_boq_ambiguous:
                boq = await require_project_boq(
                    service.session, model.project_id, request.target_boq_id, writable=True, allow_missing=True
                )
                if boq is not None:
                    position = await service._quantity_map_created_position(rule, model, boq)
                    if position is None:
                        creates += 1
                        would_link.update((f"new:{rule.id}", eid) for eid in element_ids)
            if position is not None:
                await require_project_boq(service.session, model.project_id, position.boq_id, writable=True)
                existing = {str(eid) for eid in await service._existing_link_element_ids(position.id)}
                would_link.update((str(position.id), eid) for eid in element_ids - existing)
        preview.links_to_create = len(would_link)
        preview.positions_to_create = creates
    except BOQTargetRefused as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc


async def apply_with_preview(service: BIMHubService, request: QuantityMapApplyRequest) -> QuantityMapApplyResult:
    if not request.dry_run and not request.preview_fingerprint:
        _refuse("quantity_preview_required")
    # One savepoint for the WHOLE operation. A failure cannot leave earlier
    # rules committed, even for internal callers that catch the exception.
    async with service.session.begin_nested():
        prepared, fingerprint, source_fingerprint = await _load(service, request, lock=True)
        model = prepared[0]
        if not request.dry_run and model.status not in {"active", "ready", "degraded", "complete", "completed", "done"}:
            _refuse("quantity_preview_model_not_ready")
        preview = await service._apply_quantity_maps(request.model_copy(update={"dry_run": True}), prepared=prepared)
        await _effects(service, request, prepared, preview)
        preview.preview_fingerprint = fingerprint
        if request.dry_run:
            return preview
        receipts = list((model.metadata_ or {}).get(RECEIPTS_KEY) or [])
        for receipt in receipts:
            if (
                receipt.get("token") == request.preview_fingerprint
                and receipt.get("model_id") == str(request.model_id)
                and receipt.get("target_boq_id") == (str(request.target_boq_id) if request.target_boq_id else None)
            ):
                if receipt.get("after") != fingerprint:
                    _refuse("quantity_preview_stale")
                return preview.model_copy(update={"replayed": True})
        if request.preview_fingerprint != fingerprint:
            _refuse("quantity_preview_stale")
        result = await service._apply_quantity_maps(request, prepared=prepared)
        await service.session.flush()
        _fresh, after, source_after = await _load(service, request, lock=False)
        if source_after != source_fingerprint:
            # Filesystem sidecars do not take PostgreSQL row locks. Do not
            # record a receipt for a concurrently replaced sidecar/rule set.
            _refuse("quantity_preview_stale")
        # Only small counters/identifiers, never 50k result rows, are retained.
        receipts.append(
            {
                "token": fingerprint,
                "after": after,
                "model_id": str(model.id),
                "target_boq_id": str(request.target_boq_id) if request.target_boq_id else None,
            }
        )
        model.metadata_ = {**(model.metadata_ or {}), RECEIPTS_KEY: receipts[-_MAX_RECEIPTS:]}
        await service.session.flush()
        return result.model_copy(
            update={
                "preview_fingerprint": fingerprint,
                "links_to_create": preview.links_to_create,
                "positions_to_create": preview.positions_to_create,
            }
        )
