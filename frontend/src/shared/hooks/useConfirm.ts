import { useState, useCallback, useRef } from 'react';

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'warning';
}

export interface UseConfirmReturn {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant: 'danger' | 'warning';
  loading: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
  setLoading: (loading: boolean) => void;
}

/**
 * Promise-based confirmation hook.
 *
 * Usage:
 * ```tsx
 * const { confirm, setLoading, ...confirmProps } = useConfirm();
 *
 * async function handleDelete() {
 *   const ok = await confirm({ title: 'Delete?', message: 'Cannot undo.' });
 *   if (ok) {
 *     setLoading(true);
 *     await doDelete();
 *     setLoading(false);
 *   }
 * }
 *
 * return <ConfirmDialog {...confirmProps} />;
 * ```
 */
export function useConfirm(): UseConfirmReturn {
  const [state, setState] = useState({
    open: false,
    title: '',
    message: '',
    confirmLabel: undefined as string | undefined,
    cancelLabel: undefined as string | undefined,
    variant: 'danger' as 'danger' | 'warning',
    loading: false,
  });

  const resolveRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
      setState({
        open: true,
        title: opts.title,
        message: opts.message,
        confirmLabel: opts.confirmLabel,
        cancelLabel: opts.cancelLabel,
        variant: opts.variant ?? 'danger',
        loading: false,
      });
    });
  }, []);

  const onConfirm = useCallback(() => {
    setState((prev) => ({ ...prev, open: false }));
    resolveRef.current?.(true);
    resolveRef.current = null;
  }, []);

  const onCancel = useCallback(() => {
    setState((prev) => ({ ...prev, open: false }));
    resolveRef.current?.(false);
    resolveRef.current = null;
  }, []);

  const setLoading = useCallback((loading: boolean) => {
    setState((prev) => ({ ...prev, loading }));
  }, []);

  return {
    ...state,
    onConfirm,
    onCancel,
    confirm,
    setLoading,
  };
}
