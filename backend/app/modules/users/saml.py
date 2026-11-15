"""SAML 2.0 service-provider helpers (SP-initiated, HTTP-Redirect request, HTTP-POST response).

The SAML library (python3-saml) is an optional extra: ``pip install 'openconstructionerp[saml]'``.
The import is deferred so the rest of the users module loads without it.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.config import Settings
from app.modules.users.oidc import oidc_error

INSTALL_HINT = "SAML sign-in needs the optional python3-saml package: pip install 'openconstructionerp[saml]'"


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


def _request_data(host: str, path: str, post: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"https": "on", "http_host": host, "script_name": path, "get_data": {}, "post_data": post or {}}


def login_url(s: Settings, host: str, path: str, relay_state: str | None = None) -> str:
    """The IdP redirect URL for an SP-initiated sign-in."""
    auth = require_saml_library()
    return auth.OneLogin_Saml2_Auth(_request_data(host, path), build_settings(s)).login(return_to=relay_state)


def read_response(s: Settings, host: str, path: str, form: dict[str, Any]) -> dict[str, Any]:
    """Validate a POSTed SAMLResponse and return ``{sub, email, name, groups}``."""
    auth = require_saml_library()
    handler = auth.OneLogin_Saml2_Auth(_request_data(host, path, form), build_settings(s))
    handler.process_response()
    if handler.get_errors() or not handler.is_authenticated():
        raise oidc_error(401, "invalid_saml_response", "SAML response was rejected.")
    attrs = handler.get_attributes()

    def first(name: str) -> str:
        values = attrs.get(name) or []
        return str(values[0]) if values else ""

    sub = handler.get_nameid() or ""
    email = first(s.saml_email_attribute) or (sub if "@" in sub else "")
    groups = [str(v) for v in attrs.get(s.saml_role_attribute, [])] if s.saml_role_attribute else []
    return {"sub": sub, "email": email, "name": first(s.saml_name_attribute), "groups": groups}
