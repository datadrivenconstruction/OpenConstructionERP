# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One class per probe type. Each reads ERP state the way the ERP's UI does.

Every probe reads through the owning module's service or repository, takes
exactly the frozen args model from ``spec.py``, resolves its seeded ref
through :class:`~app.modules.trainer.checker.registry.ProbeContext` and refuses
an object whose project is not the enrolment's project.

What each probe reads:

=====================  =====================================================================
type                   source
=====================  =====================================================================
boq.cost_breakdown     ``BOQService.get_cost_breakdown(boq_id)``: ``direct_cost``,
                       ``grand_total``, ``markups[name].amount``
boq.position           ``PositionRepository.list_all_for_boq`` -> ``oe_boq_position.quantity /
                       unit_rate / total`` by ``ordinal``
boq.section_total      same rows; leaf ``oe_boq_position.total`` summed below the section row
                       (``boq.service._is_section``), nested sections included
boq.markup             ``MarkupRepository.list_for_boq`` -> active ``oe_boq_markup`` rows by
                       ``name``
bid.submission         ``BidSubmissionRepository.submissions_for_package`` joined to
                       ``oe_bid_management_bidder.company_name``
bid.leveling           ``BidManagementService.get_or_create_comparison`` +
                       ``compute_leveling`` -> ``oe_bid_management_leveling`` (WRITES, see class)
bid.award              ``BidAwardRepository.get_for_package`` -> ``awarded_amount``,
                       ``awarded_bidder_id`` -> bidder ``company_name``
contract.field         ``ContractRepository.get_by_id`` -> ``oe_contracts_contract`` columns;
                       ``einvoice_vat_rate`` = ``metadata["einvoice"]["vat_rate"]``
claim.field            ``ProgressClaimRepository.claims_for_contract`` ->
                       ``oe_contracts_progress_claim`` columns
claim.line             ``ProgressClaimLineRepository.list_for_claim`` joined to
                       ``ContractLineRepository.list_for_contract`` on ``code``
claim.lien_waiver      last entry of ``oe_contracts_progress_claim.metadata["lien_waivers"]``
finance.receivable     ``FinanceService.get_receivable_for_claim`` -> ``oe_finance_invoice``
variation.request      ``VariationRequestRepository.list_for_project`` -> ``oe_variations_request``
variation.order        ``VariationOrderRepository.list_all_for_project`` filtered on
                       ``affected_contract_id``
panel.answer           ``oe_trainer_answer.value_text``
panel.option           ``oe_trainer_answer.option_index``
=====================  =====================================================================

Selectors (``claim_selector``, ``variation_ref``) are ``"latest"`` or the n-th
object in creation order. A claim's n is its number: ``PC-{n:04d}``
(``contracts.repository.next_claim_number`` numbers a contract's claims
``count + 1``). Requests and orders are ordered by ``(created_at, code)``;
``code`` breaks a tie between rows written in the same instant.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.trainer.checker.registry import (
    OPEN_LEVELING_KEY,
    Probe,
    ProbeContext,
    ProbeReading,
    register_probe,
)
from app.modules.trainer.spec import (
    BidAwardArgs,
    BidLevelingArgs,
    BidSubmissionArgs,
    BoqCostBreakdownArgs,
    BoqMarkupArgs,
    BoqPositionArgs,
    BoqSectionTotalArgs,
    ClaimFieldArgs,
    ClaimLienWaiverArgs,
    ClaimLineArgs,
    ContractFieldArgs,
    FinanceReceivableArgs,
    PanelAnswerArgs,
    PanelOptionArgs,
    VariationOrderArgs,
    VariationRequestArgs,
    to_decimal,
)

# ── Shared helpers ───────────────────────────────────────────────────────────


def _dec(value: object) -> Decimal | None:
    """A stored number as Decimal. Floats go through ``str`` (0.1 stays 0.1)."""
    return to_decimal(value)


def _key(text: object) -> str:
    return str(text or "").strip().casefold()


def _one[T](rows: Sequence[T], what: str) -> T | ProbeReading:
    """The single row, or the unknown reading for none / more than one."""
    if not rows:
        return ProbeReading.unknown("not_found", what)
    if len(rows) > 1:
        return ProbeReading.unknown("ambiguous", f"{len(rows)} x {what}")
    return rows[0]


