// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Trash2, Loader2 } from 'lucide-react';
import clsx from 'clsx';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

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

  // Trap Tab / Shift+Tab inside the dialog and restore focus to the
  // triggering element on close. Without this, Tab walks the focus
  // back into the obscured page underneath — fails WCAG 2.4.3.
  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const isDanger = variant === 'danger';

  const Icon = isDanger ? Trash2 : AlertTriangle;

  return (
    <div className="fixed inset-0 z-modal flex items-end sm:items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px] animate-fade-in" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        aria-describedby="confirm-dialog-message"
        tabIndex={-1}
        className={clsx(
          'relative z-10 w-full sm:max-w-md sm:mx-4',
          'rounded-t-2xl sm:rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-slide-up sm:animate-scale-in',
          'focus:outline-none',
        )}
      >
        {/* Body */}
        <div className="flex items-start gap-3 px-5 pt-5 pb-4">
          <div
            className={clsx(
              'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
              isDanger
                ? 'bg-semantic-error/10 text-semantic-error'
                : 'bg-semantic-warning/10 text-semantic-warning',
            )}
          >
            <Icon size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-content-primary">{title}</h2>
            <p
              id="confirm-dialog-message"
              className="mt-1 text-sm text-content-secondary leading-snug"
            >
              {message}
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border-light bg-surface-secondary/40 px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:rounded-b-2xl">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className={clsx(
              'h-8 rounded-lg px-3',
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
              'h-8 inline-flex items-center justify-center gap-1.5 rounded-lg px-3',
              'text-sm font-medium transition-all',
              'text-content-inverse',
              isDanger
                ? 'bg-semantic-error hover:opacity-90 active:opacity-80'
                : 'bg-semantic-warning hover:opacity-90 active:opacity-80',
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
