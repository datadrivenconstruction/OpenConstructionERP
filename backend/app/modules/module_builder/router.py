# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module builder HTTP API.

The wizard's four steps map onto four calls. Describing and previewing change
nothing on the server, so a user can go round that loop as often as they like
before anything is written. Installing is the one step that does, and removing
is separate from it.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.module_builder import links, review_token, service, suggest, upgrade
from app.modules.module_builder.schemas import (
    DraftRequest,
    DraftResponse,
    FieldTypeInfo,
    InstalledList,
    InstalledModuleRead,
    InstalledProblem,
    InstallRequest,
    LinkTargetInfo,
    LookupItem,
    LookupLabelsResponse,
    LookupResponse,
    PreviewFile,
    PreviewRequest,
    PreviewResponse,
    RuleKindInfo,
    Suggestion,
    SuggestRequest,
    SuggestResponse,
    UninstallResponse,
    UpgradeChange,
    UpgradePreviewResponse,
    UpgradeRequest,
    UpgradeResponse,
    VocabularyResponse,
)
from app.modules.module_builder.spec import FEATURE_NAMES, MAX_FIELDS, RESERVED_FIELD_NAMES, reserved_module_keys

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
    FieldTypeInfo(
        type="link",
        label="Link",
        hint="Points at a record another part of the platform keeps, such as a contract or a person.",
    ),
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
        link_targets=[
            LinkTargetInfo(target=t.target, module=t.module, available=links.available(t.target))
            for t in links.LINK_TARGETS.values()
        ],
        features=list(FEATURE_NAMES),
        upgrade=True,
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
    """Turn a description into a module specification. Writes nothing.

    The spec carries no links and no functions. The assistant's ideas for
    those come back as suggestions, which reach the spec only when a person
    ticks them in the wizard.
    """
    try:
        spec, suggestions = await service.draft(db, user_id, payload.description, payload.locale)
    except service.DraftRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason) from exc
    # Read off the spec rather than asserted again here: the envelope and the
    # artefact were two independent statements of the same fact, and only the
    # one on the spec survives to disk.
    return DraftResponse(spec=spec, source=spec.drafted_by, suggestions=_buildable(suggestions))


@router.post("/suggest", response_model=SuggestResponse, summary="What a module could also do, by rule")
async def suggest_for(
    payload: SuggestRequest,
    _perm: None = Depends(RequirePermission("module_builder.draft")),
) -> SuggestResponse:
    """Links and functions read off the spec's own words. No assistant, writes nothing.

    The same spec gives the same suggestions every time, so the templates and
    the path with no assistant connected get the same proposals.
    """
    return SuggestResponse(suggestions=suggest.suggest(payload.spec, payload.locale, available=links.available))


