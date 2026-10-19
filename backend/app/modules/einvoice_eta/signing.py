# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Signing an ETA document: CAdES-BES over SHA-256 with an eSeal certificate.

Source: https://sdk.invoicing.eta.gov.eg/signature-creation/ and the SDK's
signed sample ``one-doc-I.json``. The steps:

1. serialize the document canonically (:mod:`.serialization`);
2. SHA-256 over those UTF-8 bytes;
3. a detached CAdES-BES signature: CMS SignedData, version 3, content type
   ``digestedData`` with no content, the signer certificate included, and four
   signed attributes (content type, signing time, message digest,
   signingCertificateV2);
4. Base64 of the DER goes into ``signatures[{"signatureType": "I", "value": ...}]``.

Where the private key lives
===========================
Never here. The eSeal is on a USB token or an HSM issued by an ITIDA licensed
authority, and the private key does not leave it. So the work is split in two:

* :class:`CadesBesSigner` assembles the structure in process. It is pure
  bytes, small, and pinned byte for byte to ETA's own signed sample.
* a :class:`KeyOperation` performs the one RSA operation, over the DER of the
  signed attributes. :class:`Pkcs11Key` does it on a token or HSM through its
  PKCS#11 library; :class:`SoftwareKey` does it with a key in memory, which is
  for tests and nothing else.

A deployment where the token is plugged into a different machine than the
server uses :class:`ExternalHttpSigner`: the platform sends the canonical bytes
to a signing service on that machine and receives the finished signature.

Pluggable
=========
``signer_factories`` maps a ``kind`` from the profile settings to a factory.
A partner with another signing arrangement registers a factory under a new kind
from their own module; nothing here changes.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Protocol

from app.modules.einvoice_eta import der

OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
OID_DIGESTED_DATA = "1.2.840.113549.1.7.5"
OID_SHA256 = "2.16.840.1.101.3.4.2.1"
OID_RSA_ENCRYPTION = "1.2.840.113549.1.1.1"
OID_CONTENT_TYPE = "1.2.840.113549.1.9.3"
OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
OID_SIGNING_TIME = "1.2.840.113549.1.9.5"
OID_SIGNING_CERTIFICATE_V2 = "1.2.840.113549.1.9.16.2.47"

# The issuer inside signingCertificateV2 is a GeneralName. RFC 5035 tags a
# directory name [4]; ETA's own signed sample, the one its validator accepted,
# tags it [0]. The sample wins: it is the shape known to pass.
_ISSUER_GENERAL_NAME_TAG = 0

SIGNATURE_TYPE_ISSUER = "I"
SIGNATURE_TYPE_SERVICE_PROVIDER = "S"

SIGNER_TEST = "test"
SIGNER_PKCS11 = "pkcs11"
SIGNER_EXTERNAL_HTTP = "external_http"
SIGNER_PRESIGNED = "presigned"


class EtaSigningError(RuntimeError):
    """The document could not be signed, or the signature does not verify."""


class KeyOperation(Protocol):
    """The holder of the eSeal: hands out the certificate and signs bytes."""

    async def certificate(self) -> bytes:
        """The signer certificate, DER."""
        ...

    async def sign(self, data: bytes) -> bytes:
        """RSASSA-PKCS1-v1_5 with SHA-256 over ``data`` (PKCS#11 ``CKM_SHA256_RSA_PKCS``)."""
        ...


class EtaSigner(Protocol):
    """Turns canonical bytes into the Base64 CAdES-BES ETA expects."""

    kind: str
    # A test signer produces a structurally valid signature with a throwaway
    # key. ETA rejects it, which is correct; the adapter refuses to use one on
    # a live registration.
    is_test: bool

    async def sign(self, canonical: bytes) -> str:
        """The Base64 CAdES-BES signature over ``canonical``."""
        ...


# ── The CAdES-BES structure ──────────────────────────────────────────────────


