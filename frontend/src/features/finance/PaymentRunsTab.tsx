// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Banknote, Download, Lock, Trash2, XCircle } from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button, Card, ConfirmDialog, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ApiError } from '@/shared/lib/api';
import { todayLocalISO } from '@/shared/lib/dates';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { legalEntitiesApi } from '@/features/legal-entities/api';
import { paymentRunIssuesFrom, paymentRunsApi, type PaymentRun, type PaymentRunIssue, type PaymentRunStatus } from './api';
import { invalidateFinanceFigures } from './financeQueryKeys';

const inputCls =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const RUNS_KEY = ['finance', 'payment-runs'] as const;

function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
      return (detail as { message: string }).message;
    }
  }
  return err instanceof Error ? err.message : String(err);
}

export function runStatusLabel(t: TFunction, status: PaymentRunStatus): string {
  switch (status) {
    case 'draft':
      return t('finance.payrun_status_draft', { defaultValue: 'Draft' });
    case 'approved':
      return t('finance.payrun_status_approved', { defaultValue: 'Approved' });
    case 'executed':
      return t('finance.payrun_status_executed', { defaultValue: 'Paid' });
    default:
      return t('finance.payrun_status_cancelled', { defaultValue: 'Cancelled' });
  }
}

function statusVariant(status: PaymentRunStatus): 'neutral' | 'blue' | 'success' | 'warning' {
  if (status === 'approved') return 'blue';
  if (status === 'executed') return 'success';
  if (status === 'cancelled') return 'warning';
  return 'neutral';
}

