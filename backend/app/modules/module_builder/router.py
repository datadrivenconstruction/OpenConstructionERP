# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module builder HTTP API.

The wizard's four steps map onto four calls. Describing and previewing change
nothing on the server, so a user can go round that loop as often as they like
before anything is written. Installing is the one step that does, and removing
is separate from it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.module_builder import review_token, service
from app.modules.module_builder.schemas import (
    DraftRequest,
    DraftResponse,
    FieldTypeInfo,
    InstalledList,
    InstalledModuleRead,
    InstallRequest,
    PreviewFile,
    PreviewRequest,
    PreviewResponse,
    RuleKindInfo,
    UninstallResponse,
    VocabularyResponse,
)
from app.modules.module_builder.spec import MAX_FIELDS, RESERVED_FIELD_NAMES, reserved_module_keys

router = APIRouter()

FIELD_TYPES: list[FieldTypeInfo] = [
    FieldTypeInfo(type="text", label="Text", hint="A short line, such as a reference or a name."),
    FieldTypeInfo(type="long_text", label="Notes", hint="Several lines of free text."),
    FieldTypeInfo(type="integer", label="Whole number", hint="A count, such as bays or crew size."),
    FieldTypeInfo(type="number", label="Quantity", hint="A measured amount, with a unit."),
    FieldTypeInfo(type="money", label="Money", hint="An amount of money. Kept exact, never rounded to a float."),
    FieldTypeInfo(type="date", label="Date", hint="A day, with no time of day."),
    FieldTypeInfo(type="datetime", label="Date and time", hint="A moment, stored with its time zone."),
    FieldTypeInfo(type="boolean", label="Yes or no", hint="A single checkbox."),
    FieldTypeInfo(type="select", label="One of a few", hint="A fixed list of choices, two or more."),
]

NUMERIC = ["integer", "number", "money"]
TEMPORAL = ["date", "datetime"]

RULE_KINDS: list[RuleKindInfo] = [
    RuleKindInfo(
        kind="required",
        label="Must be filled in",
        hint="The record cannot be saved without it.",
        applies_to=[t.type for t in FIELD_TYPES],
    ),
    RuleKindInfo(
        kind="positive",
        label="Must be above zero",
        hint="Catches a rate or a quantity entered as zero or negative.",
        applies_to=NUMERIC,
    ),
    RuleKindInfo(
        kind="range",
        label="Must be between two values",
        hint="Catches a figure entered in the wrong unit.",
        applies_to=NUMERIC,
        needs_bounds=True,
    ),
    RuleKindInfo(
        kind="one_of",
        label="Must be one of the choices",
        hint="Keeps an imported value from arriving as something the list does not know.",
        applies_to=["select"],
    ),
    RuleKindInfo(
        kind="not_future",
        label="Cannot be in the future",
        hint="For anything recorded after it happened, such as an inspection.",
        applies_to=TEMPORAL,
    ),
    RuleKindInfo(
        kind="order",
        label="Must not come after another date",
        hint="For a pair such as start and finish.",
        applies_to=TEMPORAL,
        needs_other_field=True,
    ),
]


@router.get("/vocabulary", response_model=VocabularyResponse, summary="What the wizard may offer")
async def vocabulary(
    db: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("module_builder.read")),
) -> VocabularyResponse:
    """The field types, rule kinds and taken names, read from the spec itself.

    Sent rather than duplicated in the frontend so the two cannot disagree the
    first time a field type is added.
    """
    return VocabularyResponse(
        field_types=FIELD_TYPES,
        rule_kinds=RULE_KINDS,
        reserved_field_names=sorted(RESERVED_FIELD_NAMES),
        reserved_keys=sorted(reserved_module_keys()),
        max_fields=MAX_FIELDS,
        assistant_available=await _assistant_available(db, user_id),
    )


