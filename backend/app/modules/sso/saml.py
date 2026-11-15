# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SAML 2.0 service provider: AuthnRequest, SP metadata and Response validation.

Signature checking uses the optional ``signxml`` package (extra ``[saml]``). Only the
element covered by a valid signature, made with the configured IdP certificate, is read:
anything outside it is ignored, which defeats signature wrapping. Unsigned, expired,
wrong-audience, wrong-recipient and unsolicited responses are refused.
"""

from __future__ import annotations

import base64
import secrets
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit
from xml.sax.saxutils import escape, quoteattr

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}
_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
_BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
_MAX_RESPONSE_BYTES = 256 * 1024


class SamlError(Exception):
    """A response was refused; ``code`` is the i18n suffix under ``sso.errors``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def saml_available() -> bool:
    """True when the optional signature library is installed."""
    try:
        import lxml.etree  # noqa: F401
        import signxml  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class SamlAssertion:
    """Facts read from the signed assertion only."""

    assertion_id: str
    name_id: str
    in_response_to: str
    not_on_or_after: datetime
    session_index: str | None = None
    attributes: dict[str, list[str]] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise SamlError("invalid_response", "Unparseable timestamp in assertion.") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def new_request_id() -> str:
    """An xs:ID value (must not start with a digit)."""
    return "_" + secrets.token_hex(20)


def build_authn_request(
    *, request_id: str, sp_entity_id: str, acs_url: str, idp_sso_url: str, relay_state: str, now: datetime | None = None
) -> str:
    """Return the IdP redirect URL carrying a deflated AuthnRequest (HTTP-Redirect binding)."""
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="{NS["samlp"]}" xmlns:saml="{NS["saml"]}" '
        f'ID={quoteattr(request_id)} Version="2.0" IssueInstant={quoteattr(_iso(now or _now()))} '
        f"Destination={quoteattr(idp_sso_url)} AssertionConsumerServiceURL={quoteattr(acs_url)} "
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f"<saml:Issuer>{escape(sp_entity_id)}</saml:Issuer>"
        '<samlp:NameIDPolicy AllowCreate="true" '
        'Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"/>'
        "</samlp:AuthnRequest>"
    )
    deflated = zlib.compress(xml.encode("utf-8"))[2:-4]  # raw DEFLATE, per SAML bindings 3.4.4.1
    query = urlencode({"SAMLRequest": base64.b64encode(deflated).decode("ascii"), "RelayState": relay_state})
    sep = "&" if "?" in idp_sso_url else "?"
    return f"{idp_sso_url}{sep}{query}"


