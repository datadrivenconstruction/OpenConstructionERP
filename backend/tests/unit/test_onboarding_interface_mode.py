"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The onboarding save stores the interface mode a client reports, and no other.

The wizard switched every new user to Simple mode and in the same breath told
the server ``interface_mode: "advanced"``; the Modules page profile switch sent
"advanced" too, and the request schema defaulted to "advanced" for anyone who
sent nothing. Nothing in the app reads the stored value back, so the record
simply disagreed with the screen. The Simple / Advanced choice is a
per-browser setting the client keeps, and both callers now leave the field
out. These tests pin the server half: an omitted mode is stored as absent, not
as a claim nobody made, while a client that still reports one keeps it.
"""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.users.router import save_onboarding
from app.modules.users.schemas import OnboardingRequest


class _Users:
    """The two calls ``save_onboarding`` makes, over one in-memory user."""

    def __init__(self, metadata: dict[str, Any]) -> None:
        self.user = SimpleNamespace(metadata_=metadata)
        self.saved: dict[str, Any] | None = None

    async def get_user(self, _user_id: uuid.UUID) -> SimpleNamespace:
        return self.user

    async def update_profile(self, _user_id: uuid.UUID, *, metadata_: dict[str, Any]) -> None:
        self.saved = metadata_


def _save(body: OnboardingRequest, users: _Users) -> Any:
    return asyncio.run(save_onboarding(body, user_id=str(uuid.uuid4()), service=users))  # type: ignore[arg-type]


def test_a_request_that_names_no_mode_carries_none() -> None:
    assert OnboardingRequest(company_type="general_contractor").interface_mode is None


def test_a_reported_mode_is_accepted_and_an_unknown_one_refused() -> None:
    assert OnboardingRequest(company_type="general_contractor", interface_mode="simple").interface_mode == "simple"
    with pytest.raises(ValidationError):
        OnboardingRequest(company_type="general_contractor", interface_mode="expert")


def test_saving_without_a_mode_does_not_store_advanced() -> None:
    # A record written by the old wizard, which always claimed "advanced".
    users = _Users({"onboarding": {"company_type": "estimator", "interface_mode": "advanced", "completed": True}})

    response = _save(
        OnboardingRequest(company_type="general_contractor", enabled_modules=["boq", "contracts"]),
        users,
    )

    assert users.saved is not None
    stored = users.saved["onboarding"]
    assert stored["company_type"] == "general_contractor"
    assert stored["interface_mode"] is None
    assert response.interface_mode is None
    # The profile is what the sidebar reads back, so it must round-trip.
    assert response.company_type == "general_contractor"


def test_a_client_that_still_reports_a_mode_has_it_stored_as_sent() -> None:
    users = _Users({})

    _save(OnboardingRequest(company_type="general_contractor", interface_mode="simple"), users)

    assert users.saved is not None
    assert users.saved["onboarding"]["interface_mode"] == "simple"
