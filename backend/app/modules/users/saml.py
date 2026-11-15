"""SAML 2.0 service-provider helpers (SP-initiated, HTTP-Redirect request, HTTP-POST response).

The SAML library (python3-saml) is an optional extra: ``pip install 'openconstructionerp[saml]'``.
The import is deferred so the rest of the users module loads without it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException

from app.config import Settings
from app.core.jwt_keys import decode_jwt, encode_jwt
from app.core.self_upgrade import DESKTOP_NO_EXTRA, repair_hint
from app.modules.users.oidc import oidc_error

INSTALL_HINT = repair_hint(
    "SAML sign-in needs the optional python3-saml package: pip install 'openconstructionerp[saml]'",
    DESKTOP_NO_EXTRA,
)


def require_saml_library() -> Any:
    """Return the ``onelogin.saml2.auth`` module or raise a 501 that says how to install it."""
    try:
        from onelogin.saml2 import auth
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail={
                "code": "saml_library_missing",
                "message_key": "auth.saml_errors.library_missing",
                "message": INSTALL_HINT,
            },
        ) from exc
    return auth


def build_settings(s: Settings) -> dict[str, Any]:
    """python3-saml settings dict from the application settings."""
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": s.saml_sp_entity_id,
            "assertionConsumerService": {
                "url": s.saml_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": {
            "entityId": s.saml_idp_entity_id,
            "singleSignOnService": {
                "url": s.saml_idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": s.saml_idp_x509_cert,
        },
        "security": {"wantAssertionsSigned": True, "wantMessagesSigned": False},
    }


def is_configured(s: Settings) -> bool:
    """Whether SAML is switched on and has the minimum IdP and SP values."""
    return bool(
        s.saml_enabled and s.saml_idp_sso_url and s.saml_idp_entity_id and s.saml_idp_x509_cert and s.saml_acs_url
    )


def _request_data(s: Settings, post: dict[str, Any] | None = None) -> dict[str, Any]:
    # Host, port and path come from the configured ACS URL, never from the request's Host header.
    acs = urlsplit(s.saml_acs_url)
    data: dict[str, Any] = {
        "https": "on" if acs.scheme == "https" else "off",
        "http_host": acs.hostname or "",
        "script_name": acs.path,
        "get_data": {},
        "post_data": post or {},
    }
    if acs.port:
        data["server_port"] = str(acs.port)
    return data


def login_url(s: Settings, relay_state: str | None = None) -> tuple[str, str]:
    """The IdP redirect URL for an SP-initiated sign-in and the AuthnRequest ID it carries."""
    auth = require_saml_library()
    handler = auth.OneLogin_Saml2_Auth(_request_data(s), build_settings(s))
    url = handler.login(return_to=relay_state)
    return url, handler.get_last_request_id()


def _in_response_to(handler: Any) -> str | None:
    from onelogin.saml2.xml_utils import OneLogin_Saml2_XML

    root = OneLogin_Saml2_XML.to_etree(handler.get_last_response_xml())
    return root.get("InResponseTo")


def _rejected() -> HTTPException:
    return oidc_error(401, "invalid_saml_response", "SAML response was rejected.")


def read_response(s: Settings, form: dict[str, Any], request_id: str | None) -> dict[str, Any]:
    """Validate a POSTed SAMLResponse and return the identity plus the assertion ID and expiry.

    *request_id* is the AuthnRequest ID this browser started with. Without one the response is
    unsolicited and accepted only when ``saml_allow_idp_initiated`` is on; with one, the response
    must answer exactly that request.
    """
    if not request_id and not s.saml_allow_idp_initiated:
        raise _rejected()
    auth = require_saml_library()
    handler = auth.OneLogin_Saml2_Auth(_request_data(s, form), build_settings(s))
    handler.process_response(request_id=request_id or None)
    if handler.get_errors() or not handler.is_authenticated():
        raise _rejected()
    # python3-saml skips the InResponseTo check when the response omits it.
    if request_id and _in_response_to(handler) != request_id:
        raise _rejected()
    assertion_id = handler.get_last_assertion_id()
    not_after = handler.get_last_assertion_not_on_or_after()
    if not assertion_id or not not_after:
        raise _rejected()
    attrs = handler.get_attributes()

    def first(name: str) -> str:
        values = attrs.get(name) or []
        return str(values[0]) if values else ""

    sub = handler.get_nameid() or ""
    email = first(s.saml_email_attribute) or (sub if "@" in sub else "")
    groups = [str(v) for v in attrs.get(s.saml_role_attribute, [])] if s.saml_role_attribute else []
    return {
        "sub": sub,
        "email": email,
        "name": first(s.saml_name_attribute),
        "groups": groups,
        "assertion_id": str(assertion_id),
        "expires_at": datetime.fromtimestamp(int(not_after), tz=UTC),
    }


REQUEST_COOKIE = "oe_saml_request"
REQUEST_COOKIE_TTL = timedelta(minutes=10)


def cookie_path(s: Settings) -> str:
    """The ACS path, so the request cookie is sent only to the endpoint that reads it."""
    return urlsplit(s.saml_acs_url).path or "/"


def sign_request_id(s: Settings, request_id: str) -> str:
    """Short-lived signed token carrying the AuthnRequest ID, for the browser cookie."""
    now = datetime.now(UTC)
    payload = {"type": "saml_request", "rid": request_id, "iat": now, "exp": now + REQUEST_COOKIE_TTL}
    return encode_jwt(payload, s)


def verify_request_id(s: Settings, token: str | None) -> str | None:
    """The AuthnRequest ID from a cookie token, or None when absent, expired or forged."""
    if not token:
        return None
    try:
        claims = decode_jwt(token, s)
    except Exception:
        return None
    if claims.get("type") != "saml_request" or not isinstance(claims.get("rid"), str):
        return None
    return claims["rid"]
