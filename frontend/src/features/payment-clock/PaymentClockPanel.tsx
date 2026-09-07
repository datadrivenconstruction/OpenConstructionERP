// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Payment Clock — the statutory payment timetable on one project.
 *
 * The module answers one question and the screen is arranged around it: given
 * what was applied for and which notices were actually served, what sum is
 * payable and by when. That answer is `notified_sum`, so it leads the detail
 * pane rather than sitting at the bottom of a table.
 *
 * Reading a clock is what refreshes its breach register on the server, so the
 * register can gain rows from a plain read. That is deliberate upstream — a
 * deadline passes unattended — and it means the detail query must not be
 * cached so long that a reader sees a stale register.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CalendarClock, Plus, RefreshCw, Scale } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  type ApplicationClock,
  type ApplicationStatus,
  type PaymentApplication,
  type Regime,
  getClock,
  listApplications,
  listEvents,
  listRegimes,
  openClock,
  recomputeClock,
} from './api';
import { isOverdue, severityVariant } from './clockStatus';

const STATUS_VARIANT: Record<ApplicationStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  open: 'blue',
  paid: 'success',
  disputed: 'warning',
  closed: 'neutral',
};


export function PaymentClockPanel() {
  const { t } = useTranslation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const regimesQuery = useQuery({
    queryKey: ['payment-clock', 'regimes'],
    queryFn: () => listRegimes(),
    staleTime: 5 * 60 * 1000,
  });

  const applicationsQuery = useQuery({
    queryKey: ['payment-clock', 'applications', activeProjectId],
    queryFn: () => listApplications({ projectId: activeProjectId as string }),
    enabled: !!activeProjectId,
  });

  const eventsQuery = useQuery({
    queryKey: ['payment-clock', 'events', activeProjectId],
    queryFn: () => listEvents({ projectId: activeProjectId as string }),
    enabled: !!activeProjectId,
  });

  const clockQuery = useQuery({
    queryKey: ['payment-clock', 'clock', selectedId],
    queryFn: () => getClock(selectedId as string),
    enabled: !!selectedId,
    // Reading writes the register, so a long cache would show a register that
    // is older than the answer printed beside it.
    staleTime: 0,
  });

  const recompute = useMutation({
    mutationFn: (vars: { id: string; force: boolean }) => recomputeClock(vars.id, vars.force),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('payment_clock.recomputed', { defaultValue: 'Statutory dates recomputed.' }),
      });
      void queryClient.invalidateQueries({ queryKey: ['payment-clock'] });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('payment_clock.recompute_failed', { defaultValue: 'Could not recompute the dates' }),
        message: getErrorMessage(err),
      });
    },
  });

  if (!activeProjectId) {
    return (
      <EmptyState
        icon={<Scale className="h-8 w-8" />}
        title={t('payment_clock.no_project_title', { defaultValue: 'Pick a project first' })}
        description={t('payment_clock.no_project_body', {
          defaultValue:
            'A payment clock runs against one project, because the statutory regime and the contract dates belong to it.',
        })}
      />
    );
  }

  const applications = applicationsQuery.data ?? [];
  const events = eventsQuery.data ?? [];
  const regimes = regimesQuery.data ?? [];
  const overdueCount = applications.filter((a) => isOverdue(a, today)).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" onClick={() => setCreating((v) => !v)}>
          <Plus className="mr-1 h-4 w-4" />
          {t('payment_clock.open_clock', { defaultValue: 'Open a clock' })}
        </Button>
        <span className="text-sm text-content-secondary">
          {t('payment_clock.summary_counts', {
            defaultValue: '{{total}} on this project, {{overdue}} past the final date',
            total: applications.length,
            overdue: overdueCount,
          })}
        </span>
        {overdueCount > 0 && (
          <Badge variant="error" dot>
            {t('payment_clock.overdue_badge', { defaultValue: 'Payment overdue' })}
          </Badge>
        )}
      </div>

      {creating && (
        <NewClockForm
          projectId={activeProjectId}
          regimes={regimes}
          onDone={(created) => {
            setCreating(false);
            setSelectedId(created.id);
            void queryClient.invalidateQueries({ queryKey: ['payment-clock'] });
          }}
          onCancel={() => setCreating(false)}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <section aria-label={t('payment_clock.list_label', { defaultValue: 'Payment clocks' })}>
          {applicationsQuery.isLoading ? (
            <p className="text-sm text-content-secondary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          ) : applications.length === 0 ? (
            <EmptyState
              icon={<CalendarClock className="h-8 w-8" />}
              title={t('payment_clock.empty_title', { defaultValue: 'No payment clocks yet' })}
              description={t('payment_clock.empty_body', {
                defaultValue:
                  'Open a clock over a payment application and the statutory due date, notice deadline and final date are computed from the regime you pick.',
              })}
            />
          ) : (
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {applications.map((app) => (
                <li key={app.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(app.id)}
                    aria-current={selectedId === app.id}
                    className={`flex w-full flex-col gap-1 p-3 text-left hover:bg-surface-secondary ${
                      selectedId === app.id ? 'bg-surface-secondary' : ''
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="font-medium">
                        {app.reference ||
                          t('payment_clock.unreferenced', { defaultValue: 'No reference' })}
                      </span>
                      <Badge variant={STATUS_VARIANT[app.status]} size="sm">
                        {t(`payment_clock.status.${app.status}`, { defaultValue: app.status })}
                      </Badge>
                      {isOverdue(app, today) && (
                        <Badge variant="error" size="sm">
                          {t('payment_clock.overdue_badge', { defaultValue: 'Payment overdue' })}
                        </Badge>
                      )}
                    </span>
                    <span className="text-sm text-content-secondary">
                      {formatCurrency(app.applied_amount, app.currency)}
                      {' · '}
                      {app.jurisdiction || app.regime_code}
                    </span>
                    <span className="text-xs text-content-tertiary">
                      {t('payment_clock.final_date_short', {
                        defaultValue: 'Final date {{date}}',
                        date: app.final_date || '-',
                      })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label={t('payment_clock.detail_label', { defaultValue: 'Clock detail' })}>
          {!selectedId ? (
            <EmptyState
              icon={<Scale className="h-8 w-8" />}
              title={t('payment_clock.pick_title', { defaultValue: 'Pick a clock' })}
              description={t('payment_clock.pick_body', {
                defaultValue: 'The computed dates, the sum that is payable and why, and any breaches on record.',
              })}
            />
          ) : clockQuery.isLoading ? (
            <p className="text-sm text-content-secondary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          ) : clockQuery.data ? (
            <ClockDetail
              clock={clockQuery.data}
              onRecompute={(force) => recompute.mutate({ id: clockQuery.data.application.id, force })}
              recomputing={recompute.isPending}
            />
          ) : null}
        </section>
      </div>

      {events.length > 0 && (
        <section aria-label={t('payment_clock.register_label', { defaultValue: 'Breach register' })}>
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle className="h-4 w-4 text-semantic-warning" />
            {t('payment_clock.register_title', { defaultValue: 'Breach register' })}
          </h3>
          <p className="mb-2 text-xs text-content-tertiary">
            {t('payment_clock.register_note', {
              defaultValue:
                'Every row here was written by a validation rule when a clock was read. A quiet register on a project nobody opens is telling you about the reading, not about the payments.',
            })}
          </p>
          <ul className="space-y-1">
            {events.map((ev) => (
              <li key={ev.id} className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant={severityVariant(ev.severity)} size="sm">
                  {t(`payment_clock.event.${ev.event_type}`, { defaultValue: ev.event_type })}
                </Badge>
                <span className="text-content-secondary">{ev.consequence}</span>
                {ev.days_late !== null && (
                  <span className="text-xs text-content-tertiary">
                    {t('payment_clock.days_late', {
                      defaultValue: '{{count}} days late',
                      count: ev.days_late,
                    })}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/* ── Detail ────────────────────────────────────────────────────────────── */

function ClockDetail({
  clock,
  onRecompute,
  recomputing,
}: {
  clock: ApplicationClock;
  onRecompute: (force: boolean) => void;
  recomputing: boolean;
}) {
  const { t } = useTranslation();
  const app = clock.application;
  const sum = clock.notified_sum;

  return (
    <div className="space-y-4 rounded-lg border border-border-light p-4">
      {/* The answer the module exists to give, so it leads. */}
      <div>
        <p className="text-xs uppercase tracking-wide text-content-tertiary">
          {t('payment_clock.notified_sum_label', { defaultValue: 'Sum payable' })}
        </p>
        <p className="text-2xl font-semibold">
          {sum.amount === null
            ? t('payment_clock.notified_sum_undetermined', { defaultValue: 'Not yet determined' })
            : formatCurrency(sum.amount, sum.currency || app.currency)}
        </p>
        {sum.explanation && (
          <p className="mt-1 text-sm text-content-secondary">
            {/* The server assembles the sentence in English because it can only
                assemble it in one language. It also names which sentence it is,
                so it can be said here instead. The prose stays the fallback: a
                reading stored before the codes existed carries no reason. */}
            {sum.reason
              ? t(`payment_clock.sum_reason_${sum.reason}`, {
                  defaultValue: sum.explanation,
                  ...(sum.params ?? {}),
                })
              : sum.explanation}
          </p>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <DateRow label={t('payment_clock.due_date', { defaultValue: 'Due date' })} value={app.due_date} />
        <DateRow
          label={t('payment_clock.notice_deadline', { defaultValue: 'Payment notice deadline' })}
          value={app.payment_notice_deadline}
        />
        <DateRow
          label={t('payment_clock.pay_less_deadline', { defaultValue: 'Pay less notice deadline' })}
          value={app.pay_less_deadline}
        />
        <DateRow
          label={t('payment_clock.final_date', { defaultValue: 'Final date for payment' })}
          value={app.final_date}
        />
      </dl>

      {app.dates_overridden && (
        <p className="text-xs text-content-tertiary">
          {t('payment_clock.dates_overridden', {
            defaultValue:
              'These dates were stated rather than computed, so a recompute leaves them alone unless it is forced.',
          })}
        </p>
      )}

      <div className="flex gap-2">
        <Button size="sm" variant="secondary" onClick={() => onRecompute(false)} disabled={recomputing}>
          <RefreshCw className="mr-1 h-4 w-4" />
          {t('payment_clock.recompute', { defaultValue: 'Recompute dates' })}
        </Button>
        {app.dates_overridden && (
          <Button size="sm" variant="ghost" onClick={() => onRecompute(true)} disabled={recomputing}>
            {t('payment_clock.recompute_force', { defaultValue: 'Replace the stated dates' })}
          </Button>
        )}
      </div>

      {clock.findings.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-semibold">
            {t('payment_clock.findings_title', { defaultValue: 'What the rules say' })}
          </h4>
          <ul className="space-y-1">
            {clock.findings.map((f) => (
              <li key={f.rule_id} className="flex items-start gap-2 text-sm">
                <Badge variant={severityVariant(f.severity)} size="sm">
                  {f.severity}
                </Badge>
                <span>
                  {/* The rule's English is the fallback for a locale that has
                      no string for this key yet. */}
                  {t(f.key, { defaultValue: f.message })}
                  {f.suggestion && (
                    <em className="block text-xs not-italic text-content-tertiary">{f.suggestion}</em>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {clock.notices.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-semibold">
            {t('payment_clock.notices_title', { defaultValue: 'Notices served' })}
          </h4>
          <ul className="space-y-1 text-sm">
            {clock.notices.map((n) => (
              <li key={n.id} className="flex flex-wrap items-center gap-2">
                <Badge variant="neutral" size="sm">
                  {t(`payment_clock.notice_type.${n.notice_type}`, { defaultValue: n.notice_type })}
                </Badge>
                {/* A notice is evidence of a date, so it says the date the
                    reader's language writes rather than the wire's ISO. */}
                <span>{fmtDate(n.issued_at)}</span>
                {n.notified_amount !== null && (
                  <span className="text-content-secondary">
                    {formatCurrency(n.notified_amount, n.currency || app.currency)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {clock.derivation.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-content-secondary">
            {t('payment_clock.derivation_title', { defaultValue: 'How these dates were derived' })}
          </summary>
          <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-content-secondary">
            {clock.derivation.map((line, i) => (
              <li key={`${i}-${line}`}>{line}</li>
            ))}
          </ol>
        </details>
      )}

      {clock.interest_description && (
        <p className="text-xs text-content-tertiary">{clock.interest_description}</p>
      )}
    </div>
  );
}

function DateRow({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <dt className="text-content-secondary">{label}</dt>
      <dd className="font-medium">{value || '-'}</dd>
    </>
  );
}

/* ── Create ────────────────────────────────────────────────────────────── */

function NewClockForm({
  projectId,
  regimes,
  onDone,
  onCancel,
}: {
  projectId: string;
  regimes: Regime[];
  onDone: (created: PaymentApplication) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [regimeCode, setRegimeCode] = useState('');
  const [reference, setReference] = useState('');
  const [applicationDate, setApplicationDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [appliedAmount, setAppliedAmount] = useState('');
  const [currency, setCurrency] = useState('');

  const create = useMutation({
    mutationFn: () =>
      openClock({
        project_id: projectId,
        regime_code: regimeCode,
        reference,
        application_date: applicationDate,
        applied_amount: toDecimalPayloadString(appliedAmount),
        currency: currency.toUpperCase(),
      }),
    onSuccess: onDone,
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('payment_clock.create_failed', { defaultValue: 'Could not open the clock' }),
        message: getErrorMessage(err),
      }),
  });

  // The currency follows the regime unless the user has already typed one:
  // these regimes span six jurisdictions and an implied currency is a bug
  // waiting for a cross-border job, so it is prefilled but never forced.
  const onRegimeChange = (code: string) => {
    setRegimeCode(code);
    if (!currency) {
      const picked = regimes.find((r) => r.code === code);
      if (picked) setCurrency(guessCurrency(picked.country_code));
    }
  };

  const ready = regimeCode && applicationDate && appliedAmount && currency.length === 3;

  return (
    <form
      className="grid gap-3 rounded-lg border border-border-light p-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) create.mutate();
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        {t('payment_clock.field_regime', { defaultValue: 'Statutory regime' })}
        <select
          value={regimeCode}
          onChange={(e) => onRegimeChange(e.target.value)}
          className="rounded border border-border-light bg-surface-primary p-2"
          required
        >
          <option value="">
            {t('payment_clock.field_regime_pick', { defaultValue: 'Pick a regime' })}
          </option>
          {regimes.map((r) => (
            <option key={r.id} value={r.code}>
              {r.jurisdiction} - {r.statute}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t('payment_clock.field_reference', { defaultValue: 'Reference' })}
        <input
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          maxLength={64}
          className="rounded border border-border-light bg-surface-primary p-2"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t('payment_clock.field_application_date', { defaultValue: 'Application date' })}
        <input
          type="date"
          value={applicationDate}
          onChange={(e) => setApplicationDate(e.target.value)}
          className="rounded border border-border-light bg-surface-primary p-2"
          required
        />
      </label>

      <div className="grid grid-cols-[1fr_6rem] gap-2">
        <label className="flex flex-col gap-1 text-sm">
          {t('payment_clock.field_applied_amount', { defaultValue: 'Applied amount' })}
          <input
            inputMode="decimal"
            value={appliedAmount}
            onChange={(e) => setAppliedAmount(e.target.value)}
            className="rounded border border-border-light bg-surface-primary p-2"
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t('payment_clock.field_currency', { defaultValue: 'Currency' })}
          <input
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase().slice(0, 3))}
            maxLength={3}
            className="rounded border border-border-light bg-surface-primary p-2 uppercase"
            required
          />
        </label>
      </div>

      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" size="sm" disabled={!ready || create.isPending}>
          {t('payment_clock.create_submit', { defaultValue: 'Open the clock' })}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </form>
  );
}

/**
 * The regime carries a country, not a currency, so this is a prefill and the
 * field stays editable. A job billed in another currency is ordinary.
 */
function guessCurrency(countryCode: string): string {
  const byCountry: Record<string, string> = {
    GB: 'GBP',
    IE: 'EUR',
    DE: 'EUR',
    AU: 'AUD',
    NZ: 'NZD',
    SG: 'SGD',
    MY: 'MYR',
    US: 'USD',
    CA: 'CAD',
    AE: 'AED',
  };
  return byCountry[(countryCode || '').toUpperCase()] ?? '';
}
