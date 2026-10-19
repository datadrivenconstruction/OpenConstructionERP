# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The three digests a ZATCA document carries, computed the way ZATCA checks them.

``invoice_hash``
    SHA-256 of the C14N 1.1 form of the invoice without ``ext:UBLExtensions``,
    ``cac:Signature`` and the ``AdditionalDocumentReference`` whose ID is ``QR``,
    base64 of the raw 32 bytes (BR-KSA-26; Security Features standard v1.2,
    the ``ds:Transforms`` block). It is the reference DigestValue, the PIH of the
    next document, QR tag 6, and what the signature signs.
``certificate_digest``
    The ``xades:CertDigest``: base64 of the *hex text* of SHA-256 over the
    certificate's base64 text. Not the raw digest of the DER, which is what the
    XAdES specification means. ZATCA's SDK validator recomputes it this way, and
    every official sample carries this value.
``signed_properties_digest``
    The DigestValue of the second reference: again base64 of the hex text of a
    SHA-256, over ``xades:SignedProperties`` as written in the document with
    ``xmlns:xades`` added on the element and ``xmlns:ds`` on every ``ds:`` start
    tag, and every empty element written self-closing. Whitespace counts, the
    spelling of an empty element does not: the SDK validator parses the element
    and serializes it again. Not a C14N of the subtree, which would be the
    specification's reading. Reproduced against the official samples and probed
    against the SDK validator (D5).

These departures from XAdES are ZATCA's, not ours. They are pinned to the
official samples in the tests, so nobody "corrects" them back to the
specification and breaks every signature.
"""

from __future__ import annotations

import base64
import hashlib
import re

from app.modules.einvoice_zatca import c14n
from app.modules.einvoice_zatca.codes import NS_CAC, NS_CBC, NS_DS, NS_EXT, NS_XADES


def _left_out_of_hash(element: c14n.Element, scope: dict[str, str]) -> bool:
    namespace, local = c14n.expanded(element.tag, scope)
    if namespace == NS_EXT and local == "UBLExtensions":
        return True
    if namespace == NS_CAC and local == "Signature":
        return True
    if namespace == NS_CAC and local == "AdditionalDocumentReference":
        for child in element.elements():
            child_ns, child_local = c14n.expanded(child.tag, {**scope, **child.ns})
            if child_ns == NS_CBC and child_local == "ID":
                return child.text().strip() == "QR"
    return False


def hashed_form(root: c14n.Element) -> bytes:
    """The bytes the invoice hash is taken over."""
    return c14n.canonicalize(root, exclude=_left_out_of_hash)


def invoice_hash_bytes(root: c14n.Element) -> bytes:
    """The raw 32-byte SHA-256 of the invoice."""
    return hashlib.sha256(hashed_form(root)).digest()


def invoice_hash(root: c14n.Element) -> str:
    """The invoice hash as ZATCA writes it: base64 of the raw digest."""
    return base64.b64encode(invoice_hash_bytes(root)).decode("ascii")


def _hex_digest_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).hexdigest().encode("ascii")).decode("ascii")


def certificate_digest(certificate_b64: str) -> str:
    """``xades:CertDigest``: base64 of hex SHA-256 over the certificate's base64 text."""
    return _hex_digest_b64("".join(certificate_b64.split()).encode("ascii"))


_DS_START = re.compile(r"<ds:([A-Za-z0-9]+)")
_EMPTY = re.compile(r"<((?:ds|xades):[A-Za-z0-9]+)((?:\s[^<>]*?)?)></\1>")


def signed_properties_text(written: str) -> str:
    """The text ZATCA digests for ``xades:SignedProperties``.

    ``written`` is the element exactly as it stands in the document, from
    ``<xades:SignedProperties`` to its end tag. The SDK hashes that text with
    the two namespace declarations the element relies on written in and empty
    elements self-closing, whichever way the document spells them.
    """
    if not written.startswith("<xades:SignedProperties"):
        raise ValueError("Expected the text of an xades:SignedProperties element.")
    text = _EMPTY.sub(r"<\1\2/>", written)
    text = text.replace("<xades:SignedProperties", f'<xades:SignedProperties xmlns:xades="{NS_XADES}"', 1)
    return _DS_START.sub(lambda m: f'<ds:{m.group(1)} xmlns:ds="{NS_DS}"', text)


def signed_properties_digest(written: str) -> str:
    """The DigestValue of the ``#xadesSignedProperties`` reference."""
    return _hex_digest_b64(signed_properties_text(written).encode("utf-8"))


def written_signed_properties(document_text: str) -> str:
    """The ``xades:SignedProperties`` element as it stands in a document's text, or ``""``."""
    match = re.search(r"<xades:SignedProperties\b.*?</xades:SignedProperties>", document_text, re.S)
    return match.group(0) if match else ""


__all__ = [
    "certificate_digest",
    "hashed_form",
    "invoice_hash",
    "invoice_hash_bytes",
    "signed_properties_digest",
    "signed_properties_text",
    "written_signed_properties",
]
