# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Applying the cryptographic stamp (KSA-15) and the QR (KSA-14) to a document.

The structure is the one in the Security Features standard v1.2 §2.3 and in
every signed sample of the official SDK: an enveloped XAdES B-B signature in
``ext:UBLExtensions``, a ``cac:Signature`` pointer, and the QR as an
``AdditionalDocumentReference`` with ID ``QR``. None of the three is covered by
the invoice hash, so stamping a document does not change the hash that the
chain and the signature are built on.

What is signed is the 32-byte invoice hash itself, with ECDSA over SHA-256, not
``ds:SignedInfo``: that is how ZATCA's validator verifies the SignatureValue
(D5 of the design note). The reference to ``#xadesSignedProperties`` is there
and its digest is checked, but the signature does not cover it.
"""

from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass

from app.modules.einvoice_zatca import c14n, hashing, qr
from app.modules.einvoice_zatca.codes import (
    ALG_C14N11,
    ALG_ECDSA_SHA256,
    ALG_SHA256,
    ALG_XPATH,
    EXTENSION_URI,
    NS_DS,
    NS_SAC,
    NS_SBC,
    NS_SIG,
    NS_XADES,
    SIGNATURE_ID,
    SIGNATURE_INFORMATION_ID,
    SIGNATURE_METHOD,
    SIGNED_PROPERTIES_TYPE,
    XPATH_TRANSFORMS,
)
from app.modules.einvoice_zatca.signing import Signer


class StampError(ValueError):
    """The document cannot be stamped as it stands."""


@dataclass(frozen=True)
class Stamp:
    """What stamping produced, for the chain and the record."""

    invoice_hash: str
    signature: str
    qr: str
    signing_time: str
    certificate_serial: str


def _signing_time_text(when: dt.datetime) -> str:
    # The samples write local time without an offset, to the second.
    return when.replace(tzinfo=None, microsecond=0).isoformat()


def _signed_properties(signing_time: str, certificate_b64: str, issuer: str, serial: str) -> c14n.Element:
    props = c14n.Element("xades:SignedProperties", attrs=[("Id", "xadesSignedProperties")])
    signed = props.add("xades:SignedSignatureProperties")
    signed.add("xades:SigningTime", signing_time)
    cert = signed.add("xades:SigningCertificate").add("xades:Cert")
    digest = cert.add("xades:CertDigest")
    digest.add("ds:DigestMethod", Algorithm=ALG_SHA256)
    digest.add("ds:DigestValue", hashing.certificate_digest(certificate_b64))
    issuer_serial = cert.add("xades:IssuerSerial")
    issuer_serial.add("ds:X509IssuerName", issuer)
    issuer_serial.add("ds:X509SerialNumber", serial)
    return props


def _signature(
    *,
    invoice_hash: str,
    properties_digest: str,
    signature_value: str,
    certificate_b64: str,
    properties: c14n.Element,
) -> c14n.Element:
    signature = c14n.Element("ds:Signature", ns={"ds": NS_DS}, attrs=[("Id", "signature")])
    info = signature.add("ds:SignedInfo")
    info.add("ds:CanonicalizationMethod", Algorithm=ALG_C14N11)
    info.add("ds:SignatureMethod", Algorithm=ALG_ECDSA_SHA256)
    reference = info.add("ds:Reference", Id="invoiceSignedData", URI="")
    transforms = reference.add("ds:Transforms")
    for xpath in XPATH_TRANSFORMS:
        transforms.add("ds:Transform", Algorithm=ALG_XPATH).add("ds:XPath", xpath)
    transforms.add("ds:Transform", Algorithm=ALG_C14N11)
    reference.add("ds:DigestMethod", Algorithm=ALG_SHA256)
    reference.add("ds:DigestValue", invoice_hash)
    props_ref = c14n.Element(
        "ds:Reference", attrs=[("Type", SIGNED_PROPERTIES_TYPE), ("URI", "#xadesSignedProperties")]
    )
    info.append(props_ref)
    props_ref.add("ds:DigestMethod", Algorithm=ALG_SHA256)
    props_ref.add("ds:DigestValue", properties_digest)
    signature.add("ds:SignatureValue", signature_value)
    signature.add("ds:KeyInfo").add("ds:X509Data").add("ds:X509Certificate", certificate_b64)
    qualifying = c14n.Element("xades:QualifyingProperties", ns={"xades": NS_XADES}, attrs=[("Target", "signature")])
    signature.add("ds:Object").append(qualifying)
    qualifying.append(properties)
    return signature


def _extensions(signature: c14n.Element) -> c14n.Element:
    extensions = c14n.Element("ext:UBLExtensions")
    extension = extensions.add("ext:UBLExtension")
    extension.add("ext:ExtensionURI", EXTENSION_URI)
    documents = c14n.Element("sig:UBLDocumentSignatures", ns={"sig": NS_SIG, "sac": NS_SAC, "sbc": NS_SBC})
    extension.add("ext:ExtensionContent").append(documents)
    information = documents.add("sac:SignatureInformation")
    information.add("cbc:ID", SIGNATURE_INFORMATION_ID)
    information.add("sbc:ReferencedSignatureID", SIGNATURE_ID)
    information.append(signature)
    return extensions


def _qr_reference(text: str) -> c14n.Element:
    reference = c14n.Element("cac:AdditionalDocumentReference")
    reference.add("cbc:ID", "QR")
    reference.add("cac:Attachment").add("cbc:EmbeddedDocumentBinaryObject", text, mimeCode="text/plain")
    return reference


def _signature_pointer() -> c14n.Element:
    pointer = c14n.Element("cac:Signature")
    pointer.add("cbc:ID", SIGNATURE_ID)
    pointer.add("cbc:SignatureMethod", SIGNATURE_METHOD)
    return pointer


def _is_stamped(root: c14n.Element) -> bool:
    return root.find("ext:UBLExtensions") is not None or root.find("cac:Signature") is not None


async def apply_stamp(
    root: c14n.Element,
    signer: Signer,
    *,
    signing_time: dt.datetime,
    qr_fields: qr.QrFields,
    simplified: bool,
) -> Stamp:
    """Stamp ``root`` in place and return what was applied.

    ``qr_fields`` carries tags 1 to 5, read off the document by the caller; the
    hash, signature, public key and (for a simplified document) the
    certificate signature are filled in here.
    """
    if _is_stamped(root):
        raise StampError("The document already carries a stamp.")
    if root.find("cac:AccountingSupplierParty") is None:
        raise StampError("The document has no seller, so it is not an invoice that can be stamped.")

    digest = hashing.invoice_hash_bytes(root)
    invoice_hash = base64.b64encode(digest).decode("ascii")
    signature_value = base64.b64encode(await signer.sign(digest)).decode("ascii")
    certificate = signer.certificate
    signing_time_text = _signing_time_text(signing_time)

    properties = _signed_properties(
        signing_time_text, certificate.certificate_b64, certificate.issuer_name, certificate.serial_number
    )
    written = c14n.canonicalize(properties).decode("utf-8")
    signature = _signature(
        invoice_hash=invoice_hash,
        properties_digest=hashing.signed_properties_digest(written),
        signature_value=signature_value,
        certificate_b64=certificate.certificate_b64,
        properties=properties,
    )

    qr_text = qr.encode(
        qr.QrFields(
            seller_name=qr_fields.seller_name,
            vat_number=qr_fields.vat_number,
            timestamp=qr_fields.timestamp,
            total_with_vat=qr_fields.total_with_vat,
            vat_total=qr_fields.vat_total,
            invoice_hash=invoice_hash,
            signature=signature_value,
            public_key=certificate.public_key_der,
            certificate_signature=certificate.certificate_signature if simplified else b"",
        )
    )

    # The extensions open the document; the QR follows the last other
    # AdditionalDocumentReference and the pointer follows the QR, which is the
    # order the UBL 2.1 schema requires.
    root.children.insert(0, _extensions(signature))
    references = [
        i
        for i, c in enumerate(root.children)
        if isinstance(c, c14n.Element) and c.local == "AdditionalDocumentReference"
    ]
    if not references:
        raise StampError("The document has no ICV and PIH references to stamp after.")
    at = references[-1] + 1
    root.children.insert(at, _qr_reference(qr_text))
    root.children.insert(at + 1, _signature_pointer())

    if hashing.invoice_hash(root) != invoice_hash:  # pragma: no cover - a broken exclusion would land here
        raise StampError("Stamping changed the invoice hash; the stamp would not verify.")
    return Stamp(
        invoice_hash=invoice_hash,
        signature=signature_value,
        qr=qr_text,
        signing_time=signing_time_text,
        certificate_serial=certificate.serial_number,
    )


__all__ = ["Stamp", "StampError", "apply_stamp"]
