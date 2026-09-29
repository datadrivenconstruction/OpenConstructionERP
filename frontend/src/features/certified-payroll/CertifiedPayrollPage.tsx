// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Plus,
  ScrollText,
  Users,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Download,
  Gavel,
  Lock,
  Trash2,
  ShieldCheck,
  FileSignature,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  Badge,
  Input,
  EmptyState,
  Breadcrumb,
  ConfirmDialog,
  Skeleton,
  CollapsibleSection,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { NoAccessState } from '@/shared/ui/NoAccessState';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useToastStore } from '@/stores/useToastStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  listDeterminations,
  createDetermination,
  deleteDetermination,
  listAssignments,
  createAssignment,
  deleteAssignment,
  listWeeks,
  createWeek,
  getWeek,
  validateWeek,
  certifyWeek,
  downloadWeekForm,
} from './api';
import type {
  WageDetermination,
  DeterminationAuthority,
  FringeElection,
  CertifiedWeek,
  CertifiedLine,
} from './api';

/* ── Helpers ───────────────────────────────────────────────────────────── */

function money(value: string | number, currency?: string): string {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return n.toFixed(2);
  }
}

function hoursOf(value: string | undefined): string {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? fmtFixed(n, 2) : String(value ?? '0');
}

/** The seven ISO dates of the week ending on `weekEnding`, earliest first. */
function weekDays(weekEnding: string): string[] {
  const end = new Date(`${weekEnding}T00:00:00Z`);
  if (Number.isNaN(end.getTime())) return [];
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(end);
    d.setUTCDate(d.getUTCDate() - (6 - i));
    return d.toISOString().slice(0, 10);
  });
}

/** The total package: basic wage plus fringe. Display only - never stored. */
function packageOf(basic: string, fringe: string): number {
  return Number(basic || 0) + Number(fringe || 0);
}

type TabKey = 'weeks' | 'determinations' | 'workers';

/* ── Page ──────────────────────────────────────────────────────────────── */

export function CertifiedPayrollPage() {
  const { t } = useTranslation();
  const projectId = useActiveProjectId();
  const [tab, setTab] = useState<TabKey>('weeks');
  // Every tab reads through certified_payroll.read (manager and above). Below
  // that the explainer stays and the tabs give way to a plain no-access note.
  const canRead = useHasPermission('certified_payroll.read');

  return (
    <RequiresProject>
      <div className="space-y-6">
        <Breadcrumb
          items={[
            { label: t('nav.payroll'), to: '/payroll' },
            { label: t('certified_payroll.title') },
          ]}
        />
        <PageHeader
          srTitle={t('certified_payroll.title')}
          subtitle={t('certified_payroll.subtitle')}
        />

        {/* Explainer sits at page level, above the tab strip, so switching a
            tab never makes the explanation disappear. */}
        <CollapsibleSection
          title={t('certified_payroll.how.title')}
          storageKey="certified_payroll.how"
        >
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>{t('certified_payroll.how.intro')}</p>
            <ol className="list-decimal space-y-1 pl-5">
              <li>{t('certified_payroll.how.step1')}</li>
              <li>{t('certified_payroll.how.step2')}</li>
              <li>{t('certified_payroll.how.step3')}</li>
              <li>{t('certified_payroll.how.step4')}</li>
            </ol>
            <p className="text-xs">
              {t('certified_payroll.how.related')}{' '}
              <Link className="underline" to="/payroll">
                {t('nav.payroll')}
              </Link>
              {' · '}
              <Link className="underline" to="/field-time">
                {t('nav.field_time')}
              </Link>
            </p>
            <p className="rounded-md bg-muted/50 p-3 text-xs">
              {t('certified_payroll.how.no_rate_table')}
            </p>
          </div>
        </CollapsibleSection>

        {!canRead && <NoAccessState />}

        {canRead && (
          <div className="flex gap-1 border-b border-border">
            {(['weeks', 'determinations', 'workers'] as TabKey[]).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={clsx(
                  'px-4 py-2 text-sm font-medium transition-colors',
                  tab === key
                    ? 'border-b-2 border-primary text-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t(`certified_payroll.tab.${key}`)}
              </button>
            ))}
          </div>
        )}

        {canRead && projectId && tab === 'weeks' && <WeeksTab projectId={projectId} />}
        {canRead && projectId && tab === 'determinations' && <DeterminationsTab projectId={projectId} />}
        {canRead && projectId && tab === 'workers' && <WorkersTab projectId={projectId} />}
      </div>
    </RequiresProject>
  );
}

