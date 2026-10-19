# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who applies the cryptographic stamp, behind one small interface.

A :class:`Signer` signs a message with ECDSA over SHA-256 and shows its
certificate. Where the private key lives is the signer's business:

``stored_key``
    The key the package generated for an EGS unit at onboarding, kept
    encrypted at rest (:mod:`app.core.crypto`) and never exported, because the
    Fatoora rules list exporting a stamping key as a prohibited function.
``external_http``
    The deployment's own signing service (typically in front of an HSM): the
    package posts the message, base64, and gets the DER signature back. No
    native PKCS#11 dependency enters the platform for it.
``test``
    A throwaway secp256k1 key and a self-signed certificate made in process.
    Refused for a live registration: a document stamped by it is a document no
    authority could ever have accepted.

The curve is secp256k1. The Security Features standard says "ECDSA, 256 bit";
ZATCA's CA issues secp256k1 certificates and its SDK signs with that curve.
``cryptography`` (already in the lockfile through ``python-jose``) supports it.
"""

from __future__ import annotations

import base64
import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.url_safety import UnsafeUrlError, resolve_and_validate_ai_provider_url

SIGNER_TEST = "test"
SIGNER_STORED_KEY = "stored_key"
SIGNER_EXTERNAL_HTTP = "external_http"
SIGNER_KINDS: tuple[str, ...] = (SIGNER_STORED_KEY, SIGNER_EXTERNAL_HTTP, SIGNER_TEST)

CURVE = ec.SECP256K1()


class SigningError(RuntimeError):
    """The signer could not produce a signature, or is not allowed to."""


@dataclass(frozen=True)
class CertificateInfo:
    """What the stamp and the QR need from the certificate."""

    # The DER, base64, one line: the content of ``ds:X509Certificate``.
    certificate_b64: str
    issuer_name: str
    serial_number: str
    # SubjectPublicKeyInfo DER (QR tag 8).
    public_key_der: bytes
    # The CA's signature over the certificate (QR tag 9).
    certificate_signature: bytes
    not_after: dt.datetime

    @property
    def certificate(self) -> x509.Certificate:
        return x509.load_der_x509_certificate(base64.b64decode(self.certificate_b64))


def issuer_name_text(name: x509.Name) -> str:
    """The issuer as ZATCA writes it: most specific RDN first, ``", "`` between.

    The official samples read ``CN=PRZEINVOICESCA4-CA, DC=extgazt, DC=gov,
    DC=local`` for a certificate whose issuer is encoded DC=local first.
    """
    return ", ".join(rdn.rfc4514_string() for rdn in reversed(name.rdns))


def certificate_info(certificate: x509.Certificate | str | bytes) -> CertificateInfo:
    """Read a certificate given as an object, PEM text, base64 DER text or DER bytes."""
    if not isinstance(certificate, x509.Certificate):
        certificate = load_certificate(certificate)
    der = certificate.public_bytes(serialization.Encoding.DER)
    return CertificateInfo(
        certificate_b64=base64.b64encode(der).decode("ascii"),
        issuer_name=issuer_name_text(certificate.issuer),
        serial_number=str(certificate.serial_number),
        public_key_der=certificate.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        certificate_signature=certificate.signature,
        not_after=certificate.not_valid_after_utc,
    )


def load_certificate(value: str | bytes) -> x509.Certificate:
    """A certificate from PEM, base64 DER text, or DER bytes.

    ZATCA hands the certificate out as ``binarySecurityToken``: the base64 of
    the base64 DER text. That form is accepted too.
    """
    raw = value.encode("ascii") if isinstance(value, str) else value
    text = raw.strip()
    if text.startswith(b"-----BEGIN"):
        return x509.load_pem_x509_certificate(text)
    try:
        decoded = base64.b64decode(b"".join(text.split()), validate=True)
    except ValueError:
        return x509.load_der_x509_certificate(raw)
    if decoded[:1] == b"\x30":
        return x509.load_der_x509_certificate(decoded)
    # binarySecurityToken: one more base64 layer.
    return x509.load_der_x509_certificate(base64.b64decode(b"".join(decoded.split())))


@runtime_checkable
class Signer(Protocol):
    """Signs with ECDSA over SHA-256 and shows the certificate that verifies it."""

    kind: str

    @property
    def certificate(self) -> CertificateInfo: ...

    async def sign(self, message: bytes) -> bytes:
        """The DER-encoded ECDSA signature of SHA-256(``message``)."""
        ...


class KeySigner:
    """Signs with a private key held in memory (``stored_key`` and ``test``)."""

    def __init__(self, private_key: ec.EllipticCurvePrivateKey, certificate: x509.Certificate, *, kind: str) -> None:
        if not isinstance(private_key.curve, ec.SECP256K1):
            raise SigningError(f"The stamping key must be on secp256k1, not {private_key.curve.name}.")
        public = private_key.public_key().public_numbers()
        if certificate.public_key().public_numbers() != public:  # type: ignore[union-attr]
            raise SigningError("The certificate does not belong to this key.")
        self.kind = kind
        self._key = private_key
        self._certificate = certificate_info(certificate)

    @property
    def certificate(self) -> CertificateInfo:
        return self._certificate

    async def sign(self, message: bytes) -> bytes:
        return self._key.sign(message, ec.ECDSA(hashes.SHA256()))


class ExternalHttpSigner:
    """Asks the deployment's signing service.

    Request: ``POST {url}`` with JSON ``{"message": <base64>, "algorithm":
    "ECDSA-SHA256"}``. Answer: JSON ``{"signature": <base64 DER>}``. The
    certificate is configured beside the URL, so a service that only signs is
    enough.

    The URL comes from a unit's settings, so it passes the self-hosted endpoint
    policy of :mod:`app.core.url_safety` before every call: loopback and the
    private ranges are allowed for an agent next to the HSM, link-local and
    cloud metadata addresses are refused.
    """

    kind = SIGNER_EXTERNAL_HTTP

    def __init__(
        self,
        url: str,
        certificate: x509.Certificate | str,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
        url_guard: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        if not url.startswith("https://") and not url.startswith("http://localhost"):
            raise SigningError("An external signer is reached over https (or http://localhost for a local agent).")
        self._url = url
        self._headers = dict(headers or {})
        self._transport = transport
        self._timeout = timeout
        self._url_guard = url_guard or resolve_and_validate_ai_provider_url
        self._certificate = certificate_info(certificate)

    @property
    def certificate(self) -> CertificateInfo:
        return self._certificate

    async def sign(self, message: bytes) -> bytes:
        try:
            await self._url_guard(self._url)
        except UnsafeUrlError as exc:
            raise SigningError(f"The signing service URL is refused: {exc}") from exc
        payload = {"message": base64.b64encode(message).decode("ascii"), "algorithm": "ECDSA-SHA256"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SigningError(f"The signing service did not answer: {exc}.") from exc
        if response.status_code != 200:
            raise SigningError(f"The signing service answered {response.status_code}.")
        try:
            signature = base64.b64decode(str(response.json()["signature"]), validate=True)
        except (ValueError, KeyError, TypeError) as exc:
            raise SigningError("The signing service did not return a base64 signature.") from exc
        return signature


def generate_key() -> ec.EllipticCurvePrivateKey:
    """A new secp256k1 stamping key."""
    return ec.generate_private_key(CURVE)


def private_key_pem(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")


def load_private_key(pem: str | bytes) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode("ascii") if isinstance(pem, str) else pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise SigningError("The stored stamping key is not an EC key.")
    return key


def make_test_signer(
    *,
    common_name: str = "TST-886431145-399999999900003",
    key: ec.EllipticCurvePrivateKey | None = None,
    not_before: dt.datetime | None = None,
) -> KeySigner:
    """A throwaway key and a self-signed certificate. For sandbox and tests only."""
    key = key or generate_key()
    start = not_before or dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "SA"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Test unit"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test signer, not issued by ZATCA"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + dt.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    return KeySigner(key, certificate, kind=SIGNER_TEST)


def resolve_signer(
    kind: str,
    *,
    sandbox: bool,
    certificate: str = "",
    private_key_pem_text: str = "",
    config: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Signer:
    """The signer an EGS unit is configured for.

    ``certificate`` is the unit's active CSID certificate (any form
    :func:`load_certificate` reads). ``private_key_pem_text`` is the decrypted
    key of a ``stored_key`` unit; it never leaves this call.
    """
    config = dict(config or {})
    if kind == SIGNER_TEST:
        if not sandbox:
            raise SigningError("A test signer cannot stamp documents for a live registration.")
        if private_key_pem_text and certificate:
            return KeySigner(load_private_key(private_key_pem_text), load_certificate(certificate), kind=SIGNER_TEST)
        return make_test_signer()
    if not certificate:
        raise SigningError("The EGS unit has no CSID certificate yet; finish onboarding first.")
    if kind == SIGNER_STORED_KEY:
        if not private_key_pem_text:
            raise SigningError("The EGS unit has no stored stamping key.")
        return KeySigner(load_private_key(private_key_pem_text), load_certificate(certificate), kind=SIGNER_STORED_KEY)
    if kind == SIGNER_EXTERNAL_HTTP:
        url = str(config.get("url") or "").strip()
        if not url:
            raise SigningError("The external signer has no URL configured.")
        headers = config.get("headers") if isinstance(config.get("headers"), dict) else None
        return ExternalHttpSigner(url, load_certificate(certificate), headers=headers, transport=transport)
    raise SigningError(f"Unknown signer kind {kind!r}; use one of {', '.join(SIGNER_KINDS)}.")


def verify(public_key_der: bytes, signature: bytes, message: bytes) -> bool:
    """Whether ``signature`` is an ECDSA-SHA256 signature of ``message`` by that key."""
    from cryptography.exceptions import InvalidSignature

    key = serialization.load_der_public_key(public_key_der)
    if not isinstance(key, ec.EllipticCurvePublicKey):
        return False
    try:
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


__all__ = [
    "CURVE",
    "SIGNER_EXTERNAL_HTTP",
    "SIGNER_KINDS",
    "SIGNER_STORED_KEY",
    "SIGNER_TEST",
    "CertificateInfo",
    "ExternalHttpSigner",
    "KeySigner",
    "Signer",
    "SigningError",
    "certificate_info",
    "generate_key",
    "issuer_name_text",
    "load_certificate",
    "load_private_key",
    "make_test_signer",
    "private_key_pem",
    "resolve_signer",
    "verify",
]