def _buildable(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Leave out links to parts of the platform switched off here."""
    return [s for s in suggestions if s.kind != "link" or (s.target is not None and links.available(s.target))]


async def _target_reader(target: str, db: Any, user_id: str) -> links.Caller:
    """The caller, once it is settled that they may read ``target`` at all.

    An unknown or switched-off target answers 404, like a route that is not
    there. A caller without the target module's own read permission answers
    403, as that module's list route would.
    """
    if target not in links.LINK_TARGETS or not links.available(target):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such link target")
    caller = await links.caller_for(db, user_id)
    if not links.may_read(caller, target):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission '{links.LINK_TARGETS[target].permission}' required")
    return caller


@router.get("/lookup/{target}", response_model=LookupResponse, summary="Records a link field may point at")
async def lookup(
    target: str,
    db: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(None, description="Only records of this project"),
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=links.MAX_LOOKUP),
    _perm: None = Depends(RequirePermission("module_builder.read")),
) -> LookupResponse:
    """What the link picker offers: the target's records this caller may see.

    By the target module's own rules - its read permission, project access,
    and for documents the folder grants - so the picker never lists a record
    the caller could not open where it lives.
    """
    caller = await _target_reader(target, db, user_id)
    if project_id is not None:
        await verify_project_access(project_id, user_id, db)
    found = await links.visible(db, caller, target, project_id=project_id, query=q, limit=limit)
    return LookupResponse(items=[LookupItem(id=str(r.id), label=r.label, sublabel=r.sublabel) for r in found])


@router.get("/lookup/{target}/labels", response_model=LookupLabelsResponse, summary="Names for stored link ids")
async def lookup_labels(
    target: str,
    db: SessionDep,
    user_id: CurrentUserId,
    ids: str = Query("", description="Comma-separated record ids"),
    _perm: None = Depends(RequirePermission("module_builder.read")),
) -> LookupLabelsResponse:
    """Readable names for the ids a list shows.

    Ids the caller may not see are left out, the same as ids that do not
    exist, so the answer cannot be used to learn what is in someone else's
    project. Malformed ids are ignored for the same reason.
    """
    caller = await _target_reader(target, db, user_id)
    wanted: list[uuid.UUID] = []
    for part in ids.split(","):
        try:
            wanted.append(uuid.UUID(part.strip()))
        except ValueError:
            continue
    if len(wanted) > links.MAX_LABELS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"At most {links.MAX_LABELS} ids can be named at once."
        )
    found = await links.visible(db, caller, target, ids=wanted)
    return LookupLabelsResponse(labels={str(r.id): r.label for r in found})


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
        # A refusal with a code is one the frontend words itself; the message
        # stays as the fallback. Every other refusal keeps its plain string.
        detail: Any = {"code": exc.code, "message": str(exc), "params": exc.params} if exc.code else str(exc)
        raise HTTPException(status.HTTP_409_CONFLICT, detail=detail) from exc
    return _read(result)


@router.post(
    "/{key}/upgrade/preview", response_model=UpgradePreviewResponse, summary="See an upgrade before it is applied"
)
async def upgrade_preview(
    key: str,
    payload: PreviewRequest,
    current_user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("module_builder.install")),
) -> UpgradePreviewResponse:
    """Render the upgraded module and say what the upgrade changes. Writes nothing.

    Refused here already, with the same codes as the upgrade itself, when the
    upgrade would take something away: the person learns it before reading
    the files rather than after.
    """
    _same_key(key, payload.spec)
    try:
        outcome = await upgrade.preview(key, payload.spec)
    except upgrade.UpgradeRefused as exc:
        raise _refused(exc) from exc
    files = [PreviewFile(**f) for f in service.preview(payload.spec)]
    return UpgradePreviewResponse(
        spec=payload.spec,
        files=files,
        total_lines=sum(f.lines for f in files),
        base_path=payload.spec.url_prefix,
        review_token=review_token.issue(payload.spec, current_user_id, purpose=review_token.UPGRADE),
        changes=[UpgradeChange(**c.as_dict()) for c in outcome.changes],
        record_count=outcome.records,
    )


@router.post("/{key}/upgrade", response_model=UpgradeResponse, summary="Upgrade a module built here")
async def upgrade_module(
    key: str,
    payload: UpgradeRequest,
    request: Request,
    current_user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("module_builder.install")),
) -> UpgradeResponse:
    """Apply an upgrade previewed for this module, keeping its records.

    Only what adds is applied. Either the module is serving the upgraded code
    when this returns, or the old code is, and the table took nothing but
    empty columns.
    """
    _same_key(key, payload.spec)
    try:
        review_token.verify(payload.review_token, payload.spec, current_user_id, purpose=review_token.UPGRADE)
    except review_token.ReviewTokenInvalid as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        outcome = await upgrade.upgrade(key, payload.spec, request.app)
    except upgrade.UpgradeRefused as exc:
        raise _refused(exc) from exc
    return UpgradeResponse(
        key=key,
        module_name=payload.spec.module_name,
        base_path=payload.spec.url_prefix,
        record_count=outcome.records,
        changes=[UpgradeChange(**c.as_dict()) for c in outcome.changes],
    )


def _same_key(key: str, spec: Any) -> None:
    if spec.key != key:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The spec describes {spec.key!r}, not {key!r}. An upgrade keeps the module's key.",
        )


def _refused(exc: upgrade.UpgradeRefused) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.params:
        detail["params"] = exc.params
    return HTTPException(exc.status, detail=detail)


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
        status=module.status,
        problem=InstalledProblem(**module.problem) if module.problem else None,
    )
