// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Live cascade preview for the methodology editor.
//
// The user types sample resource totals (labor / material / machinery / ...)
// and immediately sees how the cascade marks them up: resolved base sets,
// composites, the per-step breakdown, and the direct / markup / grand totals.
// The math is the faithful client mirror of the backend engine
// (cascadeMath.ts), so the preview tracks edits with no network round-trip.
// A "Verify on server" action calls the authoritative backend /compute for the
// same sample totals so the user can confirm the two agree.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, Calculator, ServerCog } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { methodologyApi, toNum } from './api';
import {
  computeCascadePreview,
  resolveBasesFromResourceTotals,
  CascadePreviewError,
  sampleResourceTypes,
  type PreviewResult,
} from './cascadeMath';
import type { ComputeEstimateResponse, MarkupStep } from './types';

interface CascadePreviewProps {
  projectId: string;
  /** The methodology slug to verify against on the server. */
  methodologySlug: string;
  baseMapping: Record<string, string[]>;
  composites: Record<string, string[]>;
  steps: MarkupStep[];
  decimals: number;
  currency: string;
  /** True while the methodology has unsaved edits (server verify would differ). */
  dirty: boolean;
}

const DEFAULT_SAMPLE: Record<string, string> = {
  labor: '10000',
  material: '20000',
  machinery: '5000',
  equipment: '8000',
  subcontractor: '0',
};