@dataclass(frozen=True)
class _CertParts:
    der: bytes
    issuer_name: bytes
    serial: bytes


def _cert_parts(cert_der: bytes) -> _CertParts:
    """The raw issuer Name and serial INTEGER, exactly as the certificate holds them.

    Read from the bytes rather than re-encoded from a parsed certificate: a
    re-encoded name can differ in string type from the original, and then the
    issuer in the signature no longer matches the certificate it points at.
    """
    try:
        tbs = der.read(cert_der).children()[0].children()
    except (der.DerError, IndexError) as exc:
        raise EtaSigningError("The signer certificate is not a DER X.509 certificate.") from exc
    index = 1 if tbs and tbs[0].tag == 0xA0 else 0
    serial = tbs[index]
    issuer = tbs[index + 2]
    if serial.tag != der.TAG_INTEGER or issuer.tag != der.TAG_SEQUENCE:
        raise EtaSigningError("The signer certificate does not have the X.509 layout.")
    return _CertParts(der=cert_der, issuer_name=issuer.raw, serial=serial.raw)


def _algorithm(dotted: str) -> bytes:
    # No NULL parameters, as in ETA's sample.
    return der.sequence(der.oid(dotted))


def signed_attributes(cert_der: bytes, digest: bytes, signing_time: datetime) -> list[bytes]:
    """The four signed attributes, each one DER encoded Attribute."""
    parts = _cert_parts(cert_der)
    cert_hash = hashlib.sha256(cert_der).digest()
    issuer_serial = der.sequence(
        der.sequence(der.context(_ISSUER_GENERAL_NAME_TAG, parts.issuer_name)),
        parts.serial,
    )
    ess_cert_id_v2 = der.sequence(der.octet_string(cert_hash), issuer_serial)
    signing_certificate_v2 = der.sequence(der.sequence(ess_cert_id_v2))
    return [
        der.sequence(der.oid(OID_CONTENT_TYPE), der.set_of(der.oid(OID_DIGESTED_DATA))),
        der.sequence(der.oid(OID_SIGNING_TIME), der.set_of(der.utc_time(signing_time))),
        der.sequence(der.oid(OID_MESSAGE_DIGEST), der.set_of(der.octet_string(digest))),
        der.sequence(der.oid(OID_SIGNING_CERTIFICATE_V2), der.set_of(signing_certificate_v2)),
    ]


def to_be_signed(attributes: list[bytes]) -> bytes:
    """What the RSA operation covers: the attributes as a DER SET, not as [0]."""
    return der.set_of(*attributes)


def assemble(cert_der: bytes, attributes: list[bytes], signature: bytes) -> bytes:
    """The CMS ContentInfo around one signer."""
    parts = _cert_parts(cert_der)
    signer_info = der.sequence(
        der.integer(1),
        der.sequence(parts.issuer_name, parts.serial),
        _algorithm(OID_SHA256),
        der.tlv(0xA0, b"".join(sorted(attributes))),
        _algorithm(OID_RSA_ENCRYPTION),
        der.octet_string(signature),
    )
    signed_data = der.sequence(
        der.integer(3),
        der.set_of(_algorithm(OID_SHA256)),
        der.sequence(der.oid(OID_DIGESTED_DATA)),
        der.tlv(0xA0, cert_der),
        der.set_of(signer_info),
    )
    return der.sequence(der.oid(OID_SIGNED_DATA), der.context(0, signed_data))


