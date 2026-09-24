// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * State and server hooks for the assistant's proposed changes.
 *
 * The same proposal can be on screen twice at once: as a card in the chat
 * transcript and as a row in the Changes tab. Both read it from ONE place, the
 * small store below keyed by action id, so applying it in one view updates the
 * other in the same frame instead of after a refetch.
 *
 * Three rules keep that store honest:
 *
 * - Newer wins. A copy only replaces the stored one when its `updated_at` is
 *   later, so a transcript snapshot from yesterday never overwrites the state a
 *   list fetch brought in a second ago. A mutation result always wins (it is
 *   the server's answer to what this person just did).
 * - One request per action at a time. `pending[id]` is checked before every
 *   request, from whichever view it comes, so a double click or a click in
 *   both views sends one request, not two.
 * - The store is written from effects, query functions and mutation handlers,
 *   never during render.
 *
 * Nothing in this file renders, and the store hooks (`useChatAction`,
 * `useLiveChatActions`, ...) do not need a QueryClient, so a surface can read
 * proposal state without a React Query provider above it.
 */
import { useEffect, useMemo } from 'react';
import { create } from 'zustand';
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import { ApiError } from '@/shared/lib/api';
import {
  applyChatAction,
  applyChatActionsBatch,
  getChatAction,
  listChatActions,
  patchChatAction,
  rejectChatAction,
  revertChatAction,
} from './api';
import { toActionRequestError, type ActionRequestError } from './actionErrors';
import { actionDomain, type ActionOp, type ChatAction, type ChatActionListFilters } from './types';

// ── Query keys ──────────────────────────────────────────────────────────────

export const chatActionKeys = {
  all: ['erp-chat-actions'] as const,
  list: (filters: ChatActionListFilters) => ['erp-chat-actions', filters] as const,
  detail: (id: string) => ['erp-chat-action', id] as const,
};

/**
 * Query roots each domain's screens read, refreshed after a change was written
 * to (or taken back from) that domain. Named from the features' own useQuery
 * calls; a prefix match refreshes every key under the root.
 */
const DOMAIN_QUERY_KEYS: Record<string, readonly string[]> = {
  boq: ['boq', 'boqs', 'all-boqs', 'boq-activity', 'boq-cost-breakdown', 'boq-resource-summary'],
  task: ['tasks'],
  tasks: ['tasks'],
  rfi: ['rfi', 'rfis', 'rfi-stats'],
  risk: ['risks', 'risk', 'risk-summary', 'risk-matrix'],
  risks: ['risks', 'risk', 'risk-summary', 'risk-matrix'],
  punch: ['punchlist', 'punchlist-summary'],
  punchlist: ['punchlist', 'punchlist-summary'],
  schedule: ['schedule', 'schedules', 'gantt'],
};

/** Every write lands in the project's audit trail, whatever the domain. */
const AUDIT_QUERY_KEYS: readonly string[] = ['timeline', 'activity-feed'];

/** Query roots to refresh after an action of this type changed the project. */
export function domainQueryKeys(actionType: string): string[][] {
  const roots = DOMAIN_QUERY_KEYS[actionDomain(actionType)] ?? [];
  return [...roots, ...AUDIT_QUERY_KEYS].map((root) => [root]);
}

// ── Store ───────────────────────────────────────────────────────────────────

function isNewer(incoming: ChatAction, existing: ChatAction): boolean {
  const a = Date.parse(incoming.updated_at);
  const b = Date.parse(existing.updated_at);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return incoming.updated_at !== existing.updated_at;
  return a > b;
}

export interface ChatActionStoreState {
  byId: Record<string, ChatAction>;
  /** The request in flight per action; at most one. */
  pending: Record<string, ActionOp>;
  /** The last refused request per action, cleared when the next one starts. */
  errors: Record<string, ActionRequestError>;
  /** Store a copy. Without `force`, only a newer copy replaces a stored one. */
  upsert: (action: ChatAction, opts?: { force?: boolean }) => void;
  upsertMany: (actions: readonly ChatAction[], opts?: { force?: boolean }) => void;
  setPending: (ids: readonly string[], op: ActionOp | null) => void;
  setError: (ids: readonly string[], error: ActionRequestError | null) => void;
  reset: () => void;
}

export const useChatActionStore = create<ChatActionStoreState>((set) => ({
  byId: {},
  pending: {},
  errors: {},
  upsert: (action, opts) => {
    set((state) => {
      const existing = state.byId[action.id];
      if (existing && !opts?.force && !isNewer(action, existing)) return state;
      return { byId: { ...state.byId, [action.id]: action } };
    });
  },
  upsertMany: (actions, opts) => {
    set((state) => {
      let next: Record<string, ChatAction> | null = null;
      for (const action of actions) {
        const existing = (next ?? state.byId)[action.id];
        if (existing && !opts?.force && !isNewer(action, existing)) continue;
        next = next ?? { ...state.byId };
        next[action.id] = action;
      }
      return next ? { byId: next } : state;
    });
  },
  setPending: (ids, op) => {
    set((state) => {
      const pending = { ...state.pending };
      for (const id of ids) {
        if (op) pending[id] = op;
        else delete pending[id];
      }
      return { pending };
    });
  },
  setError: (ids, error) => {
    set((state) => {
      if (!error && ids.every((id) => !(id in state.errors))) return state;
      const errors = { ...state.errors };
      for (const id of ids) {
        if (error) errors[id] = error;
        else delete errors[id];
      }
      return { errors };
    });
  },
  reset: () => set({ byId: {}, pending: {}, errors: {} }),
}));

/** The stored copy of an action, or undefined when none was seen yet. */
export function useChatAction(id: string | null | undefined): ChatAction | undefined {
  return useChatActionStore((s) => (id ? s.byId[id] : undefined));
}

/**
 * The freshest known copy of an action: the stored one when there is one,
 * else `snapshot`. The snapshot is put into the store after render.
 */
export function useChatActionView(snapshot: ChatAction): ChatAction {
  const stored = useChatActionStore((s) => s.byId[snapshot.id]);
  useEffect(() => {
    useChatActionStore.getState().upsert(snapshot);
  }, [snapshot]);
  return stored ?? snapshot;
}

/**
 * Map a list of snapshots (for example, every proposal in the current
 * conversation) to their freshest known copies. Needs no QueryClient.
 */
export function useLiveChatActions(snapshots: readonly ChatAction[]): ChatAction[] {
  const byId = useChatActionStore((s) => s.byId);
  useEffect(() => {
    if (snapshots.length > 0) useChatActionStore.getState().upsertMany(snapshots);
  }, [snapshots]);
  return useMemo(() => snapshots.map((s) => byId[s.id] ?? s), [snapshots, byId]);
}

/** The request in flight for an action, or null. */
export function useActionPending(id: string): ActionOp | null {
  return useChatActionStore((s) => s.pending[id] ?? null);
}

/** The last refused request for an action, or null. */
export function useActionRequestError(id: string): ActionRequestError | null {
  return useChatActionStore((s) => s.errors[id] ?? null);
}

/** Clear the refused-request message of an action (for a dismiss button). */
export function clearActionRequestError(id: string): void {
  useChatActionStore.getState().setError([id], null);
}

// ── Queries ─────────────────────────────────────────────────────────────────

/** Retry network hiccups and 5xx, never a 4xx the server meant. */
function retryUnlessClientError(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

/** A page of proposals for a filter. Loaded rows are shared through the store. */
export function useChatActionsList(filters: ChatActionListFilters, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: chatActionKeys.list(filters),
    queryFn: async () => {
      const page = await listChatActions(filters);
      useChatActionStore.getState().upsertMany(page.items);
      return page;
    },
    enabled: options.enabled ?? true,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    retry: retryUnlessClientError,
  });
}

