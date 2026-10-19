# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The KSeF verification QR codes.

Source: https://github.com/CIRFMF/ksef-docs/blob/main/kody-qr.md (21.08.2025,
read 2026-10-19).

KOD I goes on every invoice delivered outside KSeF (a PDF, a print, an email
attachment). It links to the invoice in KSeF::

    {qr host}/invoice/{seller NIP}/{P_1 as DD-MM-YYYY}/{SHA-256 of the XML file, Base64URL}

Its label is the KSeF number, or ``OFFLINE`` while the invoice has none.

KOD II goes only on an invoice issued offline, next to KOD I. It proves the
issuer holds a KSeF certificate of the Offline type::

    {qr host}/certificate/{context type}/{context value}/{seller NIP}/{certificate serial}/{invoice hash}/{signature}

The signature is over that link without ``https://`` and without the signature
segment: RSASSA-PSS with SHA-256, MGF1 SHA-256 and a 32 byte salt, or ECDSA
P-256 with SHA-256 encoded as IEEE P1363 ``r || s``; Base64URL either way. The
label is ``CERTYFIKAT``.

The private key of the offline certificate never enters this module. A
:class:`LinkSigner` signs; :class:`SoftwareLinkSigner` is the one shipped, for
tests and for a deployment that keeps the key in a file it controls.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

from app.modules.einvoice_ksef.facts import ENVIRONMENTS

LABEL_OFFLINE = "OFFLINE"
LABEL_CERTIFICATE = "CERTYFIKAT"

CONTEXT_TYPES: tuple[str, ...] = ("Nip", "InternalId", "NipVatUe", "PeppolId")


class QrError(ValueError):
    """The inputs cannot make a verification link."""


def b64url(data: bytes) -> str:
    """Base64URL without padding, the form every KSeF link segment uses."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def invoice_hash(xml_bytes: bytes) -> str:
    """SHA-256 of the exact invoice file, Base64URL. The same bytes KSeF received."""
    return b64url(hashlib.sha256(xml_bytes).digest())


def _qr_host(environment: str) -> str:
    env = ENVIRONMENTS.get((environment or "").strip().lower())
    if env is None:
        raise QrError(f"{environment!r} is not a KSeF environment; use one of {', '.join(ENVIRONMENTS)}")
    return env.qr_base_url


def _nip(value: str) -> str:
    text = (value or "").strip()
    if not (len(text) == 10 and text.isdigit()):
        raise QrError(f"{value!r} is not a ten digit NIP")
    return text


def _file_hash(xml_bytes: bytes | None, file_hash: str) -> str:
    if xml_bytes is not None:
        return invoice_hash(xml_bytes)
    if not (file_hash or "").strip():
        raise QrError("the invoice file or its SHA-256 hash is needed")
    return file_hash.strip()


def invoice_link(
    *, environment: str, seller_nip: str, issue_date: date, xml_bytes: bytes | None = None, file_hash: str = ""
) -> str:
    """KOD I: the link that opens the invoice in KSeF."""
    digest = _file_hash(xml_bytes, file_hash)
    return f"{_qr_host(environment)}/invoice/{_nip(seller_nip)}/{issue_date.strftime('%d-%m-%Y')}/{digest}"


def kod_i_label(ksef_number: str) -> str:
    """The text under KOD I: the KSeF number, or OFFLINE before there is one."""
    return (ksef_number or "").strip() or LABEL_OFFLINE


@runtime_checkable
class LinkSigner(Protocol):
    """Whatever holds the private key of the issuer's offline KSeF certificate."""

    certificate_serial: str

    def sign(self, data: bytes) -> bytes:
        """The raw signature over ``data``: PSS for RSA, P1363 ``r || s`` for EC."""
        ...


