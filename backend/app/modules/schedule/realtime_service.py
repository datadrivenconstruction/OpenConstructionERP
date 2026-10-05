# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Real-time collaboration service (T3.4).

Optimistic-concurrency guarded writes on a single schedule activity. A client
edits against the revision it last read; this service asks the pure
:mod:`app.modules.schedule.realtime_math` engine whether that base is current,
stale, ahead, or unchanged, and only persists on an APPLY verdict (bumping the
monotonic ``Activity.revision`` token in the same write). A stale base is
rejected so a slow tab can never silently clobber a concurrent edit; an
unchanged double-submit is an idempotent no-op that does not bump the revision.

Wraps :class:`~app.modules.schedule.service.ScheduleService` to reuse the
canonical activity repository and the existing event publishing, so the
``schedule.activity.updated`` event fires unchanged and the presence bridge
picks it up. All writes ``flush`` only; the request middleware owns the commit
(matching every other schedule service).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule import realtime_math
from app.modules.schedule.milestone_events import announce_if_milestone_reached, is_completed
from app.modules.schedule.models import Activity
from app.modules.schedule.realtime_math import RevisionCheck
from app.modules.schedule.service import ScheduleService, _safe_publish

# ── Editable-field whitelist (security boundary) ─────────────────────────────
#
# A guarded update is a generic ``{field: value}`` patch coming straight from a
# client, so the set of columns it may write MUST be an explicit allowlist - an
# attacker (or a buggy client) must never be able to set ``revision`` (which
# would defeat the lost-update guard), re-parent the activity, move it to
# another schedule, or overwrite immutable bookkeeping. Only plain, obviously
# user-editable scalar columns are listed here. Structural columns
# (``id`` / ``schedule_id`` / ``parent_id`` / ``revision`` / ``created_at`` /
# ``updated_at``), the CPM result columns, the JSON collections (dependencies /
# resources / boq_position_ids / bim_element_ids / metadata) and the cost /
# units / progress-rigor columns are deliberately excluded: those have their
# own validated endpoints (typed-progress, calendar, link-position, ...). Keep
# this list conservative; widen it only with a matching validation story.
_EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "wbs_code",
        "start_date",
        "end_date",
        "duration_days",
        "progress_pct",
        "status",
        "activity_type",
        "color",
        "sort_order",
        "constraint_type",
        "constraint_date",
    }
)


class UnknownGuardedFieldError(ValueError):
    """Raised when a guarded update carries a field outside the whitelist.

    The router maps this to HTTP 422 - the request is well-formed JSON but names
    a column a guarded write is not allowed to touch.
    """

    def __init__(self, unknown: set[str]) -> None:
        self.unknown = sorted(unknown)
        super().__init__(f"Fields not allowed in a guarded update: {self.unknown}")


def _coerce_value(field: str, value: object) -> object:
    """Coerce an incoming scalar into the column's stored representation.

    ``progress_pct`` is stored as a string (the platform keeps the activity
    percent as ``String(10)``); everything else in the whitelist is stored as
    the JSON-native type the client already sent. Kept tiny on purpose - the
    whitelist guarantees we never reach a column needing exotic handling.
    """
    if field == "progress_pct":
        return str(value)
    return value


class ScheduleRealtimeService:
    """Revision-guarded activity writes and revision reads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base = ScheduleService(session)

    async def revision_of(self, activity_id: uuid.UUID) -> int:
        """Return the current optimistic-concurrency revision of an activity.

        The caller is expected to have already authorised access to the owning
        project (the router's ``_verify_activity`` does this and 404s on a
        cross-tenant id); ``get_activity`` 404s on a missing id.
        """
        activity = await self.base.get_activity(activity_id)
        return activity.revision

    async def guarded_update(
        self,
        activity_id: uuid.UUID,
        *,
        client_base_revision: int | None,
        fields: dict,
        user_id: str,
    ) -> tuple[Activity, RevisionCheck]:
        """Apply a whitelisted patch iff the client's base revision is current.

        Returns ``(activity, check)``. The router inspects ``check.outcome``:
        APPLY / NOOP both carry the up-to-date activity (APPLY persisted, NOOP
        unchanged); STALE and INVALID return the current activity WITHOUT any
        write so the router can hand back the live state (409) or reject the
        malformed base (422).
        """
        # Reject any field outside the allowlist before doing anything else -
        # this is the security boundary. A guarded update must never be a path
        # to set ``revision`` or re-home the activity.
        unknown = set(fields) - _EDITABLE_FIELDS
        if unknown:
            raise UnknownGuardedFieldError(unknown)

        activity = await self.base.get_activity(activity_id)
        schedule_id_str = str(activity.schedule_id)
        was_completed = is_completed(activity.status, activity.progress_pct)

        # ``has_changes`` is true only when at least one supplied field differs
        # from what is already stored, so an idempotent re-submit of identical
        # values is a NOOP (no revision bump) rather than a spurious APPLY.
        has_changes = any(getattr(activity, name) != _coerce_value(name, value) for name, value in fields.items())

        check = realtime_math.check_revision(
            client_base_revision=client_base_revision,
            server_revision=activity.revision,
            has_changes=has_changes,
        )

        if not check.should_write:
            # NOOP / STALE / INVALID: nothing is persisted. Return the activity
            # as loaded so the router can serialise the current server state.
            return activity, check

        # APPLY: persist the whitelisted fields AND the bumped revision in one
        # atomic compare-and-swap so the new revision is exactly ``base + 1``
        # (the lost-update guard). The ``WHERE revision = base`` clause means a
        # concurrent writer that already bumped the row matches zero rows, so we
        # never silently clobber it. ``update_fields_if_revision`` flushes; the
        # middleware commits.
        write: dict[str, object] = {name: _coerce_value(name, value) for name, value in fields.items()}
        write["revision"] = check.next_revision
        swapped = await self.base.activity_repo.update_fields_if_revision(
            activity_id, expected_revision=activity.revision, **write
        )
        if not swapped:
            # A concurrent writer bumped the revision between our read and our
            # conditional write. Re-read and re-evaluate against the new server
            # revision: the client base is now behind, so this yields a STALE
            # verdict (no write) and the router returns the current state as a
            # 409 - no lost update.
            refreshed_stale = await self.base.get_activity(activity_id)
            stale = realtime_math.check_revision(
                client_base_revision=client_base_revision,
                server_revision=refreshed_stale.revision,
                has_changes=has_changes,
            )
            return refreshed_stale, stale

        await _safe_publish(
            "schedule.activity.updated",
            {
                "activity_id": str(activity_id),
                "schedule_id": schedule_id_str,
                "fields": sorted(fields.keys()),
                "revision": check.next_revision,
                "actor_id": str(user_id),
            },
            source_module="oe_schedule",
        )

        refreshed = await self.base.get_activity(activity_id)
        await announce_if_milestone_reached(self.session, refreshed, was_completed=was_completed, actor_id=user_id)
        return refreshed, check
