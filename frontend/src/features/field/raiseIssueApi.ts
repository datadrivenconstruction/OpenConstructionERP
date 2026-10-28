// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field "raise issue" wire helpers.
 *
 * A field defect is captured through the field-native capture endpoints, NOT the
 * desktop punchlist routes. The desktop `POST /v1/punchlist/items/` requires a
 * JWT + `punchlist.create` RBAC + a real project membership - none of which a
 * field session (Bearer session token + `X-Field-PIN`) has, so replaying there
 * would 401 forever. The field-diary module exposes purpose-built, field-authed
 * equivalents that the offline queue can actually drain:
 *
 *   - `POST /v1/field-diary/capture/punch/`  create a punch, idempotent on
 *     `client_op_id`, returns the created punch id as `result_id`.
 *   - `POST /v1/field-diary/capture/photo/`  attach a photo (multipart) to a
 *     punch owned by the session project, keyed by `X-Punch-Item-Id`.
 *   - `GET  /v1/field-diary/sync/ops/`       the session's applied-op ledger,
 *     used to resolve a `client_op_id` back to its punch id across a reload.
 *
 * The create op rides the shared offline mutation queue (which injects
 * `client_op_id` into the body + the `X-Client-Op-Id` header and attaches the
 * field-session headers). The photo cannot: the queue sender is JSON-only and
 * has no op-to-op dependency, so the photo is uploaded here directly once the
 * created punch id is known. See {@link ../shared/lib/offline}.
 */

import type { PunchPriority } from '../punchlist/api';
import type { FieldSession } from './fieldApi';

/** The queue op `kind` for a raised issue - the filter key on the queue side. */
export const RAISE_ISSUE_KIND = 'field.punch.create';

/** A device-captured geolocation for a raised issue (WGS84). */
export interface RaiseIssueGeo {
  lat: number;
  lon: number;
  /** GPS accuracy radius in metres, when the device reports it. */
  accuracyM?: number;
}

/**
 * The JSON body for `POST /v1/field-diary/capture/punch/`. `client_op_id` is
 * NOT set here - the mutation queue's sender injects it (and the matching
 * header) at replay time so idempotency holds end to end.
 */
export interface PunchCreateBody {
  title: string;
  description: string;
  priority: PunchPriority;
  /** Device-local capture time (ISO), kept distinct from server time. */
  captured_at: string;
  /** Geo travels in the field-capture envelope (`lat`/`lon`/`accuracy_m`). */
  lat?: number;
  lon?: number;
  accuracy_m?: number;
}

/** Build the capture body from the form draft, omitting absent geo fields. */
export function buildPunchCreateBody(input: {
  title: string;
  description?: string;
  priority: PunchPriority;
  capturedAt: string;
  geo?: RaiseIssueGeo | null;
}): PunchCreateBody {
  const body: PunchCreateBody = {
    title: input.title,
    description: input.description ?? '',
    priority: input.priority,
    captured_at: input.capturedAt,
  };
  if (input.geo) {
    body.lat = input.geo.lat;
    body.lon = input.geo.lon;
    if (typeof input.geo.accuracyM === 'number' && Number.isFinite(input.geo.accuracyM)) {
      body.accuracy_m = input.geo.accuracyM;
    }
  }
  return body;
}

/** Auth headers for a field-session request (Bearer session token + PIN). */
function fieldHeaders(session: FieldSession): Record<string, string> {
  return {
    Authorization: `Bearer ${session.token}`,
    'X-Field-PIN': session.pin,
    Accept: 'application/json',
  };
}

/**
 * Upload a photo to a field-captured punch item. Multipart (`file`), keyed by
 * the created punch id (`X-Punch-Item-Id`) and the create op id
 * (`X-Client-Op-Id`, which the endpoint requires for its ledger). Returns true
 * on success; never throws - a network/transport failure resolves to false so
 * the caller keeps the pending-photo record for the next sync.
 */
export async function uploadFieldPunchPhoto(
  session: FieldSession,
  punchItemId: string,
  clientOpId: string,
  file: Blob,
  filename: string,
): Promise<boolean> {
  try {
    const form = new FormData();
    // A filename with an extension lets the server derive a safe suffix.
    form.append('file', file, filename || 'photo.jpg');
    const res = await fetch('/api/v1/field-diary/capture/photo/', {
      method: 'POST',
      headers: {
        ...fieldHeaders(session),
        'X-Punch-Item-Id': punchItemId,
        'X-Client-Op-Id': clientOpId,
      },
      body: form,
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Resolve create `client_op_id`s to their server punch ids via the session's
 * applied-op ledger. This is the durable fallback used after a reload, when the
 * create synced in a previous session so its punch id is no longer in the live
 * drain results. Returns only the ids it could resolve; a failure yields an
 * empty map (the caller simply retries on the next sync).
 */
export async function resolveSyncedPunchIds(
  session: FieldSession,
  wanted: readonly string[],
): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  if (wanted.length === 0) return out;
  try {
    const res = await fetch('/api/v1/field-diary/sync/ops/', { headers: fieldHeaders(session) });
    if (!res.ok) return out;
    const rows = (await res.json()) as
      | { client_op_id?: string; result_id?: string | null }[]
      | null;
    const want = new Set(wanted);
    for (const row of Array.isArray(rows) ? rows : []) {
      const opId = row?.client_op_id;
      const resultId = row?.result_id;
      if (opId && resultId && want.has(opId)) out.set(opId, resultId);
    }
  } catch {
    /* offline or transient - resolve nothing, retry next sync */
  }
  return out;
}