def _select[T](
    rows: Sequence[T], selector: object, number_of: Callable[[T], str] | None, what: str
) -> T | ProbeReading:
    """Apply a ``"latest" | n`` selector to rows already in creation order.

    With ``number_of`` (claims), n selects the row numbered ``PC-{n:04d}``;
    without it, the n-th row (1-based).
    """
    if not rows:
        return ProbeReading.unknown("not_found", what)
    if selector == "latest":
        return rows[-1]
    n = int(selector)  # type: ignore[call-overload]
    if number_of is not None:
        wanted = f"PC-{n:04d}"
        return _one([r for r in rows if number_of(r) == wanted], f"{what} {wanted}")
    if n > len(rows):
        return ProbeReading.unknown("not_found", f"{what} #{n} of {len(rows)}")
    return rows[n - 1]


def _ref(ctx: ProbeContext, ref: str) -> uuid.UUID | ProbeReading:
    ref_id = ctx.ref_id(ref)
    return ProbeReading.unknown("ref_missing", ref) if ref_id is None else ref_id


def _owned(project_id: object, ctx: ProbeContext, what: str) -> ProbeReading | None:
    """None when the object belongs to the enrolment's project, else the refusal."""
    if project_id is None or str(project_id) != str(ctx.project_id):
        return ProbeReading.unknown("ref_outside_project", what)
    return None


async def _boq_header(session: AsyncSession, ctx: ProbeContext, boq_ref: str) -> uuid.UUID | ProbeReading:
    from app.modules.boq.repository import BOQRepository

    boq_id = _ref(ctx, boq_ref)
    if isinstance(boq_id, ProbeReading):
        return boq_id
    header = await BOQRepository(session).get_header(boq_id)
    if header is None:
        return ProbeReading.unknown("not_found", boq_ref)
    refused = _owned(header["project_id"], ctx, boq_ref)
    return refused if refused is not None else boq_id


async def _positions(session: AsyncSession, boq_id: uuid.UUID) -> list[Any]:
    from app.modules.boq.repository import PositionRepository

    return await PositionRepository(session).list_all_for_boq(boq_id)


async def _package(session: AsyncSession, ctx: ProbeContext, package_ref: str) -> Any | ProbeReading:
    from app.modules.bid_management.repository import BidPackageRepository

    package_id = _ref(ctx, package_ref)
    if isinstance(package_id, ProbeReading):
        return package_id
    package = await BidPackageRepository(session).get_by_id(package_id)
    if package is None:
        return ProbeReading.unknown("not_found", package_ref)
    refused = _owned(package.project_id, ctx, package_ref)
    return refused if refused is not None else package


async def _bidder(session: AsyncSession, package_id: uuid.UUID, bidder_name: str) -> Any | ProbeReading:
    from app.modules.bid_management.repository import BidderRepository

    bidders = await BidderRepository(session).list_for_package(package_id)
    return _one([b for b in bidders if _key(b.company_name) == _key(bidder_name)], f"bidder {bidder_name!r}")


async def _contract(session: AsyncSession, ctx: ProbeContext, contract_ref: str) -> Any | ProbeReading:
    from app.modules.contracts.repository import ContractRepository

    contract_id = _ref(ctx, contract_ref)
    if isinstance(contract_id, ProbeReading):
        return contract_id
    contract = await ContractRepository(session).get_by_id(contract_id)
    if contract is None:
        return ProbeReading.unknown("not_found", contract_ref)
    refused = _owned(contract.project_id, ctx, contract_ref)
    return refused if refused is not None else contract


async def _claim(session: AsyncSession, ctx: ProbeContext, contract_ref: str, selector: object) -> Any | ProbeReading:
    from app.modules.contracts.repository import ProgressClaimRepository

    contract = await _contract(session, ctx, contract_ref)
    if isinstance(contract, ProbeReading):
        return contract
    repo = ProgressClaimRepository(session)
    claims: list[Any] = []
    offset = 0
    while True:
        page, total = await repo.claims_for_contract(contract.id, offset=offset, limit=200)
        claims.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    claims.sort(key=lambda c: (c.created_at, c.claim_number or ""))
    return _select(claims, selector, lambda c: c.claim_number or "", "progress claim")


def _decimal_field(row: Any, name: str) -> ProbeReading:
    raw = getattr(row, name)
    if raw is None:
        return ProbeReading.unknown("not_set", name)
    value = _dec(raw)
    return ProbeReading.of(value) if value is not None else ProbeReading.unknown("unreadable", name)


# ── BOQ ──────────────────────────────────────────────────────────────────────


