// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Read-only snapshot panels for the Version History drawer: View one
 * snapshot as a bill, or Compare two through the existing
 * `snapshots/compare` endpoint. Neither calls restore; the current bill is
 * left exactly as it is.
 */
import { useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Eye, GitCompare, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { boqApi } from './api';
import { snapshotDiffRows, snapshotPreview } from './revisionHelpers';
import { getNumberLocale } from '@/stores/usePreferencesStore';

function fmt(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString(getNumberLocale(), { maximumFractionDigits: digits });
}

function BackBar({ title, onBack, icon }: { title: string; onBack: () => void; icon: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
      <button
        type="button"
        onClick={onBack}
        className="flex h-7 items-center gap-1 rounded-md px-2 text-xs text-content-secondary hover:bg-surface-secondary"
      >
        <ArrowLeft size={12} />
        {t('common.back', { defaultValue: 'Back' })}
      </button>
      {icon}
      <span className="truncate text-xs font-medium text-content-primary">{title}</span>
    </div>
  );
}

export function SnapshotPreviewPanel({
  boqId,
  snapshotId,
  title,
  onBack,
}: {
  boqId: string;
  snapshotId: string;
  title: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['boq-snapshot', boqId, snapshotId],
    queryFn: () => boqApi.getSnapshot(boqId, snapshotId),
  });
  const view = useMemo(() => snapshotPreview(data?.snapshot_data), [data]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <BackBar title={title} onBack={onBack} icon={<Eye size={12} className="text-oe-blue" />} />
      <p className="border-b border-border bg-surface-secondary/40 px-4 py-1.5 text-2xs text-content-tertiary">
        {t('boq.snapshot_view_hint', { defaultValue: 'Read-only view. The current bill is not changed.' })}
      </p>
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 size={20} className="animate-spin text-content-tertiary" />
        </div>
      ) : isError ? (
        <p role="alert" className="px-4 py-12 text-center text-sm text-content-secondary">
          {t('boq.snapshots_error', { defaultValue: 'Failed to load version history.' })}
        </p>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-2xs">
            <thead className="sticky top-0 bg-surface-elevated text-content-tertiary">
              <tr>
                <th className="px-2 py-1 text-left">{t('boq.ordinal', { defaultValue: 'Pos.' })}</th>
                <th className="px-2 py-1 text-left">{t('boq.description', { defaultValue: 'Description' })}</th>
                <th className="px-2 py-1 text-right">{t('boq.compare_col_qty', { defaultValue: 'Qty' })}</th>
                <th className="px-2 py-1 text-right">{t('boq.compare_col_rate', { defaultValue: 'Rate' })}</th>
                <th className="px-2 py-1 text-right">{t('boq.total', { defaultValue: 'Total' })}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {view.rows.map((r, i) => (
                <tr key={`${r.ordinal}-${i}`} className={clsx(r.isSection && 'bg-surface-secondary/50 font-medium')}>
                  <td className="px-2 py-1 font-mono">{r.ordinal}</td>
                  <td className="max-w-[14rem] truncate px-2 py-1" title={r.description}>
                    {r.description}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">
                    {r.isSection ? '' : `${fmt(r.quantity, 3)} ${r.unit}`}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{r.isSection ? '' : fmt(r.unitRate)}</td>
                  <td className="px-2 py-1 text-right font-mono">{r.isSection ? '' : fmt(r.total)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-border font-medium">
                <td colSpan={4} className="px-2 py-1.5 text-right">
                  {t('boq.total', { defaultValue: 'Total' })}
                </td>
                <td className="px-2 py-1.5 text-right font-mono">{fmt(view.directTotal)}</td>
              </tr>
              {data?.grand_total != null && Number(data.grand_total) !== view.directTotal && (
                <tr className="font-medium">
                  <td colSpan={4} className="px-2 py-1 text-right">
                    {t('boq.grand_total', { defaultValue: 'Grand Total' })}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{fmt(data.grand_total)}</td>
                </tr>
              )}
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}

export function SnapshotComparePanel({
  boqId,
  olderId,
  newerId,
  onBack,
}: {
  boqId: string;
  olderId: string;
  newerId: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['boq-snapshot-compare', boqId, olderId, newerId],
    queryFn: () => boqApi.compareSnapshots(boqId, olderId, newerId),
    retry: false,
  });
  const rows = useMemo(() => (data ? snapshotDiffRows(data) : []), [data]);
  const delta = data ? Number(data.summary.total_change_amount) : 0;
  const title = t('boq.compare_btn', { defaultValue: 'Compare' });

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <BackBar title={title} onBack={onBack} icon={<GitCompare size={12} className="text-oe-blue" />} />
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 size={20} className="animate-spin text-content-tertiary" />
        </div>
      ) : isError || !data ? (
        <p role="alert" className="px-4 py-12 text-center text-sm text-content-secondary">
          {t('boq.compare_error', { defaultValue: 'Could not compare these BOQs.' })}
        </p>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <div className="grid grid-cols-3 gap-2 border-b border-border px-4 py-3 text-center text-2xs">
            <div>
              <div className="text-base font-semibold text-semantic-success">{data.summary.positions_added}</div>
              {t('boq.compare_ct_added', { defaultValue: 'Added' })}
            </div>
            <div>
              <div className="text-base font-semibold text-semantic-error">{data.summary.positions_removed}</div>
              {t('boq.compare_ct_removed', { defaultValue: 'Removed' })}
            </div>
            <div>
              <div className="text-base font-semibold text-semantic-warning">{data.summary.positions_changed}</div>
              {t('boq.compare_ct_changed', { defaultValue: 'Changed' })}
            </div>
          </div>
          <p className="flex items-center justify-between border-b border-border px-4 py-2 text-xs">
            <span className="text-content-secondary">{t('boq.diff_total_change', { defaultValue: 'Total change' })}</span>
            <span className="font-mono">
              {fmt(data.summary.total_a)} → {fmt(data.summary.total_b)}{' '}
              <span className={clsx('font-medium', delta > 0 ? 'text-semantic-success' : delta < 0 ? 'text-semantic-error' : '')}>
                ({delta > 0 ? '+' : ''}
                {fmt(delta)})
              </span>
            </span>
          </p>
          {rows.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-content-secondary">
              {t('boq.no_changes', { defaultValue: 'No changes' })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light">
              {rows.map((r, i) => (
                <li key={`${r.kind}-${r.ordinal}-${i}`} data-testid={`snapdiff-${r.kind}`} className="px-4 py-2">
                  <p className="flex items-center gap-1.5 text-xs">
                    <span
                      className={clsx(
                        'rounded px-1 text-2xs font-medium',
                        r.kind === 'added' && 'bg-semantic-success/10 text-semantic-success',
                        r.kind === 'removed' && 'bg-semantic-error/10 text-semantic-error',
                        r.kind === 'changed' && 'bg-semantic-warning/10 text-semantic-warning',
                      )}
                    >
                      {t(`boq.compare_ct_${r.kind}`, { defaultValue: r.kind })}
                    </span>
                    <span className="font-mono text-content-tertiary">{r.ordinal}</span>
                    <span className="truncate text-content-primary" title={r.description}>
                      {r.description}
                    </span>
                  </p>
                  <ul className="mt-0.5 pl-2 text-2xs text-content-secondary">
                    {r.changes.map((c) => (
                      <li key={c.field}>
                        <span className="font-mono text-oe-blue">{c.field}</span>{' '}
                        <span className="text-content-tertiary">{fmt(c.before)}</span>
                        <span className="mx-1 text-content-quaternary">→</span>
                        <span>{fmt(c.after)}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
