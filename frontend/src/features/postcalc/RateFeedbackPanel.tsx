// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Rate feedback: what closed projects say each cost item should cost.
 *
 * The platform only proposes. Every row carries its sample size and a
 * confidence score, and nothing reaches the company cost database until an
 * estimator presses Confirm on that row (optionally with a rate of their own).
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { formatValue } from '@/shared/lib/numberFormat';
import { useToastStore } from '@/stores/useToastStore';
import {
  confirmRateProposal,
  fetchRateProposals,
  refreshRateProposals,
  rejectRateProposal,
  type RateProposal,
} from './rateFeedbackApi';

const KEY = ['postcalc', 'rate-feedback'];

function fmt(value: string | null, digits = 2): string {
  if (value == null) return '–';
  const n = Number(value);
  return Number.isFinite(n) ? formatValue(n, 'number', { maximumFractionDigits: digits }) : '–';
}

function signed(value: string | null): string {
  if (value == null) return '–';
  const n = Number(value);
  if (!Number.isFinite(n)) return '–';
  return `${n > 0 ? '+' : ''}${fmt(value, 1)}%`;
}

/** Confidence tone: thin or inconsistent samples never look green. */
export function confidenceTone(confidence: string): 'success' | 'warning' | 'error' {
  const c = Number(confidence);
  if (c >= 0.7) return 'success';
  if (c >= 0.3) return 'warning';
  return 'error';
}

function Row({
  p,
  busy,
  onConfirm,
  onReject,
}: {
  p: RateProposal;
  busy: boolean;
  onConfirm: (id: string, rate?: string) => void;
  onReject: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [own, setOwn] = useState('');
  return (
    <tr className="border-t border-border-light align-top" data-testid="rf-row">
      <td className="px-3 py-2">
        <div className="text-xs font-medium text-content-primary">{p.cost_item_code}</div>
        <div className="text-2xs text-content-tertiary">{p.cost_item_description}</div>
        {p.warnings.map((w) => (
          <Badge key={w} variant="warning" size="sm">
            {t(`postcalc.rf.warn_${w.replace('rate_feedback.', '')}`, { defaultValue: w })}
          </Badge>
        ))}
      </td>
      <td className="px-3 py-2 text-right text-xs tabular-nums">
        <div>
          {fmt(p.current_rate)} → <strong>{fmt(p.suggested_rate)}</strong>
        </div>
        <div className="text-2xs text-content-tertiary">
          {signed(p.variance_pct)} / {p.unit}
        </div>
      </td>
      <td className="px-3 py-2 text-right text-xs tabular-nums">
        {p.observed_hours_per_unit == null ? (
          '–'
        ) : (
          <>
            <div>
              {fmt(p.current_hours_per_unit, 3)} → <strong>{fmt(p.observed_hours_per_unit, 3)}</strong>
            </div>
            <div className="text-2xs text-content-tertiary">{signed(p.hours_variance_pct)}</div>
          </>
        )}
      </td>
      <td className="px-3 py-2 text-xs text-content-secondary">
        {t('postcalc.rf.sample', { projects: p.project_count, lines: p.line_count })}
      </td>
      <td className="px-3 py-2">
        <Badge variant={confidenceTone(p.confidence)} size="sm">
          {fmt(String(Number(p.confidence) * 100), 0)}%
        </Badge>
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <input
            type="number"
            min="0"
            step="any"
            value={own}
            onChange={(e) => setOwn(e.target.value)}
            placeholder={t('postcalc.rf.own_rate')}
            aria-label={t('postcalc.rf.own_rate')}
            className="h-8 w-24 rounded-lg border border-border bg-surface-primary px-2 text-xs"
          />
          <Button size="sm" disabled={busy} onClick={() => onConfirm(p.id, own || undefined)}>
            {t('postcalc.rf.confirm')}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onReject(p.id)}>
            {t('postcalc.rf.reject')}
          </Button>
        </div>
      </td>
    </tr>
  );
}

export function RateFeedbackPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const list = useQuery({ queryKey: KEY, queryFn: fetchRateProposals });
  const done = () => qc.invalidateQueries({ queryKey: KEY });
  const fail = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });

  const refresh = useMutation({
    mutationFn: () => refreshRateProposals(),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('postcalc.rf.refreshed', { created: r.created, projects: r.closed_projects }),
      });
      done();
    },
    onError: fail,
  });
  const confirm = useMutation({
    mutationFn: (v: { id: string; rate?: string }) => confirmRateProposal(v.id, v.rate),
    onSuccess: () => {
      addToast({ type: 'success', title: t('postcalc.rf.confirmed') });
      done();
    },
    onError: fail,
  });
  const reject = useMutation({ mutationFn: (id: string) => rejectRateProposal(id), onSuccess: done, onError: fail });
  const busy = confirm.isPending || reject.isPending;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-3xl text-xs text-content-tertiary">{t('postcalc.rf.intro')}</p>
        <Button size="sm" variant="secondary" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          <RefreshCw size={14} className="mr-1.5" />
          {t('postcalc.rf.refresh')}
        </Button>
      </div>
      {list.isLoading && <SkeletonTable rows={5} />}
      {list.isError && <p className="text-xs text-semantic-error">{getErrorMessage(list.error)}</p>}
      {list.data && list.data.length === 0 && (
        <EmptyState title={t('postcalc.rf.empty_title')} description={t('postcalc.rf.empty_desc')} />
      )}
      {list.data && list.data.length > 0 && (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-2xs uppercase text-content-tertiary">
                  <th className="px-3 py-2">{t('postcalc.rf.col_item')}</th>
                  <th className="px-3 py-2 text-right">{t('postcalc.rf.col_rate')}</th>
                  <th className="px-3 py-2 text-right">{t('postcalc.rf.col_hours')}</th>
                  <th className="px-3 py-2">{t('postcalc.rf.col_sample')}</th>
                  <th className="px-3 py-2">{t('postcalc.rf.col_confidence')}</th>
                  <th className="px-3 py-2">{t('postcalc.rf.col_action')}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((p) => (
                  <Row
                    key={p.id}
                    p={p}
                    busy={busy}
                    onConfirm={(id, rate) => confirm.mutate({ id, rate })}
                    onReject={(id) => reject.mutate(id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
