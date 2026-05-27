# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts module — clause templates + clone-flow smoke tests.

The frontend deep-improvement wave (see
``frontend/src/features/contracts/ContractsPage.tsx``) added two new
UI surfaces that depend on stable backend behaviour:

1. **Empty-state template chips** — pulls ``GET /contract-templates/``
   and renders the family codes (FIDIC / JCT / NEC / AIA / ConsensusDocs)
   as hint chips so a brand-new tenant immediately understands the
   built-in standards. This test pins:
     * the catalogue is non-empty,
     * each entry has the keys the chips read (``code``, ``family``),
     * every entry exposes a ``retention_release_event`` string (the
       drawer Header card surfaces this),
     * ``clause_count`` is a positive integer (the modal copy says
       "N key clauses bundled").

2. **Clone-from-drawer button** — calls
   ``POST /contracts/{id}/clone`` with ``new_code = "<src>-COPY"``.
   This test pins the contract-clause-template's invariant that the
   clone-helpers in ``ContractsService`` return a fully populated
   clone in ``draft`` status, with copied terms but a reset
   ``signed_at`` and ``cloned_from_contract_id`` metadata
   breadcrumb — exactly the contract the UI surfaces in its toast.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.contracts.service import (
    CONTRACT_CLAUSE_TEMPLATES,
    ContractsService,
    get_contract_template,
    list_contract_templates,
)

# ── 1. Template catalogue smoke ───────────────────────────────────────────


def test_list_contract_templates_exposes_all_families() -> None:
    """``list_contract_templates`` must surface every clause family the
    UI offers as an empty-state hint chip. The five canonical families
    (FIDIC / JCT / NEC / AIA / ConsensusDocs) are the contract that
    the frontend depends on — adding a sixth is fine, removing one is
    a breaking change that needs a co-ordinated UI update.
    """
    templates = list_contract_templates()
    assert templates, "expected at least one clause template in the catalogue"
    families = {tpl["family"] for tpl in templates}
    for required in {"fidic", "jct", "nec", "aia", "consensusdocs"}:
        assert required in families, (
            f"missing required clause-template family {required!r} — "
            f"the contracts empty-state hint chips will lose this entry "
            f"if the catalogue is shrunk; check service.py "
            f"CONTRACT_CLAUSE_TEMPLATES."
        )


def test_each_template_carries_keys_the_ui_reads() -> None:
    """Every dict the frontend pulls must expose the keys the chip /
    drawer call-sites read directly.

    Concretely the React layer reads:
      * ``code``                     — chip key + future POST body
      * ``family``                   — chip text
      * ``retention_release_event``  — drawer Header card row
      * ``clause_count``             — modal "N clauses bundled" hint
    """
    for tpl in list_contract_templates():
        for key in ("code", "family", "retention_release_event", "clause_count"):
            assert key in tpl, f"template {tpl.get('code')!r} missing key {key!r}"
        assert isinstance(tpl["clause_count"], int) and tpl["clause_count"] > 0, (
            f"template {tpl['code']!r} clause_count must be a positive int, got {tpl['clause_count']!r}"
        )


def test_get_contract_template_round_trips_each_code() -> None:
    """Every template returned by the list endpoint must resolve through
    the GET-by-code helper. A 404-leak here would silently break the
    drawer's "Open template" link.
    """
    for code in CONTRACT_CLAUSE_TEMPLATES:
        body = get_contract_template(code)
        assert body["code"] == code
        assert "name" in body
        # ``get_contract_template`` returns the full key_clauses dict
        # (the list-endpoint summarises with clause_count instead) —
        # this is the by-code endpoint's value-add and the frontend
        # detail view will surface it later.
        assert "key_clauses" in body
        assert isinstance(body["key_clauses"], dict)
        assert body["key_clauses"], f"template {code!r} key_clauses must be non-empty"


def test_get_contract_template_raises_keyerror_for_unknown() -> None:
    """Unknown template codes must raise ``KeyError`` (mapped to 404 at
    the router layer) rather than returning ``{}`` — a silent empty
    response would render an empty drawer that looks like the template
    has no clauses.
    """
    with pytest.raises(KeyError):
        get_contract_template("not-a-real-template-code")


# ── 2. Clone smoke ────────────────────────────────────────────────────────
#
# We rebuild the minimum stub harness here (rather than re-importing the
# security-test stubs) so this file stays self-contained — the security
# tests are an evolving R7 surface and we don't want cross-file
# coupling.


