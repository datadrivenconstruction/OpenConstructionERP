// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { aiApi, type AISettings } from '@/features/ai/api';
import { hasLlmKey } from '@/features/ai-estimator/useAiReadiness';
import { uuid } from '@/shared/lib/browser';
import {
  fetchChatSessions,
  fetchSessionMessages,
  deleteChatSession,
} from '../api';
import { isProposalTool } from '../toolLabels';
import { toolCallsFromPersisted, type PersistedChatMessage } from '../transcript';
import type { ChatMessage, ChatSession, DataPanelEntry, ToolCallInfo } from '../types';

/** Shape of a persisted message row from GET /sessions/{id}/messages/. */
interface PersistedMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string | null;
  tool_calls: { name?: string; args?: Record<string, unknown> }[] | null;
  tool_results: { tool?: string; result?: ToolCallInfo['result'] }[] | null;
  renderer: string | null;
  renderer_data: unknown;
  created_at: string;
}

const DEFAULT_SUGGESTIONS = [
  'Show all projects',
  'BOQ overview for this project',
  'Run validation',
  'Risk overview',
  'Search CWICR database',
];

function uid(): string {
  return uuid();
}

export interface UseChatFullPageReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  sessionId: string | null;
  suggestions: string[];
  dataPanelEntries: DataPanelEntry[];
  activePanelIndex: number;
  aiConfigured: boolean | null; // null = still loading
  sessions: ChatSession[];
  /** How many sessions the caller has, as the server counts them. The route
   *  serves a hardcoded 20 and takes no offset, so this is how the sidebar
   *  says it is showing a slice - it cannot fetch the rest. */
  sessionsTotal: number;
  sessionsLoading: boolean;
  loadingSessionId: string | null;
  sendMessage: (text: string) => void;
  clearChat: () => void;
  setActivePanelIndex: (idx: number) => void;
  loadSession: (id: string) => Promise<void>;
  removeSession: (id: string) => Promise<void>;
  refreshSessions: () => Promise<void>;
}

/**
 * Rebuild the data-panel history from persisted assistant messages. Each
 * stored assistant turn that carried a renderer becomes one panel entry, in
 * chronological order, so resuming a session restores the right-hand cards
 * (not just the chat text).
 */
function panelEntriesFromMessages(rows: PersistedMessage[]): DataPanelEntry[] {
  const entries: DataPanelEntry[] = [];
  for (const row of rows) {
    if (row.role !== 'assistant' || !row.renderer || row.renderer === 'error') continue;
    const ts = new Date(row.created_at).getTime() || Date.now();
    // A proposal is shown as a card in the conversation itself, so the panel
    // shows the turn's last lookup instead, if it had one.
    if (row.renderer === 'action_proposal') {
      const lookup = [...toolCallsFromPersisted(row as unknown as PersistedChatMessage)]
        .reverse()
        .find((tc) => {
          const renderer = tc.result?.renderer;
          return !!renderer && renderer !== 'error' && renderer !== 'action_proposal';
        });
      if (lookup?.result?.renderer) {
        entries.push({
          renderer: lookup.result.renderer,
          data: lookup.result.data,
          toolName: lookup.name,
          summary: lookup.result.summary ?? '',
          timestamp: ts,
        });
      }
      continue;
    }
    // Prefer the explicit renderer_data; fall back to the last tool result's
    // data so older rows (pre renderer_data column) still render.
    let data: unknown = row.renderer_data;
    let toolName = 'result';
    if ((data == null || data === undefined) && Array.isArray(row.tool_results)) {
      const last = [...row.tool_results].reverse().find((tr) => tr?.result?.renderer);
      data = last?.result?.data;
      toolName = last?.tool ?? toolName;
    } else if (Array.isArray(row.tool_results) && row.tool_results.length > 0) {
      toolName = row.tool_results[row.tool_results.length - 1]?.tool ?? toolName;
    }
    entries.push({
      renderer: row.renderer,
      data,
      toolName,
      summary: '',
      timestamp: ts,
    });
  }
  return entries;
}

