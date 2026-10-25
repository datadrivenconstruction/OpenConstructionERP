import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNumberLocale } from '@/stores/usePreferencesStore';
import { isDecimalString } from '@/shared/lib/exactDecimal';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { boqApi } from './api';

export interface ExportEmbeddingPanelProps {
  t: (key: string, options?: Record<string, string | number>) => string;
  boqId: string;
  /** The bill's `metadata.export_embed_markups`. */
  enabled: boolean;
  /** ISO 4217 code of the bill's base currency; the preview amounts are in it. */
  currency?: string;
  readOnly?: boolean;
}

/** A factor with four decimals; the decimal string goes to Intl as is, never through a float. */
function formatFactor(k: string, locale: string): string {
  if (!isDecimalString(k)) return k;
  try {
    return (new Intl.NumberFormat(locale, { minimumFractionDigits: 4, maximumFractionDigits: 4 })
      .format as (v: string) => string)(k);
  } catch {
    return k;
  }
}

/**
 * Export option for sale rates (issue #535): markups folded into every unit
 * rate, only tax left as its own line. The setting lives on the bill, so every
 * format downloads the same way; the stored rates never change.
 */
export function ExportEmbeddingPanel({ t, boqId, enabled, currency, readOnly = false }: ExportEmbeddingPanelProps) {
  const queryClient = useQueryClient();
  const numberLocale = useNumberLocale();
  const preview = useQuery({
    queryKey: ['boq-embedding-preview', boqId],
    queryFn: () => boqApi.embeddingPreview(boqId),
    enabled,
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-embedding-preview', boqId] });
  };
  const toggle = useMutation({
    mutationFn: (next: boolean) => boqApi.update(boqId, { metadata: { export_embed_markups: next } }),
    onSuccess: refresh,
  });
  const lineFlag = useMutation({
    mutationFn: ({ id, include }: { id: string; include: boolean }) =>
      boqApi.updateMarkup(boqId, id, { metadata: { include_in_unit_rates: include } }),
    onSuccess: refresh,
  });
  const tolerance = useMutation({
    mutationFn: (value: string) => boqApi.update(boqId, { metadata: { export_embed_tolerance: value } }),
    onSuccess: refresh,
  });
  const data = preview.data;
  const [toleranceDraft, setToleranceDraft] = useState('');
  useEffect(() => {
    if (data) setToleranceDraft(data.tolerance);
  }, [data?.tolerance]); // eslint-disable-line react-hooks/exhaustive-deps
  const draftValue = toDecimalPayloadString(toleranceDraft, '');
  const draftValid = isDecimalString(draftValue) && !draftValue.startsWith('-');
  const saveTolerance = () => {
    if (data && draftValid && draftValue !== data.tolerance) tolerance.mutate(draftValue);
  };

  return (
    <div className="border-b border-border-light px-3 py-2.5 text-xs" data-testid="export-embedding-panel">
      <label className="flex items-start gap-2 text-sm text-content-primary">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={enabled}
          disabled={readOnly || toggle.isPending}
          onChange={(e) => toggle.mutate(e.target.checked)}
          data-testid="export-embed-toggle"
        />
        <span>
          {t('boq.export_embed_markups', { defaultValue: 'Sale rates: markups in unit rates' })}
          <span className="block text-xs text-content-tertiary">
            {t('boq.export_embed_markups_hint', {
              defaultValue: 'Only tax stays a separate line. The estimate itself is not changed.',
            })}
          </span>
        </span>
      </label>
      {enabled && preview.isLoading && (
        <p className="mt-2 text-content-tertiary">{t('boq.export_embed_loading', { defaultValue: 'Calculating preview...' })}</p>
      )}
      {enabled && preview.isError && (
        <p className="mt-2 text-semantic-error" role="alert">
          {t('boq.export_embed_preview_failed', { defaultValue: 'The preview could not be loaded.' })}
        </p>
      )}
      {enabled && data && (
        <div className="mt-2 space-y-1.5" data-testid="export-embedding-preview">
          {data.markups.length > 0 && (
            <ul className="space-y-0.5">
              {data.markups.map((m) => (
                <li key={m.id}>
                  <label className="flex items-center gap-2 text-content-secondary">
                    <input
                      type="checkbox"
                      checked={m.include_in_unit_rates}
                      disabled={readOnly || lineFlag.isPending}
                      onChange={(e) => lineFlag.mutate({ id: m.id, include: e.target.checked })}
                      aria-label={t('boq.export_embed_line', { defaultValue: 'Include {{name}} in unit rates', name: m.name })}
                    />
                    {m.name}
                  </label>
                </li>
              ))}
            </ul>
          )}
          {data.buckets.map((b, i) => (
            <div key={b.scope_position_ids.join('/') || `bucket-${i}`} className="flex justify-between text-content-secondary">
              <span>
                {b.scope_position_ids.length === 0
                  ? t('boq.export_embed_bucket_bill', { defaultValue: 'Whole bill' })
                  : t('boq.export_embed_bucket_scoped', {
                      defaultValue: 'Scoped section ({{count}} lines)',
                      count: b.position_count,
                    })}
              </span>
              <span className="tabular-nums">k = {formatFactor(b.k, numberLocale)}</span>
            </div>
          ))}
          <div className="flex justify-between text-content-primary">
            <span>{t('boq.export_embed_sale_net', { defaultValue: 'Net at sale rates' })}</span>
            <MoneyDisplay amount={data.sale_net} currency={currency} className="tabular-nums" />
          </div>
          <label className="flex items-center justify-between gap-2 text-content-secondary">
            <span>{t('boq.export_embed_tolerance', { defaultValue: 'Rounding tolerance' })}</span>
            <input
              type="text"
              inputMode="decimal"
              className={`w-24 rounded border px-1.5 py-0.5 text-right tabular-nums ${draftValid ? 'border-border-light' : 'border-semantic-error'}`}
              value={toleranceDraft}
              disabled={readOnly || tolerance.isPending}
              onChange={(e) => setToleranceDraft(e.target.value)}
              onBlur={saveTolerance}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveTolerance();
              }}
              aria-invalid={!draftValid}
              data-testid="export-embed-tolerance"
            />
          </label>
          <div
            className={`flex justify-between ${data.within_tolerance ? 'text-content-secondary' : 'text-semantic-warning'}`}
            data-testid="export-embedding-gap"
          >
            <span>{t('boq.export_embed_gap', { defaultValue: 'Rounding gap vs. editor' })}</span>
            <MoneyDisplay amount={data.rounding_gap} currency={currency} className="tabular-nums" />
          </div>
          {!data.within_tolerance && (
            <p className="text-semantic-warning" role="status">
              {t('boq.export_embed_gap_warning', {
                defaultValue: 'The gap is above the tolerance of {{tolerance}}.',
                tolerance: data.tolerance,
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
