/**
 * useLLMRun — shared hook for any AI/LLM-bound async operation in the
 * AI feature module. Replaces ad-hoc `useState + try/catch` patterns
 * (AdvisorPage) and direct `useMutation` blocks (QuickEstimatePage's 5
 * mutations) with one consistent surface.
 *
 * Key wins over a bare `useMutation`:
 *   - First-class `AbortController` — every run is cancellable, and
 *     unmount aborts the in-flight request (no React-act warnings or
 *     ghost toasts after navigation).
 *   - `focusRestoreRef` — optional ref the hook will refocus after the
 *     run resolves (a11y P1 finding #4: SR users should land on the
 *     result region as soon as content arrives).
 *   - Errors are normalised to `Error` so downstream `.message`
 *     access is always safe (matches the existing toast call sites).
 *   - `reset()` semantics match react-query for drop-in compatibility.
 *
 * Design notes:
 *   - Internally backed by `useMutation` so devtools, caching and
 *     `isPending`/`isError` flags keep working unchanged.
 *   - The hook does NOT own UI (toasts, breadcrumbs, focus targets) —
 *     callers pass `onSuccess` / `onError` / `focusRestoreRef`, the
 *     hook just plumbs them.
 *   - `mutationFn` receives `(input, { signal })` so callers can wire
 *     the signal into `fetch` / `apiPost` for true cancellation.
 */
import { useCallback, useEffect, useRef, type RefObject } from 'react';
import { useMutation, type UseMutationResult } from '@tanstack/react-query';

export interface UseLLMRunOptions<TInput, TResult> {
  /**
   * The async operation. Receives the caller-supplied input plus a
   * `signal` for cancellation. Implementors should forward `signal`
   * into their HTTP client (`fetch(url, { signal })` or
   * `apiPost(url, body, { signal })`).
   */
  mutationFn: (input: TInput, ctx: { signal: AbortSignal }) => Promise<TResult>;

  /** Called after a successful run, before focus is restored. */
  onSuccess?: (data: TResult, input: TInput) => void;

  /** Called when the run fails (including cancellation). */
  onError?: (error: Error, input: TInput) => void;

  /**
   * Optional ref to a focusable element (typically the result region
   * with `tabIndex={-1}`). The hook will call `.focus()` on it after
   * `onSuccess` resolves — a11y P1 finding #4.
   *
   * Use with caution: only focus elements the user can navigate away
   * from (e.g. tabIndex={-1} containers); don't trap focus.
   */
  focusRestoreRef?: RefObject<HTMLElement | null>;

  /**
   * If true (default), the previous in-flight run is aborted whenever
   * a new `run()` is issued. Mirrors react-query's default behaviour
   * for non-keyed mutations but with a real AbortController.
   */
  abortPrevious?: boolean;
}

export interface UseLLMRunResult<TInput, TResult>
  extends Pick<
    UseMutationResult<TResult, Error, TInput>,
    'data' | 'error' | 'isError' | 'isPending' | 'isSuccess' | 'reset' | 'status'
  > {
  /** Trigger a new run. Equivalent to `mutate()` but with cancellation. */
  run: (input: TInput) => void;
  /** Promise-returning variant — useful for chained workflows. */
  runAsync: (input: TInput) => Promise<TResult>;
  /** Cancel the currently-pending run, if any. */
  cancel: () => void;
}

/**
 * Returns a stable hook surface for a single LLM/AI operation.
 *
 * Example — replace a useState/try-catch advisor handler:
 *
 *   const advisor = useLLMRun({
 *     mutationFn: ({ msg }, { signal }) =>
 *       apiPost('/v1/ai/advisor/chat/', { message: msg }, { signal }),
 *     onSuccess: (data) => setMessages((p) => [...p, ...]),
 *     onError: (err) => addToast({ type: 'error', message: err.message }),
 *   });
 *   advisor.run({ msg: 'hello' });
 */
export function useLLMRun<TInput, TResult>(
  options: UseLLMRunOptions<TInput, TResult>,
): UseLLMRunResult<TInput, TResult> {
  const {
    mutationFn,
    onSuccess,
    onError,
    focusRestoreRef,
    abortPrevious = true,
  } = options;

  // Persist the active controller across renders. We deliberately do
  // NOT put it in state — flipping a controller every run would force
  // a re-render the consumer doesn't care about.
  const controllerRef = useRef<AbortController | null>(null);

  // Abort any in-flight request on unmount so we don't deliver
  // `onSuccess`/`onError` to a vanished component (one of the common
  // root causes of React-act warnings in tests).
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  const mutation = useMutation<TResult, Error, TInput>({
    mutationFn: (input: TInput) => {
      if (abortPrevious) {
        controllerRef.current?.abort();
      }
      const ctrl = new AbortController();
      controllerRef.current = ctrl;
      return mutationFn(input, { signal: ctrl.signal });
    },
    onSuccess: (data, input) => {
      onSuccess?.(data, input);
      // a11y P1 #4: after the mutation resolves and React has had a
      // chance to mount the new content, refocus the result region so
      // SR users land on the new content rather than the form.
      if (focusRestoreRef?.current) {
        requestAnimationFrame(() => {
          focusRestoreRef.current?.focus();
        });
      }
    },
    onError: (error, input) => {
      // Normalise to Error so downstream `.message` access never
      // crashes. react-query already guarantees `Error` for typed
      // mutations, but cancellation can surface DOMException.
      const normalised =
        error instanceof Error ? error : new Error(String(error));
      onError?.(normalised, input);
    },
    onSettled: () => {
      // Drop the controller once the run is done; a stale reference
      // would only matter on unmount-during-flight which we already
      // handle above.
      controllerRef.current = null;
    },
  });

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  const run = useCallback(
    (input: TInput) => {
      mutation.mutate(input);
    },
    [mutation],
  );

  const runAsync = useCallback(
    (input: TInput) => mutation.mutateAsync(input),
    [mutation],
  );

  return {
    run,
    runAsync,
    cancel,
    data: mutation.data,
    error: mutation.error,
    isError: mutation.isError,
    isPending: mutation.isPending,
    isSuccess: mutation.isSuccess,
    reset: mutation.reset,
    status: mutation.status,
  };
}
