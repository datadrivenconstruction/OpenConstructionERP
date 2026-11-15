"""SAML sign-in is an optional extra: without python3-saml the endpoints say how to install it."""

from __future__ import annotations

import sys

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.modules.users import saml


def _settings(**kw) -> Settings:
    base = {
        "saml_enabled": True,
        "saml_sp_entity_id": "https://erp.example/sp",
        "saml_acs_url": "https://erp.example/api/v1/users/auth/saml/acs/",
        "saml_idp_entity_id": "https://idp.example/",
        "saml_idp_sso_url": "https://idp.example/sso",
        "saml_idp_x509_cert": "MIIC",
    }
    return Settings(**{**base, **kw})


def test_missing_library_raises_501_with_install_hint(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "onelogin", None)
    monkeypatch.setitem(sys.modules, "onelogin.saml2", None)
    with pytest.raises(HTTPException) as exc:
        saml.login_url(_settings())
    assert exc.value.status_code == 501
    assert exc.value.detail["code"] == "saml_library_missing"
    assert "openconstructionerp[saml]" in exc.value.detail["message"]


def test_is_configured_needs_the_idp_values() -> None:
    assert saml.is_configured(_settings())
    assert not saml.is_configured(_settings(saml_enabled=False))
    assert not saml.is_configured(_settings(saml_idp_sso_url=""))


def test_settings_dict_carries_sp_and_idp() -> None:
    cfg = saml.build_settings(_settings())
    assert cfg["sp"]["entityId"] == "https://erp.example/sp"
    assert cfg["idp"]["singleSignOnService"]["url"] == "https://idp.example/sso"
    assert cfg["strict"] is True
