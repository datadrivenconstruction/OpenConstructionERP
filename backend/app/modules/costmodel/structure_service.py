# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project cost structure: code lists, the account tree, and the vectors of bill positions.

Three things live here, each on top of the Cost Spine (control accounts and
cost lines) that the rest of the platform already reads:

* **Code lists.** The shipped and pack lists come from :mod:`app.core.code_lists`;
  a list a company keeps for itself is imported from CSV or Excel, validated row
  by row, and stored per project.
* **The tree.** Accounts nest by ``parent_id``. Every node reports what is posted
  on it (the estimate of its cost lines), its own amount and its total, and the
  money that reaches no postable account sits in two visible suspense buckets
  instead of vanishing.
* **Vectors.** A bill position is on one cost line through
  ``Position.cost_line_id``, or split over several by percent or by quantity
  (:class:`~app.modules.costmodel.models.PositionAllocation`). The estimate of
  every cost line a write touches is recomputed from what it carries, so a
  split moves money between lines and never counts it twice.
"""

from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.code_lists import (
    SOURCE_CUSTOM,
    CodeList,
    CodeListEntry,
    CodeListParseError,
    available_code_lists,
    build_entries,
    code_sort_key,
    parent_for,
    parse_code_list_file,
    same_code,
)
from app.core.code_lists import get_code_list as get_shared_code_list
from app.modules.costmodel.inheritance import SOURCE_CONTRACT_LINE
from app.modules.costmodel.models import ControlAccount, CostCodeList, CostLine, LineAllocation, PositionAllocation
from app.modules.costmodel.repository import ControlAccountRepository, _amount_in_base
from app.modules.costmodel.structure import (
    MODE_QUANTITY,
    ZERO,
    AllocationError,
    AllocationView,
    PositionView,
    TreeNodeIn,
    check_shares,
    estimate_fields,
    fractions_of,
    line_contributions,
    share_fractions,
    split_amount,
    tree_totals,
)
from app.modules.costmodel.structure_schemas import (
    AllocationCoverage,
    AllocationRowOut,
    ApplyCodeListResult,
    BoqAllocations,
    CodeListDetail,
    CodeListEntryOut,
    CodeListImportResult,
    CodeListIssueOut,
    CodeListSummary,
    PositionAllocationOut,
    PositionAllocationRequest,
    StructureFinding,
    StructureNode,
    StructureTree,
    SuspenseBucket,
)

logger = logging.getLogger(__name__)

#: Line sources whose estimate is the bill's: recomputed from what they carry, zero when they carry nothing.
DERIVED_LINE_SOURCES: frozenset[str] = frozenset({"boq", "allocation"})
#: The source of a line made to receive shares put on an account rather than on a line.
SOURCE_ALLOCATION = "allocation"

_KEY_RE = re.compile(r"^[a-z][a-z0-9_\-]{1,39}$")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _problem(code: int, problem: str, message: str, **params: Any) -> HTTPException:
    """An HTTP error whose detail carries a stable problem key next to an English sentence."""
    return HTTPException(status_code=code, detail={"problem": problem, "message": message, "params": params})


def _dec(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except (ArithmeticError, ValueError):
        return ZERO
    return value if value.is_finite() else ZERO


def _summary(code_list: CodeList) -> CodeListSummary:
    return CodeListSummary(
        key=code_list.key,
        name=code_list.name,
        standard=code_list.standard,
        source=code_list.source,  # type: ignore[arg-type]
        pack_slug=code_list.pack_slug,
        entry_count=len(code_list.entries),
        depth=code_list.depth,
    )


def _entry_out(entry: CodeListEntry) -> CodeListEntryOut:
    return CodeListEntryOut(code=entry.code, title=entry.title, parent=entry.parent, level=entry.level)


def _custom_to_code_list(row: CostCodeList) -> CodeList:
    entries = tuple(
        CodeListEntry(
            code=str(e.get("code") or ""),
            title=str(e.get("title") or ""),
            parent=e.get("parent") or None,
            level=int(e.get("level") or 1),
        )
        for e in (row.entries or [])
        if isinstance(e, dict) and e.get("code")
    )
    return CodeList(key=row.key, name=row.name, standard=row.key, source=SOURCE_CUSTOM, entries=entries)


def position_code(classification: object, standard: str) -> str | None:
    """The position's code in ``standard`` and in no other.

    The spine generator used to fall back to the first other standard a position
    carried, which built one tree out of DIN 276 and MasterFormat codes at once.
    A position without a code of the chosen standard now has no code here, and
    its line goes to the suspense bucket where someone can see and fix it.
    """
    if not standard or not isinstance(classification, dict):
        return None
    raw = classification.get(standard)
    if raw in (None, ""):
        return None
    code = str(raw).strip()
    return code or None


class AccountTreeBuilder:
    """Find or create the account for a code, with every ancestor the code needs.

    Works through the account repository only (no direct session use), so the
    spine generator can drive it the same way in production and in tests.
    """

    def __init__(
        self,
        repo: Any,
        project_id: uuid.UUID,
        standard: str,
        code_list: CodeList | None,
        existing: list[Any],
    ) -> None:
        self.repo = repo
        self.project_id = project_id
        self.standard = standard
        self.code_list = code_list
        self.created = 0
        self._by_code: dict[str, SimpleNamespace] = {}
        for a in existing:
            view = SimpleNamespace(
                id=a.id,
                code=a.code,
                level=int(getattr(a, "level", 1) or 1),
                standard=getattr(a, "classification_standard", "") or "",
            )
            self._by_code[a.code] = view

    def _find(self, code: str) -> SimpleNamespace | None:
        for known, view in self._by_code.items():
            if same_code(known, code):
                return view
        return None

    async def ensure(self, code: str) -> uuid.UUID | None:
        """The id of the account for ``code``, created with its ancestors when missing."""
        hit = self._find(code)
        if hit is not None:
            return hit.id
        entry = self.code_list.find(code) if self.code_list is not None else None
        if entry is not None:
            chain = [*self.code_list.ancestors(entry.code), entry]  # type: ignore[union-attr]
            parent_id: uuid.UUID | None = None
            parent_level = 0
            for link in chain:
                view = self._find(link.code)
                if view is None:
                    view = await self._create(link.code, link.title, parent_id, parent_level + 1)
                parent_id, parent_level = view.id, view.level
            return parent_id
        # A code the list does not carry (deeper than it, or no list at all):
        # it hangs under the most specific code above it, from the list or from
        # the accounts already there.
        candidates = [e.code for e in self.code_list.entries] if self.code_list is not None else []
        candidates += [c for c, v in self._by_code.items() if v.standard in ("", self.standard)]
        parent_code = parent_for(code, candidates)
        parent_view = None
        if parent_code is not None:
            parent_id = await self.ensure(parent_code)
            parent_view = next((v for v in self._by_code.values() if v.id == parent_id), None)
        view = await self._create(
            code,
            "",
            parent_view.id if parent_view else None,
            (parent_view.level + 1) if parent_view else 1,
        )
        return view.id

    async def _create(self, code: str, title: str, parent_id: uuid.UUID | None, level: int) -> SimpleNamespace:
        account = ControlAccount(
            project_id=self.project_id,
            parent_id=parent_id,
            code=code,
            name=(title or code)[:255],
            title=title[:255],
            level=level,
            own_amount=Decimal("0"),
            is_leaf_postable=True,
            classification_standard=self.standard,
            status="open",
            sort_order=0,
            metadata_={},
        )
        account = await self.repo.create(account)
        # Capture the id now; the ORM object expires on the next write.
        view = SimpleNamespace(id=account.id, code=code, level=level, standard=self.standard)
        self._by_code[code] = view
        self.created += 1
        return view


class CostStructureService:
    """Code lists, the account tree and position vectors for one project at a time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.account_repo = ControlAccountRepository(session)

    # ── Code lists ──────────────────────────────────────────────────────────

    async def _custom_lists(self, project_id: uuid.UUID | None) -> list[CodeList]:
        if project_id is None:
            return []
        rows = (
            (await self.session.execute(select(CostCodeList).where(CostCodeList.project_id == project_id)))
            .scalars()
            .all()
        )
        return [_custom_to_code_list(r) for r in sorted(rows, key=lambda r: r.key)]

    async def code_list(self, key: str, project_id: uuid.UUID | None) -> CodeList | None:
        """A shipped, pack or (for the project) imported list by key."""
        shared = get_shared_code_list(key)
        if shared is not None:
            return shared
        for custom in await self._custom_lists(project_id):
            if custom.key == key:
                return custom
        return None

    async def list_code_lists(self, project_id: uuid.UUID | None) -> list[CodeListSummary]:
        """Every list a structure in this project can be built from."""
        lists = [*available_code_lists(), *await self._custom_lists(project_id)]
        return [_summary(c) for c in lists]

    async def code_list_detail(self, key: str, project_id: uuid.UUID | None) -> CodeListDetail:
        """One list with its entries, or 404."""
        found = await self.code_list(key, project_id)
        if found is None:
            raise _problem(status.HTTP_404_NOT_FOUND, "code_list_unknown", "Code list not found", key=key)
        return CodeListDetail(**_summary(found).model_dump(), entries=[_entry_out(e) for e in found.entries])

    async def import_code_list(
        self,
        project_id: uuid.UUID,
        *,
        filename: str,
        content: bytes,
        key: str,
        name: str,
        dry_run: bool,
        user_id: str | None,
    ) -> CodeListImportResult:
        """Validate an uploaded list and, unless ``dry_run`` or anything is wrong, store it.

        All rows or none: a list with one bad row is not stored, and every bad row
        is reported against its own row number so it can be fixed in one pass.
        """
        key = (key or "").strip().lower()
        name = (name or "").strip()
        if not _KEY_RE.match(key):
            raise _problem(status.HTTP_400_BAD_REQUEST, "key_invalid", "Use 2-40 lower-case letters, digits, - or _")
        if not name:
            raise _problem(status.HTTP_400_BAD_REQUEST, "name_missing", "Give the code list a name")
        if len(content) > MAX_UPLOAD_BYTES:
            raise _problem(status.HTTP_400_BAD_REQUEST, "file_too_large", "File too large", max=MAX_UPLOAD_BYTES)
        if get_shared_code_list(key) is not None or any(c.key == key for c in await self._custom_lists(project_id)):
            raise _problem(status.HTTP_409_CONFLICT, "key_taken", "A code list with this key exists", key=key)
        try:
            rows = parse_code_list_file(filename, content)
        except CodeListParseError as exc:
            raise _problem(status.HTTP_400_BAD_REQUEST, exc.problem, "File cannot be read", **exc.params) from exc
        entries, issues = build_entries(rows)
        depth = max((e.level for e in entries), default=0)
        result = CodeListImportResult(
            ok=not issues,
            dry_run=dry_run,
            key=key,
            name=name,
            entry_count=len(entries),
            depth=depth,
            issues=[CodeListIssueOut(row=i.row, code=i.code, problem=i.problem, params=i.params) for i in issues],
            preview=[_entry_out(e) for e in entries[:200]],
        )
        if issues or dry_run:
            return result
        row = CostCodeList(
            project_id=project_id,
            key=key,
            name=name[:200],
            entries=[{"code": e.code, "title": e.title, "parent": e.parent, "level": e.level} for e in entries],
            created_by=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        result.code_list = _summary(_custom_to_code_list(row))
        return result

    async def delete_code_list(self, project_id: uuid.UUID, key: str) -> None:
        """Remove an imported list; refused while accounts are built from it."""
        row = (
            await self.session.execute(
                select(CostCodeList).where(CostCodeList.project_id == project_id, CostCodeList.key == key)
            )
        ).scalar_one_or_none()
        if row is None:
            raise _problem(status.HTTP_404_NOT_FOUND, "code_list_unknown", "Code list not found", key=key)
        in_use = (
            await self.session.execute(
                select(func.count())
                .select_from(ControlAccount)
                .where(ControlAccount.project_id == project_id, ControlAccount.classification_standard == key)
            )
        ).scalar_one()
        if in_use:
            raise _problem(
                status.HTTP_409_CONFLICT, "code_list_in_use", "Accounts are built from this list", accounts=in_use
            )
        await self.session.delete(row)
        await self.session.flush()

    # ── Building the tree ───────────────────────────────────────────────────

    async def _structure_standards(self, project_id: uuid.UUID) -> set[str]:
        rows = (
            await self.session.execute(
                select(ControlAccount.classification_standard).where(ControlAccount.project_id == project_id).distinct()
            )
        ).all()
        return {(r[0] or "").strip() for r in rows if (r[0] or "").strip()}

    async def apply_code_list(self, project_id: uuid.UUID, key: str, max_level: int | None) -> ApplyCodeListResult:
        """Create the accounts of a list (down to ``max_level``), keeping any that exist."""
        code_list = await self.code_list(key, project_id)
        if code_list is None:
            raise _problem(status.HTTP_404_NOT_FOUND, "code_list_unknown", "Code list not found", key=key)
        used = await self._structure_standards(project_id)
        if used and key not in used:
            raise _problem(
                status.HTTP_409_CONFLICT,
                "structure_standard_mismatch",
                "The cost structure of this project is built from another code list",
                standard=sorted(used)[0],
                requested=key,
            )
        builder = AccountTreeBuilder(
            self.account_repo, project_id, key, code_list, await self.account_repo.list_for_project(project_id)
        )
        for entry in code_list.entries:
            if max_level is not None and entry.level > max_level:
                continue
            await builder.ensure(entry.code)
        return ApplyCodeListResult(key=key, accounts_created=builder.created)

    # ── Reading the tree ────────────────────────────────────────────────────

    async def _line_amounts(self, project_id: uuid.UUID) -> tuple[str, list[SimpleNamespace]]:
        from app.modules.costmodel.repository import CostSpineRepository

        base, fx = await CostSpineRepository(self.session)._fx_context(project_id)
        rows = (
            await self.session.execute(
                select(
                    CostLine.id,
                    CostLine.code,
                    CostLine.control_account_id,
                    CostLine.estimate_amount,
                    CostLine.currency,
                ).where(CostLine.project_id == project_id, CostLine.status != "archived")
            )
        ).all()
        lines = [
            SimpleNamespace(
                id=lid,
                code=code,
                account_id=acct,
                amount=_amount_in_base(str(amount or "0"), (ccy or "").strip().upper(), base, fx),
            )
            for lid, code, acct, amount, ccy in rows
        ]
        return base, lines

    async def tree(self, project_id: uuid.UUID, *, locale: str = "en") -> StructureTree:
        """The structure with its money, its suspense buckets and its findings."""
        accounts = await self.account_repo.list_for_project(project_id)
        currency, lines = await self._line_amounts(project_id)
        by_id = {a.id: a for a in accounts}
        posted: dict[uuid.UUID, Decimal] = {}
        counts: dict[uuid.UUID, int] = {}
        no_account: list[SimpleNamespace] = []
        invalid: list[SimpleNamespace] = []
        for line in lines:
            account = by_id.get(line.account_id) if line.account_id else None
            if account is None:
                no_account.append(line)
                continue
            posted[account.id] = posted.get(account.id, ZERO) + line.amount
            counts[account.id] = counts.get(account.id, 0) + 1
            if not account.is_leaf_postable or (account.status or "") == "closed":
                invalid.append(line)
        totals = tree_totals(
            TreeNodeIn(
                id=str(a.id),
                parent_id=str(a.parent_id) if a.parent_id else None,
                own_amount=_dec(a.own_amount),
                posted=posted.get(a.id, ZERO),
            )
            for a in accounts
        )
        nodes = []
        for a in accounts:
            t = totals[str(a.id)]
            nodes.append(
                StructureNode(
                    id=a.id,
                    parent_id=a.parent_id if a.parent_id in by_id else None,
                    code=a.code,
                    title=a.title or ("" if same_code(a.name, a.code) else a.name),
                    name=a.name,
                    level=t.level,
                    classification_standard=a.classification_standard or "",
                    status=a.status or "open",
                    is_leaf_postable=bool(a.is_leaf_postable),
                    own_amount=_dec(a.own_amount),
                    posted=posted.get(a.id, ZERO),
                    children_total=t.children_total,
                    total=t.total,
                    line_count=counts.get(a.id, 0),
                    child_count=len(t.children),
                )
            )
        suspense = [
            SuspenseBucket(
                kind="no_account",
                line_count=len(no_account),
                amount=sum((ln.amount for ln in no_account), ZERO),
                line_ids=[ln.id for ln in no_account][:500],
            ),
            SuspenseBucket(
                kind="invalid_account",
                line_count=len(invalid),
                amount=sum((ln.amount for ln in invalid), ZERO),
                line_ids=[ln.id for ln in invalid][:500],
            ),
        ]
        grand = sum((totals[str(a.id)].total for a in accounts if totals[str(a.id)].level == 1), ZERO)
        grand += suspense[0].amount
        tree = StructureTree(
            project_id=project_id,
            currency=currency,
            standards=sorted({a.classification_standard for a in accounts if a.classification_standard}),
            nodes=nodes,
            suspense=suspense,
            total=grand,
        )
        payload = await self.validation_payload(project_id, accounts=accounts, lines=lines, tree=tree)
        tree.findings = await self.findings(project_id, payload, locale=locale)
        return tree

    # ── Validation ──────────────────────────────────────────────────────────

    async def validation_payload(
        self,
        project_id: uuid.UUID,
        *,
        accounts: list[Any] | None = None,
        lines: list[SimpleNamespace] | None = None,
        tree: StructureTree | None = None,
    ) -> dict[str, Any]:
        """Everything rules V1 to V5 read, as plain data."""
        from app.modules.boq.models import BOQ, Position
        from app.modules.contracts.models import Contract, ContractLine

        if accounts is None:
            accounts = await self.account_repo.list_for_project(project_id)
        if lines is None:
            _, lines = await self._line_amounts(project_id)
        if tree is None:
            tree = await self.tree(project_id)
        depth_limits: dict[str, int] = {}
        for std in {a.classification_standard for a in accounts if a.classification_standard}:
            code_list = await self.code_list(std, project_id)
            if code_list is not None and code_list.max_depth:
                depth_limits[std] = code_list.max_depth
        level_of = {str(n.id): n.level for n in tree.nodes}
        total_of = {str(n.id): n.total for n in tree.nodes}

        # Split positions and their shares.
        alloc_rows = (
            await self.session.execute(
                select(
                    PositionAllocation.position_id,
                    PositionAllocation.cost_line_id,
                    PositionAllocation.mode,
                    PositionAllocation.share,
                ).where(PositionAllocation.project_id == project_id)
            )
        ).all()
        by_pos: dict[str, list[tuple[str, str, Decimal]]] = {}
        for pid, lid, mode, share in alloc_rows:
            by_pos.setdefault(str(pid), []).append((str(lid), mode, _dec(share)))
        pos_info: dict[str, tuple[str, Decimal]] = {}
        if by_pos:
            prow = (
                await self.session.execute(
                    select(Position.id, Position.ordinal, Position.quantity).where(
                        Position.id.in_([uuid.UUID(p) for p in by_pos])
                    )
                )
            ).all()
            pos_info = {str(i): (o or "", _dec(q)) for i, o, q in prow}

        # Vectors per position, to compare the contract lines that came from them.
        vectors: dict[str, set[str]] = {p: {lid for lid, _, _ in rows} for p, rows in by_pos.items()}
        single = (
            await self.session.execute(
                select(Position.id, Position.cost_line_id)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id, Position.cost_line_id.is_not(None))
            )
        ).all()
        for pid, lid in single:
            vectors.setdefault(str(pid), set()).add(str(lid))
        # Every contract line of the project, the split ones included: a line frozen into a
        # split carries no single cost line, its accounts are its LineAllocation rows.
        contract_rows = (
            await self.session.execute(
                select(ContractLine.id, ContractLine.code, ContractLine.cost_line_id, ContractLine.metadata_)
                .join(Contract, Contract.id == ContractLine.contract_id)
                .where(Contract.project_id == project_id)
            )
        ).all()
        split_rows = (
            await self.session.execute(
                select(LineAllocation.source_id, LineAllocation.cost_line_id).where(
                    LineAllocation.project_id == project_id,
                    LineAllocation.source_type == SOURCE_CONTRACT_LINE,
                )
            )
        ).all()
        split_of: dict[str, list[str]] = {}
        for sid, lid in split_rows:
            split_of.setdefault(str(sid), []).append(str(lid))
        inherited = []
        for cid, code, lid, meta in contract_rows:
            meta = meta if isinstance(meta, dict) else {}
            pos_id = str(meta.get("boq_position_id") or "").strip()
            if not pos_id or pos_id not in vectors:
                continue
            split = sorted(split_of.get(str(cid), []))
            if lid is None and not split:
                # On no cost line at all: the suspense bucket lists it, not this check.
                continue
            override = meta.get("cost_line_override")
            inherited.append(
                {
                    "kind": "contract_line",
                    "id": str(cid),
                    "code": code or "",
                    "position_id": pos_id,
                    "cost_line_id": str(lid) if lid is not None else None,
                    "cost_line_ids": split,
                    "vector": sorted(vectors[pos_id]),
                    "override_audited": isinstance(override, dict)
                    and bool(str(override.get("reason") or "").strip())
                    and bool(override.get("by")),
                }
            )

        return {
            "accounts": [
                {
                    "id": str(a.id),
                    "code": a.code,
                    "parent_id": str(a.parent_id) if a.parent_id else None,
                    "standard": a.classification_standard or "",
                    "level": level_of.get(str(a.id), 1),
                    "own_amount": str(_dec(a.own_amount)),
                    "is_leaf_postable": bool(a.is_leaf_postable),
                    "status": a.status or "open",
                    "total": str(total_of.get(str(a.id), ZERO)),
                }
                for a in accounts
            ],
            "depth_limits": depth_limits,
            "lines": [
                {
                    "id": str(ln.id),
                    "code": ln.code,
                    "account_id": str(ln.account_id) if ln.account_id else None,
                    "amount": str(ln.amount),
                }
                for ln in lines
            ],
            "allocations": [
                {
                    "position_id": pid,
                    "ordinal": pos_info.get(pid, ("", ZERO))[0],
                    "quantity": str(pos_info.get(pid, ("", ZERO))[1]),
                    "modes": sorted({m for _, m, _ in rows}),
                    "shares": [str(s) for _, _, s in rows],
                }
                for pid, rows in by_pos.items()
            ],
            "inherited": inherited,
            "reported_total": str(tree.total),
            "currency": tree.currency,
        }

    async def findings(self, project_id: uuid.UUID, payload: dict[str, Any], *, locale: str) -> list[StructureFinding]:
        """Run the ``cost_structure`` rule set on the payload."""
        from app.core.validation.engine import ValidationContext, rule_registry
        from app.modules.costmodel.structure_rules import PAYLOAD_KEY, RULE_SET

        context = ValidationContext(
            data={PAYLOAD_KEY: payload}, project_id=str(project_id), metadata={"locale": locale}
        )
        out: list[StructureFinding] = []
        for rule in rule_registry.get_rules_for_sets([RULE_SET]):
            if not rule.enabled:
                continue
            for r in await rule.validate(context):
                if r.passed:
                    continue
                out.append(
                    StructureFinding(
                        rule_id=r.rule_id,
                        severity=r.severity.value,  # type: ignore[arg-type]
                        message=r.message,
                        suggestion=r.suggestion or "",
                        element_ref=r.element_ref,
                        details={k: v for k, v in r.details.items()},
                    )
                )
        order = {"error": 0, "warning": 1, "info": 2}
        out.sort(key=lambda f: (order.get(f.severity, 3), f.rule_id, str(f.details.get("code") or "")))
        return out

    # ── Vectors ─────────────────────────────────────────────────────────────

    async def _position_and_project(self, position_id: uuid.UUID) -> tuple[Any, uuid.UUID]:
        from app.modules.boq.models import BOQ, Position

        pos = await self.session.get(Position, position_id)
        if pos is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
        boq = await self.session.get(BOQ, pos.boq_id)
        if boq is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
        return pos, boq.project_id

    async def project_of_position(self, position_id: uuid.UUID) -> uuid.UUID:
        """The project a position belongs to (for access checks), or 404."""
        _, project_id = await self._position_and_project(position_id)
        return project_id

    async def account_line(self, project_id: uuid.UUID, boq_id: uuid.UUID, account: ControlAccount) -> uuid.UUID:
        """The bill's line for shares put on an account, made on first use."""
        found = (
            await self.session.execute(
                select(CostLine.id)
                .where(
                    CostLine.project_id == project_id,
                    CostLine.boq_id == boq_id,
                    CostLine.control_account_id == account.id,
                    CostLine.source == SOURCE_ALLOCATION,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if found is not None:
            return found
        taken = set(
            (await self.session.execute(select(CostLine.code).where(CostLine.project_id == project_id))).scalars().all()
        )
        code, n = account.code, 1
        while code in taken:
            n += 1
            code = f"{account.code}-{n}"
        currency = ""
        try:
            from app.modules.projects.models import Project

            project = await self.session.get(Project, project_id)
            currency = (getattr(project, "currency", "") or "") if project is not None else ""
        except Exception:  # noqa: BLE001 - currency is cosmetic here, the report converts by line currency
            currency = ""
        line = CostLine(
            project_id=project_id,
            control_account_id=account.id,
            code=code[:80],
            description=(account.title or account.name or account.code)[:2000],
            unit=None,
            source=SOURCE_ALLOCATION,
            boq_id=boq_id,
            estimate_quantity="0",
            estimate_unit_rate="0",
            estimate_amount="0",
            currency=currency,
            status="active",
        )
        self.session.add(line)
        await self.session.flush()
        return line.id

    async def set_allocation(
        self, position_id: uuid.UUID, request: PositionAllocationRequest, user_id: str | None
    ) -> PositionAllocationOut:
        """Write a position's whole vector: one line, or shares over several."""
        pos, project_id = await self._position_and_project(position_id)
        if not pos.unit:
            raise _problem(status.HTTP_400_BAD_REQUEST, "not_costed", "A section row carries no cost")
        try:
            fractions_of(request.mode, [r.share for r in request.rows], pos.quantity)
        except AllocationError as exc:
            raise _problem(422, exc.problem, "The shares cannot be applied", **exc.params) from exc

        own_line = (
            await self.session.execute(
                select(CostLine).where(CostLine.project_id == project_id, CostLine.boq_position_id == pos.id).limit(1)
            )
        ).scalar_one_or_none()
        old_rows = (
            (await self.session.execute(select(PositionAllocation).where(PositionAllocation.position_id == pos.id)))
            .scalars()
            .all()
        )
        # A duplicated bill inherits its source's vectors, so its positions point at lines of
        # the source bill. Keeping such a line, for example to change its share, stays allowed;
        # only moving a position onto a line of another bill it was not on is refused.
        current_lines: set[uuid.UUID] = {r.cost_line_id for r in old_rows}
        if pos.cost_line_id is not None:
            current_lines.add(pos.cost_line_id)
        targets: list[tuple[uuid.UUID, Decimal]] = []
        for row in request.rows:
            if row.cost_line_id is not None:
                line = await self.session.get(CostLine, row.cost_line_id)
                if line is None:
                    raise _problem(status.HTTP_400_BAD_REQUEST, "target_missing", "Cost line not found")
                if line.project_id != project_id:
                    raise _problem(status.HTTP_400_BAD_REQUEST, "target_not_in_project", "Cost line of another project")
                if (line.status or "") == "archived":
                    raise _problem(status.HTTP_400_BAD_REQUEST, "target_missing", "Cost line not found")
                if line.boq_id is not None and line.boq_id != pos.boq_id and line.id not in current_lines:
                    raise _problem(
                        status.HTTP_400_BAD_REQUEST, "line_of_other_bill", "This cost line carries another bill"
                    )
                targets.append((line.id, row.share))
            elif row.control_account_id is not None:
                account = await self.session.get(ControlAccount, row.control_account_id)
                if account is None:
                    raise _problem(status.HTTP_400_BAD_REQUEST, "target_missing", "Account not found")
                if account.project_id != project_id:
                    raise _problem(status.HTTP_400_BAD_REQUEST, "target_not_in_project", "Account of another project")
                # A heading or a closed account takes no postings: money put there would only
                # land in the invalid-account suspense bucket.
                if not account.is_leaf_postable or (account.status or "") == "closed":
                    raise _problem(
                        status.HTTP_400_BAD_REQUEST, "account_not_postable", "This account takes no postings"
                    )
                if own_line is not None and own_line.control_account_id == account.id:
                    targets.append((own_line.id, row.share))
                else:
                    targets.append((await self.account_line(project_id, pos.boq_id, account), row.share))
            else:
                raise _problem(status.HTTP_400_BAD_REQUEST, "target_missing", "Name a cost line or an account")
        if len({t for t, _ in targets}) != len(targets):
            raise _problem(422, "duplicate_target", "Each cost line may appear once")

        touched: set[uuid.UUID] = {r.cost_line_id for r in old_rows}
        if pos.cost_line_id is not None:
            touched.add(pos.cost_line_id)
        await self.session.execute(delete(PositionAllocation).where(PositionAllocation.position_id == pos.id))
        if len(targets) == 1:
            primary = targets[0][0]
        else:
            # The main line is the largest share; on a tie, the first one named.
            primary = max(enumerate(targets), key=lambda it: (it[1][1], -it[0]))[1][0]
            for line_id, share in targets:
                self.session.add(
                    PositionAllocation(
                        project_id=project_id,
                        boq_id=pos.boq_id,
                        position_id=pos.id,
                        cost_line_id=line_id,
                        mode=request.mode,
                        share=share,
                        created_by=user_id,
                        note=request.note or "",
                    )
                )
        pos.cost_line_id = primary
        await self.session.flush()
        touched.update(t for t, _ in targets)
        await self.recompute_lines(touched)
        _publish(
            self.session,
            "costmodel.allocation.changed",
            {"project_id": str(project_id), "position_id": str(pos.id), "lines": len(targets), "by": user_id or ""},
        )
        return (await self._positions_out(pos.boq_id, only=[pos.id]))[0]

    async def clear_allocation(self, position_id: uuid.UUID, user_id: str | None) -> PositionAllocationOut:
        """Take a position off every cost line."""
        pos, project_id = await self._position_and_project(position_id)
        rows = (
            (await self.session.execute(select(PositionAllocation).where(PositionAllocation.position_id == pos.id)))
            .scalars()
            .all()
        )
        touched = {r.cost_line_id for r in rows}
        if pos.cost_line_id is not None:
            touched.add(pos.cost_line_id)
        await self.session.execute(delete(PositionAllocation).where(PositionAllocation.position_id == pos.id))
        pos.cost_line_id = None
        await self.session.flush()
        await self.recompute_lines(touched)
        _publish(
            self.session,
            "costmodel.allocation.changed",
            {"project_id": str(project_id), "position_id": str(pos.id), "lines": 0, "by": user_id or ""},
        )
        return (await self._positions_out(pos.boq_id, only=[pos.id]))[0]

    async def recompute_lines(self, line_ids: set[uuid.UUID] | list[uuid.UUID]) -> int:
        """Refresh the estimate of each line from what it carries now. Returns how many changed.

        A line owned by a bill takes only that bill's positions. A manual line
        (no bill) takes from every position put on it and keeps its own figures
        when none is.
        """
        from app.modules.boq.models import Position

        ids = [i for i in {*line_ids} if i is not None]
        if not ids:
            return 0
        lines = (await self.session.execute(select(CostLine).where(CostLine.id.in_(ids)))).scalars().all()
        if not lines:
            return 0
        alloc_pos = set(
            (
                await self.session.execute(
                    select(PositionAllocation.position_id).where(PositionAllocation.cost_line_id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        positions = (
            (
                await self.session.execute(
                    select(Position).where(
                        or_(Position.cost_line_id.in_(ids), Position.id.in_(alloc_pos or [uuid.uuid4()]))
                    )
                )
            )
            .scalars()
            .all()
        )
        pos_ids = [p.id for p in positions]
        allocs = (
            (
                await self.session.execute(
                    select(PositionAllocation).where(PositionAllocation.position_id.in_(pos_ids or [uuid.uuid4()]))
                )
            )
            .scalars()
            .all()
        )
        contributions = line_contributions(
            [
                PositionView(
                    id=str(p.id),
                    boq_id=str(p.boq_id),
                    total=p.total,
                    quantity=p.quantity,
                    unit=p.unit or "",
                    cost_line_id=str(p.cost_line_id) if p.cost_line_id else None,
                    unit_rate=p.unit_rate,
                )
                for p in positions
            ],
            [AllocationView(str(a.position_id), str(a.cost_line_id), a.mode, a.share) for a in allocs],
            line_boq={str(ln.id): (str(ln.boq_id) if ln.boq_id else None) for ln in lines},
        )
        changed = 0
        for line in lines:
            contribution = contributions.get(str(line.id))
            if contribution is None and (line.source or "") not in DERIVED_LINE_SOURCES:
                continue
            fields = estimate_fields(contribution, line.unit)
            if any(str(getattr(line, k) or "0") != v for k, v in fields.items()):
                for k, v in fields.items():
                    setattr(line, k, v)
                changed += 1
        if changed:
            await self.session.flush()
        return changed

    async def recompute_after_bill_change(
        self, position_ids: set[uuid.UUID] | list[uuid.UUID], boq_ids: set[uuid.UUID] | list[uuid.UUID]
    ) -> int:
        """Refresh the cost lines that edited or deleted bill positions feed. Returns how many changed.

        An edited position feeds its own generated line, the line it points at and
        the lines of its shares. A deleted position can no longer be asked (its
        shares went with it), so a delete refreshes every line of its bill.
        """
        from app.modules.boq.models import Position

        line_ids: set[uuid.UUID] = set()
        pids = [p for p in {*position_ids} if p is not None]
        if pids:
            line_ids.update(
                (await self.session.execute(select(CostLine.id).where(CostLine.boq_position_id.in_(pids)))).scalars()
            )
            line_ids.update(
                x
                for x in (
                    await self.session.execute(select(Position.cost_line_id).where(Position.id.in_(pids)))
                ).scalars()
                if x is not None
            )
            line_ids.update(
                (
                    await self.session.execute(
                        select(PositionAllocation.cost_line_id).where(PositionAllocation.position_id.in_(pids))
                    )
                ).scalars()
            )
        bills = [b for b in {*boq_ids} if b is not None]
        if bills:
            line_ids.update(
                (
                    await self.session.execute(
                        select(CostLine.id).where(CostLine.boq_id.in_(bills), CostLine.status != "archived")
                    )
                ).scalars()
            )
        return await self.recompute_lines(line_ids)

    async def _positions_out(
        self, boq_id: uuid.UUID, *, only: list[uuid.UUID] | None = None
    ) -> list[PositionAllocationOut]:
        from app.modules.boq.models import Position

        stmt = select(Position).where(Position.boq_id == boq_id)
        if only is not None:
            stmt = stmt.where(Position.id.in_(only))
        positions = (await self.session.execute(stmt.order_by(Position.sort_order, Position.ordinal))).scalars().all()
        alloc_stmt = select(PositionAllocation).where(PositionAllocation.boq_id == boq_id)
        if only is not None:
            alloc_stmt = alloc_stmt.where(PositionAllocation.position_id.in_(only))
        allocs = (await self.session.execute(alloc_stmt)).scalars().all()
        by_pos: dict[uuid.UUID, list[PositionAllocation]] = {}
        for a in allocs:
            by_pos.setdefault(a.position_id, []).append(a)
        line_ids = {a.cost_line_id for a in allocs} | {p.cost_line_id for p in positions if p.cost_line_id}
        lines = {
            ln.id: ln
            for ln in (await self.session.execute(select(CostLine).where(CostLine.id.in_(line_ids or [uuid.uuid4()]))))
            .scalars()
            .all()
        }
        acct_ids = {ln.control_account_id for ln in lines.values() if ln.control_account_id}
        accounts = {
            a.id: a
            for a in (
                await self.session.execute(
                    select(ControlAccount).where(ControlAccount.id.in_(acct_ids or [uuid.uuid4()]))
                )
            )
            .scalars()
            .all()
        }

        def _row(line_id: uuid.UUID, share: Decimal, fraction: Decimal, amount: Decimal) -> AllocationRowOut:
            line = lines.get(line_id)
            account = accounts.get(line.control_account_id) if line is not None and line.control_account_id else None
            return AllocationRowOut(
                cost_line_id=line_id,
                cost_line_code=line.code if line is not None else "",
                cost_line_description=(line.description or "") if line is not None else "",
                account_id=account.id if account is not None else None,
                account_code=account.code if account is not None else "",
                account_title=(account.title or ("" if same_code(account.name, account.code) else account.name))
                if account is not None
                else "",
                account_postable=account is not None
                and bool(account.is_leaf_postable)
                and (account.status or "") != "closed",
                share=share,
                fraction=fraction,
                amount=amount,
            )

        out: list[PositionAllocationOut] = []
        for p in positions:
            if not p.unit:
                continue
            total, qty = _dec(p.total), _dec(p.quantity)
            rows = sorted(
                by_pos.get(p.id, []), key=lambda r: code_sort_key(getattr(lines.get(r.cost_line_id), "code", ""))
            )
            base = {
                "position_id": p.id,
                "boq_id": p.boq_id,
                "ordinal": p.ordinal or "",
                "description": (p.description or "")[:300],
                "unit": p.unit or "",
                "quantity": qty,
                "total": total,
            }
            if rows:
                mode = rows[0].mode
                # The cents are cut in the order line_contributions uses (by line id), so the
                # amount the bill shows on each share is the amount that line's estimate carries,
                # also when a remainder cent falls on a tie. Display stays sorted by code.
                in_line_order = sorted(rows, key=lambda r: str(r.cost_line_id))
                views = [
                    AllocationView(str(r.position_id), str(r.cost_line_id), r.mode, r.share) for r in in_line_order
                ]
                fractions = share_fractions(views, qty)
                amounts = split_amount(total, fractions)
                cut = {r.cost_line_id: (f, a) for r, f, a in zip(in_line_order, fractions, amounts, strict=True)}
                check = check_shares(mode, [r.share for r in rows], qty)
                mixed = len({r.mode for r in rows}) > 1
                problem = None
                if mixed:
                    problem = "mixed_modes"
                elif not check.within_tolerance:
                    problem = "shares_do_not_add_up"
                out.append(
                    PositionAllocationOut(
                        **base,
                        mode="quantity" if mode == MODE_QUANTITY else "percent",
                        rows=[_row(r.cost_line_id, _dec(r.share), *cut[r.cost_line_id]) for r in rows],
                        valid=problem is None,
                        problem=problem,
                        share_total=check.total,
                        share_expected=check.expected,
                    )
                )
            elif p.cost_line_id is not None:
                out.append(
                    PositionAllocationOut(
                        **base,
                        mode="single",
                        rows=[_row(p.cost_line_id, Decimal("100"), Decimal("1"), total)],
                        share_total=Decimal("100"),
                        share_expected=Decimal("100"),
                    )
                )
            else:
                out.append(PositionAllocationOut(**base, mode="none"))
                continue
            out[-1].in_suspense = any(not r.account_postable for r in out[-1].rows)
        return out

    async def boq_allocations(self, boq_id: uuid.UUID) -> BoqAllocations:
        """Every costed position of a bill with its vector, and how much of the bill is covered."""
        from app.modules.boq.models import BOQ

        boq = await self.session.get(BOQ, boq_id)
        if boq is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
        positions = await self._positions_out(boq_id)
        value_total = sum((p.total for p in positions), ZERO)
        allocated = [p for p in positions if p.mode != "none"]
        # Money on a cost line without a postable account is in suspense, not on the
        # structure: it is counted apart so the share never reads as covered.
        value_in_suspense = sum((r.amount for p in allocated for r in p.rows if not r.account_postable), ZERO)
        value_on_lines = sum((p.total for p in allocated), ZERO)
        value_allocated = value_on_lines - value_in_suspense
        share = (value_allocated / value_total * Decimal("100")).quantize(Decimal("0.01")) if value_total else ZERO
        currency = ""
        try:
            from app.modules.projects.models import Project

            project = await self.session.get(Project, boq.project_id)
            currency = (getattr(project, "currency", "") or "") if project is not None else ""
        except Exception:  # noqa: BLE001 - the coverage does not depend on the label
            currency = ""
        return BoqAllocations(
            boq_id=boq_id,
            project_id=boq.project_id,
            currency=currency,
            coverage=AllocationCoverage(
                boq_id=boq_id,
                positions_total=len(positions),
                positions_allocated=len(allocated),
                positions_split=sum(1 for p in positions if p.mode in ("percent", "quantity")),
                positions_invalid=sum(1 for p in positions if not p.valid),
                value_total=value_total,
                value_allocated=value_allocated,
                value_unallocated=value_total - value_on_lines,
                positions_in_suspense=sum(1 for p in positions if p.in_suspense),
                value_in_suspense=value_in_suspense,
                share_pct=share,
            ),
            positions=positions,
        )


def _publish(session: AsyncSession, name: str, data: dict[str, Any]) -> None:
    """Announce a change once the caller's transaction commits (subscribers use their own session)."""
    try:
        from app.core.events import publish_after_commit

        publish_after_commit(session, name, data, source_module="oe_costmodel")
    except Exception:  # noqa: BLE001 - an event is a notification, never a reason to fail the write
        logger.debug("Event publish skipped: %s", name)


async def copy_vectors(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    new_boq_id: uuid.UUID,
    old_to_new: dict[uuid.UUID, uuid.UUID],
) -> int:
    """Give the positions of a copied bill the vectors of their originals.

    Each copy gets the original's ``cost_line_id`` and, for a split position,
    the same shares. The lines of the original bill take nothing from the copy
    (a line counts only the positions of its own bill), so no estimate moves:
    the copy carries the same vectors, not the same money twice. Generating the
    spine for the copy later moves it onto lines of its own, keeping the accounts.

    A position whose vector reaches a manual cost line (one no bill owns) is
    left off it on the copy. A manual line takes from every bill put on it, so
    copying would count the original and its revision together; the copy shows
    such positions as not allocated, where someone can decide.

    Returns how many positions got a vector.
    """
    from app.modules.boq.models import Position

    if not old_to_new:
        return 0
    old_ids = list(old_to_new)
    pointers = dict(
        (await session.execute(select(Position.id, Position.cost_line_id).where(Position.id.in_(old_ids)))).all()
    )
    rows = (
        (await session.execute(select(PositionAllocation).where(PositionAllocation.position_id.in_(old_ids))))
        .scalars()
        .all()
    )
    targets = {lid for lid in pointers.values() if lid is not None} | {r.cost_line_id for r in rows}
    if not targets:
        return 0
    owned = dict(
        (await session.execute(select(CostLine.id, CostLine.boq_id).where(CostLine.id.in_(list(targets))))).all()
    )
    shares_of: dict[uuid.UUID, list[PositionAllocation]] = {}
    for r in rows:
        shares_of.setdefault(r.position_id, []).append(r)

    copied = 0
    for old_id, new_id in old_to_new.items():
        vector = {r.cost_line_id for r in shares_of.get(old_id, [])}
        if pointers.get(old_id) is not None:
            vector.add(pointers[old_id])
        # A line that no longer exists, or a manual one: the copy stays unallocated.
        if not vector or any(owned.get(lid) is None for lid in vector):
            continue
        await session.execute(
            sa_update(Position).where(Position.id == new_id).values(cost_line_id=pointers.get(old_id))
        )
        for r in shares_of.get(old_id, []):
            session.add(
                PositionAllocation(
                    project_id=project_id,
                    boq_id=new_boq_id,
                    position_id=new_id,
                    cost_line_id=r.cost_line_id,
                    mode=r.mode,
                    share=r.share,
                    created_by=r.created_by,
                    note=r.note or "",
                )
            )
        copied += 1
    await session.flush()
    return copied
