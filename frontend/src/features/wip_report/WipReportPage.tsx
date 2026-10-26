// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Portfolio WIP schedule: one row per project with earned revenue, billing position and profit fade, totals per currency. */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowDown, ArrowUp, FileSpreadsheet, FileText } from 'lucide-react';
import { Button, Card, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import {
  billingPosition,
  exportPortfolio,
  fadeClass,
  fadeTone,
  sortRows,
  useWipPortfolio,
  type WipRow,
  type WipSortKey,
} from './api';

const todayIso = () => new Date().toISOString().slice(0, 10);

interface Column {
  key: WipSortKey;
  labelKey: string;
  labelDefault: string;
  numeric: boolean;
}

const COLUMNS: Column[] = [
  { key: 'project_name', labelKey: 'wip_report.col_project', labelDefault: 'Project', numeric: false },
  { key: 'contract_value', labelKey: 'wip_report.col_contract', labelDefault: 'Contract value', numeric: true },
  { key: 'percent_complete', labelKey: 'wip_report.col_percent', labelDefault: '% complete', numeric: true },
  { key: 'earned_revenue', labelKey: 'wip_report.col_earned', labelDefault: 'Earned revenue', numeric: true },
  { key: 'billed_to_date', labelKey: 'wip_report.col_billed', labelDefault: 'Billed to date', numeric: true },
  { key: 'over_billing', labelKey: 'wip_report.col_over', labelDefault: 'Over-billing', numeric: true },
  { key: 'under_billing', labelKey: 'wip_report.col_under', labelDefault: 'Under-billing', numeric: true },
  { key: 'projected_gross_profit', labelKey: 'wip_report.col_profit', labelDefault: 'Projected profit', numeric: true },
  { key: 'fade', labelKey: 'wip_report.col_fade', labelDefault: 'Fade / gain', numeric: true },
  { key: 'backlog', labelKey: 'wip_report.col_backlog', labelDefault: 'Backlog', numeric: true },
];

export function WipReportPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [asOf, setAsOf] = useState(todayIso());
  const [sort, setSort] = useState<{ key: WipSortKey; dir: 'asc' | 'desc' }>({ key: 'project_name', dir: 'asc' });
  const [exporting, setExporting] = useState<'xlsx' | 'pdf' | null>(null);
  const { data, isLoading, isError } = useWipPortfolio(asOf || undefined);

  const rows = useMemo(() => sortRows(data?.rows ?? [], sort.key, sort.dir), [data, sort]);

  const toggleSort = (key: WipSortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'project_name' ? 'asc' : 'desc' }));

  const runExport = async (format: 'xlsx' | 'pdf') => {
    setExporting(format);
    try {
      await exportPortfolio(format, asOf || undefined);
    } catch (err) {
      addToast({ type: 'error', title: t('wip_report.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });
    } finally {
      setExporting(null);
    }
  };

  const open = (r: WipRow) => navigate(`/projects/${r.project_id}/wip`);

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('wip_report.title', { defaultValue: 'WIP report' })}
        subtitle={t('wip_report.subtitle', { defaultValue: 'Work in progress by project: earned revenue against billing, with over- and under-billing and profit fade' })}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              {t('wip_report.as_of', { defaultValue: 'As of' })}
              <input
                type="date"
                value={asOf}
                onChange={(e) => setAsOf(e.target.value)}
                className="h-8 rounded-md border border-border-light bg-surface-primary px-2 text-sm text-content-primary"
                data-testid="wip-as-of"
              />
            </label>
            <Button variant="secondary" size="sm" icon={<FileSpreadsheet size={14} />} loading={exporting === 'xlsx'} disabled={exporting !== null} onClick={() => runExport('xlsx')}>
              {t('wip_report.export_xlsx', { defaultValue: 'Excel' })}
            </Button>
            <Button variant="secondary" size="sm" icon={<FileText size={14} />} loading={exporting === 'pdf'} disabled={exporting !== null} onClick={() => runExport('pdf')}>
              {t('wip_report.export_pdf', { defaultValue: 'PDF' })}
            </Button>
          </div>
        }
      />

      <p className="text-xs text-content-tertiary">
        {t('wip_report.explainer', {
          defaultValue:
            'Percent complete = cost to date / estimated total cost. Earned revenue = contract value x percent complete. Billed above earned is over-billing (a liability); earned above billed is under-billing (an asset).',
        })}
      </p>

      {isLoading ? (
        <Card padding="lg" className="text-center text-sm text-content-tertiary">{t('wip_report.loading', { defaultValue: 'Loading...' })}</Card>
      ) : isError ? (
        <EmptyState title={t('wip_report.load_error', { defaultValue: 'The WIP report could not be loaded' })} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={t('wip_report.empty', { defaultValue: 'No projects with a contract yet' })}
          description={t('wip_report.empty_hint', { defaultValue: 'A project appears here once it has a contract value and costs.' })}
        />
      ) : (
        <Card padding="none" className="overflow-x-auto">
          <table className="w-full min-w-[1100px] text-sm" data-testid="wip-table">
            <thead>
              <tr className="border-b border-border-light text-2xs uppercase tracking-wide text-content-tertiary">
                {COLUMNS.map((c) => (
                  <th key={c.key} className={`px-3 py-2 font-medium ${c.numeric ? 'text-right' : 'text-left'}`}>
                    <button type="button" onClick={() => toggleSort(c.key)} className="inline-flex items-center gap-1 hover:text-content-primary">
                      {t(c.labelKey, { defaultValue: c.labelDefault })}
                      {sort.key === c.key && (sort.dir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {rows.map((r) => {
                const pos = billingPosition(r);
                return (
                  <tr
                    key={r.project_id}
                    onClick={() => open(r)}
                    className="cursor-pointer hover:bg-surface-secondary"
                    data-testid="wip-row"
                  >
                    <td className="px-3 py-2">
                      <div className="font-medium text-content-primary">{r.project_name}</div>
                      {r.loss_job && (
                        <span className="text-2xs font-medium text-rose-600">{t('wip_report.loss_job_badge', { defaultValue: 'Loss job' })}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(r.contract_value, r.currency)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.percent_complete}%</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(r.earned_revenue, r.currency)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(r.billed_to_date, r.currency)}</td>
                    <td className={`px-3 py-2 text-right tabular-nums ${pos === 'over' ? 'bg-amber-50 font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-400' : 'text-content-tertiary'}`}>
                      {formatCurrency(r.over_billing, r.currency)}
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums ${pos === 'under' ? 'bg-sky-50 font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-400' : 'text-content-tertiary'}`}>
                      {formatCurrency(r.under_billing, r.currency)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(r.projected_gross_profit, r.currency)}</td>
                    <td className={`px-3 py-2 text-right tabular-nums ${fadeClass(fadeTone(r.fade))}`}>
                      {r.fade == null ? '-' : formatCurrency(r.fade, r.currency)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(r.backlog, r.currency)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              {(data?.totals ?? []).map((tot) => (
                <tr key={tot.currency} className="border-t-2 border-border-light bg-surface-secondary font-semibold" data-testid="wip-total">
                  <td className="px-3 py-2">
                    {t('wip_report.total_in', { defaultValue: 'Total {{currency}}', currency: tot.currency })} ({tot.projects})
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(tot.contract_value, tot.currency)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{tot.percent_complete}%</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(tot.earned_revenue, tot.currency)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(tot.billed_to_date, tot.currency)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-amber-700 dark:text-amber-400">{formatCurrency(tot.over_billing, tot.currency)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-sky-700 dark:text-sky-400">{formatCurrency(tot.under_billing, tot.currency)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(tot.projected_gross_profit, tot.currency)}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${fadeClass(fadeTone(tot.fade))}`}>{formatCurrency(tot.fade, tot.currency)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(tot.backlog, tot.currency)}</td>
                </tr>
              ))}
            </tfoot>
          </table>
        </Card>
      )}
    </div>
  );
}

export default WipReportPage;