@register_probe("boq.cost_breakdown")
class BoqCostBreakdownProbe(Probe):
    """Direct cost, grand total or one markup's amount, as the cost breakdown shows them."""

    args_model = BoqCostBreakdownArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: BoqCostBreakdownArgs) -> ProbeReading:
        from app.modules.boq.service import BOQService

        boq_id = await _boq_header(session, ctx, args.boq_ref)
        if isinstance(boq_id, ProbeReading):
            return boq_id
        breakdown = await BOQService(session).get_cost_breakdown(boq_id)
        if args.field == "direct_cost":
            return ProbeReading.of(_dec(breakdown.direct_cost))
        if args.field == "grand_total":
            return ProbeReading.of(_dec(breakdown.grand_total))
        # ``markups[].amount`` is built from ``round(float(...), 2)``; ``_dec``
        # goes through ``str`` so no binary-float tail survives.
        line = _one([m for m in breakdown.markups if _key(m.name) == _key(args.markup_name)], "markup")
        if isinstance(line, ProbeReading):
            return line
        return ProbeReading.of(_dec(line.amount))


def _find_position(positions: list[Any], ordinal: str) -> Any | ProbeReading:
    return _one([p for p in positions if (p.ordinal or "").strip() == ordinal.strip()], f"position {ordinal}")


@register_probe("boq.position")
class BoqPositionProbe(Probe):
    """One stored column of one position, by ordinal."""

    args_model = BoqPositionArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: BoqPositionArgs) -> ProbeReading:
        boq_id = await _boq_header(session, ctx, args.boq_ref)
        if isinstance(boq_id, ProbeReading):
            return boq_id
        position = _find_position(await _positions(session, boq_id), args.ordinal)
        if isinstance(position, ProbeReading):
            return position
        return _decimal_field(position, args.field)


@register_probe("boq.section_total")
class BoqSectionTotalProbe(Probe):
    """Sum of the stored totals of every leaf position below a section row.

    A section is what the ERP itself calls one (``boq.service._is_section``:
    a section unit with zero quantity and rate), so nested sections are walked
    and never counted as money themselves.
    """

    args_model = BoqSectionTotalArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: BoqSectionTotalArgs) -> ProbeReading:
        from app.modules.boq.service import _is_section

        boq_id = await _boq_header(session, ctx, args.boq_ref)
        if isinstance(boq_id, ProbeReading):
            return boq_id
        positions = await _positions(session, boq_id)
        section = _one(
            [p for p in positions if (p.ordinal or "").strip() == args.section_ordinal.strip() and _is_section(p)],
            f"section {args.section_ordinal}",
        )
        if isinstance(section, ProbeReading):
            return section
        children: dict[uuid.UUID, list[Any]] = {}
        for p in positions:
            if p.parent_id is not None:
                children.setdefault(p.parent_id, []).append(p)
        total = Decimal(0)
        stack = list(children.get(section.id, []))
        seen: set[uuid.UUID] = set()
        while stack:
            node = stack.pop()
            if node.id in seen:
                continue
            seen.add(node.id)
            if _is_section(node):
                stack.extend(children.get(node.id, []))
                continue
            value = _dec(node.total)
            if value is None:
                return ProbeReading.unknown("unreadable", f"total of {node.ordinal}")
            total += value
            stack.extend(children.get(node.id, []))
        return ProbeReading.of(total)


@register_probe("boq.markup")
class BoqMarkupProbe(Probe):
    """One column of the active markup row with that name."""

    args_model = BoqMarkupArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: BoqMarkupArgs) -> ProbeReading:
        from app.modules.boq.repository import MarkupRepository

        boq_id = await _boq_header(session, ctx, args.boq_ref)
        if isinstance(boq_id, ProbeReading):
            return boq_id
        rows = await MarkupRepository(session).list_for_boq(boq_id)
        markup = _one([m for m in rows if m.is_active and _key(m.name) == _key(args.name)], f"markup {args.name!r}")
        if isinstance(markup, ProbeReading):
            return markup
        if args.field in ("markup_type", "apply_to", "category"):
            return ProbeReading.of(getattr(markup, args.field))
        if args.field == "sort_order":
            return ProbeReading.of(Decimal(int(markup.sort_order)))
        # ``percentage`` and ``fixed_amount`` are stored as strings.
        return _decimal_field(markup, args.field)


# ── Bid management ───────────────────────────────────────────────────────────


