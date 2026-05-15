# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Image source adapter — single photo / drawing snapshot to /match-elements.

Implements MAPPING_PROCESS.md §3.1 / §4.1.4 — the "Image" source type.
The estimator uploads one PNG/JPG/WebP (a site photo, a hand-sketched
detail, a screenshot of a CAD elevation), and Claude / GPT-4V via the
existing :mod:`app.modules.ai` service is asked to enumerate the
visible construction elements as a structured JSON array. Each item
becomes a :class:`SourceElement` and flows through the same matcher
pipeline as BIM/DWG/text envelopes.

No CV / OCR / IfcOpenShell here — vision-LLM only. The CLAUDE.md ban on
heavy CAD libraries (and on IfcOpenShell specifically) is honoured by
keeping this adapter pure-Python: HTTP call out, JSON in.

Storage shape
-------------
The image arrives at session-creation time and lives on
``MatchSession.metadata_["image"]`` as a dict with one of:

    {"path":     "<absolute path on disk>", "mime": "image/jpeg",
     "filename": "site.jpg"}
    {"data_b64": "<base64 encoded bytes>",   "mime": "image/png",
     "filename": "sketch.png"}

The path form is preferred — large photos (5 MB+) bloat JSON columns
and slow session-list pagination. The base64 form exists as a fallback
for tests and ad-hoc /api calls that don't have a backing storage path.

Confidence is always reported as ``low`` in metadata so the matcher's
downstream confidence pipeline (``confidence_band_for``) knows the
upstream guess was a noisy LLM read, not a deterministic source.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements.models import MatchSession
from app.modules.match_elements.sources.base import SourceElement

logger = logging.getLogger(__name__)


# Order chip-bar group-by keys surface in. Keys not present in this list
# fall through alphabetically, preserving the cross-source grouping
# contract (``ifc_class`` always renders first).
_GROUP_BY_KEY_ORDER = (
    "ifc_class",
    "category",
    "name",
    "material",
    "ai_confidence",
)


# Allowed IFC class hints the prompt asks the LLM to choose from. We
# normalise the LLM's free-form output against this set so a hallucinated
# "IfcConcreteWall" gets coerced to "IfcWall" (or dropped to None).
_ALLOWED_IFC_CLASSES = frozenset({
    "IfcWall",
    "IfcSlab",
    "IfcColumn",
    "IfcBeam",
    "IfcDoor",
    "IfcWindow",
    "IfcRoof",
    "IfcStair",
    "IfcRailing",
    "IfcCovering",
    "IfcPipeSegment",
    "IfcDuctSegment",
    "IfcCableSegment",
    "IfcSpace",
    "IfcFurniture",
    "IfcBuildingElementProxy",
})


# Unit string → canonical SourceElement quantity bucket. Mirrors the
# BoQ adapter's mapping (m → length_m, m2 → area_m2, m3 → volume_m3,
# pcs → count, kg → mass_kg) so cross-source matchers don't branch on
# source type when reading quantities.
_UNIT_TO_QTY_KEY: dict[str, str] = {
    "m": "length_m",
    "m2": "area_m2",
    "m²": "area_m2",
    "m3": "volume_m3",
    "m³": "volume_m3",
    "pcs": "count",
    "pc": "count",
    "ea": "count",
    "nr": "count",
    "kg": "mass_kg",
}


# Vision LLM prompt. Kept as a module constant so the test suite can
# import and assert on it; updates to the wording need a paired update
# to the LLM-output fixture.
IMAGE_EXTRACTION_PROMPT: str = """\
Return a JSON array. Each item describes one construction element visible
in the drawing/photo:
[
  {
    "name": "...",
    "ifc_class_guess": "IfcWall|IfcSlab|IfcColumn|IfcBeam|IfcDoor|IfcWindow|IfcRoof|IfcStair|IfcRailing|IfcCovering|IfcPipeSegment|IfcDuctSegment|IfcCableSegment|IfcSpace|IfcFurniture|IfcBuildingElementProxy|null",
    "qty_estimate": <number or null>,
    "unit_estimate": "m|m2|m3|pcs|kg|null",
    "material_guess": "<freeform or null>",
    "confidence": "high|medium|low"
  }
]
If the image is not a construction drawing/photo, return [].
"""


# System prompt — kept short. The role guides the model to enumerate
# elements rather than describe the picture in prose.
_SYSTEM_PROMPT: str = (
    "You are a construction estimator. Return only a JSON array of "
    "construction elements visible in the image, exactly as instructed."
)


