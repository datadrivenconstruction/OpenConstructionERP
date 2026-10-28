// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the /api/v1/reconciliation/* surface. Every route is
// project-scoped and IDOR-guarded server-side (verify_project_access), so the
// project id is always in the path - a link can only be assembled, listed, or
// ruled on within a project the caller may reach.

import { apiGet, apiPost } from '@/shared/lib/api';
import type { EventThread, RecordLink, RecordLinkDecisionIn } from './types';

const BASE = '/v1/reconciliation';

// Assemble the reconciled cross-channel thread for one event. The event_key is
// either a seed record key "<record_type>:<record_id>" (e.g. change_order:<uuid>)
// or a normalized-subject key; it is path-escaped because a subject key can carry
// spaces and other reserved characters.
export const getEventThread = (projectId: string, eventKey: string) =>
  apiGet<EventThread>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/events/${encodeURIComponent(eventKey)}/thread`,
  );

// List every persisted confirm / reject decision recorded for a project.
export const listRecordLinks = (projectId: string) =>
  apiGet<RecordLink[]>(`${BASE}/projects/${encodeURIComponent(projectId)}/record-links`);

// Persist a confirm / reject decision on a suggested correlation. Idempotent:
// re-posting the same canonical endpoint pair updates the existing decision
// rather than duplicating it.
export const decideRecordLink = (projectId: string, body: RecordLinkDecisionIn) =>
  apiPost<RecordLink, RecordLinkDecisionIn>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/record-links`,
    body,
  );