export function CascadePreview({
  projectId,
  methodologySlug,
  baseMapping,
  composites,
  steps,
  decimals,
  currency,
  dirty,
}: CascadePreviewProps) {
  const { t } = useTranslation();
  const [sample, setSample] = useState<Record<string, string>>(DEFAULT_SAMPLE);
  const [serverResult, setServerResult] = useState<ComputeEstimateResponse | null>(null);

  const sampleTypes = useMemo(() => sampleResourceTypes(baseMapping), [baseMapping]);
  const resourceTotals = useMemo(() => {
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(sample)) out[k] = toNum(v);
    return out;
  }, [sample]);

  // Faithful client preview. Any structural error (forward reference, unknown
  // token, ...) is surfaced inline so the user fixes the cascade as they edit.
  const { preview, error } = useMemo((): {
    preview: PreviewResult | null;
    error: string | null;
  } => {
    try {
      const bases = resolveBasesFromResourceTotals(baseMapping, resourceTotals);
      return {
        preview: computeCascadePreview({ bases, composites, steps, decimals }),
        error: null,
      };
    } catch (e) {
      if (e instanceof CascadePreviewError) return { preview: null, error: e.message };
      return { preview: null, error: String(e) };
    }
  }, [baseMapping, composites, steps, decimals, resourceTotals]);

  const verifyMut = useMutation({
    mutationFn: () =>
      methodologyApi.compute({
        project_id: projectId,
        methodology_slug: methodologySlug,
        resource_totals: resourceTotals,
      }),
    onSuccess: (res) => setServerResult(res),
  });

  return (
    <div className="space-y-4">
      {/* ── Sample resource totals ──────────────────────────────────────── */}
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('methodology.preview.sample_title', { defaultValue: 'Sample direct costs' })}
        </h4>
        <p className="mt-0.5 text-2xs text-content-tertiary">
          {t('methodology.preview.sample_hint', {
            defaultValue: 'Try amounts per resource type to see how the cascade marks them up.',
          })}
        </p>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {sampleTypes.map((type) => (
            <label key={type} className="flex flex-col gap-1">
              <span className="text-2xs font-medium text-content-secondary">{type}</span>
              <input
                type="text"
                inputMode="decimal"
                value={sample[type] ?? ''}
                onChange={(e) => setSample((p) => ({ ...p, [type]: e.target.value }))}
                className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs tabular-nums text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              />
            </label>
          ))}
        </div>
      </div>

      {error ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2.5"
        >
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-semantic-warning" />
          <div className="min-w-0">
            <p className="text-xs font-medium text-content-primary">
              {t('methodology.preview.invalid', { defaultValue: 'This cascade cannot be computed yet' })}
            </p>
            <p className="mt-0.5 break-words text-2xs text-content-secondary">{error}</p>
          </div>
        </div>
      ) : preview ? (
        <PreviewBreakdown preview={preview} currency={currency} />
      ) : null}

      {/* ── Server verification ─────────────────────────────────────────── */}
      <div className="rounded-lg border border-border-light bg-surface-secondary/20 px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-2xs font-medium text-content-secondary">
            <ServerCog size={13} />
            {t('methodology.preview.server_title', { defaultValue: 'Authoritative server total' })}
          </span>
          <Button
            variant="secondary"
            size="sm"
            icon={<Calculator size={13} />}
            loading={verifyMut.isPending}
            onClick={() => verifyMut.mutate()}
            disabled={!!error}
          >
            {t('methodology.preview.verify', { defaultValue: 'Verify on server' })}
          </Button>
        </div>
        {dirty && (
          <p className="mt-1.5 text-2xs text-content-tertiary">
            {t('methodology.preview.dirty_hint', {
              defaultValue: 'You have unsaved edits - the server computes the last saved version. Save to verify your changes.',
            })}
          </p>
        )}
        {verifyMut.isError && (
          <p className="mt-1.5 text-2xs text-semantic-error">{getErrorMessage(verifyMut.error)}</p>
        )}
        {serverResult && (
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="text-content-secondary">
              {t('methodology.preview.server_grand', { defaultValue: 'Server grand total:' })}{' '}
              <span className="font-semibold text-content-primary">
                <MoneyDisplay amount={serverResult.grand_total} currency={serverResult.currency || currency} />
              </span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function PreviewBreakdown({ preview, currency }: { preview: PreviewResult; currency: string }) {
  const { t } = useTranslation();
  const cur = currency || undefined;
  const baseEntries = Object.entries(preview.bases);
  const compEntries = Object.entries(preview.composites);

  return (
    <div className="space-y-3">
      {/* Resolved base sets */}
      {baseEntries.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {baseEntries.map(([k, v]) => (
            <Badge key={k} variant="neutral" size="sm">
              <span className="font-mono">{k}</span>
              <span className="ml-1 tabular-nums">
                <MoneyDisplay amount={v} currency={cur} compact />
              </span>
            </Badge>
          ))}
          {compEntries.map(([k, v]) => (
            <Badge key={k} variant="blue" size="sm">
              <span className="font-mono">{k}</span>
              <span className="ml-1 tabular-nums">
                <MoneyDisplay amount={v} currency={cur} compact />
              </span>
            </Badge>
          ))}
        </div>
      )}

      {/* Per-step breakdown */}
      <div className="overflow-hidden rounded-lg border border-border-light">
        <table className="min-w-full text-xs">
          <thead className="bg-surface-secondary/40 text-2xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th className="px-2.5 py-1.5 text-left font-medium">
                {t('methodology.preview.col_step', { defaultValue: 'Step' })}
              </th>
              <th className="px-2.5 py-1.5 text-right font-medium">
                {t('methodology.preview.col_rate', { defaultValue: 'Rate' })}
              </th>
              <th className="px-2.5 py-1.5 text-right font-medium">
                {t('methodology.preview.col_amount', { defaultValue: 'Amount' })}
              </th>
              <th className="px-2.5 py-1.5 text-right font-medium">
                {t('methodology.preview.col_running', { defaultValue: 'Running total' })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            <tr className="bg-surface-secondary/20">
              <td className="px-2.5 py-1.5 font-medium text-content-secondary">
                {t('methodology.preview.direct', { defaultValue: 'Direct cost' })}
              </td>
              <td className="px-2.5 py-1.5" />
              <td className="px-2.5 py-1.5" />
              <td className="px-2.5 py-1.5 text-right font-medium tabular-nums text-content-primary">
                <MoneyDisplay amount={preview.directTotal} currency={cur} />
              </td>
            </tr>
            {preview.steps.map((s) => (
              <tr key={s.key}>
                <td className="px-2.5 py-1.5 text-content-primary">
                  {s.label || s.key}
                  {s.category === 'tax' && (
                    <span className="ml-1.5 align-middle">
                      <Badge variant="blue" size="sm">
                        {t('methodology.cascade.steps.vat_badge', { defaultValue: 'VAT' })}
                      </Badge>
                    </span>
                  )}
                </td>
                <td className="px-2.5 py-1.5 text-right tabular-nums text-content-secondary">
                  {s.kind === 'percentage' ? `${s.rate}%` : '-'}
                </td>
                <td className="px-2.5 py-1.5 text-right tabular-nums text-content-secondary">
                  <MoneyDisplay amount={s.amount} currency={cur} />
                </td>
                <td className="px-2.5 py-1.5 text-right tabular-nums text-content-primary">
                  <MoneyDisplay amount={s.runningTotal} currency={cur} />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-border bg-surface-secondary/30">
              <td className="px-2.5 py-2 text-sm font-semibold text-content-primary" colSpan={2}>
                {t('methodology.preview.grand', { defaultValue: 'Grand total' })}
              </td>
              <td className="px-2.5 py-2 text-right text-2xs text-content-tertiary tabular-nums">
                {/* The sign comes from the formatter and the cell may not be
                    broken, so the plus cannot end up on the line above its own
                    figure. Not compacted either: the column this sits under
                    prints its amounts in full. */}
                <span
                  className="whitespace-nowrap"
                  title={t('methodology.preview.markup_total', { defaultValue: 'Total markup' })}
                >
                  <MoneyDisplay amount={preview.markupTotal} currency={cur} signDisplay="always" />
                </span>
              </td>
              <td className="px-2.5 py-2 text-right text-sm font-bold tabular-nums text-content-primary">
                <MoneyDisplay amount={preview.grandTotal} currency={cur} />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
