"""SAML ACS: browsers get fragment redirects (tokens or an error code), JSON clients the token pair."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.modules.users import oidc, saml
from app.modules.users import router as users_router

HTML = {"accept": "text/html,application/xhtml+xml"}
INFO = {"sub": "u1", "email": "a@b.test", "name": "A", "groups": []}


class _Service:
    def __init__(self, error: HTTPException | None = None) -> None:
        self.error = error

    async def oidc_login(self, **_kw):
        if self.error:
            raise self.error
        return SimpleNamespace(access_token="AT", refresh_token="RT", token_type="bearer")


def _client(monkeypatch, service: _Service, *, info=INFO, read_error: HTTPException | None = None) -> TestClient:
    cfg = Settings(
        saml_enabled=True,
        saml_sp_entity_id="https://erp.example/sp",
        saml_acs_url="https://erp.example/acs",
        saml_idp_entity_id="https://idp.example/",
        saml_idp_sso_url="https://idp.example/sso",
        saml_idp_x509_cert="MIIC",
    )
    monkeypatch.setattr("app.config.get_settings", lambda: cfg)

    def read_response(*_a, **_k):
        if read_error:
            raise read_error
        return info

    monkeypatch.setattr(saml, "read_response", read_response)
    app = FastAPI()
    app.include_router(users_router.router, prefix="/api/v1/users")
    app.dependency_overrides[users_router._get_service] = lambda: service
    return TestClient(app, follow_redirects=False)


def _post(client: TestClient, headers: dict[str, str]):
    return client.post("/api/v1/users/auth/saml/acs/", data={"SAMLResponse": "x"}, headers=headers)


def test_html_success_redirects_with_tokens_in_fragment(monkeypatch) -> None:
    r = _post(_client(monkeypatch, _Service()), HTML)
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/saml/callback#access_token=AT&refresh_token=RT"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        (
            {"read_error": oidc.oidc_error(401, "invalid_saml_response", "SAML response was rejected.")},
            "invalid_saml_response",
        ),
        (
            {
                "read_error": HTTPException(
                    501, detail={"code": "saml_library_missing", "message": "pip install secret-hint"}
                )
            },
            "saml_library_missing",
        ),
        ({"info": {**INFO, "email": ""}}, "missing_claims"),
    ],
)
def test_html_failure_redirects_with_error_code_only(monkeypatch, kwargs, code) -> None:
    r = _post(_client(monkeypatch, _Service(), **kwargs), HTML)
    assert r.status_code == 303
    assert r.headers["location"] == f"/auth/saml/callback#error={code}"


def test_html_disabled_user_redirects_with_account_disabled(monkeypatch) -> None:
    service = _Service(HTTPException(403, detail="Account is deactivated."))
    r = _post(_client(monkeypatch, service), HTML)
    assert r.headers["location"] == "/auth/saml/callback#error=account_disabled"


def test_json_client_still_gets_token_pair(monkeypatch) -> None:
    r = _post(_client(monkeypatch, _Service()), {"accept": "application/json"})
    assert r.status_code == 200
    assert r.json()["access_token"] == "AT"


def test_json_client_still_gets_error_status(monkeypatch) -> None:
    err = oidc.oidc_error(401, "invalid_saml_response", "SAML response was rejected.")
    r = _post(_client(monkeypatch, _Service(), read_error=err), {"accept": "application/json"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_saml_response"
