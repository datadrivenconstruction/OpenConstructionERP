# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Handover dossier: check, assemble, file, deliver, resend.

One action from the closeout page: the package is checked against its dossier
checklist (validation rules), assembled for a scope (whole project, one area,
one asset) into an index PDF plus a ZIP, filed in Documents, and delivered.

Nothing here duplicates the closeout package build. The bound documents, the
generated COBie / punch closure / inspection artifacts and the completeness
counts come from :meth:`CloseoutService._collect_package`; this service adds
the parts a recipient needs on top: the resolved punch items with their photos
and evidence records, a commissioning certificate from the commissioning
module, the signing state of the acceptance certificate, and the index.

Delivery reuses what the platform already has: a documents share link (expiring,
optionally password protected) is the payload, sent through an integrations
webhook endpoint, a chat connector, or e-mail; a plain download is logged too.
Every attempt is a :class:`CloseoutDelivery` row, and a resend repeats an
attempt against the same archive without rebuilding it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale, t
from app.core.json_merge import merge_metadata
from app.core.storage import module_uploads_dir
from app.modules.closeout import dossier as dz
from app.modules.closeout.models import CloseoutDelivery, CloseoutDossier, CloseoutPackage
from app.modules.closeout.service import _GENERATED_KINDS, CloseoutService, _safe_zip_name

logger = logging.getLogger(__name__)

JOB_KIND = "closeout.dossier"

#: Punch statuses at which the work is claimed done.
_PUNCH_DONE = frozenset({"resolved", "verified", "closed"})
#: Integration types that can carry a dossier link (they have a send helper).
CHAT_CONNECTOR_TYPES = ("slack", "teams", "telegram", "discord", "whatsapp")
#: Most photos one punch item contributes to a dossier.
_MAX_PHOTOS_PER_ITEM = 20

