# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Portfolio tree service (T3.3).

Node CRUD, project membership, and the access-pruned tree. Every read
intersects with ``accessible_project_ids`` and every project write goes through
``verify_project_access`` - the tree is navigation only and never widens access.
All writes ``flush`` only; the request middleware owns the commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import accessible_project_ids, verify_project_access
from app.modules.portfolio.models import (
    PortfolioCrossLink,
    PortfolioMembership,
    PortfolioNode,
)
from app.modules.portfolio.schemas import CrossLinkCreate, NodeCreate, NodePatch
from app.modules.portfolio.tree_logic import build_visible_tree


def _not_found(detail: str = "Not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


class PortfolioService:
    """Business logic for portfolio nodes + memberships."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _is_admin(self, user_id: str) -> bool:
        # accessible_project_ids returns None only for admins (no scope filter).
        return (await accessible_project_ids(self.session, user_id)) is None

    async def get_node(self, node_id: uuid.UUID) -> PortfolioNode:
        node = await self.session.get(PortfolioNode, node_id)
        if node is None:
            raise _not_found("Portfolio node not found")
        return node

    # ── Tree ─────────────────────────────────────────────────────────────────

    async def get_tree(self, user_id: str) -> list[dict]:
        scope = await accessible_project_ids(self.session, user_id)
        nodes = (await self.session.execute(select(PortfolioNode))).scalars().all()
        memberships = (await self.session.execute(select(PortfolioMembership))).scalars().all()

        node_rows = [
            {
                "id": str(n.id),
                "parent_id": str(n.parent_id) if n.parent_id else None,
                "node_type": n.node_type,
                "name": n.name,
                "code": n.code,
                "sort_order": n.sort_order,
            }
            for n in nodes
        ]
        membership_rows = [{"node_id": str(m.node_id), "project_id": str(m.project_id)} for m in memberships]
        accessible = None if scope is None else {str(p) for p in scope}
        return build_visible_tree(node_rows, membership_rows, accessible)

    # ── Node CRUD ────────────────────────────────────────────────────────────

    async def create_node(self, data: NodeCreate, user_id: str) -> PortfolioNode:
        if data.parent_id is not None:
            await self.get_node(data.parent_id)  # 404 if the parent is missing
        node = PortfolioNode(
            parent_id=data.parent_id,
            node_type=data.node_type,
            name=data.name,
            code=data.code,
            owner_id=uuid.UUID(str(user_id)),
            sort_order=data.sort_order,
            metadata_=data.metadata or {},
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def _require_manageable(self, node: PortfolioNode, user_id: str) -> None:
        if await self._is_admin(user_id):
            return
        if str(node.owner_id) != str(user_id):
            # Existence-oracle safe: a non-owner cannot tell the node exists.
            raise _not_found("Portfolio node not found")

    async def _assert_no_cycle(self, node_id: uuid.UUID, new_parent_id: uuid.UUID) -> None:
        if str(new_parent_id) == str(node_id):
            raise _unprocessable("A node cannot be its own parent")
        cur = await self.session.get(PortfolioNode, new_parent_id)
        seen: set[str] = set()
        while cur is not None:
            if str(cur.id) == str(node_id):
                raise _unprocessable("Reparenting would create a cycle")
            if str(cur.id) in seen:
                break
            seen.add(str(cur.id))
            cur = await self.session.get(PortfolioNode, cur.parent_id) if cur.parent_id else None

    async def patch_node(self, node_id: uuid.UUID, data: NodePatch, user_id: str) -> PortfolioNode:
        node = await self.get_node(node_id)
        await self._require_manageable(node, user_id)

        fields_set = data.model_fields_set
        if "parent_id" in fields_set:
            if data.parent_id is None:
                node.parent_id = None
            else:
                await self._assert_no_cycle(node_id, data.parent_id)
                await self.get_node(data.parent_id)  # 404 if the new parent is missing
                node.parent_id = data.parent_id
        if data.name is not None:
            node.name = data.name
        if data.node_type is not None:
            node.node_type = data.node_type
        if data.code is not None:
            node.code = data.code
        if data.sort_order is not None:
            node.sort_order = data.sort_order

        await self.session.flush()
        return node

    async def delete_node(self, node_id: uuid.UUID, user_id: str) -> None:
        node = await self.get_node(node_id)
        await self._require_manageable(node, user_id)
        await self.session.delete(node)  # memberships cascade; child nodes -> root
        await self.session.flush()

    # ── Membership ───────────────────────────────────────────────────────────

    async def attach_project(self, node_id: uuid.UUID, project_id: uuid.UUID, user_id: str) -> None:
        await self.get_node(node_id)
        # Cannot file a project the caller cannot reach (404 on deny).
        await verify_project_access(project_id, user_id, self.session)
        existing = (
            await self.session.execute(select(PortfolioMembership).where(PortfolioMembership.project_id == project_id))
        ).scalar_one_or_none()
        if existing is not None:
            existing.node_id = node_id  # a project sits in exactly one node -> move
        else:
            self.session.add(PortfolioMembership(node_id=node_id, project_id=project_id))
        await self.session.flush()

    async def detach_project(self, node_id: uuid.UUID, project_id: uuid.UUID, user_id: str) -> None:
        await self.get_node(node_id)
        await verify_project_access(project_id, user_id, self.session)
        await self.session.execute(
            sa_delete(PortfolioMembership).where(
                PortfolioMembership.node_id == node_id,
                PortfolioMembership.project_id == project_id,
            )
        )
        await self.session.flush()

    # ── Cross-schedule links ───────────────────────────────────────────────────

    async def _schedule_project_id(self, schedule_id: uuid.UUID) -> uuid.UUID:
        from app.modules.schedule.models import Schedule

        sched = await self.session.get(Schedule, schedule_id)
        if sched is None:
            raise _not_found("Schedule not found")
        return sched.project_id

    async def _assert_activity_in_schedule(
        self,
        activity_id: uuid.UUID,
        schedule_id: uuid.UUID,
        side: str,
    ) -> None:
        """Reject a well-formed link whose activity does not belong to its schedule.

        Called only after both projects are access-checked, so this is a pure
        consistency check for a caller who CAN reach both projects: a 422 (not a
        404), because there is no existence-oracle leak across a tenant boundary.
        ``schedule_id`` is already access-verified, and ``activity.schedule_id``
        pins the activity to that schedule, so matching the two is sufficient.
        """
        from app.modules.schedule.models import Activity

        activity = await self.session.get(Activity, activity_id)
        if activity is None or activity.schedule_id != schedule_id:
            raise _unprocessable(f"{side}_activity_id does not belong to {side}_schedule_id")

    async def create_cross_link(self, data: CrossLinkCreate, user_id: str) -> PortfolioCrossLink:
        # A cross-link needs access to BOTH projects, so it cannot be used to
        # bridge into a tenant the caller cannot reach (404 on deny).
        pred_project = await self._schedule_project_id(data.predecessor_schedule_id)
        succ_project = await self._schedule_project_id(data.successor_schedule_id)
        await verify_project_access(pred_project, user_id, self.session)
        await verify_project_access(succ_project, user_id, self.session)
        # Both projects are reachable; now reject an inconsistent (well-formed)
        # pairing where an activity does not live in the schedule it is filed
        # under, instead of silently dropping it at CPM compute time.
        await self._assert_activity_in_schedule(
            data.predecessor_activity_id, data.predecessor_schedule_id, "predecessor"
        )
        await self._assert_activity_in_schedule(data.successor_activity_id, data.successor_schedule_id, "successor")
        link = PortfolioCrossLink(
            predecessor_schedule_id=data.predecessor_schedule_id,
            predecessor_activity_id=data.predecessor_activity_id,
            successor_schedule_id=data.successor_schedule_id,
            successor_activity_id=data.successor_activity_id,
            dep_type=data.dep_type,
            lag_days=data.lag_days,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def list_cross_links(self, schedule_id: uuid.UUID, user_id: str) -> list[PortfolioCrossLink]:
        await verify_project_access(await self._schedule_project_id(schedule_id), user_id, self.session)
        rows = (
            (
                await self.session.execute(
                    select(PortfolioCrossLink).where(
                        or_(
                            PortfolioCrossLink.predecessor_schedule_id == schedule_id,
                            PortfolioCrossLink.successor_schedule_id == schedule_id,
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def name_cross_link_endpoints(
        self, links: Sequence[PortfolioCrossLink]
    ) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
        """Look up the schedule and activity names the endpoints of *links* point at.

        Two batched selects for the whole page, not four lookups per row: every
        link prints four names and a register of thirty links would otherwise
        cost a hundred and twenty round trips.

        Args:
            links: The cross-links whose endpoints need naming.

        Returns:
            A ``(schedules, activities)`` pair of id-to-name maps. An id whose
            row has been deleted is simply absent, so the caller renders the id
            rather than inventing a name for something that is gone.
        """
        from app.modules.schedule.models import Activity, Schedule

        if not links:
            return {}, {}
        schedule_ids = {sid for link in links for sid in (link.predecessor_schedule_id, link.successor_schedule_id)}
        activity_ids = {aid for link in links for aid in (link.predecessor_activity_id, link.successor_activity_id)}
        schedules = dict(
            (await self.session.execute(select(Schedule.id, Schedule.name).where(Schedule.id.in_(schedule_ids)))).all()
        )
        activities = dict(
            (await self.session.execute(select(Activity.id, Activity.name).where(Activity.id.in_(activity_ids)))).all()
        )
        return schedules, activities

    async def delete_cross_link(self, link_id: uuid.UUID, user_id: str) -> None:
        from app.modules.schedule.models import Schedule

        link = await self.session.get(PortfolioCrossLink, link_id)
        if link is None:
            raise _not_found("Cross-link not found")
        # Verify access against the first endpoint whose schedule still exists; an
        # orphaned link (both schedules deleted) is freely cleaned up.
        for sid in (link.predecessor_schedule_id, link.successor_schedule_id):
            sched = await self.session.get(Schedule, sid)
            if sched is not None:
                await verify_project_access(sched.project_id, user_id, self.session)
                break
        await self.session.delete(link)
        await self.session.flush()

    # ── Portfolio (schedule-of-schedules) CPM ──────────────────────────────────

    def _subtree_project_ids(
        self,
        node_id: uuid.UUID,
        nodes: list[PortfolioNode],
        memberships: list[PortfolioMembership],
    ) -> set[str]:
        """Project ids filed anywhere under ``node_id`` (the node + its subtree)."""
        children: dict[str | None, list[str]] = {}
        for n in nodes:
            parent = str(n.parent_id) if n.parent_id else None
            children.setdefault(parent, []).append(str(n.id))
        subtree: set[str] = set()
        stack = [str(node_id)]
        while stack:
            cur = stack.pop()
            if cur in subtree:
                continue
            subtree.add(cur)
            stack.extend(children.get(cur, []))
        return {str(m.project_id) for m in memberships if str(m.node_id) in subtree}

    async def compute_node_cpm(self, node_id: uuid.UUID, user_id: str) -> dict:
        """Run one CPM pass over every accessible schedule under ``node_id``.

        Gathers the node's subtree projects (intersected with the caller's
        accessible set), merges their schedules onto a shared timeline by start
        offset, applies in-scope cross-links as real edges, and returns the
        per-activity result plus the cross-portfolio critical path. Cross-links
        whose far side is out of scope are dropped and counted, never silently.
        """
        from datetime import date

        from app.modules.portfolio.cpm_logic import (
            ActivityInput,
            ScheduleInput,
            build_portfolio_inputs,
            split_nid,
        )
        from app.modules.schedule.models import Activity as SchedActivity
        from app.modules.schedule.models import Schedule, ScheduleRelationship
        from app.modules.schedule_advanced.portfolio_cpm import (
            CycleError,
            compute_portfolio_cpm,
            portfolio_critical_path,
        )

        await self.get_node(node_id)  # 404 if the node is gone

        def _empty() -> dict:
            return {
                "node_id": node_id,
                "schedule_count": 0,
                "activity_count": 0,
                "project_finish_workday": 0,
                "cross_links_applied": 0,
                "cross_links_omitted": 0,
                "critical_path": [],
                "activities": [],
            }

        nodes = (await self.session.execute(select(PortfolioNode))).scalars().all()
        memberships = (await self.session.execute(select(PortfolioMembership))).scalars().all()
        project_ids = self._subtree_project_ids(node_id, list(nodes), list(memberships))
        scope = await accessible_project_ids(self.session, user_id)
        if scope is not None:
            project_ids &= {str(p) for p in scope}
        if not project_ids:
            return _empty()

        proj_uuids = [uuid.UUID(p) for p in project_ids]
        schedules = (
            (await self.session.execute(select(Schedule).where(Schedule.project_id.in_(proj_uuids)))).scalars().all()
        )
        if not schedules:
            return _empty()
        in_scope_sched = {str(s.id) for s in schedules}
        sched_ids = [s.id for s in schedules]

        def _iso(value: object) -> date | None:
            if not value:
                return None
            try:
                return date.fromisoformat(str(value)[:10])
            except ValueError:
                return None

        starts = {str(s.id): _iso(s.start_date) for s in schedules}
        present = [d for d in starts.values() if d is not None]
        earliest = min(present) if present else None

        acts = (
            (await self.session.execute(select(SchedActivity).where(SchedActivity.schedule_id.in_(sched_ids))))
            .scalars()
            .all()
        )
        rels = (
            (
                await self.session.execute(
                    select(ScheduleRelationship).where(ScheduleRelationship.schedule_id.in_(sched_ids))
                )
            )
            .scalars()
            .all()
        )

        preds_by_act: dict[str, list[tuple[str, str, int]]] = {}
        for r in rels:
            preds_by_act.setdefault(str(r.successor_id), []).append(
                (str(r.predecessor_id), r.relationship_type or "FS", int(r.lag_days or 0))
            )
        acts_by_sched: dict[str, list] = {}
        for a in acts:
            acts_by_sched.setdefault(str(a.schedule_id), []).append(a)

        schedule_inputs = []
        for s in schedules:
            sid = str(s.id)
            d = starts.get(sid)
            offset = (d - earliest).days if (d is not None and earliest is not None) else 0
            offset = max(0, offset)
            activity_inputs = [
                ActivityInput(
                    activity_id=str(a.id),
                    duration=int(a.duration_days or 0),
                    predecessors=tuple(preds_by_act.get(str(a.id), [])),
                )
                for a in acts_by_sched.get(sid, [])
            ]
            schedule_inputs.append(ScheduleInput(schedule_id=sid, offset=offset, activities=tuple(activity_inputs)))

        links = (
            (
                await self.session.execute(
                    select(PortfolioCrossLink).where(
                        or_(
                            PortfolioCrossLink.predecessor_schedule_id.in_(sched_ids),
                            PortfolioCrossLink.successor_schedule_id.in_(sched_ids),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        link_tuples = []
        omitted = 0
        for link in links:
            both = (
                str(link.predecessor_schedule_id) in in_scope_sched
                and str(link.successor_schedule_id) in in_scope_sched
            )
            if both:
                link_tuples.append(
                    (
                        str(link.predecessor_schedule_id),
                        str(link.predecessor_activity_id),
                        str(link.successor_schedule_id),
                        str(link.successor_activity_id),
                        link.dep_type or "FS",
                        int(link.lag_days or 0),
                    )
                )
            else:
                omitted += 1

        activities_in, cross_edges, boundaries = build_portfolio_inputs(schedule_inputs, link_tuples)
        try:
            results = compute_portfolio_cpm(activities_in, cross_edges=cross_edges, boundaries=boundaries)
            cp = portfolio_critical_path(activities_in, cross_edges=cross_edges, boundaries=boundaries)
        except CycleError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cross-schedule cycle detected: {exc}",
            ) from exc

        sched_names = {str(s.id): s.name for s in schedules}
        act_names = {str(a.id): a.name for a in acts}

        def _row(namespaced: str) -> dict:
            sid, aid = split_nid(namespaced)
            res = results[namespaced]
            return {
                "schedule_id": uuid.UUID(sid),
                "activity_id": uuid.UUID(aid),
                "schedule_name": sched_names.get(sid, ""),
                "activity_name": act_names.get(aid, ""),
                "es": res.es,
                "ef": res.ef,
                "ls": res.ls,
                "lf": res.lf,
                "total_float": res.total_float,
                "is_critical": res.is_critical,
            }

        activities_out = [_row(k) for k in results]
        finish = max((v.ef for v in results.values()), default=0)
        cp_rows = [_row(k) for k in cp if k in results]
        return {
            "node_id": node_id,
            "schedule_count": len(schedules),
            "activity_count": len(activities_out),
            "project_finish_workday": finish,
            "cross_links_applied": len(cross_edges),
            "cross_links_omitted": omitted,
            "critical_path": cp_rows,
            "activities": activities_out,
        }