/**
 * One proposal from the server. With `initialData` it renders at once and only
 * re-reads when that copy is older than 15 s, so a card that just streamed in
 * costs no request while one reloaded from yesterday's history is refreshed.
 */
export function useChatActionDetail(
  id: string,
  options: { enabled?: boolean; initialData?: ChatAction } = {},
) {
  const { initialData } = options;
  const initialAt = initialData ? Date.parse(initialData.updated_at) : NaN;
  return useQuery({
    queryKey: chatActionKeys.detail(id),
    queryFn: async () => {
      const action = await getChatAction(id);
      useChatActionStore.getState().upsert(action);
      return action;
    },
    enabled: (options.enabled ?? true) && id.length > 0,
    initialData,
    initialDataUpdatedAt: Number.isFinite(initialAt) ? initialAt : undefined,
    staleTime: 15_000,
    retry: retryUnlessClientError,
  });
}

// ── Mutations ───────────────────────────────────────────────────────────────

function wroteToProject(op: ActionOp, result: ChatAction): boolean {
  return (op === 'apply' && result.status === 'applied') || (op === 'revert' && result.status === 'reverted');
}

function refreshAfterWrite(qc: QueryClient, results: readonly ChatAction[], op: ActionOp): void {
  void qc.invalidateQueries({ queryKey: chatActionKeys.all });
  const seen = new Set<string>();
  for (const result of results) {
    if (!wroteToProject(op, result)) continue;
    for (const key of domainQueryKeys(result.action_type)) {
      const root = key[0] ?? '';
      if (seen.has(root)) continue;
      seen.add(root);
      void qc.invalidateQueries({ queryKey: key });
    }
  }
}

