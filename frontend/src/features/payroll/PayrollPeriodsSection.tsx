// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Export periods: group a project's timesheet hours into a pay period, apply a
 * country rule profile (overtime, night, weekend, holiday pay types), lock the
 * period and hand it to payroll as CSV / XLSX / JSON / LODAS. A locked period
 * freezes the timesheets inside its dates; reopening needs a reason that lands
 * in the audit trail.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Download, Loader2, Lock, LockOpen, Plus, RefreshCw, Coins } from 'lucide-react';
import { Badge, Button, Card, EmptyState, Input } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui/Badge';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  EXPORT_COLUMNS,
  PAY_TYPES,
  PeriodExportError,
  createPeriod,
  downloadPeriodExport,
  fetchPeriod,
  fetchPeriods,
  fetchRuleProfiles,
  lockPeriod,
  postPeriodCosts,
  rebuildPeriod,
  reopenPeriod,
} from './api';
import type { PeriodExportFormat, PeriodStatus, RuleProfile } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

const SELECT_CLASS =
  'h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary ' +
  'transition-all duration-normal ease-oe hover:border-content-tertiary ' +
  'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function num(value: string | number, digits = 2): string {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(n);
  } catch {
    return n.toFixed(digits);
  }
}

export function statusLabel(s: PeriodStatus, t: Translate): string {
  if (s === 'locked') return t('payroll.period_status_locked', { defaultValue: 'Locked' });
  if (s === 'exported') return t('payroll.period_status_exported', { defaultValue: 'Exported' });
  return t('payroll.period_status_open', { defaultValue: 'Open' });
}

export function statusVariant(s: PeriodStatus): BadgeVariant {
  if (s === 'locked') return 'warning';
  if (s === 'exported') return 'success';
  return 'blue';
}

export function payTypeLabel(p: string, t: Translate): string {
  const defaults: Record<string, string> = {
    regular: 'Regular',
    overtime: 'Overtime',
    overtime_weekly: 'Weekly overtime',
    night_premium: 'Night premium',
    saturday: 'Saturday',
    sunday: 'Sunday',
    holiday: 'Holiday',
    per_diem: 'Per diem',
  };
  return t(`payroll.pay_type.${p}`, { defaultValue: defaults[p] ?? p });
}

function columnLabel(c: string, t: Translate): string {
  const defaults: Record<string, string> = {
    employee_number: 'Employee number',
    employee: 'Employee',
    project: 'Project',
    cost_code: 'Cost code',
    work_date: 'Date',
    pay_type: 'Pay type',
    hours: 'Hours',
    rate: 'Rate',
    multiplier: 'Multiplier',
    amount: 'Amount',
    currency: 'Currency',
    employee_id: 'Employee ID',
    project_id: 'Project ID',
    overtime_approved: 'Overtime approved',
    period_start: 'Period start',
    period_end: 'Period end',
  };
  return t(`payroll.col.${c}`, { defaultValue: defaults[c] ?? c });
}

/* ── Reopen dialog: the reason is required ─────────────────────────────── */

