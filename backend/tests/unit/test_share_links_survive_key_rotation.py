"""Share links, upload URLs and review tokens survive a signing-key rotation.

Every HMAC signature that carries no ``kid`` is signed with the current
``JWT_SECRET`` and accepted under any secret in the key ring, so moving the
old secret into ``JWT_PREVIOUS_SECRETS`` keeps already sent links working and
dropping it from the list revokes them.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.core import storage
from app.core.jwt_keys import ring_secrets
from app.modules.module_builder import review_token
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec
from app.modules.projects import router as projects_router
from app.modules.smart_views import service as smart_views_service

OLD = "old-secret-" + "a" * 40
NEW = "new-secret-" + "b" * 40
OTHER = "other-secret-" + "c" * 40


def _settings(secret: str, previous: str = "") -> Settings:
    return Settings(jwt_secret=secret, jwt_previous_secrets=previous)


@pytest.fixture
def use_settings(monkeypatch: pytest.MonkeyPatch):
    def apply(settings: Settings) -> Settings:
        monkeypatch.setattr("app.config.get_settings", lambda: settings)
        monkeypatch.setattr(review_token, "get_settings", lambda: settings)
        monkeypatch.setattr(smart_views_service, "get_settings", lambda: settings)
        return settings

    return apply


def test_ring_signs_with_current_secret_first() -> None:
    assert ring_secrets(_settings(NEW, f"{OLD}, {NEW}")) == [NEW, OLD]


# ── Project file share links ──────────────────────────────────────────────


def _file_share_token(secret: str, exp: int) -> str:
    payload_b64 = base64.urlsafe_b64encode(json.dumps({"fid": "f", "kind": "document", "exp": exp}).encode())
    payload = payload_b64.rstrip(b"=").decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode('ascii')}"


def _open_file_share(token: str, settings: Settings) -> int:
    with pytest.raises(HTTPException) as caught:
        asyncio.run(projects_router.get_share_file(token, session=None, settings=settings))
    return caught.value.status_code


def test_file_share_link_signed_with_previous_key_still_verifies() -> None:
    # An already expired link: 410 means the signature passed, 401 that it did not.
    token = _file_share_token(OLD, exp=int(time.time()) - 10)
    assert _open_file_share(token, _settings(NEW, OLD)) == 410
    assert _open_file_share(token, _settings(NEW)) == 401
    assert _open_file_share(_file_share_token(OTHER, exp=0), _settings(NEW, OLD)) == 401


def test_file_share_links_are_minted_with_current_key() -> None:
    assert projects_router._share_token_secrets(_settings(NEW, OLD))[0] == NEW


# ── Saved-view share links ────────────────────────────────────────────────


def _view_service():
    return smart_views_service.SmartViewService.__new__(smart_views_service.SmartViewService)


def test_saved_view_link_survives_rotation(use_settings) -> None:
    view_id = uuid.uuid4()
    use_settings(_settings(OLD))
    token = _view_service()._make_share_token(view_id)

    use_settings(_settings(NEW, OLD))
    assert _view_service()._decode_share_token(token) == view_id
    fresh = _view_service()._make_share_token(view_id)

    use_settings(_settings(NEW))
    assert _view_service()._decode_share_token(token) is None
    assert _view_service()._decode_share_token(fresh) == view_id


# ── Local upload URLs ─────────────────────────────────────────────────────


def test_upload_token_survives_rotation(use_settings) -> None:
    payload = {"key": "a/b.pdf", "expires_at": time.time() + 600}
    use_settings(_settings(OLD))
    token = storage._sign_local_upload_token(payload)

    use_settings(_settings(NEW, OLD))
    assert storage._verify_local_upload_token(token) is not None

    use_settings(_settings(NEW))
    assert storage._verify_local_upload_token(token) is None


# ── Module builder review tokens ──────────────────────────────────────────


def _spec() -> ModuleSpec:
    return ModuleSpec(
        key="pour_register",
        display_name="Pour Register",
        entity=EntitySpec(
            name="pour",
            display_name="Pour",
            project_scoped=False,
            fields=[FieldSpec(name="title", label="Title", type="text", required=True)],
        ),
        rules=[RuleSpec(code="TITLE_REQUIRED", message="A pour needs a title.", kind="required", field="title")],
    )


def test_review_token_survives_rotation(use_settings) -> None:
    spec, user = _spec(), uuid.uuid4()
    use_settings(_settings(OLD))
    token = review_token.issue(spec, user)

    use_settings(_settings(NEW, OLD))
    review_token.verify(token, spec, user)

    use_settings(_settings(NEW))
    with pytest.raises(review_token.ReviewTokenInvalid):
        review_token.verify(token, spec, user)
