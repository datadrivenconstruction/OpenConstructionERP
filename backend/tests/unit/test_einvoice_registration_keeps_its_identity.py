"""A registration with documents filed under it keeps the identity they were sent with.

``remove_registration`` already refuses to delete such a registration, because
it is the only record of which company, country and tax number the filed
documents went out under. The PUT that replaces a registration rewrote exactly
those fields without asking, which erased the same record the delete protects.
Housekeeping fields (certificate, adapter, sandbox, active, notes) stay editable.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.einvoice_clearance import adapters, regimes, repository, schemas, service
from app.modules.einvoice_clearance.models import EInvoiceProfile
from app.modules.einvoice_clearance.router import replace_registration
from app.modules.einvoice_clearance.validators import register_einvoice_clearance_rules
from tests._pg import transactional_session

_MX_FIELDS = {
    "rfc_issuer": "AAA010101AAA",
    "rfc_receiver": "BBB020202BBB",
    "uso_cfdi": "G03",
    "regimen_fiscal": "601",
}


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _registries() -> None:
    register_einvoice_clearance_rules()
    adapters.register_builtin_adapters()


async def _profile(session: AsyncSession) -> EInvoiceProfile:
    entry = regimes.COUNTRY_REGIMES["MX"]
    return await repository.add_profile(
        session,
        EInvoiceProfile(
            company_key=f"acme-{uuid.uuid4().hex[:8]}",
            country="MX",
            regime=entry.regime,
            platform=entry.platform,
            tax_registration_id="AAA010101AAA",
            network_participant_id="",
            certificate_reference="vault://csd/acme",
            adapter_key=adapters.REFERENCE_ADAPTER_KEY,
            sandbox=True,
            is_active=True,
        ),
    )


async def _file_one(session: AsyncSession, profile: EInvoiceProfile) -> None:
    await service.create_document(
        session,
        profile=profile,
        body=schemas.DocumentCreateRequest(
            project_id=uuid.uuid4(),
            profile_id=profile.id,
            invoice_number="2026-0007",
            invoice_date="2026-08-05",
            currency_code="MXN",
            total_amount="1190.00",
            country_fields=_MX_FIELDS,
            payload=f"<Invoice n='{uuid.uuid4().hex}'/>",
        ),
    )


def _update(profile: EInvoiceProfile, **changes: object) -> schemas.ProfileUpdateRequest:
    values: dict[str, object] = {
        "company_key": profile.company_key,
        "country": profile.country,
        "tax_registration_id": profile.tax_registration_id,
        "network_participant_id": profile.network_participant_id,
        "certificate_reference": profile.certificate_reference,
        "adapter_key": profile.adapter_key,
        "sandbox": profile.sandbox,
        "is_active": profile.is_active,
        "notes": profile.notes or "",
    }
    values.update(changes)
    return schemas.ProfileUpdateRequest.model_validate(values)


@pytest.mark.asyncio
async def test_a_filed_registration_keeps_its_tax_number(session: AsyncSession) -> None:
    profile = await _profile(session)
    await _file_one(session, profile)
    with pytest.raises(HTTPException) as caught:
        await replace_registration(profile.id, _update(profile, tax_registration_id="ZZZ990909ZZZ"), session)
    assert caught.value.status_code == 409
    assert profile.tax_registration_id == "AAA010101AAA"


@pytest.mark.asyncio
async def test_a_filed_registration_keeps_its_company(session: AsyncSession) -> None:
    profile = await _profile(session)
    await _file_one(session, profile)
    before = profile.company_key
    with pytest.raises(HTTPException) as caught:
        await replace_registration(profile.id, _update(profile, company_key="someone-else"), session)
    assert caught.value.status_code == 409
    assert profile.company_key == before


@pytest.mark.asyncio
async def test_a_filed_registration_can_still_be_deactivated(session: AsyncSession) -> None:
    profile = await _profile(session)
    await _file_one(session, profile)
    saved = await replace_registration(
        profile.id, _update(profile, is_active=False, certificate_reference="vault://csd/acme-2027"), session
    )
    assert saved.is_active is False
    assert saved.certificate_reference == "vault://csd/acme-2027"


@pytest.mark.asyncio
async def test_an_unused_registration_can_still_be_corrected(session: AsyncSession) -> None:
    profile = await _profile(session)
    saved = await replace_registration(profile.id, _update(profile, tax_registration_id="ZZZ990909ZZZ"), session)
    assert saved.tax_registration_id == "ZZZ990909ZZZ"
