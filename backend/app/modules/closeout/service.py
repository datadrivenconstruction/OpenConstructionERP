"""Closeout business logic (stateless service).

Drives the per-project handover package: seeding the checklist from a
template, recomputing completeness on every mutation, binding / verifying
evidence, AI-suggesting (never auto-applying) bindings, kicking off an
idempotent background build, and assembling the structured ZIP.

The ZIP assembler reuses the canonical zip+manifest+index.json+sha256
pattern from ``projects/bundle_export.py`` and the path-traversal-safe
local-upload copy logic from ``property_dev/service.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_runner import submit_job
from app.modules.closeout import checklist_templates as templates
from app.modules.closeout.cover_pdf import render_cover_pdf
from app.modules.closeout.models import CloseoutBinding, CloseoutPackage, CloseoutSlot
from app.modules.closeout.repository import CloseoutRepository

logger = logging.getLogger(__name__)

JOB_KIND = "closeout.build"

# Generated-artifact slot statuses count as "delivered" once the package has
# been built (the artifact exists in the last ZIP); before that they are
# treated as outstanding unless explicitly verified.
_GENERATED_KINDS = {"cobie_xlsx", "punch_closure_report", "inspection_cert_pdf"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_zip_name(value: str, fallback: str = "item") -> str:
    """Sanitise a string into a safe ZIP path segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or fallback


