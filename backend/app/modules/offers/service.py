"""Customer offer business logic.

An offer is an issued document, not an export mode. A draft is re-priced from the BOQ on every save;
from ``sent`` on it is frozen and a BOQ edit makes the next revision. Arithmetic lives in
:mod:`app.modules.offers.pricing`, market data in :mod:`app.modules.offers.pack`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.offers import pack as pack_mod
from app.modules.offers import pricing, validators
from app.modules.offers.models import Offer, OfferSettings, OfferTextBlock
from app.modules.offers.repository import OfferRepository
from app.modules.offers.schemas import (
    AcceptRequest,
    FindingOut,
    OfferCreate,
    OfferResponse,
    OfferSummary,
    OfferUpdate,
    SettingsUpdate,
    TextBlockIn,
    ValidationOut,
)

logger = logging.getLogger(__name__)

FALLBACK_PAYMENT_DAYS = 14
LUMP_SUM_UNITS = frozenset({"ls", "lsum", "lump sum", "psch", "pschl", "forfait", "ft", "gl", "global"})

_SECTION_OF_RULE = {
    "offer.customer_present": "customer",
    "offer.billing_address_present": "customer",
    "offer.site_address_present": "customer",
    "offer.reverse_charge_tax_id": "customer",
    "offer.address_window_fit": "customer",
    "offer.number_unique": "details",
    "offer.valid_until_present": "details",
    "offer.valid_until_after_issue": "details",
    "offer.tax_rate_known": "details",
    "us_ca.offer.licence_number": "details",
    "fr.offer.reduced_vat_attestation": "details",
    "offer.unpriced_line": "items",
    "offer.alternative_target": "items",
    "offer.no_cost_columns": "items",
    "offer.totals_consistent": "items",
    "offer.rounding_gap": "items",
    "offer.single_currency": "items",
    "offer.stale_revision": "items",
    "offer.payment_terms_present": "texts",
    "offer.placeholders_resolved": "texts",
    "fr.offer.insurance_named": "texts",
    "offer.consumer_gross": "layout",
    "uk.offer.cancellation_notice": "layout",
}


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": code, "message": message})


def _normalise_address(raw: Any, country: str | None = None) -> dict[str, str]:
    """Contact and project addresses come in several shapes; the offer keeps one."""
    src = raw if isinstance(raw, dict) else {}

    def first(*keys: str) -> str:
        for key in keys:
            value = src.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    out = {
        "street": first("street", "line1", "text", "address"),
        "postcode": first("postcode", "postal_code", "zip", "postal"),
        "city": first("city", "town"),
        "state": first("state", "region", "province"),
        "country": first("country", "country_code") or (country or ""),
    }
    return {k: v for k, v in out.items() if v}


def address_lines(customer: dict[str, Any], *, home_country: str = "", attn_label: str = "Attn.") -> list[str]:
    """Address block lines: name, attn, street, postcode city, country only when foreign."""
    addr = customer.get("billing_address") or {}
    lines = [str(customer.get("name") or "")]
    if customer.get("attn"):
        lines.append(f"{attn_label} {customer['attn']}")
    if addr.get("street"):
        lines.append(addr["street"])
    town = " ".join(p for p in (addr.get("postcode"), addr.get("city")) if p)
    if addr.get("state") and (home_country or "").upper() == "US":
        town = f"{addr.get('city', '')}, {addr['state']} {addr.get('postcode', '')}".strip(", ")
    if town:
        lines.append(town)
    country = str(addr.get("country") or "")
    if country and country.upper() != (home_country or "").upper():
        lines.append(country)
    return [ln for ln in lines if ln]


def _one_line(addr: dict[str, Any]) -> str:
    return ", ".join(
        p for p in (addr.get("street"), " ".join(x for x in (addr.get("postcode"), addr.get("city")) if x)) if p
    )


class OfferService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OfferRepository(session)

    # -- sources ------------------------------------------------------------------------------

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    async def _contact(self, contact_id: uuid.UUID | None) -> Any | None:
        if contact_id is None:
            return None
        from app.modules.contacts.models import Contact

        return await self.session.get(Contact, contact_id)

    async def _gather_boq(self, boq_id: uuid.UUID) -> dict[str, Any]:
        """Items in print order, active non-tax markups, currencies seen and the fingerprint."""
        from app.modules.boq.gaeb_common import is_excluded_from_total
        from app.modules.boq.service import BOQService

        structured = await BOQService(self.session).get_boq_structured_for_export(boq_id)
        items: list[dict[str, Any]] = []
        currencies: set[str] = set()

        def add_position(pos: Any, section: str) -> None:
            meta = pos.metadata if isinstance(pos.metadata, dict) else {}
            role = str(meta.get("offer_role") or "")
            unit = (pos.unit or "").strip()
            if role not in pricing.LINE_ROLES:
                if is_excluded_from_total(pos):
                    role = "optional"
                elif unit.lower() in LUMP_SUM_UNITS:
                    role = "lump_sum"
                else:
                    role = "base"
            if meta.get("currency"):
                currencies.add(str(meta["currency"]).upper())
            items.append(
                {
                    "kind": "item",
                    "position_id": str(pos.id),
                    "ordinal": pos.ordinal,
                    "description": pos.description,
                    "unit": unit,
                    "quantity": str(pos.quantity),
                    "unit_rate": str(pos.unit_rate),
                    "role": role,
                    "alternative_of": str(meta.get("offer_alternative_of") or ""),
                    "by_others": bool(meta.get("offer_by_others")),
                    "section": section,
                }
            )

        for pos in structured.positions:
            add_position(pos, "")
        for sec in structured.sections:
            items.append({"kind": "section", "ordinal": sec.ordinal, "description": sec.description, "level": 0})
            for pos in sec.positions:
                add_position(pos, sec.ordinal)
        markups = [
            {"label": m.name, "amount": str(m.amount)}
            for m in structured.markups
            if m.is_active and (m.category or "").lower() != "tax"
        ]
        priced = [i for i in items if i["kind"] == "item"]
        return {
            "items": items,
            "markups": markups,
            "currencies": sorted(currencies),
            "fingerprint": pricing.fingerprint(priced, markups),
            "boq_name": structured.name,
            "locked": bool(structured.is_locked),
        }

    # -- settings and the text library --------------------------------------------------------

    async def settings(self) -> OfferSettings:
        return await self.repo.settings()

    async def next_number(self, pattern: str | None = None) -> str:
        cfg = await self.settings()
        pat = pattern or cfg.number_pattern
        year = date.today().year
        seq = pricing.next_sequence(pat, year, await self.repo.numbers())
        return pricing.render_number(pat, year, seq)

    async def update_settings(self, data: SettingsUpdate) -> OfferSettings:
        row = await self.settings()
        patch = data.model_dump(exclude_unset=True)
        if "schedule_templates" in patch and data.schedule_templates is not None:
            row.schedule_templates = [t.model_dump(mode="json") for t in data.schedule_templates]
            patch.pop("schedule_templates")
        for key, value in patch.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def ensure_pack_texts(self, pack: dict[str, Any]) -> None:
        """First open seeds the company library from the project's pack, once per pack."""
        key = pack.get("key") or "_default"
        cfg = await self.settings()
        if key in (cfg.texts_seeded_for or []):
            return
        for kind in pack_mod.TEXT_KINDS:
            for lang, body in ((pack.get("texts") or {}).get(kind) or {}).items():
                if not body:
                    continue
                await self.repo.add_text_block(
                    OfferTextBlock(
                        scope="company",
                        kind=kind,
                        name=kind.replace("_", " ").title(),
                        language=lang,
                        body=body,
                        is_default=True,
                        pack_key=pack.get("key"),
                    )
                )
        cfg.texts_seeded_for = [*(cfg.texts_seeded_for or []), key]
        await self.session.flush()

    async def _pick_texts(self, project_id: uuid.UUID, pack: dict[str, Any], locale: str) -> dict[str, Any]:
        lang = (locale or "en").split("-")[0].lower()
        project_blocks = await self.repo.text_blocks(project_id=project_id, scope="project")
        company = await self.repo.text_blocks(scope="company")
        out: dict[str, Any] = {}
        for kind in pack_mod.TEXT_KINDS:
            chosen, source = None, "company"
            for pool, src in ((project_blocks, "project"), ([b for b in company if b.is_default], "company")):
                same = [b for b in pool if b.kind == kind and b.language == lang]
                anyl = [b for b in pool if b.kind == kind and b.language == "en"]
                if same or anyl:
                    chosen, source = (same or anyl)[0], src
                    break
            if chosen is not None:
                out[kind] = {"source": source, "body": chosen.body, "block_id": str(chosen.id)}
            else:
                out[kind] = {"source": "company", "body": pack_mod.default_text(pack, kind, locale), "block_id": None}
        return out

    async def list_text_blocks(self, project_id: uuid.UUID | None, pack: dict[str, Any] | None) -> list[OfferTextBlock]:
        if pack is not None:
            await self.ensure_pack_texts(pack)
        company = await self.repo.text_blocks(scope="company")
        project = await self.repo.text_blocks(project_id=project_id, scope="project") if project_id else []
        return [*company, *project]

    async def save_text_block(self, data: TextBlockIn, block_id: uuid.UUID | None = None) -> OfferTextBlock:
        if data.scope == "project" and data.project_id is None:
            raise HTTPException(status_code=422, detail="A project text needs a project")
        unknown = pricing.unknown_placeholders(data.body)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown placeholder {{{unknown[0]}}}")
        block = await self.repo.text_block(block_id) if block_id else None
        if block_id and block is None:
            raise HTTPException(status_code=404, detail="Text not found")
        if block is None:
            block = await self.repo.add_text_block(
                OfferTextBlock(scope=data.scope, project_id=data.project_id, kind=data.kind, language=data.language)
            )
        block.name, block.body, block.language, block.kind = data.name, data.body, data.language, data.kind
        block.is_default = data.is_default
        if data.is_default:
            for other in await self.repo.text_blocks(scope=block.scope, kind=block.kind, project_id=block.project_id):
                if other.id != block.id and other.language == block.language:
                    other.is_default = False
        await self.session.flush()
        return block

    async def delete_text_block(self, block_id: uuid.UUID) -> None:
        block = await self.repo.text_block(block_id)
        if block is None:
            raise HTTPException(status_code=404, detail="Text not found")
        await self.repo.delete_text_block(block)

    async def restore_pack_texts(self, pack: dict[str, Any]) -> int:
        """Re-add the pack's default texts that the company deleted; edited ones stay."""
        have = {
            (b.kind, b.language) for b in await self.repo.text_blocks(scope="company") if b.pack_key == pack.get("key")
        }
        added = 0
        for kind in pack_mod.TEXT_KINDS:
            for lang, body in ((pack.get("texts") or {}).get(kind) or {}).items():
                if body and (kind, lang) not in have:
                    await self.repo.add_text_block(
                        OfferTextBlock(
                            scope="company", kind=kind, name=kind.replace("_", " ").title(), language=lang,
                            body=body, is_default=True, pack_key=pack.get("key"),
                        )
                    )  # fmt: skip
                    added += 1
        return added

    # -- context --------------------------------------------------------------------------------

    async def context(self, project_id: uuid.UUID, boq_id: uuid.UUID) -> dict[str, Any]:
        project = await self._project(project_id)
        pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
        await self.ensure_pack_texts(pack)
        cfg = await self.settings()
        locale = project.locale or "en"
        from app.modules.boq.pdf_export import _PDF_LABELS

        offers = await self.repo.list_for_boq(boq_id)
        return {
            "project_id": project.id,
            "boq_id": boq_id,
            "pack": pack_mod.summary(pack, locale),
            "locale": locale,
            "currency": project.currency or pack.get("currency") or "",
            "client_contact_id": uuid.UUID(project.client_id) if project.client_id else None,
            "default_validity_days": cfg.validity_days or int(pack.get("validity_days") or 30),
            "default_payment_days": cfg.payment_days,
            "next_number": await self.next_number(),
            "document_languages": sorted(_PDF_LABELS),
            "offers": [await self._summary(o) for o in offers],
        }

    # -- building a record --------------------------------------------------------------------

    async def _customer_snapshot(self, contact: Any | None, pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if contact is None:
            return {}, "business"
        person = " ".join(p for p in (contact.first_name, contact.last_name) if p).strip()
        company = (contact.company_name or contact.legal_name or "").strip()
        name = company or person
        addr_src = contact.billing_address if getattr(contact, "billing_address", None) else contact.address
        billing = _normalise_address(addr_src, contact.country_code)
        snapshot = {
            "name": name,
            "attn": person if company and person else "",
            "billing_address": billing,
            "vat_id": contact.vat_number or "",
            "email": contact.primary_email or "",
            "phone": contact.primary_phone or "",
            "party_kind": contact.party_kind or "",
        }
        kind = "private" if contact.party_kind == "person" and pack_mod.has_consumer_rule(pack) else "business"
        return snapshot, kind

    async def _user_person(self, user_id: str | None) -> dict[str, str]:
        if not user_id:
            return {}
        from app.modules.users.models import User

        try:
            user = await self.session.get(User, uuid.UUID(user_id))
        except ValueError:
            return {}
        return {"name": user.full_name, "email": user.email} if user else {}

    def _default_options(self, pack: dict[str, Any], kind: str) -> dict[str, Any]:
        has_notice = bool((pack.get("consumer") or {}).get("cancellation_notice"))
        return {
            "show_section_subtotals": True,
            "optional_unit_rate_only": False,
            "acceptance_block": True,
            "company_signature": True,
            "carried_forward": False,
            "item_numbers": True,
            "show_gross": True,
            "logo_size": "M",
            "cancellation_notice": has_notice and kind == "private",
            "attestation_received": False,
        }

    async def create(self, data: OfferCreate, user_id: str | None) -> Offer:
        project = await self._project(data.project_id)
        pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
        await self.ensure_pack_texts(pack)
        cfg = await self.settings()
        contact_id = data.contact_id or (uuid.UUID(project.client_id) if project.client_id else None)
        customer, kind = await self._customer_snapshot(await self._contact(contact_id), pack)
        locale = data.locale or project.locale or "en"
        today = date.today()
        days = cfg.validity_days or int(pack.get("validity_days") or 30)
        rate = pricing.dec(project.default_vat_rate, Decimal("NaN")) if project.default_vat_rate else Decimal("NaN")
        if rate.is_nan():
            rate = pack_mod.standard_rate(pack, today) or Decimal(0)
        payment_days = cfg.payment_days
        if payment_days is None and customer:
            contact = await self._contact(contact_id)
            payment_days = (
                int(contact.payment_terms_days) if contact and (contact.payment_terms_days or "").isdigit() else None
            )
        offer = Offer(
            project_id=project.id,
            boq_id=data.boq_id,
            group_id=uuid.uuid4(),
            number=await self.next_number(),
            revision="A",
            status="draft",
            contact_id=contact_id,
            customer_kind=kind,
            customer=customer,
            site_address=_normalise_address(project.address, project.country_code),
            pack_key=pack.get("key"),
            locale=locale,
            title=pack_mod.title_for(pack, locale),
            currency=(project.currency or pack.get("currency") or "").upper(),
            tax_mode="standard",
            tax_rate=pricing.plain(rate),
            tax_label=pack_mod.tax_label(pack, rate),
            issue_date=today,
            validity_days=days,
            valid_until=pricing.valid_until(today, days),
            payment_days=payment_days if payment_days is not None else FALLBACK_PAYMENT_DAYS,
            contact_person=await self._user_person(user_id),
            markup_presentation=cfg.markup_presentation or "spread",
            options=self._default_options(pack, kind),
            texts=await self._pick_texts(project.id, pack, locale),
            instalments=self._template_rows(cfg, cfg.default_schedule),
            created_by=user_id,
        )
        await self.repo.add(offer)
        await self._reprice(offer)
        return offer

    def _template_rows(self, cfg: OfferSettings, name: str) -> list[dict[str, Any]]:
        if not name:
            return []
        for tpl in cfg.schedule_templates or []:
            if tpl.get("name") == name:
                return list(tpl.get("rows") or [])
        return []

    async def get(self, offer_id: uuid.UUID) -> Offer:
        offer = await self.repo.get(offer_id)
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")
        if offer.status == "sent" and offer.valid_until and offer.valid_until < date.today():
            offer.status = "expired"
            await self.session.flush()
        return offer

    def _assert_editable(self, offer: Offer) -> None:
        if offer.status != "draft":
            raise _conflict(
                "offer_frozen",
                f"Offer {offer.number} {offer.revision} is {offer.status}. Create a revision to change it.",
            )

    async def update(self, offer_id: uuid.UUID, data: OfferUpdate) -> Offer:
        offer = await self.get(offer_id)
        self._assert_editable(offer)
        patch = data.model_dump(exclude_unset=True, mode="python")
        if "contact_id" in patch:
            project = await self._project(offer.project_id)
            pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
            offer.contact_id = patch.pop("contact_id")
            offer.customer, kind = await self._customer_snapshot(await self._contact(offer.contact_id), pack)
            if "customer_kind" not in patch:
                offer.customer_kind = kind
        for key in ("options", "contact_person"):
            if key in patch and patch[key] is not None:
                merged = dict(getattr(offer, key) or {})
                merged.update(patch.pop(key))
                setattr(offer, key, merged)
        if "texts" in patch and patch["texts"] is not None:
            current = dict(offer.texts or {})
            for kind, entry in (data.texts or {}).items():
                current[kind] = {
                    "source": entry.source,
                    "body": entry.body,
                    "block_id": str(entry.block_id) if entry.block_id else None,
                }
                if entry.source == "project" and entry.body:
                    await self._save_project_text(offer, kind, entry.body)
            offer.texts = current
            patch.pop("texts")
        if "instalments" in patch and patch["instalments"] is not None:
            offer.instalments = [i.model_dump(mode="json", exclude_none=True) for i in (data.instalments or [])]
            patch.pop("instalments")
        if "issue_date" in patch or "validity_days" in patch:
            issue = patch.get("issue_date") or offer.issue_date
            days = patch.get("validity_days") or offer.validity_days
            if "valid_until" not in patch and days:
                offer.valid_until = pricing.valid_until(issue, days)
        if "valid_until" in patch and patch["valid_until"] and "validity_days" not in patch:
            offer.validity_days = (patch["valid_until"] - (patch.get("issue_date") or offer.issue_date)).days
        for key, value in patch.items():
            if value is not None or key in ("valid_until",):
                setattr(offer, key, value)
        if "tax_rate" in patch:
            project = await self._project(offer.project_id)
            pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
            offer.tax_label = pack_mod.tax_label(pack, pricing.dec(offer.tax_rate))
        await self._reprice(offer)
        return offer

    async def reset_text(self, offer_id: uuid.UUID, kind: str) -> Offer:
        """Drop the project override for ``kind`` and put the company text back on this offer."""
        offer = await self.get(offer_id)
        self._assert_editable(offer)
        if kind not in pack_mod.TEXT_KINDS:
            raise HTTPException(status_code=422, detail="Unknown text kind")
        lang = (offer.locale or "en").split("-")[0].lower()
        for block in await self.repo.text_blocks(project_id=offer.project_id, kind=kind, scope="project"):
            if block.language == lang:
                await self.repo.delete_text_block(block)
        project = await self._project(offer.project_id)
        pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
        picked = (await self._pick_texts(offer.project_id, pack, offer.locale))[kind]
        offer.texts = {**(offer.texts or {}), kind: picked}
        await self._reprice(offer)
        return offer

    async def _save_project_text(self, offer: Offer, kind: str, body: str) -> None:
        lang = (offer.locale or "en").split("-")[0].lower()
        existing = [
            b
            for b in await self.repo.text_blocks(project_id=offer.project_id, kind=kind, scope="project")
            if b.language == lang
        ]
        if existing:
            existing[0].body = body
        else:
            await self.repo.add_text_block(
                OfferTextBlock(
                    scope="project", project_id=offer.project_id, kind=kind, language=lang, body=body, is_default=True
                )
            )

    async def _reprice(self, offer: Offer) -> None:
        """Re-price a draft from the BOQ and refresh every figure the record stores."""
        project = await self._project(offer.project_id)
        pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
        boq = (
            await self._gather_boq(offer.boq_id)
            if offer.boq_id
            else {"items": [], "markups": [], "currencies": [], "fingerprint": ""}
        )
        composed = pricing.compose(
            boq["items"],
            currency=offer.currency,
            markups=boq["markups"],
            presentation=offer.markup_presentation,
            markup_section_label=self._markup_section_label(offer.locale),
            tax_mode=offer.tax_mode,
            tax_rate=pricing.dec(offer.tax_rate),
            instalments=offer.instalments or [],
        )
        offer.lines, offer.totals, offer.schedule = composed["lines"], composed["totals"], composed["schedule"]
        offer.estimate_net = composed["estimate_net"]
        offer.boq_fingerprint = boq["fingerprint"]
        offer.metadata_ = {
            **(offer.metadata_ or {}),
            "currencies": boq["currencies"],
            "boq_name": boq.get("boq_name", ""),
        }
        offer.texts = self._resolve_texts(offer, project, pack)
        await self.session.flush()

    @staticmethod
    def _markup_section_label(locale: str) -> str:
        from app.modules.boq.pdf_export import _get_pdf_labels

        return _get_pdf_labels(locale).get("offer_preliminaries", "Preliminaries")

    def _placeholder_values(self, offer: Offer, project: Any) -> dict[str, str]:
        loc, cur = offer.locale, offer.currency
        totals = offer.totals or {}
        deposit = sum(
            (pricing.dec(r.get("percent")) for r in offer.schedule or [] if r.get("kind") == "deposit"), Decimal(0)
        )
        site = _one_line(offer.site_address or {})
        return {
            "offer_number": offer.number,
            "revision": offer.revision,
            "issue_date": pricing.format_date(offer.issue_date, loc),
            "valid_until": pricing.format_date(offer.valid_until, loc),
            "validity_days": str(offer.validity_days or ""),
            "payment_days": str(offer.payment_days if offer.payment_days is not None else ""),
            "customer_name": str((offer.customer or {}).get("name") or ""),
            "project_name": project.name if project is not None else "",
            "site_address": site,
            "net_total": pricing.format_money(totals.get("net", "0"), cur, loc, symbol=True),
            "gross_total": pricing.format_money(totals.get("gross", "0"), cur, loc, symbol=True),
            "currency": cur,
            "retention_percent": pricing.format_decimal(offer.retention_percent or "0", loc),
            "advance_percent": pricing.format_decimal(deposit.quantize(Decimal("0.01")), loc) if deposit else "",
        }

    def _resolve_texts(self, offer: Offer, project: Any, pack: dict[str, Any]) -> dict[str, Any]:
        values = self._placeholder_values(offer, project)
        out: dict[str, Any] = {}
        for kind in pack_mod.TEXT_KINDS:
            entry = dict((offer.texts or {}).get(kind) or {"source": "company", "body": "", "block_id": None})
            entry["resolved"] = pricing.resolve(str(entry.get("body") or ""), values)
            out[kind] = entry
        return out

    # -- validation --------------------------------------------------------------------------

    def _dict(self, offer: Offer) -> dict[str, Any]:
        cols = (
            "id", "status", "number", "revision", "contact_id", "customer_kind", "customer", "site_address",
            "site_same_as_billing", "issue_date", "valid_until", "currency", "tax_mode", "tax_rate",
            "markup_presentation", "options", "lines", "totals", "texts", "schedule", "instalments",
            "licence_number", "retention_percent", "advance_security", "payment_days", "contract_id",
        )  # fmt: skip
        return {c: getattr(offer, c) for c in cols}

    async def _snapshot(self, offer: Offer) -> dict[str, Any]:
        from app.modules.offers import pdf as offer_pdf

        project = await self._project(offer.project_id)
        pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
        boq_changed = False
        if offer.status in ("sent", "accepted") and offer.boq_id:
            boq_changed = (await self._gather_boq(offer.boq_id))["fingerprint"] != offer.boq_fingerprint
        currencies = set((offer.metadata_ or {}).get("currencies") or []) | (
            {offer.currency} if offer.currency else set()
        )
        taken = await self.repo.number_taken(offer.number, offer.group_id)
        window = pack_mod.address_window(pack)
        fit = offer_pdf.address_fit(
            address_lines(offer.customer or {}, home_country=project.country_code or ""), window
        )
        return {
            "offer": self._dict(offer),
            "pack": pack,
            "facts": {
                "number_taken": taken,
                "boq_changed": boq_changed,
                "currencies": sorted(currencies),
                "country": project.country_code or "",
                "address_fit": fit,
            },
        }

    async def validate(self, offer: Offer) -> ValidationOut:
        results = await validators.evaluate(await self._snapshot(offer), target_id=str(offer.id))
        findings = []
        for r in results:
            ref = r.element_ref or ""
            section = _SECTION_OF_RULE.get(r.rule_id) or (
                "schedule"
                if r.rule_id.startswith("payment_plan.") or "abschlag" in r.rule_id
                else ("texts" if ref.startswith("texts") else "items")
            )
            findings.append(
                FindingOut(
                    rule_id=r.rule_id,
                    severity=str(r.severity.value if hasattr(r.severity, "value") else r.severity).lower(),  # type: ignore[arg-type]
                    message=r.message,
                    element_ref=r.element_ref,
                    details=r.details or {},
                    section=section,  # type: ignore[arg-type]
                )
            )
        order = {"error": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda f: order.get(f.severity, 3))
        errors = [f for f in findings if f.severity == "error"]
        return ValidationOut(
            findings=findings,
            errors=len(errors),
            warnings=sum(1 for f in findings if f.severity == "warning"),
            can_send=not errors,
            first_error=errors[0].message if errors else None,
        )

    # -- lifecycle ---------------------------------------------------------------------------

    async def send(self, offer_id: uuid.UUID) -> Offer:
        offer = await self.get(offer_id)
        self._assert_editable(offer)
        await self._reprice(offer)
        report = await self.validate(offer)
        if not report.can_send:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "offer_has_errors",
                    "message": report.first_error,
                    "findings": [f.model_dump() for f in report.findings],
                },
            )
        offer.status = "sent"
        offer.sent_at = datetime.now(UTC)
        for rev in await self.repo.revisions(offer.group_id):
            if rev.id != offer.id and rev.status in ("sent", "expired"):
                rev.status = "superseded"
        await self.session.flush()
        return offer

    async def revise(self, offer_id: uuid.UUID, user_id: str | None) -> Offer:
        src = await self.get(offer_id)
        if src.status == "draft":
            raise _conflict("offer_is_draft", "The offer is still a draft. Edit it directly.")
        revisions = await self.repo.revisions(src.group_id)
        if any(r.status == "draft" for r in revisions):
            raise _conflict("draft_exists", "A draft revision of this offer already exists.")
        letter = pricing.revision_letter(max(pricing.revision_index(r.revision) for r in revisions) + 1)
        today = date.today()
        new = Offer(
            project_id=src.project_id, boq_id=src.boq_id, group_id=src.group_id, number=src.number, revision=letter,
            status="draft", contact_id=src.contact_id, customer_kind=src.customer_kind, customer=dict(src.customer or {}),
            site_address=dict(src.site_address or {}), site_same_as_billing=src.site_same_as_billing, pack_key=src.pack_key,
            locale=src.locale, title=src.title, currency=src.currency, tax_mode=src.tax_mode, tax_rate=src.tax_rate,
            tax_label=src.tax_label, issue_date=today, validity_days=src.validity_days,
            valid_until=pricing.valid_until(today, src.validity_days) if src.validity_days else None,
            payment_days=src.payment_days, reference=src.reference, contact_person=dict(src.contact_person or {}),
            licence_number=src.licence_number, markup_presentation=src.markup_presentation, options=dict(src.options or {}),
            texts={k: {kk: vv for kk, vv in v.items() if kk != "resolved"} for k, v in (src.texts or {}).items()},
            instalments=list(src.instalments or []), retention_percent=src.retention_percent,
            advance_security=src.advance_security, created_by=user_id,
        )  # fmt: skip
        await self.repo.add(new)
        await self._reprice(new)
        return new

    async def decline(self, offer_id: uuid.UUID) -> Offer:
        offer = await self.get(offer_id)
        if offer.status not in ("sent", "expired"):
            raise _conflict("offer_not_sent", "Only a sent offer can be declined.")
        offer.status, offer.decided_at = "declined", datetime.now(UTC)
        await self.session.flush()
        return offer

    async def accept(
        self, offer_id: uuid.UUID, data: AcceptRequest, user_id: str | None
    ) -> tuple[Offer, uuid.UUID | None, int]:
        """Mark an offer accepted and, by default, award it to a client contract with its milestones."""
        offer = await self.get(offer_id)
        if offer.status not in ("sent", "expired"):
            raise _conflict("offer_not_sent", "Only a sent offer can be accepted.")
        ticked = set(data.optional_ordinals)
        figures = pricing.accepted_figures(offer.lines or [], offer.instalments or [], ticked, currency=offer.currency,
                                           tax_mode=offer.tax_mode)  # fmt: skip
        offer.accepted_options = sorted(ticked)
        offer.status = "accepted"
        offer.decided_at = (
            datetime.combine(data.accepted_on, datetime.min.time(), tzinfo=UTC)
            if data.accepted_on
            else datetime.now(UTC)
        )
        offer.metadata_ = {
            **(offer.metadata_ or {}),
            "accepted_totals": figures["totals"],
            "accepted_schedule": figures["schedule"],
        }
        contract_id, milestones = None, 0
        if data.create_contract:
            contract_id, milestones = await self._award(offer, figures, user_id, data.accepted_on or date.today())
            offer.contract_id = contract_id
        if offer.boq_id:
            from app.modules.boq.models import BOQ

            boq = await self.session.get(BOQ, offer.boq_id)
            if boq is not None:
                boq.is_locked = True
        await self.session.flush()
        return offer, contract_id, milestones

    async def _award(
        self, offer: Offer, figures: dict[str, Any], user_id: str | None, accepted_on: date
    ) -> tuple[uuid.UUID, int]:
        from app.modules.contracts.models import Contract, ContractMilestone, ContractSecurity
        from app.modules.contracts.service import ContractsService

        payload = pricing.contract_payload(
            {
                "id": offer.id, "contact_id": offer.contact_id, "net": figures["totals"]["net"], "currency": offer.currency,
                "retention_percent": offer.retention_percent, "payment_days": offer.payment_days, "number": offer.number,
                "revision": offer.revision, "instalments": figures["schedule"], "advance_security": offer.advance_security,
            }
        )  # fmt: skip
        project = await self._project(offer.project_id)
        code = f"CT-{offer.number}"
        taken = (await self.session.execute(select(Contract.id).where(Contract.code == code))).first()
        if taken:
            code = f"{code}-{offer.revision}"
        contract = Contract(
            code=code, title=f"{project.name} - {offer.number} {offer.revision}", contract_type="lump_sum",
            counterparty_type="client", counterparty_id=offer.contact_id, project_id=offer.project_id,
            total_value=Decimal(payload["total_value"]), currency=offer.currency[:3],
            retention_percent=Decimal(payload["retention_percent"] or "0"), status="draft", terms=payload["terms"],
            created_by=user_id,
        )  # fmt: skip
        self.session.add(contract)
        await self.session.flush()
        svc = ContractsService(self.session)
        for row, due in zip(payload["milestones"], [r.get("due") or {} for r in figures["schedule"]], strict=True):
            kind_due = due.get("type")
            trigger = {"activity": "completion", "acceptance": "approval"}.get(kind_due or "", "date")
            planned = row["planned_date"] or (accepted_on.isoformat() if kind_due == "signing" else None)
            ms = ContractMilestone(
                contract_id=contract.id, code=row["code"], name=row["name"], planned_date=planned, trigger=trigger,
                kind=row["kind"], value=Decimal(row["value"]) if row["value"] else None,
                percent_of_contract=Decimal(row["percent_of_contract"]) if row["percent_of_contract"] else None,
                lag_days=row["lag_days"], payment_terms_days=row["payment_terms_days"],
            )  # fmt: skip
            self.session.add(ms)
            await self.session.flush()
            if row["activity_id"]:
                try:
                    await svc.link_milestone_activity(ms.id, uuid.UUID(str(row["activity_id"])))
                except (HTTPException, ValueError):
                    logger.info("Offer %s: activity link skipped for instalment %s", offer.number, row["code"])
        if payload["advance_security"]:
            deposit = next((r for r in payload["milestones"] if r["kind"] == "deposit"), None)
            self.session.add(
                ContractSecurity(
                    contract_id=contract.id, security_type="advance_payment_bond", provider_name="", status="required",
                    amount=Decimal(deposit["value"]) if deposit and deposit["value"] else Decimal(0), currency=offer.currency[:3],
                    percent_of_contract=Decimal(deposit["percent_of_contract"]) if deposit and deposit["percent_of_contract"] else None,
                )
            )  # fmt: skip
        await self.session.flush()
        return contract.id, len(payload["milestones"])

    # -- positions ---------------------------------------------------------------------------

    async def set_position_role(
        self, position_id: uuid.UUID, role: str, alternative_of: str | None, by_others: bool | None
    ) -> dict[str, Any]:
        """Set how a BOQ position prints on an offer. Stored in the position's metadata."""
        from app.modules.boq.models import Position

        pos = await self.session.get(Position, position_id)
        if pos is None:
            raise HTTPException(status_code=404, detail="Position not found")
        meta = dict(pos.metadata_ or {})
        meta["offer_role"] = role
        if role == "alternative":
            meta["offer_alternative_of"] = alternative_of or ""
        else:
            meta.pop("offer_alternative_of", None)
        if by_others is not None:
            meta["offer_by_others"] = by_others
        pos.metadata_ = meta
        await self.session.flush()
        return {"id": str(pos.id), "role": role}

    # -- output ------------------------------------------------------------------------------

    async def _summary(self, offer: Offer) -> OfferSummary:
        return OfferSummary(
            id=offer.id, project_id=offer.project_id, boq_id=offer.boq_id, number=offer.number, revision=offer.revision,
            status=offer.status, customer_name=str((offer.customer or {}).get("name") or ""), currency=offer.currency,
            gross=str((offer.totals or {}).get("gross", "0")), valid_until=offer.valid_until, issue_date=offer.issue_date,
        )  # fmt: skip

    async def response(self, offer: Offer) -> OfferResponse:
        stale = False
        if offer.status in ("sent", "accepted") and offer.boq_id:
            stale = (await self._gather_boq(offer.boq_id))["fingerprint"] != offer.boq_fingerprint
        out = OfferResponse.model_validate(offer)
        out.stale = stale
        out.editable = offer.status == "draft"
        return out

    async def render(self, offer: Offer) -> tuple[bytes, int]:
        """The PDF of the stored record. Drafts and previews carry the DRAFT watermark; a sent offer never does."""
        from app.modules.offers import pdf as offer_pdf

        project = await self._project(offer.project_id)
        pack = pack_mod.pack_for(project.country_code, project.subdivision_code)
        data = self._dict(offer)
        data.update(
            {
                "title": offer.title, "locale": offer.locale, "reference": offer.reference,
                "contact_person": offer.contact_person, "project_name": project.name, "pack": pack,
                "home_country": project.country_code or "", "validity_days": offer.validity_days,
                "payment_days": offer.payment_days, "tax_label": offer.tax_label, "licence_number": offer.licence_number,
            }
        )  # fmt: skip
        basis = await self._exclusions(offer)
        return offer_pdf.render_offer(data, exclusions=basis, draft=offer.status == "draft")

    async def _exclusions(self, offer: Offer) -> dict[str, list[str]]:
        """Exclusions and assumptions come from the estimate basis, never from a second list."""
        try:
            from app.modules.estimate_basis.models import EstimateBasis

            stmt = (
                select(EstimateBasis)
                .where(EstimateBasis.project_id == offer.project_id)
                .order_by(EstimateBasis.created_at.desc())
                .limit(1)
            )
            doc = (await self.session.execute(stmt)).scalar_one_or_none()
        except Exception:  # noqa: BLE001 - the offer prints without the basis rather than not at all
            logger.debug("Estimate basis unavailable for offer %s", offer.number, exc_info=True)
            return {}
        if doc is None:
            return {}

        def pick(items: Any) -> list[str]:
            return [str(i.get("text") or "") for i in (items or []) if i.get("enabled", True) and i.get("text")]

        return {"exclusions": pick(doc.exclusions), "assumptions": pick(doc.assumptions)}
