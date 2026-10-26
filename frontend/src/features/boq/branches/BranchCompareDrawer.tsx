// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BranchCompareDrawer — any two estimates of one branch tree side by side:
 * added, removed and changed positions (quantity, rate, text), totals by
 * section and by cost group, and the same as an XLSX or PDF download.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, FileSpreadsheet, FileText, GitCompare, Loader2, X } from 'lucide-react';
import clsx from 'clsx';
import { Badge } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { defaultDocumentLocale } from '@/shared/lib/documentExport';
import { useToastStore } from '@/stores/useToastStore';
import { branchApi, type BranchChangeType, type BranchCompareGroup, type BranchNode, type CompareView } from './branchApi';
import { deltaSign, visibleCompareRows } from './branchHelpers';

const CHANGE_VARIANT: Record<BranchChangeType, 'success' | 'error' | 'warning' | 'neutral'> = {
  added: 'success',
  removed: 'error',
  changed: 'warning',
  unchanged: 'neutral',
};

/** Backend locale files the comparison export is printed in; others fall back to English. */
const EXPORT_LOCALES: readonly string[] = [
  'ar', 'bg', 'bn', 'cs', 'da', 'de', 'el', 'en', 'es', 'et', 'fa', 'fi', 'fil', 'fr', 'he', 'hi', 'hr', 'hu', 'id',
  'it', 'ja', 'kk', 'ko', 'ky', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sv', 'th', 'tr', 'uk', 'ur', 'uz', 'vi', 'zh',
];

export interface BranchCompareDrawerProps {
  nodes: BranchNode[];
  currentBoqId: string;
  isOpen: boolean;
  onClose: () => void;
}

function Delta({ value }: { value: string }) {
  const sign = deltaSign(value);
  return (
    <span
      className={clsx(
        'font-mono',
        sign > 0 && 'text-red-600 dark:text-red-400',
        sign < 0 && 'text-emerald-600 dark:text-emerald-400',
        sign === 0 && 'text-content-tertiary',
      )}
    >
      {sign > 0 ? '+' : ''}
      {fmtNumber(value)}
    </span>
  );
}

