// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Global reporting for queries that fail with nothing left to show.
 *
 * A screen that reads `data ?? []` renders the same empty table whether the
 * list came back empty or the request never came back at all. Mutations have
 * had a global error handler from the start; queries had none, so a backend
 * that is down reads as a project with no data in it, and the user acts on an
 * answer nobody gave them.
 *
 * This handler is deliberately quiet. It reports one case, the server failing
 * to answer while the screen has nothing on it, and stays out of the way
 * everywhere else. Everything it stays out of the way of is listed below with
 * the reason, because the tempting change here is always to report more.
 *
 * Quiet also has to mean *once per thing that went wrong*. The rule this
 * replaced was a single clock for the whole handler: one toast every twelve
 * seconds, whoever the failure came from. That was written for a page firing
 * ten queries at a dead backend, and what it did was hide nine of them and then
 * repeat the tenth every twelve seconds for as long as the reader stayed on the
 * page. An owner opening the sign-in page of a fresh install met the first of
 * those repeats before the page had loaded anything at all - one cause, a
 * server that had not finished starting, announced by forty queries, arriving
 * again and again with no way to answer it. So the unit of silence here is the
 * cause rather than the clock, and a message that does carry a way to ask again.
 */
import i18next from 'i18next';

import { useToastStore } from '@/stores/useToastStore';

import { getErrorMessage } from './api';

/** The parts of a React Query `Query` this decision reads. */
export interface FailedQuery {
  state: { data?: unknown };
  meta?: Record<string, unknown>;
}

/** What the caller wants done about a failure it has just been told about. */
export interface QueryErrorToastOptions {
  /**
   * Ask the failed queries again. `main.tsx` wires this to the QueryClient, so
   * the action on the toast re-runs the requests that produced it instead of
   * reloading the document - a reload throws away the page the reader was on,
   * and on a cold start it also restarts the forty queries that caused this.
   */
  onRetry?: () => void;
}

/**
 * How many distinct causes one session remembers.
 *
 * A bound, not a policy: the map holds one short string per cause and a session
 * that produced sixty-four genuinely different server failures has bigger
 * problems than the memory, but a tab nobody closes for a week must not grow a
 * module-level map without limit. When it is full the oldest cause is forgotten,
 * which is the one least likely to still be on screen.
 */
const MAX_REPORTED_CAUSES = 64;

/**
 * The causes this session has already put on screen, in the order they arrived.
 *
 * Keyed on what makes a failure the same failure - the status and the message a
 * reader would be shown - and not on the query, because forty queries asking a
 * server that is not answering yet produce one fact, and the fact is what this
 * handler reports. Deliberately no expiry: a cause that clears and comes back
 * hours later in the same tab is not announced a second time, which is the
 * trade the twelve-second repeat was on the wrong side of.
 */
const reportedCauses = new Map<string, number>();

/**
 * Forget every reported cause.
 *
 * Called when a sign-in succeeds: whatever the server was doing while it could
 * not answer is over, and the next failure is a new fact about a session that
 * is now working. Exported for the same reason the map is module state - a test
 * that could not clear it would hand its silences to the test after it.
 */
export function resetReportedQueryErrorCauses(): void {
  reportedCauses.clear();
}

/**
 * True when `api.ts` has already put this failure on screen.
 *
 * Timeouts and aborts are toasted at the point they are thrown, on their own
 * throttle. A second message for the same abort is the flood, not a fix.
 */
function isAlreadyReported(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  if ((error as { isTimeout?: boolean }).isTimeout === true) return true;
  return (error as { name?: string }).name === 'AbortError';
}

/**
 * Whether the server said it is still starting rather than that it failed.
 *
 * 503 is what this product answers while it is coming up, with a `Retry-After`
 * beside it. Reading that as a failure tells the reader something went wrong
 * when what happened is that they arrived early, and an error-styled toast on a
 * page that has not loaded yet is how a first boot looks like a broken install.
 */
function isStillStarting(status: unknown): boolean {
  return status === 503;
}

/**
 * Decide whether a failed query deserves a toast, and raise it if so.
 *
 * Wired into the `QueryCache` in `main.tsx`. Opt out per query with
 * `meta: { suppressGlobalErrorToast: true }`, the same key the mutation
 * handler honours.
 */
export function notifyQueryError(
  error: unknown,
  query: FailedQuery,
  options: QueryErrorToastOptions = {},
): void {
  if (query.meta?.suppressGlobalErrorToast === true) return;

  // Something is already on screen. A background refetch failing over live
  // data is not the misleading case: the numbers are real, only older than the
  // user thinks. Interrupting that costs more than it tells them.
  if (query.state.data !== undefined) return;

  if (isAlreadyReported(error)) return;

  // A 4xx is an answer, not a failure to answer, and each one already has a
  // surface: 401 and 403 redirect or land on a permission screen, 404 is
  // rendered as "not found" by the features that ask for things which may be
  // absent, 422 belongs to the form that submitted it, 429 is toasted in
  // `api.ts`. What nobody reports is the server not responding at all, which
  // is 5xx and every failure that carries no status.
  const status = (error as { status?: unknown } | null)?.status;
  if (typeof status === 'number' && status < 500) return;

  const message = getErrorMessage(error);
  const starting = isStillStarting(status);
  // The cause is what a reader would be told, so two failures that would be
  // told apart on screen are told apart here, and two that would not are not.
  const cause = `${typeof status === 'number' ? status : 'none'}:${message}`;

  // Registered before anything is raised, and only for a failure this handler
  // owns: a skip above must not spend a cause's one message, or one 404 would
  // buy silence for the 500 behind it.
  const reportedAt = reportedCauses.get(cause);
  if (reportedAt !== undefined) return;
  if (reportedCauses.size >= MAX_REPORTED_CAUSES) {
    const oldest = reportedCauses.keys().next().value;
    if (oldest !== undefined) reportedCauses.delete(oldest);
  }
  reportedCauses.set(cause, Date.now());

  if (import.meta.env.DEV) console.warn('Query error:', message);
  const { onRetry } = options;
  useToastStore.getState().addToast({
    type: starting ? 'info' : 'error',
    title: starting
      ? i18next.t('errors.query_server_starting_title', { defaultValue: 'Still starting up' })
      : i18next.t('errors.query_failed_title', { defaultValue: 'Could not load data' }),
    message,
    // Only when the caller can actually re-ask. An action that does nothing is
    // worse than no action: it is a control that lies.
    ...(onRetry
      ? {
          action: {
            label: i18next.t('common.retry', { defaultValue: 'Retry' }),
            onClick: onRetry,
          },
        }
      : {}),
  });
}
