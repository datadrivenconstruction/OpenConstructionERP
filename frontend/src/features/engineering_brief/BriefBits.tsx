// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the brief screens share: the field style, a write that reports
// the server's refusal, a form submission that keeps a refusal in its dialog,
// the export buttons and the read-only notice.

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Download, Lock } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { useToastStore } from '@/stores/useToastStore';

import { downloadExport, type Can, type ExportFormat, type ExportWhat } from './api';
import { refusalText, type TFn } from './labels';

export const FIELD_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';

/**
 * A write whose refusal the reader sees in the server's own words. The client
 * does not predict permissions beyond the capability flags it was sent.
 */
export function useBriefAction<TArgs = void, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  onDone?: (result: TResult, args: TArgs) => void,
) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return useMutation({
    mutationFn: fn,
    onSuccess: (result, args) => onDone?.(result, args),
    onError: (err) => addToast({ type: 'error', title: refusalText(t as TFn, err) }),
  });
}

/** One form submission: busy while it runs; a refusal stays in the dialog instead of closing it. */
export function useSubmit(onDone: () => void) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError(refusalText(t as TFn, err));
    } finally {
      setBusy(false);
    }
  };
  const reset = useCallback(() => setError(null), []);
  return { busy, error, setError, run, reset };
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="mr-auto text-xs text-semantic-error" data-testid="brief-form-error">
      {message}
    </p>
  );
}

/** Says why the fields cannot be changed, in the server's reason when it sent one. */
export function ReadOnlyNotice({ edit }: { edit: Can }) {
  const { t } = useTranslation();
  if (edit.allowed) return null;
  return (
    <p
      className="flex items-center gap-2 rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-secondary"
      data-testid="brief-readonly"
    >
      <Lock size={14} aria-hidden />
      {t('engineeringBrief.readonly', {
        defaultValue: 'The brief is locked and cannot be changed in this state.',
      })}
      {edit.reason ? ` (${t(`engineering_brief.errors.${edit.reason}`, { defaultValue: edit.reason.replace(/_/g, ' ') })})` : ''}
    </p>
  );
}

/** PDF and Excel download of one register. */
export function ExportButtons({ projectId, what }: { projectId: string; what: ExportWhat }) {
  const { t } = useTranslation();
  const download = useBriefAction((format: ExportFormat) => downloadExport(projectId, what, format));
  return (
    <div className="flex gap-2" data-testid={`brief-export-${what}`}>
      {(['pdf', 'xlsx'] as ExportFormat[]).map((format) => (
        <Button
          key={format}
          variant="secondary"
          size="sm"
          icon={<Download size={14} />}
          loading={download.isPending && download.variables === format}
          onClick={() => download.mutate(format)}
          data-testid={`brief-export-${what}-${format}`}
        >
          {format === 'pdf'
            ? t('engineeringBrief.export.pdf', { defaultValue: 'PDF' })
            : t('engineeringBrief.export.xlsx', { defaultValue: 'Excel' })}
        </Button>
      ))}
    </div>
  );
}
