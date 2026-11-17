// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Payroll export card on the Field Time page: approved worked hours as a file for an external
 * payroll system. Hours only; pay is never computed here. Pay codes are the customer's own.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card, CardContent, CardHeader, EmptyState, ErrorState } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { HOUR_TYPES, formatHours } from './api';
import {
  createPayrollRun,
  downloadPayrollRun,
  lastCompletedWeek,
  listPayrollExamples,
  listPayrollProfiles,
  listPayrollRuns,
  previewPayroll,
  savePayrollProfile,
  updatePayrollProfile,
  type PayrollExample,
} from './payrollApi';

export function PayrollExportCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const week = lastCompletedWeek(new Date());
  const [from, setFrom] = useState(week.from);
  const [to, setTo] = useState(week.to);
  const [profileId, setProfileId] = useState<string | null>(null);

  const profiles = useQuery({ queryKey: ['payroll-profiles'], queryFn: listPayrollProfiles, select: (p) => p.items });
  const examples = useQuery({ queryKey: ['payroll-examples'], queryFn: listPayrollExamples, select: (p) => p.items });
  const runs = useQuery({ queryKey: ['payroll-runs'], queryFn: listPayrollRuns, select: (p) => p.items });
  const activeId = profileId ?? profiles.data?.[0]?.id ?? null;
  const active = profiles.data?.find((p) => p.id === activeId);
  const preview = useQuery({
    queryKey: ['payroll-preview', activeId, from, to],
    queryFn: () => previewPayroll(activeId as string, from, to, []),
    enabled: !!activeId && from <= to,
  });
  const setup = useMutation({
    mutationFn: (ex: PayrollExample) =>
      savePayrollProfile(ex.name || t('field_time.payroll_export.profile_default', { defaultValue: 'Payroll' }), ex.config),
    onSuccess: (p) => {
      setProfileId(p.id);
      void qc.invalidateQueries({ queryKey: ['payroll-profiles'] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });
  const save = useMutation({
    mutationFn: (codes: Record<string, string>) =>
      updatePayrollProfile(active!.id, active!.name, { ...active!.config, pay_codes: codes }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['payroll-profiles'] }),
  });
  const create = useMutation({
    mutationFn: () => createPayrollRun(activeId as string, from, to, []),
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: ['payroll-runs'] });
      void qc.invalidateQueries({ queryKey: ['payroll-preview'] });
      void downloadPayrollRun(run);
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (profiles.isError) {
    return (
      <ErrorState
        title={t('field_time.payroll_export.load_failed', { defaultValue: 'The payroll export could not be loaded.' })}
        onRetry={() => void profiles.refetch()}
      />
    );
  }

  return (
    <Card data-testid="payroll-export-card" id="payroll-export">
      <CardHeader title={t('field_time.payroll_export.title', { defaultValue: 'Payroll export' })} />
      <CardContent className="space-y-3">
        {profiles.data && profiles.data.length === 0 ? (
          <EmptyState
            title={t('field_time.payroll_export.empty', {
              defaultValue: 'Send approved hours to your payroll system as a file.',
            })}
            action={
              <div className="flex flex-wrap gap-2">
                {(examples.data ?? []).map((ex) => (
                  <Button key={ex.key} loading={setup.isPending} onClick={() => setup.mutate(ex)}>
                    {t('field_time.payroll_export.setup', { defaultValue: 'Set up export' })}
                    {ex.name ? `: ${ex.name}` : ''}
                  </Button>
                ))}
              </div>
            }
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <select className="oe-input" value={activeId ?? ''} onChange={(e) => setProfileId(e.target.value)}>
                {(profiles.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <input type="date" className="oe-input" value={from} onChange={(e) => setFrom(e.target.value)} />
              <input type="date" className="oe-input" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>

            {active && (
              <details>
                <summary className="cursor-pointer text-sm">
                  {t('field_time.payroll_export.pay_codes', { defaultValue: 'Pay codes' })}
                </summary>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {HOUR_TYPES.map((h) => (
                    <label key={h} className="text-xs">
                      {t(`field_time.hour_type_${h}`, { defaultValue: h })}
                      <input
                        className="oe-input w-full"
                        defaultValue={active.config.pay_codes[h] ?? ''}
                        onBlur={(e) => {
                          const next = { ...active.config.pay_codes, [h]: e.target.value.trim() };
                          if (!next[h]) delete next[h];
                          if ((active.config.pay_codes[h] ?? '') !== (next[h] ?? '')) save.mutate(next);
                        }}
                      />
                    </label>
                  ))}
                </div>
              </details>
            )}

            {preview.data && (
              <div className="space-y-2" data-testid="payroll-preview">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 text-sm">
                  <span>{t('field_time.payroll_export.kpi_workers', { defaultValue: 'Workers' })}: {preview.data.workers}</span>
                  <span>{t('field_time.payroll_export.kpi_rows', { defaultValue: 'Rows' })}: {preview.data.rows}</span>
                  <span>{t('field_time.payroll_export.kpi_hours', { defaultValue: 'Hours' })}: {formatHours(preview.data.hours)}</span>
                  <span>{t('field_time.payroll_export.kpi_corrections', { defaultValue: 'Corrections' })}: {preview.data.corrections}</span>
                </div>
                {preview.data.rows === 0 && preview.data.issues.length === 0 && (
                  <p className="text-sm text-content-secondary">
                    {t('field_time.payroll_export.none_in_period', { defaultValue: 'No approved hours in this period.' })}
                  </p>
                )}
                <ul className="space-y-1 text-sm">
                  {preview.data.issues.map((i, idx) => (
                    <li key={idx} className={i.severity === 'error' ? 'text-semantic-error' : 'text-content-secondary'}>
                      {t(`validation.${i.rule_id}`, { defaultValue: i.message, ...i.details })}
                    </li>
                  ))}
                </ul>
                <Button
                  disabled={preview.data.blocked || preview.data.rows === 0}
                  loading={create.isPending}
                  onClick={() => create.mutate()}
                >
                  {t('field_time.payroll_export.create', { defaultValue: 'Create file' })}
                </Button>
              </div>
            )}
          </>
        )}

        {runs.data && runs.data.length > 0 && (
          <div>
            <h4 className="mb-1 text-sm font-medium">
              {t('field_time.payroll_export.recent_runs', { defaultValue: 'Recent runs' })}
            </h4>
            <table className="oe-table w-full text-sm">
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td>R{r.number}</td>
                    <td>
                      <DateDisplay value={r.period_from} format="numeric" /> - <DateDisplay value={r.period_to} format="numeric" />
                    </td>
                    <td className="text-right tabular-nums">{r.row_count}</td>
                    <td className="text-right tabular-nums">{formatHours(r.total_hours)}</td>
                    <td className="text-right tabular-nums">{r.correction_count}</td>
                    <td className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => void downloadPayrollRun(r)}>
                        {t('common.download', { defaultValue: 'Download' })}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