export function BranchCompareDrawer({ nodes, currentBoqId, isOpen, onClose }: BranchCompareDrawerProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const current = nodes.find((n) => n.boq_id === currentBoqId);
  const [aId, setAId] = useState('');
  const [bId, setBId] = useState('');
  const [view, setView] = useState<CompareView>('positions');
  const [onlyChanges, setOnlyChanges] = useState(true);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    const parent = current?.parent_boq_id ?? nodes.find((n) => n.is_main)?.boq_id ?? '';
    setAId(current && !current.is_main ? parent : currentBoqId);
    setBId(current && !current.is_main ? currentBoqId : nodes.find((n) => !n.is_main)?.boq_id ?? '');
  }, [isOpen, current, currentBoqId, nodes]);

  useEffect(() => {
    if (!isOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, { capture: true });
    return () => document.removeEventListener('keydown', onKey, { capture: true });
  }, [isOpen, onClose]);

  const ready = isOpen && !!aId && !!bId && aId !== bId;
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['boq-branch-compare', aId, bId],
    queryFn: () => branchApi.compare(aId, bId),
    enabled: ready,
    retry: false,
  });

  const changeLabel = (type: BranchChangeType) =>
    type === 'added'
      ? t('boq.branch.ct_added', { defaultValue: 'Added' })
      : type === 'removed'
        ? t('boq.branch.ct_removed', { defaultValue: 'Removed' })
        : type === 'changed'
          ? t('boq.branch.ct_changed', { defaultValue: 'Changed' })
          : t('boq.branch.ct_unchanged', { defaultValue: 'Unchanged' });

  const rows = useMemo(() => visibleCompareRows(data?.rows ?? [], onlyChanges), [data, onlyChanges]);
  const groups: BranchCompareGroup[] = view === 'sections' ? data?.by_section ?? [] : data?.by_cost_group ?? [];

  const download = async (format: 'xlsx' | 'pdf') => {
    if (!ready) return;
    setExporting(true);
    try {
      await branchApi.exportCompare(aId, bId, format, view, defaultDocumentLocale(EXPORT_LOCALES));
    } catch (err) {
      addToast({
        type: 'error',
        title: t('boq.branch.export_failed', { defaultValue: 'Export failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setExporting(false);
    }
  };

  if (!isOpen) return null;

  const picker = (value: string, onChange: (v: string) => void, label: string) => (
    <label className="block flex-1 min-w-0">
      <span className="block text-2xs font-medium text-content-secondary mb-1">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
      >
        <option value="">{t('boq.branch.pick', { defaultValue: '- Select -' })}</option>
        {nodes.map((n) => (
          <option key={n.boq_id} value={n.boq_id}>
            {n.is_main ? `${n.name} (${t('boq.branch.main', { defaultValue: 'main' })})` : n.name}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      <div className="fixed inset-0 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.branch.compare_title', { defaultValue: 'Compare branches' })}
        className="relative ml-auto flex h-full w-[680px] max-w-full flex-col bg-surface-elevated border-l border-border shadow-2xl animate-slide-in-right"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <GitCompare size={16} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('boq.branch.compare_title', { defaultValue: 'Compare branches' })}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="border-b border-border p-3 space-y-2">
          <div className="flex items-end gap-2">
            {picker(aId, setAId, t('boq.branch.compare_a', { defaultValue: 'Estimate A' }))}
            <ArrowRight size={14} className="mb-2.5 shrink-0 text-content-quaternary" />
            {picker(bId, setBId, t('boq.branch.compare_b', { defaultValue: 'Estimate B' }))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div role="tablist" className="inline-flex rounded-lg border border-border-light p-0.5">
              {(['positions', 'sections', 'cost_groups'] as CompareView[]).map((v) => (
                <button
                  key={v}
                  type="button"
                  role="tab"
                  aria-selected={view === v}
                  onClick={() => setView(v)}
                  className={clsx(
                    'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                    view === v ? 'bg-oe-blue text-white' : 'text-content-secondary hover:bg-surface-secondary',
                  )}
                >
                  {v === 'positions'
                    ? t('boq.branch.view_positions', { defaultValue: 'Positions' })
                    : v === 'sections'
                      ? t('boq.branch.view_sections', { defaultValue: 'Sections' })
                      : t('boq.branch.view_cost_groups', { defaultValue: 'Cost groups' })}
                </button>
              ))}
            </div>
            {view === 'positions' && (
              <label className="flex items-center gap-1.5 text-xs text-content-secondary">
                <input
                  type="checkbox"
                  checked={onlyChanges}
                  onChange={(e) => setOnlyChanges(e.target.checked)}
                  className="accent-oe-blue"
                />
                {t('boq.branch.only_changes', { defaultValue: 'Only changes' })}
              </label>
            )}
            <div className="ml-auto flex gap-1">
              <button
                type="button"
                disabled={!ready || exporting}
                onClick={() => download('xlsx')}
                className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
              >
                <FileSpreadsheet size={13} /> XLSX
              </button>
              <button
                type="button"
                disabled={!ready || exporting}
                onClick={() => download('pdf')}
                className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
              >
                <FileText size={13} /> PDF
              </button>
            </div>
          </div>
        </div>

        {data && (
          <div className="border-b border-border px-4 py-3">
            <div className="flex flex-wrap gap-1.5 mb-2">
              <Badge variant="success" size="sm">
                {t('boq.branch.ct_added', { defaultValue: 'Added' })}: {data.summary.added}
              </Badge>
              <Badge variant="error" size="sm">
                {t('boq.branch.ct_removed', { defaultValue: 'Removed' })}: {data.summary.removed}
              </Badge>
              <Badge variant="warning" size="sm">
                {t('boq.branch.ct_changed', { defaultValue: 'Changed' })}: {data.summary.changed}
              </Badge>
              <Badge variant="neutral" size="sm">
                {t('boq.branch.ct_unchanged', { defaultValue: 'Unchanged' })}: {data.summary.unchanged}
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="text-content-tertiary">{fmtNumber(data.summary.total_a)}</span>
              <ArrowRight size={11} className="text-content-quaternary" />
              <span className="font-semibold text-content-primary">{fmtNumber(data.summary.total_b)}</span>
              <span className="text-content-tertiary">{data.currency}</span>
              <Delta value={data.summary.delta} />
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {!ready ? (
            <p className="px-4 py-12 text-center text-sm text-content-secondary">
              {t('boq.branch.compare_hint', { defaultValue: 'Pick two different estimates to compare.' })}
            </p>
          ) : isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin text-content-tertiary" />
            </div>
          ) : isError ? (
            <p className="px-4 py-12 text-center text-sm text-semantic-error">
              {error instanceof Error ? error.message : t('boq.branch.compare_error', { defaultValue: 'Could not compare.' })}
            </p>
          ) : view === 'positions' ? (
            rows.length === 0 ? (
              <p className="px-4 py-12 text-center text-sm text-content-secondary">
                {t('boq.branch.no_diff', { defaultValue: 'No differences.' })}
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-elevated border-b border-border-light">
                  <tr className="text-2xs text-content-tertiary text-left">
                    <th className="px-3 py-2 font-medium">{t('boq.branch.col_position', { defaultValue: 'Position' })}</th>
                    <th className="px-2 py-2 font-medium text-right">{t('boq.branch.col_qty', { defaultValue: 'Qty' })}</th>
                    <th className="px-2 py-2 font-medium text-right">{t('boq.branch.col_rate', { defaultValue: 'Rate' })}</th>
                    <th className="px-2 py-2 font-medium text-right">{t('boq.branch.col_delta', { defaultValue: 'Difference' })}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {rows.map((r) => {
                    const textChanged = r.changed_fields.includes('description');
                    return (
                      <tr key={r.key} className="hover:bg-surface-secondary/40" data-testid="branch-compare-row">
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-1.5">
                            <Badge variant={CHANGE_VARIANT[r.change_type]} size="sm">
                              {changeLabel(r.change_type)}
                            </Badge>
                            <span className="font-medium text-content-primary">{r.ordinal}</span>
                          </div>
                          {textChanged ? (
                            <p className="mt-0.5 text-2xs">
                              <span className="text-content-tertiary line-through">{r.a_description}</span>
                              <br />
                              <span className="text-content-primary">{r.b_description}</span>
                            </p>
                          ) : (
                            <p className="mt-0.5 max-w-[260px] truncate text-2xs text-content-tertiary">{r.description}</p>
                          )}
                        </td>
                        {(['quantity', 'unit_rate'] as const).map((field) => {
                          const a = field === 'quantity' ? r.a_quantity : r.a_unit_rate;
                          const b = field === 'quantity' ? r.b_quantity : r.b_unit_rate;
                          const pair = r.change_type === 'changed' && r.changed_fields.includes(field);
                          return (
                            <td key={field} className="px-2 py-2 align-top text-right font-mono text-2xs">
                              {pair ? (
                                <>
                                  <span className="text-content-tertiary">{fmtNumber(a)}</span>
                                  <br />
                                  <span className="font-semibold text-content-primary">{fmtNumber(b)}</span>
                                </>
                              ) : (
                                <span className="text-content-secondary">{fmtNumber(b ?? a)}</span>
                              )}
                            </td>
                          );
                        })}
                        <td className="px-2 py-2 align-top text-right text-2xs">
                          <Delta value={r.delta} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )
          ) : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-elevated border-b border-border-light">
                <tr className="text-2xs text-content-tertiary text-left">
                  <th className="px-3 py-2 font-medium">
                    {view === 'sections'
                      ? t('boq.branch.col_section', { defaultValue: 'Section' })
                      : t('boq.branch.col_cost_group', { defaultValue: 'Cost group' })}
                  </th>
                  <th className="px-2 py-2 font-medium text-right">A</th>
                  <th className="px-2 py-2 font-medium text-right">B</th>
                  <th className="px-2 py-2 font-medium text-right">{t('boq.branch.col_delta', { defaultValue: 'Difference' })}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {groups.map((g) => (
                  <tr key={g.key || '-'} data-testid="branch-compare-group">
                    <td className="px-3 py-2 text-content-primary">
                      {g.label || t('boq.branch.ungrouped', { defaultValue: 'Not grouped' })}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-2xs text-content-secondary">{fmtNumber(g.total_a)}</td>
                    <td className="px-2 py-2 text-right font-mono text-2xs text-content-primary">{fmtNumber(g.total_b)}</td>
                    <td className="px-2 py-2 text-right text-2xs">
                      <Delta value={g.delta} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
