# RFC 29 — Meetings: edit + attachments + description

**Status:** draft
**Related items:** ROADMAP_v1.9.md #29 (R2 → v1.9.1)
**Date:** 2026-04-17

## 1. Context

At `/meetings` the user reports:
- No **edit** function on a meeting
- On create: need **file attachments** (with download) and a **description / minutes** field

### Current state

- **Model** (`backend/app/modules/meetings/models.py`): required `project_id`, `meeting_number`, `meeting_type`, `title`, `meeting_date`, `status`; optional `location`, `chairperson_id`, `minutes` (Text); JSON fields `attendees`, `agenda_items`, `action_items`, `metadata_`.
- **No `document_ids` field exists** — meetings can't reference files today.
- **CRUD:**
  - `POST /v1/meetings/` ✅ + UI (`CreateMeetingModal`)
  - `GET /v1/meetings/` ✅ + UI (list + expanded rows)
  - `PATCH /v1/meetings/{id}` ✅ backend, ❌ **no UI**
  - `DELETE /v1/meetings/{id}` ✅ backend, ❌ **no UI**
  - Auxiliaries: `POST /{id}/complete/`, `GET /{id}/export/pdf/`, `POST /import-summary/`

- **Frontend API** (`frontend/src/features/meetings/api.ts`) exports `updateMeeting` (L97-102) but nothing calls it; no `deleteMeeting` wrapper.

- **Task cross-link** exists — completing a meeting auto-creates `Task` rows with `task.meeting_id = meeting.id` (`service.py:252-376`). Deleting a meeting nulls the FK (not cascade-delete).

### Two viable attachment patterns

- **(a) Dedicated `MeetingAttachment` table** — 1-N rows, separate storage. Maximal isolation.
- **(b) Cross-link to the DocumentService** — `meeting.document_ids: list[UUID]`. Same pattern used by Correspondence (`linked_document_ids`) and FieldReports (`document_ids`).

Pattern (b) aligns with the platform rule "one file = one Document row" already in effect since v1.8.3.

## 2. Options considered

### Option A — Inline PATCH for edit, document_ids list for attachments, plain textarea for minutes

Leverages everything already in place. Minimal new surface: one new DB column, no new storage path, no new routes required (PATCH handles document_ids).

### Option B — Dedicated MeetingAttachment table + rich-text minutes

Maximum flexibility for long-term features (per-attachment captions, attachment ordering, rich-text with embedded images). Large scope for a feature that the user asked about concretely in terms of "download the file."

## 3. Decision

**Option A.** Matches the platform pattern, ships in a single commit, and the upgrade path to (B) is clean if we ever need it.

- **Edit** — add `EditMeetingModal` mirroring `CreateMeetingModal`, calling `updateMeeting(id, body)` with only changed fields. Existing PATCH handler already accepts partial updates.
- **Delete** — confirm dialog via `useConfirm()` (already imported), then `apiDelete('/v1/meetings/{id}')`; new wrapper `deleteMeeting(id)` in `api.ts`.
- **Attachments** — `document_ids: list[UUID]` on `Meeting`. Create dropzone uploads to DocumentService first, then includes the resulting IDs in the create payload. Edit dialog shows a thumbnail list with download links + remove buttons.
- **Minutes** — plain `<textarea>`, matches existing convention (Risk, Safety, Correspondence use the same). Rich-text editor deferred.

## 4. Implementation sketch

### 4.1 DB migration

```python
# alembic/versions/xxxx_meetings_document_ids.py
op.add_column(
    "oe_meetings_meeting",
    sa.Column("document_ids", sa.JSON(), nullable=False, server_default="[]"),
)
```

### 4.2 Backend changes

`backend/app/modules/meetings/models.py`:
```python
document_ids: Mapped[list[str]] = mapped_column(
    JSON,
    nullable=False,
    default=list,
    server_default="[]",
)
```

`backend/app/modules/meetings/schemas.py` — add `document_ids: list[UUID] = Field(default_factory=list)` to `MeetingCreate`, `MeetingUpdate`, `MeetingResponse`.

No new routes required; PATCH already handles arbitrary fields.

Optional convenience route for link / unlink without re-posting the whole array:
```
POST   /v1/meetings/{id}/attachments       { document_id }
DELETE /v1/meetings/{id}/attachments/{did}
```
Nice-to-have, not blocking. Skip unless the UI actually benefits.

### 4.3 Frontend changes

**api.ts**
```ts
export const deleteMeeting = (id: string) => apiDelete<void>(`/v1/meetings/${id}`);
// updateMeeting already exists at L97-102 — fine.
```

**MeetingsPage.tsx**
- `EditMeetingModal` clones `CreateMeetingModal` with a `meeting?: Meeting` prop; pre-fills state on mount; on submit, diffs the form against the original and calls `updateMeeting(id, diff)`.
- `ConfirmDeleteDialog` — triggered by the row-level "Delete" button, confirms, calls `deleteMeeting`, invalidates `['meetings', projectId]`.
- `AttachmentDropzone` in both create + edit modals — uploads via `DocumentService.upload`, collects returned IDs, stores in local form state.
- Attachment list component with name + size + download button.
- Minutes: `<textarea rows={8} maxLength={50_000} />`.

### 4.4 Action-item → task (unchanged)

The existing `complete_meeting` flow remains. An optional enhancement is a per-row "Create task" button while the meeting is still open — not in scope for v1.9.1, tracked as R3.

## 5. Testing plan

**Backend unit** (`backend/tests/unit/v1_9/test_meetings.py`):
- PATCH with partial fields leaves others unchanged
- PATCH with `document_ids` replaces the list; deduplication guard
- DELETE cascades task `meeting_id` to NULL (task survives)
- Deletion leaves documents intact

**Frontend E2E** (`frontend/e2e/v1.9/29-meetings.spec.ts`):
- Create meeting with two attachments → uploads succeed → meeting lists both documents
- Download attachment → file retrieved
- Edit meeting title + minutes → PATCH payload matches diff
- Add attachment in edit mode → meeting updates
- Delete meeting → disappears from list; linked tasks still present
- Cross-check /documents — the attached files appear there as well (v1.8.3 cross-link pattern)

## 6. Risks / follow-ups

- **Orphan documents.** If a user removes an attachment in the meeting edit flow, the Document row stays (intentional — same file may be attached elsewhere). Garbage-collection of truly-orphan Documents tracked as a separate platform chore, not part of this RFC.
- **JSON vs. array column.** SQLite (dev) supports JSON; Postgres uses JSONB. Both allow the array idiom; Alembic migration takes the portable path.
- **Large attachments.** Meetings may attract 20-30 MB minute PDFs. DocumentService already handles multipart upload; no changes needed here.
- **Rich-text minutes.** When the business needs formatting (bold, lists, links) we will swap the textarea for the same editor chosen by Tasks / Correspondence. Until then, plain text is honest.