@register_probe("bid.submission")
class BidSubmissionProbe(Probe):
    """The header total or validity of one bidder's submission."""

    args_model = BidSubmissionArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: BidSubmissionArgs) -> ProbeReading:
        from app.modules.bid_management.repository import BidSubmissionRepository

        package = await _package(session, ctx, args.package_ref)
        if isinstance(package, ProbeReading):
            return package
        bidder = await _bidder(session, package.id, args.bidder_name)
        if isinstance(bidder, ProbeReading):
            return bidder
        subs = [
            s
            for s in await BidSubmissionRepository(session).submissions_for_package(package.id)
            if s.bidder_id == bidder.id
        ]
        # A withdrawn bid stays on file; it is not the bidder's submission.
        live = [s for s in subs if not (s.envelope_payload or {}).get("withdrawn")]
        submission = _one(live or subs, f"submission of {args.bidder_name!r}")
        if isinstance(submission, ProbeReading):
            return submission
        if args.field == "is_valid":
            return ProbeReading.of(bool(submission.is_valid))
        return _decimal_field(submission, "total_amount")


@register_probe("bid.leveling")
class BidLevelingProbe(Probe):
    """One bidder's row of the levelling table.

    ``read`` mode (the readback GET, decision 36) reads the rows the table
    holds and writes nothing. Before the learner has computed levelling there
    are none: ``not_computed``, with :data:`OPEN_LEVELING_KEY` telling the
    learner to open the levelling view.

    ``check`` mode WRITES. It calls the real ``get_or_create_comparison`` and
    ``compute_leveling`` so a check never grades stale rows
    (``compute_leveling`` publishes no event, so nothing else would tell the
    checker the table is out of date). Two side effects follow, both in the
    learner's own project:

    * ``get_or_create_comparison`` creates the package's comparison header
      when the learner has not opened levelling yet;
    * ``compute_leveling`` DELETES every ``oe_bid_management_leveling`` row of
      that comparison and inserts new ones (new ids, same figures for the same
      submissions), and restamps ``computed_at`` / ``recommended_bidder_id``.

    Nothing a person typed lives in those rows: ``manual_adjustment`` is never
    written by the ERP. A bidder whose submission is invalid or who was
    disqualified gets no row, which reads as ``not_found``, never as 0.
    """

    args_model = BidLevelingArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: BidLevelingArgs) -> ProbeReading:
        package = await _package(session, ctx, args.package_ref)
        if isinstance(package, ProbeReading):
            return package
        bidder = await _bidder(session, package.id, args.bidder_name)
        if isinstance(bidder, ProbeReading):
            return bidder
        rows = await (
            self._recompute(session, package.id) if ctx.mode == "check" else self._stored(session, package.id)
        )
        if rows is None:
            return ProbeReading.unknown("not_computed", OPEN_LEVELING_KEY)
        row = _one([r for r in rows if r.bidder_id == bidder.id], f"leveling row of {args.bidder_name!r}")
        if isinstance(row, ProbeReading):
            return row
        if args.field == "rank":
            return ProbeReading.of(Decimal(int(row.rank)))
        return _decimal_field(row, args.field)

    @staticmethod
    async def _recompute(session: AsyncSession, package_id: uuid.UUID) -> list[Any]:
        from app.modules.bid_management.schemas import BidComparisonCreate
        from app.modules.bid_management.service import BidManagementService

        service = BidManagementService(session)
        comparison = await service.get_or_create_comparison(BidComparisonCreate(package_id=package_id))
        return await service.compute_leveling(comparison.id)

    @staticmethod
    async def _stored(session: AsyncSession, package_id: uuid.UUID) -> list[Any] | None:
        """The rows levelling last wrote; None when it never ran for this package."""
        from app.modules.bid_management.repository import BidComparisonRepository, BidLevelingRepository

        comparison = await BidComparisonRepository(session).get_for_package(package_id)
        if comparison is None or comparison.computed_at is None:
            return None
        return await BidLevelingRepository(session).levelings_for_comparison(comparison.id)


@register_probe("bid.award")
class BidAwardProbe(Probe):
    """The package's award: amount or the awarded bidder's company name."""

    args_model = BidAwardArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: BidAwardArgs) -> ProbeReading:
        from app.modules.bid_management.repository import BidAwardRepository, BidderRepository

        package = await _package(session, ctx, args.package_ref)
        if isinstance(package, ProbeReading):
            return package
        award = await BidAwardRepository(session).get_for_package(package.id)
        if award is None:
            return ProbeReading.unknown("not_found", "award")
        if args.field == "awarded_amount":
            return _decimal_field(award, "awarded_amount")
        bidder = await BidderRepository(session).get_by_id(award.awarded_bidder_id)
        if bidder is None or bidder.package_id != package.id:
            return ProbeReading.unknown("not_found", "awarded bidder")
        return ProbeReading.of(bidder.company_name or None)


