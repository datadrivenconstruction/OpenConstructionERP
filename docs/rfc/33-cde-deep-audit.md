# RFC 33 — CDE module deep audit (ISO 19650)

**Status:** draft
**Related items:** ROADMAP_v1.9.md #33 (R2 → v1.9.1). Depends on #33 bug fix from R1 (v1.9.0).
**Date:** 2026-04-17

## 1. Context

R1 fixed the immediate "New Container doesn't work" bug (`mutationKey` + awaited invalidate + better error surfacing). R2 is the deeper audit: **is the CDE module actually complete, and does it honour ISO 19650 in day-to-day use?**

### What's already there (verified 2026-04-17)

- **ISO 19650 state machine** — `backend/app/core/cde_states.py` — WIP → SHARED → PUBLISHED → ARCHIVED, three gates (A/B/C) with role hierarchy (viewer < editor < task_team_manager < lead_ap < admin). ARCHIVED is terminal. Reverse transitions blocked.
- **Naming convention parts** — `ContainerCreate.originator_code`, `functional_breakdown`, `spatial_breakdown`, `form_code`, `discipline_code`, `sequence_number`.
- **Auto-code** — `POST /v1/cde/` with `container_code="AUTO"` assembles the code from the parts via `CDEService.generate_container_code`. Requires at least one part.
- **Revision auto-numbering** — `P.{N:02d}.01` preliminary, `C.{N:02d}` contractual, via `RevisionRepository.next_revision_number` (scoped per container).
- **Content hash** — SHA-256 computed from `container_id + revision_code + file_name + file_size` when `content_hash` not supplied.
- **Suitability code** — present on container (`suitability_code: String(10)`), free-form, not validated against ISO 19650 table.
- **State events** — `event_bus.publish("cde.container.promoted", ...)` on every valid transition.

### What's missing (the real audit findings)

1. **Suitability codes are free-text.** ISO 19650-1 specifies discrete S/A codes by lifecycle stage. Users enter whatever — "TBD", "s1", "Shared", etc. No lookup, no validation, no i18n.
2. **Transmittal ↔ CDE revision is one-way.** `TransmittalItem.document_id` points at a generic Document, not a `DocumentRevision`. A revision that got transmitted has no backlink — the container view can't show "this rev sent in Transmittal TR-001 on 2025-12-03 to X".
3. **Approval workflow is role-only.** Gate B (SHARED → PUBLISHED) requires `lead_ap` role, nothing else. No reviewer sign-off capture, no approval comments, no multi-signer requirement.
4. **State transition audit log is absent.** Events are published but nothing consumes them for persistent audit. If a container was promoted by mistake, no forensic trail.
5. **Bulk actions are absent.** No "promote all shared → published in discipline E" or "archive all superseded containers in zone A."
6. **External storage is stubbed.** `DocumentRevision.storage_key: String(500)` — just a path string. No MinIO/S3 integration in CDE (unlike Documents module which does have it). If the user uploads a 100 MB DWG rev, where does the bytes go? Answer: nowhere — only metadata is stored. Files actually live in Documents hub, revisions just point at keys.
7. **Revision file cross-link to Documents.** Same issue as transmittals — a revision doesn't formally cross-link to a Document row. If you upload a file into a CDE revision, you expect to see it at `/documents` too (per platform rule). Today, only `storage_key` string.
8. **No "compare revisions" view.** User can see revision list but can't diff P.01.01 → P.02.01.
9. **Breakdown codes are free-text.** Same problem as suitability — `functional_breakdown`, `spatial_breakdown`, etc. are `String(50)` free-text. ISO 19650 wants project-specific lookups.
10. **Frontend CDE page is 1,169 lines and uses custom modal patterns** — not consistent with the rest of the app. Review for UX parity.

## 2. Options considered

### Option A — Ship the critical ISO 19650 fixes now, defer the UX overhaul

