# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The saved-views orchestrator.

``SavedViewService`` is the only place that wires the three safety primitives
together for every entry point. ``_scoped_base`` is the single producer of a base
statement: it builds ``select(entity.model)`` and hands it to the entity scoper,
so there is no way to reach the query builder without first applying the scope.
Every public read path - ``run_view``, ``run_adhoc``, ``count_for_reminder``,
``to_export`` - flows through scope, then whitelist, then budget. There is no
sixth path.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_merge import merge_metadata
from app.modules.saved_views.errors import (
    BudgetError,
    DuplicateViewName,
    ScopeDenied,
    WhitelistError,
)
from app.modules.saved_views.events import (
    EVENT_SAVED_VIEW_CREATED,
    EVENT_SAVED_VIEW_RUN,
)
from app.modules.saved_views.models import SavedView, SavedViewRun
from app.modules.saved_views.query_builder import (
    MAX_COMPLEXITY,
    SafeQueryBuilder,
    assert_within_budget,
)
from app.modules.saved_views.registry import entity_registry
from app.modules.saved_views.repository import SavedViewRepository
from app.modules.saved_views.schemas import (
    CountResponse,
    FilterSpec,
    RunResponse,
    RunStatsResponse,
    SavedViewCreate,
    SavedViewUpdate,
    SavedViewValidationReport,
)
from app.modules.saved_views.scoper import ScopeContext
from app.modules.saved_views.validators import (
    describe_staleness,
    evaluate_view,
    spec_problems,
)

if TYPE_CHECKING:
    from app.modules.saved_views.registry import QueryableEntity

import logging
import os

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


STATEMENT_TIMEOUT_MS: int = _env_int("SAVED_VIEWS_TIMEOUT_MS", 4000)


