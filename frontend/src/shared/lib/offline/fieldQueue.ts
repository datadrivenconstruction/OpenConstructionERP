// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field mutation queue wiring — the concrete `MutationQueue` instance the field
 * shell uses, plus the HTTP sender that maps a replay response to a
 * `ReplayOutcome`.
 *
 * The sender is deliberately small and transport-explicit: it does NOT pull in
 * the desktop API client (`shared/lib/api.ts`), which attaches a JWT from
 * `useAuthStore`. The field worker has no JWT; the field session token + PIN are
 * attached here via the headers callback the caller supplies. This is the gap
 * the design doc calls out: the desktop `replayMutations` uses the JWT and so
 * cannot drain field writes.
 */

import {
  MutationQueue,
  createIndexedDbQueueStorage,
  createMemoryQueueStorage,
  type OpSender,
  type QueuedOp,
  type ReplayOutcome,
  type QueueStorage,
} from './mutationQueue';

/** Supplies the auth headers for a field replay request (session token + PIN). */
export type FieldHeadersProvider = () => Record<string, string>;

/**
 * Map an HTTP status to a replay outcome.
 *
 *  - 2xx               -> applied (read `result_id` from the body when present)
 *  - 409               -> conflict (server already has an equivalent row)
 *  - 4xx (not 409)     -> rejected (permanent; stop retrying)
 *  - 5xx / network     -> retry (transient)
 */
async function outcomeFromResponse(res: Response): Promise<ReplayOutcome> {
  if (res.ok) {
    let resultId: string | null = null;
    try {
      const data = (await res.clone().json()) as { result_id?: string; id?: string } | null;
      resultId = data?.result_id ?? data?.id ?? null;
    } catch {
      /* empty / non-JSON body is fine */
    }
    return { kind: 'applied', httpStatus: res.status, resultId };
  }
  if (res.status === 409) {
    return { kind: 'conflict', httpStatus: res.status, detail: await safeDetail(res) };
  }
  if (res.status >= 400 && res.status < 500) {
    return { kind: 'rejected', httpStatus: res.status, detail: await safeDetail(res) };
  }
  // 5xx and anything else: transient.
  return { kind: 'retry', httpStatus: res.status };
}

async function safeDetail(res: Response): Promise<string | undefined> {
  try {
    const data = (await res.clone().json()) as { detail?: unknown } | null;
    if (data && typeof data.detail === 'string') return data.detail;
  } catch {
    /* ignore */
  }
  return undefined;
}

/**
 * Build the HTTP sender for the field queue. The op's `clientOpId` is forwarded
 * both in the JSON body (the server dedups on it) and as a header for transports
 * that strip the body, keeping the idempotency guarantee end to end.
 */
export function createFieldSender(getHeaders: FieldHeadersProvider): OpSender {
  return async (op: QueuedOp): Promise<ReplayOutcome> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Client-Op-Id': op.clientOpId,
      ...getHeaders(),
    };
    const body =
      op.body === undefined
        ? undefined
        : JSON.stringify({ ...(op.body as Record<string, unknown>), client_op_id: op.clientOpId });
    const res = await fetch(`/api${op.path}`, { method: op.method, headers, body });
    return outcomeFromResponse(res);
  };
}

/**
 * Pick the best available storage: IndexedDB in the browser, in-memory anywhere
 * it is missing (private mode, SSR, tests that have not polyfilled it). The
 * queue logic is identical either way.
 */
export function pickQueueStorage(): QueueStorage {
  if (typeof indexedDB !== 'undefined') {
    return createIndexedDbQueueStorage();
  }
  return createMemoryQueueStorage();
}

let singleton: MutationQueue | null = null;

/**
 * The process-wide field queue. Created lazily on first use so a test can reset
 * it via `resetFieldQueueForTests`. The sender is rebound on each construction
 * with the supplied headers provider.
 */
export function getFieldQueue(getHeaders: FieldHeadersProvider): MutationQueue {
  if (!singleton) {
    singleton = new MutationQueue(pickQueueStorage(), createFieldSender(getHeaders));
  }
  return singleton;
}

/** Test seam: drop the singleton so the next `getFieldQueue` rebuilds it. */
export function resetFieldQueueForTests(): void {
  singleton = null;
}
