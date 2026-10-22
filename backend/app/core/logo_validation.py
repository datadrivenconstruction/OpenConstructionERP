# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for an uploaded workspace logo.

The logo is public (the login page shows it before sign-in) and is drawn by
every browser, so it is checked on the server rather than trusted from the
client: an allowed image type, a size cap, file bytes that match the declared
type, and for SVG a rewrite that keeps only drawing markup (no scripts, event
handlers, foreign content or external references). stdlib + defusedxml only.

Each rule has a stable id so the settings page and the tests can name it.
"""

from __future__ import annotations

import base64
import binascii
import re
import xml.etree.ElementTree as ET  # noqa: S405 - serialising only; parsing goes through defusedxml
from urllib.parse import unquote_to_bytes

from defusedxml import ElementTree as SafeET

#: Rule id -> human message. The id travels in the 422 detail.
LOGO_RULES: dict[str, str] = {
    "branding.logo.data_url": "The logo must be an image data URL.",
    "branding.logo.type": "The logo must be SVG, PNG, WebP or JPEG.",
    "branding.logo.size": "The logo is larger than 2 MB.",
    "branding.logo.content": "The file content does not match its image type.",
    "branding.logo.svg": "The SVG could not be read or has no drawing left after removing unsafe parts.",
}

ALLOWED_LOGO_TYPES = ("image/svg+xml", "image/png", "image/webp", "image/jpeg")

#: Decoded bytes; mirrors the frontend upload cap.
MAX_LOGO_BYTES = 2 * 1024 * 1024

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", _SVG_NS)
ET.register_namespace("xlink", _XLINK_NS)

#: Elements that can run code, embed other documents or pull remote content.
_UNSAFE_ELEMENTS = frozenset(
    {"script", "foreignobject", "iframe", "embed", "object", "handler", "listener", "audio", "video"}
)
_SAFE_HREF = re.compile(r"^(#|data:image/(png|jpeg|webp|gif);base64,)", re.IGNORECASE)
_UNSAFE_CSS = re.compile(r"(javascript:|expression\s*\(|@import|url\(\s*['\"]?(?!#)[^)]*\))", re.IGNORECASE)
_DATA_URL = re.compile(r"^data:([a-z0-9.+/-]+)(;[^,]*)?,(.*)$", re.IGNORECASE | re.DOTALL)


class LogoValidationError(ValueError):
    """A logo failed one of :data:`LOGO_RULES`."""

    def __init__(self, rule: str) -> None:
        super().__init__(LOGO_RULES[rule])
        self.rule = rule
        self.message = LOGO_RULES[rule]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def sanitise_svg(raw: bytes) -> bytes:
    """Return the SVG with every scripting and external-reference vector removed."""
    try:
        root = SafeET.fromstring(raw)
    except Exception as exc:  # defusedxml raises several types; all mean unusable
        raise LogoValidationError("branding.logo.svg") from exc
    if _local(root.tag) != "svg":
        raise LogoValidationError("branding.logo.svg")

    def clean(node: ET.Element) -> None:
        for child in list(node):
            if not isinstance(child.tag, str) or _local(child.tag) in _UNSAFE_ELEMENTS:
                node.remove(child)
                continue
            if _local(child.tag) == "style" and child.text and _UNSAFE_CSS.search(child.text):
                node.remove(child)
                continue
            clean(child)
        for name in list(node.attrib):
            local = _local(name)
            value = node.attrib[name]
            if (
                local.startswith("on")
                or (local == "href" and not _SAFE_HREF.match(value.strip()))
                or (local == "style" and _UNSAFE_CSS.search(value))
                or "javascript:" in value.lower()
            ):
                del node.attrib[name]

    clean(root)
    if len(root) == 0:
        raise LogoValidationError("branding.logo.svg")
    return ET.tostring(root, encoding="utf-8")


def _magic_ok(mime: str, data: bytes) -> bool:
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    return True


def validate_logo_data_url(value: str) -> str:
    """Check a logo data URL against every rule and return the safe version.

    Raises:
        LogoValidationError: naming the first rule that failed.
    """
    match = _DATA_URL.match(value.strip())
    if not match or not match.group(1).lower().startswith("image/"):
        raise LogoValidationError("branding.logo.data_url")
    mime = match.group(1).lower()
    if mime not in ALLOWED_LOGO_TYPES:
        raise LogoValidationError("branding.logo.type")
    is_base64 = ";base64" in (match.group(2) or "").lower()
    payload = match.group(3)
    if len(payload) > MAX_LOGO_BYTES * 4 // 3 + 16:
        raise LogoValidationError("branding.logo.size")
    try:
        if is_base64:
            data = base64.b64decode(payload, validate=True)
        else:
            data = unquote_to_bytes(payload)
    except (binascii.Error, ValueError) as exc:
        raise LogoValidationError("branding.logo.content") from exc
    if len(data) > MAX_LOGO_BYTES:
        raise LogoValidationError("branding.logo.size")
    if not _magic_ok(mime, data):
        raise LogoValidationError("branding.logo.content")
    if mime == "image/svg+xml":
        data = sanitise_svg(data)
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
