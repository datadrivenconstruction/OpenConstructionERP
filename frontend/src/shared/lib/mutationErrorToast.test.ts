// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A failed mutation puts one error toast on screen, not two.
 *
 * The first test runs a real `QueryClient` with the handler wired the way
 * `main.tsx` wires it, because the order in which React Query calls the cache
 * handler, the mutation's own `onError` and the `onError` passed to `mutate()`
 * is what the deferral depends on. The rest pin the cases where the generic
 * toast must still appear.
 */
import { MutationCache, QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useToastStore } from '@/stores/useToastStore';

import { MUTATION_ERROR_TOAST_DELAY_MS, notifyMutationError } from './mutationErrorToast';

function conflict(): Error & { status: number } {
  return Object.assign(new Error('Ordinal already in use'), { status: 409 });
}

function client(): QueryClient {
  return new QueryClient({
    defaultOptions: { mutations: { retry: 0 } },
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => notifyMutationError(error, mutation),
    }),
  });
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, MUTATION_ERROR_TOAST_DELAY_MS * 3));
}

function errorTitles(): string[] {
  return useToastStore
    .getState()
    .toasts.filter((t) => t.type === 'error')
    .map((t) => t.title);
}

beforeEach(() => {
  useToastStore.setState({ toasts: [], history: [] });
});

afterEach(() => {
  useToastStore.setState({ toasts: [], history: [] });
});

describe('the global mutation error toast', () => {
  it("stays quiet when the mutation's own onError reports the failure", async () => {
    const qc = client();
    const mutation = qc.getMutationCache().build(qc, {
      mutationFn: () => Promise.reject(conflict()),
      onError: () => {
        useToastStore.getState().addToast({ type: 'error', title: 'Failed to add section' });
      },
    });
    await mutation.execute(undefined).catch(() => undefined);
    await settle();
    expect(errorTitles()).toEqual(['Failed to add section']);
  });

  it('stays quiet when the caller reports it a tick later', async () => {
    notifyMutationError(conflict(), {});
    setTimeout(() => {
      useToastStore.getState().addToast({ type: 'error', title: 'Could not save' });
    }, 0);
    await settle();
    expect(errorTitles()).toEqual(['Could not save']);
  });

  it('speaks when nothing else does', async () => {
    const qc = client();
    const mutation = qc.getMutationCache().build(qc, {
      mutationFn: () => Promise.reject(conflict()),
      // A rollback that says nothing must not swallow the only message.
      onError: () => undefined,
    });
    await mutation.execute(undefined).catch(() => undefined);
    await settle();
    expect(errorTitles()).toEqual(['Operation failed']);
  });

  it('is not silenced by an error toast that was already on screen', async () => {
    useToastStore.getState().addToast({ type: 'error', title: 'Earlier failure' });
    notifyMutationError(conflict(), {});
    await settle();
    expect(errorTitles()).toEqual(['Earlier failure', 'Operation failed']);
  });

  it('is not silenced by a success toast raised meanwhile', async () => {
    notifyMutationError(conflict(), {});
    useToastStore.getState().addToast({ type: 'success', title: 'Saved' });
    await settle();
    expect(errorTitles()).toEqual(['Operation failed']);
  });

  it('honours the opt-out and leaves auth failures to the login flow', async () => {
    notifyMutationError(conflict(), { meta: { suppressGlobalErrorToast: true } });
    notifyMutationError(Object.assign(new Error('Unauthorized'), { status: 401 }), {});
    await settle();
    expect(errorTitles()).toEqual([]);
  });
});