export function useChatFullPage(): UseChatFullPageReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_SUGGESTIONS);
  const [dataPanelEntries, setDataPanelEntries] = useState<DataPanelEntry[]>([]);
  const [activePanelIndex, setActivePanelIndex] = useState(-1);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsTotal, setSessionsTotal] = useState(0);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { i18n } = useTranslation();

  // Check if any AI provider is configured
  useEffect(() => {
    let cancelled = false;
    aiApi
      .getSettings()
      .then((settings: AISettings) => {
        if (cancelled) return;
        // Prefer the backend's authoritative readiness flag (counts local
        // Ollama / vLLM via base_url, which carry no api_key). Fall back to the
        // shared local-aware helper for older payloads without the flag.
        const ready =
          typeof settings.ai_ready === 'boolean' ? settings.ai_ready : hasLlmKey(settings);
        setAiConfigured(ready);
      })
      .catch(() => {
        if (!cancelled) setAiConfigured(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const res = await fetchChatSessions();
      setSessions(res.items ?? []);
      setSessionsTotal(res.total ?? res.items?.length ?? 0);
    } catch {
      // Non-fatal: the sidebar just stays empty. The chat itself still works.
      setSessions([]);
      setSessionsTotal(0);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  // Load the session list once on mount so the user can resume past chats.
  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  const loadSession = useCallback(
    async (id: string) => {
      if (abortRef.current) abortRef.current.abort();
      // Aborting the in-flight stream does not run its finally block
      // synchronously, so clear the streaming flag here. Otherwise loading a
      // past session mid-stream leaves the UI locked (input disabled, spinner
      // active) against a stream that no longer exists.
      setIsStreaming(false);
      setLoadingSessionId(id);
      try {
        const rows = (await fetchSessionMessages(id)) as PersistedMessage[];
        const rebuilt: ChatMessage[] = rows
          .filter((r) => r.role === 'user' || r.role === 'assistant')
          .map((r) => ({
            id: r.id,
            role: r.role,
            content: r.content ?? '',
            ts: new Date(r.created_at),
            // Stored as a list or, in some rows, an object; a proposal comes
            // back as its card, which re-reads its current status.
            toolCalls:
              r.role === 'assistant'
                ? toolCallsFromPersisted(r as unknown as PersistedChatMessage)
                : undefined,
          }));
        const entries = panelEntriesFromMessages(rows);
        setMessages(rebuilt);
        setDataPanelEntries(entries);
        setActivePanelIndex(entries.length > 0 ? entries.length - 1 : -1);
        setSessionId(id);
        setSuggestions([]);
      } catch {
        // Surface a non-destructive system note rather than wiping the UI.
        setMessages((prev) => [
          ...prev,
          {
            id: uid(),
            role: 'system',
            content: 'Could not load that conversation. It may have been deleted.',
            ts: new Date(),
          },
        ]);
        // Deselect the broken session so the sidebar no longer highlights it
        // as active. Otherwise the UI is inconsistent: a session is "active"
        // but its messages never loaded, and the user has no way to tell.
        setSessionId(null);
      } finally {
        setLoadingSessionId(null);
      }
    },
    [],
  );

  const removeSession = useCallback(
    async (id: string) => {
      // Optimistically drop from the list; restore on failure.
      const prev = sessions;
      setSessions((s) => s.filter((x) => x.id !== id));
      try {
        await deleteChatSession(id);
        // If we deleted the active conversation, reset to a fresh chat.
        setSessionId((current) => {
          if (current === id) {
            setMessages([]);
            setDataPanelEntries([]);
            setActivePanelIndex(-1);
            setSuggestions(DEFAULT_SUGGESTIONS);
            return null;
          }
          return current;
        });
      } catch {
        setSessions(prev);
      }
    },
    [sessions],
  );

  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

      // If no AI provider is configured, show an onboarding message instead
      // of hitting the API (which would return a 500 error).
      if (aiConfigured === false) {
        const userMsg: ChatMessage = {
          id: uid(),
          role: 'user',
          content: trimmed,
          ts: new Date(),
        };
        const onboardingMsg: ChatMessage = {
          id: uid(),
          role: 'assistant',
          content:
            '**AI assistant is not configured yet**\n\n' +
            'Connect your AI provider (Anthropic, OpenAI, Google, or another supported provider) in **Settings** to enable the chat assistant.\n\n' +
            'Go to [Settings](/settings) to add your API key.',
          ts: new Date(),
        };
        setMessages((prev) => [...prev, userMsg, onboardingMsg]);
        return;
      }

      const userMsg: ChatMessage = {
        id: uid(),
        role: 'user',
        content: trimmed,
        ts: new Date(),
      };
      const aiMsg: ChatMessage = {
        id: uid(),
        role: 'assistant',
        content: '',
        toolCalls: [],
        ts: new Date(),
      };

      setMessages((prev) => [...prev, userMsg, aiMsg]);
      setIsStreaming(true);
      setSuggestions([]);

      const token = useAuthStore.getState().accessToken;

      const controller = new AbortController();
      abortRef.current = controller;

      const aiMsgId = aiMsg.id;
      // Set once the backend confirms the assistant turn was persisted (the
      // 'done' event carries the DB row id). Preferred signal to refresh the
      // sidebar. Not every provider path includes it though: the fallback
      // provider branch emits an empty 'done' payload, so we also capture the
      // session id (always emitted) as a backstop - by the time the stream
      // finishes the session row is committed, so it is a safe refresh signal.
      let persistedMessageId: string | undefined;
      let streamSessionId: string | undefined;

      (async () => {
        try {
          const response = await fetch('/api/v1/erp_chat/stream/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({
              message: trimmed,
              session_id: sessionId,
              project_id: activeProjectId,
              // Same context as the dock sends: the reply language and the
              // page the question was asked on.
              locale: i18n.language,
              client_context: {
                route: window.location.pathname,
                project_id: activeProjectId ?? null,
              },
            }),
            signal: controller.signal,
          });

          if (!response.ok) {
            const errText = await response.text().catch(() => 'Unknown error');
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId ? { ...m, content: `Error: ${response.status} - ${errText}` } : m,
              ),
            );
            setIsStreaming(false);
            return;
          }

          // A 200 OK is not enough: a misbehaving backend (or a proxy error
          // page) can return HTML/JSON with a 2xx status. The SSE parser would
          // then read garbage, silently drop every frame and leave a blank
          // bubble. Fail fast if the stream is not text/event-stream.
          const contentType = response.headers.get('content-type') ?? '';
          if (!contentType.includes('text/event-stream')) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId
                  ? { ...m, content: 'Error: unexpected response format from the AI service.' }
                  : m,
              ),
            );
            setIsStreaming(false);
            return;
          }

          const reader = response.body?.getReader();
          if (!reader) {
            setIsStreaming(false);
            return;
          }

          const decoder = new TextDecoder();
          let buffer = '';
          // The backend emits standard SSE frames where the event name is on
          // an ``event:`` line and the JSON payload on the following
          // ``data:`` line (see backend _sse()). The previous parser only
          // read ``data:`` and switched on a non-existent ``chunk.type``
          // field, so NOTHING ever rendered. Track the current event name
          // and reset it after each blank-line-delimited frame.
          let currentEvent = '';

          const lastToolCallId = { id: '' };

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            // Keep the last (possibly incomplete) line in the buffer
            buffer = lines.pop() ?? '';

            for (const rawLine of lines) {
              const line = rawLine.replace(/\r$/, '');
              // Blank line terminates an SSE frame — reset the event name.
              if (line.trim() === '') {
                currentEvent = '';
                continue;
              }
              if (line.startsWith('event:')) {
                currentEvent = line.slice(6).trim();
                continue;
              }
              if (!line.startsWith('data:')) continue;

              const jsonStr = line.slice(5).trim();
              if (!jsonStr || jsonStr === '[DONE]') continue;

              let payload: Record<string, unknown>;
              try {
                payload = JSON.parse(jsonStr) as Record<string, unknown>;
              } catch {
                continue;
              }

              switch (currentEvent) {
                case 'session_id': {
                  const sid = payload.session_id as string | undefined;
                  if (sid) {
                    streamSessionId = sid;
                    setSessionId(sid);
                  }
                  break;
                }

                case 'text': {
                  const content = payload.content as string | undefined;
                  if (content) {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === aiMsgId
                          ? { ...m, content: m.content + content }
                          : m,
                      ),
                    );
                  }
                  break;
                }

                case 'tool_start': {
                  const toolName = (payload.tool as string | undefined) ?? 'unknown';
                  const toolCall: ToolCallInfo = {
                    id: uid(),
                    name: toolName,
                    status: 'running',
                    input: payload.args as Record<string, unknown> | undefined,
                    startedAt: Date.now(),
                  };
                  lastToolCallId.id = toolCall.id;
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsgId
                        ? { ...m, toolCalls: [...(m.toolCalls ?? []), toolCall] }
                        : m,
                    ),
                  );
                  break;
                }

                case 'tool_result': {
                  // Backend payload: { tool, result }. There is no per-call
                  // id on the wire, so the most-recently-started running
                  // tool call for this message is the one being resolved
                  // (of the same tool, when the payload names it).
                  const result = payload.result as ToolCallInfo['result'] | undefined;
                  const resultTool = typeof payload.tool === 'string' ? payload.tool : null;
                  // An error result is a failed call, so its card shows the
                  // failure (and, for a proposal, the reason).
                  const status = result?.renderer === 'error' ? ('error' as const) : ('done' as const);
                  setMessages((prev) =>
                    prev.map((m) => {
                      if (m.id !== aiMsgId) return m;
                      const calls = m.toolCalls ?? [];
                      let index = -1;
                      for (let i = calls.length - 1; i >= 0 && index === -1; i -= 1) {
                        const tc = calls[i]!;
                        if (tc.status === 'running' && (!resultTool || tc.name === resultTool)) index = i;
                      }
                      for (let i = calls.length - 1; i >= 0 && index === -1; i -= 1) {
                        if (calls[i]!.status === 'running') index = i;
                      }
                      if (index === -1) return m;
                      const toolCalls = calls.map((tc, i) =>
                        i === index
                          ? { ...tc, status, result, durationMs: Date.now() - tc.startedAt }
                          : tc,
                      );
                      return { ...m, toolCalls };
                    }),
                  );

                  // Add to data panel entries. A proposal is not one: it is
                  // shown as a card in the conversation, with its buttons.
                  const proposal =
                    result?.renderer === 'action_proposal' || (!!resultTool && isProposalTool(resultTool));
                  if (result?.renderer && !proposal) {
                    const entry: DataPanelEntry = {
                      renderer: result.renderer,
                      data: result.data,
                      toolName: (payload.tool as string | undefined) ?? 'unknown',
                      summary: result.summary ?? '',
                      timestamp: Date.now(),
                    };
                    setDataPanelEntries((prev) => [...prev, entry]);
                    setActivePanelIndex((prev) => (prev < 0 ? 0 : prev + 1));
                  }
                  break;
                }

                case 'error': {
                  const errMsg = (payload.message as string | undefined) ?? 'Unknown error';
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsgId
                        ? {
                            ...m,
                            content: m.content + `\n\n**Error:** ${errMsg}`,
                            toolCalls: (m.toolCalls ?? []).map((tc) =>
                              tc.status === 'running'
                                ? { ...tc, status: 'error' as const, durationMs: Date.now() - tc.startedAt }
                                : tc,
                            ),
                          }
                        : m,
                    ),
                  );
                  break;
                }

                case 'done': {
                  // Reconcile the optimistic client bubble id with the
                  // persisted assistant ChatMessage id so thumbs feedback
                  // POSTs against a real row (the backend 404s on a client
                  // UUID, which silently broke the T8 feedback pipeline).
                  const persistedId = payload.message_id as string | undefined;
                  if (persistedId) {
                    persistedMessageId = persistedId;
                    setMessages((prev) =>
                      prev.map((m) => (m.id === aiMsgId ? { ...m, id: persistedId } : m)),
                    );
                  }
                  break;
                }
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof DOMException && err.name === 'AbortError') {
            // User-initiated abort
          } else {
            const errorMsg = err instanceof Error ? err.message : 'Connection failed';
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId
                  ? { ...m, content: m.content || `Error: ${errorMsg}` }
                  : m,
              ),
            );
          }
        } finally {
          setIsStreaming(false);
          abortRef.current = null;
          // A turn just persisted (and possibly created + auto-titled) a
          // session. Refresh the sidebar so the conversation shows up and
          // its title reflects the first prompt. Prefer the persisted message
          // id from the 'done' event, but fall back to the stream's session
          // id: the fallback provider path emits an empty 'done' payload, and
          // by the time this finally runs the stream has closed and the row
          // is committed, so any started conversation still refreshes.
          if (persistedMessageId || streamSessionId) {
            void refreshSessions();
          }
        }
      })();
    },
    [isStreaming, sessionId, activeProjectId, aiConfigured, refreshSessions, i18n],
  );

  const clearChat = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    setMessages([]);
    setIsStreaming(false);
    setSessionId(null);
    setSuggestions(DEFAULT_SUGGESTIONS);
    setDataPanelEntries([]);
    setActivePanelIndex(-1);
  }, []);

  return {
    messages,
    isStreaming,
    sessionId,
    suggestions,
    dataPanelEntries,
    activePanelIndex,
    aiConfigured,
    sessions,
    sessionsTotal,
    sessionsLoading,
    loadingSessionId,
    sendMessage,
    clearChat,
    setActivePanelIndex,
    loadSession,
    removeSession,
    refreshSessions,
  };
}
