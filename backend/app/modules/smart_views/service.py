# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Smart Views business logic.

The service layer is the single source of truth for the **scoping
rules** — RBAC at the router decides *whether* a caller may touch the
feature at all; the service decides *which rows* they may touch. The
counter-intuitive split (instead of just a per-row owner check) buys
the user-/project-/federation- scoped sharing model BIMcollab Zoom
made famous.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from fastapi import HTTPException, status
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.bim_hub.models import BIMFederation, BIMModel
from app.modules.projects.models import Project
from app.modules.smart_views.evaluator import evaluate_smart_view
from app.modules.smart_views.models import SmartView
from app.modules.smart_views.presets import BUILTIN_PRESETS, get_preset
from app.modules.smart_views.repository import SmartViewRepository
from app.modules.smart_views.schemas import (
    SmartViewCreate,
    SmartViewEvaluateResponse,
    SmartViewPresetSummary,
    SmartViewResponse,
    SmartViewRule,
    SmartViewShareInfo,
    SmartViewUpdate,
)

# Salt is namespaced so a leaked JWT secret cannot be replayed against
# another itsdangerous surface (or vice-versa). The value is constant
# across the install — the JWT secret IS the actual entropy source.
_SHARE_SIGNER_SALT = "oe.smart_views.share.v1"

logger = logging.getLogger(__name__)


