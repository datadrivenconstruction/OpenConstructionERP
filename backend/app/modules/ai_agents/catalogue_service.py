# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run, configure and review the project agent catalogue.

A run is recorded exactly like any other agent run (``AgentRun`` plus one
``AgentStep`` per tool call and observation), so the existing run timeline
and audit views show it. The run gathers through the agent's read-only
registry tools, drafts with :mod:`catalogue_logic`, and, when an AI provider
is configured, lets the model add a short narrative through the ReAct runner
under the project's per-run token limit. The output is an ``AgentDraft``
with a confidence and its sources; nothing else is written.

Guards, in order: the project kill switch, the agent being enabled on the
project, the required inputs. Accepting a draft is the human step; for an
RFI draft it can also create the RFI (status ``draft``) through the RFI
service.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.base import (
    Agent,
    AgentRunner,
    LLMBridge,
    _truncate_observation,
    global_tool_registry,
)
from app.modules.ai_agents.catalogue import (
    CATALOGUE,
    DEFAULT_MAX_TOKENS_PER_RUN,
    TOOL_DAY,
    TOOL_MARKUP,
    TOOL_SEARCH,
    TOOL_SUBMITTAL,
    CatalogueSpec,
    hits_from_json,
)
from app.modules.ai_agents.catalogue_logic import (
    DEFAULT_CLAUSE_CHECKLIST,
    check_submittal,
    compose_daily_report,
    draft_rfi,
    review_clauses,
)
from app.modules.ai_agents.models import AgentDraft, AgentRun, AgentStep, ProjectAgentGuard, ProjectAgentSetting

logger = logging.getLogger(__name__)

MAX_OBSERVATION_CHARS = 6_000