function ReopenDialog({
  busy,
  onCancel,
  onConfirm,
}: {
  busy: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const valid = reason.trim().length >= 3;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('payroll.reopen_title', { defaultValue: 'Reopen payroll period' })}
        className="w-full max-w-md space-y-3 rounded-xl bg-surface-primary p-5 shadow-xl"
      >
        <h3 className="text-sm font-semibold text-content-primary">
          {t('payroll.reopen_title', { defaultValue: 'Reopen payroll period' })}
        </h3>
        <p className="text-xs text-content-tertiary">
          {t('payroll.reopen_desc', {
            defaultValue: 'Timesheets in this period become editable again. The reason is kept in the audit trail.',
          })}
        </p>
        <label className="block text-xs text-content-secondary">
          {t('payroll.reopen_reason', { defaultValue: 'Reason (at least 3 characters)' })}
          <textarea
            className="mt-1 w-full rounded-lg border border-border bg-surface-primary p-2 text-sm"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-label={t('payroll.reopen_reason', { defaultValue: 'Reason (at least 3 characters)' })}
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel}>
            {t('confirm_dialog.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!valid || busy}
            onClick={() => onConfirm(reason.trim())}
          >
            {t('payroll.reopen_confirm', { defaultValue: 'Reopen period' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Section ───────────────────────────────────────────────────────────── */

export function PayrollPeriodsSection({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [label, setLabel] = useState('');
  const [profile, setProfile] = useState('');
  const [reopenOpen, setReopenOpen] = useState(false);
  const [format, setFormat] = useState<PeriodExportFormat>('csv');
  const [columns, setColumns] = useState<string[]>([...EXPORT_COLUMNS]);
  const [consultant, setConsultant] = useState('');
  const [client, setClient] = useState('');
  const [exportErrors, setExportErrors] = useState<string[]>([]);

  const profilesQuery = useQuery({ queryKey: ['payroll', 'rule-profiles'], queryFn: fetchRuleProfiles });
  const periodsQuery = useQuery({
    queryKey: ['payroll', 'periods', projectId],
    queryFn: () => fetchPeriods(projectId),
    enabled: Boolean(projectId),
  });
  const detailQuery = useQuery({
    queryKey: ['payroll', 'period', selectedId],
    queryFn: () => fetchPeriod(selectedId as string),
    enabled: Boolean(selectedId),
  });

  const profiles: RuleProfile[] = profilesQuery.data ?? [];
  const periods = periodsQuery.data ?? [];
  const detail = detailQuery.data ?? null;
  const detailProfile = useMemo(
    () => profiles.find((p) => p.profile === detail?.rule_profile) ?? null,
    [profiles, detail],
  );
  const chosenProfile = profiles.find((p) => p.profile === profile) ?? null;

  const refresh = (id?: string) => {
    void queryClient.invalidateQueries({ queryKey: ['payroll', 'periods', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['payroll', 'dashboard'] });
    if (id) void queryClient.invalidateQueries({ queryKey: ['payroll', 'period', id] });
  };
  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });
  const ok = (message: string) => addToast({ type: 'success', title: '', message });

  const createMut = useMutation({
    mutationFn: () =>
      createPeriod(projectId, {
        period_start: start,
        period_end: end,
        ...(label.trim() ? { label: label.trim() } : {}),
        ...(profile ? { rule_profile: profile } : {}),
      }),
    onSuccess: (p) => {
      ok(t('payroll.period_created', { defaultValue: 'Pay period created from the timesheets.' }));
      refresh();
      setSelectedId(p.id);
    },
    onError,
  });
  const rebuildMut = useMutation({
    mutationFn: (id: string) => rebuildPeriod(id),
    onSuccess: (p) => {
      ok(t('payroll.period_rebuilt', { defaultValue: 'Period rebuilt from the timesheets.' }));
      refresh(p.id);
    },
    onError,
  });
  const lockMut = useMutation({
    mutationFn: (id: string) => lockPeriod(id),
    onSuccess: (p) => {
      ok(t('payroll.period_locked', { defaultValue: 'Period locked. Timesheets in it can no longer change.' }));
      refresh(p.id);
    },
    onError,
  });
  const reopenMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => reopenPeriod(id, reason),
    onSuccess: (p) => {
      ok(t('payroll.period_reopened', { defaultValue: 'Period reopened.' }));
      setReopenOpen(false);
      refresh(p.id);
    },
    onError,
  });
  const postMut = useMutation({
    mutationFn: (id: string) => postPeriodCosts(id),
    onSuccess: (p) => {
      ok(t('payroll.period_costs_posted', { defaultValue: 'Labour cost posted to the project.' }));
      refresh(p.id);
    },
    onError,
  });
  const exportMut = useMutation({
    mutationFn: (id: string) =>
      downloadPeriodExport(id, {
        format,
        columns,
        consultantNumber: consultant.trim(),
        clientNumber: client.trim(),
      }),
    onMutate: () => setExportErrors([]),
    onSuccess: () => {
      ok(t('payroll.period_exported', { defaultValue: 'Export downloaded.' }));
      if (selectedId) refresh(selectedId);
    },
    onError: (err) => {
      if (err instanceof PeriodExportError && err.messages.length > 0) setExportErrors(err.messages);
      else setExportErrors([getErrorMessage(err)]);
    },
  });

  const lodasNeedsNumbers = format === 'lodas' && (!consultant.trim() || !client.trim());
  const canCreate = Boolean(start && end && end >= start);
  const isOpen = detail?.status === 'open';
  const columnsApply = format === 'csv' || format === 'xlsx';

  const toggleColumn = (c: string) =>
    setColumns((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));

  return (
    <Card className="space-y-4 p-4" data-testid="payroll-periods">
      <div>
        <h2 className="text-sm font-semibold text-content-primary">
          {t('payroll.periods_title', { defaultValue: 'Export periods' })}
        </h2>
        <p className="text-xs text-content-tertiary">
          {t('payroll.periods_desc', {
            defaultValue: 'Turn timesheet hours into pay types by country rules, lock the period, then export it for payroll.',
          })}
        </p>
      </div>

      {/* Create */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Input
          label={t('payroll.period_start', { defaultValue: 'From' })}
          type="date"
          value={start}
          onChange={(e) => setStart(e.target.value)}
        />
        <Input
          label={t('payroll.period_end', { defaultValue: 'To' })}
          type="date"
          value={end}
          onChange={(e) => setEnd(e.target.value)}
        />
        <Input
          label={t('payroll.period_label', { defaultValue: 'Label (optional)' })}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <label className="text-xs text-content-secondary">
          {t('payroll.rule_profile', { defaultValue: 'Rule profile' })}
          <select
            className={clsx(SELECT_CLASS, 'mt-1 w-full')}
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            aria-label={t('payroll.rule_profile', { defaultValue: 'Rule profile' })}
          >
            <option value="">{t('payroll.rule_profile_auto', { defaultValue: 'Project country default' })}</option>
            {profiles.map((p) => (
              <option key={p.profile} value={p.profile}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <Button
            variant="primary"
            size="sm"
            disabled={!canCreate || createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            {createMut.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Plus size={14} className="mr-1.5" />}
            {t('payroll.period_create', { defaultValue: 'Create period' })}
          </Button>
        </div>
      </div>
      {chosenProfile?.needs_expert_review && (
        <p className="text-xs text-semantic-warning">
          {t('payroll.profile_review', {
            defaultValue: 'This rule profile is a starting point. Have a payroll expert confirm it before you rely on it.',
          })}
        </p>
      )}

      {/* List */}
      {periods.length === 0 ? (
        <EmptyState
          title={t('payroll.periods_empty', { defaultValue: 'No pay periods yet' })}
          description={t('payroll.periods_empty_desc', {
            defaultValue: 'Choose the dates above to build the first period from your timesheets.',
          })}
        />
      ) : (
        <ul className="divide-y divide-border-light rounded-lg border border-border-light">
          {periods.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => {
                  setSelectedId((prev) => (prev === p.id ? null : p.id));
                  setExportErrors([]);
                }}
                className={clsx(
                  'flex w-full flex-wrap items-center gap-3 px-3 py-2 text-left text-sm hover:bg-surface-secondary/60',
                  selectedId === p.id && 'bg-surface-secondary/60',
                )}
              >
                <span className="font-medium text-content-primary">{p.label}</span>
                <span className="text-xs text-content-tertiary">
                  {p.period_start} - {p.period_end}
                </span>
                <Badge variant={statusVariant(p.status)} size="sm">
                  {statusLabel(p.status, t)}
                </Badge>
                <span className="ml-auto text-xs tabular-nums text-content-secondary">
                  {num(p.total_hours)} h · {num(p.total_gross)} {p.currency}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Detail */}
      {selectedId && detailQuery.isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
      {detail && (
        <div className="space-y-4 border-t border-border-light pt-4" data-testid="period-detail">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-content-primary">{detail.label}</h3>
            <Badge variant={statusVariant(detail.status)}>{statusLabel(detail.status, t)}</Badge>
            <span className="text-xs text-content-tertiary">
              {detail.country} · {detailProfile?.label ?? detail.rule_profile}
            </span>
            <span className="text-xs text-content-tertiary">
              {t('payroll.period_lines_count', {
                defaultValue_one: '{{count}} line',
                defaultValue_other: '{{count}} lines',
                count: detail.lines.length,
              })}
            </span>
          </div>

          {!isOpen && (
            <p className="rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-content-secondary" data-testid="locked-note">
              {t('payroll.locked_note', {
                defaultValue: 'This period is locked. Timesheets dated between {{from}} and {{to}} cannot be edited until you reopen it.',
                from: detail.period_start,
                to: detail.period_end,
              })}
            </p>
          )}

          {/* Totals by pay type */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-2xs uppercase text-content-tertiary">
                  <th className="py-2 pr-3">{t('payroll.col.pay_type', { defaultValue: 'Pay type' })}</th>
                  <th className="py-2 pr-3 text-right">{t('payroll.col.hours', { defaultValue: 'Hours' })}</th>
                  <th className="py-2 text-right">{t('payroll.col.amount', { defaultValue: 'Amount' })}</th>
                </tr>
              </thead>
              <tbody>
                {PAY_TYPES.filter((pt) => detail.totals_by_type[pt]).map((pt) => (
                  <tr key={pt} className="border-b border-border-light/60">
                    <td className="py-1.5 pr-3">{payTypeLabel(pt, t)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{num(detail.totals_by_type[pt]?.hours ?? '0')}</td>
                    <td className="py-1.5 text-right tabular-nums">
                      {num(detail.totals_by_type[pt]?.amount ?? '0')} {detail.currency}
                    </td>
                  </tr>
                ))}
                <tr className="font-semibold">
                  <td className="py-1.5 pr-3">{t('payroll.total', { defaultValue: 'Total' })}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{num(detail.total_hours)}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {num(detail.total_gross)} {detail.currency}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Actions */}
          <div className="flex flex-wrap gap-2">
            {isOpen && (
              <>
                <Button variant="secondary" size="sm" disabled={rebuildMut.isPending} onClick={() => rebuildMut.mutate(detail.id)}>
                  <RefreshCw size={14} className="mr-1.5" />
                  {t('payroll.period_rebuild', { defaultValue: 'Rebuild from timesheets' })}
                </Button>
                <Button variant="primary" size="sm" disabled={lockMut.isPending} onClick={() => lockMut.mutate(detail.id)}>
                  <Lock size={14} className="mr-1.5" />
                  {t('payroll.period_lock', { defaultValue: 'Lock period' })}
                </Button>
              </>
            )}
            {!isOpen && (
              <>
                <Button variant="secondary" size="sm" onClick={() => setReopenOpen(true)}>
                  <LockOpen size={14} className="mr-1.5" />
                  {t('payroll.period_reopen', { defaultValue: 'Reopen period' })}
                </Button>
                <Button variant="secondary" size="sm" disabled={postMut.isPending} onClick={() => postMut.mutate(detail.id)}>
                  <Coins size={14} className="mr-1.5" />
                  {t('payroll.period_post_costs', { defaultValue: 'Post labour cost' })}
                </Button>
              </>
            )}
          </div>

          {/* Export */}
          <div className="space-y-2 rounded-lg border border-border-light p-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-content-secondary">
                {t('payroll.export_format', { defaultValue: 'Export format' })}
                <select
                  className={clsx(SELECT_CLASS, 'mt-1 block')}
                  value={format}
                  onChange={(e) => setFormat(e.target.value as PeriodExportFormat)}
                  aria-label={t('payroll.export_format', { defaultValue: 'Export format' })}
                >
                  <option value="csv">CSV</option>
                  <option value="xlsx">XLSX</option>
                  <option value="json">JSON</option>
                  {detailProfile?.has_lodas && <option value="lodas">LODAS</option>}
                </select>
              </label>
              {format === 'lodas' && (
                <>
                  <Input
                    label={t('payroll.consultant_number', { defaultValue: 'Consultant number' })}
                    value={consultant}
                    onChange={(e) => setConsultant(e.target.value)}
                  />
                  <Input
                    label={t('payroll.client_number', { defaultValue: 'Client number' })}
                    value={client}
                    onChange={(e) => setClient(e.target.value)}
                  />
                </>
              )}
              <Button
                variant="primary"
                size="sm"
                disabled={exportMut.isPending || lodasNeedsNumbers || (columnsApply && columns.length === 0)}
                onClick={() => exportMut.mutate(detail.id)}
              >
                {exportMut.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Download size={14} className="mr-1.5" />}
                {t('payroll.period_export', { defaultValue: 'Export period' })}
              </Button>
            </div>
            {format === 'lodas' && lodasNeedsNumbers && (
              <p className="text-xs text-content-tertiary">
                {t('payroll.lodas_numbers_hint', { defaultValue: 'LODAS needs the consultant number and the client number.' })}
              </p>
            )}
            {columnsApply && (
              <fieldset>
                <legend className="text-xs font-medium text-content-secondary">
                  {t('payroll.export_columns', { defaultValue: 'Columns' })}
                </legend>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                  {EXPORT_COLUMNS.map((c) => (
                    <label key={c} className="flex items-center gap-1.5 text-xs text-content-secondary">
                      <input type="checkbox" checked={columns.includes(c)} onChange={() => toggleColumn(c)} />
                      {columnLabel(c, t)}
                    </label>
                  ))}
                </div>
              </fieldset>
            )}
            {exportErrors.length > 0 && (
              <div role="alert" className="rounded-lg bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error" data-testid="export-errors">
                <p className="font-semibold">{t('payroll.export_blocked', { defaultValue: 'Export is blocked' })}</p>
                <ul className="mt-1 list-disc pl-4">
                  {exportErrors.map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Findings */}
          {detail.findings.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-semibold text-content-primary">
                {t('payroll.findings', { defaultValue: 'Findings' })}
              </h4>
              <ul className="space-y-1">
                {detail.findings.map((f, i) => (
                  <li key={`${f.rule_id}-${i}`} className="flex items-start gap-2 text-xs text-content-secondary">
                    <Badge variant={f.severity === 'error' ? 'error' : f.severity === 'warning' ? 'warning' : 'neutral'} size="sm">
                      {f.severity}
                    </Badge>
                    <span>{f.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Lines */}
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-primary">
                <tr className="border-b border-border-light text-left text-2xs uppercase text-content-tertiary">
                  <th className="py-2 pr-3">{t('payroll.col.employee', { defaultValue: 'Employee' })}</th>
                  <th className="py-2 pr-3">{t('payroll.col.date', { defaultValue: 'Date' })}</th>
                  <th className="py-2 pr-3">{t('payroll.col.pay_type', { defaultValue: 'Pay type' })}</th>
                  <th className="py-2 pr-3">{t('payroll.col.cost_code', { defaultValue: 'Cost code' })}</th>
                  <th className="py-2 pr-3 text-right">{t('payroll.col.hours', { defaultValue: 'Hours' })}</th>
                  <th className="py-2 pr-3 text-right">{t('payroll.col.rate', { defaultValue: 'Rate' })}</th>
                  <th className="py-2 text-right">{t('payroll.col.amount', { defaultValue: 'Amount' })}</th>
                </tr>
              </thead>
              <tbody>
                {detail.lines.map((l) => (
                  <tr key={l.id} className="border-b border-border-light/60">
                    <td className="py-1.5 pr-3">{l.employee_name}</td>
                    <td className="py-1.5 pr-3">{l.work_date}</td>
                    <td className="py-1.5 pr-3">{payTypeLabel(l.pay_type, t)}</td>
                    <td className="py-1.5 pr-3">{l.cost_code ?? '-'}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{num(l.hours)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{num(l.rate)}</td>
                    <td className="py-1.5 text-right tabular-nums">{num(l.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Audit trail */}
          <div>
            <h4 className="mb-1 text-xs font-semibold text-content-primary">
              {t('payroll.audit_trail', { defaultValue: 'Audit trail' })}
            </h4>
            {detail.events.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('payroll.audit_empty', { defaultValue: 'No events yet.' })}
              </p>
            ) : (
              <ul className="space-y-1" data-testid="audit-trail">
                {detail.events.map((e, i) => (
                  <li key={i} className="text-xs text-content-secondary">
                    <span className="tabular-nums text-content-tertiary">{e.created_at.slice(0, 16).replace('T', ' ')}</span>{' '}
                    <span className="font-medium">{e.action}</span>
                    {e.reason && <span>: {e.reason}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {reopenOpen && detail && (
        <ReopenDialog
          busy={reopenMut.isPending}
          onCancel={() => setReopenOpen(false)}
          onConfirm={(reason) => reopenMut.mutate({ id: detail.id, reason })}
        />
      )}
    </Card>
  );
}