/** Findings of a run: errors first, each naming its invoice. */
function IssueList({ issues }: { issues: PaymentRunIssue[] }) {
  if (issues.length === 0) return null;
  const ordered = [...issues].sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'error' ? -1 : 1));
  return (
    <ul className="space-y-1.5" data-testid="payrun-issues">
      {ordered.map((issue, idx) => (
        <li
          key={`${issue.code}-${issue.item_id ?? idx}`}
          className={clsx(
            'flex items-start gap-2 rounded-lg px-3 py-2 text-sm',
            issue.severity === 'error'
              ? 'bg-semantic-error/10 text-semantic-error'
              : 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
          )}
        >
          {issue.severity === 'error' ? (
            <XCircle size={15} className="mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          )}
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  );
}

/** Amount input of one draft item; saves on blur when it changed. */
function AmountCell({
  value,
  disabled,
  onSave,
  label,
}: {
  value: string;
  disabled: boolean;
  onSave: (amount: string) => void;
  label: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <input
      aria-label={label}
      inputMode="decimal"
      value={draft}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        const next = draft.trim().replace(',', '.');
        if (next && next !== value) onSave(next);
        else setDraft(value);
      }}
      className={clsx(inputCls, 'h-8 w-28 text-right tabular-nums')}
    />
  );
}

/** One run: its items, its findings and what can be done with it next. */
function RunDetail({ runId }: { runId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [refused, setRefused] = useState<PaymentRunIssue[] | null>(null);

  const runQ = useQuery({ queryKey: [...RUNS_KEY, runId], queryFn: () => paymentRunsApi.get(runId) });

  const settle = (run: PaymentRun) => {
    qc.setQueryData([...RUNS_KEY, runId], run);
    qc.invalidateQueries({ queryKey: RUNS_KEY, exact: true });
    setRefused(null);
  };
  const fail = (err: unknown) => {
    const issues = err instanceof ApiError ? paymentRunIssuesFrom(err.body) : [];
    setRefused(issues.length ? issues : null);
    addToast({ type: 'error', title: t('finance.payrun_action_failed', { defaultValue: 'The run was not changed' }), message: errorText(err) });
  };

  const updateItem = useMutation({
    mutationFn: ({ itemId, amount }: { itemId: string; amount: string }) =>
      paymentRunsApi.updateItem(runId, itemId, amount),
    onSuccess: settle,
    onError: (err) => {
      fail(err);
      runQ.refetch();
    },
  });
  const removeItem = useMutation({
    mutationFn: (itemId: string) => paymentRunsApi.removeItem(runId, itemId),
    onSuccess: settle,
    onError: fail,
  });
  const approve = useMutation({ mutationFn: () => paymentRunsApi.approve(runId), onSuccess: settle, onError: fail });
  const execute = useMutation({
    mutationFn: () => paymentRunsApi.execute(runId),
    onSuccess: (run) => {
      settle(run);
      invalidateFinanceFigures(qc);
      addToast({
        type: 'success',
        title: t('finance.payrun_executed_toast', {
          defaultValue: 'Payments recorded: {{n}}',
          n: run.item_count,
        }),
      });
    },
    onError: fail,
  });
  const cancel = useMutation({ mutationFn: () => paymentRunsApi.cancel(runId), onSuccess: settle, onError: fail });

  if (runQ.isError) return <RecoveryCard error={runQ.error} onRetry={() => runQ.refetch()} />;
  const run = runQ.data;
  if (!run) return <SkeletonTable rows={4} columns={6} />;

  const draft = run.status === 'draft';
  const busy = updateItem.isPending || removeItem.isPending || approve.isPending || execute.isPending || cancel.isPending;
  const issues = refused ?? run.issues;
  const blocked = issues.some((i) => i.severity === 'error');
  const itemIssue = (itemId: string) => issues.find((i) => i.item_id === itemId && i.severity === 'error');

  return (
    <Card padding="none" className="space-y-4 p-4" data-testid="payrun-detail">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-mono text-base font-semibold text-content-primary">{run.run_number}</h3>
            <Badge variant={statusVariant(run.status)} size="sm">
              {runStatusLabel(t, run.status)}
            </Badge>
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-content-secondary">
            <span>{run.legal_entity_name || t('finance.ageing_no_entity', { defaultValue: 'No legal entity' })}</span>
            <span aria-hidden>·</span>
            <span>{t('finance.payrun_pay_on', { defaultValue: 'Pay on' })}</span>
            <DateDisplay value={run.payment_date} className="font-medium" />
            <span aria-hidden>·</span>
            <span>{t('finance.payrun_due_by', { defaultValue: 'Due by' })}</span>
            <DateDisplay value={run.due_by} />
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('finance.payrun_total', { defaultValue: 'Total to pay' })}
          </p>
          <p className="text-lg font-semibold tabular-nums text-content-primary">
            <MoneyDisplay amount={run.total} currency={run.currency_code || undefined} />
          </p>
        </div>
      </div>

      <IssueList issues={issues} />

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
              <th className="px-3 py-2 font-medium">{t('finance.ageing_col_invoice', { defaultValue: 'Invoice' })}</th>
              <th className="px-3 py-2 font-medium">
                {t('finance.ageing_col_counterparty', { defaultValue: 'Counterparty' })}
              </th>
              <th className="px-3 py-2 font-medium">{t('finance.payrun_col_project', { defaultValue: 'Project' })}</th>
              <th className="px-3 py-2 font-medium">{t('finance.ageing_col_due_date', { defaultValue: 'Due date' })}</th>
              <th className="px-3 py-2 text-right font-medium">
                {t('finance.payrun_col_open', { defaultValue: 'Open when proposed' })}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('finance.payrun_col_amount', { defaultValue: 'To pay' })}
              </th>
              {draft && <th className="px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {run.items.map((item) => (
              <tr
                key={item.id}
                className={clsx(
                  'border-b border-border/60 last:border-0',
                  itemIssue(item.id) && 'bg-semantic-error/5',
                )}
              >
                <td className="px-3 py-2 font-mono text-content-primary">{item.invoice_number}</td>
                <td className="px-3 py-2 text-content-primary">
                  {item.counterparty_name ||
                    t('finance.retention_unnamed', { defaultValue: 'Unspecified counterparty' })}
                </td>
                <td className="px-3 py-2 text-content-secondary">{item.project_name ?? '-'}</td>
                <td className="px-3 py-2 text-content-secondary">
                  {item.due_date ? <DateDisplay value={item.due_date} /> : '-'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                  <MoneyDisplay amount={item.open_at_proposal} currency={run.currency_code || undefined} />
                </td>
                <td className="px-3 py-2 text-right">
                  {draft ? (
                    <AmountCell
                      value={item.amount}
                      disabled={busy}
                      label={t('finance.payrun_amount_for', {
                        defaultValue: 'Amount to pay on {{invoice}}',
                        invoice: item.invoice_number,
                      })}
                      onSave={(amount) => updateItem.mutate({ itemId: item.id, amount })}
                    />
                  ) : (
                    <span className="font-medium tabular-nums text-content-primary">
                      <MoneyDisplay amount={item.amount} currency={run.currency_code || undefined} />
                    </span>
                  )}
                </td>
                {draft && (
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      disabled={busy || run.items.length <= 1}
                      onClick={() => removeItem.mutate(item.id)}
                      aria-label={t('finance.payrun_remove_item', {
                        defaultValue: 'Take {{invoice}} out of the run',
                        invoice: item.invoice_number,
                      })}
                      className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error disabled:opacity-40"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {draft && (
          <Button size="sm" disabled={busy || blocked} loading={approve.isPending} onClick={() => approve.mutate()}>
            {t('finance.payrun_approve', { defaultValue: 'Approve run' })}
          </Button>
        )}
        {run.status === 'approved' && (
          <Button
            size="sm"
            disabled={busy || blocked}
            loading={execute.isPending}
            onClick={async () => {
              const ok = await confirm({
                title: t('finance.payrun_execute_title', { defaultValue: 'Record these payments?' }),
                message: t('finance.payrun_execute_message', {
                  defaultValue:
                    'One payment per invoice is recorded, dated the payment date of the run. Send the bank file to your bank as well: the platform does not move money.',
                }),
                confirmLabel: t('finance.payrun_execute', { defaultValue: 'Record payments' }),
                variant: 'warning',
              });
              if (ok) execute.mutate();
            }}
          >
            {t('finance.payrun_execute', { defaultValue: 'Record payments' })}
          </Button>
        )}
        <Button
          size="sm"
          variant="secondary"
          icon={<Download size={14} />}
          onClick={() =>
            paymentRunsApi.downloadBankFile(run).catch((err: unknown) =>
              addToast({
                type: 'error',
                title: t('finance.payrun_download_failed', { defaultValue: 'The bank file could not be downloaded' }),
                message: errorText(err),
              }),
            )
          }
        >
          {t('finance.payrun_bank_file', { defaultValue: 'Bank file (CSV)' })}
        </Button>
        {(draft || run.status === 'approved') && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={async () => {
              const ok = await confirm({
                title: t('finance.payrun_cancel_title', { defaultValue: 'Cancel this run?' }),
                message: t('finance.payrun_cancel_message', {
                  defaultValue: 'Nothing is paid, and its invoices can go into another run.',
                }),
                confirmLabel: t('finance.payrun_cancel', { defaultValue: 'Cancel run' }),
              });
              if (ok) cancel.mutate();
            }}
          >
            {t('finance.payrun_cancel', { defaultValue: 'Cancel run' })}
          </Button>
        )}
      </div>
      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}

/**
 * Payment runs: the approved supplier invoices of one legal entity, in one
 * currency, that fall due by a date, paid together. The server proposes each
 * invoice for what is still open on it and checks the run again before it is
 * approved and before the payments are recorded; nothing is paid without a
 * person approving it.
 */
export function PaymentRunsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const today = todayLocalISO();

  const entitiesQ = useQuery({
    queryKey: ['legal-entities', 'list', 'payment-runs'],
    queryFn: () => legalEntitiesApi.list(false),
    staleTime: 5 * 60_000,
  });
  const projectEntityQ = useQuery({
    queryKey: ['legal-entities', 'project', projectId],
    queryFn: () => legalEntitiesApi.projectEntity(projectId),
    staleTime: 5 * 60_000,
  });
  const entities = entitiesQ.data?.items ?? [];

  const [entityId, setEntityId] = useState<string | null>(null);
  const [currency, setCurrency] = useState<string | null>(null);
  const [payOn, setPayOn] = useState(today);
  const [dueBy, setDueBy] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  // Start from the entity that owns the active project and its currency.
  const projectEntity = projectEntityQ.data?.legal_entity ?? null;
  const effectiveEntityId = entityId ?? projectEntity?.id ?? '';
  const chosenEntity = entities.find((e) => e.id === effectiveEntityId) ?? projectEntity;
  const effectiveCurrency = currency ?? chosenEntity?.functional_currency ?? '';

  const runsQ = useQuery({ queryKey: RUNS_KEY, queryFn: () => paymentRunsApi.list() });

  const create = useMutation({
    mutationFn: () =>
      paymentRunsApi.create({
        legal_entity_id: effectiveEntityId || null,
        currency_code: effectiveCurrency.trim().toUpperCase(),
        payment_date: payOn,
        due_by: dueBy || undefined,
      }),
    onSuccess: (run) => {
      qc.setQueryData([...RUNS_KEY, run.id], run);
      qc.invalidateQueries({ queryKey: RUNS_KEY, exact: true });
      setSelected(run.id);
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('finance.payrun_create_failed', { defaultValue: 'No run was drawn up' }),
        message: errorText(err),
      }),
  });

  const runs = runsQ.data?.items ?? [];
  const canCreate = /^[A-Za-z]{3}$/.test(effectiveCurrency.trim()) && !!payOn && !create.isPending;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-oe-blue/15 bg-oe-blue/[0.03] p-3">
        <p className="text-sm text-content-secondary">
          {t('finance.payrun_subtitle', {
            defaultValue:
              'Pay suppliers in one batch. A run gathers the approved supplier invoices of one legal entity, in one currency, that fall due by a date, each for what is still open on it. Edit the amounts, approve the run, then record the payments and send the bank file to your bank.',
          })}
        </p>
      </div>

      {/* Draw up */}
      <Card padding="none" className="p-4">
        <div className="flex flex-wrap items-end gap-3">
          {entities.length > 0 && (
            <label className="flex flex-col gap-1">
              <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {t('finance.ageing_entity', { defaultValue: 'Legal entity' })}
              </span>
              <select
                value={effectiveEntityId}
                onChange={(e) => {
                  setEntityId(e.target.value);
                  setCurrency(null);
                }}
                className={clsx(inputCls, 'max-w-[16rem]')}
              >
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.code ? `${entity.code} · ${entity.name}` : entity.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.payrun_currency', { defaultValue: 'Currency' })}
            </span>
            <input
              value={effectiveCurrency}
              maxLength={3}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              className={clsx(inputCls, 'w-20 font-mono uppercase')}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.payrun_pay_on', { defaultValue: 'Pay on' })}
            </span>
            <input type="date" value={payOn} onChange={(e) => setPayOn(e.target.value)} className={inputCls} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.payrun_due_by', { defaultValue: 'Due by' })}
            </span>
            <input
              type="date"
              value={dueBy}
              placeholder={payOn}
              onChange={(e) => setDueBy(e.target.value)}
              className={inputCls}
            />
          </label>
          <Button disabled={!canCreate} loading={create.isPending} onClick={() => create.mutate()}>
            {t('finance.payrun_create', { defaultValue: 'Draw up run' })}
          </Button>
        </div>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('finance.payrun_create_hint', {
            defaultValue:
              'Invoices due by the date are proposed; leave it empty to take what is due by the payment date. Invoices already in an open run are left out.',
          })}
        </p>
      </Card>

      {runsQ.isError && isForbidden(runsQ.error) ? (
        <EmptyState
          icon={<Lock size={26} strokeWidth={1.5} />}
          title={t('finance.retention_forbidden_title', { defaultValue: 'Finance access required' })}
          description={t('finance.payrun_forbidden_desc', {
            defaultValue:
              'You do not have permission to read finance data, so payment runs cannot be shown. Ask an administrator to grant the finance read role.',
          })}
        />
      ) : runsQ.isError ? (
        <RecoveryCard error={runsQ.error} onRetry={() => runsQ.refetch()} />
      ) : !runsQ.data ? (
        <SkeletonTable rows={4} columns={6} />
      ) : runs.length === 0 && !selected ? (
        <EmptyState
          icon={<Banknote size={26} strokeWidth={1.5} />}
          title={t('finance.payrun_empty_title', { defaultValue: 'No payment runs yet' })}
          description={t('finance.payrun_empty_desc', {
            defaultValue: 'Draw up the first run above. It stays a draft until someone approves it.',
          })}
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <Card padding="none" className="overflow-hidden">
            <ul className="divide-y divide-border/60">
              {runs.map((run) => (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(run.id)}
                    aria-current={selected === run.id ? 'true' : undefined}
                    className={clsx(
                      'flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-surface-secondary/50',
                      selected === run.id && 'bg-oe-blue/[0.06]',
                    )}
                  >
                    <span>
                      <span className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium text-content-primary">{run.run_number}</span>
                        <Badge variant={statusVariant(run.status)} size="sm">
                          {runStatusLabel(t, run.status)}
                        </Badge>
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-2xs text-content-tertiary">
                        <DateDisplay value={run.payment_date} />
                        <span>
                          {t('finance.ageing_invoice_count', { defaultValue: 'Invoices: {{n}}', n: run.item_count })}
                        </span>
                      </span>
                    </span>
                    <span className="text-sm font-medium tabular-nums text-content-primary">
                      <MoneyDisplay amount={run.total} currency={run.currency_code || undefined} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {selected ? (
            <RunDetail key={selected} runId={selected} />
          ) : (
            <p className="self-center text-sm text-content-tertiary">
              {t('finance.payrun_pick', { defaultValue: 'Pick a run to see its invoices.' })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