def _parse_ai_response(text: str) -> list[dict[str, Any]]:
    """Parse the LLM's response into a list of element dicts.

    Tolerates the same shapes :func:`app.modules.ai.ai_client.extract_json`
    handles (markdown code fences, surrounding prose, partial JSON), but
    also coerces unexpected response shapes (single dict, ``None``, dict
    wrapping a list under ``items``/``elements``) into a flat list. A
    parse failure returns ``[]`` rather than crashing — the adapter has
    to be robust against malformed LLM output.
    """
    if not text:
        return []
    raw = text.strip()
    parsed: Any
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Try fenced code block, then bracket scan.
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None
        if parsed is None:
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end > start:
                try:
                    parsed = json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None

    if parsed is None:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        # Some models wrap the array in a ``{"elements": [...]}`` envelope.
        for key in ("elements", "items", "data", "result", "results"):
            inner = parsed.get(key)
            if isinstance(inner, list):
                return [item for item in inner if isinstance(item, dict)]
    return []


def _coerce_ifc_class(raw: Any) -> str | None:
    """Coerce the LLM's ``ifc_class_guess`` to one of the allowed classes.

    Strings outside the whitelist are dropped to ``None`` rather than
    forwarded — better that a downstream group-by sees "unclassified"
    than that the matcher receives a hallucinated IFC class that never
    appears in CWICR's classification index.
    """
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    if cleaned in _ALLOWED_IFC_CLASSES:
        return cleaned
    # Case-insensitive recovery (the LLM occasionally lowercases the prefix).
    for allowed in _ALLOWED_IFC_CLASSES:
        if cleaned.lower() == allowed.lower():
            return allowed
    return None


def _coerce_unit(raw: Any) -> str | None:
    """Normalise ``unit_estimate`` to a recognised unit string."""
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower().replace(" ", "")
    if not cleaned or cleaned == "null":
        return None
    return cleaned if cleaned in _UNIT_TO_QTY_KEY else None