# ── Contracts ────────────────────────────────────────────────────────────────


def _einvoice_vat_rate(metadata: object) -> ProbeReading:
    """``metadata.einvoice.vat_rate`` as a percent, the way finance reads it.

    Finance multiplies the claim's gross by ``vat_rate / 100`` and treats an
    absent or null rate as 0 (``finance.service``, ``_safe_decimal(..., 0)``),
    so absent and null read as 0 here too: that IS the rate the ERP charges.
    Anything that is not a number (an object, a list, a boolean, text) is
    ``unreadable``, never 0. Finance would silently charge 0 on it, and a
    checker that agreed would bless a contract whose VAT never reaches an
    invoice.
    """
    einvoice = metadata.get("einvoice") if isinstance(metadata, dict) else None
    if einvoice is None:
        return ProbeReading.of(Decimal(0), "einvoice not set; finance charges 0")
    if not isinstance(einvoice, dict):
        return ProbeReading.unknown("unreadable", "metadata.einvoice is not an object")
    raw = einvoice.get("vat_rate")
    if raw is None:
        return ProbeReading.of(Decimal(0), "vat_rate not set; finance charges 0")
    if isinstance(raw, (bool, dict, list)):
        return ProbeReading.unknown("unreadable", f"vat_rate is a {type(raw).__name__}")
    value = _dec(raw)
    if value is None:
        return ProbeReading.unknown("unreadable", "vat_rate is not a number")
    return ProbeReading.of(value)


@register_probe("contract.field")
class ContractFieldProbe(Probe):
    """One column of the seeded contract (never the T3 award draft: by ref only)."""

    args_model = ContractFieldArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: ContractFieldArgs) -> ProbeReading:
        contract = await _contract(session, ctx, args.contract_ref)
        if isinstance(contract, ProbeReading):
            return contract
        if args.field == "einvoice_vat_rate":
            return _einvoice_vat_rate(contract.metadata_)
        if args.field == "status":
            return ProbeReading.of(contract.status or None)
        return _decimal_field(contract, args.field)


@register_probe("claim.field")
class ClaimFieldProbe(Probe):
    """One column of a progress claim on the seeded contract."""

    args_model = ClaimFieldArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: ClaimFieldArgs) -> ProbeReading:
        claim = await _claim(session, ctx, args.contract_ref, args.claim_selector)
        if isinstance(claim, ProbeReading):
            return claim
        if args.field == "status":
            return ProbeReading.of(claim.status or None)
        return _decimal_field(claim, args.field)


@register_probe("claim.line")
class ClaimLineProbe(Probe):
    """One column of a claim's line for the SOV line with that code."""

    args_model = ClaimLineArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: ClaimLineArgs) -> ProbeReading:
        from app.modules.contracts.repository import ContractLineRepository, ProgressClaimLineRepository

        claim = await _claim(session, ctx, args.contract_ref, args.claim_selector)
        if isinstance(claim, ProbeReading):
            return claim
        sov = await ContractLineRepository(session).list_for_contract(claim.contract_id)
        sov_line = _one([s for s in sov if (s.code or "").strip() == args.line_code.strip()], f"SOV {args.line_code}")
        if isinstance(sov_line, ProbeReading):
            return sov_line
        lines = await ProgressClaimLineRepository(session).list_for_claim(claim.id)
        line = _one([cl for cl in lines if cl.contract_line_id == sov_line.id], f"claim line {args.line_code}")
        if isinstance(line, ProbeReading):
            return line
        return _decimal_field(line, args.field)


@register_probe("claim.lien_waiver")
class ClaimLienWaiverProbe(Probe):
    """The last lien waiver attached to a claim (``attach_lien_waiver`` appends)."""

    args_model = ClaimLienWaiverArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: ClaimLienWaiverArgs) -> ProbeReading:
        claim = await _claim(session, ctx, args.contract_ref, args.claim_selector)
        if isinstance(claim, ProbeReading):
            return claim
        waivers = (claim.metadata_ or {}).get("lien_waivers") or []
        if not isinstance(waivers, list) or not waivers or not isinstance(waivers[-1], dict):
            return ProbeReading.unknown("not_found", "lien waiver")
        raw = waivers[-1].get(args.field)
        if args.field == "amount":
            value = _dec(raw)
            return ProbeReading.of(value) if value is not None else ProbeReading.unknown("unreadable", "amount")
        return ProbeReading.of(str(raw) if raw not in (None, "") else None)


