# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Estimate Builder orchestrator service.

Drives the four-stage pipeline (Understand -> Group -> Match -> Assemble) over
a long-lived run row. The design rules are absolute:

* AI suggests, the human confirms. Nothing is auto-written to a BOQ; every
  stage ends in a human-confirm checkpoint enforced by the FSM.
* The LLM understands, groups, labels and REASONS over real candidates - it
  NEVER invents a unit rate or a code. Rates come only from the cost database
  via the verified grounded retrieval stack (``ranker_qdrant.rank`` and the
  resources matcher).
* Confidence is a real retrieval/model-derived float in [0, 1] or None - never
  a fabricated placeholder.
* Currencies are never blended; per-line FX rollup in the project base
  currency with per-currency subtotals.
* Graceful degradation: no AI key -> deterministic grouping + top-1 grounded
  match; no vectors -> lexical match (honest low scores); no catalogue for the
  currency -> honest "no rate" rather than an invented number.

The module reuses, never reimplements: ``ranker_qdrant.rank`` (grounded
candidates), ``match_cwicr_items`` (lexical fallback), the CWICR
``CostItem.components`` resource breakdown, the BOQ FX rollup math (mirrored
from ``match_elements.apply_to_boq``), and the core validation engine.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_estimator import benchmarks, schemas
from app.modules.ai_estimator import events as estimator_events
from app.modules.ai_estimator.models import (
    AiEstimatorGroup,
    AiEstimatorRun,
    AiEstimatorStep,
)
from app.modules.ai_estimator.repository import (
    AiEstimatorGroupRepository,
    AiEstimatorRunRepository,
    AiEstimatorStepRepository,
)
from app.modules.ai_estimator.taxonomy import classify_trade

logger = logging.getLogger(__name__)

# Confidence-band thresholds, exposed to the UI on the group list so the
# frontend never hardcodes them (matches the core match_service config).
CONFIDENCE_HIGH_THRESHOLD = 0.78
CONFIDENCE_MEDIUM_THRESHOLD = 0.62

# Pass-2 (unit/scale reconcile) demotion penalty. A candidate whose unit
# dimension is incompatible with the group's chosen-unit dimension keeps its
# real rate but has its score multiplied by this factor so the dimensionally
# correct candidate rises to top-1. It is a re-rank, never a drop: the demoted
# candidate stays in the override list for the human.
_UNIT_MISMATCH_PENALTY = 0.1

# Per-pass caps (a vector search over hundreds of groups blocks the request
# thread; the UI repeats the action to walk through the full set).
# DEFAULT_MATCH_GROUP_CAP is the per-match-call group cap: how many groups one
# match-all pass processes when the caller does not override ``max_groups``. It
# lives on the schema (the single source of truth - the request schema default,
# this service and the meta endpoint all read that one definition, zero
# duplication). _MAX_GROUPS_PER_MATCH is the hard ceiling a caller can never
# exceed even by passing a larger ``max_groups``.
DEFAULT_MATCH_GROUP_CAP = schemas.DEFAULT_MATCH_GROUP_CAP
_MAX_GROUPS_PER_MATCH = 500
_APPLY_BATCH_LIMIT = 1000

_Q2 = Decimal("0.01")
_Q4 = Decimal("0.0001")

# Default group-by keys when the user/AI suggests none.
_DEFAULT_GROUP_BY = ["category", "unit"]

# Stage titles for the stepper (English defaults; the UI translates).
_STAGE_TITLES: dict[str, str] = {
    "source": "Understand source",
    "grouping": "Group quantities",
    "matching": "Match rates",
    "assembly": "Review and apply",
}
_STAGE_ORDER = ("source", "grouping", "matching", "assembly")


class _SourceExtractionError(Exception):
    """Raised when a referenced source artifact is missing or yields nothing.

    Carries a human-readable ``reason`` that ``analyze`` stores on the run's
    ``failure_reason`` so the failure is honest, never a silent empty success.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── Money / quantity helpers (Decimal end-to-end, never round through float) ──


def _dec(value: Any, default: str = "0") -> Decimal:
    """Coerce a string/number to Decimal, never raising for junk input."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
    return d if d.is_finite() else Decimal(default)


def _quantity_for_unit(quantities: dict[str, float], unit: str) -> float:
    """Pick the canonical quantity matching a chosen unit (mirrors match-elements)."""
    return {
        "m3": quantities.get("volume_m3", 0.0),
        "m2": quantities.get("area_m2", 0.0),
        "m": quantities.get("length_m", 0.0),
        "kg": quantities.get("mass_kg", 0.0),
        "t": (quantities.get("mass_kg", 0.0) or 0.0) / 1000.0,
        "pcs": quantities.get("count", 0.0),
    }.get(unit, quantities.get("count", 0.0))


# Envelope source kind -> standardised WorkGroup source (design 3.1 / 4.1).
# CAD/BIM models are ``cad``; parsed files (BOQ rows, PDF/DWG takeoff, free
# text) are ``file``; site photos are ``photo``. The dialogue path tags
# ``dialogue`` directly in the intake composer.
_ENVELOPE_SOURCE_TO_WORKGROUP: dict[str, str] = {
    "bim": "cad",
    "dwg": "cad",
    "pdf": "file",
    "boq": "file",
    "text": "file",
    "image": "photo",
    "photo": "photo",
}


def _workgroup_source(envelope_source: Any) -> str:
    """Map an envelope ``source`` to the standardised WorkGroup source.

    Args:
        envelope_source: The ``source`` field of the representative envelope
            (``bim`` / ``dwg`` / ``pdf`` / ``boq`` / ``text`` / ``photo``).

    Returns:
        One of ``cad`` / ``file`` / ``photo``; an unknown / missing source
        defaults to ``file`` (a measured group never carries ``dialogue``).
    """
    return _ENVELOPE_SOURCE_TO_WORKGROUP.get(str(envelope_source or ""), "file")


def _pick_unit(quantities: dict[str, float]) -> str:
    """Auto-pick the most specific non-zero dimension (volume>area>length>...)."""
    for unit, key in (
        ("m3", "volume_m3"),
        ("m2", "area_m2"),
        ("m", "length_m"),
        ("kg", "mass_kg"),
        ("pcs", "count"),
    ):
        try:
            if float(quantities.get(key, 0.0) or 0.0) > 0:
                return unit
        except (TypeError, ValueError):
            continue
    return "pcs"


def _split_unit_multiplier(unit: str | None) -> tuple[Decimal, str]:
    """Peel a leading numeric multiplier off a catalogue unit ("100 m3")."""
    if not unit:
        return Decimal("1"), ""
    s = str(unit).strip()
    if not s:
        return Decimal("1"), s
    parts = s.split(None, 1)
    if len(parts) == 2:
        try:
            mult = Decimal(parts[0].replace(",", "."))
            if mult > 0:
                return mult, parts[1].strip()
        except (InvalidOperation, ValueError):
            pass
    return Decimal("1"), s


def _confidence_band(score: float | None) -> str:
    """Map a real score onto the high/medium/low/none band."""
    if score is None:
        return "none"
    if score >= CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if score >= CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


# ── Service ────────────────────────────────────────────────────────────────


