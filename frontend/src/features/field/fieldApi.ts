// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field-worker API client — authenticated reads + offline-queued writes.
 *
 * Reads go straight over `fetch` with the field session token + PIN (the
 * desktop `shared/lib/api.ts` attaches a JWT the field worker does not have).
 * Writes are NOT sent here: they are handed to the field mutation queue via
 * `useFieldSync().enqueue` so they survive a flaky site connection and replay
 * idempotently. This module only owns the read side + the session helpers.
 */

import type { CrewRosterMember } from './crewRosterStore';

/** The field session, persisted by the PIN-redemption screen into sessionStorage. */
export interface FieldSession {
  token: string;
  pin: string;
  projectId: string;
  userId: string;
}

/** Persist a freshly-minted field session into sessionStorage (set by the
 * PIN-redemption screen after a successful `/auth/consume/`). The field shell
 * reads these exact keys via {@link readFieldSession}. */
export function persistFieldSession(session: FieldSession): void {
  try {
    sessionStorage.setItem('oe_field_session_token', session.token);
    sessionStorage.setItem('oe_field_session_pin', session.pin);
    sessionStorage.setItem('oe_field_session_project', session.projectId);
    sessionStorage.setItem('oe_field_session_user', session.userId);
  } catch {
    /* storage unavailable - the shell will show the signed-out state */
  }
}

/** The object handed out last time, so an unchanged session keeps its identity. */
let lastSession: FieldSession | null = null;

/** Read the live field session from sessionStorage, or null when absent.
 *
 * Returns the *same object* while the stored values are unchanged. The field
 * shell calls this during render and re-renders on every sync tick, so minting
 * a fresh object each time would restart every effect keyed on the session -
 * the crew roster would refetch on a loop, on the phone, over the connection
 * this screen exists to work without. Fixed here rather than at the one caller
 * that noticed, because the next caller will read it during render too.
 *
 * The returned object is shared and must be treated as read-only.
 */
export function readFieldSession(): FieldSession | null {
  try {
    const token = sessionStorage.getItem('oe_field_session_token');
    const pin = sessionStorage.getItem('oe_field_session_pin');
    const projectId = sessionStorage.getItem('oe_field_session_project');
    const userId = sessionStorage.getItem('oe_field_session_user');
    if (!token || !pin || !projectId) {
      lastSession = null;
      return null;
    }
    const next: FieldSession = { token, pin, projectId, userId: userId ?? '' };
    if (
      lastSession &&
      lastSession.token === next.token &&
      lastSession.pin === next.pin &&
      lastSession.projectId === next.projectId &&
      lastSession.userId === next.userId
    ) {
      return lastSession;
    }
    lastSession = next;
    return next;
  } catch {
    return null;
  }
}

function authHeaders(session: FieldSession): Record<string, string> {
  return {
    Authorization: `Bearer ${session.token}`,
    'X-Field-PIN': session.pin,
    Accept: 'application/json',
  };
}

export interface DiaryActivity {
  id: string;
  entry_id: string;
  activity_type: string;
  description: string | null;
  hours: string | null;
  location: string | null;
  started_at: string | null;
  ended_at: string | null;
  metadata: Record<string, unknown>;
}

export interface DiaryEntry {
  id: string;
  project_id: string;
  author_id: string;
  entry_date: string;
  status: string;
  headcount: number;
  notes_md: string | null;
}

/** ISO YYYY-MM-DD for "today" in the device's local timezone. */
export function todayIso(): string {
  const d = new Date();
  const tz = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - tz).toISOString().slice(0, 10);
}

/**
 * The project's people and crews, for the punch list to pick from.
 *
 * Returns `null` rather than `[]` when the call does not land, so the caller
 * can tell "nobody is on this project" from "the phone has no signal" and keep
 * the cached list in the second case.
 */
export async function listRoster(session: FieldSession): Promise<CrewRosterMember[] | null> {
  try {
    const res = await fetch('/api/v1/field-diary/roster/', { headers: authHeaders(session) });
    if (!res.ok) return null;
    const data: unknown = await res.json();
    return Array.isArray(data) ? (data as CrewRosterMember[]) : null;
  } catch {
    return null;
  }
}

/** List this field session's diary entries for the given date (read-only). */
export async function listEntries(session: FieldSession, date: string): Promise<DiaryEntry[]> {
  const url = `/api/v1/field-diary/entries/?date_from=${date}&date_to=${date}`;
  const res = await fetch(url, { headers: authHeaders(session) });
  if (!res.ok) return [];
  const data = (await res.json()) as DiaryEntry[] | null;
  return Array.isArray(data) ? data : [];
}

/** List the activities on one diary entry (read-only). */
export async function listActivities(
  session: FieldSession,
  entryId: string,
): Promise<DiaryActivity[]> {
  // The entry detail does not embed activities; the list view derives crew
  // status from the entry's own activities endpoint when present. The backend
  // exposes activities as a sub-resource create-only, so the Today tab reads
  // the entry list and the Crew tab tracks open punches in component state +
  // the offline queue. This helper is a thin read used by the Today summary.
  const res = await fetch(`/api/v1/field-diary/entries/${encodeURIComponent(entryId)}/`, {
    headers: authHeaders(session),
  });
  if (!res.ok) return [];
  const data = (await res.json()) as { activities?: DiaryActivity[] } | null;
  return Array.isArray(data?.activities) ? (data?.activities ?? []) : [];
}
