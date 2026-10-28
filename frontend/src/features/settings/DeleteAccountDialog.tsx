// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2 } from 'lucide-react';
import clsx from 'clsx';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

export interface DeleteAccountDialogProps {
  open: boolean;
  onCancel: () => void;
  onConfirm: (value: string) => void;
  loading?: boolean;
  error?: string | null;
}

/**
 * Confirmation dialog for self-service account erasure (GDPR right to
 * erasure). The single field doubles as the confirmation for both account
 * types: a password account types its current password, a single sign-on
 * account types the literal word DELETE. The caller sends the value as both
 * `current_password` and `confirm`, and the server applies whichever check
 * fits the account, so the dialog never needs to know which kind it is.
 */
export function DeleteAccountDialog({
  open,
  onCancel,
  onConfirm,
  loading = false,
  error,
}: DeleteAccountDialogProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState('');

  // Clear the field and focus it each time the dialog opens.
  useEffect(() => {
    if (open) {
      setValue('');
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return undefined;
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

  // Close on backdrop click.
  useEffect(() => {
    if (!open) return undefined;
    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        onCancel();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onCancel]);

  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const canSubmit = value.trim().length > 0 && !loading;
  const submit = () => {
    if (canSubmit) onConfirm(value.trim());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-label={t('settings.delete_account_title', { defaultValue: 'Delete your account' })}
        tabIndex={-1}
        className={clsx(
          'relative z-10 w-full max-w-md mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in focus:outline-none',
        )}
      >
        <div className="px-6 pt-6 pb-4">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-semantic-error/10 text-semantic-error">
            <AlertTriangle size={20} />
          </div>

          <h2 className="text-center text-base font-semibold text-content-primary">
            {t('settings.delete_account_title', { defaultValue: 'Delete your account' })}
          </h2>

          <p className="mt-2 text-center text-sm leading-relaxed text-content-secondary">
            {t('settings.delete_account_warning', {
              defaultValue:
                'This permanently removes your personal data and signs you out everywhere. Projects and history you created stay in the workspace but are no longer tied to your name. This cannot be undone.',
            })}
          </p>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="mt-4"
          >
            <label
              htmlFor="delete-account-confirm"
              className="mb-1.5 block text-xs font-medium text-content-secondary"
            >
              {t('settings.delete_account_field_label', {
                defaultValue: 'Enter your password to confirm. Single sign-on accounts: type DELETE.',
              })}
            </label>
            <input
              ref={inputRef}
              id="delete-account-confirm"
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
              disabled={loading}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2.5 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-semantic-error/50"
            />
            {error ? <p className="mt-2 text-xs text-semantic-error">{error}</p> : null}
          </form>
        </div>

        <div className="flex gap-3 px-6 pb-6">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className={clsx(
              'flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-all',
              'border border-border bg-surface-primary text-content-primary',
              'hover:bg-surface-secondary active:bg-surface-tertiary',
              'disabled:pointer-events-none disabled:opacity-40',
            )}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            data-testid="delete-account-confirm"
            className={clsx(
              'flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5',
              'text-sm font-medium transition-all text-content-inverse',
              'bg-semantic-error shadow-xs hover:opacity-90 active:opacity-80',
              'disabled:pointer-events-none disabled:opacity-40',
            )}
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : null}
            {t('settings.delete_account_confirm', { defaultValue: 'Delete account' })}
          </button>
        </div>
      </div>
    </div>
  );
}
