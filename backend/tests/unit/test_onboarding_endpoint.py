"""The onboarding save and read endpoints, over HTTP.

The wizard and the Modules page both write the user's company profile through
``POST /v1/users/me/onboarding/``, and the sidebar, the Modules page and the
dashboard read it back through ``GET``. Three behaviours are pinned here.

An unknown profile is refused with a 422 and nothing is written. The field
used to accept any slug, so a typo or a key from another build was stored as
the user's profile and every reader had to guess what it meant.

Old answers keep reading back. Accounts that picked a team size in an earlier
release carry ``size_*`` keys; they read back verbatim, save again, and a
client that no longer sends ``company_size`` leaves the stored one alone.

A module selection made without a profile (``company_type: null``) is saved as
sent. Before, the wizard sent ``full_enterprise`` for it, and the server pins
that profile to every module, so every switch the user had turned off came
back on after Finish.

The service is a stub that holds one user's metadata in memory: the question
is what the router accepts and what it hands to storage, not how storage works.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.onboarding_presets import _ALL_FUNCTIONAL, COMPANY_PRESETS, SIZE_PRESETS
from app.dependencies import get_current_user_id
from app.modules.users.router import _get_service
from app.modules.users.router import router as users_router
from app.modules.users.schemas import OnboardingRequest

USER_ID = str(uuid.UUID("00000000-0000-4000-8000-00000000000a"))
URL = "/v1/users/me/onboarding/"


class _StubUserService:
    """One user's metadata, and a log of every write the router asked for."""

    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self.metadata: dict[str, Any] = dict(metadata or {})
        self.writes: list[dict[str, Any]] = []

    async def get_user(self, user_id: uuid.UUID) -> SimpleNamespace:
        assert str(user_id) == USER_ID
        return SimpleNamespace(metadata_=dict(self.metadata))

    async def update_profile(self, user_id: uuid.UUID, **fields: Any) -> None:
        assert str(user_id) == USER_ID
        self.writes.append(fields)
        if "metadata_" in fields:
            self.metadata = dict(fields["metadata_"])


def _client(service: _StubUserService) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(users_router, prefix="/v1/users")

    async def _user_override() -> str:
        return USER_ID

    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[_get_service] = lambda: service
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ── Refused: an answer the catalogue does not know ────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        # A plausible profile the catalogue does not have.
        {"company_type": "demolition_contractor", "enabled_modules": ["boq"]},
        # Free text where a key belongs.
        {"company_type": "We build roads", "enabled_modules": ["boq"]},
        # The right shape and a typo.
        {"company_type": "general_contractr", "enabled_modules": ["boq"]},
        # A known profile with a size that does not exist.
        {"company_type": "general_contractor", "company_size": "size_huge", "enabled_modules": ["boq"]},
        # A profile key where a size belongs.
        {"company_type": "general_contractor", "company_size": "estimator", "enabled_modules": ["boq"]},
        # No company_type at all: null is an answer, silence is not.
        {"enabled_modules": ["boq"]},
    ],
)
async def test_an_unknown_profile_is_refused_and_nothing_is_stored(body: dict[str, Any]) -> None:
    service = _StubUserService({"onboarding": {"company_type": "estimator", "completed": True}})
    async with _client(service) as client:
        resp = await client.post(URL, json=body)
    assert resp.status_code == 422, resp.text
    assert service.writes == []
    assert service.metadata["onboarding"]["company_type"] == "estimator"


@pytest.mark.parametrize("key", sorted(COMPANY_PRESETS))
def test_every_company_profile_is_accepted(key: str) -> None:
    assert OnboardingRequest(company_type=key, enabled_modules=[]).company_type == key


@pytest.mark.parametrize("key", sorted(SIZE_PRESETS))
def test_every_legacy_size_tier_is_still_accepted(key: str) -> None:
    req = OnboardingRequest(company_type=key, company_size=key, enabled_modules=[])
    assert (req.company_type, req.company_size) == (key, key)


# ── Stored: what a valid answer writes ───────────────────────────────────────


