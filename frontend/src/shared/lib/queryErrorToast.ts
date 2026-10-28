// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
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
 */
import i18next from 'i18next';

import { useToastStore } from '@/stores/useToastStore';

import { getErrorMessage } from './api';

/**
 * Matches the timeout throttle in `api.ts` on purpose: both toasts land on the
 * same screen, and a page firing ten queries against a dead backend has to
 * produce one message, not ten. That flood happened once already.
 */
const QUERY_ERROR_TOAST_THROTTLE_MS = 12_000;

let lastQueryErrorToastAt = 0;

/** The parts of a React Query `Query` this decision reads. */
export interface FailedQuery {
  state: { data?: unknown };
  meta?: Record<string, unknown>;
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
 * Decide whether a failed query deserves a toast, and raise it if so.
 *
 * Wired into the `QueryCache` in `main.tsx`. Opt out per query with
 * `meta: { suppressGlobalErrorToast: true }`, the same key the mutation
 * handler honours.
 */
export function notifyQueryError(error: unknown, query: FailedQuery): void {
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

  const now = Date.now();
  if (now - lastQueryErrorToastAt <= QUERY_ERROR_TOAST_THROTTLE_MS) return;
  lastQueryErrorToastAt = now;

  const message = getErrorMessage(error);
  if (import.meta.env.DEV) console.warn('Query error:', message);
  useToastStore.getState().addToast({
    type: 'error',
    title: i18next.t('errors.query_failed_title', { defaultValue: 'Could not load data' }),
    message,
  });
}
