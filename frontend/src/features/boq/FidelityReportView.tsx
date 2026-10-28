// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The body of an exchange fidelity report: counts by severity, filters, the
 * item table and, for a stored report, the CSV / XLSX download.
 *
 * Used by the report dialog after an export or a check, and inline by the
 * import preview, where the report is not stored yet.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Download, Loader2, RefreshCw } from 'lucide-react';
import { Badge } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  FIDELITY_SEVERITIES,
  downloadFidelityReport,
  type FidelityReport,
  type FidelitySeverity,
} from './exchangeFidelityApi';
import {
  EMPTY_FILTER,
  fieldLabel,
  filterFidelityItems,
  kindLabel,
  kindsInReport,
  severityLabel,
  type FidelityFilter,
} from './exchangeFidelityText';

const SEVERITY_VARIANT: Record<FidelitySeverity, 'error' | 'warning' | 'neutral'> = {
  error: 'error',
  warning: 'warning',
  info: 'neutral',
};

export interface FidelityReportViewProps {
  report: FidelityReport;
  /** Needed for the download; without it (or without ``report.id``) no download is offered. */
  boqId?: string;
  /** Rows shown before "show all"; the import preview keeps it short. */
  initialRows?: number;
}

export function FidelityReportView({ report, boqId, initialRows = 200 }: FidelityReportViewProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [filter, setFilter] = useState<FidelityFilter>(EMPTY_FILTER);
  const [showAll, setShowAll] = useState(false);
  const [downloading, setDownloading] = useState<'csv' | 'xlsx' | null>(null);
  const kinds = useMemo(() => kindsInReport(report), [report]);
  const items = useMemo(() => filterFidelityItems(report.items, filter), [report.items, filter]);
  const visible = showAll ? items : items.slice(0, initialRows);
  const counts = report.summary.by_severity;

  const download = async (format: 'csv' | 'xlsx') => {
    if (!boqId || !report.id) return;
    setDownloading(format);
    try {
      await downloadFidelityReport(boqId, report.id, format, { severity: filter.severity, kind: filter.kind });
    } catch {
      addToast({ type: 'error', title: t('boq.fidelity.download_failed', { defaultValue: 'The report could not be downloaded' }) });
    } finally {
      setDownloading(null);
    }
  };

  if (report.summary.total === 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-semantic-success-bg p-3 text-xs text-semantic-success">
        <CheckCircle2 size={14} className="shrink-0" />
        <span>{t('boq.fidelity.lossless', { defaultValue: 'Nothing was lost: every value was carried across unchanged.' })}</span>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="fidelity-report">
      <div className="flex flex-wrap items-center gap-2">
        {FIDELITY_SEVERITIES.map((severity) => (
          <button
            key={severity}
            type="button"
            onClick={() => setFilter((f) => ({ ...f, severity: f.severity === severity ? '' : severity }))}
            aria-pressed={filter.severity === severity}
            className={`rounded-full ${filter.severity === severity ? 'ring-2 ring-oe-blue' : ''}`}
          >
            <Badge variant={SEVERITY_VARIANT[severity]} size="sm">
              {severityLabel(t, severity)}: {fmtNumber(counts[severity] ?? 0, 0)}
            </Badge>
          </button>
        ))}
        {report.roundtrip && (
          <Badge variant="blue" size="sm">
            <RefreshCw size={10} className="mr-1 inline" />
            {t('boq.fidelity.roundtrip_checked', { defaultValue: 'Round trip checked' })}
          </Badge>
        )}
        {boqId && report.id && (
          <div className="ml-auto flex gap-1">
            {(['csv', 'xlsx'] as const).map((format) => (
              <button
                key={format}
                type="button"
                onClick={() => download(format)}
                disabled={downloading !== null}
                className="flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
              >
                {downloading === format ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                {format.toUpperCase()}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <select
          value={filter.kind}
          onChange={(e) => setFilter((f) => ({ ...f, kind: e.target.value }))}
          aria-label={t('boq.fidelity.filter_kind', { defaultValue: 'Kind of loss' })}
          className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs"
        >
          <option value="">{t('boq.fidelity.all_kinds', { defaultValue: 'All kinds' })}</option>
          {kinds.map((kind) => (
            <option key={kind} value={kind}>
              {kindLabel(t, kind)} ({fmtNumber(report.summary.by_kind[kind] ?? 0, 0)})
            </option>
          ))}
        </select>
        <input
          type="search"
          value={filter.query}
          onChange={(e) => setFilter((f) => ({ ...f, query: e.target.value }))}
          placeholder={t('boq.fidelity.search_placeholder', { defaultValue: 'Search position, field or value' })}
          className="min-w-[12rem] flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs"
        />
      </div>

      {(report.items_truncated || report.summary.items_truncated) && (
        <p className="text-2xs text-content-tertiary">
          {t('boq.fidelity.items_truncated', {
            defaultValue: 'Only the first {{shown}} of {{total}} items were kept; the counts cover all of them.',
            shown: fmtNumber(report.items.length, 0),
            total: fmtNumber(report.summary.total, 0),
          })}
        </p>
      )}

      <div className="max-h-[50vh] overflow-auto rounded-lg border border-border-light">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-surface-secondary text-left text-content-secondary">
            <tr>
              <th className="px-2 py-1.5 font-medium">{t('boq.fidelity.col_severity', { defaultValue: 'Severity' })}</th>
              <th className="px-2 py-1.5 font-medium">{t('boq.fidelity.col_kind', { defaultValue: 'Kind of loss' })}</th>
              <th className="px-2 py-1.5 font-medium">{t('boq.fidelity.col_position', { defaultValue: 'Position' })}</th>
              <th className="px-2 py-1.5 font-medium">{t('boq.fidelity.col_field', { defaultValue: 'Field' })}</th>
              <th className="px-2 py-1.5 font-medium">{t('boq.fidelity.col_original', { defaultValue: 'Original value' })}</th>
              <th className="px-2 py-1.5 font-medium">{t('boq.fidelity.col_written', { defaultValue: 'Value written' })}</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((item, index) => (
              <tr key={`${item.kind}-${item.position_ref}-${item.field}-${index}`} className="border-t border-border-light align-top">
                <td className="px-2 py-1.5">
                  <Badge variant={SEVERITY_VARIANT[item.severity] ?? 'neutral'} size="sm">
                    {severityLabel(t, item.severity)}
                  </Badge>
                </td>
                <td className="px-2 py-1.5">
                  {kindLabel(t, item.kind)}
                  {item.count > 1 && <span className="ml-1 text-content-tertiary">×{fmtNumber(item.count, 0)}</span>}
                  {item.detail && <div className="mt-0.5 text-2xs text-content-tertiary">{item.detail}</div>}
                </td>
                <td className="px-2 py-1.5 font-mono">{item.position_ref || '–'}</td>
                <td className="px-2 py-1.5">{fieldLabel(t, item.field)}</td>
                <td className="px-2 py-1.5 break-all">{item.original ?? '–'}</td>
                <td className="px-2 py-1.5 break-all">{item.written ?? '–'}</td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} className="px-2 py-4 text-center text-content-tertiary">
                  {t('boq.fidelity.no_match', { defaultValue: 'No item matches the filter.' })}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {!showAll && items.length > initialRows && (
        <button type="button" onClick={() => setShowAll(true)} className="text-xs text-oe-blue hover:underline">
          {t('boq.fidelity.show_all', { defaultValue: 'Show all items ({{n}})', n: fmtNumber(items.length, 0) })}
        </button>
      )}
    </div>
  );
}
