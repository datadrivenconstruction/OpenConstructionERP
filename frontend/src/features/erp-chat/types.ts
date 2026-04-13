export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  toolCalls?: ToolCallInfo[];
  ts: Date;
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
