// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Exchange report dialog: what an export or import of this bill did not
 * carry across, and a check that builds an export in memory, reads it back
 * with the matching importer and lists every difference, without a download.
 *
 * Opened with a ``reportId`` right after an export or import, or empty to run
 * a check or reopen one of the bill's earlier reports.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, FileSearch, Loader2, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { fmtDate } from '@/shared/lib/formatters';
import {
  checkExportFidelity,
  getFidelityReport,
  listFidelityReports,
  type CheckFormat,
  type FidelityReport,
} from './exchangeFidelityApi';
import { formatLabel, severityLabel } from './exchangeFidelityText';
import { FidelityReportView } from './FidelityReportView';

export interface ExchangeFidelityDialogProps {
  open: boolean;
  boqId: string;
  /** Open on this stored report; omitted opens the check and the register. */
  reportId?: string | null;
  onClose: () => void;
}

const CHECK_TARGETS: { value: string; format: CheckFormat; variant: '' | 'x83' | 'x84' }[] = [
  { value: 'gaeb_x83', format: 'gaeb_xml', variant: 'x83' },
  { value: 'gaeb_x84', format: 'gaeb_xml', variant: 'x84' },
  { value: 'bc3', format: 'bc3', variant: '' },
  { value: 'excel', format: 'excel', variant: '' },
  { value: 'csv', format: 'csv', variant: '' },
];

export function ExchangeFidelityDialog({ open, boqId, reportId, onClose }: ExchangeFidelityDialogProps) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(reportId ?? null);
  const [checked, setChecked] = useState<FidelityReport | null>(null);
  const [target, setTarget] = useState('gaeb_x83');
  const [roundtrip, setRoundtrip] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setSelectedId(reportId ?? null);
      setChecked(null);
      setError(null);
    }
  }, [open, reportId]);

  const register = useQuery({
    queryKey: ['boq-exchange-reports', boqId],
    queryFn: () => listFidelityReports(boqId),
    enabled: open,
  });
  const detail = useQuery({
    queryKey: ['boq-exchange-report', boqId, selectedId],
    queryFn: () => getFidelityReport(boqId, selectedId as string),
    enabled: open && !!selectedId && checked?.id !== selectedId,
  });

  if (!open) return null;

  const report: FidelityReport | null = checked && checked.id === selectedId ? checked : (detail.data ?? null);

  const runCheck = async () => {
    const choice = CHECK_TARGETS.find((c) => c.value === target) ?? CHECK_TARGETS[0]!;
    setRunning(true);
    setError(null);
    try {
      const result = await checkExportFidelity(boqId, { format_id: choice.format, variant: choice.variant, roundtrip });
      setChecked(result);
      setSelectedId(result.id ?? null);
      void register.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('boq.fidelity.check_failed', { defaultValue: 'The check failed' }));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="boq-fidelity-title"
        className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-full max-w-5xl max-h-[90vh] flex flex-col animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h3 id="boq-fidelity-title" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <FileSearch size={16} />
            {t('boq.fidelity.title', { defaultValue: 'Exchange report' })}
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-content-tertiary hover:bg-surface-secondary transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-4">
          <p className="text-xs text-content-secondary">
            {t('boq.fidelity.intro', {
              defaultValue:
                'Every exchange format holds less than the bill. This report lists what an import or export did not carry across unchanged: cut texts, rounded values, dropped attributes, markups the format cannot hold.',
            })}
          </p>

          <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border-light p-3">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('boq.fidelity.check_format', { defaultValue: 'Check an export to' })}
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary"
              >
                {CHECK_TARGETS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {formatLabel(t, c.format, c.variant)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input type="checkbox" checked={roundtrip} onChange={(e) => setRoundtrip(e.target.checked)} />
              {t('boq.fidelity.roundtrip_option', { defaultValue: 'Round trip: read the file back and compare' })}
            </label>
            <Button size="sm" onClick={runCheck} loading={running}>
              {t('boq.fidelity.run_check', { defaultValue: 'Run check' })}
            </Button>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg p-3 text-xs text-semantic-error">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {(register.data?.items.length ?? 0) > 0 && (
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('boq.fidelity.earlier_reports', { defaultValue: 'Reports of this bill' })}
              <select
                value={selectedId ?? ''}
                onChange={(e) => {
                  setChecked(null);
                  setSelectedId(e.target.value || null);
                }}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary"
              >
                <option value="">{t('boq.fidelity.pick_report', { defaultValue: 'Choose a report' })}</option>
                {register.data!.items.map((r) => (
                  <option key={r.id} value={r.id}>
                    {[
                      r.created_at ? fmtDate(r.created_at, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '',
                      r.direction === 'import'
                        ? t('boq.fidelity.direction_import', { defaultValue: 'Import' })
                        : r.is_check
                          ? t('boq.fidelity.direction_check', { defaultValue: 'Check' })
                          : t('boq.fidelity.direction_export', { defaultValue: 'Export' }),
                      formatLabel(t, r.format_id, r.variant),
                      `${severityLabel(t, 'error')} ${r.summary.by_severity?.error ?? 0}`,
                      `${severityLabel(t, 'warning')} ${r.summary.by_severity?.warning ?? 0}`,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </option>
                ))}
              </select>
            </label>
          )}

          {detail.isLoading && selectedId && !report && (
            <div className="flex items-center gap-2 text-xs text-content-secondary">
              <Loader2 size={14} className="animate-spin" />
              {t('common.loading', { defaultValue: 'Loading...' })}
            </div>
          )}
          {report && (
            <div className="space-y-2">
              <div className="text-xs font-medium text-content-primary">
                {formatLabel(t, report.format_id, report.variant)}
                {report.file_name ? ` · ${report.file_name}` : ''}
              </div>
              <FidelityReportView report={report} boqId={boqId} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
