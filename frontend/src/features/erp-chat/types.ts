// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  toolCalls?: ToolCallInfo[];
  ts: Date;
  /**
   * Friendly error description attached to an assistant message when the
   * SSE stream returned an error or a 4xx/5xx response. When present, the
   * UI renders the {@link ErrorCard} INSTEAD of letting the raw text bubble
   * up as plain content.
   *
   * `lastUserPrompt` is captured so the Retry button can resend exactly
   * what the user typed without making them re-enter it.
   */
  errorText?: string;
  /**
   * Optional i18n key carried by the server-side error payload (e.g.
   * ``"chat.error.manager_required"``). When set, the {@link ErrorCard}
   * renders the localized message instead of ``errorText`` AND suppresses
   * the Retry CTA — retrying a permission-denied call would just fail
   * again, so we replace it with a non-retryable variant.
   */
  errorI18nKey?: string;
  lastUserPrompt?: string;
}

export interface ToolCallInfo {
  id: string;
  name: string;
  status: 'running' | 'done' | 'error';
  input?: Record<string, unknown>;
  result?: { renderer?: string; data?: unknown; summary?: string };
  startedAt: number;
  durationMs?: number;
}

export interface ChatStreamChunk {
  type: 'text' | 'tool_start' | 'tool_result' | 'error' | 'done' | 'stream_start';
  content?: string;
  tool_name?: string;
  tool_call_id?: string;
  tool_input?: Record<string, unknown>;
  result?: { renderer?: string; data?: unknown; summary?: string };
  message?: string;
  session_id?: string;
}

export interface DataPanelEntry {
  renderer: string;
  data: unknown;
  toolName: string;
  summary: string;
  timestamp: number;
}

export interface ChatSession {
  id: string;
  project_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
}

// ── T8: thumbs feedback + admin observability ────────────────────────────

export interface FeedbackResponse {
  id: string;
  message_id: string;
  user_id: string | null;
  rating: -1 | 1;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface DailyChatStat {
  date: string;
  messages: number;
  thumbs_up: number;
  thumbs_down: number;
  tokens: number;
}

export interface NegativePromptSnippet {
  snippet: string;
  thumbs_down: number;
  message_id: string | null;
}

export interface AdminStats {
  window_days: number;
  total_messages: number;
  total_thumbs_up: number;
  total_thumbs_down: number;
  feedback_rate_pct: number;
  total_tokens_input: number;
  total_tokens_output: number;
  cache_hit_rate_pct: number;
  top_negative_prompts: NegativePromptSnippet[];
  daily_breakdown: DailyChatStat[];
}