class SavedViewService:
    """Save, run, count, and export saved views under the three gates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SavedViewRepository(session)

    # ── The scope choke point (primitive 1) ─────────────────────────────

    async def _scoped_base(
        self,
        entity: QueryableEntity,
        ctx: ScopeContext,
    ) -> Select:
        """Build ``select(entity.model)`` and hand it to the entity scoper.

        The ONLY producer of a base statement. Private, but it is the choke point
        the whole safety story rests on: the builder requires a base statement
        and only this method makes one.
        """
        base = select(entity.model)
        return await entity.scoper.scope(base, entity.model, ctx, self.session)

    # ── Run a stored view (all three gates) ─────────────────────────────

    async def run_view(
        self,
        view_id: uuid.UUID,
        ctx: ScopeContext,
        *,
        page: int | None = None,
        page_size: int | None = None,
    ) -> RunResponse:
        """Run a stored saved view through scope, whitelist, and budget."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        await self._assert_view_visible(view, ctx)

        entity = self._require_entity(view.entity_type)
        spec = self._load_spec(view.spec)
        if page is not None:
            spec = spec.model_copy(update={"page": page})
        if page_size is not None:
            spec = spec.model_copy(update={"page_size": page_size})
        return await self._execute(entity, spec, ctx, saved_view_id=view.id)

    async def run_adhoc(
        self,
        entity_type: str,
        spec: FilterSpec,
        ctx: ScopeContext,
    ) -> RunResponse:
        """Run an inline spec without a stored row (the preview-before-save UX)."""
        entity = self._require_entity(entity_type)
        return await self._execute(entity, spec, ctx, saved_view_id=None)

    async def _execute(
        self,
        entity: QueryableEntity,
        spec: FilterSpec,
        ctx: ScopeContext,
        *,
        saved_view_id: uuid.UUID | None,
    ) -> RunResponse:
        """Compile + run a spec under all three gates, recording the run."""
        builder = SafeQueryBuilder(entity)
        start = time.perf_counter()
        try:
            # 2. WHITELIST - reject non-whitelisted fields / operators / values.
            spec.bind(entity)
            # 3. BUDGET (static) - refuse pathological specs before any DB hit.
            assert_within_budget(builder, spec)
            # 1. SCOPE - the base statement is scoped here, nowhere else.
            base = await self._scoped_base(entity, ctx)
            stmt = builder.build(base, spec)

            rows, truncated = await self._run_capped(stmt, builder.row_cap(spec.page_size))
        except WhitelistError:
            await self._record(saved_view_id, entity, ctx, 0, False, start, "whitelist")
            raise
        except BudgetError:
            await self._record(saved_view_id, entity, ctx, 0, False, start, "budget")
            raise
        except ScopeDenied:
            await self._record(saved_view_id, entity, ctx, 0, False, start, "scope")
            raise

        columns = self._result_columns(entity, spec)
        serialized = [self._serialize_row(entity, spec, r, columns) for r in rows]
        await self._record(saved_view_id, entity, ctx, len(serialized), truncated, start, "ok")
        return RunResponse(
            rows=serialized,
            columns=columns,
            total_estimate=None,
            truncated=truncated,
            page=spec.page,
            page_size=builder.row_cap(spec.page_size),
        )

    async def _run_capped(self, stmt: Select, cap: int) -> tuple[list[Any], bool]:
        """Execute under a statement timeout, trim the +1 sentinel."""
        try:
            await self._apply_statement_timeout()
            result = await self.session.execute(stmt)
            fetched = list(result.all())
        except Exception as exc:  # noqa: BLE001 - DB timeout / planner refusal
            if self._is_timeout(exc):
                raise BudgetError("The query took too long and was stopped; narrow your filter") from exc
            raise
        truncated = len(fetched) > cap
        return (fetched[:cap], truncated)

    async def _apply_statement_timeout(self) -> None:
        """Set a per-transaction ``statement_timeout`` on PostgreSQL.

        Bounds any query that somehow slips the static guards. No-op on a backend
        that does not support it. Never raises.
        """
        try:
            dialect = self.session.bind.dialect.name if self.session.bind else ""
            if dialect == "postgresql":
                await self.session.execute(text(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}"))
        except Exception:  # noqa: BLE001 - timeout is best-effort, never fatal
            return

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        """Heuristically detect a statement-timeout / cancel error."""
        text_blob = f"{type(exc).__name__}:{exc}".lower()
        return any(
            token in text_blob for token in ("statement_timeout", "canceling statement", "querycanceled", "timeout")
        )

    # ── Count for a reminder badge (capped) ─────────────────────────────

    async def count_for_reminder(
        self,
        view_id: uuid.UUID,
        ctx: ScopeContext,
    ) -> CountResponse:
        """Capped count for a reminder badge or dashboard tile."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        await self._assert_view_visible(view, ctx)
        entity = self._require_entity(view.entity_type)
        spec = self._load_spec(view.spec)
        builder = SafeQueryBuilder(entity)
        spec.bind(entity)
        assert_within_budget(builder, spec)
        base = await self._scoped_base(entity, ctx)
        count_stmt = builder.build_count(base, spec)
        await self._apply_statement_timeout()
        try:
            result = await self.session.execute(count_stmt)
            count = int(result.scalar_one())
        except Exception as exc:  # noqa: BLE001
            if self._is_timeout(exc):
                raise BudgetError("The count took too long and was stopped") from exc
            raise
        cap = builder.row_cap(spec.page_size)
        truncated = count > cap
        return CountResponse(count=min(count, cap), truncated=truncated)

    # ── Export (chunked, capped) ────────────────────────────────────────

    async def to_export(
        self,
        view_id: uuid.UUID,
        ctx: ScopeContext,
        fmt: str = "csv",
    ) -> AsyncIterator[bytes]:
        """Stream a capped export (CSV) in chunks; never one unbounded fetch.

        Each page re-applies the row cap, honouring the 3GB-core rule. ``parquet``
        falls back to CSV bytes when pandas is unavailable; the CSV path is pure
        stdlib so it always works.
        """
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        await self._assert_view_visible(view, ctx)
        entity = self._require_entity(view.entity_type)
        spec = self._load_spec(view.spec)
        spec.bind(entity)
        builder = SafeQueryBuilder(entity)
        assert_within_budget(builder, spec)
        columns = self._result_columns(entity, spec)

        import csv
        import io

        header = io.StringIO()
        csv.writer(header).writerow(columns)
        yield header.getvalue().encode("utf-8")

        page = 1
        cap = builder.row_cap(spec.page_size)
        while True:
            page_spec = spec.model_copy(update={"page": page})
            base = await self._scoped_base(entity, ctx)
            stmt = builder.build(base, page_spec)
            rows, truncated = await self._run_capped(stmt, cap)
            if not rows:
                break
            buf = io.StringIO()
            writer = csv.writer(buf)
            for r in rows:
                serialized = self._serialize_row(entity, page_spec, r, columns)
                writer.writerow([serialized.get(c, "") for c in columns])
            yield buf.getvalue().encode("utf-8")
            if not truncated:
                break
            page += 1

    # ── CRUD ────────────────────────────────────────────────────────────

    async def save_view(self, ctx: ScopeContext, payload: SavedViewCreate) -> SavedView:
        """Create a saved view after validating entity, spec, name and share grant.

        Args:
            ctx: The caller, who becomes the owner.
            payload: The validated create request.

        Returns:
            The persisted row (the caller commits).

        Raises:
            WhitelistError: The spec does not bind, or the share is not the
                caller's to grant.
            DuplicateViewName: The owner already has a view of that name here.
        """
        entity = self._require_entity(payload.entity_type)
        # Re-validate the spec binds cleanly before persisting.
        payload.spec.bind(entity)
        await self._assert_can_grant_share(
            payload.share_scope,
            ctx,
            project_id=payload.project_id,
            shared_team_id=payload.shared_team_id,
        )
        await self._assert_name_free(
            owner_id=ctx.user_id,
            project_id=payload.project_id,
            entity_type=payload.entity_type,
            name=payload.name,
        )
        view = SavedView(
            owner_id=ctx.user_id,
            project_id=payload.project_id,
            entity_type=payload.entity_type,
            name=payload.name,
            description=payload.description,
            spec=payload.spec.model_dump(mode="json"),
            share_scope=payload.share_scope,
            shared_team_id=payload.shared_team_id,
            is_pinned=payload.is_pinned,
            metadata_=payload.metadata_,
        )
        created = await self.repo.create(view)
        await self._publish(
            EVENT_SAVED_VIEW_CREATED,
            {
                "view_id": str(created.id),
                "owner_id": str(created.owner_id),
                "project_id": str(created.project_id) if created.project_id else None,
                "entity_type": created.entity_type,
                "share_scope": created.share_scope,
            },
        )
        return created

    async def update_view(
        self,
        view_id: uuid.UUID,
        ctx: ScopeContext,
        payload: SavedViewUpdate,
    ) -> SavedView:
        """Update a view (owner or admin only)."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        self._assert_can_mutate(view, ctx)
        entity = self._require_entity(view.entity_type)
        fields: dict[str, Any] = {}
        if payload.name is not None:
            await self._assert_name_free(
                owner_id=view.owner_id,
                project_id=view.project_id,
                entity_type=view.entity_type,
                name=payload.name,
                exclude_id=view.id,
            )
            fields["name"] = payload.name
        if payload.description is not None:
            fields["description"] = payload.description
        if payload.spec is not None:
            payload.spec.bind(entity)
            fields["spec"] = payload.spec.model_dump(mode="json")
        if payload.share_scope is not None or payload.shared_team_id is not None:
            # Scope and team pin are decided together against the row as it
            # will be, not as it was: patching one without the other must not
            # be able to leave a team share with no team or a team pin on a
            # project-wide share.
            share_scope = payload.share_scope or view.share_scope
            shared_team_id = payload.shared_team_id if payload.shared_team_id is not None else view.shared_team_id
            if share_scope != "team":
                shared_team_id = None
            await self._assert_can_grant_share(
                share_scope,
                ctx,
                project_id=view.project_id,
                shared_team_id=shared_team_id,
            )
            fields["share_scope"] = share_scope
            fields["shared_team_id"] = shared_team_id
        if payload.is_pinned is not None:
            fields["is_pinned"] = payload.is_pinned
        if payload.metadata_ is not None:
            fields["metadata_"] = (
                merge_metadata(getattr(view, "metadata_", None), payload.metadata_)
                if isinstance(payload.metadata_, dict)
                else payload.metadata_
            )
        return await self.repo.update_fields(view, fields)

    async def delete_view(self, view_id: uuid.UUID, ctx: ScopeContext) -> None:
        """Delete a view (owner or admin only)."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        self._assert_can_mutate(view, ctx)
        await self.repo.delete(view)

    async def list_views(
        self,
        ctx: ScopeContext,
        *,
        entity_type: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> list[SavedView]:
        """List the caller's own views plus shared views in the project.

        Team-shared views are included only for the teams the caller actually
        belongs to, resolved through the teams module. The shared half is
        skipped entirely unless the caller can reach the project, so a listing
        can never be used to enumerate another project's saved views.
        """
        own = await self.repo.list_for_owner(ctx.user_id, entity_type=entity_type, project_id=project_id)
        shared: list[SavedView] = []
        if project_id is not None:
            reachable = ctx.is_admin
            if not reachable:
                try:
                    await self._assert_project_access(project_id, ctx)
                    reachable = True
                except ScopeDenied:
                    reachable = False
            if reachable:
                team_ids = () if ctx.is_admin else await self._member_team_ids(ctx.user_id, project_id)
                shared = await self.repo.list_shared_in_project(
                    project_id,
                    entity_type=entity_type,
                    member_team_ids=team_ids,
                    include_all_teams=ctx.is_admin,
                )
        merged: dict[uuid.UUID, SavedView] = {v.id: v for v in own}
        for v in shared:
            merged.setdefault(v.id, v)
        return list(merged.values())

    async def get_view(self, view_id: uuid.UUID, ctx: ScopeContext) -> SavedView:
        """Fetch one definition the caller may see.

        Unlike run / count / export, this path never flows through the scoper
        (it returns the stored definition, it does not run the stored spec), so
        the project-access check the scoper performs for those paths has to be
        applied here explicitly. :meth:`_assert_view_visible` does exactly that
        for every path, resolving membership against the view's OWN project.
        """
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        await self._assert_view_visible(view, ctx)
        return view

    # ── Health and telemetry ────────────────────────────────────────────

    def staleness(self, view: SavedView) -> tuple[bool, list[str]]:
        """Whether a stored view still binds against its entity, and why not.

        A pure registry comparison with no database access, so a list response
        can annotate every row it returns. The heavier
        :meth:`validate_view` runs the full rule set over one view.

        Args:
            view: The stored row.

        Returns:
            ``(is_stale, reasons)``.
        """
        return describe_staleness(
            view.entity_type,
            view.spec,
            entity_registry.get(view.entity_type),
        )

    async def validate_view(
        self,
        view_id: uuid.UUID,
        ctx: ScopeContext,
        *,
        locale: str = "",
    ) -> SavedViewValidationReport:
        """Run the saved-views rule set over one stored definition.

        Args:
            view_id: The view to check.
            ctx: The caller, checked for visibility exactly as a read is.
            locale: The caller's locale, carried into the report metadata.

        Returns:
            The findings, worst severity first in the counts.

        Raises:
            ScopeDenied: The caller may not see this view.
        """
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        await self._assert_view_visible(view, ctx)
        entity = entity_registry.get(view.entity_type)
        payload = {
            "view": {
                "id": str(view.id),
                "name": view.name,
                "description": view.description,
                "entity_type": view.entity_type,
                "share_scope": view.share_scope,
                "shared_team_id": str(view.shared_team_id) if view.shared_team_id else None,
                "project_id": str(view.project_id) if view.project_id else None,
                "owner_id": str(view.owner_id),
            },
            "problems": spec_problems(view.entity_type, view.spec, entity),
            "entity_facts": self._entity_facts(view, entity),
        }
        return await evaluate_view(
            payload,
            project_id=str(view.project_id) if view.project_id else None,
            locale=locale,
        )

    @staticmethod
    def _entity_facts(view: SavedView, entity: QueryableEntity | None) -> dict[str, Any]:
        """Registry caps plus the stored spec's static complexity.

        Returns an empty-ish dict when the spec cannot be parsed or the entity
        is gone: the rules that read these facts then skip rather than report
        on numbers they could not compute.
        """
        facts: dict[str, Any] = {
            "spec_parsed": False,
            "complexity_ceiling": MAX_COMPLEXITY,
        }
        if entity is None:
            return facts
        try:
            spec = FilterSpec.model_validate(view.spec or {})
        except Exception:  # noqa: BLE001 - the spec_parses rule reports this
            return facts
        builder = SafeQueryBuilder(entity)
        facts.update(
            {
                "spec_parsed": True,
                "complexity": builder.estimate_cost(spec),
                "page_size": spec.page_size,
                "row_cap": builder.row_cap(spec.page_size),
                "spec_is_empty": (
                    not spec.where.conditions
                    and not spec.where.groups
                    and not spec.sort
                    and not spec.columns
                    and not spec.group_by
                ),
            }
        )
        return facts

    async def run_stats(self, view_id: uuid.UUID, ctx: ScopeContext) -> RunStatsResponse:
        """Aggregated run telemetry for one view.

        The ``oe_saved_views_run`` rows are written on every run and, until
        this method, were never read back. They answer whether a view is used,
        whether it is slow, and whether it keeps hitting the row cap.

        Args:
            view_id: The view to report on.
            ctx: The caller, checked for visibility exactly as a read is.

        Returns:
            Counts, timings and the last outcome.

        Raises:
            ScopeDenied: The caller may not see this view.
        """
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise ScopeDenied("Saved view not found")
        await self._assert_view_visible(view, ctx)
        outcomes = await self.repo.run_outcome_counts(view.id)
        avg_ms, max_ms, truncated = await self.repo.run_timings(view.id)
        last = await self.repo.last_run(view.id)
        return RunStatsResponse(
            view_id=view.id,
            total_runs=sum(outcomes.values()),
            outcomes=outcomes,
            last_run_at=last.created_at if last else None,
            last_outcome=last.outcome if last else None,
            last_row_count=last.row_count if last else None,
            avg_elapsed_ms=avg_ms,
            max_elapsed_ms=max_ms,
            truncated_runs=truncated,
        )

    # ── Helpers ─────────────────────────────────────────────────────────

    async def _assert_name_free(
        self,
        *,
        owner_id: uuid.UUID,
        project_id: uuid.UUID | None,
        entity_type: str,
        name: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Refuse a name ``uq_saved_views_owner_scope_name`` would reject.

        Without this the insert raises ``IntegrityError``, which reaches the
        client as a 500 and, worse, has already aborted the request's
        transaction. The unique index is still the authority under a race; this
        only turns the common case into a 409 that names the collision.

        Raises:
            DuplicateViewName: The owner already has a view of that name here.
        """
        taken = await self.repo.name_taken(
            owner_id=owner_id,
            project_id=project_id,
            entity_type=entity_type,
            name=name,
            exclude_id=exclude_id,
        )
        if taken:
            raise DuplicateViewName(name)

    async def _publish(self, event_name: str, data: dict[str, Any]) -> None:
        """Publish a module event without letting a subscriber break the request.

        The two event names have been declared since the module shipped and
        nothing ever emitted them, so no subscriber can have come to depend on
        the old silence.
        """
        try:
            from app.core.events import event_bus

            await event_bus.publish(event_name, data, source_module="oe_saved_views")
        except Exception:  # noqa: BLE001 - an event is telemetry, never a gate
            logger.warning("saved-views event %s could not be published", event_name, exc_info=True)

    @staticmethod
    def _require_entity(entity_type: str) -> QueryableEntity:
        entity = entity_registry.get(entity_type)
        if entity is None:
            raise WhitelistError(f"Unknown entity type {entity_type!r}", field="entity_type")
        return entity

    @staticmethod
    def _load_spec(raw: dict | None) -> FilterSpec:
        """Re-validate the stored spec JSON through Pydantic, never trust as-is."""
        return FilterSpec.model_validate(raw or {})

    async def _assert_view_visible(self, view: SavedView, ctx: ScopeContext) -> None:
        """Refuse to read a definition the caller may not see.

        Owner and admin always. Every other reader is admitted against the
        view's OWN project, never against ``ctx.project_id``: that is a
        caller-supplied query parameter, and deriving visibility from it would
        let any holder of ``saved_views.read`` reach a shared definition simply
        by echoing the right project id back. This mirrors :meth:`get_view`,
        which has always resolved membership the strict way.

        Sharing decides who can see the DEFINITION. It never widens the rows:
        the run path scopes every query under the reader's own identity, so a
        colleague running a shared view gets their own records. A ``team`` share
        is therefore an intersection - team membership AND project access - not
        an alternative route in.
        """
        if ctx.is_admin or view.owner_id == ctx.user_id:
            return
        if view.share_scope == "private" or view.project_id is None:
            raise ScopeDenied("Saved view not found")
        if view.share_scope == "team":
            # A team share whose team was deleted (ON DELETE SET NULL) reaches
            # nobody but its owner. Fail closed rather than fall through to the
            # project-wide branch, which would widen the share on team deletion.
            if view.shared_team_id is None or not await self._is_team_member(view.shared_team_id, ctx.user_id):
                raise ScopeDenied("Saved view not found")
        elif view.share_scope not in ("project", "workspace"):
            raise ScopeDenied("Saved view not found")
        await self._assert_project_access(view.project_id, ctx)

    async def _assert_project_access(self, project_id: uuid.UUID, ctx: ScopeContext) -> None:
        """Admit the caller to ``project_id`` or raise :class:`ScopeDenied`.

        Normalises the 404 that :func:`app.dependencies.verify_project_access`
        raises into the module's own refusal, so the router keeps producing a
        404 with no existence oracle.
        """
        from app.dependencies import verify_project_access

        try:
            await verify_project_access(project_id, str(ctx.user_id), self.session)
        except Exception as exc:  # noqa: BLE001 - normalise to a scope refusal
            from fastapi import HTTPException

            if isinstance(exc, HTTPException) and exc.status_code == 404:
                raise ScopeDenied("Saved view not found") from exc
            raise

    async def _is_team_member(self, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Whether ``user_id`` belongs to ``team_id``, per the teams module.

        Imported late and on purpose. ``teams`` owns team membership and this
        module must not become a second answer to that question; a late import
        also means saved views still load, fail closed, in a deployment where
        the teams module is absent.

        Args:
            team_id: The team a view is shared with.
            user_id: The caller.

        Returns:
            ``True`` only on a positive answer from the teams module. Any
            failure to resolve membership counts as "not a member".
        """
        try:
            from sqlalchemy import select as sa_select

            from app.modules.teams.models import TeamMembership
        except ImportError:  # pragma: no cover - teams is auto_install
            logger.warning("teams module unavailable; treating the team share as owner-only")
            return False
        stmt = sa_select(TeamMembership.id).where(
            TeamMembership.team_id == team_id,
            TeamMembership.user_id == user_id,
        )
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def _member_team_ids(self, user_id: uuid.UUID, project_id: uuid.UUID) -> list[uuid.UUID]:
        """Every team on ``project_id`` that ``user_id`` belongs to.

        Used to widen a list response to team-shared views. An empty list is the
        correct fail-closed answer: the caller then sees project and workspace
        shares only.
        """
        try:
            from sqlalchemy import select as sa_select

            from app.modules.teams.models import Team, TeamMembership
        except ImportError:  # pragma: no cover - teams is auto_install
            return []
        stmt = (
            sa_select(TeamMembership.team_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(TeamMembership.user_id == user_id, Team.project_id == project_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    def _assert_can_mutate(self, view: SavedView, ctx: ScopeContext) -> None:
        """Only the owner or an admin may update / delete a definition."""
        if ctx.is_admin or view.owner_id == ctx.user_id:
            return
        raise ScopeDenied("Saved view not found")

    async def _assert_can_grant_share(
        self,
        share_scope: str,
        ctx: ScopeContext,
        *,
        project_id: uuid.UUID | None,
        shared_team_id: uuid.UUID | None,
    ) -> None:
        """Refuse a share the caller is not entitled to grant.

        Two separate rules:

        * ``workspace`` needs a project owner / manager / admin. A plain editor
          or viewer cannot publish a view that wide.
        * ``team`` needs the granter to be in that team AND the team to belong
          to the view's own project. Without the second half, a member of team A
          on project X could pin a view on project Y to team A and hand its
          definition to people who have nothing to do with project Y.

        Args:
            share_scope: The scope being granted.
            ctx: The caller.
            project_id: The project the view is pinned to.
            shared_team_id: The team named on a ``team`` share.

        Raises:
            WhitelistError: The caller may not grant this share.
        """
        if share_scope == "workspace":
            # role is the canonical, DB-rehydrated role; manager+ or admin may
            # grant a workspace share. A plain editor / viewer cannot.
            if ctx.is_admin or ctx.role in ("manager", "owner"):
                return
            raise WhitelistError(
                "Only a project owner or admin may create a workspace-shared view",
                field="share_scope",
            )
        if share_scope != "team":
            return
        if shared_team_id is None:
            raise WhitelistError(
                "A team-shared view must name the team it is shared with",
                field="shared_team_id",
            )
        if project_id is None:
            raise WhitelistError(
                "A team-shared view must be pinned to the project the team belongs to",
                field="project_id",
            )
        if not await self._team_is_on_project(shared_team_id, project_id):
            raise WhitelistError(
                "That team does not belong to this project",
                field="shared_team_id",
            )
        if ctx.is_admin:
            return
        if not await self._is_team_member(shared_team_id, ctx.user_id):
            raise WhitelistError(
                "You can only share a view with a team you belong to",
                field="shared_team_id",
            )

    async def _team_is_on_project(self, team_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Whether ``team_id`` belongs to ``project_id``, per the teams module."""
        try:
            from sqlalchemy import select as sa_select

            from app.modules.teams.models import Team
        except ImportError:  # pragma: no cover - teams is auto_install
            return False
        stmt = sa_select(Team.id).where(Team.id == team_id, Team.project_id == project_id)
        return (await self.session.execute(stmt.limit(1))).first() is not None

    @staticmethod
    def _result_columns(entity: QueryableEntity, spec: FilterSpec) -> list[str]:
        """Resolve the output column names for a spec."""
        if spec.group_by:
            return [*spec.group_by, "count"]
        if spec.columns:
            return list(spec.columns)
        if entity.default_columns:
            return list(entity.default_columns)
        return [name for name, fs in entity.fields.items() if fs.selectable]

    @staticmethod
    def _serialize_row(
        entity: QueryableEntity,
        spec: FilterSpec,
        row: Any,
        columns: Iterable[str],
    ) -> dict[str, Any]:
        """Project a result row to a JSON-friendly dict of whitelisted columns."""
        out: dict[str, Any] = {}
        if spec.group_by:
            # Grouped rows are SQLAlchemy Row objects: group cols + count.
            mapping = row._mapping if hasattr(row, "_mapping") else {}
            for name in spec.group_by:
                column = entity.fields[name].column
                out[name] = _jsonable(mapping.get(column))
            out["count"] = int(mapping.get("count", 0) or 0)
            return out
        # Non-grouped rows: a ``select(model)`` yields a Row whose first element
        # is the ORM instance. Unwrap it whether the driver hands back a Row, a
        # tuple, or (defensively) the bare instance.
        if isinstance(row, entity.model):
            obj = row
        elif hasattr(row, "_mapping") or isinstance(row, (tuple, list)):
            obj = row[0]
        else:
            obj = row
        for name in columns:
            fs = entity.fields.get(name)
            if fs is None:
                continue
            out[name] = _jsonable(getattr(obj, fs.column, None))
        return out

    async def _record(
        self,
        saved_view_id: uuid.UUID | None,
        entity: QueryableEntity,
        ctx: ScopeContext,
        row_count: int,
        truncated: bool,
        start: float,
        outcome: str,
    ) -> None:
        """Append a ``SavedViewRun`` audit row. Never raises into the caller."""
        elapsed = int((time.perf_counter() - start) * 1000)
        try:
            run = SavedViewRun(
                saved_view_id=saved_view_id,
                owner_id=ctx.user_id,
                entity_type=entity.entity_type,
                row_count=row_count,
                truncated=truncated,
                elapsed_ms=elapsed,
                outcome=outcome,
            )
            await self.repo.record_run(run)
        except Exception:  # noqa: BLE001 - telemetry must never break a request
            return
        await self._publish(
            EVENT_SAVED_VIEW_RUN,
            {
                "view_id": str(saved_view_id) if saved_view_id else None,
                "owner_id": str(ctx.user_id),
                "entity_type": entity.entity_type,
                "outcome": outcome,
                "row_count": row_count,
                "truncated": truncated,
                "elapsed_ms": elapsed,
            },
        )


def _jsonable(value: Any) -> Any:
    """Coerce a column value to a JSON-friendly scalar."""
    import datetime as _dt
    from decimal import Decimal

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return str(value)
