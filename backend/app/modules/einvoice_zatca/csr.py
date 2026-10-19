# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The certificate signing request an EGS unit sends to get its CSID.

Built the way the ZATCA SDK 238-R3.3.8 builds it (``CsrGenerationService``),
field for field, because the onboarding API compares the request with what the
SDK would have produced:

* subject ``C, OU, O, CN`` in that order;
* the Microsoft certificate template extension (1.3.6.1.4.1.311.20.2) with a
  UTF8String naming the environment: ``TSTZATCA-Code-Signing`` on the
  developer portal, ``PREZATCA-Code-Signing`` on simulation and
  ``ZATCA-Code-Signing`` in production;
* a subjectAltName holding one directory name with ``SN`` (the solution, model
  and serial, ``1-..|2-..|3-..``), ``UID`` (the VAT number), ``title`` (four
  invoice-type flags: standard, simplified, then two reserved), the
  ``registeredAddress`` and the ``businessCategory``;
* an ECDSA key on secp256k1, signed with SHA-256.

The API takes the PEM text base64-encoded once more. The same input checks the
SDK runs are run here first, so a request ZATCA would refuse never leaves.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

TEMPLATE_OID = ObjectIdentifier("1.3.6.1.4.1.311.20.2")
OID_SN = ObjectIdentifier("2.5.4.4")
OID_UID = ObjectIdentifier("0.9.2342.19200300.100.1.1")
OID_TITLE = ObjectIdentifier("2.5.4.12")
OID_REGISTERED_ADDRESS = ObjectIdentifier("2.5.4.26")
OID_BUSINESS_CATEGORY = ObjectIdentifier("2.5.4.15")

TEMPLATES: dict[str, str] = {
    "developer_portal": "TSTZATCA-Code-Signing",
    "simulation": "PREZATCA-Code-Signing",
    "production": "ZATCA-Code-Signing",
}

_SERIAL = re.compile(r"^1-(.+)\|2-(.+)\|3-(.+)$")
_INVOICE_TYPE = re.compile(r"^[01]{4}$")
# The characters the SDK refuses in the names (application.properties).
_SPECIAL = re.compile(r"[!@#$%&*_<]")


class CsrError(ValueError):
    """The CSR fields are not what ZATCA accepts."""


@dataclass(frozen=True)
class CsrFields:
    common_name: str
    serial_number: str
    vat_number: str
    organization_unit: str
    organization_name: str
    invoice_type: str = "1100"
    location: str = ""
    industry: str = ""
    country: str = "SA"

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> CsrFields:
        def text(key: str, default: str = "") -> str:
            return str(raw.get(key) or default).strip()

        return cls(
            common_name=text("common_name"),
            serial_number=text("serial_number"),
            vat_number=text("vat_number"),
            organization_unit=text("organization_unit"),
            organization_name=text("organization_name"),
            invoice_type=text("invoice_type", "1100"),
            location=text("location"),
            industry=text("industry"),
            country=text("country", "SA").upper(),
        )

    def problems(self) -> list[str]:
        """The SDK's own input checks, in its words where it has them."""
        found: list[str] = []
        required = {
            "common name": self.common_name,
            "serial number": self.serial_number,
            "VAT number (organization identifier)": self.vat_number,
            "organization unit": self.organization_unit,
            "organization name": self.organization_name,
            "invoice type": self.invoice_type,
            "location": self.location,
            "industry": self.industry,
        }
        found.extend(f"the {label} is required" for label, value in required.items() if not value)
        if self.serial_number and ("=" in self.serial_number or not _SERIAL.match(self.serial_number)):
            found.append("the serial number must read 1-<solution>|2-<model>|3-<serial> and contain no '='")
        vat = self.vat_number
        if vat and not (len(vat) == 15 and vat.isdigit() and vat[0] == "3" and vat[-1] == "3"):
            found.append("the VAT number must be 15 digits starting and ending with 3")
        elif vat and vat[10] == "1" and len(self.organization_unit) != 10:
            found.append(
                "for a VAT group the organization unit must be the 10-digit TIN of the member whose unit this is"
            )
        if not 2 <= len(self.country) <= 3:
            found.append("the country code must have two or three letters")
        if self.invoice_type and not _INVOICE_TYPE.match(self.invoice_type):
            found.append("the invoice type must be four 0/1 flags, for example 1100 for standard and simplified")
        for label, value in (
            ("common name", self.common_name),
            ("organization unit", self.organization_unit),
            ("organization name", self.organization_name),
            ("location", self.location),
            ("industry", self.industry),
        ):
            if value and _SPECIAL.search(value):
                found.append(f"the {label} must not contain any of ! @ # $ % & * _ <")
        return found


def _utf8_string(value: str) -> bytes:
    """DER of an ASN.1 UTF8String (short or long form length)."""
    body = value.encode("utf-8")
    if len(body) < 0x80:
        return bytes([0x0C, len(body)]) + body
    length = len(body).to_bytes((len(body).bit_length() + 7) // 8, "big")
    return bytes([0x0C, 0x80 | len(length)]) + length + body


def build_csr(fields: CsrFields, private_key: ec.EllipticCurvePrivateKey, *, environment: str) -> str:
    """The CSR as PEM text. Raises :class:`CsrError` on fields ZATCA would refuse."""
    problems = fields.problems()
    template = TEMPLATES.get(environment)
    if template is None:
        problems.append(f"unknown environment {environment!r}; use one of {', '.join(TEMPLATES)}")
    if problems:
        raise CsrError("; ".join(problems))
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, fields.country),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, fields.organization_unit),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, fields.organization_name),
            x509.NameAttribute(NameOID.COMMON_NAME, fields.common_name),
        ]
    )
    directory = x509.Name(
        [
            x509.NameAttribute(OID_SN, fields.serial_number),
            x509.NameAttribute(OID_UID, fields.vat_number),
            x509.NameAttribute(OID_TITLE, fields.invoice_type),
            x509.NameAttribute(OID_REGISTERED_ADDRESS, fields.location),
            x509.NameAttribute(OID_BUSINESS_CATEGORY, fields.industry),
        ]
    )
    request = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.UnrecognizedExtension(TEMPLATE_OID, _utf8_string(str(template))), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DirectoryName(directory)]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    return request.public_bytes(serialization.Encoding.PEM).decode("ascii")


def csr_for_api(csr_pem: str) -> str:
    """The value of the ``csr`` member: the PEM text, base64-encoded."""
    return base64.b64encode(csr_pem.encode("ascii")).decode("ascii")


def read_csr(csr_pem: str) -> x509.CertificateSigningRequest:
    """Parse a CSR an operator supplied (for a key held outside the platform)."""
    try:
        return x509.load_pem_x509_csr(csr_pem.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise CsrError(f"The CSR is not a PEM certificate request: {exc}") from exc


__all__ = [
    "TEMPLATES",
    "TEMPLATE_OID",
    "CsrError",
    "CsrFields",
    "build_csr",
    "csr_for_api",
    "read_csr",
]