/** After a conflict the card shows the server's truth, not our guess. */
async function refreshAfterConflict(qc: QueryClient, id: string): Promise<void> {
  try {
    const fresh = await getChatAction(id);
    useChatActionStore.getState().upsert(fresh, { force: true });
    qc.setQueryData(chatActionKeys.detail(id), fresh);
  } catch {
    // The action may no longer be visible to this person; the message stays.
  }
  void qc.invalidateQueries({ queryKey: chatActionKeys.all });
}

/**
 * Run one request on one action with the shared guards. Resolves to null when
 * another request on the same action is already in flight (nothing is sent).
 * A refused request is recorded in the store and re-thrown.
 */
export async function performActionOp(
  qc: QueryClient,
  id: string,
  op: ActionOp,
  call: () => Promise<ChatAction>,
): Promise<ChatAction | null> {
  const store = useChatActionStore.getState();
  if (store.pending[id]) return null;
  store.setPending([id], op);
  store.setError([id], null);
  try {
    const result = await call();
    useChatActionStore.getState().upsert(result, { force: true });
    qc.setQueryData(chatActionKeys.detail(id), result);
    refreshAfterWrite(qc, [result], op);
    return result;
  } catch (err) {
    const info = toActionRequestError(err, op);
    useChatActionStore.getState().setError([id], info);
    if (info.status === 409 || info.status === 404) void refreshAfterConflict(qc, id);
    throw err;
  } finally {
    useChatActionStore.getState().setPending([id], null);
  }
}

/** Most ids the server takes in one apply-batch request (ChatActionBatchRequest). */
export const BATCH_APPLY_LIMIT = 50;

/**
 * Apply several actions at once; ids with a request in flight are skipped.
 * More than BATCH_APPLY_LIMIT ids go out as consecutive requests. Resolves to
 * every action the server returned; rejects only when no request got through.
 */
export async function performBatchApply(qc: QueryClient, ids: readonly string[]): Promise<ChatAction[]> {
  const store = useChatActionStore.getState();
  const free = Array.from(new Set(ids)).filter((id) => !store.pending[id]);
  if (free.length === 0) return [];
  store.setPending(free, 'apply');
  store.setError(free, null);
  const returned: ChatAction[] = [];
  let failedChunks = 0;
  let lastError: unknown = null;
  let chunkCount = 0;
  for (let start = 0; start < free.length; start += BATCH_APPLY_LIMIT) {
    const chunk = free.slice(start, start + BATCH_APPLY_LIMIT);
    chunkCount += 1;
    try {
      const { items, errors } = await applyChatActionsBatch(chunk);
      useChatActionStore.getState().upsertMany(items, { force: true });
      for (const item of items) qc.setQueryData(chatActionKeys.detail(item.id), item);
      // A refused id keeps its card and says why, exactly as a single apply would.
      for (const e of errors ?? []) {
        useChatActionStore.getState().setError([e.id], {
          op: 'apply',
          status: e.status_code,
          code: e.code,
          messageKey: e.message_key,
          params: {},
          fieldErrors: {},
          serverMessage: e.message || null,
        });
        if (e.status_code === 409 || e.status_code === 404) void refreshAfterConflict(qc, e.id);
      }
      returned.push(...items);
    } catch (err) {
      failedChunks += 1;
      lastError = err;
      useChatActionStore.getState().setError(chunk, toActionRequestError(err, 'apply'));
    } finally {
      useChatActionStore.getState().setPending(chunk, null);
    }
  }
  refreshAfterWrite(qc, returned, 'apply');
  if (failedChunks === chunkCount) throw lastError;
  return returned;
}

/**
 * The card and the Changes row say why a write was refused, in their own
 * words, so the app-wide error toast would only repeat it in English.
 */
const INLINE_ERRORS = { suppressGlobalErrorToast: true } as const;

/** Write a proposal to the project. */
export function useApplyChatAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: INLINE_ERRORS,
    mutationFn: (id: string) => performActionOp(qc, id, 'apply', () => applyChatAction(id)),
  });
}

/** Decline a proposal. */
export function useRejectChatAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: INLINE_ERRORS,
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      performActionOp(qc, id, 'reject', () => rejectChatAction(id, note)),
  });
}

/** Save a person's edits to a proposal (changed keys only). */
export function usePatchChatAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: INLINE_ERRORS,
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) =>
      performActionOp(qc, id, 'save', () => patchChatAction(id, payload)),
  });
}

/** Take an applied change back. */
export function useRevertChatAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: INLINE_ERRORS,
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      performActionOp(qc, id, 'revert', () => revertChatAction(id, note)),
  });
}

/** Apply several proposals, each independently. */
export function useApplyChatActionsBatch() {
  const qc = useQueryClient();
  return useMutation({
    meta: INLINE_ERRORS,
    mutationFn: (ids: readonly string[]) => performBatchApply(qc, ids),
  });
}

/** Proposals still waiting for a decision. */
export function pendingActions(actions: readonly ChatAction[]): ChatAction[] {
  return actions.filter((a) => a.status === 'proposed');
}