class AiEstimatorService:
    """Stateless orchestrator. All DB state lives on the run/group/step rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repo = AiEstimatorRunRepository(session)
        self.group_repo = AiEstimatorGroupRepository(session)
        self.step_repo = AiEstimatorStepRepository(session)

    # ── Run lifecycle ─────────────────────────────────────────────────────

    async def create_run(self, spec: schemas.RunCreate, user_id: uuid.UUID) -> AiEstimatorRun:
        """Create a run row and record the source inputs (stage 1 is started
        explicitly by ``analyze`` so the wizard can attach more sources first).
        """
        source_inputs: dict[str, Any] = {
            "source": spec.source,
            "text_input": spec.text_input or "",
            "file_refs": list(spec.file_refs or []),
            "rows": list(spec.rows or []),
            "bim_model_ids": [str(m) for m in (spec.bim_model_ids or [])],
            "document_ids": [str(d) for d in (spec.document_ids or [])],
            "boq_ids": [str(b) for b in (spec.boq_ids or [])],
        }
        run = AiEstimatorRun(
            project_id=spec.project_id,
            user_id=user_id,
            name=spec.name,
            agent_name=spec.agent_name,
            status="draft",
            current_stage="source",
            source_inputs=source_inputs,
            catalogue_id=spec.catalogue_id,
            region=spec.region,
            currency=(spec.currency or "").upper() or None,
            construction_stage=spec.construction_stage,
            group_by=list(_DEFAULT_GROUP_BY),
        )
        run = await self.run_repo.create(run)
        estimator_events.emit_run_started(
            run_id=str(run.id),
            project_id=str(run.project_id),
            source=spec.source,
        )
        return run

    async def add_sources(self, run: AiEstimatorRun, spec: schemas.AddSourcesRequest) -> AiEstimatorRun:
        """Coalesce additional sources into a draft run before analysis."""
        if run.status not in ("draft", "analyzing"):
            raise HTTPException(status_code=409, detail="Sources can only be added before analysis.")
        si = dict(run.source_inputs or {})
        si["file_refs"] = list(si.get("file_refs") or []) + list(spec.file_refs or [])
        si["rows"] = list(si.get("rows") or []) + list(spec.rows or [])
        si["bim_model_ids"] = list(si.get("bim_model_ids") or []) + [str(m) for m in (spec.bim_model_ids or [])]
        si["document_ids"] = list(si.get("document_ids") or []) + [str(d) for d in (spec.document_ids or [])]
        si["boq_ids"] = list(si.get("boq_ids") or []) + [str(b) for b in (spec.boq_ids or [])]
        if spec.text_input:
            existing = si.get("text_input") or ""
            si["text_input"] = f"{existing}\n{spec.text_input}".strip()
        await self.run_repo.update_fields(run.id, source_inputs=si)
        refreshed = await self.run_repo.get_by_id(run.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    # ── Stage 1: source understanding ─────────────────────────────────────

    async def analyze(self, run: AiEstimatorRun, *, use_ai: bool) -> AiEstimatorRun:
        """Normalise sources to envelopes and (optionally) AI-classify them.

        Stores ``detected_source`` + ``suggested_config`` and parks the run at
        checkpoint #1 (status ``analyzing``). Stage 2 grouping runs when the
        user accepts the ``source`` checkpoint.
        """
        await self.run_repo.update_fields(run.id, status="analyzing", current_stage="source")
        await self._log(run.id, "source", "thought", {"text": "Reading and normalising the source."})

        try:
            envelopes = await self._collect_envelopes(run)
        except _SourceExtractionError as exc:
            # A referenced artifact does not exist or yields zero estimable
            # elements. Fail the run honestly with a clear reason rather than
            # parking an empty success at checkpoint #1.
            await self.run_repo.update_fields(
                run.id, status="failed", current_stage="source", failure_reason=exc.reason
            )
            await self._log(run.id, "source", "error", {"failure_reason": exc.reason})
            estimator_events.emit_run_failed(
                run_id=str(run.id), project_id=str(run.project_id), failure_reason=exc.reason
            )
            refreshed = await self.run_repo.get_by_id(run.id)
            assert refreshed is not None  # noqa: S101
            return refreshed

        await self.run_repo.update_fields(run.id, metadata_={**(run.metadata_ or {}), "envelopes": envelopes})

        detected, suggested, ai_provenance = await self._classify_source(run, envelopes, use_ai=use_ai)

        suggested.setdefault("group_by", list(run.group_by or _DEFAULT_GROUP_BY))
        if run.currency:
            suggested.setdefault("currency", run.currency)
        if run.region:
            suggested.setdefault("region", run.region)
        if run.catalogue_id:
            suggested.setdefault("catalogue_id", run.catalogue_id)

        fields: dict[str, Any] = {
            "detected_source": detected,
            "suggested_config": suggested,
        }
        fields.update(ai_provenance)
        await self.run_repo.update_fields(run.id, **fields)
        await self._log(
            run.id,
            "source",
            "stage_complete",
            {"detected": detected, "element_count": len(envelopes)},
        )
        estimator_events.emit_stage_completed(run_id=str(run.id), project_id=str(run.project_id), stage="source")
        refreshed = await self.run_repo.get_by_id(run.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    def _normalise_sources(self, source_inputs: dict[str, Any]) -> list[dict[str, Any]]:
        """Turn inline text + pre-parsed rows into serialised ElementEnvelope dicts.

        Covers the two source kinds that carry their data inline and need no DB:
        free text and pre-parsed rows (Excel / GAEB / PDF tables already parsed
        upstream into ``rows``). Each envelope is the source-agnostic
        intermediate the matcher consumes. DB-backed sources (BIM/CAD, takeoff,
        BOQ re-estimate, photos) are extracted by :meth:`_collect_envelopes` via
        the real ``extractors`` over the live tables - this method only handles
        the inline payload and is intentionally synchronous / DB-free.
        """
        envelopes: list[dict[str, Any]] = []
        rows = source_inputs.get("rows") or []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            desc = str(row.get("description") or row.get("name") or "").strip()
            if not desc:
                continue
            unit = str(row.get("unit") or "").strip()
            qty = row.get("qty", row.get("quantity"))
            quantities = self._quantities_from_row(unit, qty)
            envelopes.append(
                {
                    "id": str(row.get("id") or f"row_{idx}"),
                    "source": "boq",
                    "description": desc[:2000],
                    "unit_hint": unit or None,
                    "category": str(row.get("category") or "").strip(),
                    "quantities": quantities,
                    # Only promote a code that looks like a real catalogue code;
                    # never a synthetic source label (ifc_class poisoning guard).
                    "exact_code": (str(row.get("code")).strip() or None) if row.get("code") else None,
                }
            )

        text = str(source_inputs.get("text_input") or "").strip()
        if text:
            # Deterministic clause-aware parse: one envelope per scope line item
            # (split on newlines + list separators) with the leading
            # "<number> <unit>" read off each clause. Only numbers the user
            # actually wrote are read - never invented. The grouping pass
            # collapses duplicates.
            from app.modules.ai_estimator.extractors import parse_text_scope

            envelopes.extend(parse_text_scope(text))
        return envelopes

    async def _collect_envelopes(self, run: AiEstimatorRun) -> list[dict[str, Any]]:
        """Normalise every referenced source into one envelope list.

        Text + pre-parsed rows are normalised synchronously (no DB). Sources
        that reference an artifact already in the system - a BIM/CAD model,
        takeoff measurements, existing BOQ positions, site photos - are
        extracted via the real ``extractors`` over the live tables. A source
        that references a missing artifact, or yields zero estimable elements,
        raises :class:`_SourceExtractionError` so ``analyze`` fails the run with
        an honest reason rather than continuing with an empty list.
        """
        from app.modules.ai_estimator import extractors

        source_inputs = run.source_inputs or {}
        declared = str(source_inputs.get("source") or "text")

        # Text + pre-parsed rows: always normalised, no DB, never fail here.
        envelopes = self._normalise_sources(source_inputs)

        bim_ids = list(source_inputs.get("bim_model_ids") or [])
        document_ids = list(source_inputs.get("document_ids") or [])
        boq_ids = list(source_inputs.get("boq_ids") or [])
        file_refs = list(source_inputs.get("file_refs") or [])
        has_inline = bool(source_inputs.get("rows") or (source_inputs.get("text_input") or "").strip())

        # ── BIM / CAD (an existing converted model in the project) ──
        if declared == "bim" or bim_ids:
            res = await extractors.extract_bim(self.session, run.project_id, bim_ids)
            await self._log_extraction(run.id, "bim", res)
            if res.requested and not res.found:
                raise _SourceExtractionError("The selected BIM/CAD model was not found in this project.")
            if (declared == "bim" or bim_ids) and not res.envelopes:
                raise _SourceExtractionError(
                    "The BIM/CAD model has no convertible elements with quantities to estimate."
                )
            envelopes.extend(res.envelopes)

        # ── Takeoff (measured items from PDF + DWG takeoff) ──
        # Only when the source references measured artifacts, not when a DWG/PDF
        # was uploaded and parsed inline (those rows are already normalised).
        if declared == "takeoff" or (declared == "dwg" and not bim_ids and not has_inline):
            res = await extractors.extract_takeoff(self.session, run.project_id)
            await self._log_extraction(run.id, "takeoff", res)
            if not res.envelopes:
                raise _SourceExtractionError("No measured takeoff items were found for this project to estimate.")
            envelopes.extend(res.envelopes)

        # ── BOQ re-estimate (existing positions) ──
        if declared == "boq" or boq_ids:
            res = await extractors.extract_boq(self.session, run.project_id, boq_ids)
            await self._log_extraction(run.id, "boq", res)
            if res.requested and not res.found:
                raise _SourceExtractionError("The selected BOQ was not found in this project.")
            if (declared == "boq" or boq_ids) and not res.envelopes:
                raise _SourceExtractionError("The selected BOQ has no positions with a description to re-estimate.")
            envelopes.extend(res.envelopes)

        # ── Photo (presence signals from project photos) ──
        if declared == "photo":
            res = await extractors.extract_photos(self.session, run.project_id, file_refs)
            await self._log_extraction(run.id, "photo", res)
            if not res.found:
                raise _SourceExtractionError("No project photos were found to analyse for the estimate.")
            if not res.envelopes:
                raise _SourceExtractionError(
                    "The project photos did not yield any element suggestions to estimate "
                    "(no recognisable construction content)."
                )
            envelopes.extend(res.envelopes)

        # ── Documents: an attached document carries no measured quantities on
        # its own. Surface this honestly rather than fabricating an estimate
        # from a file we have not converted to elements.
        if declared == "documents" and document_ids and not envelopes:
            raise _SourceExtractionError(
                "Selected documents carry no measured elements to estimate. Run them through "
                "PDF/CAD takeoff or BIM conversion first, then estimate from that source."
            )

        if not envelopes:
            raise _SourceExtractionError("No estimable elements were found in the provided source(s).")
        return envelopes

    async def _log_extraction(self, run_id: uuid.UUID, source: str, res: Any) -> None:
        """Record an honest per-source extraction observation on the timeline."""
        content: dict[str, Any] = {
            "source": source,
            "requested": res.requested,
            "found": res.found,
            "scanned": res.scanned,
            "elements": len(res.envelopes),
        }
        if res.notes:
            content["notes"] = res.notes[:20]
        await self._log(run_id, "source", "observation", content)

    @staticmethod
    def _quantities_from_row(unit: str, qty: Any) -> dict[str, float]:
        """Map a row's (unit, qty) onto the canonical quantity dict."""
        try:
            q = float(qty)
        except (TypeError, ValueError):
            return {}
        if q <= 0:
            return {}
        u = (unit or "").strip().lower()
        key = {
            "m3": "volume_m3",
            "m2": "area_m2",
            "m": "length_m",
            "kg": "mass_kg",
        }.get(u, "count")
        return {key: q}

    async def _classify_source(
        self,
        run: AiEstimatorRun,
        envelopes: list[dict[str, Any]],
        *,
        use_ai: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Return (detected_source, suggested_config, ai_provenance fields).

        Deterministic baseline always runs. When a key is present and
        ``use_ai`` is set, an LLM pass refines the detection; on any failure
        (no key, undecryptable key, provider error) it degrades silently to the
        deterministic result - never a 500.
        """
        declared = str((run.source_inputs or {}).get("source") or "text")
        # Per-source element breakdown so the detected-source card is honest
        # about what was actually extracted (a mixed run reports each source).
        by_source: dict[str, int] = {}
        disciplines: list[str] = []
        for env in envelopes:
            s = str(env.get("source") or declared)
            by_source[s] = by_source.get(s, 0) + 1
            disc = env.get("discipline")
            if disc and str(disc) not in disciplines:
                disciplines.append(str(disc))
        # Inline sources (text / excel / gaeb / pdf-tables) keep the declared
        # type the user picked - the user knows their file better than the
        # internal envelope label ("excel" rows are tagged "boq" internally).
        # DB-backed sources report the source that contributed the most
        # elements so a mixed run is honest about what was actually extracted.
        db_backed = {"bim", "dwg", "photo"}
        if by_source and (set(by_source) & db_backed):
            detected_type = max(by_source, key=by_source.get)
        else:
            detected_type = declared
        breakdown = ", ".join(f"{n} {s}" for s, n in sorted(by_source.items(), key=lambda kv: -kv[1]))
        detected: dict[str, Any] = {
            "type": detected_type,
            "confidence": None,
            "disciplines": disciplines[:12],
            "by_source": by_source,
            "summary": (f"{len(envelopes)} estimable element(s)" + (f" ({breakdown})." if breakdown else ".")),
        }
        suggested: dict[str, Any] = {}
        provenance: dict[str, Any] = {}

        if not use_ai or not envelopes:
            return detected, suggested, provenance

        from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
        from app.modules.ai_estimator.prompts import (
            SOURCE_CLASSIFY_SYSTEM,
            build_source_classify_prompt,
        )

        settings = await AISettingsRepository(self.session).get_by_user_id(run.user_id)
        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            # No / undecryptable key: degrade. The progress + readiness
            # surfaces "no_ai_key"; the run still works deterministically.
            logger.info("ai_estimator analyze: degrading to deterministic (%s)", exc)
            await self._log(run.id, "source", "observation", {"degraded": "no_ai_key"})
            return detected, suggested, provenance

        digest = self._source_digest(envelopes)
        prompt = build_source_classify_prompt(
            digest=digest,
            hint_currency=run.currency or "",
            hint_region=run.region or "",
        )
        started = time.monotonic()
        try:
            raw, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SOURCE_CLASSIFY_SYSTEM,
                prompt=prompt,
                model=model_override,
            )
        except ValueError as exc:
            logger.info("ai_estimator analyze: AI call failed, degrading (%s)", exc)
            await self._log(run.id, "source", "observation", {"degraded": "llm_error", "message": str(exc)[:200]})
            return detected, suggested, provenance

        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            detected = {
                "type": str(parsed.get("source_type") or declared),
                "confidence": self._real_confidence(parsed.get("confidence")),
                "disciplines": list(parsed.get("disciplines") or []),
                "summary": str(parsed.get("summary") or detected["summary"])[:400],
            }
            suggested = {
                "region": str(parsed.get("recommended_region") or "").strip() or None,
                "currency": (str(parsed.get("recommended_currency") or "").strip().upper() or None),
                "group_by": list(parsed.get("recommended_group_by") or []) or list(_DEFAULT_GROUP_BY),
            }
            suggested = {k: v for k, v in suggested.items() if v is not None}
        provenance = self._ai_provenance_fields(
            run, provider, model_override, int(tokens or 0), int((time.monotonic() - started) * 1000)
        )
        await self._log(run.id, "source", "answer", {"detected": detected, "suggested": suggested})
        return detected, suggested, provenance

    @staticmethod
    def _source_digest(envelopes: list[dict[str, Any]], *, max_rows: int = 40) -> str:
        """Build a compact, fence-able digest of the source for the classifier."""
        lines: list[str] = [f"element_count={len(envelopes)}"]
        for env in envelopes[:max_rows]:
            unit = env.get("unit_hint") or ""
            cat = env.get("category") or ""
            lines.append(f"- [{cat}|{unit}] {str(env.get('description') or '')[:160]}")
        return "\n".join(lines)

    @staticmethod
    def _real_confidence(value: Any) -> float | None:
        """Coerce a model confidence to a real [0,1] float, else None."""
        try:
            c = float(value)
        except (TypeError, ValueError):
            return None
        if c < 0 or c > 1:
            return None
        return round(c, 4)

    @staticmethod
    def _ai_provenance_fields(
        run: AiEstimatorRun, provider: str, model: str | None, tokens: int, duration_ms: int
    ) -> dict[str, Any]:
        """Accumulate the run's provider/model/token/cost/duration rollup."""
        from app.core.ai.pricing import estimate_cost_usd

        cost = float(estimate_cost_usd(model or provider, tokens))
        return {
            "provider": provider,
            "model_used": model or provider,
            "total_tokens": int(run.total_tokens or 0) + tokens,
            "cost_usd_estimate": float(run.cost_usd_estimate or 0.0) + cost,
            "duration_ms": int(run.duration_ms or 0) + duration_ms,
        }

    # ── Stage confirm (the four checkpoints) ──────────────────────────────

    async def confirm_stage(
        self, run: AiEstimatorRun, spec: schemas.StageConfirmRequest, user_id: uuid.UUID
    ) -> AiEstimatorRun:
        """Accept a checkpoint, apply stage edits, and advance the FSM."""
        checkpoints = dict(run.checkpoints or {})
        checkpoints[spec.stage] = {"accepted_at": datetime.now(UTC).isoformat(), "by": str(user_id)}

        if spec.stage == "source":
            edits = spec.edits or {}
            config_fields: dict[str, Any] = {
                "checkpoints": checkpoints,
                "status": "grouping",
                "current_stage": "grouping",
            }
            sugg = dict(run.suggested_config or {})
            config_fields["catalogue_id"] = edits.get("catalogue_id", run.catalogue_id or sugg.get("catalogue_id"))
            config_fields["region"] = edits.get("region", run.region or sugg.get("region"))
            currency = edits.get("currency", run.currency or sugg.get("currency"))
            config_fields["currency"] = (currency or "").upper() or None if currency else None
            config_fields["group_by"] = (
                edits.get("group_by") or run.group_by or sugg.get("group_by") or _DEFAULT_GROUP_BY
            )
            cs = edits.get("construction_stage", run.construction_stage)
            config_fields["construction_stage"] = cs
            await self.run_repo.update_fields(run.id, **config_fields)
            refreshed = await self.run_repo.get_by_id(run.id)
            assert refreshed is not None  # noqa: S101
            # An intake-originated run already has the composed groups (the
            # intake composer wrote them BEFORE this checkpoint). Re-deriving
            # groups from envelopes here would wipe the composed board, so skip
            # grouping and keep the intake's groups (flagged on the run).
            if (refreshed.metadata_ or {}).get("intake_composed"):
                return refreshed
            # Run grouping now that the config is confirmed.
            return await self._build_groups(refreshed)

        if spec.stage == "grouping":
            await self.run_repo.update_fields(
                run.id, checkpoints=checkpoints, status="matching", current_stage="matching"
            )
            estimator_events.emit_stage_completed(run_id=str(run.id), project_id=str(run.project_id), stage="grouping")
        elif spec.stage == "matching":
            await self.run_repo.update_fields(
                run.id, checkpoints=checkpoints, status="review", current_stage="assembly"
            )
            estimator_events.emit_stage_completed(run_id=str(run.id), project_id=str(run.project_id), stage="matching")
        elif spec.stage == "assembly":
            # The assembly checkpoint is the precondition for apply; the write
            # itself happens on POST /apply.
            await self.run_repo.update_fields(run.id, checkpoints=checkpoints, current_stage="assembly")
            estimator_events.emit_stage_completed(run_id=str(run.id), project_id=str(run.project_id), stage="assembly")

        refreshed = await self.run_repo.get_by_id(run.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    # ── Stage 2: grouping ─────────────────────────────────────────────────

    async def _build_groups(self, run: AiEstimatorRun) -> AiEstimatorRun:
        """Bucket envelopes by signature, sum canonical quantities, persist groups.

        Deterministic grouping math (the AI never touches quantities); an
        optional AI refinement pass relabels groups when a key is present.
        """
        from app.modules.match_elements.signature import derive_group_key, normalize_signature

        envelopes = list((run.metadata_ or {}).get("envelopes") or [])
        group_by = list(run.group_by or _DEFAULT_GROUP_BY)

        # Drop existing groups so re-grouping replaces them wholesale.
        await self.group_repo.delete_for_run(run.id)

        buckets: dict[str, dict[str, Any]] = {}
        for env in envelopes:
            values = self._group_by_values(env, group_by)
            key = derive_group_key(group_by, values) or (env.get("description") or "ungrouped")[:200]
            # A free-text scope clause is an independently authored line item:
            # its ``group_hint`` keeps it as its own group so two clauses that
            # share a unit (and even a trade) are never silently merged. Other
            # sources (BIM/takeoff/BOQ) keep the homogeneous-signature grouping
            # that legitimately collapses duplicate elements.
            group_hint = env.get("group_hint")
            if group_hint:
                key = f"{key}|{group_hint}"
            bucket = buckets.setdefault(
                key,
                {
                    "envelopes": [],
                    "element_ids": [],
                    "quantities": {},
                    "values": values,
                },
            )
            bucket["envelopes"].append(env)
            bucket["element_ids"].append(str(env.get("id")))
            for qk, qv in (env.get("quantities") or {}).items():
                try:
                    bucket["quantities"][qk] = float(bucket["quantities"].get(qk, 0.0)) + float(qv)
                except (TypeError, ValueError):
                    continue

        groups: list[AiEstimatorGroup] = []
        for sort_order, (key, bucket) in enumerate(buckets.items()):
            quantities = {k: v for k, v in bucket["quantities"].items() if v}
            unit = _pick_unit(quantities)
            sample = bucket["envelopes"][0]
            desc = str(sample.get("description") or key)[:500]
            _label, sig = normalize_signature(group_by, bucket["values"])
            trade = classify_trade(desc, sample.get("category"), sample.get("ifc_class"))
            # The representative envelope the matcher consumes for this group.
            envelope = self._group_envelope(bucket["envelopes"], desc, unit, run)
            groups.append(
                AiEstimatorGroup(
                    run_id=run.id,
                    group_key=key,
                    signature=sig or None,
                    element_ids=bucket["element_ids"],
                    element_count=len(bucket["element_ids"]),
                    quantities=quantities,
                    envelope=envelope,
                    chosen_unit=unit,
                    description=desc,
                    trade=trade,
                    status="unmatched",
                    sort_order=sort_order,
                    # WorkGroup provenance (design 3.1 / 4.1): a measured group
                    # carries its origin source (file | cad | photo) uniformly,
                    # mapped from the envelope's own source kind.
                    metadata_={"source": _workgroup_source(sample.get("source"))},
                )
            )
        if groups:
            await self.group_repo.bulk_add(groups)
        await self._log(run.id, "grouping", "stage_complete", {"group_count": len(groups)})
        refreshed = await self.run_repo.get_by_id(run.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    @staticmethod
    def _group_by_values(env: dict[str, Any], group_by: list[str]) -> dict[str, Any]:
        """Pull the group-by attribute values from an envelope dict."""
        values: dict[str, Any] = {}
        for key in group_by:
            if key in env:
                values[key] = env.get(key)
            elif key == "unit":
                values[key] = env.get("unit_hint")
            else:
                values[key] = (
                    (env.get("properties") or {}).get(key) if isinstance(env.get("properties"), dict) else None
                )
        return values

    @staticmethod
    def _group_envelope(
        envelopes: list[dict[str, Any]], description: str, unit: str, run: AiEstimatorRun
    ) -> dict[str, Any]:
        """Build the serialised ElementEnvelope the matcher consumes per group.

        Carries through the v3 structured fields (``ifc_class`` hard filter,
        ``material_class`` soft boost, ``classifier_hint``) from a homogeneous
        group's sample so BIM/CAD-sourced groups keep the discriminating signal
        the grounded ranker relies on. These are only forwarded when every
        element in the group shares the same value, so a mixed group never
        inherits one element's hard filter (which would zero the others).
        """
        sample = envelopes[0]
        single = len(envelopes) == 1
        exact_code = sample.get("exact_code") if single else None

        def _shared(key: str) -> Any:
            """Return the common value of ``key`` across the group, else None."""
            first = sample.get(key)
            if not first:
                return None
            for env in envelopes:
                if env.get(key) != first:
                    return None
            return first

        # The matcher honours the source's own kind ("bim" carries an
        # ifc_class hard filter; text/boq do not). Fall back to "text" for
        # synthetic sources so the description drives the dense query.
        source = str(sample.get("source") or "text")
        env: dict[str, Any] = {
            "source": source if source in ("bim", "dwg", "pdf", "photo", "boq", "text", "image") else "text",
            "description": description[:2000],
            "category": str(sample.get("category") or ""),
            "unit_hint": unit or None,
            "exact_code": exact_code,
            "project_currency": (run.currency or "").upper(),
            "project_region": run.region or "",
            "construction_stage_hint": run.construction_stage,
        }
        ifc_class = _shared("ifc_class")
        if ifc_class:
            env["ifc_class"] = str(ifc_class)
        material_class = _shared("material_class")
        if material_class:
            env["material_class"] = str(material_class)
        hint = sample.get("classifier_hint") if single else None
        if isinstance(hint, dict) and hint:
            env["classifier_hint"] = {k: str(v) for k, v in hint.items()}
        return env

    # ── Stage 3: matching ─────────────────────────────────────────────────

    async def run_matching(self, run: AiEstimatorRun, spec: schemas.RunMatchRequest) -> None:
        """Ground a rate per group via the verified retrieval stack.

        The deterministic path (always available) calls ``rank()`` per group
        and takes the honest top candidate. When a key is present and
        ``use_agent`` is set, the user-selected agent reasons over the
        candidates first; its pick is resolved back to a real stored candidate
        (the agent can only choose ids the tools returned). No rate is ever
        fabricated; groups with no grounded rate come back ``needs_human``.

        This orchestrates the three named mapping passes per group (semantic,
        unit/scale reconcile, rate sanity) via :meth:`_map_group`; the heavy
        retrieval imports live in :meth:`_pass_semantic`.
        """
        # Bind the catalogue the user picked at stage 1 to the project's match
        # settings, because ``rank()`` resolves the catalogue from
        # ``MatchProjectSettings.cost_database_id`` (not from the request). The
        # ai-estimator stage-1 picker stores the choice on the run; without this
        # hop the matcher would search ``no_catalog_selected`` and every group
        # would come back ``needs_human`` even though the user chose a catalogue.
        # We only ever propagate the user's explicit choice - never auto-guess.
        await self._bind_run_catalogue(run)

        groups, eligible_total = await self._select_groups_for_match(run.id, spec)
        remaining = max(eligible_total - len(groups), 0)
        if remaining:
            # Honest cap disclosure: a match-all pass over more groups than the
            # cap processes only the first N (largest by element count); the
            # caller (the UI's "match more" action) repeats the call to walk the
            # remainder. Never a silent truncation.
            await self._log(
                run.id,
                "matching",
                "thought",
                {
                    "text": (
                        f"Matching {len(groups)} of {eligible_total} group(s) this pass; "
                        f"{remaining} remaining - run match again to continue."
                    ),
                    "processed": len(groups),
                    "eligible_total": eligible_total,
                    "remaining": remaining,
                },
            )
        else:
            await self._log(run.id, "matching", "thought", {"text": f"Matching {len(groups)} group(s)."})

        # Resolve the agent LLM once (best-effort). When absent, the whole pass
        # is deterministic.
        agent_runner = None
        if spec.use_agent:
            agent_runner = await self._build_agent_runner(run)

        for grp in groups:
            await self._map_group(run, grp, spec, agent_runner)

        await self.run_repo.update_fields(run.id, status="matching", current_stage="matching")
        # Honest cap disclosure on the terminal step too: how many groups this
        # pass processed and how many remain (0 when the whole eligible set was
        # covered). A non-zero ``remaining`` tells the UI to offer "match more".
        await self._log(
            run.id,
            "matching",
            "stage_complete",
            {"matched": len(groups), "eligible_total": eligible_total, "remaining": remaining},
        )

    # ── Multi-pass mapping (design 4.3): semantic -> unit/scale -> rate sanity ──

    async def _map_group(
        self,
        run: AiEstimatorRun,
        grp: AiEstimatorGroup,
        spec: schemas.RunMatchRequest,
        agent_runner: dict[str, Any] | None,
    ) -> None:
        """Map one group's rate through the three named, observable passes.

        The pipeline is explicit and logged so the founder's "in several passes"
        is literal: pass 1 retrieves real candidates from the cost DB, pass 2
        reconciles their unit/scale against the group dimension, pass 3 sanity
        checks the surviving rates against a per-run benchmark band. No pass ever
        invents a rate; passes 2 and 3 only re-rank, rescale or flag the real
        candidates pass 1 retrieved. Each pass writes a structured trace entry
        (kept/dropped/notes) and an observation step onto the run timeline, and
        the assembled trace is persisted on the group ``metadata_.mapping_trace``.

        Args:
            run: The owning run (carries the bound catalogue + project context).
            grp: The group being mapped.
            spec: The match request (top_k / reranker / agent flags).
            agent_runner: The resolved agent bundle, or ``None`` when no AI key
                is present (the whole pipeline then stays deterministic).
        """
        passes: list[dict[str, Any]] = []

        candidates = await self._pass_semantic(run, grp, spec, passes)
        if candidates:
            self._reconcile_units(grp, candidates, passes)
            outlier_idx = self._rate_sanity(grp, candidates, passes)
        else:
            outlier_idx = set()

        # The chosen top-1 is the highest-scoring candidate that is NOT a flagged
        # outlier; only when every candidate is an outlier do we keep the highest
        # score (and pass 3 has already marked the group's reason in the trace).
        chosen_idx = self._first_non_outlier(candidates, outlier_idx)

        # The agent (when present) reasons over the survivors of pass 3 - it can
        # only pick an id the tools returned, recorded as final_method=llm.
        agent_method = None
        if candidates and agent_runner is not None:
            agent_idx, agent_method = await self._agent_pick(run, grp, candidates, agent_runner)
            if agent_method == "llm":
                chosen_idx = agent_idx

        final_method = agent_method or ("vector" if candidates else "manual")
        all_outliers = bool(candidates) and len(outlier_idx) == len(candidates)
        trace: dict[str, Any] = {"passes": passes, "final_method": final_method}
        if all_outliers:
            trace["needs_human_reason"] = "every candidate rate is a benchmark-band outlier"

        await self._apply_match_result(
            grp,
            candidates,
            chosen_idx,
            agent_method,
            mapping_trace=trace,
            force_needs_human=all_outliers,
            outlier_idx=outlier_idx,
        )

    async def _pass_semantic(
        self,
        run: AiEstimatorRun,
        grp: AiEstimatorGroup,
        spec: schemas.RunMatchRequest,
        passes: list[dict[str, Any]],
    ) -> list[Any]:
        """Pass 1 - semantic candidates: grounded vector rank + cost-DB enrich.

        Builds the group's :class:`ElementEnvelope`, calls the verified grounded
        ranker for the top-K real candidates, then backfills the real stored
        rate / currency / unit / components from the SQL cost table. This is the
        existing single-shot behaviour, now explicitly labelled and logged as
        pass 1. It never fabricates a candidate; a rank failure degrades this
        group to an empty candidate list (honest ``needs_human`` downstream).

        Args:
            run: The owning run.
            grp: The group being mapped.
            spec: The match request (top_k / reranker).
            passes: The accumulating trace list this pass appends to.

        Returns:
            The retrieved, cost-DB-enriched candidate list (possibly empty).
        """
        from app.core.match_service.envelope import ElementEnvelope, MatchRequest
        from app.core.match_service.ranker_qdrant import rank

        env_data = dict(grp.envelope or {})
        try:
            envelope = ElementEnvelope(
                source=env_data.get("source", "text"),
                description=env_data.get("description", grp.description or grp.group_key),
                category=env_data.get("category", ""),
                unit_hint=env_data.get("unit_hint"),
                exact_code=env_data.get("exact_code"),
                # v3 structured fields carried from BIM/CAD sources so the
                # grounded ranker's hard filters / soft boosts fire.
                ifc_class=env_data.get("ifc_class"),
                material_class=env_data.get("material_class"),
                classifier_hint=env_data.get("classifier_hint"),
                project_currency=env_data.get("project_currency", ""),
                project_region=env_data.get("project_region", ""),
                construction_stage_hint=env_data.get("construction_stage_hint"),
            )
            resp = await rank(
                MatchRequest(
                    envelope=envelope,
                    project_id=run.project_id,
                    top_k=spec.top_k,
                    use_reranker=spec.use_reranker,
                ),
                db=self.session,
            )
            candidates = list(resp.candidates)
            # The Qdrant payload carries classification only; the priced CWICR
            # snapshot (parquet) is optional in some installs, so the ranker can
            # return a grounded code with unit_rate 0 when the parquet is absent.
            # Backfill the REAL stored rate / currency / unit / resource
            # components from the SQL cost table for the exact grounded code +
            # bound catalogue. This reads the real stored rate, never fabricates.
            await self._enrich_candidates_from_costdb(candidates, run.catalogue_id)
        except Exception as exc:  # noqa: BLE001 - degrade per group, never crash the pass
            logger.warning("ai_estimator match: group %s rank failed: %s", grp.group_key, exc)
            candidates = []

        notes = (
            f"{len(candidates)} grounded candidate(s) retrieved" if candidates else "no grounded candidate retrieved"
        )
        passes.append({"pass": "semantic", "kept": len(candidates), "dropped": 0, "notes": notes, "benchmark": None})
        await self._log(
            run.id,
            "matching",
            "observation",
            {"pass": "semantic", "group": grp.group_key, "kept": len(candidates), "notes": notes},
        )
        return candidates

    def _reconcile_units(self, grp: AiEstimatorGroup, candidates: list[Any], passes: list[dict[str, Any]]) -> None:
        """Pass 2 - unit/scale reconcile: rescale to per-base-unit, demote misfits.

        For each candidate the catalogue unit's leading numeric multiplier is
        peeled (``"100 CY"`` -> ``(100, "CY")``) and the base unit mapped to a
        dimension bucket (Area / Volume / Linear / Mass / Count, reusing the
        :func:`query_builder.unit_type_for` vocabulary). A candidate whose
        dimension is incompatible with the group's chosen-unit dimension (for
        example an ``m3`` rate for an ``m2`` tiling group) is DEMOTED, not
        dropped: its ``score`` is multiplied by a penalty so the dimensionally
        correct candidate rises to top-1, while the real rate stays in the
        override list for the human. The per-base-unit rate is already computed
        by :meth:`_candidate_unit_rate` at apply time; this pass only re-ranks.
        Candidates are re-sorted by the adjusted score (stable, highest first).

        Args:
            grp: The group being mapped (carries ``chosen_unit``).
            candidates: The pass-1 candidate list, mutated in place (scores and
                order change; rates are untouched).
            passes: The accumulating trace list this pass appends to.
        """
        # Warm the match_service package before importing query_builder: the
        # package __init__ eagerly imports ranker_qdrant, which imports
        # build_search_plan back from query_builder. Importing query_builder
        # first (cold) would hit that as a partial-init cycle. Production always
        # loads the match stack before matching, so this only matters when this
        # pass is the first match_service consumer (e.g. an isolated unit test).
        import app.core.match_service  # noqa: F401
        from app.modules.costs.query_builder import unit_type_for

        group_dim = unit_type_for(grp.chosen_unit)
        demoted = 0
        for cand in candidates:
            _mult, base_unit = _split_unit_multiplier(getattr(cand, "unit", "") or "")
            cand_dim = unit_type_for(base_unit)
            # Only demote on a genuine dimension MISMATCH: both sides known and
            # different. An unknown dimension on either side (lump sum, unmapped
            # unit) is never penalised - we never guess a dimension we cannot read.
            if group_dim and cand_dim and group_dim != cand_dim:
                try:
                    cand.score = float(getattr(cand, "score", 0.0) or 0.0) * _UNIT_MISMATCH_PENALTY
                except (TypeError, ValueError):
                    cand.score = 0.0
                demoted += 1
        # Stable sort by adjusted score so a demoted candidate sinks below every
        # dimensionally-correct one while equal-score ties keep their rank-1 order.
        candidates.sort(key=lambda c: float(getattr(c, "score", 0.0) or 0.0), reverse=True)

        notes = (
            f"{demoted} dimensionally-incompatible candidate(s) demoted vs group unit {grp.chosen_unit or '?'}"
            if demoted
            else f"all candidate units compatible with group unit {grp.chosen_unit or '?'}"
        )
        passes.append(
            {"pass": "unit_scale", "kept": len(candidates), "dropped": demoted, "notes": notes, "benchmark": None}
        )

    def _rate_sanity(self, grp: AiEstimatorGroup, candidates: list[Any], passes: list[dict[str, Any]]) -> set[int]:
        """Pass 3 - rate sanity: flag benchmark-band outliers, cap their confidence.

        Computes the per-run median per-base-unit rate across the surviving
        candidates, then flags any candidate more than the ``(trade, unit)`` band
        factor away from that median (see :mod:`benchmarks`). A flagged candidate
        is NOT dropped: its serialised ``confidence_band`` is capped at ``low``
        and an ``outlier`` annotation is recorded on it, so the real DB rate stays
        available for human override while the dimensionally- and price-plausible
        candidate is preferred for the top-1. This keeps "rates only from the DB":
        it is a sanity flag, not a price book.

        Args:
            grp: The group being mapped (provides trade + chosen unit).
            candidates: The pass-2 candidate list, mutated in place (flagged
                candidates get a capped band + outlier marker; rates untouched).
            passes: The accumulating trace list this pass appends to.

        Returns:
            The set of candidate indices flagged as outliers (empty when none).
        """
        rates = [float(_dec(self._candidate_unit_rate(c))) for c in candidates]
        trade = grp.trade or "other"
        unit = grp.chosen_unit or "pcs"
        band_low, band_high, factor = benchmarks.evaluate_band(trade, unit, rates)
        median_rate = benchmarks.candidate_median(rates)

        outliers: set[int] = set()
        for idx, (cand, rate) in enumerate(zip(candidates, rates, strict=False)):
            if benchmarks.is_outlier(rate, median_rate, factor):
                outliers.add(idx)
                # Cap the flagged candidate at the LOW band so the override UI
                # reads "low" for a suspect rate. ``confidence_band`` is a declared
                # field (safe to reassign); the rate itself is never altered. The
                # per-candidate ``rate_outlier`` marker is threaded by index into
                # the serialised candidate dicts (a MatchCandidate forbids new
                # attributes), so we never mutate an undeclared field here.
                cand.confidence_band = "low"

        benchmark_block = {
            "trade": trade,
            "unit": unit,
            "band_low": round(band_low, 4) if band_low is not None else None,
            "band_high": round(band_high, 4) if band_high is not None else None,
            "outliers": len(outliers),
        }
        notes = (
            f"{len(outliers)} rate outlier(s) flagged against median band"
            if outliers
            else "all candidate rates within the benchmark band"
        )
        passes.append(
            {"pass": "rate_sanity", "kept": len(candidates), "dropped": 0, "notes": notes, "benchmark": benchmark_block}
        )
        return outliers

    @staticmethod
    def _first_non_outlier(candidates: list[Any], outlier_idx: set[int]) -> int:
        """Index of the highest-scoring non-outlier candidate (0 when all flagged).

        Candidates are already ordered best-first by passes 1-2. The chosen top-1
        is the first that is not a rate-sanity outlier; if every candidate is an
        outlier (or the list is empty) we fall back to index 0 so a real - if
        suspect - rate is still surfaced for human review, never an invented one.
        """
        for idx in range(len(candidates)):
            if idx not in outlier_idx:
                return idx
        return 0

    async def _bind_run_catalogue(self, run: AiEstimatorRun) -> None:
        """Propagate the run's stage-1 catalogue choice to project match settings.

        ``rank()`` binds the catalogue from ``MatchProjectSettings.cost_database_id``.
        The ai-estimator stage-1 picker stores the user's choice on the run as
        ``catalogue_id``; this writes it onto the project's match settings so the
        actual search targets the catalogue the user selected. Only the explicit
        user choice is propagated - we never auto-pick a catalogue the user did
        not choose (that would be a silent guess about which cost data to use).
        """
        catalogue_id = (run.catalogue_id or "").strip()
        if not catalogue_id:
            return
        try:
            from app.modules.projects.service import get_or_create_match_settings

            settings = await get_or_create_match_settings(self.session, run.project_id)
            if (settings.cost_database_id or "") != catalogue_id:
                settings.cost_database_id = catalogue_id
                self.session.add(settings)
                await self.session.flush()
                await self._log(
                    run.id,
                    "matching",
                    "observation",
                    {"catalogue_bound": catalogue_id},
                )
        except Exception as exc:  # noqa: BLE001 - never crash the match pass over a binding hiccup
            logger.warning("ai_estimator: catalogue bind failed for run %s: %s", run.id, exc)

    async def _select_groups_for_match(
        self, run_id: uuid.UUID, spec: schemas.RunMatchRequest
    ) -> tuple[list[AiEstimatorGroup], int]:
        """Choose which groups this pass matches (explicit ids or N largest).

        Returns ``(selected, eligible_total)`` where ``eligible_total`` is how
        many groups were eligible for matching before the per-pass cap. The
        caller discloses ``eligible_total - len(selected)`` as the honest
        "remaining" count so a capped match-all pass never silently truncates.
        """
        if spec.group_ids:
            wanted = {gid for gid in spec.group_ids}
            groups = [g for g in await self.group_repo.list_for_run(run_id) if g.id in wanted]
            return groups, len(groups)
        # N largest NOT-YET-ATTEMPTED groups by element count. After a match pass
        # a group leaves ``unmatched`` for ``suggested`` (a grounded candidate
        # was found) or ``needs_human`` (the matcher ran and found none) - either
        # way it has been attempted. Selecting only the never-attempted
        # (``unmatched`` / ``tbd``) groups means a capped match-all pass the UI
        # repeats walks forward through the remainder instead of re-running the
        # same N (or looping forever on the un-matchable ones). An on-demand
        # re-match of an already-attempted group goes through the explicit
        # ``group_ids`` path (rematch endpoint) above.
        candidates = await self.group_repo.list_for_run(run_id, statuses=["unmatched", "tbd"])
        candidates.sort(key=lambda g: g.element_count, reverse=True)
        cap = min(int(spec.max_groups or DEFAULT_MATCH_GROUP_CAP), _MAX_GROUPS_PER_MATCH)
        return candidates[:cap], len(candidates)

    async def _enrich_candidates_from_costdb(self, candidates: list[Any], catalogue_id: str | None) -> None:
        """Backfill real stored rate / currency / unit / components per candidate.

        The grounded ranker resolves the CWICR classification code via vector
        search; the price for that code lives in the SQL ``oe_costs_item`` table
        keyed by ``(code, region)``. When the optional priced parquet snapshot
        is not installed the ranker returns the code with ``unit_rate == 0`` -
        so we look the code up in the cost table for the bound catalogue and
        attach the REAL stored rate. This is the exact same priced row the cost
        browser shows; nothing is invented. A candidate whose code is not in the
        cost table is left untouched (honest zero / needs_human downstream).
        """
        region = (catalogue_id or "").strip()
        if not region or not candidates:
            return
        from sqlalchemy import select

        from app.modules.costs.models import CostItem

        codes = [str(getattr(c, "code", "") or "") for c in candidates if getattr(c, "code", None)]
        if not codes:
            return
        rows = (
            (
                await self.session.execute(
                    select(CostItem)
                    .where(CostItem.region == region)
                    .where(CostItem.code.in_(codes))
                    .where(CostItem.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        by_code = {str(r.code): r for r in rows}
        for cand in candidates:
            item = by_code.get(str(getattr(cand, "code", "") or ""))
            if item is None:
                continue
            try:
                real_rate = float(_dec(item.rate))
            except Exception:  # noqa: BLE001
                real_rate = 0.0
            # Only overwrite when the ranker did not already carry a positive
            # rate (the parquet path, when present, is authoritative).
            if real_rate > 0 and not float(getattr(cand, "unit_rate", 0.0) or 0.0):
                cand.unit_rate = real_rate
                if item.currency:
                    cand.currency = item.currency
                if item.unit:
                    cand.unit = item.unit
            # Point the candidate id at the real CostItem UUID so the resource
            # breakdown (keyed by CostItem.id) resolves the stored components.
            cand.id = str(item.id)

    async def _apply_match_result(
        self,
        grp: AiEstimatorGroup,
        candidates: list[Any],
        chosen_idx: int,
        agent_method: str | None,
        *,
        mapping_trace: dict[str, Any] | None = None,
        force_needs_human: bool = False,
        outlier_idx: set[int] | None = None,
    ) -> None:
        """Persist a group's match outcome from real candidates (never invents).

        Args:
            grp: The group whose match result is being written.
            candidates: The pass-3 surviving candidate list (best-first).
            chosen_idx: Index of the human-preferred top-1 (first non-outlier).
            agent_method: ``"llm"`` when an agent reasoned the pick, else ``None``.
            mapping_trace: The multi-pass trace (design 3.3) written to
                ``metadata_.mapping_trace`` so the run timeline + GroupDetail can
                show "why this rate". ``None`` leaves any prior trace untouched.
            force_needs_human: When every candidate is a rate-sanity outlier, the
                group is parked ``needs_human`` and the chosen rate's confidence
                is capped at the LOW band - the real rate is still surfaced, never
                dropped, and never auto-confirmed.
            outlier_idx: Indices of candidates the rate-sanity pass flagged, so
                each serialised candidate carries a ``rate_outlier`` marker for
                the override UI without mutating the candidate object.
        """
        flagged = outlier_idx or set()
        # Serialise the top-K candidates for the override UI (grounded only).
        cand_dicts = [self._candidate_out(c, rate_outlier=idx in flagged) for idx, c in enumerate(candidates)]
        if not candidates:
            empty_fields: dict[str, Any] = dict(
                candidates=[],
                status="needs_human",
                match_method=None,
                chosen_code=None,
                candidate_id=None,
                unit_rate=None,
                currency=None,
                score=None,
                confidence=None,
                confidence_band="none",
                resources=[],
            )
            if mapping_trace is not None:
                empty_fields["metadata_"] = {**dict(grp.metadata_ or {}), "mapping_trace": mapping_trace}
            await self.group_repo.update_fields(grp.id, **empty_fields)
            return

        chosen_idx = max(0, min(chosen_idx, len(candidates) - 1))
        top = candidates[chosen_idx]
        score = float(getattr(top, "score", 0.0) or 0.0)
        currency = getattr(top, "currency", "") or ""
        env_currency = (grp.envelope or {}).get("project_currency") or ""
        # Currency hard-honesty: if the project has a currency and the rate's
        # currency differs, flag for human rather than book a wrong-currency
        # number (never-blend). rank() already hard-filters, this is belt+braces.
        currency_ok = (not env_currency) or (not currency) or currency.upper() == env_currency.upper()
        resources = await self._resource_breakdown(getattr(top, "id", None))

        confidence = round(score, 4) if score > 0 else None
        band = _confidence_band(confidence)
        # The grounded ranker is the vector path; the agent records "llm" when
        # it reasoned its pick. ``candidates`` is non-empty here by guard above.
        method = agent_method or "vector"
        status = "needs_human" if not currency_ok else "suggested"

        # Pass 3 sanity: when every candidate is a benchmark-band outlier the
        # chosen (still real) rate is suspect, so cap its band at LOW and park the
        # group needs_human for review. The rate is surfaced, never dropped or
        # auto-confirmed - the human decides.
        if force_needs_human:
            band = "low"
            status = "needs_human"

        # Persist the chosen candidate's standard classification (MasterFormat /
        # DIN / NRM) the grounded CWICR row carries, so the position written to
        # the BOQ is classified by the real catalogue code rather than blank.
        chosen_classification = getattr(top, "classification", None)
        meta = dict(grp.metadata_ or {})
        if isinstance(chosen_classification, dict) and chosen_classification:
            meta["classification"] = {k: str(v) for k, v in chosen_classification.items() if v}
        else:
            meta.pop("classification", None)
        if mapping_trace is not None:
            meta["mapping_trace"] = mapping_trace

        await self.group_repo.update_fields(
            grp.id,
            candidates=cand_dicts,
            candidate_id=getattr(top, "id", None),
            chosen_code=getattr(top, "code", None),
            unit_rate=self._candidate_unit_rate(top),
            currency=currency or None,
            score=confidence,
            confidence=confidence,
            confidence_band=band,
            match_method=method,
            resources=resources,
            status=status,
            metadata_=meta,
        )

    @staticmethod
    def _candidate_unit_rate(candidate: Any) -> str | None:
        """Per-base-unit rate as a Decimal-string, stripping any unit multiplier.

        Returns ``None`` when there is no real rate (a non-positive value), so a
        grounded-but-unpriced code stores a NULL rate rather than ``"0"``. A
        ``"0"`` would surface in the UI as a fabricated $0.00; null reads as the
        honest "matched, no price" state and the apply/preview path coerces it
        back to ``Decimal("0")`` for the rollup via :func:`_dec`.
        """
        raw_rate = _dec(getattr(candidate, "unit_rate", 0))
        mult, _unit = _split_unit_multiplier(getattr(candidate, "unit", "") or "")
        rate = (raw_rate / mult) if mult > 0 else raw_rate
        return format(rate, "f") if rate > 0 else None

    @staticmethod
    def _candidate_out(candidate: Any, *, rate_outlier: bool = False) -> dict[str, Any]:
        """Serialise a MatchCandidate for storage / the override UI.

        ``rate_outlier`` is the pass-3 rate-sanity flag (see :meth:`_rate_sanity`)
        so the override UI can badge a candidate whose rate sits outside the
        benchmark band. It is only ``True`` on a candidate the sanity pass flagged;
        the rate itself is never altered.
        """
        raw_rate = _dec(getattr(candidate, "unit_rate", 0))
        return {
            "candidate_id": getattr(candidate, "id", None),
            "code": getattr(candidate, "code", "") or "",
            "description": (getattr(candidate, "description", "") or "")[:300],
            "unit": getattr(candidate, "unit", "") or "",
            # Null, not "0", when the grounded code is unpriced - the override UI
            # shows "no price" rather than a fabricated $0.00.
            "unit_rate": format(raw_rate, "f") if raw_rate > 0 else None,
            "currency": getattr(candidate, "currency", "") or "",
            "score": round(float(getattr(candidate, "score", 0.0) or 0.0), 4),
            "confidence_band": getattr(candidate, "confidence_band", "low"),
            "rate_outlier": bool(rate_outlier),
        }

    @staticmethod
    def _classification_for_group(grp: AiEstimatorGroup) -> dict[str, str]:
        """Standard classification (MasterFormat/DIN/NRM) the chosen rate carries.

        The grounded candidate's classification (read from the CWICR Qdrant
        snapshot - the only place a snapshot-only install holds the MasterFormat
        division) is stored on the group at match time under
        ``metadata_['classification']``. We propagate it onto the position so the
        MasterFormat / DIN validation rules see the real code the matched
        catalogue row provides - never a fabricated code. Returns an empty dict
        when the group has no grounded candidate (honest: an un-matched line
        carries no classification).
        """
        meta = grp.metadata_ if isinstance(grp.metadata_, dict) else {}
        cls = meta.get("classification")
        if not isinstance(cls, dict):
            return {}
        return {k: str(v) for k, v in cls.items() if v and k in ("din276", "nrm", "masterformat", "uniformat", "csi")}

    async def _resource_breakdown(self, candidate_id: str | None) -> list[dict[str, Any]]:
        """Read a candidate's CWICR resource components from the cost DB."""
        if not candidate_id:
            return []
        from app.modules.costs.models import CostItem

        try:
            item = await self.session.get(CostItem, uuid.UUID(str(candidate_id)))
        except (ValueError, TypeError):
            return []
        if item is None or not isinstance(item.components, list):
            return []
        out: list[dict[str, Any]] = []
        for comp in item.components:
            if not isinstance(comp, dict):
                continue
            out.append(
                {
                    "name": str(comp.get("description") or comp.get("name") or comp.get("code") or ""),
                    "code": str(comp.get("code") or ""),
                    "unit": str(comp.get("unit") or ""),
                    "factor": float(comp.get("factor", 1.0) or 1.0),
                    "unit_rate": format(_dec(comp.get("unit_rate") or comp.get("rate")), "f"),
                    "type": str(comp.get("type") or "other"),
                }
            )
        return out

    async def _build_agent_runner(self, run: AiEstimatorRun) -> Any:
        """Build the ReAct runner for stage-3 reasoning, or None to degrade.

        Honours the user-selected agent (``run.agent_name``) when set, else the
        module's grounded precise-match agent. Returns None on any key/agent
        resolution failure so matching degrades to the deterministic top-1.
        """
        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
        from app.modules.ai_agents.base import AgentRunner, get_agent
        from app.modules.ai_agents.llm import CallAILLM
        from app.modules.ai_estimator.tools import PRECISE_MATCH_AGENT

        agent_name = run.agent_name or PRECISE_MATCH_AGENT
        agent = get_agent(agent_name) or get_agent(PRECISE_MATCH_AGENT)
        if agent is None:
            return None
        settings = await AISettingsRepository(self.session).get_by_user_id(run.user_id)
        try:
            provider, api_key, model = resolve_provider_key_model(settings)
        except ValueError as exc:
            logger.info("ai_estimator match: no usable AI key, deterministic path (%s)", exc)
            await self._log(run.id, "matching", "observation", {"degraded": "no_ai_key"})
            return None
        bridge = CallAILLM(provider=provider, api_key=api_key, model=model)
        return {"agent": agent, "runner": AgentRunner(bridge)}

    async def _agent_pick(
        self, run: AiEstimatorRun, grp: AiEstimatorGroup, candidates: list[Any], agent_bundle: dict[str, Any]
    ) -> tuple[int, str | None]:
        """Let the agent reason over candidates and return (chosen_idx, method).

        The agent can only pick a candidate id the tools returned; its final
        prose is scanned for one of the real candidate ids. Falls back to the
        deterministic top-1 (index 0) when the agent flags-for-human or its
        answer references no real id - never invents.
        """
        from app.modules.ai_estimator.prompts import build_match_reasoning_input

        agent = agent_bundle["agent"]
        runner = agent_bundle["runner"]
        quantities_summary = ", ".join(f"{k}={v}" for k, v in (grp.quantities or {}).items()) or "none"
        user_input = build_match_reasoning_input(
            description=grp.description or grp.group_key,
            unit=grp.chosen_unit or "",
            quantities_summary=quantities_summary,
        )
        try:
            result = await runner.run(
                agent,
                user_input,
                context={"project_id": str(run.project_id), "region": run.region or ""},
            )
        except Exception as exc:  # noqa: BLE001 - degrade to deterministic top-1
            logger.warning("ai_estimator agent pick failed for %s: %s", grp.group_key, exc)
            await self._log(run.id, "matching", "observation", {"agent_error": str(exc)[:200]})
            return 0, "vector"

        # Persist the agent's reasoning steps into this run's timeline.
        for step in result.steps:
            await self._log(run.id, "matching", step.role, step.content, token_count=step.token_count)

        # Accumulate the agent's token spend onto the run.
        prov = self._ai_provenance_fields(run, run.provider or "", run.model_used, int(result.total_tokens or 0), 0)
        await self.run_repo.update_fields(run.id, **prov)

        answer = (result.final_output or "").strip()
        # Find a real candidate id the agent referenced. Only ids that exist in
        # the returned candidates count - the agent cannot invent one.
        for idx, cand in enumerate(candidates):
            cid = getattr(cand, "id", None)
            if cid and str(cid) in answer:
                return idx, "llm"
        # No real id referenced (flagged for human or vague answer): keep the
        # honest deterministic top-1.
        return 0, "vector"

    # ── Group edit / override / confirm ───────────────────────────────────

    async def update_group(self, grp: AiEstimatorGroup, spec: schemas.GroupUpdate) -> AiEstimatorGroup:
        """Edit a group's stage-2 fields, or override its stage-3 candidate.

        A candidate override MUST reference an id already in the stored
        candidate list - the user (like the LLM) can never inject a fabricated
        code. Editing quantities/units invalidates the prior match.
        """
        fields: dict[str, Any] = {}
        if spec.description is not None:
            fields["description"] = spec.description
        if spec.chosen_unit is not None:
            fields["chosen_unit"] = spec.chosen_unit
        if spec.quantities is not None:
            fields["quantities"] = spec.quantities
        if spec.notes is not None:
            fields["notes"] = spec.notes

        if spec.candidate_id is not None:
            cand = next(
                (c for c in (grp.candidates or []) if str(c.get("candidate_id")) == str(spec.candidate_id)),
                None,
            )
            if cand is None:
                raise HTTPException(
                    status_code=400,
                    detail="candidate_id must be one of this group's existing candidates (rates are never fabricated).",
                )
            resources = await self._resource_breakdown(cand.get("candidate_id"))
            score = self._real_confidence(cand.get("score"))
            fields.update(
                candidate_id=cand.get("candidate_id"),
                chosen_code=cand.get("code"),
                unit_rate=cand.get("unit_rate"),
                currency=cand.get("currency") or None,
                score=score,
                confidence=score,
                confidence_band=cand.get("confidence_band") or _confidence_band(score),
                match_method="manual",
                resources=resources,
                status="overridden",
            )
        if spec.status is not None:
            fields["status"] = spec.status

        await self.group_repo.update_fields(grp.id, **fields)
        refreshed = await self.group_repo.get_by_id(grp.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    async def merge_groups(self, run: AiEstimatorRun, spec: schemas.GroupMergeRequest) -> None:
        """Merge several stage-2 groups into the first, summing quantities.

        The merged group keeps the first id; the rest are deleted. Any prior
        match is cleared (the merged group must be re-matched) so a stale
        candidate never carries over onto a changed quantity.
        """
        if len(spec.group_ids) < 2:
            raise HTTPException(status_code=400, detail="Merging requires at least two groups.")
        wanted = {gid for gid in spec.group_ids}
        groups = [g for g in await self.group_repo.list_for_run(run.id) if g.id in wanted]
        if len(groups) != len(wanted):
            raise HTTPException(status_code=404, detail="One or more groups were not found in this run.")
        primary, *rest = groups
        merged_qty: dict[str, float] = dict(primary.quantities or {})
        merged_ids: list[str] = list(primary.element_ids or [])
        for g in rest:
            for k, v in (g.quantities or {}).items():
                merged_qty[k] = float(merged_qty.get(k, 0.0)) + float(v or 0.0)
            merged_ids.extend(str(e) for e in (g.element_ids or []))
        unit = _pick_unit(merged_qty)
        await self.group_repo.update_fields(
            primary.id,
            quantities=merged_qty,
            element_ids=merged_ids,
            element_count=len(merged_ids),
            chosen_unit=unit,
            description=spec.new_description or primary.description,
            status="unmatched",
            candidate_id=None,
            chosen_code=None,
            unit_rate=None,
            currency=None,
            score=None,
            confidence=None,
            confidence_band="none",
            resources=[],
            candidates=[],
            match_method=None,
        )
        for g in rest:
            await self.session.delete(g)
        await self.session.flush()

    async def split_group(self, run: AiEstimatorRun, spec: schemas.GroupSplitRequest) -> None:
        """Split a subset of element ids out of their group into a new group.

        Locates the group owning the requested element ids, removes them, and
        creates a fresh unmatched group for them. Both groups lose any prior
        match so the changed quantities are re-grounded.
        """
        wanted = {str(e) for e in spec.element_ids}
        if not wanted:
            raise HTTPException(status_code=400, detail="No element ids to split.")
        groups = await self.group_repo.list_for_run(run.id)
        source = next((g for g in groups if wanted & {str(e) for e in (g.element_ids or [])}), None)
        if source is None:
            raise HTTPException(status_code=404, detail="No group owns the requested elements.")

        remaining = [str(e) for e in (source.element_ids or []) if str(e) not in wanted]
        moved = [str(e) for e in (source.element_ids or []) if str(e) in wanted]
        if not moved:
            raise HTTPException(status_code=400, detail="Requested elements are not in any group.")

        # Re-derive quantities from the run's stored envelopes for each side so
        # the split is dimensionally honest (we never guess - we re-sum).
        envelopes = {str(e.get("id")): e for e in ((run.metadata_ or {}).get("envelopes") or [])}
        rem_qty = self._sum_quantities(remaining, envelopes)
        new_qty = self._sum_quantities(moved, envelopes)

        # Snapshot the scalars we need for the new group BEFORE mutating the
        # source row (group_key / sort_order are not in the update, and we read
        # them after - this keeps the new-group build independent of ORM state).
        source_group_key = source.group_key
        source_sort_order = int(source.sort_order or 0)

        await self.group_repo.update_fields(
            source.id,
            element_ids=remaining,
            element_count=len(remaining),
            quantities=rem_qty,
            chosen_unit=_pick_unit(rem_qty),
            status="unmatched",
            candidate_id=None,
            chosen_code=None,
            unit_rate=None,
            currency=None,
            score=None,
            confidence=None,
            confidence_band="none",
            resources=[],
            candidates=[],
            match_method=None,
        )
        new_unit = _pick_unit(new_qty)
        sample = envelopes.get(moved[0], {})
        new_desc = spec.new_description or str(sample.get("description") or source_group_key)[:500]
        await self.group_repo.add(
            AiEstimatorGroup(
                run_id=run.id,
                group_key=f"{source_group_key} (split)",
                signature=None,
                element_ids=moved,
                element_count=len(moved),
                quantities=new_qty,
                envelope=self._group_envelope([sample] if sample else [{}], new_desc, new_unit, run),
                chosen_unit=new_unit,
                description=new_desc,
                trade=classify_trade(new_desc, sample.get("category")),
                status="unmatched",
                sort_order=source_sort_order,
            )
        )

    @staticmethod
    def _sum_quantities(element_ids: list[str], envelopes: dict[str, dict[str, Any]]) -> dict[str, float]:
        """Re-sum canonical quantities for a set of element ids from envelopes."""
        out: dict[str, float] = {}
        for eid in element_ids:
            env = envelopes.get(eid)
            if not env:
                continue
            for k, v in (env.get("quantities") or {}).items():
                try:
                    out[k] = float(out.get(k, 0.0)) + float(v)
                except (TypeError, ValueError):
                    continue
        return {k: v for k, v in out.items() if v}

    async def confirm_group(
        self, grp: AiEstimatorGroup, spec: schemas.ConfirmGroupRequest, user_id: uuid.UUID
    ) -> AiEstimatorGroup:
        """Confirm a group's chosen candidate as the human decision."""
        fields: dict[str, Any] = {
            "status": "confirmed",
            "confirmed_by": user_id,
            "confirmed_at": datetime.now(UTC),
        }
        if spec.candidate_id is not None:
            cand = next(
                (c for c in (grp.candidates or []) if str(c.get("candidate_id")) == str(spec.candidate_id)),
                None,
            )
            if cand is None:
                raise HTTPException(
                    status_code=400,
                    detail="candidate_id must be one of this group's existing candidates.",
                )
            fields.update(
                candidate_id=cand.get("candidate_id"),
                chosen_code=cand.get("code"),
                unit_rate=cand.get("unit_rate"),
                currency=cand.get("currency") or None,
                resources=await self._resource_breakdown(cand.get("candidate_id")),
                match_method="manual",
            )
        if not grp.candidate_id and spec.candidate_id is None:
            raise HTTPException(status_code=400, detail="Cannot confirm a group with no grounded rate.")
        if spec.confidence is not None:
            fields["confidence"] = spec.confidence
            fields["confidence_band"] = _confidence_band(spec.confidence)
        await self.group_repo.update_fields(grp.id, **fields)
        refreshed = await self.group_repo.get_by_id(grp.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    async def bulk_confirm(
        self, run: AiEstimatorRun, spec: schemas.BulkConfirmRequest, user_id: uuid.UUID
    ) -> schemas.BulkConfirmResponse:
        """Confirm every suggested group at/above the confidence threshold."""
        groups = await self.group_repo.list_for_run(run.id)
        target_ids = {gid for gid in spec.group_ids} if spec.group_ids else None
        confirmed: list[uuid.UUID] = []
        skipped = 0
        for grp in groups:
            if target_ids is not None and grp.id not in target_ids:
                continue
            conf = grp.confidence
            if grp.status == "suggested" and grp.candidate_id and conf is not None and conf >= spec.threshold:
                await self.group_repo.update_fields(
                    grp.id,
                    status="confirmed",
                    confirmed_by=user_id,
                    confirmed_at=datetime.now(UTC),
                )
                confirmed.append(grp.id)
            else:
                skipped += 1
        return schemas.BulkConfirmResponse(confirmed=len(confirmed), skipped=skipped, group_ids=confirmed)

    # ── Stage 4: assembly preview + apply ─────────────────────────────────

    async def build_preview(self, run: AiEstimatorRun) -> schemas.PreviewResponse:
        """Assemble the estimate preview (NOT written) + run validation.

        Reuses the FX-correct, never-blend rollup math from
        ``match_elements.apply_to_boq`` (Decimal end-to-end) and the resource
        sub-row scaling, then validates the in-memory positions through the
        core engine.
        """
        base_currency, fx_map = await self._project_currency_context(run)
        groups = await self.group_repo.list_for_run(run.id, statuses=["confirmed", "overridden", "suggested"])

        rows: list[schemas.PreviewPositionRow] = []
        validation_positions: list[dict[str, Any]] = []
        grand_total = Decimal("0")
        subtotals: dict[str, Decimal] = {}

        for ordinal, grp in enumerate(groups, start=1):
            unit = grp.chosen_unit or "pcs"
            qty = Decimal(str(_quantity_for_unit(grp.quantities or {}, unit)))
            unit_rate = _dec(grp.unit_rate)
            currency = (grp.currency or base_currency or "").upper()
            resources = self._preview_resources(grp.resources or [], float(qty))
            line = qty * unit_rate
            # FX-correct base-currency rollup; never blend currencies.
            base_line = line
            if currency and base_currency and currency != base_currency and fx_map:
                fx = fx_map.get(currency)
                if fx:
                    base_line = line * _dec(fx)
            grand_total += base_line
            subtotals[currency or base_currency] = subtotals.get(currency or base_currency, Decimal("0")) + line

            confidence = grp.confidence
            rows.append(
                schemas.PreviewPositionRow(
                    group_id=grp.id,
                    group_key=grp.group_key,
                    section_path=self._section_path(grp),
                    description=grp.description or grp.group_key,
                    unit=unit,
                    quantity=float(qty),
                    unit_rate=unit_rate,
                    currency=currency or base_currency or "",
                    line_total=line.quantize(_Q2, rounding=ROUND_HALF_UP),
                    confidence=confidence,
                    confidence_band=grp.confidence_band or _confidence_band(confidence),  # type: ignore[arg-type]
                    resources=resources,
                    confirmed=False,
                )
            )
            validation_positions.append(
                {
                    "id": str(grp.id),
                    "group_id": str(grp.id),
                    "ordinal": f"{ordinal:04d}",
                    "description": grp.description or grp.group_key,
                    "unit": unit,
                    "quantity": float(qty),
                    "unit_rate": format(unit_rate, "f"),
                    "currency": currency or base_currency or "",
                    "confidence": confidence,
                    "confidence_band": grp.confidence_band,
                    "human_confirmed": grp.status in ("confirmed", "overridden"),
                    "resources": grp.resources or [],
                    # The grounded CWICR row's standard classification so the
                    # MasterFormat / DIN rules validate against the real code.
                    "classification": self._classification_for_group(grp),
                    "metadata_": {"cost_item_id": grp.candidate_id, "match_method": grp.match_method},
                }
            )

        validation, completeness, missing = await self._validate_positions(run, validation_positions, base_currency)
        can_apply = validation is None or validation.status != "errors"
        # A run with no confirmed/overridden groups cannot apply yet.
        has_confirmed = any(g.status in ("confirmed", "overridden") for g in groups)
        can_apply = can_apply and has_confirmed

        await self.run_repo.update_fields(
            run.id,
            validation_report=(validation.model_dump() if validation else None),
            grand_total=format(grand_total.quantize(_Q2, rounding=ROUND_HALF_UP), "f"),
            currency_subtotals={k: format(v.quantize(_Q2, rounding=ROUND_HALF_UP), "f") for k, v in subtotals.items()},
            completeness_score=completeness,
        )

        return schemas.PreviewResponse(
            run_id=run.id,
            positions=rows,
            grand_total=grand_total.quantize(_Q2, rounding=ROUND_HALF_UP),
            currency=base_currency or None,
            currency_subtotals={k: format(v.quantize(_Q2, rounding=ROUND_HALF_UP), "f") for k, v in subtotals.items()},
            validation=validation,
            completeness_score=completeness,
            missing_items=missing,
            can_apply=can_apply,
        )

    def _preview_resources(
        self, resources: list[dict[str, Any]], parent_qty: float
    ) -> list[schemas.PreviewResourceRow]:
        """Scale stored resource components by factor x parent quantity."""
        out: list[schemas.PreviewResourceRow] = []
        for comp in resources:
            if not isinstance(comp, dict):
                continue
            factor = float(comp.get("factor", 1.0) or 1.0)
            out.append(
                schemas.PreviewResourceRow(
                    description=str(comp.get("name") or comp.get("code") or ""),
                    factor=factor,
                    quantity=factor * parent_qty,
                    unit=str(comp.get("unit") or ""),
                    unit_rate=_dec(comp.get("unit_rate")),
                    type=str(comp.get("type") or "other"),
                )
            )
        return out

    @staticmethod
    def _section_path(grp: AiEstimatorGroup) -> list[str]:
        """Classification/trade section path for the preview row."""
        return [grp.trade or "other"]

    async def _project_currency_context(self, run: AiEstimatorRun) -> tuple[str, dict[str, Any]]:
        """Resolve the run's base currency + FX map (no EUR hardcode)."""
        from app.modules.boq.service import _project_fx_map
        from app.modules.projects.models import Project

        project = await self.session.get(Project, run.project_id)
        base_currency = (run.currency or "").upper()
        if not base_currency and project and getattr(project, "currency", None):
            base_currency = str(project.currency).upper()
        if not base_currency and project is not None:
            from app.modules.costs.router import _REGION_CURRENCY

            region = (getattr(project, "region", "") or "").strip().upper()
            base_currency = _REGION_CURRENCY.get(region, "")
        fx_map = _project_fx_map(project) if project is not None else {}
        return base_currency, fx_map

    async def _validate_positions(
        self, run: AiEstimatorRun, positions: list[dict[str, Any]], base_currency: str
    ) -> tuple[schemas.ValidationReportOut | None, float | None, list[str]]:
        """Run the core engine (boq_quality + ai_estimator + regional) on the
        in-memory preview positions, returning the report, completeness, missing.
        """
        from app.core.validation.engine import validation_engine
        from app.modules.costs.cwicr_v3_catalogue import get_catalogue

        if not positions:
            return None, None, []

        rule_sets = ["boq_quality", "ai_estimator"]
        # Add the project's regional standard when known (from the catalogue).
        regional = None
        if run.catalogue_id:
            cat = get_catalogue(run.catalogue_id) or get_catalogue(run.region or "")
            regional = getattr(cat, "default_classification_standard", None) if cat else None
        if regional:
            rule_sets.append(regional)

        missing_items = list((run.metadata_ or {}).get("missing_items") or [])
        try:
            report = await validation_engine.validate(
                data={"positions": positions},
                rule_sets=rule_sets,
                target_type="boq",
                target_id=str(run.id),
                project_id=str(run.project_id),
                metadata={"base_currency": base_currency, "missing_items": missing_items},
            )
        except Exception as exc:  # noqa: BLE001 - validation must not break the preview
            logger.warning("ai_estimator validation failed: %s", exc)
            return None, None, missing_items

        out = self._report_to_schema(report, "+".join(rule_sets))
        # Completeness from missing items (advisory). 1.0 when nothing missing.
        completeness = 1.0 if not missing_items else max(0.0, 1.0 - 0.1 * len(missing_items))
        return out, round(completeness, 4), missing_items

    @staticmethod
    def _report_to_schema(report: Any, rule_set: str) -> schemas.ValidationReportOut:
        """Convert a core ValidationReport to the API ValidationReportOut.

        SKIPPED reports keep ``score=None`` (never 1.0). Only failing rows are
        listed in the warning/error buckets; passing rows are summarised.
        """

        def _row(r: Any) -> schemas.ValidationResultOut:
            sev = r.severity.value if hasattr(r.severity, "value") else str(r.severity)
            status = "pass" if r.passed else ("error" if sev == "error" else "warning")
            return schemas.ValidationResultOut(
                rule_id=r.rule_id,
                status=status,  # type: ignore[arg-type]
                severity=sev,  # type: ignore[arg-type]
                message=r.message,
                element_ref=r.element_ref,
            )

        return schemas.ValidationReportOut(
            status=report.status.value,  # type: ignore[arg-type]
            score=report.score,
            rule_set=rule_set,
            passed=[_row(r) for r in report.passed_rules[:50]],
            warnings=[_row(r) for r in report.warnings[:200]],
            errors=[_row(r) for r in report.errors[:200]],
        )

    async def apply(self, run: AiEstimatorRun, spec: schemas.ApplyRequest, user_id: uuid.UUID) -> schemas.ApplyResponse:
        """Write the assembled estimate to a BOQ (explicit human action only).

        Requires the assembly checkpoint accepted and a clean validation report
        (no ERROR-severity rule). Creates one Position per confirmed group with
        provenance ``source='ai_precise_estimate'``, the real (or null)
        confidence, ``validation_status='pending'``, ``cad_element_ids``, and
        the scaled resource breakdown in ``metadata_['resources']``.
        """
        from app.modules.boq.models import BOQ, Position
        from app.modules.projects.models import Project

        if "assembly" not in (run.checkpoints or {}):
            raise HTTPException(status_code=409, detail="Accept the assembly review checkpoint before applying.")

        # Re-run the preview so the apply is gated on the current validation.
        preview = await self.build_preview(run)
        if not preview.can_apply:
            raise HTTPException(
                status_code=409,
                detail="The estimate cannot be applied: validation has blocking errors or no group is confirmed.",
            )

        base_currency, fx_map = await self._project_currency_context(run)

        # Resolve/create the target BOQ (cross-tenant guard on a supplied id).
        boq_id = spec.target_boq_id
        if boq_id is not None:
            target = await self.session.get(BOQ, boq_id)
            if target is None or target.project_id != run.project_id:
                raise HTTPException(status_code=404, detail="Target BOQ not found.")
        else:
            project = await self.session.get(Project, run.project_id)
            label = getattr(project, "name", None) or f"Project {str(run.project_id)[:8]}"
            boq = BOQ(
                project_id=run.project_id,
                name=spec.boq_name or f"{label} - AI Estimate",
                description=f"Created by AI Estimate Builder (run {str(run.id)[:8]}).",
                status="draft",
            )
            self.session.add(boq)
            await self.session.flush()
            boq_id = boq.id

        # Continue ordinals after any positions already on the target BOQ.
        max_ord = await self._count_positions(boq_id)

        target_ids = {gid for gid in spec.group_ids} if spec.group_ids else None
        groups = await self.group_repo.list_for_run(run.id, statuses=["confirmed", "overridden"])
        groups = groups[:_APPLY_BATCH_LIMIT]

        positions_created = 0
        grand_total = Decimal("0")
        subtotals: dict[str, Decimal] = {}

        for grp in groups:
            if target_ids is not None and grp.id not in target_ids:
                continue
            unit = grp.chosen_unit or "pcs"
            qty = Decimal(str(_quantity_for_unit(grp.quantities or {}, unit)))
            unit_rate = _dec(grp.unit_rate)
            currency = (grp.currency or base_currency or "").upper()
            line = qty * unit_rate
            base_line = line
            if currency and base_currency and currency != base_currency and fx_map:
                fx = fx_map.get(currency)
                if fx:
                    base_line = line * _dec(fx)
            grand_total += base_line
            subtotals[currency or base_currency] = subtotals.get(currency or base_currency, Decimal("0")) + line

            max_ord += 1
            scaled_resources = [
                {**c, "quantity": float(c.get("factor", 1.0) or 1.0) * float(qty)}
                for c in (grp.resources or [])
                if isinstance(c, dict)
            ]
            metadata: dict[str, Any] = {
                "ai_estimator_run_id": str(run.id),
                "group_key": grp.group_key,
                "signature": grp.signature or "",
                "match_method": grp.match_method or "manual",
                "score": grp.score,
                "candidates_considered": len(grp.candidates or []),
                "resources": scaled_resources,
            }
            if grp.candidate_id:
                metadata["cost_item_id"] = grp.candidate_id

            pos = Position(
                boq_id=boq_id,
                parent_id=None,
                ordinal=f"{max_ord:04d}",
                description=grp.description or grp.group_key,
                unit=unit,
                quantity=f"{float(qty):.4f}",
                unit_rate=format(unit_rate.quantize(_Q4, rounding=ROUND_HALF_UP), "f"),
                total=format((qty * unit_rate).quantize(_Q4, rounding=ROUND_HALF_UP), "f"),
                # The grounded CWICR row's standard classification (MasterFormat /
                # DIN / NRM) - the real code the matched catalogue row carries.
                classification=self._classification_for_group(grp),
                source="ai_precise_estimate",
                # Confidence is the real float or empty string when none - never
                # a fabricated placeholder (Position.confidence is a free string).
                confidence=("" if grp.confidence is None else f"{grp.confidence:.4f}"),
                cad_element_ids=list(grp.element_ids or []),
                validation_status="pending",
                metadata_=metadata,
                sort_order=max_ord,
            )
            self.session.add(pos)
            await self.session.flush()
            await self.group_repo.update_fields(grp.id, boq_position_id=pos.id, status="applied")
            positions_created += 1

        await self.run_repo.update_fields(
            run.id,
            status="applied",
            current_stage="assembly",
            boq_id=boq_id,
            grand_total=format(grand_total.quantize(_Q2, rounding=ROUND_HALF_UP), "f"),
            currency_subtotals={k: format(v.quantize(_Q2, rounding=ROUND_HALF_UP), "f") for k, v in subtotals.items()},
        )
        await self._log(
            run.id, "assembly", "stage_complete", {"positions_created": positions_created, "boq_id": str(boq_id)}
        )
        estimator_events.emit_run_applied(
            run_id=str(run.id),
            project_id=str(run.project_id),
            boq_id=str(boq_id),
            positions_created=positions_created,
        )
        return schemas.ApplyResponse(
            run_id=run.id,
            boq_id=boq_id,
            positions_created=positions_created,
            grand_total=grand_total.quantize(_Q2, rounding=ROUND_HALF_UP),
            currency=base_currency or None,
            currency_subtotals={k: format(v.quantize(_Q2, rounding=ROUND_HALF_UP), "f") for k, v in subtotals.items()},
        )

    async def _count_positions(self, boq_id: uuid.UUID) -> int:
        """Count existing positions on a BOQ (so appended ordinals continue)."""
        from sqlalchemy import func as sa_func
        from sqlalchemy import select

        from app.modules.boq.models import Position

        result = await self.session.execute(select(sa_func.count(Position.id)).where(Position.boq_id == boq_id))
        return int(result.scalar_one() or 0)

    async def cancel(self, run: AiEstimatorRun) -> AiEstimatorRun:
        """Cancel a run (terminal). Applied runs cannot be cancelled."""
        if run.status == "applied":
            raise HTTPException(status_code=409, detail="An applied run cannot be cancelled.")
        await self.run_repo.update_fields(run.id, status="cancelled")
        refreshed = await self.run_repo.get_by_id(run.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    # ── Progress / readiness / serialisation ──────────────────────────────

    async def build_progress(self, run: AiEstimatorRun) -> schemas.ProgressResponse:
        """Assemble the poll payload: status, stepper, counts, AI/vector state."""
        counts = await self.group_repo.status_counts(run.id)
        group_count = sum(counts.values())
        matched = sum(v for k, v in counts.items() if k in ("suggested", "confirmed", "overridden", "applied"))
        confirmed = sum(v for k, v in counts.items() if k in ("confirmed", "overridden", "applied"))
        ai_connected, _provider, _model = await self._ai_status(run.user_id)
        vector_ready, _vec_count = await self._vector_status(run)
        degraded = self._degraded_reason(ai_connected, vector_ready, run)
        steps = await self.step_repo.list_for_run(run.id, limit=12, newest_first=True)

        return schemas.ProgressResponse(
            run_id=run.id,
            status=run.status,  # type: ignore[arg-type]
            current_stage=run.current_stage,  # type: ignore[arg-type]
            stages=self._stage_states(run),
            group_count=group_count,
            matched_count=matched,
            confirmed_count=confirmed,
            failure_reason=run.failure_reason,
            ai_connected=ai_connected,
            vector_ready=vector_ready,
            degraded_reason=degraded,
            provider=run.provider or (_provider if ai_connected else None),
            model_used=run.model_used or (_model if ai_connected else None),
            recent_steps=[schemas.StepOut.model_validate(s) for s in reversed(steps)],
        )

    def _stage_states(self, run: AiEstimatorRun) -> list[schemas.StageState]:
        """Render the four-stage stepper from the run FSM + checkpoints."""
        checkpoints = run.checkpoints or {}
        out: list[schemas.StageState] = []
        active = run.current_stage
        for stage in _STAGE_ORDER:
            accepted = checkpoints.get(stage, {}).get("accepted_at")
            if accepted:
                status = "complete"
            elif stage == active:
                status = "error" if run.status == "failed" else "active"
            else:
                status = "pending"
            out.append(
                schemas.StageState(
                    stage=stage,  # type: ignore[arg-type]
                    title=_STAGE_TITLES[stage],
                    status=status,  # type: ignore[arg-type]
                    accepted_at=(datetime.fromisoformat(accepted) if accepted else None),
                )
            )
        return out

    async def build_readiness(self, run: AiEstimatorRun) -> schemas.ReadinessResponse:
        """Pre-flight: AI key + vector DB + catalogue availability with guidance."""
        from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES

        ai_connected, provider, model = await self._ai_status(run.user_id)
        vector_ready, vector_count = await self._vector_status(run)
        catalogues_available = sum(1 for c in CWICR_V3_CATALOGUES if c.available)

        message = None
        if not ai_connected:
            message = (
                "AI is not connected. The estimate still works with deterministic grounded matching. "
                "Add or re-enter your API key in Settings > AI to enable AI source understanding and "
                "per-group reasoning."
            )
        elif not vector_ready:
            message = (
                "The vector database has few or no rates indexed for this catalogue. Matching falls back to "
                "lexical search (honest, lower scores). Install or index a catalogue to improve recall."
            )
        return schemas.ReadinessResponse(
            ai_connected=ai_connected,
            provider=provider,
            model_used=model,
            vector_ready=vector_ready,
            vector_count=vector_count,
            catalogues_available=catalogues_available,
            message=message,
        )

    async def _ai_status(self, user_id: uuid.UUID) -> tuple[bool, str | None, str | None]:
        """Return (connected, provider, model) without raising."""
        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository

        settings = await AISettingsRepository(self.session).get_by_user_id(user_id)
        try:
            provider, _key, model = resolve_provider_key_model(settings)
        except ValueError:
            return False, None, None
        return True, provider, (model or provider)

    async def _vector_status(self, run: AiEstimatorRun) -> tuple[bool, int]:
        """Probe whether the run's catalogue has > 100 vectors indexed."""
        from app.core.match_service.ranker_qdrant import _resolve_catalog_status

        catalogue = run.catalogue_id
        if not catalogue:
            return False, 0
        try:
            _status, _sql, vec = await _resolve_catalog_status(self.session, catalogue)
        except Exception:  # noqa: BLE001
            return False, 0
        return (vec or 0) > 100, int(vec or 0)

    @staticmethod
    def _degraded_reason(ai_connected: bool, vector_ready: bool, run: AiEstimatorRun) -> str | None:
        """Pick the single most relevant degradation reason for the banner."""
        if not ai_connected:
            return "no_ai_key"
        if run.catalogue_id and not vector_ready:
            return "no_vectors"
        if not run.catalogue_id:
            return "no_catalogue"
        return None

    # ── Step logging ──────────────────────────────────────────────────────

    async def _log(self, run_id: uuid.UUID, stage: str, role: str, content: Any, *, token_count: int = 0) -> None:
        """Append one entry to the run's pipeline timeline."""
        idx = await self.step_repo.next_idx(run_id)
        await self.step_repo.add(
            AiEstimatorStep(
                run_id=run_id,
                stage=stage,
                step_idx=idx,
                role=role,
                content=content,
                token_count=token_count,
            )
        )

    # ── Serialisation ─────────────────────────────────────────────────────

    @staticmethod
    def run_to_read(run: AiEstimatorRun) -> schemas.RunRead:
        """Serialise a run row to the full RunRead payload."""
        return schemas.RunRead(
            id=run.id,
            project_id=run.project_id,
            user_id=run.user_id,
            name=run.name,
            agent_name=run.agent_name,
            status=run.status,  # type: ignore[arg-type]
            current_stage=run.current_stage,  # type: ignore[arg-type]
            checkpoints=run.checkpoints or {},
            source_inputs=run.source_inputs or {},
            detected_source=run.detected_source or {},
            suggested_config=run.suggested_config or {},
            catalogue_id=run.catalogue_id,
            region=run.region,
            currency=run.currency,
            group_by=list(run.group_by or []),
            construction_stage=run.construction_stage,  # type: ignore[arg-type]
            provider=run.provider,
            model_used=run.model_used,
            total_tokens=int(run.total_tokens or 0),
            cost_usd_estimate=float(run.cost_usd_estimate or 0.0),
            duration_ms=int(run.duration_ms or 0),
            validation_report=run.validation_report,
            grand_total=(Decimal(run.grand_total) if run.grand_total else None),
            currency_subtotals=run.currency_subtotals or {},
            completeness_score=run.completeness_score,
            boq_id=run.boq_id,
            failure_reason=run.failure_reason,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    async def run_to_summary(self, run: AiEstimatorRun) -> schemas.RunSummary:
        """Serialise a run row to the compact RunSummary (with group counts)."""
        counts = await self.group_repo.status_counts(run.id)
        return schemas.RunSummary(
            id=run.id,
            project_id=run.project_id,
            name=run.name,
            source=(run.source_inputs or {}).get("source"),
            status=run.status,  # type: ignore[arg-type]
            current_stage=run.current_stage,  # type: ignore[arg-type]
            group_count=sum(counts.values()),
            confirmed_count=sum(v for k, v in counts.items() if k in ("confirmed", "overridden", "applied")),
            applied_count=counts.get("applied", 0),
            model_used=run.model_used,
            grand_total=(Decimal(run.grand_total) if run.grand_total else None),
            currency=run.currency,
            boq_id=run.boq_id,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @staticmethod
    def _mapping_trace_out(raw: Any) -> schemas.MappingTrace | None:
        """Serialise the stored multi-pass trace into the typed schema (design 3.3).

        The trace lives in the group's free ``metadata_.mapping_trace`` JSON the
        matcher writes (passes + final_method + optional needs_human_reason). It
        is display-only provenance, so this read path is deliberately defensive:
        an absent, non-dict or partially-malformed trace yields ``None`` rather
        than ever crashing the group-detail endpoint. The pass key ``pass`` is
        mapped onto the ``pass_`` field alias by the model.

        Args:
            raw: The ``metadata_.mapping_trace`` value (any JSON-decoded type).

        Returns:
            The typed :class:`schemas.MappingTrace`, or ``None`` when the group
            has not been matched yet or the stored trace is unusable.
        """
        if not isinstance(raw, dict) or not raw:
            return None
        try:
            return schemas.MappingTrace.model_validate(raw)
        except ValidationError as exc:  # never break the detail view over bad provenance
            logger.warning("ai_estimator: unreadable mapping_trace, omitting: %s", exc)
            return None

    def group_to_summary(self, grp: AiEstimatorGroup) -> schemas.GroupSummary:
        """Serialise a group to the grid-row GroupSummary."""
        unit = grp.chosen_unit or "pcs"
        return schemas.GroupSummary(
            id=grp.id,
            group_key=grp.group_key,
            description=grp.description,
            trade=grp.trade,
            signature=grp.signature,
            element_count=int(grp.element_count or 0),
            quantities={k: float(v) for k, v in (grp.quantities or {}).items()},
            chosen_unit=unit,
            primary_quantity=float(_quantity_for_unit(grp.quantities or {}, unit) or 0.0),
            chosen_code=grp.chosen_code,
            # Treat a stored "0" (legacy rows / manual override of an unpriced
            # code) as no rate, so the grid never shows a fabricated $0.00.
            unit_rate=(_dec(grp.unit_rate) if grp.unit_rate and _dec(grp.unit_rate) > 0 else None),
            currency=grp.currency,
            score=grp.score,
            confidence=grp.confidence,
            confidence_band=grp.confidence_band or "none",  # type: ignore[arg-type]
            match_method=grp.match_method,
            status=grp.status,  # type: ignore[arg-type]
            boq_position_id=grp.boq_position_id,
            sort_order=int(grp.sort_order or 0),
        )

    def group_to_detail(self, grp: AiEstimatorGroup) -> schemas.GroupDetail:
        """Serialise a group to the full GroupDetail (candidates + resources).

        Surfaces the WorkGroup provenance (design 3.1) read-only from
        ``metadata_``: ``source``, ``derivation``, ``assumptions`` and the
        ``mapping_trace`` the matcher writes.
        """
        summary = self.group_to_summary(grp)
        meta = grp.metadata_ or {}
        assumptions = meta.get("assumptions")
        return schemas.GroupDetail(
            **summary.model_dump(),
            run_id=grp.run_id,
            element_ids=[str(e) for e in (grp.element_ids or [])],
            envelope=grp.envelope or {},
            source=(str(meta["source"]) if meta.get("source") else None),
            derivation=(str(meta["derivation"]) if meta.get("derivation") else None),
            assumptions=[str(a) for a in assumptions] if isinstance(assumptions, list) else [],
            mapping_trace=self._mapping_trace_out(meta.get("mapping_trace")),
            resources=[
                schemas.ResourceOut(
                    name=str(r.get("name") or ""),
                    code=str(r.get("code") or ""),
                    unit=str(r.get("unit") or ""),
                    factor=float(r.get("factor", 0.0) or 0.0),
                    quantity=float(r.get("quantity", 0.0) or 0.0),
                    unit_rate=_dec(r.get("unit_rate")),
                    type=str(r.get("type") or "other"),
                )
                for r in (grp.resources or [])
                if isinstance(r, dict)
            ],
            candidates=[
                schemas.CandidateOut(
                    candidate_id=c.get("candidate_id"),
                    code=str(c.get("code") or ""),
                    description=str(c.get("description") or ""),
                    unit=str(c.get("unit") or ""),
                    # Preserve a null rate (unpriced code) instead of coercing it
                    # back to 0; only a positive stored value is a real rate.
                    unit_rate=(
                        _dec(c.get("unit_rate"))
                        if c.get("unit_rate") not in (None, "") and _dec(c.get("unit_rate")) > 0
                        else None
                    ),
                    currency=str(c.get("currency") or ""),
                    score=float(c.get("score", 0.0) or 0.0),
                    confidence_band=c.get("confidence_band") or "low",
                    rate_outlier=bool(c.get("rate_outlier", False)),
                )
                for c in (grp.candidates or [])
                if isinstance(c, dict)
            ],
            confirmed_by=grp.confirmed_by,
            confirmed_at=grp.confirmed_at,
            notes=grp.notes,
        )

    async def group_list_response(
        self, run_id: uuid.UUID, *, statuses: list[str] | None = None
    ) -> schemas.GroupListResponse:
        """Assemble the GroupListResponse with summary counts + thresholds."""
        groups = await self.group_repo.list_for_run(run_id, statuses=statuses)
        counts = await self.group_repo.status_counts(run_id)
        return schemas.GroupListResponse(
            run_id=run_id,
            total=len(groups),
            groups=[self.group_to_summary(g) for g in groups],
            summary=counts,
            confidence_high_threshold=CONFIDENCE_HIGH_THRESHOLD,
            confidence_medium_threshold=CONFIDENCE_MEDIUM_THRESHOLD,
        )
