// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Poll-after-abort fallback for `POST /v1/costs/vector/index/`.
 *
 * Indexing embeds the whole loaded cost catalogue (~55K items per CWICR
 * region, several hundred thousand on a multi-region install) and may spend
 * up to 30s loading the embedding model before it embeds anything. Every call
 * site opts into the 5-min `longRunning` budget, but on a small box even that
 * can run out - and when the client aborts, the server does NOT stop: there is
 * no disconnect cancellation on that handler, so it keeps embedding and
 * commits. Reporting "timed out" for work that actually landed is a lie the
 * user cannot act on (GitHub #436).
 *
 * Same shape as the CWICR region-import fallback in `ImportDatabasePage`
 * (which polls `/v1/costs/regions/stats/` after its own abort): read the
 * count before the write, and if the write aborts, watch the count until the
 * work shows up or the poll budget runs out.
 */

import i18next from 'i18next';

import { apiGet, ApiError, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/** Shape of `GET /v1/costs/vector/status/` that this module reads. */
interface VectorStatusResponse {
  connected?: boolean;
  cost_collection?: { vectors_count?: number } | null;
}

/** Default poll budget: 7 attempts, 10s apart - about a minute, as in the
 *  CWICR region-import fallback this mirrors. */
export const VECTOR_POLL_ATTEMPTS = 7;
export const VECTOR_POLL_INTERVAL_MS = 10_000;

/**
 * Vector count below which the BOQ editor still treats the index as unusable
 * (`vectorReady` there is `vectors_count > 100`). A poll that "succeeds" at 40
 * vectors would show "Vector Database Ready" and then bounce the user straight
 * back into the setup modal on their next AI action.
 */
export const VECTOR_READY_MIN_COUNT = 100;

/**
 * Read the current vector count. Returns `null` when the status endpoint
 * cannot be read or does not report a count - `null` means "unknown", never
 * "zero", because the caller uses it as the baseline of a strict comparison.
 *
 * `suppressTimeoutToast` because this read is silent by construction: it
 * swallows every failure into `null` and reports nothing to the user. Without
 * the flag a slow status read raises the global "Request timed out" banner
 * from inside the very poll that is proving the indexing succeeded - the
 * contradiction this whole fallback exists to remove (GitHub #436).
 */
export async function readVectorCount(): Promise<number | null> {
  try {
    const status = await apiGet<VectorStatusResponse>('/v1/costs/vector/status/', {
      suppressTimeoutToast: true,
    });
    const count = status?.cost_collection?.vectors_count;
    return typeof count === 'number' ? count : null;
  } catch {
    return null;
  }
}

/**
 * Does this error leave the server plausibly still working?
 *
 * Our own client timeout (tagged `isTimeout` in `api.ts`) and a bare
 * `AbortError` both mean we stopped listening, not that the backend stopped.
 * A gateway 502/504 is the reverse-proxy version of the same thing. Anything
 * else (503 "vector backend unavailable", 403, 500) is a real answer from the
 * server and polling for a minute would only delay an honest failure.
 */
export function mayStillBeRunning(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 502 || err.status === 504;
  if (err instanceof Error) {
    if ((err as Error & { isTimeout?: boolean }).isTimeout === true) return true;
    if (err.name === 'AbortError') return true;
  }
  return false;
}

/**
 * Say something true about a background index request that did not return.
 *
 * The auto-index fired after an import is not awaited: the user is already
 * being congratulated on the import by the time it runs. Swallowing its
 * failure (`.catch(() => {})`) is what made GitHub #436 hard to see from the
 * outside - the catalogue lands, the index does not, nothing says so, and the
 * first symptom is that search finds nothing days later.
 *
 * The two directions are different facts and must not share a message:
 *
 * A client abort means WE stopped listening. That endpoint has no disconnect
 * cancellation, so the server is still embedding and will still commit. The
 * wrapper's own "the request took too long and was cancelled" is false about
 * the half the user cares about, which is why these callers suppress it - the
 * honest report is that indexing is running, not that anything was cancelled.
 *
 * Any other error is the server's own answer (503 with no embedder installed
 * is the common one) and means the index will NOT appear. That is the case
 * worth interrupting someone for, and today it is the case that says nothing
 * at all.
 *
 * Reports through the toast store directly rather than a component's `t`, so
 * a five-minute abort still reaches the user on whatever screen they have
 * moved on to - a first-run import is normally followed by leaving the page.
 */
export function reportBackgroundIndexFailure(err: unknown): void {
  const { addToast } = useToastStore.getState();
  if (mayStillBeRunning(err)) {
    addToast({
      type: 'info',
      // Every one of these callers posts the endpoint with no `region`, which
      // indexes the whole loaded catalogue - so this label is literally what
      // the server is still doing at the moment we give up waiting for it.
      title: i18next.t('costs.vec_indexing_all', { defaultValue: 'Generating vectors for all regions...' }),
    });
    return;
  }
  addToast({
    type: 'error',
    title: i18next.t('costs.indexing_failed', { defaultValue: 'Indexing failed' }),
    // The server's own reason. `getErrorMessage` already unwraps a structured
    // `detail`, so a backend that explains itself is quoted rather than
    // flattened into a generic failure.
    message: getErrorMessage(err),
  });
}

/**
 * Client abort budget for `POST /v1/costs/vector/restore-snapshot/{db_id}`,
 * derived from what that handler is allowed to spend server side.
 *
 * The handler downloads the pre-built snapshot with a 600s budget and then
 * hands the file to Qdrant with `timeout_s=1800`, so 2400s is the longest run
 * it can legitimately have. Both halves run off the event loop (an executor
 * for the download, `asyncio.to_thread` for the restore) and neither watches
 * the client, so a browser that stops waiting does not stop the work - which
 * is exactly why a client budget below the server's turned a slow success
 * into a reported failure.
 *
 * Keep this number tied to those two: if the handler's budgets change, this
 * one is wrong the same day.
 */
export const SNAPSHOT_RESTORE_TIMEOUT_MS = 2_400_000; // 600s download + 1800s restore

/** The body `POST /v1/costs/vector/restore-snapshot/{db_id}` returns. */
export interface SnapshotRestoreResponse {
  restored?: boolean;
  collection?: string;
  database?: string;
  vectors_count?: number | null;
  source?: string;
  duration_seconds?: number;
}

/** What the two callers of the restore endpoint need to say about a result. */
export interface SnapshotRestoreOutcome {
  /** `restored` with a real count, `restored_unknown_count` when Qdrant took
   *  the snapshot but would not tell us how many points landed, and
   *  `not_restored` when the body does not claim a restore at all. */
  kind: 'restored' | 'restored_unknown_count' | 'not_restored';
  /** Points in the restored collection. Meaningful only for `restored`. */
  vectors: number;
  /** Server-measured wall time, 0 when the body omits it. */
  duration: number;
}

/**
 * Read a restore response the way the endpoint actually answers.
 *
 * The restore endpoint and the neighbouring `load-github` endpoint report
 * their result in DIFFERENT fields: `load-github` returns `indexed`, restore
 * returns `vectors_count` and no `indexed` at all. Reading `indexed` off a
 * restore body therefore yields `undefined` every single time, and a caller
 * that defaults that to 0 announces "the backend indexed 0 vectors" at the
 * end of a restore that just loaded fifty thousand of them. That is the shape
 * `ModulesPage` shipped, and `ImportDatabasePage` reported one vector for the
 * same reason. Neither field name is wrong; reading one body with the other's
 * field is.
 *
 * Lives here rather than in either page because both pages have to make the
 * same call, and the last time they each made it privately they disagreed.
 */
export function describeSnapshotRestore(data: SnapshotRestoreResponse | undefined): SnapshotRestoreOutcome {
  const duration = typeof data?.duration_seconds === 'number' ? data.duration_seconds : 0;
  const count = data?.vectors_count;
  if (typeof count === 'number' && count > 0) {
    return { kind: 'restored', vectors: count, duration };
  }
  // `vectors_count` comes back null when the collection-info read failed
  // after a restore that itself succeeded, and the handler cannot tell that
  // apart from an empty collection. Neither is a reason to call a restore a
  // failure; the body not claiming `restored` at all is the real negative.
  if (data?.restored === true) {
    return { kind: 'restored_unknown_count', vectors: 0, duration };
  }
  return { kind: 'not_restored', vectors: 0, duration };
}

export interface PollVectorIndexOptions {
  /** Vector count read BEFORE the index request, via {@link readVectorCount}.
   *  `null` (unknown) makes the poll refuse to claim success. */
  baseline: number | null;
  /** Count the result must also exceed, on top of the baseline. */
  minCount?: number;
  /** Keeps the poll from touching state after the view unmounts. */
  isMounted?: () => boolean;
  attempts?: number;
  intervalMs?: number;
  /** Injection seams for tests. */
  readCount?: () => Promise<number | null>;
  sleep?: (ms: number) => Promise<void>;
}

/**
 * Watch the vector count until the aborted index request lands.
 *
 * Returns the observed count on success, or `null` when the work did not show
 * up within the poll budget, when the view unmounted, or when the baseline was
 * unknown. `null` means "cannot prove it worked" - the caller must then report
 * the failure honestly rather than guess.
 */
export async function pollVectorIndexLanded(options: PollVectorIndexOptions): Promise<number | null> {
  const {
    baseline,
    minCount = 0,
    isMounted,
    attempts = VECTOR_POLL_ATTEMPTS,
    intervalMs = VECTOR_POLL_INTERVAL_MS,
    readCount = readVectorCount,
    sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms)),
  } = options;

  // No baseline means no evidence. A count of 55,719 proves nothing if we
  // never learned whether those 55,719 vectors were already there.
  if (baseline === null) return null;

  for (let attempt = 0; attempt < attempts; attempt++) {
    if (isMounted && !isMounted()) return null;
    const count = await readCount();
    if (count !== null && count > baseline && count > minCount) return count;
    if (attempt < attempts - 1) await sleep(intervalMs);
  }
  return null;
}