class SmartViewService:
    """‌⁠‍Smart Views CRUD + evaluator orchestrator."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SmartViewRepository(session)

    # ── Share-token signer (lazy + memoised on the instance) ───────────

    def _signer(self) -> URLSafeSerializer:
        """Return a URLSafeSerializer keyed by the platform JWT secret.

        The serializer is itsdangerous's stateless variant: the token
        body carries the view UUID + a random nonce, signed with the
        JWT secret. We choose ``URLSafeSerializer`` over the *Timed*
        variant because share links are explicitly revocable (the
        column is nulled on revoke) and an expiring token would make
        UX worse without adding security — a stolen token is mitigated
        by revoke, not by a TTL.
        """
        cached = getattr(self, "_share_signer_cache", None)
        if cached is None:
            settings = get_settings()
            cached = URLSafeSerializer(settings.jwt_secret, salt=_SHARE_SIGNER_SALT)
            self._share_signer_cache = cached  # type: ignore[attr-defined]
        return cached

    def _make_share_token(self, view_id: uuid.UUID) -> str:
        """Generate a signed token whose payload is the view id + nonce.

        The nonce ensures that revoke→re-share produces a *different*
        token even if the JWT secret is unchanged — otherwise an old
        copy of a revoked link would silently start working again on
        the next share. ``secrets.token_urlsafe(16)`` gives 128 bits.
        """
        nonce = secrets.token_urlsafe(16)
        return self._signer().dumps({"v": str(view_id), "n": nonce})

    def _decode_share_token(self, token: str) -> uuid.UUID | None:
        """Verify signature + return the embedded view id, or ``None``."""
        try:
            payload = self._signer().loads(token)
        except BadSignature:
            return None
        if not isinstance(payload, dict):
            return None
        raw_id = payload.get("v")
        if not isinstance(raw_id, str):
            return None
        try:
            return uuid.UUID(raw_id)
        except (ValueError, TypeError):
            return None

    # ── Response shaping ──────────────────────────────────────────────

    @staticmethod
    def _response_for(view: SmartView, *, viewer_id: uuid.UUID | None) -> SmartViewResponse:
        """Build the response payload, redacting share_token for non-authors.

        The DB-level uniqueness on ``share_token`` already prevents an
        accidental leak via the list endpoint — but a project-scoped
        view's token still must not surface to collaborators who don't
        own the row. We blanket-redact unless ``viewer_id`` equals the
        ``created_by`` user.
        """
        resp = SmartViewResponse.model_validate(view)
        if viewer_id is None or view.created_by != viewer_id:
            resp.share_token = None
        return resp

    # ── Helpers ────────────────────────────────────────────────────────

    async def _accessible_project_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Project IDs the user may read (owner-or-admin scope).

        We deliberately reuse the simple ownership model used across
        ``clash`` / ``bcf`` / ``bim_hub``: a viewer sees their own
        projects. Admins are short-circuited at the router level via
        the live JWT ``role`` claim, so we do not need to special-case
        admin here — they get the full list because the router skips
        the scoping check entirely.
        """
        stmt = select(Project.id).where(Project.owner_id == user_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _verify_scope(
        self,
        *,
        scope_type: str,
        scope_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Reject a create/update whose scope target does not exist or is unauthorised.

        Mapping:

        * ``user``       — ``scope_id`` must equal the caller's user id.
                           A user cannot create a "private" view on
                           someone else's behalf.
        * ``project``    — the project must exist and the caller must
                           own it (admin bypass happens at the router).
        * ``federation`` — the federation must exist and its project
                           must be owned by the caller.
        """
        if scope_type == "user":
            if scope_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot create a user-scoped SmartView for another user",
                )
            return

        if scope_type == "project":
            project = await self.session.get(Project, scope_id)
            if project is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=translate("errors.project_not_found", locale=get_locale()),
                )
            if str(getattr(project, "owner_id", "")) != str(user_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot create a SmartView on a project you do not own",
                )
            return

        if scope_type == "federation":
            federation = await self.session.get(BIMFederation, scope_id)
            if federation is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Federation not found",
                )
            project = await self.session.get(Project, federation.project_id)
            if project is None or str(getattr(project, "owner_id", "")) != str(user_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot create a SmartView on a federation you do not own",
                )
            return

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown scope_type: {scope_type!r}",
        )

    def _can_read(
        self,
        view: SmartView,
        *,
        user_id: uuid.UUID,
        accessible_project_ids: set[uuid.UUID],
    ) -> bool:
        """Visibility predicate — see :class:`SmartViewRepository`."""
        if view.scope_type == "user":
            return view.scope_id == user_id
        if view.scope_type == "project":
            return view.scope_id in accessible_project_ids
        # Federation views are read-gated through the federation's
        # parent project. The earlier "permit by readability" stub was
        # a cross-project leak (#103): any authenticated caller with
        # ``smart_views.read`` could pull a federation-scoped view from
        # another tenant by guessing the federation UUID. Use the async
        # variant ``_can_read_async`` for federation views; this sync
        # predicate defaults to False so callers that forget to check
        # fail closed, not open.
        return False

    async def _can_read_async(
        self,
        view: SmartView,
        *,
        user_id: uuid.UUID,
        accessible_project_ids: set[uuid.UUID],
    ) -> bool:
        """Visibility predicate that handles federation→project lookup.

        For ``user`` / ``project`` scopes this is equivalent to
        :meth:`_can_read` — no extra DB hit. For ``federation`` scope
        we resolve the federation's ``project_id`` and check it is in
        the caller's accessible project set. The N+1 cost is one extra
        ``session.get`` per federation-scoped row touched (capped to
        the small list of views a single request handles).
        """
        if view.scope_type in {"user", "project"}:
            return self._can_read(view, user_id=user_id, accessible_project_ids=accessible_project_ids)
        if view.scope_type == "federation":
            federation = await self.session.get(BIMFederation, view.scope_id)
            if federation is None:
                return False
            return federation.project_id in accessible_project_ids
        return False

    def _can_write(self, view: SmartView, *, user_id: uuid.UUID) -> bool:
        """Mutation predicate — only the author can edit/delete their view."""
        return view.created_by == user_id

    # ── Cross-module visibility event (#103) ──────────────────────────

    async def _emit_visibility_changed(
        self,
        view: SmartView,
        *,
        reason: str,
    ) -> None:
        """Re-broadcast a federation/project view's visibility change.

        Backlog #103: when a smart view's owner changes, the view is
        shared/unshared, or the view itself is created/updated/deleted
        under a federation scope, downstream consumers (the BIM viewer
        sidebar cache, the federation hub's permission badge) must be
        told to drop their cached list. We emit a single event the bus
        can fan out — subscribers are responsible for their own
        invalidation strategy. Fire-and-forget so the request still
        commits cleanly even if a subscriber raises.
        """
        try:
            payload = {
                "view_id": str(view.id),
                "scope_type": view.scope_type,
                "scope_id": str(view.scope_id),
                "owner_id": str(view.created_by),
                "shared": view.share_token is not None,
                "reason": reason,
            }
            event_bus.publish_detached(
                "smart_views.visibility_changed",
                payload,
                source_module="oe_smart_views",
            )
        except Exception:
            # Visibility re-emission is best-effort; never block the
            # transaction on a misbehaving subscriber.
            logger.debug("smart_views.visibility_changed emit failed", exc_info=True)

    # ── CRUD ───────────────────────────────────────────────────────────

    async def create_view(
        self,
        payload: SmartViewCreate,
        *,
        user_id: uuid.UUID,
    ) -> SmartViewResponse:
        """Persist a new SmartView after verifying the scope target."""
        await self._verify_scope(
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            user_id=user_id,
        )

        # Rules and legend are stored as plain JSON. Pydantic has
        # already validated every rule shape; we drop to dicts for the
        # JSON column.
        rules_json = [r.model_dump(mode="json") for r in payload.rules]
        legend = self._initial_legend(payload)

        view = SmartView(
            id=uuid.uuid4(),
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            name=payload.name,
            description=payload.description,
            rules=rules_json,
            default_action=payload.default_action,
            color_legend=legend,
            created_by=user_id,
        )
        await self.repo.add(view)
        await self._emit_visibility_changed(view, reason="created")
        return self._response_for(view, viewer_id=user_id)

    async def list_views(
        self,
        *,
        user_id: uuid.UUID,
        scope_type: str | None = None,
        scope_id: uuid.UUID | None = None,
    ) -> list[SmartViewResponse]:
        """Return every view the caller may see, newest first."""
        project_ids = await self._accessible_project_ids(user_id)
        rows = await self.repo.list_visible_to_user(
            user_id=user_id,
            accessible_project_ids=project_ids,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return [self._response_for(r, viewer_id=user_id) for r in rows]

    async def get_view(
        self,
        view_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> SmartViewResponse:
        """Fetch one view; 404 if not found / not visible."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        project_ids = set(await self._accessible_project_ids(user_id))
        if not await self._can_read_async(view, user_id=user_id, accessible_project_ids=project_ids):
            # 404, not 403 — same UUID-existence-leak hardening the
            # other modules use.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        return self._response_for(view, viewer_id=user_id)

    async def update_view(
        self,
        view_id: uuid.UUID,
        payload: SmartViewUpdate,
        *,
        user_id: uuid.UUID,
    ) -> SmartViewResponse:
        """Partial-update an existing view (authoring user only)."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        project_ids = set(await self._accessible_project_ids(user_id))
        if not await self._can_read_async(view, user_id=user_id, accessible_project_ids=project_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        if not self._can_write(view, user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author can edit this SmartView",
            )

        if payload.name is not None:
            view.name = payload.name
        if payload.description is not None:
            view.description = payload.description
        if payload.default_action is not None:
            view.default_action = payload.default_action
        if payload.rules is not None:
            view.rules = [r.model_dump(mode="json") for r in payload.rules]
            # Re-seed the legend whenever the rules change so the UI
            # never serves a stale palette.
            view.color_legend = self._initial_legend_from_rules(payload.rules)

        await self.session.flush()
        # Refresh ``updated_at`` (the ``onupdate=func.now()`` trigger
        # mutates the column at flush time, but the ORM marks the
        # attribute expired — accessing it from the sync Pydantic
        # validator would attempt a synchronous lazy reload and trip
        # MissingGreenlet under the async session).
        await self.session.refresh(view)
        await self._emit_visibility_changed(view, reason="updated")
        return self._response_for(view, viewer_id=user_id)

    async def delete_view(
        self,
        view_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> None:
        """Hard-delete a view (authoring user only)."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        project_ids = set(await self._accessible_project_ids(user_id))
        if not await self._can_read_async(view, user_id=user_id, accessible_project_ids=project_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        if not self._can_write(view, user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author can delete this SmartView",
            )
        # Capture identity for the visibility event before SQLAlchemy
        # detaches the row on delete.
        await self._emit_visibility_changed(view, reason="deleted")
        await self.repo.delete(view)

    # ── Evaluator ──────────────────────────────────────────────────────

    async def evaluate(
        self,
        view_id: uuid.UUID,
        model_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> SmartViewEvaluateResponse:
        """Run the view's rules against a specific BIM model's elements."""
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        project_ids = set(await self._accessible_project_ids(user_id))
        if not await self._can_read_async(view, user_id=user_id, accessible_project_ids=project_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")

        model: BIMModel | None = await self.repo.get_model(model_id)
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BIM model not found")
        # Cross-project leak hardening: the model's project must be
        # one the caller may read. Federation-scoped views are read
        # via the federation's project (already enforced above).
        model_project_id: uuid.UUID = model.project_id
        if model_project_id not in project_ids:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BIM model not found")

        elements = await self.repo.elements_for_model(model_id)
        states, legend = evaluate_smart_view(view, elements)
        return SmartViewEvaluateResponse(
            states=states,
            legend=legend or None,
            element_count=len(elements),
            rule_count=len(view.rules or []),
        )

    # ── Presets ───────────────────────────────────────────────────────

    @staticmethod
    def list_presets() -> list[SmartViewPresetSummary]:
        """Return the catalogue of built-in presets.

        Pure / static — does not touch the DB. The UI calls this to
        render the install cards in the SmartViews panel's "Presets"
        tab. We deliberately do NOT return the full rule list: install
        happens by ``preset_id`` so the server's canonical rule set is
        always authoritative (no stale-bundle replay risk).
        """
        return [
            SmartViewPresetSummary(
                preset_id=p["preset_id"],
                category=p["category"],
                name=p["name"],
                description=p["description"],
                rule_count=len(p["rules"]),
            )
            for p in BUILTIN_PRESETS
        ]

    async def install_preset(
        self,
        preset_id: str,
        *,
        scope_type: str,
        scope_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> SmartViewResponse:
        """Materialise a preset as a new SmartView under the given scope.

        Idempotent: if a view authored by ``user_id`` with the same
        ``name`` already exists under (``scope_type``, ``scope_id``),
        the existing row is returned instead of creating a duplicate.
        That matches user mental model — re-clicking "Install" twice
        in a row should never produce two identical cards.

        We validate the preset's rule list through the same Pydantic
        path a user-authored view goes through; presets ship as plain
        dicts so they cannot accidentally rely on a private code path
        the public API does not also accept.
        """
        preset = get_preset(preset_id)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preset not found: {preset_id!r}",
            )

        # Scope verification reuses the same guard create_view uses.
        await self._verify_scope(scope_type=scope_type, scope_id=scope_id, user_id=user_id)

        # Idempotency lookup — same author + same scope + same name.
        # We deliberately key on name (not preset_id) because a user
        # may freely rename an installed preset; re-installing then
        # should produce a *new* view, not silently bring back the
        # original name.
        existing_stmt = select(SmartView).where(
            SmartView.created_by == user_id,
            SmartView.scope_type == scope_type,
            SmartView.scope_id == scope_id,
            SmartView.name == preset["name"],
        )
        existing = (await self.session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return self._response_for(existing, viewer_id=user_id)

        # Revalidate the rules through Pydantic so a malformed preset
        # (e.g. someone edited presets.py with a typo) fails loudly at
        # install time rather than at evaluate time.
        rules = [SmartViewRule.model_validate(r) for r in preset["rules"]]
        payload = SmartViewCreate(
            scope_type=scope_type,  # type: ignore[arg-type]
            scope_id=scope_id,
            name=preset["name"],
            description=preset.get("description"),
            rules=rules,
            default_action=preset.get("default_action", "show_all"),  # type: ignore[arg-type]
        )
        return await self.create_view(payload, user_id=user_id)

    # ── Share-by-link ────────────────────────────────────────────────

    async def create_share_token(
        self,
        view_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> SmartViewShareInfo:
        """Generate (or rotate) a signed share token for an owned view.

        Only the authoring user may share the view. Calling this on a
        view that already has a token rotates the token (old links
        stop working immediately) — that doubles as the "rotate" UX
        without needing a separate endpoint.
        """
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        if not self._can_write(view, user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author can share this SmartView",
            )

        token = self._make_share_token(view.id)
        view.share_token = token
        await self.session.flush()
        await self._emit_visibility_changed(view, reason="shared")
        return SmartViewShareInfo(
            view_id=view.id,
            share_token=token,
            url=f"/share/smart-views/{token}",
        )

    async def revoke_share_token(
        self,
        view_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> None:
        """Null the view's share token; existing links stop working.

        Idempotent: revoking an already-revoked view is a no-op (still
        200) so the UI does not have to track local state.
        """
        view = await self.repo.get_by_id(view_id)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SmartView not found")
        if not self._can_write(view, user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author can revoke this SmartView's share token",
            )
        view.share_token = None
        await self.session.flush()
        await self._emit_visibility_changed(view, reason="unshared")

    async def resolve_share_token(self, token: str) -> SmartViewResponse:
        """Look up a SmartView by share token — UNAUTHENTICATED path.

        The token must:
          (a) carry a valid signature (else 404 — never 401, to avoid
              leaking the existence of the share endpoint to scanners);
          (b) decode to a UUID that matches an extant ``share_token``
              column value (a non-matching but signature-valid token
              indicates the link was revoked).
        Both failure modes return 404 with the same body so probing
        cannot distinguish them.

        The response is built with ``viewer_id=None`` so the share
        token does NOT leak back through the response payload (callers
        already hold the token; re-exposing it on the public route
        would let a screenshot leak the URL embed).
        """
        if not token or len(token) > 4096:
            # Guard against absurdly-long inputs before the signer
            # spends any CPU on them. 4 KB is well past a realistic
            # itsdangerous URL-safe token.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found")

        view_id = self._decode_share_token(token)
        if view_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found")

        view = await self.repo.get_by_id(view_id)
        if view is None or view.share_token != token:
            # The token decoded but the column is NULL (revoked) or
            # carries a *different* token (rotated). Same 404 either way.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found")

        return self._response_for(view, viewer_id=None)

    # ── Legend helpers ────────────────────────────────────────────────

    @staticmethod
    def _initial_legend(payload: SmartViewCreate) -> dict | None:
        """Stub legend keyed by the property a ``color_by_property`` rule
        targets. The real legend is rebuilt on every evaluate; this is
        only a hint for the UI to render an empty-state swatch row
        before the first evaluation lands.
        """
        return SmartViewService._initial_legend_from_rules(payload.rules)

    @staticmethod
    def _initial_legend_from_rules(rules: list) -> dict | None:
        for r in rules:
            args = getattr(r, "action_args", None)
            prop = getattr(args, "color_by_property", None) if args else None
            if prop:
                # ``__property__`` is a sentinel the UI can detect to
                # show "Auto-coloured by FireRating" before the first
                # evaluate populates the real value→hex map.
                return {"__property__": prop}
        return None