async def test_a_company_profile_is_stored_with_its_modules() -> None:
    service = _StubUserService()
    async with _client(service) as client:
        resp = await client.post(
            URL,
            json={"company_type": "subcontractor", "enabled_modules": ["boq", "payroll"], "completed": True},
        )
    assert resp.status_code == 200, resp.text
    stored = service.metadata["onboarding"]
    assert stored["company_type"] == "subcontractor"
    assert stored["enabled_modules"] == ["boq", "payroll"]
    assert stored["completed"] is True
    prefs = service.metadata["module_preferences"]
    assert prefs["payroll"] is True
    assert prefs["finance"] is False


async def test_modules_chosen_without_a_profile_are_saved_as_sent() -> None:
    """``company_type: null`` must not be pinned the way Full Enterprise is."""
    service = _StubUserService()
    chosen = [m for m in _ALL_FUNCTIONAL if m != "finance"]
    async with _client(service) as client:
        resp = await client.post(URL, json={"company_type": None, "enabled_modules": chosen})
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_type"] is None
    stored = service.metadata["onboarding"]
    assert stored["company_type"] is None
    assert stored["enabled_modules"] == chosen
    # The one switch the user turned off stays off.
    assert service.metadata["module_preferences"]["finance"] is False
    assert service.metadata["module_preferences"]["boq"] is True


async def test_full_enterprise_is_still_pinned_to_every_module() -> None:
    service = _StubUserService()
    async with _client(service) as client:
        resp = await client.post(URL, json={"company_type": "full_enterprise", "enabled_modules": ["boq"]})
    assert resp.status_code == 200, resp.text
    assert set(service.metadata["onboarding"]["enabled_modules"]) == set(_ALL_FUNCTIONAL)
    assert service.metadata["module_preferences"]["finance"] is True


# ── Old answers: read back, saved again, never silently reset ─────────────────


async def test_a_stored_size_tier_reads_back_verbatim() -> None:
    legacy = {
        "company_type": "size_small",
        "company_size": "size_small",
        "enabled_modules": ["boq", "takeoff"],
        "interface_mode": "advanced",
        "completed": True,
    }
    service = _StubUserService({"onboarding": legacy})
    async with _client(service) as client:
        resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    assert resp.json() == legacy
    assert service.writes == []


async def test_a_stored_value_outside_the_catalogue_still_reads_back() -> None:
    """Validation guards the write. A read must not fail on what an older build stored."""
    service = _StubUserService({"onboarding": {"company_type": "project_management", "completed": True}})
    async with _client(service) as client:
        resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_type"] == "project_management"


async def test_saving_a_profile_keeps_the_stored_size_when_none_is_sent() -> None:
    service = _StubUserService({"onboarding": {"company_type": "size_medium", "company_size": "size_medium"}})
    async with _client(service) as client:
        resp = await client.post(URL, json={"company_type": "general_contractor", "enabled_modules": ["boq"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_size"] == "size_medium"
    assert service.metadata["onboarding"]["company_type"] == "general_contractor"
    assert service.metadata["onboarding"]["company_size"] == "size_medium"


async def test_an_explicit_null_size_clears_it() -> None:
    service = _StubUserService({"onboarding": {"company_type": "size_medium", "company_size": "size_medium"}})
    async with _client(service) as client:
        resp = await client.post(
            URL, json={"company_type": "general_contractor", "company_size": None, "enabled_modules": ["boq"]}
        )
    assert resp.status_code == 200, resp.text
    assert service.metadata["onboarding"]["company_size"] is None


async def test_an_older_client_can_still_save_a_size_tier() -> None:
    service = _StubUserService()
    async with _client(service) as client:
        resp = await client.post(
            URL, json={"company_type": "size_large", "company_size": "size_large", "enabled_modules": ["boq"]}
        )
    assert resp.status_code == 200, resp.text
    stored = service.metadata["onboarding"]
    assert (stored["company_type"], stored["company_size"]) == ("size_large", "size_large")
    # Large Enterprise is pinned to every module, as it always was.
    assert set(stored["enabled_modules"]) == set(_ALL_FUNCTIONAL)