class SoftwareLinkSigner:
    """A signer over a key loaded in this process. RSA (2048 bits or more) or EC P-256."""

    def __init__(self, private_key: Any, certificate_serial: str) -> None:
        from cryptography.hazmat.primitives.asymmetric import ec, rsa

        if isinstance(private_key, rsa.RSAPrivateKey):
            if private_key.key_size < 2048:
                raise QrError("an RSA key for KOD II must be at least 2048 bits")
        elif isinstance(private_key, ec.EllipticCurvePrivateKey):
            if not isinstance(private_key.curve, ec.SECP256R1):
                raise QrError("an EC key for KOD II must be on the P-256 curve")
        else:
            raise QrError("KOD II is signed with an RSA or an EC P-256 key")
        self._key = private_key
        self.certificate_serial = certificate_serial

    def sign(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, padding
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        if isinstance(self._key, ec.EllipticCurvePrivateKey):
            r, s = decode_dss_signature(self._key.sign(data, ec.ECDSA(hashes.SHA256())))
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return self._key.sign(
            data,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
            hashes.SHA256(),
        )


def certificate_link(
    *,
    environment: str,
    context_type: str,
    context_value: str,
    seller_nip: str,
    signer: LinkSigner,
    xml_bytes: bytes | None = None,
    file_hash: str = "",
) -> str:
    """KOD II: the signed link that verifies the issuer's offline certificate."""
    if context_type not in CONTEXT_TYPES:
        raise QrError(f"{context_type!r} is not a KSeF context type; use one of {', '.join(CONTEXT_TYPES)}")
    serial = (signer.certificate_serial or "").strip()
    if not serial:
        raise QrError("the offline certificate serial number is missing")
    if not (context_value or "").strip():
        raise QrError("the context identifier value is missing")
    host = _qr_host(environment)
    digest = _file_hash(xml_bytes, file_hash)
    unsigned = f"{host}/certificate/{context_type}/{context_value.strip()}/{_nip(seller_nip)}/{serial}/{digest}"
    to_sign = unsigned.removeprefix("https://").rstrip("/")
    return f"{unsigned}/{b64url(signer.sign(to_sign.encode('utf-8')))}"


def signed_part(link: str) -> tuple[bytes, bytes]:
    """``(the bytes that were signed, the signature)`` of a KOD II link."""
    head, _, signature = link.rpartition("/")
    padded = signature + "=" * (-len(signature) % 4)
    return head.removeprefix("https://").encode("utf-8"), base64.urlsafe_b64decode(padded)


@dataclass(frozen=True)
class QrCode:
    link: str
    label: str
    svg: str


def render_svg(link: str, label: str, *, size: int = 180) -> str:
    """The QR code for ``link`` with ``label`` under it, as SVG (ISO/IEC 18004 via reportlab)."""
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing, String

    label_height = 16
    widget = QrCodeWidget(link, barLevel="M", barWidth=size, barHeight=size, y=label_height)
    drawing = Drawing(size, size + label_height)
    drawing.add(widget)
    drawing.add(String(size / 2, 3, label, textAnchor="middle", fontName="Helvetica", fontSize=9))
    return renderSVG.drawToString(drawing)


def kod_i(*, environment: str, seller_nip: str, issue_date: date, xml_bytes: bytes, ksef_number: str = "") -> QrCode:
    """KOD I with its label and image."""
    link = invoice_link(environment=environment, seller_nip=seller_nip, issue_date=issue_date, xml_bytes=xml_bytes)
    label = kod_i_label(ksef_number)
    return QrCode(link=link, label=label, svg=render_svg(link, label))


def kod_ii(
    *,
    environment: str,
    context_type: str,
    context_value: str,
    seller_nip: str,
    xml_bytes: bytes,
    signer: LinkSigner,
) -> QrCode:
    """KOD II with its label and image."""
    link = certificate_link(
        environment=environment,
        context_type=context_type,
        context_value=context_value,
        seller_nip=seller_nip,
        xml_bytes=xml_bytes,
        signer=signer,
    )
    return QrCode(link=link, label=LABEL_CERTIFICATE, svg=render_svg(link, LABEL_CERTIFICATE))


__all__ = [
    "CONTEXT_TYPES",
    "LABEL_CERTIFICATE",
    "LABEL_OFFLINE",
    "LinkSigner",
    "QrCode",
    "QrError",
    "SoftwareLinkSigner",
    "b64url",
    "certificate_link",
    "invoice_hash",
    "invoice_link",
    "kod_i",
    "kod_i_label",
    "kod_ii",
    "render_svg",
    "signed_part",
]
