"""Design changes an assistant may propose (card R15): stored as pending proposals, written only when a person applies.

Each spec plugs into the ERP assistant's action registry, so the same proposal reaches the in-app Changes view whether
it came from the in-app assistant or an MCP client. ``build`` only reads; ``apply`` runs for the person who clicks
Apply, under the gates of the Design REST route it mirrors, and never commits (the Changes service owns the
transaction).
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, ClassVar

from fastapi import HTTPException

from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionContext,
    ActionDraft,
    ActionNotFoundError,
    ActionPermissionError,
    ActionSpec,
    ActionValidationError,
    AppliedResult,
    coerce_uuid,
)
from app.modules.erp_chat.actions.registry import register_spec
from app.modules.erp_chat.schemas import ActionEntityRef, ActionField

from .auth import now_utc

MODULE = "oe_design"
MAX_VALUES = 60
_LABEL_PREFIX = "design.mcp."


def _field(key: str, label: str, value: Any, *, before: Any = None, kind: str = "text") -> ActionField:
    # The Changes view shows ``label`` when it has no translation for ``label_key``.
    return ActionField(
        key=key, label_key=f"{_LABEL_PREFIX}field.{key}", label=label, kind=kind, value=value, before=before
    )


def _shown(value: Any) -> Any:
    return value if isinstance(value, str | int | float | bool) or value is None else str(value)


async def _project(ctx: ActionContext, args: dict[str, Any]) -> uuid.UUID:
    raw = args.get("project_id")
    pid = coerce_uuid(raw) if raw not in (None, "") else ctx.project_id
    if pid is None:
        raise ActionValidationError(code="project_required")
    await ctx.require_project_access(pid)
    return pid


async def _require_manager(ctx: ActionContext, project_id: uuid.UUID) -> None:
    from app.modules.projects.models import Project

    from .router import _can_accept

    project = await ctx.session.get(Project, project_id)
    if project is None or not await _can_accept(ctx.session, ctx.user_id, project):
        raise ActionPermissionError("Only a project manager may do this.", code="forbidden")


def _http(exc: HTTPException) -> Exception:
    detail = exc.detail if isinstance(exc.detail, str) else str((exc.detail or {}).get("message", exc.detail))
    if exc.status_code == 404:
        return ActionNotFoundError(detail, code="not_found")
    if exc.status_code == 403:
        return ActionPermissionError(detail, code="forbidden")
    if exc.status_code == 409:
        return ActionConflictError(detail, code="conflict")
    return ActionValidationError(detail, code="validation_error")


class _DesignSpec(ActionSpec):
    modules: ClassVar[tuple[str, ...]] = (MODULE,)
    apply_permissions: ClassVar[tuple[str, ...]] = ()
    english_title: ClassVar[str]

    @property
    def title(self) -> str:
        return self.english_title

    @property
    def title_key(self) -> str:
        return f"{_LABEL_PREFIX}title.{self.action_type}"


# ── Brief values ────────────────────────────────────────────────────────────


class BriefValuesSpec(_DesignSpec):
    """Set brief values; applying saves them and records the person who applied as their confirmer."""

    action_type: ClassVar[str] = "design.brief.values"
    tool_name: ClassVar[str] = "propose_design_brief_values"
    english_title: ClassVar[str] = "Design brief values"
    entity_type: ClassVar[str] = "design_brief"
    tool_description: ClassVar[str] = (
        "Propose values for a project's design brief (ddc-brief/1), each as a JSON Pointer and a value, for example "
        "{'pointer': '/massing/floors_above', 'value': 5}. Read the brief first and pass its version as "
        "base_version. Nothing is saved: a person reviews the values and, by applying, saves and confirms them."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID."},
        "base_version": {
            "type": "integer",
            "minimum": 0,
            "description": "Version of the brief the values are based on (0 when there is none).",
        },
        "values": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_VALUES,
            "items": {
                "type": "object",
                "required": ["pointer", "value"],
                "properties": {
                    "pointer": {"type": "string", "description": "JSON Pointer of a brief field, e.g. /country."},
                    "value": {"description": "The value, in the field's own type."},
                    "sources": {
                        "type": "array",
                        "description": "Citations: {kind, document_id?, page?, quote?}.",
                        "items": {"type": "object"},
                    },
                },
            },
        },
    }
    required_args: ClassVar[tuple[str, ...]] = ("project_id", "base_version", "values")

    async def build(self, ctx, args, *, prior=None) -> ActionDraft:
        from .brief import _head
        from .brief_doc import exists, resolve
        from .brief_fields import FieldError, coerce

        pid = await _project(ctx, args)
        head = await _head(ctx.session, pid)
        current = 0 if head is None else head.version
        base = args.get("base_version")
        if not isinstance(base, int) or isinstance(base, bool):
            raise ActionValidationError(
                "base_version must be the brief version the values are based on.", code="validation_error"
            )
        if base != current:
            raise ActionConflictError(
                f"The brief is at version {current}, not {base}; read it again.", code="stale_brief"
            )
        raw = args.get("values")
        if not isinstance(raw, list) or not 0 < len(raw) <= MAX_VALUES:
            raise ActionValidationError(f"values must list 1 to {MAX_VALUES} items.", code="validation_error")
        doc = {} if head is None else head.document
        values, fields, errors = [], [], {}
        for item in raw:
            pointer = item.get("pointer") if isinstance(item, dict) else None
            try:
                if not isinstance(pointer, str):
                    raise FieldError(str(pointer), "needs a pointer")
                value = coerce(pointer, item.get("value"))
            except FieldError as exc:
                errors[exc.pointer] = {"code": "invalid", "message": exc.message}
                continue
            sources = item.get("sources") if isinstance(item.get("sources"), list) else []
            values.append({"pointer": pointer, "value": value, "sources": sources[:10]})
            before = _shown(resolve(doc, pointer)) if exists(doc, pointer) else None
            fields.append(_field(pointer, pointer, _shown(value), before=before))
        if errors:
            raise ActionValidationError(
                "Some values do not fit their fields.", code="validation_error", field_errors=errors
            )
        return ActionDraft(
            payload={"project_id": str(pid), "base_version": current, "values": values},
            fields=fields,
            project_id=pid,
            target=ActionEntityRef(entity_type=self.entity_type, entity_id=str(pid)),
            before_state={"version": current},
        )

    async def check_apply_gates(self, ctx, payload) -> None:
        await _project(ctx, payload)

    async def apply(self, ctx, action, draft) -> AppliedResult:
        from .brief import _head, _store
        from .brief_doc import BriefError, apply_confirm, prepare_save
        from .brief_fields import set_at

        pid = draft.project_id
        head = await _head(ctx.session, pid)
        current = 0 if head is None else head.version
        if current != draft.payload["base_version"]:
            raise ActionConflictError("The brief changed after this proposal; ask for a new one.", code="stale_brief")
        doc = copy.deepcopy({} if head is None else head.document)
        prov = doc.setdefault("provenance", {})
        for v in draft.payload["values"]:
            set_at(doc, v["pointer"], v["value"])
            prov[v["pointer"]] = {
                "status": "proposed",
                "sources": v["sources"] or [{"kind": "text"}],
                "note": "Proposed by an assistant.",
            }
        try:
            stored, _ = prepare_save(
                doc,
                None if head is None else head.document,
                project_id=pid,
                brief_id=uuid.uuid4() if head is None else head.id,
                version=current + 1,
                draft=True,
            )
            await _store(
                ctx.session,
                head,
                project_id=pid,
                expected=current,
                document=stored,
                user_id=ctx.user_id,
                action="save",
                commit=False,
            )
            final, confirmed = stored, False
            try:
                final = apply_confirm(
                    stored,
                    [v["pointer"] for v in draft.payload["values"]],
                    user_id=ctx.user_id,
                    at=now_utc(),
                    version=stored["version"] + 1,
                )
                confirmed = True
            except BriefError as exc:
                # Gaps the draft already had do not block confirming (as on the brief form); a newly missing
                # required value keeps the values saved as proposed, and the person confirms them in the form.
                if any(e["message"] != "is required" for e in exc.errors):
                    raise
            if confirmed:
                head = await _head(ctx.session, pid)
                await _store(
                    ctx.session,
                    head,
                    project_id=pid,
                    expected=stored["version"],
                    document=final,
                    user_id=ctx.user_id,
                    action="confirm",
                    commit=False,
                )
        except BriefError as exc:
            raise ActionValidationError(str(exc)[:500], code="validation_error") from exc
        except HTTPException as exc:
            raise _http(exc) from exc
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(pid),
            label=f"v{final['version']}",
            url="/design/brief",
            after_state={"version": final["version"], "confirmed": confirmed},
            audit_action="updated",
            before_state={"version": current},
        )


# ── Revision decision ───────────────────────────────────────────────────────


class RevisionDecisionSpec(_DesignSpec):
    """Accept or reject a shared revision; applying runs the acceptance exactly as the acceptance screen does."""

    action_type: ClassVar[str] = "design.revision.decide"
    tool_name: ClassVar[str] = "propose_design_revision_decision"
    english_title: ClassVar[str] = "Design revision decision"
    entity_type: ClassVar[str] = "design_revision"
    tool_description: ClassVar[str] = (
        "Propose to accept or reject a model revision that awaits a decision (status 'shared'). Read its impact "
        "first. Nothing changes: a project manager reviews the proposal and applies it; accepting recomputes the "
        "estimate. A rejection needs a comment."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "revision_id": {"type": "string", "description": "Revision UUID."},
        "decision": {"type": "string", "enum": ["accept", "reject"]},
        "comment": {"type": "string", "maxLength": 2000},
        "change_order": {
            "type": "boolean",
            "description": "With the project setting 'ask': also draft a change "
            "order with the cost delta and the changed elements (a person approves it later).",
        },
    }
    required_args: ClassVar[tuple[str, ...]] = ("revision_id", "decision")

    async def _revision(self, ctx, raw):
        from .models import DesignRevision

        rid = coerce_uuid(raw)
        rev = await ctx.session.get(DesignRevision, rid) if rid else None
        if rev is None or rev.status in ("uploading",):
            raise ActionNotFoundError("Revision not found.", code="not_found")
        await ctx.require_project_access(rev.project_id)
        return rev

    async def build(self, ctx, args, *, prior=None) -> ActionDraft:
        rev = await self._revision(ctx, args.get("revision_id"))
        decision = args.get("decision")
        if decision not in ("accept", "reject"):
            raise ActionValidationError("decision must be 'accept' or 'reject'.", code="validation_error")
        comment = str(args.get("comment") or "").strip()[:2000]
        if decision == "reject" and not comment:
            raise ActionValidationError("A rejection needs a comment.", code="validation_error")
        if rev.status != "shared":
            raise ActionConflictError(f"Revision is {rev.status}, not awaiting a decision.", code="not_pending")
        change_order = args.get("change_order")
        if change_order is not None and not isinstance(change_order, bool):
            raise ActionValidationError("change_order must be true or false.", code="validation_error")
        if decision == "reject":
            change_order = None
        return ActionDraft(
            payload={
                "revision_id": str(rev.id),
                "decision": decision,
                "comment": comment or None,
                "change_order": change_order,
            },
            fields=[
                _field("revision", "Revision", f"R{rev.number}"),
                _field("decision", "Decision", decision),
                _field("comment", "Comment", comment or None, kind="longtext"),
                _field("change_order", "Draft change order", change_order),
            ],
            project_id=rev.project_id,
            subtitle=f"R{rev.number}",
            target=ActionEntityRef(
                entity_type=self.entity_type, entity_id=str(rev.id), label=f"R{rev.number}", url="/design/acceptance"
            ),
            before_state={"status": rev.status},
        )

    async def check_apply_gates(self, ctx, payload) -> None:
        rev = await self._revision(ctx, payload.get("revision_id"))
        await _require_manager(ctx, rev.project_id)

    async def apply(self, ctx, action, draft) -> AppliedResult:
        from .router import decide_accept, decide_reject

        rev = await self._revision(ctx, draft.payload["revision_id"])
        if rev.status != "shared":
            raise ActionConflictError(f"Revision is {rev.status}, not awaiting a decision.", code="not_pending")
        try:
            if draft.payload["decision"] == "accept":
                await decide_accept(
                    ctx.session,
                    rev,
                    ctx.user_id,
                    draft.payload.get("comment"),
                    change_order=draft.payload.get("change_order"),
                )
            else:
                await decide_reject(ctx.session, rev, ctx.user_id, draft.payload["comment"])
        except HTTPException as exc:
            raise _http(exc) from exc
        status_after = "published" if draft.payload["decision"] == "accept" else "rejected"
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(rev.id),
            label=f"R{rev.number}",
            url="/design/acceptance",
            after_state={"status": status_after},
            audit_action="updated",
            before_state={"status": "shared"},
        )


# ── Estimate rules ──────────────────────────────────────────────────────────


class EstimateRulesSpec(_DesignSpec):
    """Install the country starter rule set that turns model quantities into estimate positions."""

    action_type: ClassVar[str] = "design.estimate.rules"
    tool_name: ClassVar[str] = "propose_design_estimate_rules"
    english_title: ClassVar[str] = "Design estimate rules"
    entity_type: ClassVar[str] = "design_estimate"
    tool_description: ClassVar[str] = (
        "Propose installing the starter estimate rule set for a country (two-letter code, e.g. DE) in a project, "
        "so accepted revisions produce estimate positions. Nothing changes until a project manager applies it."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID."},
        "country": {"type": "string", "minLength": 2, "maxLength": 2},
    }
    required_args: ClassVar[tuple[str, ...]] = ("project_id", "country")

    async def build(self, ctx, args, *, prior=None) -> ActionDraft:
        from . import rules

        pid = await _project(ctx, args)
        country = str(args.get("country") or "").upper()
        doc = rules.starter_set(country) if len(country) == 2 else None
        if doc is None:
            raise ActionValidationError(f"No starter rule set for country {country or '?'}.", code="validation_error")
        return ActionDraft(
            payload={"project_id": str(pid), "country": country},
            fields=[_field("country", "Country", country), _field("rules", "Rules", len(doc["rules"]), kind="number")],
            project_id=pid,
            target=ActionEntityRef(entity_type=self.entity_type, entity_id=str(pid)),
        )

    async def check_apply_gates(self, ctx, payload) -> None:
        pid = await _project(ctx, payload)
        await _require_manager(ctx, pid)

    async def apply(self, ctx, action, draft) -> AppliedResult:
        from . import estimate as est
        from . import rules

        doc = rules.starter_set(draft.payload["country"])
        try:
            e = await est.install_rules(ctx.session, draft.project_id, doc, ctx.user_id)
        except rules.RulesError as exc:
            raise ActionValidationError(str(exc)[:500], code="validation_error") from exc
        await ctx.session.flush()
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(e.boq_id),
            label=draft.payload["country"],
            url="/design/acceptance",
            after_state={"rules": len(doc["rules"]), "at": str(now_utc())},
        )


# ── Generation (R13) ────────────────────────────────────────────────────────


class GenerationSpec(_DesignSpec):
    """Start the server worker: generate a revision from the confirmed brief. Applying starts the job."""

    action_type: ClassVar[str] = "design.generation.start"
    tool_name: ClassVar[str] = "propose_design_generation"
    english_title: ClassVar[str] = "Generate design revision"
    entity_type: ClassVar[str] = "design_job"
    tool_description: ClassVar[str] = (
        "Propose generating a new model revision from the project's confirmed design brief on the server. Read the "
        "brief first and pass its version. Nothing starts: a project manager applies the proposal, the job then "
        "runs and the result waits as a pending revision (read it with design_list_revisions / design_get_job)."
    )
    input_properties: ClassVar[dict[str, Any]] = {
        "project_id": {"type": "string", "description": "Project UUID."},
        "brief_version": {"type": "integer", "minimum": 1, "description": "Version of the confirmed brief."},
    }
    required_args: ClassVar[tuple[str, ...]] = ("project_id", "brief_version")

    async def _check(self, ctx, pid: uuid.UUID, version: Any) -> int:
        from . import jobs
        from .brief import current_brief

        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ActionValidationError(
                "brief_version must be the version of the confirmed brief.", code="validation_error"
            )
        _, reason = jobs.cli_state()
        if reason:
            raise ActionValidationError(reason, code="generation_disabled")
        doc = await current_brief(ctx.session, pid)
        if doc is None:
            raise ActionConflictError("The project has no brief yet.", code="no_brief")
        if doc.get("version") != version:
            raise ActionConflictError(
                f"The brief is at version {doc.get('version')}, not {version}; read it again.", code="stale_brief"
            )
        problems = jobs.brief_problems(doc)
        if problems:
            raise ActionValidationError("The brief is not confirmed yet.", code="brief_not_confirmed")
        if await jobs.active_job(ctx.session, pid) is not None:
            raise ActionConflictError("A generation is already running for this project.", code="job_active")
        return version

    async def build(self, ctx, args, *, prior=None) -> ActionDraft:
        pid = await _project(ctx, args)
        version = await self._check(ctx, pid, args.get("brief_version"))
        return ActionDraft(
            payload={"project_id": str(pid), "brief_version": version},
            fields=[_field("brief_version", "Brief version", version, kind="number")],
            project_id=pid,
            subtitle=f"brief v{version}",
            target=ActionEntityRef(entity_type=self.entity_type, entity_id=str(pid), url="/design/revisions"),
        )

    async def check_apply_gates(self, ctx, payload) -> None:
        pid = await _project(ctx, payload)
        await _require_manager(ctx, pid)

    async def apply(self, ctx, action, draft) -> AppliedResult:
        from . import jobs

        pid = draft.project_id
        # The job runs after this request and must see its own row, so it commits on its own sessions.
        try:
            job = await jobs.start_generation(pid, ctx.user_id, draft.payload["brief_version"])
        except HTTPException as exc:
            raise _http(exc) from exc
        return AppliedResult(
            entity_type=self.entity_type,
            entity_id=str(job.id),
            label="Generation",
            url="/design/revisions",
            after_state={"status": job.status, "job_id": str(job.id)},
        )


SPECS: tuple[type[_DesignSpec], ...] = (BriefValuesSpec, RevisionDecisionSpec, EstimateRulesSpec, GenerationSpec)


def register_specs() -> None:
    """Idempotent: re-registering replaces."""
    for cls in SPECS:
        register_spec(cls())
