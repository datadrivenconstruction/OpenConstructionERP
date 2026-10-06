// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import i18next from 'i18next';

/** Opt-in for a single heavy request, including reading its response body.
 * Cancels only the browser wait; it does not promise server-side rollback.
 * Caller cancellation and the deadline both remain effective. No replay.
 */
export async function withLongRunningDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  callerSignal?: AbortSignal | null,
): Promise<T> {
  if (callerSignal?.aborted) throw callerSignal.reason;
  const controller = new AbortController();
  const cancel = () => controller.abort(callerSignal?.reason);
  callerSignal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(() => {
    const fallback = 'The request took too long and was cancelled. Please try again.';
    const error = new Error(i18next.t('errors.timeout', { defaultValue: fallback }) || fallback);
    error.name = 'TimeoutError';
    controller.abort(error);
  }, 300_000);
  try {
    return await operation(controller.signal);
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', cancel);
  }
}
