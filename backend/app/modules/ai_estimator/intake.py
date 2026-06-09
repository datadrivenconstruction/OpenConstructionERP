# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Conversational intake (v2) state machine for the AI Estimate Builder.

This is the dialogue layer that sits in front of the existing run FSM. It turns
a vague free-text request ("ремонт кухни") into a confirmed parameter sheet
plus a composed, editable element-group board, then hands off to the verified
grouping -> matching -> apply pipeline unchanged.

The machine is identical for the AI and offline paths; only the SOURCE of the
clarification questions differs (LLM-phrased prompts vs the curated
questionnaire). Both paths share:

* deterministic project-type detection seeded by ``project_types`` synonyms
  (offline) or an LLM extraction that degrades to it (AI);
* the same curated round grouping (the LLM may only phrase the bounded set of
  questions, never invent more);
* the same pure quantity formulas (:mod:`quantities`);
* the same live vector-probe composer (Qdrant + the existing ranker, which need
  no LLM key), so even the offline path gets DB-grounded groups.

Invariants preserved: AI proposes / human confirms (two checkpoints), rates are
never invented (the composer only shapes the QUERY), confidence is a real probe
score or null, max 3 clarification rounds (a hard ceiling), and the flow never
500s (every external call degrades honestly).
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.models import (
    AiEstimatorGroup,
    AiEstimatorIntake,
    AiEstimatorRun,
)
from app.modules.ai_estimator.project_types import (
    FOREMAN_STAGE_TO_OMNICLASS,
    FOREMAN_STAGES,
    PROJECT_TYPE_ORDER,
    ProjectParam,
    ProjectType,
    WorkPackage,
    default_packages,
    dependency_warnings,
    detect_project_type,
    get_project_type,
    package_by_key,
    params_for_round,
)
from app.modules.ai_estimator.quantities import compute_quantity, describe_derivation
from app.modules.ai_estimator.repository import (
    AiEstimatorGroupRepository,
    AiEstimatorIntakeRepository,
    AiEstimatorRunRepository,
)

logger = logging.getLogger(__name__)

# The maximum number of clarification rounds (founder decision 1, a hard
# ceiling enforced in the machine and the API).
MAX_CLARIFY_ROUNDS = 3

# Readiness threshold above which the machine skips straight to the parameter
# sheet without burning a clarification round (confidence-driven skipping).
_READINESS_SKIP_THRESHOLD = 0.9

# Per-param status values.
_KNOWN = "known"
_ASKED = "asked"
_CONFIRMED = "confirmed"
_SKIPPED = "skipped"

# The ordered dialogue phases.
_INTAKE_PHASES: tuple[str, ...] = (
    "collect_request",
    "extract",
    "clarify_round_1",
    "clarify_round_2",
    "clarify_round_3",
    "parameter_sheet",
    "compose_groups",
    "group_board",
    "done",
)

# Vector-probe coverage thresholds (reuse the module's confidence bands).
from app.modules.ai_estimator.service import (  # noqa: E402
    CONFIDENCE_MEDIUM_THRESHOLD,
)

# A probe scoring below this floor is treated as no usable match (a gap).
_PROBE_LOW_FLOOR = 0.30
# The composer's total probe-call ceiling (20 cells x 3 phrasings). Beyond it,
# only the first phrasing of each cell is probed (honest cap, like the matcher).
_PROBE_CALL_CAP = 60
# top_k for a probe (small - we only need the top-1 score). The probes share the
# request's single AsyncSession (which is not concurrency-safe), so they run
# serially - see ``_compose`` for the rationale - rather than fanning out.
_PROBE_TOP_K = 5


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _coerce_value(param: ProjectParam, raw: Any) -> Any | None:
    """Coerce a raw answer to the parameter's kind, or None if unusable.

    Numbers / lengths coerce to float (rejecting junk and non-positive sizes);
    booleans accept truthy / yes-no strings; choices must be in the allowed set.
    A None / unusable value is dropped so the param stays unanswered rather than
    landing a fabricated value.
    """
    if raw is None:
        return None
    if param.kind in ("number", "length"):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            return None
        return value if value >= 0 else None
    if param.kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "yes", "y", "1", "да", "ja"):
            return True
        if s in ("false", "no", "n", "0", "нет", "nein"):
            return False
        return None
    if param.kind == "choice":
        s = str(raw).strip()
        if param.choices and s in param.choices:
            return s
        return None
    return None


