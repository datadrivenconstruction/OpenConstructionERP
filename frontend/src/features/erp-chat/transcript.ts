// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The chat transcript as data: rebuilt from what the server stored, and read
 * for the proposals it carries.
 *
 * `GET /v1/erp_chat/sessions/{id}/messages/` returns one row per stored
 * message. An assistant row keeps the tools it ran twice over: `tool_calls`
 * ([{name, args, id}]) and `tool_results` ([{tool, id, result}], where
 * `result` is the same `{renderer, data, summary}` the stream sent). Rows
 * written before the columns settled may carry a single entry, or an object
 * instead of a list, so both are read. Rows older still have neither and only
 * `renderer` / `renderer_data`.
 *
 * Rebuilt tool calls go through the same renderer registry as live ones, so a
 * proposal from yesterday comes back as a card (which re-reads its status on
 * mount) rather than as text.
 */
import { isChatAction, normalizeChatAction, type ChatAction } from './actions/types';
import type { ChatMessage, ToolCallInfo } from './types';

/** One stored message as the history route returns it. */
export interface PersistedChatMessage {
  id: string;
  session_id?: string;
  role: string;
  content: string | null;
  tool_calls?: unknown;
  tool_results?: unknown;
  renderer?: string | null;
  renderer_data?: unknown;
  created_at: string;
}

type Row = Record<string, unknown>;

function isRecord(v: unknown): v is Row {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null;
}

/** Keys a stored list has been seen wrapped under. */
const LIST_KEYS = ['items', 'calls', 'results', 'tool_calls', 'tool_results'] as const;

/**
 * Stored tool calls or tool results as a list of entries, whatever shape they
 * were stored in: a list, a list wrapped in an object, one bare entry, or an
 * object keyed by call id.
 */
export function persistedEntries(value: unknown): Row[] {
  if (Array.isArray(value)) return value.filter(isRecord);
  if (!isRecord(value)) return [];
  for (const key of LIST_KEYS) {
    const inner = value[key];
    if (Array.isArray(inner)) return inner.filter(isRecord);
  }
  if ('result' in value || 'renderer' in value || 'tool' in value || 'name' in value) return [value];
  return Object.values(value).filter(isRecord);
}

/** The `{renderer, data, summary}` of a stored result entry. */
function resultOf(entry: Row): ToolCallInfo['result'] | undefined {
  const raw = isRecord(entry.result) ? entry.result : str(entry.renderer) ? entry : null;
  if (!raw) return undefined;
  return {
    renderer: str(raw.renderer) ?? undefined,
    data: raw.data,
    summary: str(raw.summary) ?? undefined,
  };
}

/** The tool calls of one stored assistant message, in the order they ran. */
export function toolCallsFromPersisted(row: PersistedChatMessage): ToolCallInfo[] {
  const calls = persistedEntries(row.tool_calls);
  const results = persistedEntries(row.tool_results);
  const out: ToolCallInfo[] = results.map((entry, index) => {
    const callId = str(entry.id) ?? str(entry.tool_id);
    const call = (callId ? calls.find((c) => str(c.id) === callId) : undefined) ?? calls[index];
    const result = resultOf(entry);
    return {
      // Stable across reloads of the same conversation, unique per message.
      id: `${row.id}:${callId ?? index}`,
      name: str(entry.tool) ?? str(entry.tool_name) ?? str(entry.name) ?? str(call?.name) ?? 'tool',
      status: result?.renderer === 'error' ? 'error' : 'done',
      input: isRecord(call?.args) ? call.args : undefined,
      result,
      startedAt: 0,
    };
  });
  // Oldest rows: no per-tool results, only the turn's one renderer.
  const renderer = str(row.renderer);
  if (out.length === 0 && renderer) {
    out.push({
      id: `${row.id}:0`,
      name: str(calls[0]?.name) ?? renderer,
      status: renderer === 'error' ? 'error' : 'done',
      result: { renderer, data: row.renderer_data },
      startedAt: 0,
    });
  }
  return out;
}

/** The rows of a history response, whether a bare list or `{items}`. */
function historyRows(raw: unknown): Row[] {
  if (Array.isArray(raw)) return raw.filter(isRecord);
  if (isRecord(raw) && Array.isArray(raw.items)) return raw.items.filter(isRecord);
  return [];
}

const ROLE_ORDER: Record<string, number> = { user: 0, assistant: 1 };

/**
 * A conversation's messages, oldest first, ready for the transcript. The
 * question and the answer of one turn are written in the same flush and can
 * share a timestamp, so on a tie the question goes first; otherwise the
 * server's order stands.
 */
export function transcriptFromPersisted(raw: unknown): ChatMessage[] {
  const rows = historyRows(raw)
    .filter((r) => r.role === 'user' || r.role === 'assistant')
    .map((row, index) => ({ row, index, time: Date.parse(str(row.created_at) ?? '') }));
  rows.sort((a, b) => {
    const byTime = Number.isFinite(a.time) && Number.isFinite(b.time) ? a.time - b.time : 0;
    if (byTime !== 0) return byTime;
    const byRole = (ROLE_ORDER[String(a.row.role)] ?? 1) - (ROLE_ORDER[String(b.row.role)] ?? 1);
    return byRole !== 0 ? byRole : a.index - b.index;
  });
  const out: ChatMessage[] = [];
  for (const { row, index, time } of rows) {
    const persisted = row as unknown as PersistedChatMessage;
    const role = row.role === 'user' ? 'user' : 'assistant';
    const content = typeof row.content === 'string' ? row.content : '';
    const toolCalls = role === 'assistant' ? toolCallsFromPersisted(persisted) : undefined;
    // An assistant turn with neither words nor tools would render as an empty block.
    if (role === 'assistant' && !content.trim() && (toolCalls?.length ?? 0) === 0) continue;
    out.push({
      id: str(row.id) ?? `history-${index}`,
      role,
      content,
      ts: new Date(Number.isFinite(time) ? time : 0),
      toolCalls,
    });
  }
  return out;
}

// One normalised copy per payload object: the transcript re-renders on every
// streamed chunk, and a fresh copy each time would look like a new proposal
// to every memo and effect keyed on it.
const snapshotCache = new WeakMap<object, ChatAction>();

function snapshotOf(data: ChatAction): ChatAction {
  let snapshot = snapshotCache.get(data);
  if (!snapshot) {
    snapshot = normalizeChatAction(data);
    snapshotCache.set(data, snapshot);
  }
  return snapshot;
}

/**
 * Every proposal the transcript carries, as its tool result delivered it, one
 * per action id (the latest copy wins). The status here is the one at the
 * time of the message; `useLiveChatActions` swaps in the current one.
 */
export function proposalsInTranscript(messages: readonly ChatMessage[]): ChatAction[] {
  const byId = new Map<string, ChatAction>();
  for (const message of messages) {
    for (const call of message.toolCalls ?? []) {
      const result = call.result;
      if (result?.renderer !== 'action_proposal' || !isChatAction(result.data)) continue;
      const snapshot = snapshotOf(result.data);
      byId.delete(snapshot.id);
      byId.set(snapshot.id, snapshot);
    }
  }
  return Array.from(byId.values());
}