class CadesBesSigner:
    """CAdES-BES assembled here, the RSA operation done by a :class:`KeyOperation`."""

    def __init__(
        self,
        key: KeyOperation,
        *,
        kind: str,
        is_test: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.key = key
        self.kind = kind
        self.is_test = is_test
        self._clock = clock or (lambda: datetime.now(UTC))

    async def sign(self, canonical: bytes) -> str:
        cert = await self.key.certificate()
        attributes = signed_attributes(cert, hashlib.sha256(canonical).digest(), self._clock())
        signature = await self.key.sign(to_be_signed(attributes))
        return base64.b64encode(assemble(cert, attributes, signature)).decode("ascii")


# ── Verification ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedSignature:
    certificate: bytes
    attributes: list[bytes]
    message_digest: bytes
    signing_time: str
    signature: bytes


def parse_cades(value: str | bytes) -> ParsedSignature:
    """Take a CAdES-BES apart into the pieces this module builds it from."""
    raw = base64.b64decode(value) if isinstance(value, str) else value
    try:
        content_info = der.read(raw).children()
        if content_info[0].raw != der.oid(OID_SIGNED_DATA):
            raise EtaSigningError("The signature is not a CMS SignedData.")
        signed_data = content_info[1].children()[0].children()
        certificates = next(e for e in signed_data if e.tag == 0xA0)
        signer_infos = signed_data[-1].children()
        signer = signer_infos[0].children()
        attrs_element = next(e for e in signer if e.tag == 0xA0)
        attributes = [a.raw for a in attrs_element.children()]
        signature = signer[-1].content
    except (der.DerError, IndexError, StopIteration) as exc:
        raise EtaSigningError("The signature is not a CAdES-BES structure this module can read.") from exc

    digest = b""
    signing_time = ""
    for attribute in attrs_element.children():
        children = attribute.children()
        oid_bytes = children[0].raw
        value = children[1].children()[0]
        if oid_bytes == der.oid(OID_MESSAGE_DIGEST):
            digest = value.content
        elif oid_bytes == der.oid(OID_SIGNING_TIME):
            signing_time = value.content.decode("ascii")
    return ParsedSignature(
        certificate=certificates.children()[0].raw,
        attributes=attributes,
        message_digest=digest,
        signing_time=signing_time,
        signature=signature,
    )


def verify_cades(value: str, canonical: bytes) -> None:
    """Raise unless ``value`` is a signature over ``canonical`` by its own certificate.

    Checks the two things a signer can get wrong without noticing: that the
    message digest is the hash of these canonical bytes, and that the RSA value
    verifies against the certificate it carries. It does not check the
    certificate chain or validity dates; ETA does that against its trust list.
    """
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    parsed = parse_cades(value)
    if parsed.message_digest != hashlib.sha256(canonical).digest():
        raise EtaSigningError("The signature covers a different document: its message digest does not match.")
    public_key = x509.load_der_x509_certificate(parsed.certificate).public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise EtaSigningError("ETA requires an RSA eSeal certificate.")
    try:
        public_key.verify(
            parsed.signature,
            der.tlv(der.TAG_SET, b"".join(parsed.attributes)),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise EtaSigningError("The RSA signature does not verify against the signer certificate.") from exc


# ── Key operations ───────────────────────────────────────────────────────────


class SoftwareKey:
    """A private key in memory. For tests only: an eSeal never leaves its token."""

    def __init__(self, private_key: Any, certificate_der: bytes) -> None:
        self._key = private_key
        self._cert = certificate_der

    async def certificate(self) -> bytes:
        return self._cert

    async def sign(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        return self._key.sign(data, padding.PKCS1v15(), hashes.SHA256())


@cache
def _throwaway_key() -> tuple[Any, bytes]:
    """A self-signed RSA key pair, generated once per process."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "EG"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenConstructionERP test signer"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Not an eSeal"),
        ]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.DER)


def make_test_signer(*, clock: Callable[[], datetime] | None = None) -> CadesBesSigner:
    """A signer with a throwaway key. ETA rejects what it signs; that is the point."""
    key, cert = _throwaway_key()
    return CadesBesSigner(SoftwareKey(key, cert), kind=SIGNER_TEST, is_test=True, clock=clock)


class Pkcs11Key:
    """The eSeal on a USB token or HSM, through its vendor PKCS#11 library.

    Needs the optional ``python-pkcs11`` package on the machine the token is
    attached to. It is not a platform dependency: a deployment that signs
    elsewhere never imports it. The PIN is read from the environment variable
    the settings name and is never stored.

    Settings: ``library`` (path to the vendor's PKCS#11 module), ``token_label``,
    ``key_label``, ``certificate_label`` (defaults to ``key_label``), ``pin_env``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.library = str(config.get("library") or "").strip()
        self.token_label = str(config.get("token_label") or "").strip()
        self.key_label = str(config.get("key_label") or "").strip()
        self.certificate_label = str(config.get("certificate_label") or self.key_label).strip()
        self.pin_env = str(config.get("pin_env") or "").strip()
        missing = [
            name
            for name, value in (
                ("library", self.library),
                ("token_label", self.token_label),
                ("key_label", self.key_label),
                ("pin_env", self.pin_env),
            )
            if not value
        ]
        if missing:
            raise EtaSigningError(f"The PKCS#11 signer settings are missing: {', '.join(missing)}.")

    def _module(self) -> Any:
        try:
            import pkcs11  # type: ignore[import-not-found]
        except ImportError as exc:
            raise EtaSigningError(
                "The PKCS#11 signer needs the python-pkcs11 package on the machine the token is attached to "
                "(pip install python-pkcs11), or use the external_http signer from that machine instead."
            ) from exc
        return pkcs11

    def _pin(self) -> str:
        pin = os.environ.get(self.pin_env, "")
        if not pin:
            raise EtaSigningError(f"The token PIN is not set: environment variable {self.pin_env} is empty.")
        return pin

    def _certificate_sync(self) -> bytes:
        pkcs11 = self._module()
        token = pkcs11.lib(self.library).get_token(token_label=self.token_label)
        with token.open(user_pin=self._pin()) as session:
            for obj in session.get_objects(
                {
                    pkcs11.Attribute.CLASS: pkcs11.ObjectClass.CERTIFICATE,
                    pkcs11.Attribute.LABEL: self.certificate_label,
                }
            ):
                return bytes(obj[pkcs11.Attribute.VALUE])
        raise EtaSigningError(f"No certificate labelled {self.certificate_label!r} on token {self.token_label!r}.")

    def _sign_sync(self, data: bytes) -> bytes:
        pkcs11 = self._module()
        token = pkcs11.lib(self.library).get_token(token_label=self.token_label)
        with token.open(user_pin=self._pin()) as session:
            key = session.get_key(object_class=pkcs11.ObjectClass.PRIVATE_KEY, label=self.key_label)
            return bytes(key.sign(data, mechanism=pkcs11.Mechanism.SHA256_RSA_PKCS))

    async def certificate(self) -> bytes:
        return await asyncio.to_thread(self._certificate_sync)

    async def sign(self, data: bytes) -> bytes:
        return await asyncio.to_thread(self._sign_sync, data)


class ExternalHttpSigner:
    """A signing service on the machine the token is plugged into.

    The contract, which a partner implements on that machine:

        POST <url>
        {"canonical_base64": "<the canonical bytes, Base64>", "sha256_hex": "<their SHA-256>"}
        -> 200 {"signature": "<Base64 CAdES-BES>"}

    The service is expected to build the CAdES-BES itself (ETA's own signing
    tools do). The answer is verified against the canonical bytes before it is
    used, so a service that signed the wrong thing is caught here and not by
    ETA an hour later.

    The URL comes from a registration, so it passes the self-hosted endpoint
    policy of :mod:`app.core.url_safety` before every call: loopback and the
    private ranges are allowed, because the service runs next to the token,
    and link-local and cloud metadata addresses are refused.
    """

    kind = SIGNER_EXTERNAL_HTTP
    is_test = False

    def __init__(self, config: dict[str, Any], *, transport: Any = None, url_guard: Any = None) -> None:
        self.url = str(config.get("url") or "").strip()
        self._url_guard = url_guard
        if not self.url:
            raise EtaSigningError("The external signer settings need the url of the signing service.")
        self.timeout = float(config.get("timeout_seconds") or 30)
        self.token_env = str(config.get("token_env") or "").strip()
        self._transport = transport

    async def sign(self, canonical: bytes) -> str:
        import httpx

        from app.core.url_safety import UnsafeUrlError, resolve_and_validate_ai_provider_url

        guard = self._url_guard or resolve_and_validate_ai_provider_url
        try:
            await guard(self.url)
        except UnsafeUrlError as exc:
            raise EtaSigningError(f"The signing service URL {self.url} is refused: {exc}") from exc
        headers = {"Content-Type": "application/json"}
        if self.token_env and os.environ.get(self.token_env):
            headers["Authorization"] = f"Bearer {os.environ[self.token_env]}"
        body = {
            "canonical_base64": base64.b64encode(canonical).decode("ascii"),
            "sha256_hex": hashlib.sha256(canonical).hexdigest(),
        }
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            response = await client.post(self.url, json=body, headers=headers)
        if response.status_code != 200:
            raise EtaSigningError(f"The signing service answered {response.status_code}: {response.text[:200]}")
        try:
            signature = str(response.json()["signature"])
        except (ValueError, KeyError, TypeError) as exc:
            raise EtaSigningError("The signing service did not return a signature member.") from exc
        verify_cades(signature, canonical)
        return signature


class PresignedSigner:
    """For payloads signed upstream by the taxpayer's own tool. Never signs."""

    kind = SIGNER_PRESIGNED
    is_test = False

    async def sign(self, canonical: bytes) -> str:
        raise EtaSigningError(
            "This registration expects documents that are already signed, and this one carries no signature."
        )


SignerFactory = Callable[[dict[str, Any]], EtaSigner]

signer_factories: dict[str, SignerFactory] = {
    SIGNER_TEST: lambda config: make_test_signer(),
    SIGNER_PKCS11: lambda config: CadesBesSigner(Pkcs11Key(config), kind=SIGNER_PKCS11),
    SIGNER_EXTERNAL_HTTP: lambda config: ExternalHttpSigner(config),
    SIGNER_PRESIGNED: lambda config: PresignedSigner(),
}


def register_signer_factory(kind: str, factory: SignerFactory) -> None:
    """Add a signing arrangement under a new kind. Overwrites by kind."""
    signer_factories[(kind or "").strip()] = factory


def resolve_signer(config: Any, *, sandbox: bool) -> EtaSigner:
    """The signer a registration's settings describe.

    Raises:
        EtaSigningError: no signer is configured, the kind is unknown, or a test
            signer is configured on a live registration.
    """
    if not isinstance(config, dict) or not str(config.get("kind") or "").strip():
        raise EtaSigningError("No signer is configured for this registration (settings.eta.signer.kind).")
    kind = str(config["kind"]).strip()
    factory = signer_factories.get(kind)
    if factory is None:
        raise EtaSigningError(f"Unknown signer kind {kind!r}; installed: {', '.join(sorted(signer_factories))}.")
    signer = factory(config)
    if signer.is_test and not sandbox:
        raise EtaSigningError(
            "A test signer cannot sign for a live registration. Configure the eSeal (pkcs11 or external_http)."
        )
    return signer


__all__ = [
    "SIGNATURE_TYPE_ISSUER",
    "SIGNATURE_TYPE_SERVICE_PROVIDER",
    "SIGNER_EXTERNAL_HTTP",
    "SIGNER_PKCS11",
    "SIGNER_PRESIGNED",
    "SIGNER_TEST",
    "CadesBesSigner",
    "EtaSigner",
    "EtaSigningError",
    "ExternalHttpSigner",
    "KeyOperation",
    "ParsedSignature",
    "Pkcs11Key",
    "PresignedSigner",
    "SoftwareKey",
    "assemble",
    "make_test_signer",
    "parse_cades",
    "register_signer_factory",
    "resolve_signer",
    "signed_attributes",
    "signer_factories",
    "to_be_signed",
    "verify_cades",
]
