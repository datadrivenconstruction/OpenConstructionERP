# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Other modules add to a claim's rule context by registering, not by import.

Contracts used to import the subcontractors rollup lazily to put it into the
``pay_application`` context. Modules are plugins, so that import is a server
error on every install where the other module is absent or differs. The
registry in ``contracts.claim_context`` turns the dependency around; these
tests hold what it promises: nothing registered means nothing added, a
provider lands under its key, ``None`` leaves the key out, and a provider that
fails is not quietly dropped.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.contracts import claim_context
from app.modules.contracts.claim_context import collect_claim_context, register_claim_context_provider

pytestmark = pytest.mark.asyncio

CLAIM = SimpleNamespace(id="claim-1")


@pytest.fixture(autouse=True)
def _no_providers(monkeypatch):
    # Whatever the installed modules registered on import is not this test's.
    monkeypatch.setattr(claim_context, "_providers", {})


async def test_with_nothing_registered_nothing_is_added() -> None:
    assert await collect_claim_context(None, CLAIM) == {}


async def test_sync_and_async_providers_land_under_their_keys() -> None:
    async def rollup(session, claim):
        return {"claim": claim.id, "pay_apps": 2}

    register_claim_context_provider("subcontract_rollup", rollup)
    register_claim_context_provider("site_diary", lambda session, claim: ["2026-03-31"])
    assert await collect_claim_context(None, CLAIM) == {
        "subcontract_rollup": {"claim": "claim-1", "pay_apps": 2},
        "site_diary": ["2026-03-31"],
    }


async def test_a_provider_with_nothing_to_say_leaves_its_key_out() -> None:
    register_claim_context_provider("subcontract_rollup", lambda session, claim: None)
    assert await collect_claim_context(None, CLAIM) == {}


async def test_registering_a_key_again_replaces_the_provider() -> None:
    register_claim_context_provider("subcontract_rollup", lambda session, claim: 1)
    register_claim_context_provider("subcontract_rollup", lambda session, claim: 2)
    assert await collect_claim_context(None, CLAIM) == {"subcontract_rollup": 2}
    claim_context.unregister_claim_context_provider("subcontract_rollup")
    assert await collect_claim_context(None, CLAIM) == {}


async def test_a_provider_that_fails_is_not_dropped() -> None:
    # A context that silently lost a section would pass the rules reading it.
    def broken(session, claim):
        raise LookupError("rollup table missing")

    register_claim_context_provider("subcontract_rollup", broken)
    with pytest.raises(LookupError):
        await collect_claim_context(None, CLAIM)