Five must-fix items in v1.9.1:
1. Suitability-code lookup (fixed table per state + i18n labels)
2. Revision ↔ Document cross-link (a revision upload creates a Document row too)
3. Transmittal ↔ Revision cross-link (add `revision_id` to `TransmittalItem` alongside existing `document_id`)
4. State transition audit log (persistent table, consumes the existing event)
5. Approval captures (reviewer field + signed_at on the container during Gate B)

Other items (bulk actions, compare revisions, breakdown lookup, UX overhaul) → v1.9.2+.

### Option B — Full rewrite / module redesign

Rename to `/cde/v2`, fresh schema, full ISO 19650-2 alignment (information exchanges, milestone-scoped containers). Very large scope; not v1.9.1.

### Option C — Do nothing — mark CDE as "feature-complete for MVP" and move on

Ignores the audit findings. Won't pass "experienced CTO review."

## 3. Decision

**Option A.** Ship the five must-fix items. Explicit R3 / R4 issues for the rest.

### Concrete changes

#### 3.1 Suitability-code lookup

New constant table in `backend/app/modules/cde/suitability.py`:

```python
SUITABILITY_CODES: dict[str, list[tuple[str, str]]] = {
    "wip": [("S0", "Initial status or WIP")],
    "shared": [
        ("S1", "Suitable for coordination"),
        ("S2", "Suitable for information"),
        ("S3", "Suitable for internal review and comment"),
        ("S4", "Suitable for stage approval"),
        ("S6", "Suitable for PIM authorisation"),
        ("S7", "Suitable for AIM authorisation"),
    ],
    "published": [
        ("A1", "Approved for construction"),
        ("A2", "Approved for manufacture"),
        ("A3", "Approved for use"),
        ("A4", "Approved for regulatory submission"),
        ("A5", "Approved for delivery"),
    ],
    "archived": [("AR", "Archived / superseded")],
}
```

Pydantic validator in `ContainerCreate.suitability_code` — must be one of the codes valid for the chosen `cde_state`. Expose via `GET /v1/cde/suitability-codes` for the frontend dropdown.

#### 3.2 Revision ↔ Document cross-link

When a revision is created with a file, also create a `Document` row (like meeting-transcript cross-link at `meetings/router.py:991-1020`). Add `document_id: String(36)` column to `DocumentRevision`.

Migration: `alembic/versions/v191_cde_revision_document_link.py` — nullable column; existing rows unaffected.

`CDEService.create_revision` after writing the revision:
```python
if data.storage_key:
    doc = Document(
        project_id=container.project_id,
        name=data.file_name,
        description=f"CDE rev {revision_code} — {container.container_code}",
        category="cde",
        file_size=int(data.file_size) if data.file_size else None,
        mime_type=data.mime_type,
        file_path=data.storage_key,
        version=rev_number,
        uploaded_by=str(user_id) if user_id else "",
        tags=["cde", container.container_code],
    )
    self.session.add(doc)
    await self.session.flush()
    await self.revision_repo.update_fields(revision.id, document_id=str(doc.id))
```

#### 3.3 Transmittal ↔ Revision cross-link

Add `revision_id: GUID, nullable=True` to `TransmittalItem`. Frontend transmittal builder gets a "Link to CDE revision" picker. List containers → list revisions → select. `TransmittalItem.document_id` and `TransmittalItem.revision_id` are mutually-exclusive-preferred (prefer `revision_id` when set; fall back to `document_id` for free-form attachments).

Backlink on container view: `GET /v1/cde/containers/{id}/transmittals` returns `[{transmittal_number, sent_at, recipients[]}]`.

#### 3.4 State transition audit log

New table `oe_cde_state_transition` — (container_id, from_state, to_state, user_id, user_role, reason, gate_code, transitioned_at).

Event consumer in `cde/events.py`:
```python
@event_bus.subscribe("cde.container.promoted")
async def _log_transition(data: dict) -> None:
    # Persist a row in oe_cde_state_transition ...
```

`GET /v1/cde/containers/{id}/history` returns the audit trail.

#### 3.5 Approval captures on Gate B