@register_probe("finance.receivable")
class FinanceReceivableProbe(Probe):
    """The receivable invoice finance raised from a claim."""

    args_model = FinanceReceivableArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: FinanceReceivableArgs) -> ProbeReading:
        try:
            from app.modules.finance.service import FinanceService
        except ImportError:  # oe_finance is an optional dependency
            return ProbeReading.unknown("probe_unavailable", "oe_finance is not installed")
        claim = await _claim(session, ctx, args.contract_ref, args.claim_selector)
        if isinstance(claim, ProbeReading):
            return claim
        invoice = await FinanceService(session).get_receivable_for_claim(claim.id)
        if invoice is None:
            return ProbeReading.unknown("not_found", "receivable invoice")
        refused = _owned(invoice.project_id, ctx, "receivable invoice")
        if refused is not None:
            return refused
        return _decimal_field(invoice, args.field)


# ── Variations ───────────────────────────────────────────────────────────────


def _creation_order(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=lambda r: (r.created_at, r.code or ""))


@register_probe("variation.request")
class VariationRequestProbe(Probe):
    """A variation request of the learner's project (requests carry no contract)."""

    args_model = VariationRequestArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: VariationRequestArgs) -> ProbeReading:
        from app.modules.variations.repository import VariationRequestRepository

        rows, _total = await VariationRequestRepository(session).list_for_project(ctx.project_id, limit=10_000)
        request = _select(_creation_order(rows), args.variation_ref, None, "variation request")
        if isinstance(request, ProbeReading):
            return request
        if args.field == "status":
            return ProbeReading.of(request.status or None)
        return _decimal_field(request, args.field)


@register_probe("variation.order")
class VariationOrderProbe(Probe):
    """A variation order whose ``affected_contract_id`` is the seeded contract."""

    args_model = VariationOrderArgs

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: VariationOrderArgs) -> ProbeReading:
        from app.modules.variations.repository import VariationOrderRepository

        contract = await _contract(session, ctx, args.contract_ref)
        if isinstance(contract, ProbeReading):
            return contract
        orders = await VariationOrderRepository(session).list_all_for_project(ctx.project_id)
        mine = _creation_order([o for o in orders if o.affected_contract_id == contract.id])
        order = _select(mine, args.variation_ref, None, "variation order on the contract")
        if isinstance(order, ProbeReading):
            return order
        if args.field == "status":
            return ProbeReading.of(order.status or None)
        return _decimal_field(order, args.field)


# ── Panel ────────────────────────────────────────────────────────────────────


async def _answer(session: AsyncSession, ctx: ProbeContext, name: str) -> Any | ProbeReading:
    from app.modules.trainer.models import TrainerAnswer

    if ctx.enrolment_id is None or ctx.task_id is None:
        return ProbeReading.unknown("ref_missing", "enrolment or task")
    stmt = select(TrainerAnswer).where(
        TrainerAnswer.enrolment_id == ctx.enrolment_id,
        TrainerAnswer.task_id == ctx.task_id,
        TrainerAnswer.answer_name == name,
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return _one(rows, f"answer {name!r}")


@register_probe("panel.answer")
class PanelAnswerProbe(Probe):
    """A typed answer of this task, as stored. Does not read the ERP."""

    args_model = PanelAnswerArgs
    reads_erp = False

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: PanelAnswerArgs) -> ProbeReading:
        answer = await _answer(session, ctx, args.answer_name)
        if isinstance(answer, ProbeReading):
            return answer
        return ProbeReading.of(answer.value_text or None)


@register_probe("panel.option")
class PanelOptionProbe(Probe):
    """The option index chosen for this task's trace or explain question."""

    args_model = PanelOptionArgs
    reads_erp = False

    async def read(self, session: AsyncSession, ctx: ProbeContext, args: PanelOptionArgs) -> ProbeReading:
        name = ctx.question_answer_names.get(args.question)
        if name is None:
            return ProbeReading.unknown("not_found", f"{args.question} question")
        answer = await _answer(session, ctx, name)
        if isinstance(answer, ProbeReading):
            return answer
        if answer.option_index is None:
            return ProbeReading.unknown("not_set", name)
        return ProbeReading.of(Decimal(int(answer.option_index)))
