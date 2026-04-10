import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import type { ChatSession } from './types';

export async function fetchChatSessions(): Promise<{ items: ChatSession[]; total: number }> {
  return apiGet('/v1/erp_chat/sessions/');
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