Extend `StateTransitionRequest`:
```python
class StateTransitionRequest(BaseModel):
    target_state: str = Field(..., pattern=r"^(wip|shared|published|archived)$")
    reason: str | None = Field(default=None, max_length=500)
    approver_signature: str | None = Field(default=None, max_length=200)   # NEW
    approval_comments: str | None = Field(default=None, max_length=2000)   # NEW
```

On Gate B (SHARED → PUBLISHED), `approver_signature` is **required**. Service raises 400 otherwise. The signature is stored in `metadata_.last_approval = {by, at, signature, comments}`.

## 4. Implementation sketch (file-level)

### 4.1 Backend

- `backend/app/modules/cde/suitability.py` — new module with the lookup table + validation helpers.
- `backend/app/modules/cde/schemas.py` — tighten `suitability_code` + extend `StateTransitionRequest`.
- `backend/app/modules/cde/models.py` — add `document_id` column to `DocumentRevision`.
- `backend/app/modules/cde/service.py` — revision cross-link on create; enforce approver_signature on Gate B; persist approval metadata.
- `backend/app/modules/cde/events.py` — NEW file: subscribe to `cde.container.promoted`, persist to `oe_cde_state_transition`.
- `backend/app/modules/cde/models.py` — add `StateTransition` model for audit log.
- `backend/app/modules/cde/router.py` — new routes `/suitability-codes`, `/containers/{id}/history`, `/containers/{id}/transmittals`.
- `backend/app/modules/transmittals/models.py` — add `revision_id` column to `TransmittalItem`.
- `backend/alembic/versions/v191_cde_audit.py` — three migrations bundled.

### 4.2 Frontend

- `frontend/src/features/cde/CDEPage.tsx` — suitability dropdown (fetches `/suitability-codes`), approval signature modal on Gate B.
- `frontend/src/features/cde/CDEHistoryDrawer.tsx` — NEW: right-drawer showing state transition history.
- `frontend/src/features/cde/CDETransmittalsBadge.tsx` — small badge per container: "2 transmittals" → clicks into a drawer listing them.
- `frontend/src/features/transmittals/TransmittalsPage.tsx` — revision picker instead of document picker.

## 5. Testing plan

**Backend unit** (`backend/tests/unit/v1_9/test_cde_deep_audit.py`):
- Suitability validation: invalid code for state → 422
- Create revision → Document row persisted and `revision.document_id` populated
- Gate B without `approver_signature` → 400
- Gate B with signature → success + `metadata_.last_approval` populated
- Event consumer writes a row to `oe_cde_state_transition` (check with `session.execute`)

**Backend integration** (`backend/tests/integration/v1_9/test_cde_transmittals.py`):
- Create container + revision → link revision to transmittal item → `GET /containers/{id}/transmittals` returns it.

**Frontend E2E** (`frontend/e2e/v1.9/33-cde-deep-audit.spec.ts`):
- Suitability dropdown shows S1–S7 for SHARED, A1–A5 for PUBLISHED
- Revision upload → file appears at `/documents` too
- History drawer lists transition entries after a promotion
- Transmittal → revision-picker → select → verify `/containers/{id}/transmittals` shows the link

## 6. Risks / follow-ups

- **Existing data.** Any containers with free-text `suitability_code` that doesn't match the new lookup — migration handles them by setting to NULL (nullable column). A backfill script could bucket "s1" → "S1" etc., but not worth the effort in v1.9.1.
- **Event consumer race.** State-transition event publishes before the commit — the event consumer must either use the same session (inline) or subscribe post-commit. Current `event_bus` semantics (sync publish on `await`) need verification. If it fires before commit, audit row could reference a transition that gets rolled back. Mitigation: call the audit writer inline in `transition_state` after the repo update, not via event bus. Events stay for cross-module notification.
- **Bulk actions.** Deferred to v1.9.2 (R3). Track as `#33-R3-bulk`.
- **Compare revisions UI.** Deferred. Needs diff viewer for PDFs/DWGs — non-trivial.
- **Breakdown-code lookup.** Deferred. Needs per-project breakdown-code tables; out of scope for v1.9.1.
- **Frontend UX parity.** CDE page is older — deferred to R3 (v1.9.2 #33-R3-ux).
