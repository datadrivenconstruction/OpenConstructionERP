import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Trash2, Loader2 } from 'lucide-react';
import clsx from 'clsx';

export interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'warning';
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  message,
  confirmLabel,
  cancelLabel,
  variant = 'danger',
  loading = false,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  const resolvedConfirmLabel =
    confirmLabel ?? t('confirm_dialog.delete', { defaultValue: 'Delete' });
  const resolvedCancelLabel =
    cancelLabel ?? t('confirm_dialog.cancel', { defaultValue: 'Cancel' });

  // Close on Escape key
  useEffect(() => {
    if (!open) return;

    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCancel();
      }
    };

    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onCancel]);

  // Close on backdrop click
  useEffect(() => {
    if (!open) return;

    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        onCancel();
      }
    };

    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onCancel]);

  // Focus the confirm button when dialog opens
  useEffect(() => {
    if (open) {
      confirmRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  const isDanger = variant === 'danger';

  const Icon = isDanger ? Trash2 : AlertTriangle;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        aria-describedby="confirm-dialog-message"
        tabIndex={-1}
        className={clsx(
          'relative z-10 w-full max-w-sm mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in',
          'focus:outline-none',
        )}
      >
        {/* Body */}
        <div className="px-6 pt-6 pb-4">
          {/* Icon */}
          <div
            className={clsx(
              'mx-auto flex h-11 w-11 items-center justify-center rounded-full mb-4',
              isDanger
                ? 'bg-semantic-error/10 text-semantic-error'
                : 'bg-semantic-warning/10 text-semantic-warning',
            )}
          >
            <Icon size={20} />
          </div>

          {/* Title */}
          <h2 className="text-base font-semibold text-content-primary text-center">{title}</h2>

          {/* Message */}
          <p
            id="confirm-dialog-message"
            className="mt-2 text-sm text-content-secondary text-center leading-relaxed"
          >
            {message}
          </p>
        </div>

        {/* Actions */}
        <div className="flex gap-3 px-6 pb-6">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className={clsx(
              'flex-1 rounded-lg px-4 py-2.5',
              'text-sm font-medium transition-all',
              'bg-surface-primary text-content-primary',
              'border border-border',
              'hover:bg-surface-secondary active:bg-surface-tertiary',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
              'disabled:opacity-40 disabled:pointer-events-none',
            )}
          >
            {resolvedCancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={loading}
            data-testid="confirm-dialog-confirm"
            className={clsx(
              'flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5',
              'text-sm font-medium transition-all',
              'text-content-inverse',
              isDanger
                ? 'bg-semantic-error hover:opacity-90 active:opacity-80'
                : 'bg-semantic-warning hover:opacity-90 active:opacity-80',
              'shadow-xs hover:shadow-md',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
              isDanger
                ? 'focus-visible:ring-semantic-error'
                : 'focus-visible:ring-semantic-warning',
              'disabled:opacity-40 disabled:pointer-events-none',
            )}
          >
            {loading && <Loader2 size={14} className="animate-spin" />}
            {resolvedConfirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
