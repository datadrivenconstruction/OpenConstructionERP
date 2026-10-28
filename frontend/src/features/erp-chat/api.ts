// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost, apiDelete, type Page } from '@/shared/lib/api';
import type { AdminStats, ChatSession, FeedbackResponse } from './types';

/**
 * The caller's chat sessions, newest first.
 *
 * `Pick<Page<…>>` rather than `Page<…>`: the route returns items and a real
 * count and nothing else. It takes no limit or offset either - the service is
 * called with a hardcoded 20 - so this is a page nobody can turn from here.
 * `total` is what lets the sidebar admit that, which is the whole reason it
 * has to reach the components rather than being discarded at this line.
 */
export async function fetchChatSessions(): Promise<Pick<Page<ChatSession>, 'items' | 'total'>> {
  return apiGet<Pick<Page<ChatSession>, 'items' | 'total'>>('/v1/erp_chat/sessions/');
}

export async function createChatSession(projectId?: string): Promise<ChatSession> {
  return apiPost('/v1/erp_chat/sessions/', { project_id: projectId, title: 'New Chat' });
}

export async function fetchSessionMessages(sessionId: string): Promise<unknown[]> {
  return apiGet(`/v1/erp_chat/sessions/${sessionId}/messages/`);
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  return apiDelete(`/v1/erp_chat/sessions/${sessionId}/`);
}

// ── T8: thumbs feedback + admin observability ────────────────────────────

/**
 * Submit (or flip) a thumbs up / down rating on an assistant message.
 *
 * The backend is idempotent per `(message_id, user)` — re-calling with a
 * different `rating` updates the existing row in place.
 */
export async function submitFeedback(
  messageId: string,
  rating: 1 | -1,
  comment?: string,
): Promise<FeedbackResponse> {
  return apiPost(`/v1/erp_chat/messages/${messageId}/feedback/`, { rating, comment });
}

/**
 * Fetch the admin observability rollup (token spend, feedback, cache hit
 * rate, daily breakdown, top thumbed-down prompts). Requires the
 * `erp_chat.admin` permission (manager+); 403 propagates as a thrown error.
 */
export async function getAdminStats(windowDays = 30): Promise<AdminStats> {
  return apiGet(`/v1/erp_chat/admin/stats/?window_days=${windowDays}`);
}