class CatalogueError(Exception):
    """A run that may not start; ``code`` is stable for the UI."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CatalogueService:
    """Project-scoped catalogue operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Settings and kill switch ────────────────────────────────────────────

    async def settings(self, project_id: uuid.UUID) -> dict[str, ProjectAgentSetting]:
        rows = (
            (
                await self.session.execute(
                    select(ProjectAgentSetting).where(ProjectAgentSetting.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        return {r.agent_name: r for r in rows}

    async def guard(self, project_id: uuid.UUID) -> ProjectAgentGuard | None:
        stmt = select(ProjectAgentGuard).where(ProjectAgentGuard.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def catalogue(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Every catalogue agent with this project's setting, plus the kill switch state."""
        settings = await self.settings(project_id)
        guard = await self.guard(project_id)
        agents = []
        for spec in CATALOGUE.values():
            row = settings.get(spec.name)
            agents.append(
                {
                    **spec.to_dict(),
                    "enabled": bool(row and row.enabled),
                    "config": {**spec.default_config, **((row.config or {}) if row else {})},
                    "max_tokens_per_run": row.max_tokens_per_run if row else DEFAULT_MAX_TOKENS_PER_RUN,
                }
            )
        return {
            "project_id": str(project_id),
            "halted": bool(guard and guard.halted),
            "halt_reason": guard.reason if guard else "",
            "agents": agents,
        }

    async def configure(
        self,
        project_id: uuid.UUID,
        agent_name: str,
        *,
        user_id: uuid.UUID,
        enabled: bool | None = None,
        config: dict[str, Any] | None = None,
        max_tokens_per_run: int | None = None,
    ) -> ProjectAgentSetting:
        """Enable, disable or configure one agent on one project."""
        if agent_name not in CATALOGUE:
            raise CatalogueError("unknown_agent")
        row = (await self.settings(project_id)).get(agent_name)
        if row is None:
            row = ProjectAgentSetting(project_id=project_id, agent_name=agent_name, enabled=False, config={})
            self.session.add(row)
        if enabled is not None:
            row.enabled = enabled
        if config is not None:
            row.config = config
        if max_tokens_per_run is not None:
            row.max_tokens_per_run = max(500, min(int(max_tokens_per_run), 200_000))
        row.updated_by = user_id
        await self.session.flush()
        return row

    async def set_halt(
        self, project_id: uuid.UUID, *, halted: bool, reason: str, user_id: uuid.UUID
    ) -> ProjectAgentGuard:
        """Flip the project kill switch."""
        row = await self.guard(project_id)
        if row is None:
            row = ProjectAgentGuard(project_id=project_id)
            self.session.add(row)
        row.halted = halted
        row.reason = (reason or "")[:500]
        row.set_by = user_id
        await self.session.flush()
        return row

    # ── Run ─────────────────────────────────────────────────────────────────

    async def run(
        self,
        *,
        project_id: uuid.UUID,
        agent_name: str,
        inputs: dict[str, Any],
        user_id: uuid.UUID,
        role: str,
        llm: LLMBridge | None = None,
        use_ai: bool = True,
    ) -> tuple[AgentRun, AgentDraft | None]:
        """Run one catalogue agent and persist its draft; see the module docstring."""
        spec = CATALOGUE.get(agent_name)
        if spec is None:
            raise CatalogueError("unknown_agent")
        guard = await self.guard(project_id)
        if guard is not None and guard.halted:
            raise CatalogueError("halted", guard.reason)
        setting = (await self.settings(project_id)).get(agent_name)
        if setting is None or not setting.enabled:
            raise CatalogueError("disabled")
        missing = [f.key for f in spec.inputs if f.required and not str(inputs.get(f.key) or "").strip()]
        if missing:
            raise CatalogueError("missing_inputs", ", ".join(missing))
        config = {**spec.default_config, **(setting.config or {})}

        run = AgentRun(
            agent_name=agent_name,
            project_id=project_id,
            user_id=user_id,
            status="running",
            user_input=json.dumps(inputs, ensure_ascii=False, default=str)[:4000],
            iterations=0,
            total_tokens=0,
            started_at=_now(),
            trigger_source="catalogue",
        )
        self.session.add(run)
        await self.session.flush()
        context = {"user_id": str(user_id), "project_id": str(project_id), "role": role}
        steps = {"i": 0}

        async def _record(role_name: str, content: Any, tokens: int = 0) -> None:
            steps["i"] += 1
            self.session.add(
                AgentStep(
                    run_id=run.id,
                    step_idx=steps["i"],
                    role=role_name,
                    content=_truncate_observation(content, MAX_OBSERVATION_CHARS),
                    token_count=tokens,
                )
            )

        async def call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            if tool_name not in spec.tools:
                raise CatalogueError("tool_not_allowed", tool_name)
            tool = global_tool_registry.get(tool_name)
            if tool is None:
                raise CatalogueError("tool_missing", tool_name)
            await _record("tool_call", {"tool": tool_name, "args": args})
            result = await tool.run({**args, "__agent_context__": dict(context)})
            await _record("observation", {"tool": tool_name, "result": result})
            return result if isinstance(result, dict) else {"result": result}

        try:
            payload, title = await self._draft(spec, inputs, config, call)
        except CatalogueError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed gather is a failed run, not a crash
            logger.exception("Catalogue run %s failed", run.id)
            run.status, run.failure_reason, run.finished_at = "failed", "exception", _now()
            run.final_output = str(exc)[:500]
            await self.session.flush()
            return run, None

        tokens = 0
        if use_ai:
            narrative, tokens, failure = await self._narrative(spec, payload, setting.max_tokens_per_run, llm, user_id)
            if narrative:
                payload["narrative"] = narrative
            if failure:
                payload["narrative_skipped"] = failure
        confidence = float(payload.get("confidence") or 0.0)
        sources = _sources_of(payload)
        draft = AgentDraft(
            project_id=project_id,
            run_id=run.id,
            agent_name=agent_name,
            draft_kind=spec.draft_kind,
            title=title[:500],
            payload=payload,
            confidence=confidence,
            sources=sources,
            status="pending",
            created_by=user_id,
        )
        self.session.add(draft)
        await _record("answer", {"draft_kind": spec.draft_kind, "title": title, "confidence": confidence})
        run.status = "completed"
        run.iterations = steps["i"]
        run.total_tokens = tokens
        run.final_output = title
        run.trust = {"confidence": confidence, "sources": sources[:20], "rationale": spec.tagline}
        run.finished_at = _now()
        await self.session.flush()
        return run, draft

    async def _draft(
        self, spec: CatalogueSpec, inputs: dict[str, Any], config: dict[str, Any], call: Any
    ) -> tuple[dict, str]:
        if spec.name == "rfi_drafter":
            context: dict[str, Any] = {"photo_id": inputs.get("photo_id"), "markup_id": inputs.get("markup_id")}
            query = str(inputs.get("question") or "")
            if inputs.get("markup_id"):
                markup = await call(TOOL_MARKUP, {"markup_id": str(inputs["markup_id"])})
                if not markup.get("error"):
                    context["markup_label"] = " ".join(str(markup.get(k) or "") for k in ("label", "text")).strip()
                    query = f"{query} {context['markup_label']}"
            found = await call(TOOL_SEARCH, {"q": query, "kinds": ["drawing", "specification", "document"], "k": 6})
            payload = draft_rfi(str(inputs.get("question") or ""), hits_from_json(found.get("hits", [])), context)
            return payload, payload["subject"]
        if spec.name == "daily_reporter":
            day = str(inputs["date"])
            found = await call(TOOL_DAY, {"date": day})
            if found.get("error"):
                raise CatalogueError(str(found["error"]))
            payload = compose_daily_report(day, found.get("records") or {})
            return payload, f"Daily report {day}"
        if spec.name == "clause_reviewer":
            checklist = config.get("checklist") or DEFAULT_CLAUSE_CHECKLIST
            hits_by_item: dict[str, list] = {}
            for item in checklist:
                if item.get("enabled") is False:
                    continue
                args: dict[str, Any] = {"q": str(item.get("label") or item.get("key")), "kinds": ["contract"], "k": 4}
                if inputs.get("document_id"):
                    args["document_id"] = str(inputs["document_id"])
                elif inputs.get("contract_id"):
                    args["document_id"] = str(inputs["contract_id"])
                found = await call(TOOL_SEARCH, args)
                hits_by_item[str(item.get("key"))] = hits_from_json(found.get("hits", []))
            payload = review_clauses(hits_by_item, checklist)
            return payload, f"Clause review: {payload['flagged']} to check"
        if spec.name == "submittal_checker":
            sub = await call(TOOL_SUBMITTAL, {"submittal_id": str(inputs["submittal_id"])})
            if sub.get("error"):
                raise CatalogueError(str(sub["error"]))
            q = f"{sub.get('spec_section') or ''} {sub.get('title') or ''}".strip()
            found = await call(TOOL_SEARCH, {"q": q, "kinds": ["specification"], "k": 6})
            hits = hits_from_json(found.get("hits", []))
            section = str(sub.get("spec_section") or "").replace(" ", "")
            if section:
                in_section = [
                    h for h in hits if section in f"{h.passage.section or ''} {h.passage.title}".replace(" ", "")
                ]
                hits = in_section or hits
            payload = {
                **check_submittal(sub, hits),
                "submittal_id": sub.get("id"),
                "submittal_number": sub.get("number"),
            }
            return payload, f"Submittal check {sub.get('number') or ''}".strip()
        raise CatalogueError("unknown_agent")

    async def _narrative(
        self,
        spec: CatalogueSpec,
        payload: dict[str, Any],
        max_tokens: int,
        llm: LLMBridge | None,
        user_id: uuid.UUID,
    ) -> tuple[str | None, int, str | None]:
        """Optional model-written summary of the draft, capped by the project's token limit."""
        bridge = llm
        if bridge is None:
            from app.modules.ai_agents.service import _resolve_production_llm

            bridge = await _resolve_production_llm(self.session, user_id)
        if bridge is None:
            return None, 0, "no_llm"
        agent = Agent(
            name=f"{spec.name}_narrative",
            system_prompt=(
                "Summarise this draft for the person who will review it, in at most 6 sentences. Use only the "
                "facts in the JSON, keep every reference (document, revision, page, sheet, section) you mention "
                "exactly as given, and say what still needs checking."
            ),
            max_iterations=1,
            allowed_tools=[],
            max_total_tokens=max_tokens,
        )
        brief = json.dumps({k: v for k, v in payload.items() if k != "sources"}, ensure_ascii=False, default=str)
        result = await AgentRunner(bridge).run(agent, brief[:12_000])
        if result.status != "completed":
            return None, result.total_tokens, result.failure_reason or "failed"
        return result.final_output, result.total_tokens, None

    # ── Drafts and history ──────────────────────────────────────────────────

    async def drafts(self, project_id: uuid.UUID, status: str | None = None, limit: int = 100) -> list[AgentDraft]:
        stmt = select(AgentDraft).where(AgentDraft.project_id == project_id)
        if status:
            stmt = stmt.where(AgentDraft.status == status)
        stmt = stmt.order_by(AgentDraft.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def drafts_page(
        self, project_id: uuid.UUID, status: str | None, *, offset: int, limit: int
    ) -> tuple[list[AgentDraft], int]:
        cond = [AgentDraft.project_id == project_id]
        if status:
            cond.append(AgentDraft.status == status)
        total = (await self.session.execute(select(func.count()).select_from(AgentDraft).where(*cond))).scalar_one()
        stmt = select(AgentDraft).where(*cond).order_by(AgentDraft.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), int(total)

    async def history_page(self, project_id: uuid.UUID, *, offset: int, limit: int) -> tuple[list[AgentRun], int]:
        cond = [AgentRun.project_id == project_id, AgentRun.agent_name.in_(list(CATALOGUE))]
        total = (await self.session.execute(select(func.count()).select_from(AgentRun).where(*cond))).scalar_one()
        stmt = select(AgentRun).where(*cond).order_by(AgentRun.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), int(total)

    async def history(self, project_id: uuid.UUID, limit: int = 50) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .where(AgentRun.project_id == project_id, AgentRun.agent_name.in_(list(CATALOGUE)))
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def review(
        self,
        draft_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        decision: str,
        user_id: uuid.UUID,
        note: str | None = None,
        apply: bool = False,
        edits: dict[str, Any] | None = None,
    ) -> AgentDraft:
        """Accept or reject a draft; accepting an RFI draft with ``apply`` creates the RFI as a draft."""
        draft = await self.session.get(AgentDraft, draft_id)
        if draft is None or draft.project_id != project_id:
            raise CatalogueError("not_found")
        if draft.status != "pending":
            raise CatalogueError("already_reviewed")
        if decision not in ("accepted", "rejected"):
            raise CatalogueError("invalid_decision")
        if edits:
            draft.payload = {**(draft.payload or {}), **edits, "edited_by_reviewer": True}
        if decision == "accepted" and apply and draft.draft_kind == "rfi":
            draft.applied_record_id = await self._apply_rfi(draft, user_id)
        draft.status = decision
        draft.reviewed_by = user_id
        draft.reviewed_at = _now()
        draft.review_note = note
        await self.session.flush()
        return draft

    async def _apply_rfi(self, draft: AgentDraft, user_id: uuid.UUID) -> str:
        from app.modules.rfi.schemas import RFICreate
        from app.modules.rfi.service import RFIService

        p = draft.payload or {}
        refs = "\n".join(
            f"- {r.get('title')}"
            + (f", rev {r['revision']}" if r.get("revision") else "")
            + (f", sheet {r['sheet_number']}" if r.get("sheet_number") else "")
            + (f", page {r['page']}" if r.get("page") else "")
            + (f", {r['section']}" if r.get("section") else "")
            for r in p.get("references", [])
        )
        body = str(p.get("question") or "") + (f"\n\nReferences:\n{refs}" if refs else "")
        rfi = await RFIService(self.session).create_rfi(
            RFICreate(
                project_id=draft.project_id,
                subject=str(p.get("subject") or draft.title)[:500],
                question=body[:10000],
                status="draft",
                metadata={"source": "ai_agent", "agent": draft.agent_name, "draft_id": str(draft.id)},
            ),
            user_id=str(user_id),
        )
        return str(rfi.id)


def _sources_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten every citation or record reference a draft carries."""
    out: list[dict[str, Any]] = []
    for r in payload.get("references", []) or []:
        out.append(r)
    for f in payload.get("findings", []) or []:
        out.extend(f.get("citations", []))
    for r in payload.get("requirements", []) or []:
        if r.get("citation"):
            out.append(r["citation"])
    out.extend(payload.get("sources", []) or [])
    seen: set[str] = set()
    unique = []
    for s in out:
        key = str(s.get("passage_id") or f"{s.get('kind')}:{s.get('id')}")
        if key not in seen:
            seen.add(key)
            unique.append({k: v for k, v in s.items() if k != "text"})
    return unique