def _coerce_qty(raw: Any) -> float | None:
    """Best-effort numeric coercion for ``qty_estimate``."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _quantities_for(unit: str | None, qty: float | None) -> dict[str, float]:
    """Map ``unit_estimate`` + ``qty_estimate`` onto canonical buckets.

    Always carries ``count >= 1.0`` so a no-quantity element still
    flows through the matcher pipeline. The value matches the BoQ /
    text adapters' contract.
    """
    out: dict[str, float] = {"count": 1.0}
    if qty is None or qty <= 0:
        return out
    canon = _UNIT_TO_QTY_KEY.get((unit or "").strip().lower())
    if canon is None:
        return out
    if canon == "count":
        out["count"] = qty
    else:
        out[canon] = qty
    return out


def _read_image_bytes(image: dict[str, Any]) -> tuple[bytes, str] | None:
    """Resolve the image dict into ``(bytes, mime)`` or ``None``.

    Accepts either a ``path`` (preferred for production — the file
    lives on the storage backend) or an inline ``data_b64`` (used by
    ad-hoc API callers and tests that don't write to disk first).

    Missing files / un-decodable base64 / empty payloads → ``None``.
    Callers treat that as "no image bound, return []" rather than
    crashing the adapter.
    """
    mime = str(image.get("mime") or "image/jpeg")

    path = image.get("path")
    if isinstance(path, str) and path:
        try:
            data = Path(path).read_bytes()
        except (OSError, FileNotFoundError) as exc:
            logger.warning("ImageAdapter: cannot read image at %s: %s", path, exc)
            return None
        if not data:
            return None
        return data, mime

    raw_b64 = image.get("data_b64") or image.get("data")
    if isinstance(raw_b64, str) and raw_b64:
        try:
            data = base64.b64decode(raw_b64, validate=False)
        except (ValueError, TypeError) as exc:
            logger.warning("ImageAdapter: invalid base64 payload: %s", exc)
            return None
        if not data:
            return None
        return data, mime

    return None


class ImageSourceAdapter:
    """Image (photo / drawing snapshot) → :class:`SourceElement` list.

    Uses the existing :mod:`app.modules.ai` vision pipeline (Claude /
    GPT-4V via :func:`app.modules.ai.ai_client.call_ai`) to extract a
    structured list of construction elements from a single image.
    Output goes through the same matcher pipeline as BIM/DWG/text
    envelopes.

    The adapter is deliberately stateless — one async call per session
    per ``iter_elements`` invocation. We don't cache the LLM response
    here because the surrounding service layer caches at the group level
    (``MatchGroup.methods`` JSON) and re-running the LLM on session
    refresh is the user's explicit signal that the image was updated.
    """

    source_name: str = "image"

    def __init__(
        self,
        session: AsyncSession | None,
        match_session: MatchSession | None = None,
    ) -> None:
        self.session = session
        self.match_session = match_session

    # ── Internals ────────────────────────────────────────────────────

    def _image_metadata(self) -> dict[str, Any] | None:
        """Return the ``image`` dict from session metadata, or ``None``.

        Empty dict / non-dict shapes count as missing — callers treat
        that as "no image, return []".
        """
        if self.match_session is None:
            return None
        meta = self.match_session.metadata_ or {}
        image = meta.get("image")
        if not isinstance(image, dict) or not image:
            return None
        return image

    async def _extract_via_ai(
        self,
        image_bytes: bytes,
        mime: str,
    ) -> list[dict[str, Any]]:
        """Call the AI vision pipeline and return the parsed item list.

        Catches every error path — missing API key, network failure,
        4xx response, malformed JSON — and degrades to an empty list
        with a warning log. The adapter never raises HTTPException;
        the surrounding service treats an empty list as "no elements
        extracted from this image" and keeps the session usable.
        """
        # Late imports keep the match-elements module decoupled from
        # the AI module at import time — so a tenant that disabled
        # the AI module entirely doesn't break match-elements imports.
        try:
            from app.modules.ai.ai_client import call_ai, resolve_provider_and_key
            from app.modules.ai.repository import AISettingsRepository
        except ImportError as exc:
            logger.warning("ImageAdapter: AI module not available: %s", exc)
            return []

        # Resolve the most-recent AI settings row. The match-elements
        # session has no per-user binding (the matcher never stores
        # ``user_id``) so we pick the first usable settings row — for
        # single-tenant deploys this is correct, and multi-tenant
        # deploys gate vision on a system-level key anyway.
        provider: str | None = None
        api_key: str | None = None
        if self.session is not None:
            try:
                repo = AISettingsRepository(self.session)
                # Prefer the session creator's settings if available.
                creator_id = getattr(self.match_session, "created_by", None)
                settings_row = None
                if creator_id is not None:
                    settings_row = await repo.get_by_user_id(creator_id)
                if settings_row is None:
                    # Fallback: any settings row with a usable key.
                    from sqlalchemy import select

                    from app.modules.ai.models import AISettings

                    rows = (
                        await self.session.execute(
                            select(AISettings).limit(50),
                        )
                    ).scalars().all()
                    for row in rows:
                        try:
                            provider, api_key, preferred_model = resolve_provider_and_key(row)
                            settings_row = row
                            break
                        except ValueError:
                            continue
                if settings_row is not None and provider is None:
                    try:
                        provider, api_key, preferred_model = resolve_provider_and_key(settings_row)
                    except ValueError:
                        provider, api_key, preferred_model = None, None, None
            except Exception as exc:  # noqa: BLE001 — AI is best-effort
                logger.warning("ImageAdapter: settings lookup failed: %s", exc)

        if not provider or not api_key:
            logger.warning(
                "ImageAdapter: no AI provider configured — returning []",
            )
            return []

        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        try:
            raw_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=_SYSTEM_PROMPT,
                prompt=IMAGE_EXTRACTION_PROMPT,
                image_base64=image_b64,
                image_media_type=mime,
                model=preferred_model if 'preferred_model' in dir() else None,
            )
        except Exception as exc:  # noqa: BLE001 — vision is best-effort
            logger.warning("ImageAdapter: AI call failed: %s", exc)
            return []

        return _parse_ai_response(raw_response or "")

    async def _items(self) -> list[dict[str, Any]]:
        """Return the parsed list of items from the LLM's response.

        Cached on ``self`` so a single call to ``iter_elements`` followed
        by ``list_categories`` (the chip-bar refresh path) doesn't re-hit
        the LLM. The cache is per-adapter-instance, not per-session, so
        a second adapter constructed inside the same request still
        re-fetches — that matches the BoQ / Text adapter behaviour.
        """
        cache: list[dict[str, Any]] | None = getattr(self, "_items_cache", None)
        if cache is not None:
            return cache

        image = self._image_metadata()
        if image is None:
            self._items_cache = []
            return []

        resolved = _read_image_bytes(image)
        if resolved is None:
            self._items_cache = []
            return []
        image_bytes, mime = resolved

        items = await self._extract_via_ai(image_bytes, mime)
        self._items_cache = items
        return items

    # ── Public adapter API ───────────────────────────────────────────

    async def list_attribute_keys(
        self,
        project_id: uuid.UUID,  # noqa: ARG002 — image adapter is session-scoped
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> list[str]:
        """Return the union of attribute keys present on the parsed items.

        Always carries ``ifc_class`` and ``category`` so the cross-source
        group-by chip resolves on image sessions (matches the contract
        the BIM / DWG / Text adapters expose).
        """
        keys: set[str] = {"ifc_class", "category", "name", "material", "ai_confidence"}
        for item in await self._items():
            keys.update(k for k in item if isinstance(k, str))
        # Drop quantity-bearing columns from the chip-bar — they belong
        # to ``quantities``, not group-by.
        for q in ("qty_estimate", "unit_estimate", "ifc_class_guess",
                  "material_guess", "confidence"):
            keys.discard(q)
        ordered = [k for k in _GROUP_BY_KEY_ORDER if k in keys]
        ordered.extend(sorted(k for k in keys if k not in _GROUP_BY_KEY_ORDER))
        return ordered

    async def list_categories(
        self,
        project_id: uuid.UUID,  # noqa: ARG002
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> list[tuple[str, int]]:
        """Group parsed items by their (coerced) ``ifc_class`` hint.

        Falls back to ``"Image"`` when the LLM didn't return a class —
        matches the "Text" / "BoQ" defaults on text/boq adapters.
        """
        counter: Counter[str] = Counter()
        for item in await self._items():
            ifc = _coerce_ifc_class(item.get("ifc_class_guess")) or "Image"
            counter[ifc] += 1
        return counter.most_common()

    async def iter_elements(
        self,
        *,
        project_id: uuid.UUID,  # noqa: ARG002
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
        filters: dict[str, list[Any]] | None = None,
        excluded_categories: list[str] | None = None,
        use_net_quantities: bool = True,  # noqa: ARG002 — image has no openings
    ) -> list[SourceElement]:
        """Convert each parsed item to a :class:`SourceElement`."""
        excluded = {str(c) for c in (excluded_categories or []) if c}
        norm_filters: dict[str, set[str]] = {}
        if filters:
            for fkey, fvals in filters.items():
                if fvals:
                    norm_filters[fkey] = {str(v) for v in fvals}

        items = await self._items()
        if not items:
            return []

        ref_id: str | None = None
        if self.match_session is not None:
            image = self._image_metadata() or {}
            ref_id = (
                str(image.get("image_id"))
                if image.get("image_id")
                else str(self.match_session.id)
            )

        out: list[SourceElement] = []
        for idx, item in enumerate(items):
            ifc_class = _coerce_ifc_class(item.get("ifc_class_guess"))
            category = ifc_class or "Image"
            if category in excluded:
                continue

            name = item.get("name")
            name_str = str(name).strip() if isinstance(name, str) else ""

            material_guess = item.get("material_guess")
            material = (
                str(material_guess).strip()
                if isinstance(material_guess, str) and material_guess.strip()
                else None
            )

            # Always normalise confidence to 'low' in metadata — the
            # surrounding pipeline reads ``ai_confidence`` to gate
            # auto-confirm. Image-source matches are noisy by definition.
            ai_confidence = "low"

            qty = _coerce_qty(item.get("qty_estimate"))
            unit = _coerce_unit(item.get("unit_estimate"))
            quantities = _quantities_for(unit, qty)

            attrs: dict[str, Any] = {
                "ifc_class": ifc_class,
                "category": category,
                "name": name_str or None,
                "material": material,
                "ai_confidence": ai_confidence,
            }
            if unit:
                attrs["unit"] = unit
            if qty is not None:
                attrs["qty_estimate"] = qty
            # Promote category → ifc_class so cross-source group-by works
            # even when ifc_class is None (e.g., LLM returned ``null``).
            if attrs["ifc_class"] is None:
                attrs["ifc_class"] = category

            # Per-attribute filter (chip selections from the UI).
            if norm_filters:
                skip = False
                for fkey, fvals in norm_filters.items():
                    actual = attrs.get(fkey)
                    if actual is None or str(actual) not in fvals:
                        skip = True
                        break
                if skip:
                    continue

            element_id = f"image:{idx}"
            out.append(
                SourceElement(
                    id=element_id,
                    category=category,
                    name=(name_str[:200] or None) if name_str else None,
                    attributes=attrs,
                    quantities=quantities,
                    raw_ref=ref_id,
                )
            )

        return out


__all__ = ["ImageSourceAdapter", "IMAGE_EXTRACTION_PROMPT"]