class _StubContractRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.by_code: dict[str, Any] = {}

    async def get_by_id(self, contract_id: uuid.UUID) -> Any:
        return self.rows.get(contract_id)

    async def get_by_code(self, code: str) -> Any:
        return self.by_code.get(code)

    async def update_fields(self, contract_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(contract_id)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        if getattr(item, "code", None):
            self.by_code[item.code] = item
        return item


class _StubLineRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "contract_id", None) == contract_id]

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        return item


class _StubGenericRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "contract_id", None) == contract_id]

    async def get_for_contract(self, contract_id: uuid.UUID) -> Any:
        for r in self.rows.values():
            if getattr(r, "contract_id", None) == contract_id:
                return r
        return None


class _StubSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, item: Any) -> None:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.added.append(item)

    async def flush(self) -> None:
        pass

    async def refresh(self, _obj: Any) -> None:
        pass


def _make_service() -> ContractsService:
    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession()
    svc.contract_repo = _StubContractRepo()
    svc.line_repo = _StubLineRepo()
    svc.retention_repo = _StubGenericRepo()
    svc.fee_repo = _StubGenericRepo()
    svc.gainshare_repo = _StubGenericRepo()
    svc.ld_repo = _StubGenericRepo()
    svc.claim_repo = _StubGenericRepo()
    svc.claim_line_repo = _StubGenericRepo()
    svc.final_account_repo = _StubGenericRepo()
    svc.type_repo = _StubGenericRepo()
    return svc


def _seed_active_contract(svc: ContractsService) -> Any:
    project_id = uuid.uuid4()
    contract = SimpleNamespace(
        id=uuid.uuid4(),
        code="A-001",
        title="Source contract",
        contract_type="lump_sum",
        counterparty_type="client",
        counterparty_id=None,
        project_id=project_id,
        parent_contract_id=None,
        start_date=None,
        end_date=None,
        total_value=Decimal("100000"),
        currency="EUR",
        retention_percent=Decimal("5"),
        retention_release_event="practical_completion",
        status="active",
        signed_at="2026-01-01T10:00:00+00:00",
        terms={"jurisdiction": "DE", "language": "de"},
        metadata_={},
        created_by=None,
    )
    svc.contract_repo.rows[contract.id] = contract
    svc.contract_repo.by_code[contract.code] = contract
    return contract


@pytest.mark.asyncio
async def test_clone_returns_draft_with_terms_copied() -> None:
    """The clone-from-drawer button calls clone_contract with a unique
    new_code; the result must be in draft status (caller must re-sign)
    with terms copied by value.
    """
    svc = _make_service()
    source = _seed_active_contract(svc)

    clone = await svc.clone_contract(
        source.id,
        new_code="A-001-COPY",
        new_title=None,
        target_project_id=None,
        include_lines=True,
        copy_subconfigs=True,
        user_id=str(uuid.uuid4()),
    )

    assert clone.status == "draft", "cloned contract must start in draft"
    assert clone.signed_at is None, "cloned contract must reset signed_at"
    assert clone.code == "A-001-COPY"
    assert clone.terms == source.terms, "terms must be copied by value"
    # Mutate the clone's terms — source must not be touched (deep copy).
    clone.terms["jurisdiction"] = "UK"
    assert source.terms["jurisdiction"] == "DE"


@pytest.mark.asyncio
async def test_clone_strips_payment_history_metadata() -> None:
    """Volatile payment-history fields on the source's metadata must
    NOT leak into the clone — retention_releases / lien_waivers belong
    to the original instrument's ledger.

    The clone carries a ``cloned_from_contract_id`` breadcrumb so the
    UI can later render "Cloned from C-001" on the detail drawer.
    """
    svc = _make_service()
    source = _seed_active_contract(svc)
    # Inject the two payment-history keys that the service strips on
    # clone (per service.py ~L751: `for k in ("retention_releases",
    # "lien_waivers")`).
    source.metadata_["retention_releases"] = [{"amount": "1000"}]
    source.metadata_["lien_waivers"] = [{"signed_by": "ACME LLC"}]

    clone = await svc.clone_contract(
        source.id,
        new_code="A-001-COPY-2",
        new_title=None,
        target_project_id=None,
        include_lines=False,
        copy_subconfigs=False,
        user_id=str(uuid.uuid4()),
    )

    assert clone.metadata_.get("cloned_from_contract_id") == str(source.id)
    assert "retention_releases" not in clone.metadata_
    assert "lien_waivers" not in clone.metadata_