async def _assistant_available(db: Any, user_id: str) -> bool:
    """Whether drafting from a sentence will work for this user.

    Asked up front so the wizard can offer the by-hand path first rather than
    letting someone type a description and only then learn there is no
    assistant connected.
    """
    if not user_id:
        return False
    try:
        import uuid as _uuid

        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository

        settings = await AISettingsRepository(db).get_by_user_id(_uuid.UUID(user_id))
        resolve_provider_key_model(settings)
    except Exception:
        return False
    return True


@router.post("/draft", response_model=DraftResponse, summary="Describe a module in a sentence")
async def draft(
    payload: DraftRequest,
    db: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("module_builder.draft")),
) -> DraftResponse:
    """Turn a description into a module specification. Writes nothing."""
    try:
        spec = await service.draft_spec(db, user_id, payload.description)
    except service.DraftRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason) from exc
    # Read off the spec rather than asserted again here: the envelope and the
    # artefact were two independent statements of the same fact, and only the
    # one on the spec survives to disk.
    return DraftResponse(spec=spec, source=spec.drafted_by)


@router.post("/preview", response_model=PreviewResponse, summary="See the module before it is written")
async def preview(
    payload: PreviewRequest,
    current_user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("module_builder.draft")),
) -> PreviewResponse:
    """Render every file the module would consist of, without writing any.

    The spec has already been validated by the time it arrives here: it is a
    typed body, so a description that cannot be built is refused by the request
    model rather than by the generator.

    The response carries a review token for these exact files. Install requires
    it, so the only way to write a module is to have asked to see it first.
    """
    files = [PreviewFile(**f) for f in service.preview(payload.spec)]
    return PreviewResponse(
        spec=payload.spec,
        files=files,
        total_lines=sum(f.lines for f in files),
        base_path=payload.spec.url_prefix,
        review_token=review_token.issue(payload.spec, current_user_id),
    )


@router.post("", response_model=InstalledModuleRead, status_code=status.HTTP_201_CREATED, summary="Install a module")
async def install(
    payload: InstallRequest,
    request: Request,
    current_user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("module_builder.install")),
) -> InstalledModuleRead:
    """Write the module and load it into the running server.

    Either the module is installed and serving when this returns, or nothing
    was left behind. There is no state in between for the user to clean up.

    Refuses a spec that does not arrive with the review token ``/preview``
    issued for it. Writing Python into a running server is allowed because a
    person reads it first, so the server checks that rather than trusting the
    wizard to have shown it.
    """
    try:
        review_token.verify(payload.review_token, payload.spec, current_user_id)
    except review_token.ReviewTokenInvalid as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        result = await service.install(payload.spec, request.app)
    except service.InstallRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(result)


@router.get("", response_model=InstalledList, summary="Modules built on this instance")
async def list_installed(
    _perm: None = Depends(RequirePermission("module_builder.read")),
) -> InstalledList:
    from app.core.module_runtime_root import runtime_modules_dir

    items = [_read(m) for m in service.installed()]
    return InstalledList(items=items, total=len(items), runtime_root=str(runtime_modules_dir()))


@router.delete("/{key}", response_model=UninstallResponse, summary="Remove a module built here")
async def uninstall(
    key: str,
    request: Request,
    drop_data: bool = False,
    _perm: None = Depends(RequirePermission("module_builder.uninstall")),
) -> UninstallResponse:
    """Take the module away again.

    The records it holds stay unless ``drop_data`` is asked for. Someone
    removing a module they regret installing should not also lose what they
    recorded with it, and the table can be dropped later by asking again.
    """
    try:
        result = await service.uninstall(key, request.app, drop_data=drop_data)
    except service.InstallRefused as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return UninstallResponse(**result)


def _read(module: service.InstalledModule) -> InstalledModuleRead:
    return InstalledModuleRead(
        key=module.key,
        module_name=module.module_name,
        display_name=module.display_name,
        version=module.version,
        generated_at=module.generated_at,
        entity=module.entity,
        field_count=module.field_count,
        rule_count=module.rule_count,
        base_path=module.base_path,
    )