class CloseoutService:
    """Stateless service for the closeout package workflow."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CloseoutRepository(session)

    # ── Package lifecycle ────────────────────────────────────────────────

    async def get_package_for_project(self, project_id: uuid.UUID) -> CloseoutPackage | None:
        return await self.repo.get_package_for_project(project_id)

    async def get_package_or_404(self, package_id: uuid.UUID) -> CloseoutPackage:
        package = await self.repo.get_package(package_id)
        if package is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Closeout package not found")
        return package

    async def create_package(
        self,
        project_id: uuid.UUID,
        project_type: str,
        *,
        title: str | None = None,
    ) -> CloseoutPackage:
        """Create the package for a project and seed slots from the template.

        Idempotent at the project grain: if a package already exists it is
        returned unchanged (the table enforces one package per project).
        """
        existing = await self.repo.get_package_for_project(project_id)
        if existing is not None:
            return existing

        template_key = templates.resolve_template_key(project_type)
        package = CloseoutPackage(
            project_id=project_id,
            title=title or "Handover & Closeout Package",
            project_type=template_key,
            checklist_template=template_key,
            status="draft",
        )
        await self.repo.create_package(package)

        for slot_def in templates.template_for(template_key):
            slot = CloseoutSlot(
                package_id=package.id,
                slot_key=slot_def["slot_key"],
                title=slot_def["title"],
                category=slot_def.get("category", "other"),
                discipline=slot_def.get("discipline"),
                is_required=bool(slot_def.get("is_required", True)),
                source_kind=slot_def.get("source_kind", "cde_document"),
                generated_artifact=slot_def.get("generated_artifact"),
                ordinal=int(slot_def.get("ordinal", 0)),
            )
            await self.repo.add_slot(slot)

        await self.recompute_completeness(package)
        await self.session.commit()
        await self.session.refresh(package)
        return package

    # ── Completeness ─────────────────────────────────────────────────────

    def _slot_status(self, slot: CloseoutSlot, binding: CloseoutBinding | None, *, has_built: bool) -> str:
        """Derive a slot status from its binding and the build state."""
        if binding is not None:
            return "verified" if binding.is_verified else "bound"
        # Generated artifacts are produced by the build itself; once the
        # package has been built they are present, otherwise outstanding.
        if slot.source_kind == "generated" and slot.generated_artifact in _GENERATED_KINDS and has_built:
            return "bound"
        return "empty"

    async def _slot_status_map(self, package: CloseoutPackage) -> dict[uuid.UUID, str]:
        slots = await self.repo.list_slots(package.id)
        bindings = await self.repo.list_bindings_for_package(package.id)
        has_built = bool(package.package_key)
        return {slot.id: self._slot_status(slot, bindings.get(slot.id), has_built=has_built) for slot in slots}

    async def recompute_completeness(self, package: CloseoutPackage) -> CloseoutPackage:
        """Recompute denormalised counters + status from current slots/bindings.

        Completeness % = verified-or-delivered required slots / required slots.
        Status walks draft -> in_progress -> ready as evidence lands. ``issued``
        is a terminal state set explicitly (not auto-downgraded here).
        """
        slots = await self.repo.list_slots(package.id)
        bindings = await self.repo.list_bindings_for_package(package.id)
        has_built = bool(package.package_key)

        required = [s for s in slots if s.is_required]
        required_count = len(required)
        delivered_count = 0
        for slot in required:
            st = self._slot_status(slot, bindings.get(slot.id), has_built=has_built)
            # A required slot counts as delivered only when verified, OR when it
            # is a generated artifact that the LAST BUILD actually produced. A
            # generated artifact does not exist until the package is built, so
            # it must not inflate completeness before that (has_built gates it).
            if st == "verified" or (
                slot.source_kind == "generated" and slot.generated_artifact in _GENERATED_KINDS and has_built
            ):
                delivered_count += 1

        pct = 100 if required_count == 0 else round(delivered_count * 100 / required_count)

        package.required_slot_count = required_count
        package.delivered_slot_count = delivered_count
        package.completeness_pct = int(pct)

        if package.status != "issued":
            if delivered_count >= required_count and required_count > 0:
                package.status = "ready"
            elif delivered_count > 0 or any(bindings.get(s.id) for s in slots):
                package.status = "in_progress"
            else:
                package.status = "draft"

        self.session.add(package)
        await self.session.flush()
        return package

    async def gaps(self, package: CloseoutPackage, *, treat_built: bool | None = None) -> list[str]:
        """Titles of required slots not yet satisfied (the gap list).

        ``treat_built`` overrides whether generated artifacts are treated as
        present. It defaults to the package's real build state, but the build
        job passes ``True`` so the package it is producing reports its
        generated artifacts as delivered in its own cover / manifest.
        """
        slots = await self.repo.list_slots(package.id)
        bindings = await self.repo.list_bindings_for_package(package.id)
        has_built = bool(package.package_key) if treat_built is None else treat_built
        out: list[str] = []
        for slot in slots:
            if not slot.is_required:
                continue
            st = self._slot_status(slot, bindings.get(slot.id), has_built=has_built)
            if st == "verified":
                continue
            if slot.source_kind == "generated" and slot.generated_artifact in _GENERATED_KINDS and has_built:
                # Generated artifact present in the last build; not a gap.
                continue
            out.append(slot.title)
        return out

    async def is_ready(self, package: CloseoutPackage) -> bool:
        """True when every required slot is bound and verified."""
        return len(await self.gaps(package)) == 0 and package.required_slot_count > 0

    # ── Slot CRUD ────────────────────────────────────────────────────────

    async def add_slot(self, package: CloseoutPackage, data: dict[str, Any]) -> CloseoutSlot:
        # ``slot_key`` keys the build idempotency hash, validation-rule
        # element_ref and slot routing, so it must be unique within a package.
        slot_key = str(data["slot_key"]).strip()
        if not slot_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="slot_key must not be empty",
            )
        existing = await self.repo.list_slots(package.id)
        if any(s.slot_key == slot_key for s in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A slot with key '{slot_key}' already exists in this package",
            )
        slot = CloseoutSlot(
            package_id=package.id,
            slot_key=slot_key,
            title=data["title"],
            category=data.get("category", "other"),
            discipline=data.get("discipline"),
            is_required=bool(data.get("is_required", True)),
            source_kind=data.get("source_kind", "cde_document"),
            generated_artifact=data.get("generated_artifact"),
            ordinal=int(data.get("ordinal", 0)),
            metadata_=dict(data.get("metadata") or {}),
        )
        await self.repo.add_slot(slot)
        # Mark stale first so completeness recomputes against the cleared build
        # state (a fresh slot can invalidate a previously built / issued ZIP).
        await self._mark_stale(package)
        await self.recompute_completeness(package)
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def get_slot_or_404(self, slot_id: uuid.UUID) -> CloseoutSlot:
        slot = await self.repo.get_slot(slot_id)
        if slot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Closeout slot not found")
        return slot

    async def update_slot(self, slot: CloseoutSlot, fields: dict[str, Any]) -> CloseoutSlot:
        for key in ("title", "category", "discipline", "is_required", "source_kind", "generated_artifact", "ordinal"):
            if key in fields and fields[key] is not None:
                setattr(slot, key, fields[key])
        if fields.get("metadata") is not None:
            slot.metadata_ = dict(fields["metadata"])
        self.session.add(slot)
        await self.session.flush()
        package = await self.get_package_or_404(slot.package_id)
        await self._mark_stale(package)
        await self.recompute_completeness(package)
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def delete_slot(self, slot: CloseoutSlot) -> None:
        package_id = slot.package_id
        await self.repo.delete_slot(slot.id)
        package = await self.get_package_or_404(package_id)
        await self._mark_stale(package)
        await self.recompute_completeness(package)
        await self.session.commit()

    # ── Binding / verification ───────────────────────────────────────────

    async def bind_slot(
        self,
        slot: CloseoutSlot,
        *,
        document_id: uuid.UUID | None,
        external_url: str | None,
        mark_verified: bool,
        verified_by: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> CloseoutBinding:
        """Bind a slot to a document or external URL.

        Replaces any existing binding (one active binding per slot). The
        document, when supplied, must belong to the same project as the slot.
        """
        if document_id is None and not (external_url or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide either document_id or external_url",
            )

        package = await self.get_package_or_404(slot.package_id)

        if document_id is not None:
            await self._assert_document_in_project(document_id, package.project_id)

        await self.repo.delete_bindings_for_slot(slot.id)
        binding = CloseoutBinding(
            slot_id=slot.id,
            document_id=document_id,
            external_url=(external_url or "").strip() or None,
            is_verified=bool(mark_verified),
            verified_by=verified_by if mark_verified else None,
            verified_at=_now_iso() if mark_verified else None,
            suggested_by_ai=False,
            metadata_=dict(metadata or {}),
        )
        await self.repo.add_binding(binding)
        await self._mark_stale(package)
        await self.recompute_completeness(package)
        await self.session.commit()
        await self.session.refresh(binding)
        return binding

    async def unbind_slot(self, slot: CloseoutSlot) -> None:
        package = await self.get_package_or_404(slot.package_id)
        await self.repo.delete_bindings_for_slot(slot.id)
        await self._mark_stale(package)
        await self.recompute_completeness(package)
        await self.session.commit()

    async def verify_slot(self, slot: CloseoutSlot, *, is_verified: bool, verified_by: str | None) -> CloseoutBinding:
        """Human sign-off on a slot's evidence."""
        binding = await self.repo.get_binding_for_slot(slot.id)
        if binding is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slot has no evidence to verify - bind a document first",
            )
        binding.is_verified = bool(is_verified)
        binding.verified_by = verified_by if is_verified else None
        binding.verified_at = _now_iso() if is_verified else None
        self.session.add(binding)
        await self.session.flush()
        package = await self.get_package_or_404(slot.package_id)
        await self._mark_stale(package)
        await self.recompute_completeness(package)
        await self.session.commit()
        await self.session.refresh(binding)
        return binding

    async def _assert_document_in_project(self, document_id: uuid.UUID, project_id: uuid.UUID) -> None:
        """404 unless the document exists and belongs to the project (IDOR guard)."""
        from app.modules.documents.models import Document

        doc = await self.session.get(Document, document_id)
        if doc is None or doc.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found in this project")

    # ── AI-suggests-human-confirms ───────────────────────────────────────

    async def suggest_bindings(self, package: CloseoutPackage) -> list[dict[str, Any]]:
        """Propose CDE documents for empty document-backed slots.

        Matches by category / discipline / title keyword and returns a
        confidence score. Binds NOTHING - the caller confirms each suggestion
        explicitly (AI-augmented, human-confirmed).
        """
        from app.modules.documents.models import Document

        slots = await self.repo.list_slots(package.id)
        bindings = await self.repo.list_bindings_for_package(package.id)
        empty_doc_slots = [
            s for s in slots if s.source_kind in ("cde_document", "manual_upload") and bindings.get(s.id) is None
        ]
        if not empty_doc_slots:
            return []

        stmt = select(Document).where(Document.project_id == package.project_id)
        docs = list((await self.session.execute(stmt)).scalars().all())
        if not docs:
            return []

        suggestions: list[dict[str, Any]] = []
        used_doc_ids: set[uuid.UUID] = set()
        for slot in empty_doc_slots:
            best: tuple[float, Document, str] | None = None
            for doc in docs:
                if doc.id in used_doc_ids:
                    continue
                score, reason = self._score_doc_for_slot(slot, doc)
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, doc, reason)
            if best is not None and best[0] >= 0.3:
                score, doc, reason = best
                used_doc_ids.add(doc.id)
                suggestions.append(
                    {
                        "slot_id": slot.id,
                        "slot_key": slot.slot_key,
                        "document_id": doc.id,
                        "document_name": doc.name,
                        "confidence": round(min(score, 1.0), 2),
                        "reason": reason,
                    }
                )
        return suggestions

    def _score_doc_for_slot(self, slot: CloseoutSlot, doc: Any) -> tuple[float, str]:
        """Heuristic match score in 0..1 for one (slot, document) pair."""
        score = 0.0
        reasons: list[str] = []

        slot_cat = (slot.category or "").lower()
        doc_cat = (getattr(doc, "category", "") or "").lower()
        slot_key_tokens = set(re.split(r"[_\s]+", (slot.slot_key or "").lower()))
        title_tokens = set(re.split(r"[^a-z0-9]+", (getattr(doc, "name", "") or "").lower()))
        title_tokens.discard("")

        # Category alignment.
        if slot_cat and doc_cat and (slot_cat in doc_cat or doc_cat in slot_cat):
            score += 0.4
            reasons.append("category match")

        # Discipline alignment.
        slot_disc = (slot.discipline or "").lower()
        doc_disc = (getattr(doc, "discipline", "") or "").lower()
        if slot_disc and doc_disc and slot_disc == doc_disc:
            score += 0.25
            reasons.append("discipline match")

        # Keyword overlap between slot key / title and document name.
        keyword_map = {
            "as_built_drawings": {"as", "built", "asbuilt", "drawing", "drawings"},
            "om_manual": {"om", "operation", "maintenance", "manual"},
            "warranty": {"warranty", "warranties", "guarantee", "guarantees"},
            "hs_file": {"health", "safety", "hs", "hse", "file"},
            "commissioning_certs": {"commissioning", "test", "certificate", "certificates"},
            "epc_certificate": {"energy", "performance", "epc"},
            "geotechnical_records": {"geotechnical", "survey", "soil"},
        }
        wanted = keyword_map.get(slot.slot_key, set()) | (slot_key_tokens - {"", "cert", "certs"})
        overlap = wanted & title_tokens
        if overlap:
            score += min(0.35, 0.12 * len(overlap))
            reasons.append("name keyword match")

        # Prefer current, published / approved revisions.
        if getattr(doc, "is_current_revision", None) is not False:
            score += 0.05
        if (getattr(doc, "cde_state", "") or "").lower() == "published":
            score += 0.1
            reasons.append("published revision")

        return score, ", ".join(reasons) if reasons else "weak match"

    # ── Build (idempotent background job) ────────────────────────────────

    def _slot_revision_hash(self, slots: list[CloseoutSlot], bindings: dict[uuid.UUID, CloseoutBinding]) -> str:
        """Stable hash of the slot+binding state for the idempotency key.

        Re-clicking Build with no changes yields the same hash and therefore
        the same JobRun (idempotent). Any bind / verify / slot change shifts
        the hash and triggers a fresh build.
        """
        parts: list[str] = []
        for slot in sorted(slots, key=lambda s: str(s.id)):
            binding = bindings.get(slot.id)
            parts.append(
                "|".join(
                    [
                        str(slot.id),
                        slot.slot_key,
                        str(slot.is_required),
                        slot.source_kind,
                        slot.generated_artifact or "",
                        str(binding.document_id) if binding and binding.document_id else "",
                        binding.external_url or "" if binding else "",
                        str(binding.is_verified) if binding else "0",
                    ]
                )
            )
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        return digest[:16]

    async def build_package(self, package: CloseoutPackage) -> Any:
        """Submit the idempotent ZIP build job and return the JobRun.

        Re-clicking Build with no slot / binding changes returns the same
        JobRun via the idempotency key.
        """
        slots = await self.repo.list_slots(package.id)
        bindings = await self.repo.list_bindings_for_package(package.id)
        rev = self._slot_revision_hash(slots, bindings)
        job = await submit_job(
            JOB_KIND,
            {"package_id": str(package.id), "project_id": str(package.project_id)},
            idempotency_key=f"closeout-build:{package.id}:{rev}",
        )
        # Stamp the in-flight job id so the UI can poll without re-deriving it.
        package.last_built_job_id = job.id
        self.session.add(package)
        await self.session.commit()
        return job

    async def _build_zip_blob(self, package: CloseoutPackage) -> tuple[bytes, dict[str, Any]]:
        """Assemble the closeout ZIP and return ``(zip_bytes, build_summary)``.

        ZIP layout:
            cover.pdf
            manifest.json                     machine-readable index + completeness
            index.json                        sha256 + size per binary
            documents/<slot_key>/<file>       bound CDE documents (local uploads)
            generated/cobie_asset_register.xlsx
            generated/punch_closure_report.pdf
            generated/final_inspection_certificates.pdf
            README.md

        Degrades gracefully: missing files / a model-less project / a render
        failure are recorded in the manifest and never abort the export.
        """
        slots = await self.repo.list_slots(package.id)
        bindings = await self.repo.list_bindings_for_package(package.id)
        project_name = await self._project_name(package.project_id)

        date_iso = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        uploads_root = Path("uploads").resolve()

        documents: list[tuple[str, bytes]] = []
        generated: list[tuple[str, bytes]] = []
        index: list[dict[str, Any]] = []
        slot_summaries: list[dict[str, Any]] = []
        notes: list[str] = []

        # ── Bound CDE documents (local uploads only) ─────────────────────
        for slot in slots:
            binding = bindings.get(slot.id)
            evidence_label = "-"
            arc_paths: list[str] = []
            if binding is not None:
                if binding.document_id is not None:
                    arc, data, label = await self._read_document_blob(binding.document_id, slot, uploads_root)
                    evidence_label = label
                    if arc and data is not None:
                        documents.append((arc, data))
                        arc_paths.append(arc)
                    else:
                        notes.append(f"{slot.slot_key}: document {binding.document_id} not available as a local file")
                elif binding.external_url:
                    evidence_label = f"external: {binding.external_url}"
                    notes.append(f"{slot.slot_key}: external reference {binding.external_url}")

            slot_summaries.append(
                {
                    "slot_key": slot.slot_key,
                    "title": slot.title,
                    "category": slot.category,
                    "is_required": bool(slot.is_required),
                    "source_kind": slot.source_kind,
                    "generated_artifact": slot.generated_artifact,
                    "status": self._slot_status(slot, binding, has_built=True),
                    "evidence": evidence_label,
                    "verified_at": binding.verified_at if binding else None,
                    "files": arc_paths,
                }
            )

        # ── Generated artifacts ──────────────────────────────────────────
        wants = {s.generated_artifact for s in slots if s.source_kind == "generated"}
        if "cobie_xlsx" in wants:
            blob = await self._render_cobie(package.project_id, notes)
            if blob is not None:
                generated.append(("generated/cobie_asset_register.xlsx", blob))
        if "punch_closure_report" in wants:
            try:
                punch_blob = await self._render_punch_report(package.project_id)
                generated.append(("generated/punch_closure_report.pdf", punch_blob))
            except Exception as exc:  # noqa: BLE001 - never abort the export
                notes.append(f"punch closure report not generated ({exc.__class__.__name__})")
        if "inspection_cert_pdf" in wants:
            blob = await self._render_inspection_certs(package.project_id, notes)
            if blob is not None:
                generated.append(("generated/final_inspection_certificates.pdf", blob))

        # The build is producing the generated artifacts right now, so report
        # them as present for this package's own cover / manifest readiness.
        # The completeness numbers must use the same treat_built=True basis as
        # the ready flag, otherwise the cover / manifest contradict themselves
        # (generated required slots present for ready, absent for the percent).
        # The persisted package row was last recomputed with has_built=False,
        # so we derive consistent counts locally here instead of reading it.
        required_slots = [s for s in slots if s.is_required]
        required_count = len(required_slots)
        delivered_count = 0
        for slot in required_slots:
            st = self._slot_status(slot, bindings.get(slot.id), has_built=True)
            if st == "verified" or (slot.source_kind == "generated" and slot.generated_artifact in _GENERATED_KINDS):
                delivered_count += 1
        completeness_pct = 100 if required_count == 0 else round(delivered_count * 100 / required_count)

        gaps = await self.gaps(package, treat_built=True)
        ready = len(gaps) == 0 and required_count > 0

        # ── Cover PDF ────────────────────────────────────────────────────
        cover_summary = {
            "project_name": project_name,
            "project_type": package.project_type,
            "title": package.title,
            "completeness_pct": completeness_pct,
            "required_slot_count": required_count,
            "delivered_slot_count": delivered_count,
            "ready": ready,
            "gaps": gaps,
            "slots": slot_summaries,
            "built_at": date_iso,
        }
        cover_pdf: bytes | None = None
        try:
            cover_pdf = render_cover_pdf(cover_summary)
        except Exception as exc:  # noqa: BLE001 - never abort the export
            logger.warning("closeout: cover PDF render failed for package %s: %s", package.id, exc)
            notes.append(f"cover.pdf not generated ({exc.__class__.__name__})")

        # ── Machine-readable manifest ────────────────────────────────────
        manifest_obj = {
            "format_version": "1.0",
            "kind": "construction_closeout_package",
            "package_id": str(package.id),
            "project_id": str(package.project_id),
            "project_name": project_name,
            "project_type": package.project_type,
            "generated": date_iso,
            "completeness": {
                "required_slot_count": required_count,
                "delivered_slot_count": delivered_count,
                "completeness_pct": completeness_pct,
                "ready": ready,
                "gaps": gaps,
            },
            "slots": slot_summaries,
            "contents": {
                "documents": [arc for arc, _ in documents],
                "generated": [arc for arc, _ in generated],
                "cover": "cover.pdf" if cover_pdf is not None else None,
            },
            "notes": notes,
        }

        # ── Assemble the ZIP (bundle_export.py pattern) ──────────────────
        buf = io.BytesIO()
        total_bytes = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if cover_pdf is not None:
                zf.writestr("cover.pdf", cover_pdf)
                index.append(self._index_entry("cover.pdf", cover_pdf))
                total_bytes += len(cover_pdf)
            for arc, data in documents + generated:
                zf.writestr(arc, data)
                index.append(self._index_entry(arc, data))
                total_bytes += len(data)
            zf.writestr("index.json", json.dumps(index, indent=2, ensure_ascii=False))
            zf.writestr("manifest.json", json.dumps(manifest_obj, indent=2, ensure_ascii=False))
            zf.writestr("README.md", self._readme_md(project_name, package, completeness_pct, ready, gaps))

        build_summary = {
            "size_bytes": total_bytes,
            "completeness_pct": completeness_pct,
            "ready": ready,
            "document_count": len(documents),
            "generated_count": len(generated),
            "notes": notes,
        }
        return buf.getvalue(), build_summary

    @staticmethod
    def _index_entry(arc: str, data: bytes) -> dict[str, Any]:
        return {
            "path": arc,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    @staticmethod
    def _readme_md(
        project_name: str,
        package: CloseoutPackage,
        completeness_pct: int,
        ready: bool,
        gaps: list[str],
    ) -> str:
        lines = [
            "# Digital handover and closeout package",
            "",
            f"Project: {project_name}",
            f"Project type: {package.project_type}",
            f"Completeness: {completeness_pct}%",
            f"Status: {'READY' if ready else 'INCOMPLETE'}",
            "",
            "See manifest.json for the machine-readable index, cover.pdf for the",
            "completeness summary, documents/ for bound evidence and generated/",
            "for the COBie asset register, punch-closure report and final",
            "inspection certificates.",
            "",
        ]
        if gaps:
            lines.append("## Outstanding required items")
            lines.extend(f"- {g}" for g in gaps)
            lines.append("")
        return "\n".join(lines)

    # ── Generated-artifact renderers (best-effort) ───────────────────────

    async def _read_document_blob(
        self,
        document_id: uuid.UUID,
        slot: CloseoutSlot,
        uploads_root: Path,
    ) -> tuple[str | None, bytes | None, str]:
        """Resolve a bound document to (arc_path, bytes, label) safely.

        Path-traversal-safe local-upload copy mirroring property_dev export.
        External / missing files return ``(None, None, label)``.
        """
        from app.modules.documents.models import Document

        doc = await self.session.get(Document, document_id)
        if doc is None:
            return None, None, f"document {document_id} (deleted)"
        label = doc.name or str(document_id)
        raw = (doc.file_path or "").strip()
        if not raw:
            return None, None, label
        if raw.lower().startswith(("http://", "https://")):
            return None, None, f"{label} (external)"
        rel = raw.lstrip("/")
        if rel.startswith("uploads/"):
            rel = rel[len("uploads/") :]
        candidate = (uploads_root / rel).resolve()
        try:
            inside = candidate.is_relative_to(uploads_root)
        except AttributeError:  # pragma: no cover - py<3.9 guard
            inside = str(candidate).startswith(str(uploads_root))
        if not inside or not candidate.is_file():
            return None, None, f"{label} (file missing)"
        try:
            data = candidate.read_bytes()
        except OSError:
            return None, None, f"{label} (unreadable)"
        leaf = f"documents/{_safe_zip_name(slot.slot_key)}/{_safe_zip_name(candidate.name, 'document')}"
        return leaf, data, label

    async def _render_cobie(self, project_id: uuid.UUID, notes: list[str]) -> bytes | None:
        """Render a COBie asset-register workbook for the project's BIM model.

        Degrades to a manifest note if the project has no BIM model.
        """
        try:
            from app.modules.bim_hub.exporters.cobie import build_cobie_workbook
            from app.modules.bim_hub.models import BIMElement, BIMModel
        except Exception as exc:  # noqa: BLE001
            notes.append(f"COBie skipped (bim_hub unavailable: {exc.__class__.__name__})")
            return None

        model = (
            (
                await self.session.execute(
                    select(BIMModel).where(BIMModel.project_id == project_id).order_by(BIMModel.created_at.desc()),
                )
            )
            .scalars()
            .first()
        )
        if model is None:
            notes.append("COBie skipped (project has no BIM model)")
            return None
        elements = list(
            (await self.session.execute(select(BIMElement).where(BIMElement.model_id == model.id))).scalars().all()
        )
        try:
            return build_cobie_workbook(model, elements)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"COBie not generated ({exc.__class__.__name__})")
            return None

    async def _render_punch_report(self, project_id: uuid.UUID) -> bytes:
        """Render a punch / snag closure report PDF from punchlist items."""
        from app.modules.punchlist.models import PunchItem

        items = list(
            (await self.session.execute(select(PunchItem).where(PunchItem.project_id == project_id))).scalars().all()
        )
        total = len(items)
        closed = sum(1 for it in items if (it.status or "").lower() in ("closed", "verified"))
        rows = [
            {
                "title": it.title,
                "status": "verified" if (it.verified_at or it.status == "verified") else (it.status or "open"),
                "evidence": (it.resolution_notes or "")[:120] or "-",
                "verified_at": str(it.verified_at) if it.verified_at else "-",
            }
            for it in items
        ]
        summary = {
            "project_name": "Punch / snag closure",
            "project_type": "punch_closure",
            "title": "Punch and snag closure evidence",
            "completeness_pct": 100 if total == 0 else round(closed * 100 / total),
            "required_slot_count": total,
            "delivered_slot_count": closed,
            "ready": total == closed,
            "gaps": [it.title for it in items if (it.status or "").lower() not in ("closed", "verified")][:50],
            "slots": rows,
        }
        return render_cover_pdf(summary)

    async def _render_inspection_certs(self, project_id: uuid.UUID, notes: list[str]) -> bytes | None:
        """Render a final-inspection certificate PDF from passed inspections."""
        try:
            from app.modules.inspections.models import QualityInspection
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Inspection certificate skipped ({exc.__class__.__name__})")
            return None
        inspections = list(
            (
                await self.session.execute(
                    select(QualityInspection).where(QualityInspection.project_id == project_id),
                )
            )
            .scalars()
            .all()
        )
        passed = [i for i in inspections if (i.result or "").lower() == "pass"]
        rows = [
            {
                "title": f"{i.inspection_number} {i.title}",
                "status": "verified" if (i.result or "").lower() == "pass" else (i.status or "scheduled"),
                "evidence": i.inspection_type or "-",
                "verified_at": i.inspection_date or "-",
            }
            for i in inspections
        ]
        summary = {
            "project_name": "Final inspection certificates",
            "project_type": "inspection",
            "title": "Final inspection certificates",
            "completeness_pct": 100 if not inspections else round(len(passed) * 100 / len(inspections)),
            "required_slot_count": len(inspections),
            "delivered_slot_count": len(passed),
            "ready": len(passed) == len(inspections) and bool(inspections),
            "gaps": [f"{i.inspection_number} {i.title}" for i in inspections if (i.result or "").lower() != "pass"][
                :50
            ],
            "slots": rows,
        }
        return render_cover_pdf(summary)

    async def _project_name(self, project_id: uuid.UUID) -> str:
        try:
            from app.modules.projects.repository import ProjectRepository

            project = await ProjectRepository(self.session).get_by_id(project_id)
            return getattr(project, "name", None) or str(project_id)
        except Exception:  # noqa: BLE001
            return str(project_id)

    # ── Freshness ────────────────────────────────────────────────────────

    async def _mark_stale(self, package: CloseoutPackage) -> None:
        """Clear the built-package stamp so the UI prompts a rebuild.

        Called after any slot / binding mutation. Does not touch storage; the
        previously built ZIP key is cleared so download 409s until rebuilt.
        """
        if package.package_key is None and package.last_built_at is None:
            return
        package.package_key = None
        package.last_built_at = None
        package.last_built_job_id = None
        if package.status == "issued":
            package.status = "in_progress"
        self.session.add(package)
        await self.session.flush()
