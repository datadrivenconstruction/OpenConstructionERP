// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Global reporting for mutations that fail, said once.
 *
 * Every failed mutation used to get a generic "Operation failed" toast from
 * the `MutationCache`, and most screens also report the failure in their own
 * `onError` with words that fit the action ("Failed to add section"). One 409
 * then put two toasts on screen for one click. A screen could opt out with
 * `meta: { suppressGlobalErrorToast: true }`, but only the screens someone
 * remembered to mark did.
 *
 * The cache handler runs before the mutation's own `onError`, and an `onError`
 * passed to `mutate()` runs later still, on the notify scheduler. So the
 * generic toast waits a moment and stays quiet when an error toast was raised
 * in the meantime. A screen that only rolls back and says nothing still gets
 * the generic message.
 */
import { useToastStore } from '@/stores/useToastStore';

/**
 * How long the generic toast waits for the screen to speak first. Long enough
 * for both `onError` hooks and the notify scheduler's `setTimeout(0)`, short
 * enough that nobody reads it as a delay.
 */
export const MUTATION_ERROR_TOAST_DELAY_MS = 60;

/** The parts of a React Query `Mutation` this decision reads. */
export interface FailedMutation {
  meta?: Record<string, unknown>;
}

/**
 * Raise the generic error toast for a failed mutation unless something else
 * reports it.
 *
 * Wired into the `MutationCache` in `main.tsx`.
 */
export function notifyMutationError(error: unknown, mutation: FailedMutation | undefined): void {
  const message = error instanceof Error ? error.message : 'Operation failed';
  const status = (error as { status?: number } | null)?.status;
  const isAuthFailure = status === 401 || status === 403 || message.includes('401');
  if (isAuthFailure || mutation?.meta?.suppressGlobalErrorToast === true) return;

  // History gets an entry for every toast, merged duplicates included, so the
  // newest entry marks where this failure started.
  const store = useToastStore.getState();
  const before = store.history[0]?.id;

  setTimeout(() => {
    const { history, addToast } = useToastStore.getState();
    for (const entry of history) {
      if (entry.id === before) break;
      if (entry.type === 'error') return;
    }
    if (import.meta.env.DEV) console.warn('Mutation error:', message);
    addToast({ type: 'error', title: 'Operation failed', message });
  }, MUTATION_ERROR_TOAST_DELAY_MS);
}