_PDF_LABEL_KEYS = (
    "title",
    "scope",
    "built",
    "status_passed",
    "status_warnings",
    "status_errors",
    "findings",
    "severity",
    "finding",
    "severity_error",
    "severity_warning",
    "severity_info",
    "contents",
    "file",
    "size",
    "punch",
    "item",
    "status",
    "photos",
    "evidence",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def dossier_dir(project_id: uuid.UUID) -> Path:
    """Where dossier archives of a project are filed (under the uploads root)."""
    return module_uploads_dir("closeout", "dossiers", str(project_id))


def pdf_labels(locale: str | None) -> dict[str, str]:
    """Translated labels for the index PDF."""
    return {key: t(f"closeout_dossier.pdf.{key}", locale) for key in _PDF_LABEL_KEYS}


class DossierService:
    """Stateless service for handover dossiers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.closeout = CloseoutService(session)

    # ── Checklist configuration ──────────────────────────────────────────

    def get_config(self, package: CloseoutPackage) -> dict[str, Any]:
        """The package's dossier checklist (defaults filled in)."""
        return dz.normalise_config((package.metadata_ or {}).get("dossier"))

    async def set_config(self, package: CloseoutPackage, raw: dict[str, Any]) -> dict[str, Any]:
        """Replace the package's dossier checklist with a normalised copy."""
        cfg = dz.normalise_config({**self.get_config(package), **(raw or {})})
        package.metadata_ = merge_metadata(package.metadata_ or {}, {"dossier": cfg})
        self.session.add(package)
        await self.session.flush()
        return cfg

    # ── Check context (what the rules read) ──────────────────────────────

    async def _punch_in_scope(self, project_id: uuid.UUID, scope: dict[str, Any]) -> list[Any]:
        try:
            from app.modules.punchlist.models import PunchItem
        except Exception:  # noqa: BLE001 - punch list module absent
            return []
        rows = (await self.session.execute(select(PunchItem).where(PunchItem.project_id == project_id))).scalars().all()
        out = []
        for it in rows:
            meta = it.metadata_ if isinstance(it.metadata_, dict) else {}
            refs = (meta.get("asset_ref"), meta.get("plant_item_id"), meta.get("bim_element_id"))
            if dz.matches_scope(scope, area=meta.get("area") or meta.get("location"), asset_refs=refs):
                out.append(it)
        return out

    async def _systems_in_scope(self, project_id: uuid.UUID, scope: dict[str, Any]) -> list[Any]:
        try:
            from app.modules.commissioning.models import CxSystem
        except Exception:  # noqa: BLE001 - commissioning module absent
            return []
        rows = (await self.session.execute(select(CxSystem).where(CxSystem.project_id == project_id))).scalars().all()
        return [
            s for s in rows if dz.matches_scope(scope, area=s.location, asset_refs=(s.plant_item_id, s.tag, str(s.id)))
        ]

    async def _signing_state(self, project_id: uuid.UUID, document_id: uuid.UUID) -> str | None:
        """Best status of the signing sessions that reference this document."""
        try:
            from app.modules.signing.models import SigningSession
        except Exception:  # noqa: BLE001 - signing module absent
            return None
        rows = (
            await self.session.execute(
                select(SigningSession.status, SigningSession.document_ref).where(
                    SigningSession.project_id == project_id
                )
            )
        ).all()
        doc = str(document_id).lower()
        statuses = [str(st or "") for st, ref in rows if doc in str(ref or "").lower()]
        if not statuses:
            return None
        order = ["fully_signed", "partially_signed", "awaiting_signatures", "draft", "declined", "expired"]
        return min(statuses, key=lambda st: order.index(st) if st in order else len(order))

    async def check_context(self, package: CloseoutPackage, scope: dict[str, Any]) -> dict[str, Any]:
        """Build the plain dict the dossier rules validate."""
        cfg = self.get_config(package)
        slots = await self.closeout.repo.list_slots(package.id)
        bindings = await self.closeout.repo.list_bindings_for_package(package.id)
        systems = await self._systems_in_scope(package.project_id, scope)

        categories: dict[str, dict[str, Any]] = {}
        acceptance: dict[str, Any] = {"bound": False, "signed": False, "signing_status": None}
        for slot in slots:
            binding = bindings.get(slot.id)
            state = categories.setdefault(slot.category, {"present": False, "verified": True, "titles": []})
            state["titles"].append(slot.title)
            generated = slot.source_kind == "generated" and slot.generated_artifact in _GENERATED_KINDS
            if binding is not None or generated:
                state["present"] = True
                if binding is not None and not binding.is_verified:
                    state["verified"] = False
            if slot.category == dz.CATEGORY_ACCEPTANCE and binding is not None:
                acceptance["bound"] = True
                if binding.document_id is not None:
                    st = await self._signing_state(package.project_id, binding.document_id)
                    acceptance["signing_status"] = st
                    acceptance["signed"] = acceptance["signed"] or st == "fully_signed"
                else:
                    acceptance["signing_status"] = acceptance["signing_status"] or "external"
        if systems:
            state = categories.setdefault("commissioning", {"present": False, "verified": True, "titles": []})
            state["present"] = True
        for state in categories.values():
            if not state["present"]:
                state["verified"] = False

        punch = await self._punch_in_scope(package.project_id, scope)
        open_items = [{"id": str(p.id), "title": p.title} for p in punch if (p.status or "") not in _PUNCH_DONE]
        no_photo = [
            {"id": str(p.id), "title": p.title} for p in punch if (p.status or "") in _PUNCH_DONE and not p.photos
        ]

        critical = 0
        pending = [{"id": str(s.id), "name": s.name} for s in systems if (s.status or "") != "commissioned"]
        if systems:
            try:
                from app.modules.commissioning.repository import CxSystemRepository

                counts = await CxSystemRepository(self.session).open_critical_issue_counts([s.id for s in systems])
                critical = sum(counts.values())
            except Exception:  # noqa: BLE001 - advisory only
                logger.debug("dossier: critical issue count failed", exc_info=True)

        return {
            "scope": scope,
            "config": cfg,
            "categories": categories,
            "punch": {"total": len(punch), "open": open_items, "without_photo": no_photo},
            "commissioning": {"systems": len(systems), "pending": pending, "open_critical_issues": critical},
            "acceptance": acceptance,
        }

    async def run_checks(
        self, package: CloseoutPackage, scope: dict[str, Any], locale: str | None = None
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """Validate the dossier; returns ``(status, failed_results, context)``."""
        from app.core.validation.engine import validation_engine

        context = await self.check_context(package, scope)
        report = await validation_engine.validate(
            data=context,
            rule_sets=[dz.DOSSIER_RULE_SET],
            target_type="closeout_dossier",
            target_id=str(package.id),
            project_id=str(package.project_id),
            metadata={"locale": locale or get_locale()},
        )
        failed = [
            {
                "rule_id": r.rule_id,
                "severity": str(r.severity),
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }
            for r in report.results
            if not r.passed and not r.is_engine_error
        ]
        severities = {f["severity"] for f in failed}
        state = "errors" if "error" in severities else "warnings" if failed else "passed"
        return state, failed, context

    # ── Request (queue the build) ────────────────────────────────────────

    async def request(
        self,
        package: CloseoutPackage,
        *,
        scope: dict[str, Any],
        deliveries: list[dict[str, Any]],
        allow_incomplete: bool,
        requested_by: str | None,
        locale: str | None = None,
    ) -> CloseoutDossier:
        """Check, then queue the assembly (and the deliveries that follow it).

        Raises 409 with the findings when the checklist has errors and
        ``allow_incomplete`` is not set.
        """
        for entry in deliveries:
            await self.validate_target(package.project_id, entry, requested_by)
        check_status, failed, _context = await self.run_checks(package, scope, locale)
        if check_status == "errors" and not allow_incomplete:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": t("closeout_dossier.blocked", locale),
                    "check_status": check_status,
                    "results": failed,
                },
            )
        dossier = CloseoutDossier(
            package_id=package.id,
            project_id=package.project_id,
            status="queued",
            scope=scope,
            check_status=check_status,
            check_results=failed,
            delivery_request=deliveries,
            requested_by=requested_by,
            metadata_={"allow_incomplete": bool(allow_incomplete), "locale": locale or get_locale()},
        )
        self.session.add(dossier)
        await self.session.flush()
        return dossier

    async def validate_target(self, project_id: uuid.UUID, entry: dict[str, Any], user_id: str | None) -> None:
        """Reject a delivery target that does not exist or is not usable for this project."""
        channel = entry.get("channel")
        if channel not in dz.DELIVERY_CHANNELS:
            raise HTTPException(status_code=422, detail=f"Unknown delivery channel {channel!r}")
        if channel == "email":
            recipient = str(entry.get("recipient") or "")
            if "@" not in recipient or len(recipient) > 320:
                raise HTTPException(status_code=422, detail="A valid recipient e-mail address is required")
            return
        if channel == "download":
            return
        target = _as_uuid(entry.get("target_id"))
        if target is None:
            raise HTTPException(status_code=422, detail="A delivery target is required")
        if channel == "webhook":
            from app.modules.integrations.models import WebhookEndpoint

            hook = await self.session.get(WebhookEndpoint, target)
            if hook is None or not hook.is_active or not _usable(hook.project_id, hook.user_id, project_id, user_id):
                raise HTTPException(status_code=404, detail="Webhook endpoint not found")
        else:
            from app.modules.integrations.models import IntegrationConfig

            cfg = await self.session.get(IntegrationConfig, target)
            if cfg is None or not cfg.is_active or not _usable(cfg.project_id, cfg.user_id, project_id, user_id):
                raise HTTPException(status_code=404, detail="Connector not found")

    # ── Assemble ─────────────────────────────────────────────────────────

    async def build(self, dossier: CloseoutDossier) -> CloseoutDossier:
        """Assemble the dossier archive, file it in Documents and stamp the row."""
        package = await self.closeout.get_package_or_404(dossier.package_id)
        locale = (dossier.metadata_ or {}).get("locale")
        scope = dossier.scope or {"kind": "project", "value": None}
        parts = await self.closeout._collect_package(package)
        members: list[tuple[str, bytes]] = list(parts["documents"]) + list(parts["generated"])
        notes: list[str] = list(parts["notes"])

        punch_rows, punch_members, register = await self._punch_members(package.project_id, scope)
        members.extend(punch_members)
        if register:
            members.append(("punch/register.json", json.dumps(register, indent=2, ensure_ascii=False).encode()))
        cx_pdf = await self._commissioning_pdf(package.project_id, scope, notes)
        if cx_pdf is not None:
            members.append(("generated/commissioning_certificates.pdf", cx_pdf))

        file_index = [CloseoutService._index_entry(arc, data) for arc, data in members]
        built_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        index_summary = {
            "labels": pdf_labels(locale),
            "title": package.title,
            "project_name": parts["project_name"],
            "scope_label": dz.scope_label(scope),
            "built_at": built_at,
            "check_status": dossier.check_status or "passed",
            "findings": [
                {"severity": f.get("severity"), "message": f.get("message")} for f in dossier.check_results or []
            ],
            "files": file_index,
            "punch": punch_rows,
        }
        from app.modules.closeout.dossier_pdf import render_dossier_index_pdf

        index_pdf = await asyncio.to_thread(render_dossier_index_pdf, index_summary)
        manifest = {
            "format_version": "1.0",
            "kind": "construction_handover_dossier",
            "dossier_id": str(dossier.id),
            "package_id": str(package.id),
            "project_id": str(package.project_id),
            "project_name": parts["project_name"],
            "scope": scope,
            "generated": built_at,
            "checks": {"status": dossier.check_status, "findings": dossier.check_results or []},
            "completeness": {
                "required_slot_count": parts["required_count"],
                "delivered_slot_count": parts["delivered_count"],
                "completeness_pct": parts["completeness_pct"],
                "gaps": parts["gaps"],
            },
            "slots": parts["slot_summaries"],
            "punch_items": len(register),
            "notes": notes,
        }
        readme = "\n".join(
            [
                f"# {package.title}",
                "",
                f"{parts['project_name']} - {dz.scope_label(scope)}",
                "",
                "index.pdf      contents, checklist findings and punch register",
                "manifest.json  machine-readable description of this dossier",
                "index.json     size and SHA-256 of every file",
                "",
            ]
        )
        index: list[dict[str, Any]] = []
        zip_bytes, _total = await asyncio.to_thread(
            CloseoutService._assemble_zip, index_pdf, members, index, manifest, readme, "index.pdf"
        )

        name = f"handover_dossier_{dz.scope_slug(scope)}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
        target_dir = dossier_dir(package.project_id)
        path = target_dir / name

        def _write() -> None:
            target_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(zip_bytes)

        await asyncio.to_thread(_write)
        document_id = await self._file_document(package, dossier, path, name, len(zip_bytes))
        dossier.file_path = str(path)
        dossier.file_name = name
        dossier.sha256 = hashlib.sha256(zip_bytes).hexdigest()
        dossier.size_bytes = len(zip_bytes)
        dossier.file_count = len(members) + 1
        dossier.document_id = document_id
        dossier.built_at = _now_iso()
        dossier.status = "built"
        dossier.error = None
        self.session.add(dossier)
        await self.session.flush()
        return dossier

    async def _file_document(
        self, package: CloseoutPackage, dossier: CloseoutDossier, path: Path, name: str, size: int
    ) -> uuid.UUID | None:
        """File the archive as a project document so it can be shared and found."""
        try:
            from app.modules.documents.models import Document

            async with self.session.begin_nested():
                doc = Document(
                    project_id=package.project_id,
                    name=name,
                    description=f"{package.title} - {dz.scope_label(dossier.scope or {})}",
                    category="other",
                    file_size=size,
                    mime_type="application/zip",
                    file_path=str(path),
                    version=1,
                    uploaded_by=dossier.requested_by or "",
                    tags=["closeout", "handover_dossier"],
                    metadata_={"closeout_dossier_id": str(dossier.id), "package_id": str(package.id)},
                )
                self.session.add(doc)
                await self.session.flush()
            return doc.id
        except Exception:  # noqa: BLE001 - the archive stays downloadable from the dossier
            logger.exception("dossier %s: filing the archive in Documents failed", dossier.id)
            return None

    async def _punch_members(
        self, project_id: uuid.UUID, scope: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[tuple[str, bytes]], list[dict[str, Any]]]:
        """Resolved punch items in scope: index rows, photo members, register entries."""
        try:
            from app.modules.punchlist.service import PHOTO_EVIDENCE_KEY, _resolve_photo_path, evidence_caption
        except Exception:  # noqa: BLE001
            return [], [], []
        items = [p for p in await self._punch_in_scope(project_id, scope) if (p.status or "") in _PUNCH_DONE]
        rows: list[dict[str, Any]] = []
        register: list[dict[str, Any]] = []
        wanted: list[tuple[str, str]] = []
        for it in items:
            meta = it.metadata_ if isinstance(it.metadata_, dict) else {}
            records = meta.get(PHOTO_EVIDENCE_KEY) if isinstance(meta.get(PHOTO_EVIDENCE_KEY), dict) else {}
            code = meta.get("code") or str(it.id)[:8]
            folder = f"punch/{_safe_zip_name(str(code))}_{_safe_zip_name(it.title, 'item')[:40]}"
            photos_out = []
            first_line = ""
            for path in list(it.photos or [])[:_MAX_PHOTOS_PER_ITEM]:
                arc = f"{folder}/{_safe_zip_name(Path(path).name, 'photo')}"
                record = records.get(path) if isinstance(records, dict) else None
                wanted.append((path, arc))
                photos_out.append({"file": arc, "evidence": record})
                if not first_line and isinstance(record, dict):
                    first_line = evidence_caption(record)
            register.append(
                {
                    "id": str(it.id),
                    "code": meta.get("code"),
                    "title": it.title,
                    "status": it.status,
                    "priority": it.priority,
                    "category": it.category,
                    "trade": it.trade,
                    "resolution_notes": it.resolution_notes,
                    "resolved_at": str(it.resolved_at) if it.resolved_at else None,
                    "verified_at": str(it.verified_at) if it.verified_at else None,
                    "verified_by": it.verified_by,
                    "geo": {"lat": it.geo_lat, "lon": it.geo_lon} if it.geo_lat is not None else None,
                    "photos": photos_out,
                }
            )
            rows.append(
                {"title": it.title, "status": it.status, "photos": len(it.photos or []), "evidence": first_line}
            )

        def _read() -> list[tuple[str, bytes]]:
            out: list[tuple[str, bytes]] = []
            for path, arc in wanted:
                disk = _resolve_photo_path(path)
                if disk is None:
                    continue
                try:
                    out.append((arc, disk.read_bytes()))
                except OSError:
                    continue
            return out

        return rows, await asyncio.to_thread(_read), register

    async def _commissioning_pdf(self, project_id: uuid.UUID, scope: dict[str, Any], notes: list[str]) -> bytes | None:
        """Commissioning certificate of the systems in scope (same layout as the closeout reports)."""
        systems = await self._systems_in_scope(project_id, scope)
        if not systems:
            return None
        try:
            from app.modules.closeout.cover_pdf import render_cover_pdf
            from app.modules.commissioning.service import CommissioningService

            readiness = await CommissioningService(self.session).readiness_map([s.id for s in systems])
        except Exception as exc:  # noqa: BLE001
            notes.append(f"commissioning certificate skipped ({exc.__class__.__name__})")
            return None
        done = [s for s in systems if (s.status or "") == "commissioned"]
        rows = [
            {
                "title": f"{s.tag + ' ' if s.tag else ''}{s.name}",
                "status": "verified" if (s.status or "") == "commissioned" else (s.status or "not_started"),
                "evidence": f"{s.system_type} - {round(float((readiness.get(s.id) or {}).get('readiness_pct', 0)))}%",
                "verified_at": s.commissioned_at or "-",
            }
            for s in systems
        ]
        summary = {
            "project_name": "Commissioning certificates",
            "project_type": "commissioning",
            "title": "Test and commissioning certificates",
            "completeness_pct": round(len(done) * 100 / len(systems)),
            "required_slot_count": len(systems),
            "delivered_slot_count": len(done),
            "ready": len(done) == len(systems),
            "gaps": [s.name for s in systems if s not in done][:50],
            "slots": rows,
        }
        return await asyncio.to_thread(render_cover_pdf, summary)

    # ── Delivery ─────────────────────────────────────────────────────────

    async def deliver(
        self,
        dossier: CloseoutDossier,
        entry: dict[str, Any],
        *,
        delivered_by: str | None,
        resend_of: uuid.UUID | None = None,
    ) -> CloseoutDelivery:
        """Deliver a built dossier through one channel and log the attempt."""
        if dossier.status not in ("built", "delivered") or not dossier.file_path:
            raise HTTPException(status_code=409, detail="Dossier is not built yet")
        channel = str(entry.get("channel") or "download")
        delivery = CloseoutDelivery(
            dossier_id=dossier.id,
            project_id=dossier.project_id,
            channel=channel,
            target_id=str(entry.get("target_id") or "") or None,
            recipient=entry.get("recipient"),
            status="pending",
            resend_of=resend_of,
            delivered_by=delivered_by,
            metadata_={"message": (entry.get("message") or "")[:2000]},
        )
        self.session.add(delivery)
        await self.session.flush()

        if channel == "download":
            delivery.status = "sent"
            delivery.delivered_at = _now_iso()
            delivery.target_label = "download"
            await self.session.flush()
            return delivery

        try:
            share_url, link_id, expires = await self._share_link(dossier, entry, delivered_by)
            delivery.share_url = share_url
            delivery.share_link_id = link_id
            delivery.share_expires_at = expires
            ok, code, label, detail = await self._send(dossier, delivery, entry, share_url, expires)
        except HTTPException as exc:
            ok, code, label, detail = False, exc.status_code, None, str(exc.detail)[:1000]
        except Exception as exc:  # noqa: BLE001 - the log row records the failure
            logger.warning("dossier %s: %s delivery failed: %s", dossier.id, channel, exc)
            ok, code, label, detail = False, None, None, f"{exc.__class__.__name__}: {exc}"[:1000]
        delivery.status = "sent" if ok else "failed"
        delivery.status_code = code
        delivery.target_label = label
        delivery.detail = detail
        delivery.delivered_at = _now_iso()
        if ok:
            dossier.status = "delivered"
        self.session.add(dossier)
        await self.session.flush()
        return delivery

    async def _share_link(
        self, dossier: CloseoutDossier, entry: dict[str, Any], user_id: str | None
    ) -> tuple[str, uuid.UUID | None, str | None]:
        """Mint an expiring documents share link for the archive."""
        from app.config import get_settings

        if dossier.document_id is None:
            raise HTTPException(status_code=409, detail="Dossier archive is not filed as a document")
        from app.modules.documents.share_service import _build_public_url, create_share_link

        package = await self.closeout.get_package_or_404(dossier.package_id)
        days = int(entry.get("expires_in_days") or self.get_config(package)["share_expires_in_days"])
        creator = _as_uuid(user_id) or _as_uuid(dossier.requested_by)
        if creator is None:
            raise HTTPException(status_code=422, detail="A user is required to share the dossier")
        link = await create_share_link(
            self.session,
            document_id=dossier.document_id,
            created_by=creator,
            password=entry.get("password") or None,
            expires_in_days=max(1, min(365, days)),
        )
        base = get_settings().resolved_frontend_url
        expires = link.expires_at.isoformat() if link.expires_at else None
        return f"{base}{_build_public_url(link.token)}", link.id, expires

    async def _send(
        self,
        dossier: CloseoutDossier,
        delivery: CloseoutDelivery,
        entry: dict[str, Any],
        share_url: str,
        expires: str | None,
    ) -> tuple[bool, int | None, str | None, str | None]:
        """Send through the chosen channel; returns ``(ok, status_code, label, detail)``."""
        package = await self.closeout.get_package_or_404(dossier.package_id)
        locale = (dossier.metadata_ or {}).get("locale")
        project_name = await self.closeout._project_name(package.project_id)
        scope = dz.scope_label(dossier.scope or {})
        title = t("closeout_dossier.delivery_title", locale, project=project_name)
        message = t("closeout_dossier.delivery_body", locale, title=package.title, scope=scope, expires=expires or "-")
        note = str(entry.get("message") or "").strip()
        if note:
            message = f"{message}\n\n{note}"
        if delivery.channel == "webhook":
            from app.modules.integrations.models import WebhookEndpoint
            from app.modules.integrations.service import WebhookService

            hook = await self.session.get(WebhookEndpoint, _as_uuid(delivery.target_id))
            if hook is None:
                return False, None, None, "webhook endpoint not found"
            payload = {
                "event": "closeout.dossier.delivered",
                "project_id": str(dossier.project_id),
                "project_name": project_name,
                "package_id": str(dossier.package_id),
                "dossier_id": str(dossier.id),
                "scope": dossier.scope,
                "check_status": dossier.check_status,
                "file_name": dossier.file_name,
                "sha256": dossier.sha256,
                "size_bytes": dossier.size_bytes,
                "file_count": dossier.file_count,
                "download_url": share_url,
                "expires_at": expires,
                "message": note or None,
            }
            # The webhook service commits its own delivery row; ours rides the same commit.
            sent = await WebhookService(self.session).deliver_to(hook, "closeout.dossier.delivered", payload)
            code = sent.status_code
            ok = code is not None and 200 <= code < 300
            return ok, code, hook.name, (sent.response_body or None)
        if delivery.channel == "connector":
            from app.modules.integrations.models import IntegrationConfig
            from app.modules.integrations.notification_bridge import send_connector_message

            cfg = await self.session.get(IntegrationConfig, _as_uuid(delivery.target_id))
            if cfg is None:
                return False, None, None, "connector not found"
            ok = await send_connector_message(cfg, title, message, share_url)
            return ok, None, f"{cfg.integration_type}: {cfg.name}", None if ok else "connector refused the message"
        if delivery.channel == "email":
            import html

            from app.modules.integrations.email_service import send_email

            body = (
                f"<p>{html.escape(message).replace(chr(10), '<br>')}</p>"
                f'<p><a href="{html.escape(share_url, quote=True)}">{html.escape(share_url)}</a></p>'
            )
            ok = await send_email(str(delivery.recipient), title, body)
            return ok, None, delivery.recipient, None if ok else "mail server refused the message"
        return False, None, None, f"unsupported channel {delivery.channel}"

    async def resend(self, delivery: CloseoutDelivery, *, delivered_by: str | None) -> CloseoutDelivery:
        """Repeat a delivery against the same archive (a fresh share link, a new log row)."""
        dossier = await self.get_dossier_or_404(delivery.dossier_id)
        entry = {
            "channel": delivery.channel,
            "target_id": delivery.target_id,
            "recipient": delivery.recipient,
            "message": (delivery.metadata_ or {}).get("message"),
        }
        return await self.deliver(dossier, entry, delivered_by=delivered_by, resend_of=delivery.id)

    # ── Reads ────────────────────────────────────────────────────────────

    async def get_dossier_or_404(self, dossier_id: uuid.UUID) -> CloseoutDossier:
        row = await self.session.get(CloseoutDossier, dossier_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Dossier not found")
        return row

    async def get_delivery_or_404(self, delivery_id: uuid.UUID) -> CloseoutDelivery:
        row = await self.session.get(CloseoutDelivery, delivery_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Delivery not found")
        return row

    async def list_dossiers(self, package_id: uuid.UUID, limit: int = 50) -> list[CloseoutDossier]:
        stmt = (
            select(CloseoutDossier)
            .where(CloseoutDossier.package_id == package_id)
            .order_by(CloseoutDossier.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_deliveries(self, dossier_ids: list[uuid.UUID]) -> list[CloseoutDelivery]:
        if not dossier_ids:
            return []
        stmt = (
            select(CloseoutDelivery)
            .where(CloseoutDelivery.dossier_id.in_(dossier_ids))
            .order_by(CloseoutDelivery.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


def _usable(owner_project: Any, owner_user: Any, project_id: uuid.UUID, user_id: str | None) -> bool:
    """A target is usable when scoped to this project, or global and owned by the requester."""
    if owner_project is not None:
        return str(owner_project) == str(project_id)
    return user_id is not None and str(owner_user) == str(user_id)


async def list_delivery_targets(
    session: AsyncSession, project_id: uuid.UUID, user_id: str | None
) -> list[dict[str, Any]]:
    """Webhook endpoints and chat connectors usable for this project's dossiers.

    Usable means active and either scoped to the project, or global and owned
    by the requester (the same rule :meth:`DossierService.validate_target` applies).
    """
    from sqlalchemy import and_, or_

    try:
        from app.modules.integrations.models import IntegrationConfig, WebhookEndpoint
    except Exception:  # noqa: BLE001 - integrations module absent
        return []
    uid = _as_uuid(user_id)
    out: list[dict[str, Any]] = []
    hooks = (
        await session.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.is_active.is_(True),
                or_(
                    WebhookEndpoint.project_id == project_id,
                    and_(WebhookEndpoint.project_id.is_(None), WebhookEndpoint.user_id == uid),
                ),
            )
        )
    ).scalars()
    out.extend({"id": h.id, "channel": "webhook", "name": h.name, "kind": None} for h in hooks)
    configs = (
        await session.execute(
            select(IntegrationConfig).where(
                IntegrationConfig.is_active.is_(True),
                IntegrationConfig.integration_type.in_(CHAT_CONNECTOR_TYPES),
                or_(
                    IntegrationConfig.project_id == project_id,
                    and_(IntegrationConfig.project_id.is_(None), IntegrationConfig.user_id == uid),
                ),
            )
        )
    ).scalars()
    out.extend({"id": c.id, "channel": "connector", "name": c.name, "kind": c.integration_type} for c in configs)
    return out