class IntakeService:
    """Drives the conversational intake FSM (AI + offline paths, one machine)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repo = AiEstimatorRunRepository(session)
        self.intake_repo = AiEstimatorIntakeRepository(session)
        self.group_repo = AiEstimatorGroupRepository(session)

    # ── Public API: the six intake operations ─────────────────────────────

    async def start(self, spec: schemas.IntakeCreate, user_id: uuid.UUID) -> tuple[AiEstimatorRun, AiEstimatorIntake]:
        """Create a run (status ``intake``) + intake row and run ``extract``.

        Returns the (run, intake) pair; the caller serialises an
        :class:`schemas.IntakeState`.
        """
        ai_connected, _provider, _model = await self._ai_status(user_id)
        mode = self._resolve_mode(spec.mode_hint, ai_connected)

        run = AiEstimatorRun(
            project_id=spec.project_id,
            user_id=user_id,
            name=spec.name,
            status="intake",
            current_stage="source",
            source_inputs={
                "source": "text",
                "text_input": spec.text or "",
                "file_refs": [],
                "rows": [],
                "bim_model_ids": [],
                "document_ids": [],
                "boq_ids": [],
                "intake": True,
            },
            catalogue_id=spec.catalogue_id,
            region=spec.region,
            currency=(spec.currency or "").upper() or None,
            metadata_={"intake": True},
        )
        run = await self.run_repo.create(run)

        intake = AiEstimatorIntake(
            run_id=run.id,
            mode=mode,
            raw_request=spec.text or "",
            phase="collect_request",
            transcript=([{"role": "user", "text": spec.text, "ts": _now_iso()}] if spec.text else []),
        )
        intake = await self.intake_repo.create(intake)

        await self._run_extract(run, intake, manual_type=spec.project_type)
        intake = await self._reload_intake(run.id)
        return run, intake

    async def answer(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, spec: schemas.IntakeAnswerRequest
    ) -> AiEstimatorIntake:
        """Record the current round's answers and (optionally) advance the FSM."""
        pt = self._require_type(intake, spec.project_type)
        if spec.project_type and spec.project_type != intake.detected_type:
            # The user changed the type: re-seed the sheet from the raw text.
            await self._reseed_type(run, intake, spec.project_type)
            intake = await self._reload_intake(run.id)
            pt = self._require_type(intake)

        params = dict(intake.params or {})
        status = dict(intake.param_status or {})
        transcript = list(intake.transcript or [])

        recorded: list[str] = []
        for key, raw in (spec.answers or {}).items():
            param = self._param(pt, key)
            if param is None:
                continue
            value = _coerce_value(param, raw)
            if value is None:
                continue
            params[key] = value
            status[key] = _CONFIRMED
            recorded.append(key)

        if recorded:
            transcript.append({"role": "user", "text": self._format_answers(pt, spec.answers), "ts": _now_iso()})

        await self.intake_repo.update_fields(intake.id, params=params, param_status=status, transcript=transcript)
        intake = await self._reload_intake(run.id)

        if not spec.advance:
            return intake
        return await self._advance(run, intake, pt)

    async def confirm_parameters(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, spec: schemas.ConfirmParametersRequest
    ) -> AiEstimatorIntake:
        """Confirm the parameter sheet (checkpoint A) and compose the board."""
        pt = self._require_type(intake)
        params = dict(intake.params or {})
        status = dict(intake.param_status or {})
        for key, raw in (spec.params or {}).items():
            param = self._param(pt, key)
            if param is None:
                continue
            value = _coerce_value(param, raw)
            if value is None:
                continue
            params[key] = value
            status[key] = _CONFIRMED
        # Fill any still-missing required param with its declared default so the
        # sheet is complete without a fourth round (the user can edit it).
        self._apply_defaults(pt, params, status)
        await self.intake_repo.update_fields(intake.id, params=params, param_status=status, phase="compose_groups")
        intake = await self._reload_intake(run.id)
        await self._compose(run, intake, pt, selected_keys=None)
        return await self._reload_intake(run.id)

    async def edit_packages(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, spec: schemas.IntakePackagesRequest
    ) -> AiEstimatorIntake:
        """Edit the package board: add / remove / toggle packages (checkpoint B).

        Removing a package deletes its composed groups; adding or toggling-on a
        package re-probes it (editing a package honestly re-probes it).
        """
        pt = self._require_type(intake)
        board = {p["package_key"]: dict(p) for p in (intake.packages or [])}

        # Remove: drop the package and delete its groups.
        for key in spec.remove or []:
            entry = board.pop(key, None)
            if entry:
                await self._delete_groups(entry.get("group_ids") or [])

        # Toggle: flip selected; toggling on re-probes, toggling off keeps the
        # entry but drops its groups so the rates are not matched.
        recompose: list[str] = []
        for key, on in (spec.toggle or {}).items():
            entry = board.get(key)
            if entry is None:
                continue
            entry["selected"] = bool(on)
            if on:
                recompose.append(key)
            else:
                await self._delete_groups(entry.get("group_ids") or [])
                entry["group_ids"] = []

        # Add: curated keys re-compose; custom descriptions become a manual
        # group the composer probes immediately.
        custom: list[schemas.WorkPackageSelection] = []
        for sel in spec.add or []:
            if sel.package_key and package_by_key(pt, sel.package_key):
                board.setdefault(
                    sel.package_key,
                    {"package_key": sel.package_key, "selected": True, "group_ids": []},
                )["selected"] = True
                recompose.append(sel.package_key)
            elif sel.custom_description:
                custom.append(sel)

        await self.intake_repo.update_fields(intake.id, packages=list(board.values()))
        intake = await self._reload_intake(run.id)

        if recompose:
            await self._compose(run, intake, pt, selected_keys=set(recompose))
            intake = await self._reload_intake(run.id)
        for sel in custom:
            await self._compose_custom(run, intake, sel)
            intake = await self._reload_intake(run.id)
        return intake

    async def finish(self, run: AiEstimatorRun, intake: AiEstimatorIntake, user_id: uuid.UUID) -> AiEstimatorRun:
        """Confirm the group board (checkpoint B) and bridge to the run FSM.

        Advances the run to exactly where the legacy ``confirm_stage("source")``
        lands (status ``grouping``, current_stage ``grouping``, the ``source``
        checkpoint recorded), so the rest of the pipeline (match / preview /
        apply) is untouched. The composed groups ARE the grouping output, so a
        ``metadata_.intake_composed`` flag tells ``confirm_stage`` not to
        re-derive groups and wipe the composed ones.
        """
        checkpoints = dict(run.checkpoints or {})
        checkpoints["source"] = {"accepted_at": _now_iso(), "by": str(user_id)}
        metadata = dict(run.metadata_ or {})
        metadata["intake_composed"] = True
        # Carry the confirmed config the user picked through to the run.
        await self.run_repo.update_fields(
            run.id,
            status="grouping",
            current_stage="grouping",
            checkpoints=checkpoints,
            metadata_=metadata,
            group_by=list(run.group_by or ["category", "unit"]),
        )
        await self.intake_repo.update_fields(intake.id, phase="done")
        refreshed = await self.run_repo.get_by_id(run.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    # ── FSM: extract + round advancement ──────────────────────────────────

    async def _run_extract(self, run: AiEstimatorRun, intake: AiEstimatorIntake, *, manual_type: str | None) -> None:
        """Detect the project type + seed params, then open round 1 (or skip)."""
        await self.intake_repo.update_fields(intake.id, phase="extract")

        detected, confidence, seeded, summary, degraded = await self._extract(run, intake, manual_type=manual_type)

        status = dict.fromkeys(seeded, _KNOWN)
        await self.intake_repo.update_fields(
            intake.id,
            detected_type=detected,
            type_confidence=confidence,
            params=seeded,
            param_status=status,
        )
        intake = await self._reload_intake(run.id)
        await self._log_thought(run, summary or "Detecting project type and parameters.")

        if not detected:
            # Ambiguous / unknown: stay at extract; the UI shows the type tiles.
            await self.intake_repo.update_fields(intake.id, phase="extract")
            return

        pt = get_project_type(detected)
        assert pt is not None  # noqa: S101 - detected is a registry key
        await self._open_next_round(run, intake, pt, from_round=0)

    async def _extract(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, *, manual_type: str | None
    ) -> tuple[str | None, float | None, dict[str, Any], str | None, str | None]:
        """Return (type, confidence, seeded_params, summary, degraded_reason).

        AI path: an LLM extraction that degrades to the deterministic detector
        on any failure. Offline path: the deterministic synonym detector +
        ``parse_text_scope`` for any explicit quantities. A manual type pick
        always wins over detection.
        """
        text = intake.raw_request or ""
        seeded = self._seed_from_text(text)

        if manual_type and get_project_type(manual_type):
            return manual_type, None, self._filter_params(manual_type, seeded), None, None

        if intake.mode == "ai":
            ai = await self._extract_ai(run, intake, text)
            if ai is not None:
                detected, confidence, ai_params, summary = ai
                merged = {**seeded, **ai_params}
                if detected and get_project_type(detected):
                    return detected, confidence, self._filter_params(detected, merged), summary, None
                # AI unsure of type: fall through to deterministic detection.
                seeded = merged

        # Offline / degraded deterministic detection.
        detected, count = detect_project_type(text)
        degraded = "no_ai_key" if intake.mode == "offline" else None
        if detected:
            return detected, None, self._filter_params(detected, seeded), None, degraded
        return None, None, seeded, None, degraded

    async def _extract_ai(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, text: str
    ) -> tuple[str | None, float | None, dict[str, Any], str | None] | None:
        """Run the LLM extraction pass. Returns None on any degradation."""
        from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
        from app.modules.ai_estimator.prompts import (
            INTAKE_EXTRACT_SYSTEM,
            build_intake_extract_prompt,
        )

        settings = await AISettingsRepository(self.session).get_by_user_id(run.user_id)
        try:
            provider, api_key, model = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.info("intake extract: degrading to deterministic (%s)", exc)
            await self._log_observation(run, {"degraded": "no_ai_key"})
            return None

        prompt = build_intake_extract_prompt(request_text=text, type_registry_digest=self._type_registry_digest())
        try:
            raw, _tokens = await call_ai(
                provider=provider, api_key=api_key, system=INTAKE_EXTRACT_SYSTEM, prompt=prompt, model=model
            )
        except ValueError as exc:
            logger.info("intake extract: AI call failed, degrading (%s)", exc)
            await self._log_observation(run, {"degraded": "llm_error", "message": str(exc)[:200]})
            return None

        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            return None
        detected = str(parsed.get("project_type") or "").strip() or None
        confidence = self._real_confidence(parsed.get("type_confidence"))
        ai_params = parsed.get("params") if isinstance(parsed.get("params"), dict) else {}
        summary = str(parsed.get("summary") or "")[:400] or None
        return detected, confidence, dict(ai_params or {}), summary

    async def _advance(self, run: AiEstimatorRun, intake: AiEstimatorIntake, pt: ProjectType) -> AiEstimatorIntake:
        """Compute the next phase after a round's answers were recorded."""
        round_idx = int(intake.round_idx or 0)

        # Confidence-driven skipping: if the sheet is ready, jump to the sheet
        # without burning a round; if the round cap is hit, go to the sheet and
        # default the rest. Otherwise open the next round.
        if self._readiness(pt, intake.params or {}) >= _READINESS_SKIP_THRESHOLD:
            return await self._goto_parameter_sheet(run, intake, pt)
        if round_idx >= MAX_CLARIFY_ROUNDS:
            return await self._goto_parameter_sheet(run, intake, pt)
        return await self._open_next_round(run, intake, pt, from_round=round_idx)

    async def _open_next_round(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, pt: ProjectType, *, from_round: int
    ) -> AiEstimatorIntake:
        """Open the next round that still has unanswered questions (cap 3).

        Skips a round whose questions are all already answered. If no round
        within the cap has unresolved questions, goes straight to the sheet.
        """
        params = dict(intake.params or {})
        for nxt in range(from_round + 1, MAX_CLARIFY_ROUNDS + 1):
            pending = [p for p in params_for_round(pt, nxt) if p.key not in params]
            if not pending:
                continue
            questions = await self._build_questions(run, intake, pt, pending)
            status = dict(intake.param_status or {})
            for p in pending:
                status[p.key] = _ASKED
            await self.intake_repo.update_fields(
                intake.id,
                phase=f"clarify_round_{nxt}",
                round_idx=nxt,
                questions=[q.model_dump() for q in questions],
                param_status=status,
            )
            await self._log_thought(run, f"Clarification round {nxt} of up to {MAX_CLARIFY_ROUNDS}.")
            return await self._reload_intake(run.id)

        # Every remaining round is already answered: ready for the sheet.
        return await self._goto_parameter_sheet(run, intake, pt)

    async def _goto_parameter_sheet(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, pt: ProjectType
    ) -> AiEstimatorIntake:
        """Apply defaults for still-missing required params and open the sheet."""
        params = dict(intake.params or {})
        status = dict(intake.param_status or {})
        self._apply_defaults(pt, params, status)
        await self.intake_repo.update_fields(
            intake.id, phase="parameter_sheet", params=params, param_status=status, questions=[]
        )
        await self._log_thought(run, "Parameter sheet ready for review.")
        return await self._reload_intake(run.id)

    # ── Question building (AI-phrased or curated) ─────────────────────────

    async def _build_questions(
        self,
        run: AiEstimatorRun,
        intake: AiEstimatorIntake,
        pt: ProjectType,
        pending: list[ProjectParam],
    ) -> list[schemas.IntakeQuestion]:
        """Build the question batch for a round (curated, optionally LLM-phrased).

        The SET of questions is always the curated ``pending`` list (the LLM can
        never run away with extra questions); only the prompt WORDING is
        LLM-phrased on the AI path, and it degrades to the curated default.
        """
        prompts = {}
        if intake.mode == "ai":
            prompts = await self._phrase_questions_ai(run, pt, pending)
        return [self._curated_question(p, prompts.get(p.key)) for p in pending]

    def _curated_question(self, param: ProjectParam, llm_prompt: str | None) -> schemas.IntakeQuestion:
        """Render one :class:`IntakeQuestion` from a curated param (+ LLM prompt)."""
        options = (
            [schemas.IntakeQuestionOption(value=c, label_key=f"aiest.choice.{c}") for c in param.choices]
            if param.kind == "choice" and param.choices
            else []
        )
        return schemas.IntakeQuestion(
            param_key=param.key,
            kind=param.kind,  # type: ignore[arg-type]
            unit=param.unit,
            required=param.required,
            options=options,
            prompt=llm_prompt or f"aiest.q.{param.key}",
            why=f"aiest.why.{param.key}",
            current_value=None,
        )

    async def _phrase_questions_ai(
        self, run: AiEstimatorRun, pt: ProjectType, pending: list[ProjectParam]
    ) -> dict[str, str]:
        """LLM-phrase the round's questions. Returns {} on any degradation."""
        from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
        from app.modules.ai_estimator.prompts import (
            INTAKE_QUESTIONS_SYSTEM,
            build_intake_questions_prompt,
        )

        settings = await AISettingsRepository(self.session).get_by_user_id(run.user_id)
        try:
            provider, api_key, model = resolve_provider_key_model(settings)
        except ValueError:
            return {}

        digest = "\n".join(
            f"- {p.key} | kind={p.kind} | unit={p.unit or ''} | choices={','.join(p.choices or ())}" for p in pending
        )
        prompt = build_intake_questions_prompt(language=self._language(run), params_digest=digest)
        try:
            raw, _tokens = await call_ai(
                provider=provider, api_key=api_key, system=INTAKE_QUESTIONS_SYSTEM, prompt=prompt, model=model
            )
        except ValueError:
            return {}
        parsed = extract_json(raw)
        out: dict[str, str] = {}
        if isinstance(parsed, list):
            valid = {p.key for p in pending}
            for item in parsed:
                if isinstance(item, dict):
                    key = str(item.get("param_key") or "")
                    text = str(item.get("prompt") or "").strip()
                    if key in valid and text:
                        out[key] = text[:200]
        return out

    # ── The hybrid checklist + live vector-probe composer ─────────────────

    async def _compose(
        self,
        run: AiEstimatorRun,
        intake: AiEstimatorIntake,
        pt: ProjectType,
        *,
        selected_keys: set[str] | None,
    ) -> None:
        """Compose element groups for the selected packages (probe + persist).

        For each selected (package x stage) cell: compute the quantity from the
        confirmed sheet, probe the live vector DB with the curated phrasings,
        keep the best-scoring phrasing as the group description, classify the
        coverage (grounded / weak / gap), persist one ``AiEstimatorGroup``, and
        record the package on the board. Gaps are never dropped - they are
        created and disclosed honestly.
        """
        params = dict(intake.params or {})
        existing = {p["package_key"]: dict(p) for p in (intake.packages or [])}

        # Which packages to compose: the curated default checklist on the first
        # compose, or the explicitly-requested subset on a board edit.
        if selected_keys is None:
            packages = list(default_packages(pt))
        else:
            packages = [pkg for pkg in pt.packages if pkg.key in selected_keys]

        # Build the (package x stage) cell list and cap the probe fan-out.
        cells: list[tuple[WorkPackage, str]] = []
        for pkg in packages:
            for stage in pkg.stages:
                cells.append((pkg, stage))
        probe_first_only = len(cells) > _PROBE_CALL_CAP // 3

        await self._log_thought(
            run,
            f"Probing the cost database across {len(packages)} work package(s).",
        )

        # Drop any prior groups for the packages we are about to (re)compose.
        for pkg in packages:
            entry = existing.get(pkg.key)
            if entry:
                await self._delete_groups(entry.get("group_ids") or [])

        sort_base = await self._next_sort_order(run.id)
        # The probe goes through ``rank()``, which uses THIS request's shared
        # AsyncSession. An AsyncSession is not safe for concurrent use, so the
        # cells are probed one at a time (the per-phrasing fan-out inside
        # ``_probe_best`` is likewise serialised). Running them through
        # ``asyncio.gather`` here corrupted the session mid-request: every probe
        # failed with MissingGreenlet (silently degrading the whole board to
        # gaps) and, worse, the shared ``run`` instance was left expired so the
        # very next ``run.currency`` read in ``_persist_group`` raised and 500'd
        # the confirm-parameters call. Sequential probing keeps the session
        # consistent and the real grounded scores intact.
        semaphore = asyncio.Semaphore(1)

        async def _probe_cell(pkg: WorkPackage, stage: str) -> dict[str, Any]:
            phrasings = pkg.probes if not probe_first_only else pkg.probes[:1]
            best_desc, best_score = await self._probe_best(run, phrasings, pkg.unit, stage, semaphore)
            return {"pkg": pkg, "stage": stage, "desc": best_desc, "score": best_score}

        results: list[dict[str, Any]] = [await _probe_cell(pkg, stage) for pkg, stage in cells]

        # Persist groups in build-stage order so the board reads top-to-bottom.
        results.sort(key=lambda r: (FOREMAN_STAGES.index(r["stage"]), r["pkg"].key))
        per_package: dict[str, dict[str, Any]] = {}
        grounded = weak = gap = 0
        for offset, res in enumerate(results):
            pkg: WorkPackage = res["pkg"]
            stage: str = res["stage"]
            qty = compute_quantity(pkg.qty_formula, params, pkg.unit)
            coverage = self._coverage(res["score"])
            grounded += coverage == "grounded"
            weak += coverage == "weak"
            gap += coverage == "gap"
            group = await self._persist_group(
                run, pkg, stage, res["desc"], res["score"], qty, sort_base + offset, params=params
            )
            board = per_package.setdefault(
                pkg.key,
                {
                    "package_key": pkg.key,
                    "trade": pkg.trade,
                    "selected": True,
                    "stages": list(pkg.stages),
                    "group_ids": [],
                    "coverage": coverage,
                    "best_score": res["score"],
                    "quantity": qty.quantity,
                    "unit": pkg.unit,
                    "estimated": qty.estimated,
                },
            )
            board["group_ids"].append(str(group.id))
            # The package coverage is the best (greenest) of its cells.
            board["coverage"] = self._merge_coverage(board["coverage"], coverage)
            if res["score"] is not None and (board["best_score"] is None or res["score"] > board["best_score"]):
                board["best_score"] = res["score"]

        # Merge into the existing board, then flip to group_board phase.
        merged = {**existing, **per_package}
        await self.intake_repo.update_fields(intake.id, packages=list(merged.values()), phase="group_board")
        await self._log_stage_complete(
            run, {"grounded": grounded, "weak": weak, "gap": gap, "packages": len(per_package)}
        )

    async def _compose_custom(
        self, run: AiEstimatorRun, intake: AiEstimatorIntake, sel: schemas.WorkPackageSelection
    ) -> None:
        """Compose a single custom (free-text) work group, probed immediately."""
        desc = (sel.custom_description or "").strip()
        if not desc:
            return
        unit = sel.unit or "pcs"
        semaphore = asyncio.Semaphore(1)
        best_desc, best_score = await self._probe_best(run, (desc,), unit, "finish", semaphore)
        sort_base = await self._next_sort_order(run.id)
        # A custom group carries a zero quantity for the user to fill in.
        from app.modules.ai_estimator.quantities import QtyResult

        group = await self._persist_group(
            run,
            _custom_package(desc, unit),
            "finish",
            best_desc or desc,
            best_score,
            QtyResult(0.0, unit, estimated=False),
            sort_base,
        )
        board = {p["package_key"]: dict(p) for p in (intake.packages or [])}
        key = f"custom_{group.id}"
        board[key] = {
            "package_key": key,
            "trade": "other",
            "selected": True,
            "stages": ["finish"],
            "group_ids": [str(group.id)],
            "coverage": self._coverage(best_score),
            "best_score": best_score,
            "quantity": 0.0,
            "unit": unit,
            "estimated": False,
        }
        await self.intake_repo.update_fields(intake.id, packages=list(board.values()))

    async def _probe_best(
        self,
        run: AiEstimatorRun,
        phrasings: tuple[str, ...],
        unit: str,
        stage: str,
        semaphore: asyncio.Semaphore,
    ) -> tuple[str | None, float | None]:
        """Probe each phrasing through the real ranker; keep the best top-1 score.

        Uses the SAME grounded ranker the real match uses (a lightweight
        envelope: description + unit + the OmniClass stage hint + project
        currency/region). Returns (best_phrasing, best_score). On any failure
        (no vectors, no catalogue, ranker error) returns (first_phrasing, None)
        so the cell is an honest gap rather than a crash.
        """
        if not phrasings:
            return None, None
        best_desc: str | None = phrasings[0]
        best_score: float | None = None

        async def _one(text: str) -> tuple[str, float | None]:
            async with semaphore:
                return text, await self._probe_score(run, text, unit, stage)

        try:
            scored = await asyncio.gather(*[_one(t) for t in phrasings])
        except Exception as exc:  # noqa: BLE001 - degrade to a gap, never crash
            logger.warning("intake probe failed: %s", exc)
            return best_desc, None

        for text, score in scored:
            if score is not None and (best_score is None or score > best_score):
                best_score = score
                best_desc = text
        return best_desc, best_score

    async def _probe_score(self, run: AiEstimatorRun, text: str, unit: str, stage: str) -> float | None:
        """Return the top-1 grounded score for one phrasing, or None."""
        from app.core.match_service.envelope import ElementEnvelope, MatchRequest
        from app.core.match_service.ranker_qdrant import rank

        envelope = ElementEnvelope(
            source="text",
            description=text[:2000],
            unit_hint=unit if unit in ("m", "m2", "m3", "kg", "pcs") else None,
            project_currency=(run.currency or "").upper(),
            project_region=run.region or "",
            construction_stage_hint=FOREMAN_STAGE_TO_OMNICLASS.get(stage),
        )
        try:
            resp = await rank(
                MatchRequest(
                    envelope=envelope,
                    project_id=run.project_id,
                    top_k=_PROBE_TOP_K,
                    use_reranker=True,
                ),
                db=self.session,
            )
        except Exception as exc:  # noqa: BLE001 - any probe failure is a gap
            logger.warning("intake probe rank failed: %s", exc)
            return None
        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            return None
        top = candidates[0]
        score = getattr(top, "score", None)
        return self._real_confidence(score)

    async def _persist_group(
        self,
        run: AiEstimatorRun,
        pkg: WorkPackage,
        stage: str,
        description: str | None,
        score: float | None,
        qty: Any,
        sort_order: int,
        params: dict[str, Any] | None = None,
    ) -> AiEstimatorGroup:
        """Write one composed :class:`AiEstimatorGroup` ready for run_matching.

        The WorkGroup provenance fields the design standardises (section 3.1)
        are written uniformly into ``metadata_`` here, the single dialogue-path
        creation site: ``derivation`` (the formula id plus a short human
        sentence), ``assumptions`` (the proxies actually applied for these
        params), and ``source="dialogue"``. They ride the existing free JSON
        column, so there is no migration.
        """
        desc = (description or pkg.key)[:500]
        quantities = self._quantities_dict(pkg.unit, qty.quantity)
        derivation_text, assumptions = describe_derivation(pkg.qty_formula, params or {}, qty)
        envelope = {
            "source": "text",
            "description": desc,
            "category": pkg.trade,
            "unit_hint": pkg.unit if pkg.unit in ("m", "m2", "m3", "kg", "pcs") else None,
            "project_currency": (run.currency or "").upper(),
            "project_region": run.region or "",
            "construction_stage_hint": FOREMAN_STAGE_TO_OMNICLASS.get(stage),
        }
        group = AiEstimatorGroup(
            run_id=run.id,
            group_key=f"{pkg.key}|{stage}",
            element_ids=[],
            element_count=1,
            quantities=quantities,
            envelope=envelope,
            chosen_unit=pkg.unit,
            description=desc,
            trade=pkg.trade,
            status="unmatched",
            sort_order=sort_order,
            metadata_={
                "intake": True,
                "package_key": pkg.key,
                "foreman_stage": stage,
                "probe": {"chosen": desc, "score": score},
                "estimated": bool(getattr(qty, "estimated", False)),
                "coverage": self._coverage(score),
                # WorkGroup provenance (design 3.1), written uniformly here.
                "source": "dialogue",
                "qty_formula": pkg.qty_formula,
                "derivation": derivation_text,
                "assumptions": assumptions,
            },
        )
        return await self.group_repo.add(group)

    # ── State serialisation ───────────────────────────────────────────────

    async def to_state(self, run: AiEstimatorRun, intake: AiEstimatorIntake) -> schemas.IntakeState:
        """Serialise the (run, intake) pair to the :class:`IntakeState` payload."""
        ai_connected, _provider, _model = await self._ai_status(run.user_id)
        vector_ready, _vec = await self._vector_status(run)
        degraded = self._degraded_reason(intake.mode, ai_connected, vector_ready, run)
        round_idx = int(intake.round_idx or 0)
        questions = [schemas.IntakeQuestion.model_validate(q) for q in (intake.questions or [])]
        packages = [self._board_to_schema(p) for p in (intake.packages or [])]
        warnings = self._dependency_warnings(intake)
        return schemas.IntakeState(
            run_id=run.id,
            mode=intake.mode,  # type: ignore[arg-type]
            phase=intake.phase,  # type: ignore[arg-type]
            round_idx=round_idx,
            rounds_remaining=max(0, MAX_CLARIFY_ROUNDS - round_idx),
            detected_type=intake.detected_type,
            type_confidence=intake.type_confidence,
            params=dict(intake.params or {}),
            questions=questions,
            packages=packages,
            dependency_warnings=warnings,
            transcript=list(intake.transcript or []),
            ai_connected=ai_connected,
            vector_ready=vector_ready,
            degraded_reason=degraded,
            summary=self._last_assistant_text(intake),
        )

    @staticmethod
    def _board_to_schema(entry: dict[str, Any]) -> schemas.ComposedPackage:
        return schemas.ComposedPackage(
            package_key=str(entry.get("package_key") or ""),
            trade=str(entry.get("trade") or "other"),
            selected=bool(entry.get("selected", True)),
            stages=list(entry.get("stages") or []),
            group_ids=[uuid.UUID(g) for g in (entry.get("group_ids") or []) if _is_uuid(g)],
            coverage=entry.get("coverage") or "gap",  # type: ignore[arg-type]
            best_score=entry.get("best_score"),
            quantity=float(entry.get("quantity") or 0.0),
            unit=str(entry.get("unit") or "pcs"),
            estimated=bool(entry.get("estimated", False)),
        )

    @staticmethod
    def _dependency_warnings(intake: AiEstimatorIntake) -> list[dict[str, str]]:
        """Advisory foreman-sequence warnings for the selected package board.

        Reads the currently-selected curated packages off the board and runs the
        stage-dependency DAG (:func:`project_types.dependency_warnings`). Empty
        until the board exists or when no type is resolved. Custom (free-text)
        packages have no curated prerequisites, so they never raise a warning.
        """
        pt = get_project_type(intake.detected_type) if intake.detected_type else None
        if pt is None:
            return []
        selected = {
            str(p.get("package_key"))
            for p in (intake.packages or [])
            if p.get("selected", True) and p.get("package_key")
        }
        if not selected:
            return []
        return dependency_warnings(pt, selected)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_mode(mode_hint: str | None, ai_connected: bool) -> str:
        """Pick the dialogue mode: an explicit hint wins, else AI when connected."""
        if mode_hint in ("ai", "offline"):
            return mode_hint
        return "ai" if ai_connected else "offline"

    @staticmethod
    def _seed_from_text(text: str) -> dict[str, Any]:
        """Seed explicit quantities the user wrote (offline parity with v1).

        Reuses ``parse_text_scope`` to read a leading "<number> <unit>" and maps
        an area onto ``floor_area_m2``. The v1 parser only reads a LEADING
        quantity, but an intake free-text request usually trails it
        ("ремонт дома 120м2"), so we also scan for a "<number> m2 / м2" anywhere
        in the text as the floor area. Only numbers the user actually wrote are
        seeded - never an invented quantity.
        """
        from app.modules.ai_estimator.extractors import parse_text_scope

        seeded: dict[str, Any] = {}
        for env in parse_text_scope(text):
            q = env.get("quantities") or {}
            if "area_m2" in q and "floor_area_m2" not in seeded:
                seeded["floor_area_m2"] = float(q["area_m2"])
        if "floor_area_m2" not in seeded:
            area = _scan_trailing_area_m2(text)
            if area is not None:
                seeded["floor_area_m2"] = area
        return seeded

    @staticmethod
    def _filter_params(type_key: str, params: dict[str, Any]) -> dict[str, Any]:
        """Keep only params that exist in the type's questionnaire (drop noise)."""
        pt = get_project_type(type_key)
        if pt is None:
            return {}
        valid = {p.key: p for p in pt.params}
        out: dict[str, Any] = {}
        for key, raw in params.items():
            param = valid.get(key)
            if param is None:
                continue
            value = _coerce_value(param, raw)
            if value is not None:
                out[key] = value
        return out

    @staticmethod
    def _apply_defaults(pt: ProjectType, params: dict[str, Any], status: dict[str, Any]) -> None:
        """Fill still-missing params that declare a default (clearly labelled)."""
        for p in pt.params:
            if p.key not in params and p.default is not None:
                params[p.key] = p.default
                status[p.key] = _SKIPPED

    @staticmethod
    def _readiness(pt: ProjectType, params: dict[str, Any]) -> float:
        """Required-param coverage in [0,1] (the round-skip readiness score).

        Weighted by how much quantity each required param unlocks (more unlocks
        = more weight), so answering the high-payoff questions reaches the skip
        threshold faster.
        """
        required = [p for p in pt.params if p.required]
        if not required:
            return 1.0
        total = sum(max(len(p.unlocks), 1) for p in required)
        have = sum(max(len(p.unlocks), 1) for p in required if p.key in params)
        return have / total if total else 1.0

    def _quantities_dict(self, unit: str, quantity: float) -> dict[str, float]:
        """Map a (unit, quantity) onto the canonical quantity dict the matcher uses."""
        key = {
            "m3": "volume_m3",
            "m2": "area_m2",
            "m": "length_m",
            "kg": "mass_kg",
            "pcs": "count",
            "lsum": "count",
        }.get(unit, "count")
        return {key: float(quantity)} if quantity else {}

    @staticmethod
    def _coverage(score: float | None) -> str:
        """Map a real probe score to a coverage band (grounded / weak / gap)."""
        if score is None or score < _PROBE_LOW_FLOOR:
            return "gap"
        if score >= CONFIDENCE_MEDIUM_THRESHOLD:
            return "grounded"
        return "weak"

    @staticmethod
    def _merge_coverage(current: str, candidate: str) -> str:
        """Return the greenest of two coverage bands (a package's best cell)."""
        order = {"gap": 0, "weak": 1, "grounded": 2}
        return current if order.get(current, 0) >= order.get(candidate, 0) else candidate

    @staticmethod
    def _real_confidence(value: Any) -> float | None:
        """Coerce a probe/model score to a real [0,1] float, else None."""
        try:
            c = float(value)
        except (TypeError, ValueError):
            return None
        if c < 0 or c > 1:
            return None
        return round(c, 4)

    @staticmethod
    def _type_registry_digest() -> str:
        """Compact, safe digest of the type registry for the LLM extractor."""
        lines: list[str] = []
        for key in PROJECT_TYPE_ORDER:
            pt = get_project_type(key)
            if pt is None:
                continue
            syns = ", ".join((*pt.synonyms_en[:3], *pt.synonyms_ru[:2], *pt.synonyms_de[:2]))
            param_keys = ", ".join(p.key for p in pt.params)
            lines.append(f"{key}: synonyms=[{syns}]; params=[{param_keys}]")
        return "\n".join(lines)

    @staticmethod
    def _format_answers(pt: ProjectType, answers: dict[str, Any]) -> str:
        """A short transcript line summarising the user's answers (factual)."""
        parts = [f"{k}={v}" for k, v in answers.items()]
        return ", ".join(parts)[:400]

    @staticmethod
    def _language(run: AiEstimatorRun) -> str:
        """Best-effort UI language for question phrasing (region-derived)."""
        region = (run.region or "").upper()
        if region.startswith("RU") or region.startswith("MN"):
            return "ru"
        if region.startswith("DE") or region.startswith("AT") or region.startswith("CH"):
            return "de"
        return "en"

    @staticmethod
    def _last_assistant_text(intake: AiEstimatorIntake) -> str | None:
        for turn in reversed(intake.transcript or []):
            if turn.get("role") == "assistant":
                return str(turn.get("text") or "") or None
        return None

    def _require_type(self, intake: AiEstimatorIntake, override: str | None = None) -> ProjectType:
        """Return the resolved project type or 409 when none has been chosen."""
        key = override or intake.detected_type
        pt = get_project_type(key) if key else None
        if pt is None:
            raise HTTPException(status_code=409, detail="No project type selected yet. Pick a type to continue.")
        return pt

    @staticmethod
    def _param(pt: ProjectType, key: str) -> ProjectParam | None:
        for p in pt.params:
            if p.key == key:
                return p
        return None

    async def _reseed_type(self, run: AiEstimatorRun, intake: AiEstimatorIntake, type_key: str) -> None:
        """Re-seed the sheet for a user-changed type from the original text."""
        seeded = self._filter_params(type_key, self._seed_from_text(intake.raw_request or ""))
        await self.intake_repo.update_fields(
            intake.id,
            detected_type=type_key,
            type_confidence=None,
            params=seeded,
            param_status=dict.fromkeys(seeded, _KNOWN),
            round_idx=0,
            questions=[],
            phase="extract",
        )

    async def _delete_groups(self, group_ids: list[str]) -> None:
        """Delete composed groups by id (board remove / toggle-off / recompose)."""
        for gid in group_ids:
            if not _is_uuid(gid):
                continue
            grp = await self.group_repo.get_by_id(uuid.UUID(gid))
            if grp is not None:
                await self.session.delete(grp)
        await self.session.flush()

    async def _next_sort_order(self, run_id: uuid.UUID) -> int:
        """Return the next free sort_order so re-composed groups append cleanly."""
        groups = await self.group_repo.list_for_run(run_id)
        return (max((int(g.sort_order or 0) for g in groups), default=-1) + 1) if groups else 0

    async def _reload_intake(self, run_id: uuid.UUID) -> AiEstimatorIntake:
        intake = await self.intake_repo.get_for_run(run_id)
        assert intake is not None  # noqa: S101
        return intake

    # ── Status helpers (reuse the run service's probes) ───────────────────

    async def _ai_status(self, user_id: uuid.UUID) -> tuple[bool, str | None, str | None]:
        from app.modules.ai_estimator.service import AiEstimatorService

        return await AiEstimatorService(self.session)._ai_status(user_id)

    async def _vector_status(self, run: AiEstimatorRun) -> tuple[bool, int]:
        from app.modules.ai_estimator.service import AiEstimatorService

        return await AiEstimatorService(self.session)._vector_status(run)

    @staticmethod
    def _degraded_reason(mode: str, ai_connected: bool, vector_ready: bool, run: AiEstimatorRun) -> str | None:
        """Pick the single most relevant degradation reason for the banner."""
        if mode == "offline" or not ai_connected:
            return "no_ai_key"
        if run.catalogue_id and not vector_ready:
            return "no_vectors"
        if not run.catalogue_id:
            return "no_catalogue"
        return None

    # ── Timeline logging (writes AiEstimatorStep rows) ────────────────────

    async def _log_thought(self, run: AiEstimatorRun, text: str) -> None:
        await self._log(run, "source", "thought", {"text": text})

    async def _log_observation(self, run: AiEstimatorRun, content: dict[str, Any]) -> None:
        await self._log(run, "source", "observation", content)

    async def _log_stage_complete(self, run: AiEstimatorRun, content: dict[str, Any]) -> None:
        await self._log(run, "grouping", "stage_complete", content)

    async def _log(self, run: AiEstimatorRun, stage: str, role: str, content: Any) -> None:
        from app.modules.ai_estimator.service import AiEstimatorService

        await AiEstimatorService(self.session)._log(run.id, stage, role, content)


# A number (with optional decimal comma/point) immediately followed by a square
# metre unit token (m2 / m^2 / m² / sq m, EN + RU "м2/м²"). Used to seed the
# floor area from a trailing quantity the v1 leading-only parser misses.
_AREA_M2_RE = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?:m|м)\s*(?:2|²|\^2)\b",
    re.IGNORECASE,
)


def _scan_trailing_area_m2(text: str) -> float | None:
    """Return the first "<number> m2 / м2" area in the text, or None."""
    if not text:
        return None
    match = _AREA_M2_RE.search(text)
    if not match:
        return None
    try:
        value = float(match.group("num").replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


def _custom_package(description: str, unit: str) -> WorkPackage:
    """Build a throwaway WorkPackage for a user-added custom work line."""
    return WorkPackage(
        key="custom",
        trade="other",
        default_on=False,
        stages=("finish",),
        probes=(description,),
        qty_formula="lump",
        unit=unit,
    )


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True
