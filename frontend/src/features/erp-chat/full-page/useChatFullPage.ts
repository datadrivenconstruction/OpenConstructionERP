import { useState, useCallback, useRef } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import type { ChatMessage, ChatStreamChunk, DataPanelEntry, ToolCallInfo } from '../types';

const DEFAULT_SUGGESTIONS = [
  'Show all projects',
  'BOQ overview for this project',
  'Run validation',
  'Risk overview',
  'Search CWICR database',
];

function uid(): string {
  return crypto.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export interface UseChatFullPageReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  sessionId: string | null;
  suggestions: string[];
  dataPanelEntries: DataPanelEntry[];
  activePanelIndex: number;
  sendMessage: (text: string) => void;
  clearChat: () => void;
  setActivePanelIndex: (idx: number) => void;
}

export function useChatFullPage(): UseChatFullPageReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_SUGGESTIONS);
  const [dataPanelEntries, setDataPanelEntries] = useState<DataPanelEntry[]>([]);
  const [activePanelIndex, setActivePanelIndex] = useState(-1);

  const abortRef = useRef<AbortController | null>(null);

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

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

          const reader = response.body?.getReader();
          if (!reader) {
            setIsStreaming(false);
            return;
          }

          const decoder = new TextDecoder();
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            // Keep the last (possibly incomplete) line in the buffer
            buffer = lines.pop() ?? '';

            for (const line of lines) {
              const trimmedLine = line.trim();
              if (!trimmedLine || !trimmedLine.startsWith('data: ')) continue;

              const jsonStr = trimmedLine.slice(6);
              if (jsonStr === '[DONE]') continue;

              let chunk: ChatStreamChunk;
              try {
                chunk = JSON.parse(jsonStr) as ChatStreamChunk;
              } catch {
                continue;
              }

              switch (chunk.type) {
                case 'stream_start': {
                  if (chunk.session_id) {
                    setSessionId(chunk.session_id);
                  }
                  break;
                }

                case 'text': {
                  if (chunk.content) {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === aiMsgId
                          ? { ...m, content: m.content + chunk.content }
                          : m,
                      ),
                    );
                  }
                  break;
                }

                case 'tool_start': {
                  const toolCall: ToolCallInfo = {
                    id: chunk.tool_call_id ?? uid(),
                    name: chunk.tool_name ?? 'unknown',
                    status: 'running',
                    input: chunk.tool_input as Record<string, unknown> | undefined,
                    startedAt: Date.now(),
                  };
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
                  const toolCallId = chunk.tool_call_id;
                  setMessages((prev) =>
                    prev.map((m) => {
                      if (m.id !== aiMsgId) return m;
                      return {
                        ...m,
                        toolCalls: (m.toolCalls ?? []).map((tc) =>
                          tc.id === toolCallId
                            ? {
                                ...tc,
                                status: 'done' as const,
                                result: chunk.result as ToolCallInfo['result'],
                                durationMs: Date.now() - tc.startedAt,
                              }
                            : tc,
                        ),
                      };
                    }),
                  );

                  // Add to data panel entries
                  if (chunk.result?.renderer) {
                    const entry: DataPanelEntry = {
                      renderer: chunk.result.renderer as string,
                      data: chunk.result.data,
                      toolName: chunk.tool_name ?? 'unknown',
                      summary: (chunk.result.summary as string) ?? '',
                      timestamp: Date.now(),
                    };
                    setDataPanelEntries((prev) => [...prev, entry]);
                    setActivePanelIndex((prev) =>
                      prev < 0 ? 0 : prev + 1,
                    );
                  }
                  break;
                }

                case 'error': {
                  const errMsg = chunk.message ?? 'Unknown error';
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
        }
      })();
    },
    [isStreaming, sessionId, activeProjectId],
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
    sendMessage,
    clearChat,
    setActivePanelIndex,
  };
}