def build_sp_metadata(*, sp_entity_id: str, acs_url: str) -> str:
    """SP metadata document the IdP admin imports."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID={quoteattr(sp_entity_id)}>'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        "<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>"
        '<md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location={quoteattr(acs_url)} index="0" isDefault="true"/>'
        "</md:SPSSODescriptor></md:EntityDescriptor>"
    )


def _parse(raw: bytes) -> Any:
    from lxml import etree

    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise SamlError("invalid_response", "DTDs are not allowed in SAML responses.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_comments=False)
    try:
        return etree.fromstring(raw, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise SamlError("invalid_response", "SAML response is not well-formed XML.") from exc


def _verify_signed_element(root: Any, idp_cert_pem: str) -> Any:
    """Return the element covered by a valid signature from *idp_cert_pem*, or raise."""
    from signxml import XMLVerifier
    from signxml.exceptions import InvalidInput, InvalidSignature

    if root.find(".//ds:Signature", NS) is None:
        raise SamlError("unsigned", "SAML response carries no signature.")
    try:
        result = XMLVerifier().verify(root, x509_cert=idp_cert_pem)
    except (InvalidSignature, InvalidInput) as exc:
        raise SamlError("bad_signature", "SAML signature is invalid or not made by the configured IdP.") from exc
    except Exception as exc:  # signxml raises lxml / cryptography errors on malformed input
        raise SamlError("bad_signature", "SAML signature could not be verified.") from exc
    signed = result[0].signed_xml if isinstance(result, list) else result.signed_xml
    return signed


def validate_response(
    saml_response_b64: str,
    *,
    idp_entity_id: str,
    idp_cert_pem: str,
    sp_entity_id: str,
    acs_url: str,
    clock_skew_seconds: int = 120,
    allow_unsolicited: bool = False,
    now: datetime | None = None,
) -> SamlAssertion:
    """Validate a POSTed SAMLResponse and return the signed assertion's facts.

    Checks: well-formed, no DTD, Status Success, signature by the configured certificate
    over the Response or the Assertion, exactly one assertion inside the signed element,
    Issuer, Conditions window with *clock_skew_seconds*, Audience, bearer
    SubjectConfirmation with Recipient and NotOnOrAfter, and an InResponseTo value unless
    *allow_unsolicited* (IdP-initiated sign-in) is set. The Response element's InResponseTo, when
    present, must equal the assertion's. Replay of the assertion ID and the match of InResponseTo are checked by the caller.
    """
    if not saml_available():
        raise SamlError("saml_unavailable", "SAML support is not installed on this server.")
    try:
        raw = base64.b64decode(saml_response_b64, validate=False)
    except (ValueError, TypeError) as exc:
        raise SamlError("invalid_response", "SAMLResponse is not base64.") from exc
    if not raw or len(raw) > _MAX_RESPONSE_BYTES:
        raise SamlError("invalid_response", "SAMLResponse is empty or too large.")
    root = _parse(raw)
    if root.tag != f"{{{NS['samlp']}}}Response":
        raise SamlError("invalid_response", "Document is not a SAML Response.")
    status = root.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or status.get("Value") != _SUCCESS:
        raise SamlError("idp_refused", "The identity provider did not authenticate the user.")
    if root.find(".//saml:EncryptedAssertion", NS) is not None:
        raise SamlError("encrypted_unsupported", "Encrypted assertions are not supported; send signed ones.")

    signed = _verify_signed_element(root, idp_cert_pem)
    if signed.tag == f"{{{NS['saml']}}}Assertion":
        assertion = signed
    elif signed.tag == f"{{{NS['samlp']}}}Response":
        found = signed.findall("saml:Assertion", NS)
        if len(found) != 1:
            raise SamlError("invalid_response", "Signed response must hold exactly one assertion.")
        assertion = found[0]
    else:
        raise SamlError("bad_signature", "Signature covers neither the response nor the assertion.")

    skew = timedelta(seconds=max(0, int(clock_skew_seconds)))
    now = now or _now()

    issuer = (assertion.findtext("saml:Issuer", namespaces=NS) or "").strip()
    if issuer != idp_entity_id:
        raise SamlError("wrong_issuer", "Assertion issuer does not match the configured IdP.")

    conditions = assertion.find("saml:Conditions", NS)
    if conditions is None:
        raise SamlError("invalid_response", "Assertion has no Conditions.")
    not_before = _parse_time(conditions.get("NotBefore"))
    not_after = _parse_time(conditions.get("NotOnOrAfter"))
    if not_after is None:
        raise SamlError("invalid_response", "Assertion Conditions lack NotOnOrAfter.")
    if not_before is not None and now + skew < not_before:
        raise SamlError("not_yet_valid", "Assertion is not valid yet.")
    if now - skew >= not_after:
        raise SamlError("expired", "Assertion has expired.")
    audiences = [(a.text or "").strip() for a in conditions.findall("saml:AudienceRestriction/saml:Audience", NS)]
    if sp_entity_id not in audiences:
        raise SamlError("wrong_audience", "Assertion is not addressed to this service provider.")

    subject = assertion.find("saml:Subject", NS)
    name_id = (subject.findtext("saml:NameID", namespaces=NS) if subject is not None else "") or ""
    if not name_id.strip():
        raise SamlError("invalid_response", "Assertion has no NameID.")
    in_response_to = ""
    confirmed = False
    for sc in subject.findall("saml:SubjectConfirmation", NS):
        if sc.get("Method") != _BEARER:
            continue
        data = sc.find("saml:SubjectConfirmationData", NS)
        if data is None:
            continue
        if data.get("Recipient") != acs_url:
            continue
        sc_after = _parse_time(data.get("NotOnOrAfter"))
        if sc_after is None or now - skew >= sc_after:
            continue
        in_response_to = data.get("InResponseTo") or ""
        confirmed = True
        break
    if not confirmed:
        raise SamlError("wrong_recipient", "No valid bearer confirmation for this endpoint.")
    outer_irt = root.get("InResponseTo") or ""
    if outer_irt and in_response_to and outer_irt != in_response_to:
        raise SamlError("invalid_response", "Response and assertion answer different requests.")
    in_response_to = in_response_to or outer_irt
    if not in_response_to and not allow_unsolicited:
        raise SamlError("unsolicited", "IdP-initiated sign-in is not accepted; start from the login page.")

    attrs: dict[str, list[str]] = {}
    for attr in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        name = attr.get("Name") or ""
        values = [(v.text or "").strip() for v in attr.findall("saml:AttributeValue", NS)]
        attrs.setdefault(name, []).extend(v for v in values if v)
        friendly = attr.get("FriendlyName")
        if friendly and friendly != name:
            attrs.setdefault(friendly, []).extend(v for v in values if v)
    authn = assertion.find("saml:AuthnStatement", NS)
    return SamlAssertion(
        assertion_id=assertion.get("ID") or "",
        name_id=name_id.strip(),
        in_response_to=in_response_to,
        not_on_or_after=not_after,
        session_index=authn.get("SessionIndex") if authn is not None else None,
        attributes=attrs,
    )


REQUEST_COOKIE = "oe_sso_saml_request"
REQUEST_COOKIE_TTL = timedelta(minutes=10)


def cookie_path(acs_url: str) -> str:
    """The ACS path, so the request cookie is sent only to the endpoint that reads it."""
    return urlsplit(acs_url).path or "/"


def sign_request_id(settings: Any, slug: str, request_id: str) -> str:
    """Short-lived signed token binding the AuthnRequest ID to this browser."""
    from app.core.jwt_keys import encode_jwt

    now = _now()
    payload = {"type": "sso_saml_request", "slug": slug, "rid": request_id, "iat": now, "exp": now + REQUEST_COOKIE_TTL}
    return encode_jwt(payload, settings)


def verify_request_id(settings: Any, slug: str, token: str | None) -> str | None:
    """The AuthnRequest ID from a cookie token, or None when absent, expired, forged or for another provider."""
    if not token:
        return None
    from app.core.jwt_keys import decode_jwt

    try:
        claims = decode_jwt(token, settings)
    except Exception:
        return None
    if claims.get("type") != "sso_saml_request" or claims.get("slug") != slug:
        return None
    rid = claims.get("rid")
    return rid if isinstance(rid, str) else None