/* ── Weeks ─────────────────────────────────────────────────────────────── */

function WeeksTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const [selected, setSelected] = useState<string | null>(null);
  const [weekEnding, setWeekEnding] = useState('');
  const [payrollNumber, setPayrollNumber] = useState('');
  const [dailyThreshold, setDailyThreshold] = useState('8');
  const [weeklyThreshold, setWeeklyThreshold] = useState('40');

  const weeks = useQuery({
    queryKey: ['certpay', 'weeks', projectId],
    queryFn: () => listWeeks(projectId),
  });

  const create = useMutation({
    mutationFn: () =>
      createWeek(projectId, {
        week_ending: weekEnding,
        payroll_number: payrollNumber,
        daily_overtime_threshold: dailyThreshold || null,
        weekly_overtime_threshold: weeklyThreshold || null,
      }),
    onSuccess: (week) => {
      toast({ type: 'success', title: t('certified_payroll.week.created') });
      setWeekEnding('');
      setPayrollNumber('');
      setSelected(week.id);
      void qc.invalidateQueries({ queryKey: ['certpay', 'weeks', projectId] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (weeks.isLoading) return <Skeleton className="h-48 w-full" />;

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">{t('certified_payroll.week.open')}</h3>
        <div className="grid gap-3 sm:grid-cols-4">
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">{t('certified_payroll.week.week_ending')}</span>
            <Input type="date" value={weekEnding} onChange={(e) => setWeekEnding(e.target.value)} />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">
              {t('certified_payroll.week.payroll_number')}
            </span>
            <Input value={payrollNumber} onChange={(e) => setPayrollNumber(e.target.value)} />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">
              {t('certified_payroll.week.daily_threshold')}
            </span>
            <Input value={dailyThreshold} onChange={(e) => setDailyThreshold(e.target.value)} />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">
              {t('certified_payroll.week.weekly_threshold')}
            </span>
            <Input value={weeklyThreshold} onChange={(e) => setWeeklyThreshold(e.target.value)} />
          </label>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('certified_payroll.week.threshold_hint')}
        </p>
        <Button
          onClick={() => create.mutate()}
          disabled={!weekEnding || create.isPending}
          className="w-fit"
        >
          {create.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Plus className="mr-2 h-4 w-4" />
          )}
          {t('certified_payroll.week.open_action')}
        </Button>
      </Card>

      {(weeks.data ?? []).length === 0 ? (
        <EmptyState
          icon={<ScrollText className="h-8 w-8" />}
          title={t('certified_payroll.week.empty_title')}
          description={t('certified_payroll.week.empty_body')}
        />
      ) : (
        <div className="space-y-2">
          {(weeks.data ?? []).map((week) => (
            <WeekRow
              key={week.id}
              week={week}
              expanded={selected === week.id}
              onToggle={() => setSelected(selected === week.id ? null : week.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function WeekRow({
  week,
  expanded,
  onToggle,
}: {
  week: CertifiedWeek;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 p-4 text-left"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium">
              {t('certified_payroll.week.ending', { date: week.week_ending })}
            </span>
            {week.payroll_number && (
              <Badge variant="neutral">
                {t('certified_payroll.week.number', { number: week.payroll_number })}
              </Badge>
            )}
            {week.is_final && <Badge variant="neutral">{t('certified_payroll.week.final')}</Badge>}
          </div>
          {week.status === 'certified' && week.signatory_name && (
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {t('certified_payroll.week.signed_by', {
                name: week.signatory_name,
                title: week.signatory_title ?? '',
              })}
            </p>
          )}
        </div>
        <Badge variant={week.status === 'certified' ? 'success' : 'neutral'}>
          {t(`certified_payroll.status.${week.status}`)}
        </Badge>
      </button>
      {expanded && <WeekDetail weekId={week.id} />}
    </Card>
  );
}

function WeekDetail({ weekId }: { weekId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const [signatoryName, setSignatoryName] = useState('');
  const [signatoryTitle, setSignatoryTitle] = useState('');
  const [election, setElection] = useState<FringeElection>('plan');
  const [confirmCertify, setConfirmCertify] = useState(false);

  const detail = useQuery({
    queryKey: ['certpay', 'week', weekId],
    queryFn: () => getWeek(weekId),
  });
  const validation = useQuery({
    queryKey: ['certpay', 'validate', weekId],
    queryFn: () => validateWeek(weekId),
  });

  const certify = useMutation({
    mutationFn: () =>
      certifyWeek(weekId, {
        signatory_name: signatoryName,
        signatory_title: signatoryTitle,
        fringe_election: election,
      }),
    onSuccess: () => {
      toast({ type: 'success', title: t('certified_payroll.certify.done') });
      void qc.invalidateQueries({ queryKey: ['certpay'] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (detail.isLoading) return <div className="p-4"><Skeleton className="h-40 w-full" /></div>;
  const week = detail.data;
  if (!week) return null;

  const days = weekDays(week.week_ending);
  const findings = (validation.data?.findings ?? []).filter((f) => !f.passed);
  const errors = findings.filter((f) => f.severity === 'error');
  const warnings = findings.filter((f) => f.severity === 'warning');
  const isDraft = week.status === 'draft';

  return (
    <div className="space-y-4 border-t border-border p-4">
      {week.lines_are_derived && (
        <p className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
          {t('certified_payroll.week.derived_note')}
        </p>
      )}

      {/* Compliance findings */}
      {validation.isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            {errors.length === 0 ? (
              <>
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                <span>{t('certified_payroll.validation.clean')}</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-4 w-4 text-destructive" />
                <span>
                  {t('certified_payroll.validation.blocked', { count: errors.length })}
                </span>
              </>
            )}
            {warnings.length > 0 && (
              <Badge variant="neutral">
                {t('certified_payroll.validation.warnings', { count: warnings.length })}
              </Badge>
            )}
          </div>
          {findings.map((f) => (
            <div
              key={`${f.rule_id}-${f.element_ref ?? ''}-${f.message.slice(0, 24)}`}
              className={clsx(
                'rounded-md border p-3 text-xs',
                f.severity === 'error'
                  ? 'border-destructive/40 bg-destructive/5'
                  : 'border-amber-500/40 bg-amber-500/5',
              )}
            >
              <p className="font-medium">{f.rule_name}</p>
              <p className="mt-1 text-muted-foreground">{f.message}</p>
              {f.suggestion && <p className="mt-1 italic text-muted-foreground">{f.suggestion}</p>}
            </div>
          ))}
        </div>
      )}

      {/* The weekly grid */}
      {week.lines.length === 0 ? (
        <EmptyState
          icon={<ScrollText className="h-8 w-8" />}
          title={t('certified_payroll.week.no_lines_title')}
          description={t('certified_payroll.week.no_lines_body')}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[64rem] text-xs">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="p-2">{t('certified_payroll.col.worker')}</th>
                <th className="p-2">{t('certified_payroll.col.classification')}</th>
                {days.map((d) => (
                  <th key={d} className="p-2 text-right">
                    {d.slice(5)}
                  </th>
                ))}
                <th className="p-2 text-right">{t('certified_payroll.col.straight')}</th>
                <th className="p-2 text-right">{t('certified_payroll.col.overtime')}</th>
                <th className="p-2 text-right">{t('certified_payroll.col.basic_rate')}</th>
                <th className="p-2 text-right">{t('certified_payroll.col.fringe_rate')}</th>
                <th className="p-2 text-right">{t('certified_payroll.col.gross')}</th>
                <th className="p-2 text-right">{t('certified_payroll.col.deductions')}</th>
                <th className="p-2 text-right">{t('certified_payroll.col.net')}</th>
              </tr>
            </thead>
            <tbody>
              {week.lines.map((line: CertifiedLine, idx) => (
                <tr key={line.id ?? `${line.worker_name}-${idx}`} className="border-b border-border/50">
                  <td className="p-2">
                    <div className="font-medium">{line.worker_name}</div>
                    {line.determination_identifier && (
                      <div className="text-muted-foreground">{line.determination_identifier}</div>
                    )}
                  </td>
                  <td className="p-2">
                    {line.classification_title || (
                      <span className="text-destructive">
                        {t('certified_payroll.col.unclassified')}
                      </span>
                    )}
                  </td>
                  {days.map((d) => {
                    const cell = line.hours_by_day?.[d];
                    return (
                      <td key={d} className="p-2 text-right tabular-nums">
                        {hoursOf(cell?.straight)}
                        {Number(cell?.overtime ?? 0) > 0 && (
                          <span className="ml-1 text-amber-600">
                            +{hoursOf(cell?.overtime)}
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td className="p-2 text-right tabular-nums">{hoursOf(line.straight_hours)}</td>
                  <td className="p-2 text-right tabular-nums">{hoursOf(line.overtime_hours)}</td>
                  <td className="p-2 text-right tabular-nums">
                    {money(line.paid_basic_rate, line.currency)}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {money(line.paid_fringe_rate, line.currency)}
                    {line.fringe_election && (
                      <span className="ml-1 text-muted-foreground">
                        {t(`certified_payroll.election.${line.fringe_election}`)}
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {money(line.gross_amount, line.currency)}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {money(line.total_deductions, line.currency)}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {money(line.net_amount, line.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {week.governing_reason && (
        <p className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          <Gavel className="mr-1 inline h-3 w-3" />
          {week.governing_reason}
        </p>
      )}

      {/* Statement of compliance */}
      {isDraft ? (
        <Card className="space-y-3 p-4">
          <h4 className="flex items-center gap-2 text-sm font-semibold">
            <FileSignature className="h-4 w-4" />
            {t('certified_payroll.certify.title')}
          </h4>
          <p className="text-xs text-muted-foreground">{t('certified_payroll.certify.blurb')}</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">
                {t('certified_payroll.certify.signatory_name')}
              </span>
              <Input value={signatoryName} onChange={(e) => setSignatoryName(e.target.value)} />
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">
                {t('certified_payroll.certify.signatory_title')}
              </span>
              <Input value={signatoryTitle} onChange={(e) => setSignatoryTitle(e.target.value)} />
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">
                {t('certified_payroll.certify.election')}
              </span>
              <select
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={election}
                onChange={(e) => setElection(e.target.value as FringeElection)}
              >
                <option value="plan">{t('certified_payroll.election.plan')}</option>
                <option value="cash">{t('certified_payroll.election.cash')}</option>
                <option value="mixed">{t('certified_payroll.election.mixed')}</option>
              </select>
            </label>
          </div>
          <Button
            onClick={() => setConfirmCertify(true)}
            disabled={!signatoryName || !signatoryTitle || errors.length > 0 || certify.isPending}
            className="w-fit"
          >
            {certify.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <ShieldCheck className="mr-2 h-4 w-4" />
            )}
            {t('certified_payroll.certify.action')}
          </Button>
          {errors.length > 0 && (
            <p className="text-xs text-destructive">{t('certified_payroll.certify.blocked_hint')}</p>
          )}
        </Card>
      ) : (
        <Card className="space-y-2 p-4">
          <h4 className="flex items-center gap-2 text-sm font-semibold">
            <Lock className="h-4 w-4" />
            {t('certified_payroll.certify.signed_title')}
          </h4>
          <p className="whitespace-pre-wrap text-xs text-muted-foreground">{week.statement_text}</p>
        </Card>
      )}

      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void downloadWeekForm(week.id, week.week_ending, 'csv')}
        >
          <Download className="mr-2 h-4 w-4" />
          {t('certified_payroll.export.csv')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void downloadWeekForm(week.id, week.week_ending, 'json')}
        >
          <Download className="mr-2 h-4 w-4" />
          {t('certified_payroll.export.json')}
        </Button>
      </div>

      <ConfirmDialog
        open={confirmCertify}
        title={t('certified_payroll.certify.confirm_title')}
        message={t('certified_payroll.certify.confirm_body')}
        confirmLabel={t('certified_payroll.certify.action')}
        variant="warning"
        loading={certify.isPending}
        onCancel={() => setConfirmCertify(false)}
        onConfirm={() => {
          setConfirmCertify(false);
          certify.mutate();
        }}
      />
    </div>
  );
}

/* ── Determinations ────────────────────────────────────────────────────── */

function DeterminationsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const [authority, setAuthority] = useState<DeterminationAuthority>('federal');
  const [identifier, setIdentifier] = useState('');
  const [locality, setLocality] = useState('');
  const [effectiveDate, setEffectiveDate] = useState('');
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const determinations = useQuery({
    queryKey: ['certpay', 'determinations', projectId],
    queryFn: () => listDeterminations(projectId),
  });

  const create = useMutation({
    mutationFn: () =>
      createDetermination(projectId, {
        authority,
        identifier,
        locality,
        effective_date: effectiveDate || null,
      }),
    onSuccess: () => {
      toast({ type: 'success', title: t('certified_payroll.determination.created') });
      setIdentifier('');
      setLocality('');
      setEffectiveDate('');
      void qc.invalidateQueries({ queryKey: ['certpay', 'determinations', projectId] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteDetermination(id),
    onSuccess: () => {
      toast({ type: 'success', title: t('certified_payroll.determination.deleted') });
      void qc.invalidateQueries({ queryKey: ['certpay', 'determinations', projectId] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (determinations.isLoading) return <Skeleton className="h-48 w-full" />;

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">{t('certified_payroll.determination.add')}</h3>
        <p className="text-xs text-muted-foreground">
          {t('certified_payroll.determination.add_hint')}
        </p>
        <div className="grid gap-3 sm:grid-cols-4">
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">
              {t('certified_payroll.determination.authority')}
            </span>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={authority}
              onChange={(e) => setAuthority(e.target.value as DeterminationAuthority)}
            >
              <option value="federal">{t('certified_payroll.authority.federal')}</option>
              <option value="state">{t('certified_payroll.authority.state')}</option>
              <option value="awarding_body">
                {t('certified_payroll.authority.awarding_body')}
              </option>
            </select>
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">
              {t('certified_payroll.determination.identifier')}
            </span>
            <Input value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">
              {t('certified_payroll.determination.locality')}
            </span>
            <Input value={locality} onChange={(e) => setLocality(e.target.value)} />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">
              {t('certified_payroll.determination.effective_date')}
            </span>
            <Input
              type="date"
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
            />
          </label>
        </div>
        <Button
          onClick={() => create.mutate()}
          disabled={!identifier || create.isPending}
          className="w-fit"
        >
          <Plus className="mr-2 h-4 w-4" />
          {t('certified_payroll.determination.add_action')}
        </Button>
      </Card>

      {(determinations.data ?? []).length === 0 ? (
        <EmptyState
          icon={<Gavel className="h-8 w-8" />}
          title={t('certified_payroll.determination.empty_title')}
          description={t('certified_payroll.determination.empty_body')}
        />
      ) : (
        (determinations.data ?? []).map((d: WageDetermination) => (
          <Card key={d.id} className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{d.identifier}</span>
                  <Badge variant="neutral">
                    {t(`certified_payroll.authority.${d.authority}`)}
                  </Badge>
                  {d.locked && (
                    <Badge variant="neutral">
                      <Lock className="mr-1 h-3 w-3" />
                      {t('certified_payroll.determination.locked')}
                    </Badge>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {[d.locality, d.effective_date, d.statute_reference]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </div>
              {!d.locked && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPendingDelete(d.id)}
                  aria-label={t('certified_payroll.determination.delete')}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
            {d.classifications.length > 0 && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="p-2">{t('certified_payroll.col.classification')}</th>
                    <th className="p-2 text-right">{t('certified_payroll.col.basic_rate')}</th>
                    <th className="p-2 text-right">{t('certified_payroll.col.fringe_rate')}</th>
                    <th className="p-2 text-right">{t('certified_payroll.col.package')}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.classifications.map((c) => (
                    <tr key={c.id} className="border-b border-border/50">
                      <td className="p-2">
                        {c.title}
                        <span className="ml-2 text-muted-foreground">{c.code}</span>
                      </td>
                      <td className="p-2 text-right tabular-nums">
                        {money(c.basic_hourly_rate, d.currency)}
                      </td>
                      <td className="p-2 text-right tabular-nums">
                        {money(c.fringe_rate, d.currency)}
                      </td>
                      <td className="p-2 text-right tabular-nums">
                        {money(packageOf(c.basic_hourly_rate, c.fringe_rate), d.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        ))
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('certified_payroll.determination.delete_title')}
        message={t('certified_payroll.determination.delete_body')}
        confirmLabel={t('certified_payroll.determination.delete')}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) remove.mutate(pendingDelete);
          setPendingDelete(null);
        }}
      />
    </div>
  );
}

/* ── Workers ───────────────────────────────────────────────────────────── */

function WorkersTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const [workerName, setWorkerName] = useState('');
  const [classificationId, setClassificationId] = useState('');
  const [paidBasic, setPaidBasic] = useState('');
  const [paidFringe, setPaidFringe] = useState('');
  const [election, setElection] = useState<FringeElection>('plan');
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const determinations = useQuery({
    queryKey: ['certpay', 'determinations', projectId],
    queryFn: () => listDeterminations(projectId),
  });
  const assignments = useQuery({
    queryKey: ['certpay', 'assignments', projectId],
    queryFn: () => listAssignments(projectId),
  });

  const classificationLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of determinations.data ?? []) {
      for (const c of d.classifications) {
        map.set(c.id, `${c.title} (${d.identifier})`);
      }
    }
    return map;
  }, [determinations.data]);

  const create = useMutation({
    mutationFn: () =>
      createAssignment(projectId, {
        worker_name: workerName,
        classification_id: classificationId,
        paid_basic_rate: paidBasic || null,
        paid_fringe_rate: paidFringe || null,
        fringe_election: election,
      }),
    onSuccess: () => {
      toast({ type: 'success', title: t('certified_payroll.worker.created') });
      setWorkerName('');
      setPaidBasic('');
      setPaidFringe('');
      void qc.invalidateQueries({ queryKey: ['certpay', 'assignments', projectId] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteAssignment(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['certpay', 'assignments', projectId] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  const handleCreate = useCallback(() => create.mutate(), [create]);

  if (assignments.isLoading || determinations.isLoading) return <Skeleton className="h-48 w-full" />;

  const hasClassifications = classificationLabel.size > 0;

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-semibold">{t('certified_payroll.worker.add')}</h3>
        <p className="text-xs text-muted-foreground">{t('certified_payroll.worker.add_hint')}</p>
        {!hasClassifications ? (
          <p className="text-xs text-destructive">
            {t('certified_payroll.worker.needs_determination')}
          </p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-5">
              <label className="space-y-1 text-xs">
                <span className="text-muted-foreground">
                  {t('certified_payroll.worker.name')}
                </span>
                <Input value={workerName} onChange={(e) => setWorkerName(e.target.value)} />
              </label>
              <label className="space-y-1 text-xs">
                <span className="text-muted-foreground">
                  {t('certified_payroll.col.classification')}
                </span>
                <select
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={classificationId}
                  onChange={(e) => setClassificationId(e.target.value)}
                >
                  <option value="">{t('certified_payroll.worker.pick_classification')}</option>
                  {[...classificationLabel.entries()].map(([id, label]) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="text-muted-foreground">
                  {t('certified_payroll.col.basic_rate')}
                </span>
                <Input value={paidBasic} onChange={(e) => setPaidBasic(e.target.value)} />
              </label>
              <label className="space-y-1 text-xs">
                <span className="text-muted-foreground">
                  {t('certified_payroll.col.fringe_rate')}
                </span>
                <Input value={paidFringe} onChange={(e) => setPaidFringe(e.target.value)} />
              </label>
              <label className="space-y-1 text-xs">
                <span className="text-muted-foreground">
                  {t('certified_payroll.certify.election')}
                </span>
                <select
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={election}
                  onChange={(e) => setElection(e.target.value as FringeElection)}
                >
                  <option value="plan">{t('certified_payroll.election.plan')}</option>
                  <option value="cash">{t('certified_payroll.election.cash')}</option>
                  <option value="mixed">{t('certified_payroll.election.mixed')}</option>
                </select>
              </label>
            </div>
            <p className="text-xs text-muted-foreground">
              {t('certified_payroll.worker.split_hint')}
            </p>
            <Button
              onClick={handleCreate}
              disabled={!workerName || !classificationId || create.isPending}
              className="w-fit"
            >
              <Plus className="mr-2 h-4 w-4" />
              {t('certified_payroll.worker.add_action')}
            </Button>
          </>
        )}
      </Card>

      {(assignments.data ?? []).length === 0 ? (
        <EmptyState
          icon={<Users className="h-8 w-8" />}
          title={t('certified_payroll.worker.empty_title')}
          description={t('certified_payroll.worker.empty_body')}
        />
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="p-3">{t('certified_payroll.worker.name')}</th>
                <th className="p-3">{t('certified_payroll.col.classification')}</th>
                <th className="p-3 text-right">{t('certified_payroll.col.basic_rate')}</th>
                <th className="p-3 text-right">{t('certified_payroll.col.fringe_rate')}</th>
                <th className="p-3">{t('certified_payroll.certify.election')}</th>
                <th className="p-3" />
              </tr>
            </thead>
            <tbody>
              {(assignments.data ?? []).map((a) => (
                <tr key={a.id} className="border-b border-border/50">
                  <td className="p-3 font-medium">{a.worker_name}</td>
                  <td className="p-3">
                    {classificationLabel.get(a.classification_id) ?? a.classification_id}
                  </td>
                  <td className="p-3 text-right tabular-nums">
                    {a.paid_basic_rate ?? (
                      <span className="text-muted-foreground">
                        {t('certified_payroll.worker.derived')}
                      </span>
                    )}
                  </td>
                  <td className="p-3 text-right tabular-nums">
                    {a.paid_fringe_rate ?? (
                      <span className="text-muted-foreground">
                        {t('certified_payroll.worker.derived')}
                      </span>
                    )}
                  </td>
                  <td className="p-3">
                    {a.fringe_election
                      ? t(`certified_payroll.election.${a.fringe_election}`)
                      : '-'}
                  </td>
                  <td className="p-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setPendingDelete(a.id)}
                      aria-label={t('certified_payroll.worker.delete')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('certified_payroll.worker.delete_title')}
        message={t('certified_payroll.worker.delete_body')}
        confirmLabel={t('certified_payroll.worker.delete')}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) remove.mutate(pendingDelete);
          setPendingDelete(null);
        }}
      />
    </div>
  );
}

export default CertifiedPayrollPage;
